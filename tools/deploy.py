from __future__ import annotations

import argparse
from datetime import UTC, datetime, timedelta
import io
import json
import hashlib
import time
import uuid
import zipfile

import httpx
from azure.identity import ClientSecretCredential
from PIL import Image, ImageDraw

from fleet.storage import StateStore
from tools.cloud import ARM, CONFIG, GRAPH, ROOT, Cloud, az, load_state, save_state


def app_path(state: dict) -> str:
    return f"{ARM}/subscriptions/{CONFIG['subscription_id']}/resourceGroups/{CONFIG['resource_group']}/providers/Microsoft.Web/sites/{state['appName']}"


def configure(cloud: Cloud, state: dict, *, prebuilt: bool = False) -> None:
    cloud.request("PATCH", f"{GRAPH}/applications/{state['agent_app_object_id']}", {
        "web": {
            "redirectUris": [state["appUrl"] + "/.auth/login/aad/callback"],
            "implicitGrantSettings": {"enableAccessTokenIssuance": False, "enableIdTokenIssuance": True},
        },
    })
    role_id = str(uuid.uuid5(uuid.NAMESPACE_URL, CONFIG["subscription_id"] + "/caldova-capacity-wakeup"))
    role_path = f"/subscriptions/{CONFIG['subscription_id']}/providers/Microsoft.Authorization/roleDefinitions/{role_id}"
    cloud.request("PUT", ARM + role_path + "?api-version=2022-04-01", {"properties": {
        "roleName": "Caldova Drive - Resume Fabric",
        "description": "Read and resume the approved demo capacity before the daily fleet briefing.",
        "type": "CustomRole",
        "permissions": [{"actions": ["Microsoft.Fabric/capacities/read", "Microsoft.Fabric/capacities/resume/action"], "notActions": [], "dataActions": [], "notDataActions": []}],
        "assignableScopes": [f"/subscriptions/{CONFIG['subscription_id']}/resourceGroups/rg-apollo-agents-demo"],
    }})
    assignment = str(uuid.uuid5(uuid.NAMESPACE_URL, role_id + state["appIdentity"]))
    cloud.request(
        "PUT", ARM + CONFIG["fabric_capacity_resource_id"] + f"/providers/Microsoft.Authorization/roleAssignments/{assignment}?api-version=2022-04-01",
        {"properties": {"roleDefinitionId": role_path, "principalId": state["appIdentity"], "principalType": "ServicePrincipal"}},
    )
    path = app_path(state)
    settings = cloud.request("POST", path + "/config/appsettings/list?api-version=2023-12-01")["properties"]
    secret = settings.get("FLEET_AGENT_SECRET")
    if not secret:
        credential = cloud.request(
            "POST", f"{GRAPH}/applications/{state['agent_app_object_id']}/addPassword",
            {"passwordCredential": {
                "displayName": "Caldova Drive App Service",
                "endDateTime": (datetime.now(UTC) + timedelta(days=180)).isoformat(),
            }},
        )
        secret = credential["secretText"]
        state["credential_expires"] = credential["endDateTime"]
    settings.update({
        "FLEET_DEPLOYMENT": json.dumps(state), "FLEET_AGENT_SECRET": secret,
        "MICROSOFT_PROVIDER_AUTHENTICATION_SECRET": secret,
        "SCM_DO_BUILD_DURING_DEPLOYMENT": "false" if prebuilt else "true",
        "ENABLE_ORYX_BUILD": "false" if prebuilt else "true",
        "WEBSITES_CONTAINER_START_TIME_LIMIT": "900",
        "PORT": "8000", "FLEET_WORKER_ENABLED": "true",
        "FLEET_REPAIR_WORKER_ENABLED": "true" if state.get("impact_schema_ready") else "false",
    })
    cloud.request("PUT", path + "/config/appsettings?api-version=2023-12-01", {"properties": settings})
    if prebuilt:
        cloud.request("PATCH", path + "/config/web?api-version=2023-12-01", {"properties": {
            "appCommandLine": "PYTHONPATH=/home/site/wwwroot/.python_packages/lib/site-packages python -m fleet.web",
        }})
    cloud.request("PUT", path + "/config/authsettingsV2?api-version=2023-12-01", {"properties": {
        "platform": {"enabled": True, "runtimeVersion": "~1"},
        "globalValidation": {
            "requireAuthentication": True, "unauthenticatedClientAction": "RedirectToLoginPage",
            "redirectToProvider": "azureactivedirectory",
            "excludedPaths": [
                "/api/messages", "/health/live", "/privacy", "/terms", "/integrations/fabric/impacts",
                "/report/*", "/customer/*", "/static/report.css", "/static/report.js", "/static/mark.svg",
            ],
        },
        "identityProviders": {"azureActiveDirectory": {
            "enabled": True,
            "registration": {
                "clientId": state["agent_app_id"],
                "clientSecretSettingName": "MICROSOFT_PROVIDER_AUTHENTICATION_SECRET",
                "openIdIssuer": f"https://login.microsoftonline.com/{CONFIG['tenant_id']}/v2.0",
            },
            "login": {"loginParameters": ["scope=openid profile email"]},
            "validation": {"allowedAudiences": [state["agent_app_id"]]},
        }},
        "login": {"tokenStore": {"enabled": False}},
        "httpSettings": {"requireHttps": True},
    }})
    save_state(state)
    print("Single-tenant application authentication configured; credentials remain in Azure App Service.", flush=True)


