from __future__ import annotations

import json

from tools.cloud import Cloud, CONFIG, GRAPH, ROOT, load_state, save_state

CONTENT_SCOPES = ["User.Read", "Chat.Create", "ChatMessage.Send", "Chat.Read", "Calendars.ReadWrite", "Files.ReadWrite"]


def main() -> None:
    cloud, state = Cloud(), load_state()
    graph = cloud.pages(
        GRAPH + "/servicePrincipals?$filter=appId eq '00000003-0000-0000-c000-000000000000'"
    )[0]
    scopes = {
        permission["value"]: permission["id"]
        for permission in graph["oauth2PermissionScopes"]
        if permission.get("isEnabled")
    }
    missing = set(CONTENT_SCOPES) - scopes.keys()
    if missing:
        raise RuntimeError(f"Required Graph delegated permissions are unavailable: {missing}")
    name = "Caldova IQ Content Studio"
    applications = cloud.pages(GRAPH + f"/applications?$filter=displayName eq '{name}'")
    configuration = {
        "displayName": name,
        "signInAudience": "AzureADMyOrg",
        "isFallbackPublicClient": True,
        "publicClient": {"redirectUris": ["http://localhost"]},
        "requiredResourceAccess": [{
            "resourceAppId": graph["appId"],
            "resourceAccess": [{"id": scopes[scope], "type": "Scope"} for scope in CONTENT_SCOPES],
        }],
    }
    if applications:
        application = applications[0]
        cloud.request("PATCH", f"{GRAPH}/applications/{application['id']}", configuration)
    else:
        application = cloud.request("POST", GRAPH + "/applications", configuration)
    principals = cloud.pages(GRAPH + f"/servicePrincipals?$filter=appId eq '{application['appId']}'")
    principal = principals[0] if principals else cloud.request(
        "POST", GRAPH + "/servicePrincipals", {"appId": application["appId"]}
    )
    content = json.loads((ROOT / "content.config.json").read_text(encoding="utf-8"))
    upns = [author["upn"] for author in content["authors"]] + [content["observer"]]
    personas = []
    for upn in upns:
        if upn.split("@")[-1].casefold() != CONFIG["tenant_domain"].casefold():
            raise ValueError("Content authors and recipients must be Caldova tenant accounts.")
        user = cloud.request(
            "GET", f"{GRAPH}/users/{upn}?$select=id,displayName,userPrincipalName,userType,accountEnabled,assignedLicenses"
        )
        if user["userType"] != "Member" or not user["accountEnabled"] or not user["assignedLicenses"]:
            raise RuntimeError(f"{upn} must be an enabled, licensed tenant member.")
        personas.append({key: user[key] for key in ("id", "displayName", "userPrincipalName")})
    cloud.request(
        "PATCH", f"{GRAPH}/servicePrincipals/{principal['id']}", {"appRoleAssignmentRequired": True}
    )
    assignments = cloud.pages(f"{GRAPH}/servicePrincipals/{principal['id']}/appRoleAssignedTo")
    grants = cloud.pages(
        GRAPH + f"/oauth2PermissionGrants?$filter=clientId eq '{principal['id']}'"
    )
    for user in personas:
        if not any(assignment["principalId"] == user["id"] for assignment in assignments):
            cloud.request(
                "POST", f"{GRAPH}/servicePrincipals/{principal['id']}/appRoleAssignedTo",
                {
                    "principalId": user["id"], "resourceId": principal["id"],
                    "appRoleId": "00000000-0000-0000-0000-000000000000",
                },
            )
        existing = next(
            (grant for grant in grants if grant.get("principalId") == user["id"] and grant["resourceId"] == graph["id"]),
            None,
        )
        if existing:
            cloud.request(
                "PATCH", f"{GRAPH}/oauth2PermissionGrants/{existing['id']}",
                {"scope": " ".join(CONTENT_SCOPES)},
            )
        else:
            cloud.request("POST", GRAPH + "/oauth2PermissionGrants", {
                "clientId": principal["id"], "consentType": "Principal",
                "principalId": user["id"], "resourceId": graph["id"],
                "scope": " ".join(CONTENT_SCOPES),
            })
    state.update(
        content_app_id=application["appId"],
        content_app_object_id=application["id"],
        content_principal_id=principal["id"],
    )
    save_state(state)
    persona_file = ROOT / ".local" / "content-personas.json"
    persona_file.write_text(json.dumps(personas, indent=2), encoding="utf-8")
    verified = cloud.request("GET", GRAPH + f"/applications/{application['id']}?$select=appId,signInAudience,requiredResourceAccess")
    if verified["signInAudience"] != "AzureADMyOrg":
        raise RuntimeError("Content Studio must remain single-tenant.")
    print(f"Created: {name}")
    print(f"Tenant: {CONFIG['tenant_id']}")
    print(f"Client ID: {application['appId']}")
    print("Delegated permissions: " + ", ".join(CONTENT_SCOPES))
    print(f"Sign-in and consent are restricted to {len(personas)} approved Caldova accounts.")
    print("No application-wide impersonation permissions or client secrets were created.")


if __name__ == "__main__":
    main()
