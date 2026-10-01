from __future__ import annotations

import json
import os
from pathlib import Path

import httpx
import msal
from msal_extensions import FilePersistenceWithDataProtection, PersistedTokenCache

from tools.cloud import CONFIG, GRAPH, ROOT, load_state
from tools.content_app import CONTENT_SCOPES

SCOPES = [f"https://graph.microsoft.com/{scope}" for scope in CONTENT_SCOPES]


def personas() -> dict[str, dict]:
    path = ROOT / ".local" / "content-personas.json"
    if not path.exists():
        raise RuntimeError("Run python -m tools.content_app before authenticating content authors.")
    return {
        user["userPrincipalName"].casefold(): user
        for user in json.loads(path.read_text(encoding="utf-8"))
    }


class AuthorSession:
    def __init__(self, upn: str) -> None:
        people = personas()
        if upn.casefold() not in people:
            raise ValueError("This account is not an approved Caldova content participant.")
        self.person = people[upn.casefold()]
        if os.name != "nt":
            raise RuntimeError("This local authoring tool requires Windows DPAPI-protected token storage.")
        directory = ROOT / ".local" / "content-auth"
        directory.mkdir(parents=True, exist_ok=True)
        cache = PersistedTokenCache(
            FilePersistenceWithDataProtection(str(directory / f"{self.person['id']}.bin"))
        )
        self.app = msal.PublicClientApplication(
            load_state()["content_app_id"],
            authority=f"https://login.microsoftonline.com/{CONFIG['tenant_id']}",
            token_cache=cache,
        )

    def login(self) -> None:
        flow = self.app.initiate_device_flow(scopes=SCOPES)
        if "user_code" not in flow:
            raise RuntimeError(f"Could not start sign-in: {flow.get('error_description', flow)}")
        print(f"Sign in ONLY as {self.person['userPrincipalName']} in the Caldova Edge profile.", flush=True)
        print(flow["message"], flush=True)
        result = self.app.acquire_token_by_device_flow(flow)
        self._validate(result)
        print(f"Connected {self.person['displayName']} to Caldova IQ Content Studio.", flush=True)

    def token(self) -> str:
        accounts = [
            account for account in self.app.get_accounts()
            if account.get("username", "").casefold() == self.person["userPrincipalName"].casefold()
        ]
        if len(accounts) != 1:
            raise RuntimeError(f"Sign-in required: python -m content_studio login --user {self.person['userPrincipalName']}")
        result = self.app.acquire_token_silent(SCOPES, account=accounts[0])
        return self._validate(result)

    def _validate(self, result: dict | None) -> str:
        if not result or "access_token" not in result:
            details = (result or {}).get("error_description", "Interactive sign-in is required.")
            raise RuntimeError(f"Caldova author authentication failed: {details}")
        claims = result.get("id_token_claims", {})
        if claims.get("tid") != CONFIG["tenant_id"] or claims.get("oid") != self.person["id"]:
            raise RuntimeError("The signed-in identity is not the expected Caldova author. No content was sent.")
        return result["access_token"]

    def verify(self) -> dict:
        response = httpx.get(
            GRAPH + "/me?$select=id,displayName,userPrincipalName",
            headers={"Authorization": f"Bearer {self.token()}"}, timeout=30,
        )
        response.raise_for_status()
        person = response.json()
        if person["id"] != self.person["id"]:
            raise RuntimeError("Graph returned the wrong author identity.")
        return person