def deployment_zip(*, prebuilt: bool = False, code_only: bool = False) -> str:
    destination = ROOT / ".local" / "caldova-drive.zip"
    digest = hashlib.sha256()
    with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as archive:
        for directory in ("fleet", "static", "fabric"):
            for path in (ROOT / directory).rglob("*"):
                if path.is_file() and "__pycache__" not in path.parts:
                    archive.write(path, path.relative_to(ROOT).as_posix())
                    digest.update(path.relative_to(ROOT).as_posix().encode())
                    digest.update(path.read_bytes())
        for name in ("requirements.txt", "demo.config.json", "insurance.config.json"):
            archive.write(ROOT / name, name)
            digest.update(name.encode())
            digest.update((ROOT / name).read_bytes())
        archive.writestr("bootstrap.json", json.dumps(StateStore().export(), allow_nan=False))
        archive.writestr(".build.json", json.dumps({"id": digest.hexdigest()[:16]}))
        (ROOT / ".local" / "build-id.txt").write_text(digest.hexdigest()[:16], encoding="utf-8")
        if prebuilt:
            packages = ROOT / ".local" / "linux-packages"
            if not packages.is_dir() or not (packages / "aiohttp").is_dir():
                raise RuntimeError("Restore the Linux runtime dependencies under .local\\linux-packages first.")
            for path in packages.rglob("*"):
                if path.is_file() and "__pycache__" not in path.parts:
                    if code_only:
                        top = path.relative_to(packages).parts[0]
                        if top not in {"PIL", "pillow.libs", "reportlab"} and not top.startswith(("pillow-", "reportlab-")):
                            continue
                    archive.write(path, ".python_packages/lib/site-packages/" + path.relative_to(packages).as_posix())
    return str(destination)


