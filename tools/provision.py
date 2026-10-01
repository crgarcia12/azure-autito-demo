from __future__ import annotations

import argparse
import uuid

from tools.cloud import ARM, CONFIG, FABRIC, GRAPH, ROOT, Cloud, az, load_state, save_state


def foundation() -> None:
    cloud = Cloud()
    state = load_state()
    groups = cloud.pages(
        f"{GRAPH}/groups?$filter=displayName eq '{CONFIG['fabric_security_group']}'"
    )
    group = groups[0] if groups else cloud.request(
        "POST",
        f"{GRAPH}/groups",
        {
            "displayName": CONFIG["fabric_security_group"],
            "mailEnabled": False,
            "mailNickname": "caldova-drive-fabric-iq",
            "securityEnabled": True,
        },
    )
    state["security_group_id"] = group["id"]
    save_state(state)
    members = cloud.pages(f"{GRAPH}/groups/{group['id']}/members")
    if CONFIG["admin_object_id"] not in {member["id"] for member in members}:
        cloud.request(
            "POST",
            f"{GRAPH}/groups/{group['id']}/members/$ref",
            {"@odata.id": f"{GRAPH}/directoryObjects/{CONFIG['admin_object_id']}"},
        )
    settings = cloud.request("GET", f"{FABRIC}/admin/tenantsettings")["tenantSettings"]
    ontology_setting = next(s for s in settings if s["settingName"] == "OntologyPreview")
    if not ontology_setting["enabled"] or (
        ontology_setting.get("enabledSecurityGroups")
        and group["id"] not in {
            g["graphId"] for g in ontology_setting["enabledSecurityGroups"]
        }
    ):
        scoped_groups = ontology_setting.get("enabledSecurityGroups") or []
        scoped_groups.append({"graphId": group["id"], "name": group["displayName"]})
        cloud.request(
            "POST",
            f"{FABRIC}/admin/tenantsettings/OntologyPreview/update",
            {
                "enabled": True,
                "enabledSecurityGroups": scoped_groups,
                "excludedSecurityGroups": ontology_setting.get("excludedSecurityGroups", []),
            },
        )
    workspaces = cloud.pages(f"{FABRIC}/workspaces")
    workspace = next(
        (w for w in workspaces if w["displayName"] == CONFIG["fabric_workspace_name"]), None
    )
    if not workspace:
        workspace = cloud.request(
            "POST",
            f"{FABRIC}/workspaces",
            {
                "displayName": CONFIG["fabric_workspace_name"],
                "description": "UK rental fleet digital twins, journeys and mileage intelligence.",
                "capacityId": CONFIG["fabric_capacity_id"],
            },
        )
    state["workspace_id"] = workspace["id"]
    save_state(state)
    application_name = "Caldova Drive - Fleet Agent"
    applications = cloud.pages(
        f"{GRAPH}/applications?$filter=displayName eq '{application_name}'"
    )
    application = applications[0] if applications else cloud.request(
        "POST",
        f"{GRAPH}/applications",
        {
            "displayName": application_name,
            "signInAudience": "AzureADMyOrg",
            "web": {
                "redirectUris": [
                    f"https://{CONFIG['resource_prefix']}.azurewebsites.net/.auth/login/aad/callback"
                ]
            },
        },
    )
    state["agent_app_id"] = application["appId"]
    state["agent_app_object_id"] = application["id"]
    principals = cloud.pages(
        f"{GRAPH}/servicePrincipals?$filter=appId eq '{application['appId']}'"
    )
    principal = principals[0] if principals else cloud.request(
        "POST", f"{GRAPH}/servicePrincipals", {"appId": application["appId"]}
    )
    state["agent_principal_id"] = principal["id"]
    save_state(state)
    if principal["id"] not in {member["id"] for member in members}:
        cloud.request(
            "POST",
            f"{GRAPH}/groups/{group['id']}/members/$ref",
            {"@odata.id": f"{GRAPH}/directoryObjects/{principal['id']}"},
        )
    assignments = cloud.pages(f"{FABRIC}/workspaces/{workspace['id']}/roleAssignments")
    if principal["id"] not in {a["principal"]["id"] for a in assignments}:
        cloud.request(
            "POST",
            f"{FABRIC}/workspaces/{workspace['id']}/roleAssignments",
            {"principal": {"id": principal["id"], "type": "ServicePrincipal"}, "role": "Contributor"},
        )
    print(f"Fabric workspace: {workspace['id']}", flush=True)
    print(f"Fabric IQ access group: {group['id']}", flush=True)
    print(f"Agent application: {application['appId']}", flush=True)
    az(
        "group", "create",
        "--name", CONFIG["resource_group"],
        "--location", CONFIG["location"],
        "--subscription", CONFIG["subscription_id"],
        "--tags", "project=caldova-drive", "purpose=demo",
    )
    deployment = az(
        "deployment", "group", "create",
        "--resource-group", CONFIG["resource_group"],
        "--subscription", CONFIG["subscription_id"],
        "--name", "caldova-drive-foundation",
        "--template-file", str(ROOT / "infra" / "main.bicep"),
        "--parameters",
        f"prefix={CONFIG['resource_prefix']}",
        f"location={CONFIG['location']}",
        f"tenantId={CONFIG['tenant_id']}",
        f"agentAppId={application['appId']}",
    )
    outputs = {k: v["value"] for k, v in deployment["properties"]["outputs"].items()}
    state.update(outputs)
    save_state(state)
    for scope, role in (
        (state["mapsId"], "Azure Maps Data Reader"),
        (state["storageId"], "Storage Blob Data Contributor"),
    ):
        az(
            "role", "assignment", "create",
            "--assignee-object-id", CONFIG["admin_object_id"],
            "--assignee-principal-type", "User",
            "--role", role, "--scope", scope,
            "--subscription", CONFIG["subscription_id"],
        )
    print(f"Application: {state['appUrl']}", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=["foundation"])
    parser.parse_args()
    foundation()
