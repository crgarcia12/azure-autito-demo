from __future__ import annotations

import json
import secrets
import uuid
from datetime import UTC, datetime, timedelta

from fleet.fabric import FabricData
from tools.cloud import Cloud, FABRIC, ROOT, load_state, save_state
from tools.deploy import app_path
from tools.fabric_provision import part


def identifier(name: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, "caldova-drive-impact/" + name))


def arguments(**values):
    return [{"name": key, "type": "string", "value": value} for key, value in values.items()]


def main():
    cloud, state = Cloud(), load_state()
    data = FabricData()
    for command in (ROOT / "fabric" / "insurance.kql").read_text(encoding="utf-8").split("\n\n"):
        if command.strip():
            data.client.execute_mgmt(data.database, command.strip())
    schema = data.query(".show table VehicleImpacts cslschema")[0]["Schema"]
    names = [item.strip().split(":")[0].strip("[]'() ") for item in schema.split(",")]
    mapping = [{"column": name, "Properties": {"Path": f"$.{name}"}} for name in names]
    data.client.execute_mgmt(data.database, f".create-or-alter table VehicleImpacts ingestion json mapping 'VehicleImpactsJson' '{json.dumps(mapping)}'")
    state["impact_schema_ready"] = True
    save_state(state)
    endpoint = app_path(state) + "/config/appsettings"
    settings = cloud.request("POST", endpoint + "/list?api-version=2023-12-01")["properties"]
    secret = settings.get("FLEET_FABRIC_TRIGGER_SECRET") or secrets.token_urlsafe(32)
    settings["FLEET_FABRIC_TRIGGER_SECRET"] = secret
    cloud.request("PUT", endpoint + "?api-version=2023-12-01", {"properties": settings})
    connections = cloud.pages(FABRIC + "/connections")
    connection = next((item for item in connections if item.get("displayName") == "Caldova Incident Callback"), None)
    if connection is None:
        connection = cloud.request("POST", FABRIC + "/connections", {
            "connectivityType": "ShareableCloud", "displayName": "Caldova Incident Callback",
            "connectionDetails": {"type": "WebForPipeline", "creationMethod": "WebForPipeline.Contents",
                                  "parameters": [{"dataType": "Text", "name": "baseUrl", "value": state["appUrl"]}]},
            "privacyLevel": "Organizational",
            "credentialDetails": {"singleSignOnType": "None", "connectionEncryption": "NotEncrypted",
                                  "credentials": {"credentialType": "Anonymous"}},
        })
    state["impact_web_connection_id"] = connection["id"]
    save_state(state)
    pipeline_definition = {
        "properties": {
            "activities": [{
                "name": "Open detected vehicle incidents", "type": "WebActivity",
                "policy": {"timeout": "0.00:03:00", "retry": 2, "retryIntervalInSeconds": 30, "secureOutput": True, "secureInput": True},
                "typeProperties": {
                    "method": "POST", "relativeUrl": "/integrations/fabric/impacts",
                    "headers": {"Content-Type": "application/json", "X-Caldova-Fabric": secret},
                    "body": {"value": "@concat('{\"pipeline_run_id\":\"', pipeline().RunId, '\"}')", "type": "Expression"},
                },
                "externalReferences": {"connection": connection["id"]},
            }],
        },
    }
    pipeline = cloud.item(state["workspace_id"], "DataPipeline", "Caldova_Impact_Response",
                          definition={"parts": [part("pipeline-content.json", pipeline_definition)]})
    cloud.request("POST", f"{FABRIC}/workspaces/{state['workspace_id']}/dataPipelines/{pipeline['id']}/updateDefinition",
                  {"definition": {"parts": [part("pipeline-content.json", pipeline_definition)]}})
    state["impact_pipeline_id"] = pipeline["id"]
    save_state(state)
    container, source, event, rule, action = [identifier(name) for name in ("container", "source", "event", "rule", "action")]
    parent = {"targetUniqueIdentifier": container}
    entities = [
        {"uniqueIdentifier": container, "type": "container-v1", "payload": {"name": "Vehicle impact detection", "type": "kqlQueries"}},
        {"uniqueIdentifier": source, "type": "kqlSource-v1", "payload": {
            "name": "Suspected impacts in Eventhouse", "parentContainer": parent,
            "runSettings": {"executionIntervalInSeconds": 60},
            "query": {"queryString": "declare query_parameters(startTime:datetime, endTime:datetime); VehicleImpacts | where Timestamp > startTime and Timestamp <= endTime"},
            "eventhouseItem": {"itemId": state["database_id"], "workspaceId": state["workspace_id"], "itemType": "KustoDatabase"},
            "queryParameters": [
                {"name": "startTime", "type": "DURATION_START", "value": (datetime.now(UTC) - timedelta(minutes=2)).isoformat()},
                {"name": "endTime", "type": "DURATION_END", "value": datetime.now(UTC).isoformat()},
            ],
            "eventTimeSettings": {"timeFieldName": "Timestamp", "ingestionDelayInSeconds": 15, "timeZone": "UTC"},
            "metadata": {"workspaceId": state["workspace_id"], "measureName": "", "querySetId": "", "queryId": ""},
        }},
        {"uniqueIdentifier": event, "type": "timeSeriesView-v1", "payload": {
            "name": "Impact events", "parentContainer": parent,
            "definition": {"type": "Event", "instance": json.dumps({
                "templateId": "SourceEvent", "templateVersion": "1.2.4", "steps": [{
                    "name": "SourceEventStep", "id": identifier("select-source"),
                    "rows": [{"name": "SourceSelector", "kind": "SourceReference", "arguments": arguments(entityId=source)}],
                }],
            })},
        }},
        {"uniqueIdentifier": action, "type": "fabricItemAction-v1", "payload": {
            "name": "Open incident and customer notification", "parentContainer": parent,
            "fabricItem": {"itemId": pipeline["id"], "workspaceId": state["workspace_id"], "itemType": "Pipeline"},
            "jobType": "Pipeline",
        }},
        {"uniqueIdentifier": rule, "type": "timeSeriesView-v1", "payload": {
            "name": "Possible vehicle impact", "parentContainer": parent,
            "definition": {
                "type": "Rule", "settings": {"shouldRun": True, "shouldApplyRuleOnUpdate": False},
                "instance": json.dumps({
                    "templateId": "EventTrigger", "templateVersion": "1.2.4",
                    "steps": [
                        {"name": "FieldsDefaultsStep", "id": identifier("select-event"), "rows": [{
                            "name": "EventSelector", "kind": "Event",
                            "arguments": [{"name": "event", "kind": "EventReference", "type": "complex", "arguments": arguments(entityId=event)}],
                        }]},
                        *[{
                            "name": "EventDetectStep", "id": identifier(field),
                            "rows": [
                                {"name": "EventFieldSelector", "kind": "EventField", "arguments": arguments(fieldName=field)},
                                {"name": "NumberValueCondition", "kind": "NumberValueCondition", "arguments": [
                                    {"name": "op", "type": "string", "value": operator},
                                    {"name": "threshold", "type": "number", "value": threshold},
                                ]},
                            ],
                        } for field, operator, threshold in [
                            ("PeakAccelerationG", "IsGreaterThanOrEqualTo", 2.5),
                            ("DeltaVKmh", "IsGreaterThanOrEqualTo", 4.0),
                            ("SpeedAfterKmh", "IsLessThanOrEqualTo", 1.0),
                        ]],
                        {"name": "ActStep", "id": identifier("invoke-pipeline"), "rows": [{
                            "name": "FabricItemBinding", "kind": "FabricItemInvocation",
                            "arguments": arguments(workspaceId=state["workspace_id"], itemId=pipeline["id"], itemType="Pipeline",
                                                   jobType="Pipeline", fabricJobConnectionDocumentId=action) + [
                                {"name": "additionalInformation", "type": "array", "values": []},
                                {"name": "parameters", "type": "array", "values": []},
                            ],
                        }]},
                    ],
                }),
            },
        }},
    ]
    reflex = cloud.item(state["workspace_id"], "Reflex", "Caldova_Incident_Activator",
                        definition={"parts": [part("ReflexEntities.json", json.dumps(entities))]})
    cloud.request("POST", f"{FABRIC}/workspaces/{state['workspace_id']}/reflexes/{reflex['id']}/updateDefinition",
                  {"definition": {"parts": [part("ReflexEntities.json", json.dumps(entities))]}})
    state["impact_activator_id"] = reflex["id"]
    save_state(state)
    print("Fabric impact schema:", state["database_id"])
    print("Response pipeline:", pipeline["id"])
    print("Activator:", reflex["id"])


if __name__ == "__main__":
    main()
