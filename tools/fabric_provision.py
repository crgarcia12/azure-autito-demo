from __future__ import annotations

import base64
import json
import uuid

from tools.cloud import CONFIG, FABRIC, Cloud, load_state, save_state


def part(path: str, content: str | dict) -> dict:
    text = content if isinstance(content, str) else json.dumps(content)
    return {"path": path, "payload": base64.b64encode(text.encode()).decode(), "payloadType": "InlineBase64"}


def provision_data() -> None:
    cloud = Cloud()
    state = load_state()
    workspace = state["workspace_id"]
    eventhouse = cloud.item(
        workspace, "Eventhouse", "CaldovaFleet",
        description="Live UK rental vehicle telemetry and digital twin state.",
    )
    state["eventhouse_id"] = eventhouse["id"]
    save_state(state)
    databases = cloud.pages(f"{FABRIC}/workspaces/{workspace}/kqlDatabases")
    database = next(
        (db for db in databases if db["displayName"] == "CaldovaFleet"
         and db.get("properties", {}).get("parentEventhouseItemId") in {None, eventhouse["id"]}),
        None,
    )
    if database is None:
        database = cloud.request(
            "POST", f"{FABRIC}/workspaces/{workspace}/kqlDatabases",
            {"displayName": "CaldovaFleet", "creationPayload": {
                "databaseType": "ReadWrite", "parentEventhouseItemId": eventhouse["id"],
            }},
        )
    database = cloud.request(
        "GET", f"{FABRIC}/workspaces/{workspace}/kqlDatabases/{database['id']}"
    )
    props = database["properties"]
    state.update(
        database_id=database["id"], database_name=database["displayName"],
        query_service_uri=props["queryServiceUri"],
        ingestion_service_uri=props["ingestionServiceUri"],
    )
    save_state(state)
    lakehouse = cloud.item(
        workspace, "Lakehouse", "FleetIntelligence",
        description="Governed fleet entities, current state and daily mileage for Fabric IQ and Copilot.",
    )
    state["lakehouse_id"] = lakehouse["id"]
    save_state(state)
    assignments = cloud.pages(f"{FABRIC}/workspaces/{workspace}/roleAssignments")
    if state.get("appIdentity") and state["appIdentity"] not in {a["principal"]["id"] for a in assignments}:
        cloud.request(
            "POST", f"{FABRIC}/workspaces/{workspace}/roleAssignments",
            {"principal": {"id": state["appIdentity"], "type": "ServicePrincipal"}, "role": "Contributor"},
        )
    print(json.dumps({key: state[key] for key in (
        "workspace_id", "eventhouse_id", "database_id", "lakehouse_id",
        "query_service_uri", "ingestion_service_uri",
    )}, indent=2), flush=True)


if __name__ == "__main__":
    provision_data()
