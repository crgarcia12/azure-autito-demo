from __future__ import annotations

import uuid

from tools.cloud import Cloud, GRAPH, load_state
from tools.deploy import app_path


def main():
    cloud, state = Cloud(), load_state()
    application = cloud.request("GET", f"{GRAPH}/applications/{state['agent_app_object_id']}?$select=api,identifierUris")
    api = application.get("api") or {}
    scopes = api.get("oauth2PermissionScopes") or []
    permission = next((scope for scope in scopes if scope["value"] == "access_as_user"), None)
    if permission is None:
        permission = {
            "id": str(uuid.uuid5(uuid.NAMESPACE_URL, state["agent_app_id"] + "/access_as_user")),
            "value": "access_as_user", "type": "Admin", "isEnabled": True,
            "adminConsentDisplayName": "Access the Caldova fleet workspace as the signed-in operator",
            "adminConsentDescription": "Call Caldova fleet APIs as the signed-in user. The service still restricts access to its configured Caldova operator.",
        }
        scopes.append(permission)
    clients = api.get("preAuthorizedApplications") or []
    cli_id = "04b07795-8ddb-461a-bbee-02f9e1bf7b46"
    if not any(client["appId"] == cli_id for client in clients):
        clients.append({"appId": cli_id, "delegatedPermissionIds": [permission["id"]]})
    cloud.request("PATCH", f"{GRAPH}/applications/{state['agent_app_object_id']}", {
        "identifierUris": list(dict.fromkeys([*(application.get("identifierUris") or []), f"api://{state['agent_app_id']}"])),
        "api": {"requestedAccessTokenVersion": 2, "oauth2PermissionScopes": scopes},
    })
    cloud.request("PATCH", f"{GRAPH}/applications/{state['agent_app_object_id']}", {
        "api": {"preAuthorizedApplications": clients},
    })
    print("Configured scoped, user-delegated Azure CLI access to the Caldova API. The operator allowlist remains enforced.")


if __name__ == "__main__":
    main()
