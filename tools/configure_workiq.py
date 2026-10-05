from __future__ import annotations

import argparse
from datetime import UTC, datetime, timedelta
import json
import shutil
import subprocess
from urllib.parse import urlparse
import uuid

from cryptography.fernet import Fernet

from fleet.config import settings
from fleet.storage import StateStore
from fleet.workiq import FOUNDRY_SCOPE, WORK_IQ_SCOPE, WorkIQSession
from tools.cloud import ARM, CONFIG, GRAPH, ROOT, Cloud, load_state, save_state
from tools.deploy import app_path

RESOURCE_APP_ID = "fdcc1f02-fc51-4226-8753-f668596af7f7"
ASK_SCOPE_ID = "0b1715fd-f4bf-4c63-b16d-5be31f9847c2"
FOUNDRY_APP_ID = "18a66f5f-dbdf-4c17-9dd7-1634712a9cbe"
FOUNDRY_SCOPE_ID = "1a7925b5-f871-417a-9b8b-303f9f29fa10"


def provision(cloud: Cloud, state: dict) -> None:
    resources = cloud.pages(GRAPH + f"/servicePrincipals?$filter=appId eq '{RESOURCE_APP_ID}'")
    resource = resources[0] if resources else cloud.request("POST", GRAPH + "/servicePrincipals", {"appId": RESOURCE_APP_ID})
    if not state.get("workiq_app_id"):
        app = cloud.request("POST", GRAPH + "/applications", {
            "displayName": "Fleet Repair Agents - Work IQ", "signInAudience": "AzureADMyOrg",
            "isFallbackPublicClient": True, "publicClient": {"redirectUris": ["http://localhost"]},
            "requiredResourceAccess": [{"resourceAppId": RESOURCE_APP_ID, "resourceAccess": [{"id": ASK_SCOPE_ID, "type": "Scope"}]}],
        })
        state.update(workiq_app_id=app["appId"], workiq_app_object_id=app["id"])
        save_state(state)
    principals = cloud.pages(GRAPH + f"/servicePrincipals?$filter=appId eq '{state['workiq_app_id']}'")
    principal = principals[0] if principals else cloud.request("POST", GRAPH + "/servicePrincipals", {"appId": state["workiq_app_id"]})
    grants = cloud.pages(GRAPH + f"/oauth2PermissionGrants?$filter=clientId eq '{principal['id']}'")
    if not any(
        grant["resourceId"] == resource["id"] and grant.get("principalId") == CONFIG["admin_object_id"]
        and "WorkIQAgent.Ask" in grant["scope"].split() for grant in grants
    ):
        cloud.request("POST", GRAPH + "/oauth2PermissionGrants", {
            "clientId": principal["id"], "resourceId": resource["id"], "consentType": "Principal",
            "principalId": CONFIG["admin_object_id"], "scope": "WorkIQAgent.Ask",
        })
    app = cloud.request("GET", GRAPH + "/applications/" + state["workiq_app_object_id"] + "?$select=requiredResourceAccess")
    required = app["requiredResourceAccess"]
    if not any(entry["resourceAppId"] == FOUNDRY_APP_ID for entry in required):
        required.append({"resourceAppId": FOUNDRY_APP_ID, "resourceAccess": [{"id": FOUNDRY_SCOPE_ID, "type": "Scope"}]})
        cloud.request("PATCH", GRAPH + "/applications/" + state["workiq_app_object_id"], {"requiredResourceAccess": required})
    foundry = cloud.pages(GRAPH + f"/servicePrincipals?$filter=appId eq '{FOUNDRY_APP_ID}'")[0]
    if not any(grant["resourceId"] == foundry["id"] and grant.get("principalId") == CONFIG["admin_object_id"] for grant in grants):
        cloud.request("POST", GRAPH + "/oauth2PermissionGrants", {
            "clientId": principal["id"], "resourceId": foundry["id"], "consentType": "Principal",
            "principalId": CONFIG["admin_object_id"], "scope": "user_impersonation",
        })
    print("Work IQ consent is scoped to the configured Caldova operator.", flush=True)


