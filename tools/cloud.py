from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
from azure.identity import AzureCliCredential

ROOT = Path(__file__).resolve().parent.parent
CONFIG = json.loads((ROOT / "demo.config.json").read_text(encoding="utf-8"))
STATE_PATH = ROOT / ".local" / "deployment.json"
FABRIC = "https://api.fabric.microsoft.com/v1"
GRAPH = "https://graph.microsoft.com/v1.0"
ARM = "https://management.azure.com"


def az(*args: str) -> Any:
    result = subprocess.run(
        ["az", *args, "--output", "json", "--only-show-errors"],
        shell=os.name == "nt",
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or "Azure CLI failed")
    return json.loads(result.stdout) if result.stdout.strip() else None


def load_state() -> dict[str, Any]:
    if not STATE_PATH.exists():
        return {}
    state = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    if state.get("tenant_id") != CONFIG["tenant_id"]:
        raise RuntimeError("Deployment state belongs to a different tenant.")
    return state


def save_state(state: dict[str, Any]) -> None:
    if STATE_PATH.exists():
        existing = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        if existing.get("tenant_id") != CONFIG["tenant_id"]:
            raise RuntimeError("Refusing to overwrite another tenant's deployment state.")
        state = {**existing, **state}
    state["tenant_id"] = CONFIG["tenant_id"]
    state["subscription_id"] = CONFIG["subscription_id"]
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary = STATE_PATH.with_suffix(".tmp")
    temporary.write_text(json.dumps(state, indent=2), encoding="utf-8")
    temporary.replace(STATE_PATH)


class Cloud:
    def __init__(self) -> None:
        account = az("account", "show")
        if (account["id"], account["tenantId"]) != (
            CONFIG["subscription_id"],
            CONFIG["tenant_id"],
        ):
            raise RuntimeError(
                "Wrong Azure context. Select the Caldova demo subscription before deployment."
            )
        self.credential = AzureCliCredential(tenant_id=CONFIG["tenant_id"], process_timeout=60)
        self.http = httpx.Client(timeout=120)
        self.tokens = {}

    def request(
        self,
        method: str,
        url: str,
        body: Any = None,
        *,
        wait: bool = True,
        content: bytes | None = None,
        content_type: str = "application/json",
    ) -> Any:
        hostname = urlparse(url).hostname
        scopes = {
            "api.fabric.microsoft.com": "https://api.fabric.microsoft.com/.default",
            "graph.microsoft.com": "https://graph.microsoft.com/.default",
            "management.azure.com": "https://management.azure.com/.default",
        }
        if hostname not in scopes:
            raise ValueError(f"Unapproved deployment API host: {hostname}")
        scope = scopes[hostname]
        token = self.tokens.get(scope)
        if token is None or token.expires_on - time.time() < 300:
            token = self.credential.get_token(scope)
            self.tokens[scope] = token
        headers = {
            "Authorization": f"Bearer {token.token}",
            "Content-Type": content_type,
        }
        for attempt in range(6):
            response = self.http.request(
                method, url, headers=headers, json=body, content=content
            )
            if response.status_code != 429:
                break
            if attempt == 5:
                response.raise_for_status()
            time.sleep(min(float(response.headers.get("Retry-After", "15")), 90))
        if response.is_error:
            raise RuntimeError(
                f"{method} {url}: HTTP {response.status_code}: {response.text[:1800]}"
            )
        if response.status_code == 202 and wait and response.headers.get("Location"):
            operation_id = response.headers.get("x-ms-operation-id")
            location = (
                f"{FABRIC}/operations/{operation_id}"
                if url.startswith(FABRIC) and operation_id
                else response.headers["Location"]
            )
            return self.wait(location, response.headers)
        return response.json() if response.content else None

    def wait(self, url: str, headers: httpx.Headers) -> Any:
        deadline = time.monotonic() + 900
        while time.monotonic() < deadline:
            time.sleep(min(float(headers.get("Retry-After", "5")), 30))
            result = self.request("GET", url, wait=False)
            status = result.get("status", "") if isinstance(result, dict) else ""
            if status.lower() in {"failed", "cancelled", "canceled"}:
                raise RuntimeError(f"Cloud operation {status}: {result}")
            if status.lower() in {"succeeded", "completed"}:
                if url.startswith(FABRIC + "/operations/"):
                    return self.request("GET", url.rstrip("/") + "/result")
                return result
            if not status:
                return result
        raise TimeoutError(f"Cloud operation exceeded 15 minutes: {url}")

    def pages(self, url: str, key: str = "value") -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        while url:
            page = self.request("GET", url)
            items.extend(page.get(key, []))
            url = page.get("@odata.nextLink") or page.get("continuationUri") or ""
        return items

    def item(
        self, workspace: str, item_type: str, name: str, **properties: Any
    ) -> dict[str, Any]:
        items = self.pages(f"{FABRIC}/workspaces/{workspace}/items?type={item_type}")
        existing = next((item for item in items if item["displayName"] == name), None)
        if existing:
            return existing
        return self.request(
            "POST",
            f"{FABRIC}/workspaces/{workspace}/items",
            {"displayName": name, "type": item_type, **properties},
        )