def icon(size: int, *, outline: bool = False) -> bytes:
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0) if outline else "#14271f")
    draw = ImageDraw.Draw(image)
    margin = size // 5
    draw.rounded_rectangle((margin, margin, size - margin, size - margin), radius=size // 6, fill="white" if outline else "#b5edba")
    ink = "#14271f" if not outline else (0, 0, 0, 0)
    draw.arc((size * .31, size * .30, size * .68, size * .70), 40, 320, fill=ink, width=max(2, size // 14))
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def teams_package(state: dict) -> bytes:
    manifest = {
        "$schema": "https://developer.microsoft.com/json-schemas/teams/v1.23/MicrosoftTeams.schema.json",
        "manifestVersion": "1.23", "version": "1.0.0", "id": state["agent_app_id"],
        "developer": {
            "name": "Caldova", "websiteUrl": state["appUrl"],
            "privacyUrl": state["appUrl"] + "/privacy", "termsOfUseUrl": state["appUrl"] + "/terms",
        },
        "icons": {"color": "color.png", "outline": "outline.png"},
        "name": {"short": "Caldova Drive", "full": "Caldova Drive Fleet Intelligence"},
        "description": {
            "short": "Your UK rental fleet, connected through Microsoft Fabric IQ.",
            "full": "Ask Caldova Drive about vehicle locations, health, rentals, branch utilization and kilometers driven. Answers are grounded in Microsoft Fabric. Receive a daily mileage briefing at 08:00 Europe/Madrid in your personal Teams chat.",
        },
        "accentColor": "#234932",
        "bots": [{
            "botId": state["agent_app_id"], "scopes": ["personal"],
            "supportsFiles": False, "isNotificationOnly": False,
            "commandLists": [{"scopes": ["personal"], "commands": [
                {"title": "Yesterday's kilometers", "description": "Get total and branch mileage for yesterday"},
                {"title": "Vehicles needing attention", "description": "Review live battery, tyre and maintenance alerts"},
                {"title": "stop briefings", "description": "Pause daily Teams briefings"},
                {"title": "resume briefings", "description": "Resume daily Teams briefings"},
            ]}],
        }],
        "copilotAgents": {"customEngineAgents": [{"id": state["agent_app_id"], "type": "bot"}]},
        "validDomains": [state["appUrl"].removeprefix("https://")],
        "webApplicationInfo": {"id": state["agent_app_id"], "resource": f"api://{state['agent_app_id']}"},
    }
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", json.dumps(manifest))
        archive.writestr("color.png", icon(192))
        archive.writestr("outline.png", icon(32, outline=True))
    return buffer.getvalue()


def publish_teams(cloud: Cloud, state: dict) -> None:
    package = teams_package(state)
    (ROOT / ".local" / "caldova-teams.zip").write_bytes(package)
    graph = cloud.pages(f"{GRAPH}/servicePrincipals?$filter=appId eq '00000003-0000-0000-c000-000000000000'")[0]
    permissions = {"AppCatalog.ReadWrite.All", "TeamsAppInstallation.ReadWriteSelfForUser.All"}
    roles = [role for role in graph["appRoles"] if role["value"] in permissions and "Application" in role["allowedMemberTypes"]]
    if len(roles) != len(permissions):
        raise RuntimeError("The required Teams deployment roles were not found.")
    granted = []
    existing_roles = cloud.pages(f"{GRAPH}/servicePrincipals/{state['agent_principal_id']}/appRoleAssignments")
    secret = cloud.request("POST", app_path(state) + "/config/appsettings/list?api-version=2023-12-01")["properties"]["FLEET_AGENT_SECRET"]
    try:
        for role in roles:
            if any(assignment["appRoleId"] == role["id"] for assignment in existing_roles):
                continue
            assignment = cloud.request(
                "POST", f"{GRAPH}/servicePrincipals/{state['agent_principal_id']}/appRoleAssignments",
                {"principalId": state["agent_principal_id"], "resourceId": graph["id"], "appRoleId": role["id"]},
            )
            granted.append(assignment["id"])
        client = httpx.Client(timeout=120)
        for attempt in range(8):
            credential = ClientSecretCredential(CONFIG["tenant_id"], state["agent_app_id"], secret)
            token = credential.get_token("https://graph.microsoft.com/.default").token
            client.headers["Authorization"] = f"Bearer {token}"
            response = client.get(f"{GRAPH}/appCatalogs/teamsApps", params={"$filter": f"externalId eq '{state['agent_app_id']}'"})
            if response.status_code != 403:
                break
            if attempt == 7:
                response.raise_for_status()
            time.sleep(15)
        response.raise_for_status()
        existing = response.json()["value"]
        if existing:
            app = existing[0]
        else:
            response = client.post(f"{GRAPH}/appCatalogs/teamsApps", content=package, headers={"Content-Type": "application/zip"})
            response.raise_for_status()
            app = response.json()
        state["teams_catalog_id"] = app["id"]
        save_state(state)
        installed = client.get(
            f"{GRAPH}/users/{CONFIG['admin_object_id']}/teamwork/installedApps",
            params={"$expand": "teamsApp", "$filter": f"teamsApp/id eq '{app['id']}'"},
        )
        installed.raise_for_status()
        if not installed.json()["value"]:
            response = client.post(
                f"{GRAPH}/users/{CONFIG['admin_object_id']}/teamwork/installedApps",
                json={"teamsApp@odata.bind": f"{GRAPH}/appCatalogs/teamsApps/{app['id']}"},
            )
            response.raise_for_status()
    finally:
        for assignment_id in granted:
            cloud.request("DELETE", f"{GRAPH}/servicePrincipals/{state['agent_principal_id']}/appRoleAssignments/{assignment_id}")
    print("Caldova Drive published and installed for the confirmed Teams recipient.", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=["app", "teams"])
    parser.add_argument("--prebuilt", action="store_true", help="Deploy locally restored Linux wheels without a remote Oryx SDK build.")
    parser.add_argument("--code-only", action="store_true", help="Reuse the already deployed compatible Linux dependency bundle.")
    args = parser.parse_args()
    cloud, state = Cloud(), load_state()
    for key in ("ontology_id", "data_agent_id", "lakehouse_id"):
        if not state.get(key):
            raise RuntimeError(f"Complete Fabric intelligence provisioning first: missing {key}.")
    if args.stage == "teams":
        publish_teams(cloud, state)
        return
    if args.code_only and not args.prebuilt:
        raise RuntimeError("--code-only requires --prebuilt.")
    package = deployment_zip(prebuilt=args.prebuilt, code_only=args.code_only)
    configure(cloud, state, prebuilt=args.prebuilt)
    previous_deployments = az(
        "webapp", "log", "deployment", "list", "--name", state["appName"],
        "--resource-group", CONFIG["resource_group"], "--subscription", CONFIG["subscription_id"],
    )
    previous_ids = {item["id"] for item in previous_deployments}
    deployment = az(
        "webapp", "deploy", "--name", state["appName"],
        "--resource-group", CONFIG["resource_group"], "--subscription", CONFIG["subscription_id"],
        "--src-path", package, "--type", "zip", "--timeout", "1200000", "--async", "true", "--track-status", "false",
    )
    print("Deployment accepted; waiting for its durable completion status.", flush=True)
    deadline = time.monotonic() + 1200
    while time.monotonic() < deadline:
        deployments = az(
            "webapp", "log", "deployment", "list", "--name", state["appName"],
            "--resource-group", CONFIG["resource_group"], "--subscription", CONFIG["subscription_id"],
        )
        current = next((item for item in deployments if item["id"] not in previous_ids and not item["id"].startswith("temp-")), None)
        if current and current["status"] == 3:
            raise RuntimeError(f"Azure deployment failed: {current['id']}")
        if current and current["status"] == 4 and current.get("active"):
            break
        time.sleep(15)
    else:
        raise TimeoutError("Azure deployment did not finish within twenty minutes.")
    az("webapp", "restart", "--name", state["appName"], "--resource-group", CONFIG["resource_group"], "--subscription", CONFIG["subscription_id"])
    expected_build = (ROOT / ".local" / "build-id.txt").read_text()
    ready = False
    for _ in range(24):
        try:
            response = httpx.get(state["appUrl"] + "/health/live", timeout=30)
            if response.is_success and response.json().get("buildId") == expected_build:
                ready = True
                break
        except (httpx.TimeoutException, httpx.ConnectError) as error:
            print(f"Waiting for application readiness ({type(error).__name__}).", flush=True)
        time.sleep(10)
    if not ready:
        raise RuntimeError(f"The new build {expected_build} did not become healthy after deployment.")
    print(state["appUrl"], flush=True)


if __name__ == "__main__":
    main()