def native_connection(cloud: Cloud, state: dict) -> None:
    from msal_extensions import FilePersistenceWithDataProtection
    executable = shutil.which("azd.exe") or shutil.which("azd")
    if not executable:
        raise RuntimeError("Azure Developer CLI is required to create the native OAuth connection.")
    connection_id = state["foundry_project_id"] + "/connections/work-iq"
    existing = cloud.request("GET", ARM + state["foundry_project_id"] + "/connections?api-version=2025-06-01")["value"]
    if not any(value["id"].casefold() == connection_id.casefold() for value in existing):
        secret_store = FilePersistenceWithDataProtection(str(ROOT / ".local" / "workiq-connector-secret.bin"))
        if (ROOT / ".local" / "workiq-connector-secret.bin").exists():
            secret = secret_store.load()
        else:
            password = cloud.request("POST", GRAPH + "/applications/" + state["workiq_app_object_id"] + "/addPassword", {
                "passwordCredential": {
                    "displayName": "Foundry native Work IQ OAuth",
                    "endDateTime": (datetime.now(UTC) + timedelta(days=180)).isoformat(),
                },
            })
            secret = password["secretText"]
            secret_store.save(secret)
            save_state({"workiq_connector_credential_id": password["keyId"]})
        authority = "https://login.microsoftonline.com/" + CONFIG["tenant_id"] + "/oauth2/v2.0/"
        command = [
            executable, "ai", "connection", "create", "work-iq",
            "--project-endpoint", state["foundry_project_endpoint"], "--kind", "remote-tool",
            "--target", "https://workiq.svc.cloud.microsoft/mcp", "--auth-type", "oauth2",
            "--client-id", state["workiq_app_id"], "--client-secret", secret,
            "--authorization-url", authority + "authorize", "--token-url", authority + "token",
            "--refresh-url", authority + "token", "--scopes", WORK_IQ_SCOPE, "--scopes", "offline_access",
            "--no-prompt", "--output", "json",
        ]
        result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=180, check=False)
        if result.returncode:
            raise RuntimeError("Native Work IQ connection creation failed: " + (result.stderr + result.stdout).replace(secret, "<redacted>")[-1600:])
    connection = cloud.request("GET", ARM + connection_id + "?api-version=2025-06-01")
    properties = connection["properties"]
    redirect = properties.get("redirectUrl", "")
    callback = urlparse(redirect)
    if callback.scheme != "https" or callback.hostname != "global.consent.azure-apim.net" or not callback.path.startswith("/redirect/"):
        raise RuntimeError("Foundry did not return its expected native OAuth callback.")
    app = cloud.request("GET", GRAPH + "/applications/" + state["workiq_app_object_id"] + "?$select=web")
    redirects = app["web"].get("redirectUris", [])
    if redirect not in redirects:
        cloud.request("PATCH", GRAPH + "/applications/" + state["workiq_app_object_id"], {
            "web": {"redirectUris": [*redirects, redirect]},
        })
    metadata = properties.get("metadata", {})
    save_state({"workiq_connection_id": connection_id, "workiq_connection_name": connection["name"]})
    print(json.dumps({
        "id": connection_id, "name": connection["name"], "target": properties.get("target"),
        "auth_type": properties.get("authType"), "metadata_keys": list(metadata),
        "redirect_url": redirect,
        "redirect_fields": {key: value for key, value in metadata.items() if "redirect" in key.casefold()},
    }, indent=2), flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Configure the real delegated Work IQ connection for repair-agent tools.")
    parser.add_argument("action", choices=["provision", "login", "deploy", "connect"])
    args = parser.parse_args()
    cloud, state = Cloud(), load_state()
    if args.action == "provision":
        provision(cloud, state)
        return
    if args.action == "connect":
        native_connection(cloud, state)
        return
    session = WorkIQSession(StateStore(), settings())
    if args.action == "login":
        flow = session.app.initiate_device_flow(scopes=[WORK_IQ_SCOPE])
        if "user_code" not in flow:
            raise RuntimeError(flow.get("error_description", "Work IQ sign-in could not be started."))
        print("Use only the Caldova Work 2 profile and " + CONFIG["report_recipient"], flush=True)
        print(flow["message"], flush=True)
        result = session.app.acquire_token_by_device_flow(flow)
        claims = result.get("id_token_claims", {})
        if claims.get("tid") != CONFIG["tenant_id"] or claims.get("oid") != CONFIG["admin_object_id"]:
            raise RuntimeError("The sign-in did not authenticate the configured Caldova operator.")
        session.token()
        session.token(FOUNDRY_SCOPE)
        session.token(FOUNDRY_SCOPE)
        print("Caldova Work IQ sign-in confirmed.", flush=True)
        return
    session.token()
    key = Fernet.generate_key()
    app_settings = cloud.request("POST", app_path(state) + "/config/appsettings/list?api-version=2023-12-01")["properties"]
    app_settings.update({
        "FLEET_WORKIQ_CACHE_KEY": key.decode(),
        "FLEET_WORKIQ_CACHE_SEED": Fernet(key).encrypt(session.cache.serialize().encode()).decode(),
        "FLEET_WORKIQ_CACHE_VERSION": str(uuid.uuid4()),
    })
    cloud.request("PUT", app_path(state) + "/config/appsettings?api-version=2023-12-01", {"properties": app_settings})
    print("Encrypted delegated connection deployed to protected App Service settings.", flush=True)


if __name__ == "__main__":
    main()
