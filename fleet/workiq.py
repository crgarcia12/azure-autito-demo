from __future__ import annotations

import asyncio
import base64
from datetime import UTC, datetime
import hashlib
import io
import json
import os
import threading
from urllib.parse import parse_qs, urlparse
from xml.etree import ElementTree
import zipfile

from cryptography.fernet import Fernet
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
import msal

from fleet.config import ROOT, settings
from fleet.domain import utc_text
from fleet.insurance import IncidentError
from fleet.repair_policy import PUBLICATION_PATH, policy_document, policy_reference
from fleet.storage import StateStore

WORK_IQ_SCOPE = "api://workiq.svc.cloud.microsoft/WorkIQAgent.Ask"
FOUNDRY_SCOPE = "https://ai.azure.com/.default"
WORK_IQ_MCP = "https://workiq.svc.cloud.microsoft/mcp"


def word_text(content: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(content)) as package:
        document = package.getinfo("word/document.xml")
        if document.file_size > 2_000_000:
            raise IncidentError("The repair policy document exceeds the permitted size.")
        root = ElementTree.fromstring(package.read(document))
    ns = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    return "\n".join(
        " ".join("".join(node.text or "" for node in paragraph.iter(ns + "t")).split())
        for paragraph in root.iter(ns + "p")
    ).strip()


def same_document(candidate: str, expected: str) -> bool:
    left, right = urlparse(candidate), urlparse(expected)
    return (
        left.scheme == "https" and left.hostname == right.hostname and left.path == right.path
        and parse_qs(left.query).get("sourcedoc") == parse_qs(right.query).get("sourcedoc")
        and bool(parse_qs(left.query).get("sourcedoc"))
    )


class WorkIQSession:
    def __init__(self, store: StateStore, config: dict | None = None):
        self.store, self.config = store, config or settings()
        self.lock = threading.Lock()
        self.cipher = None
        if os.environ.get("WEBSITE_INSTANCE_ID"):
            key = os.environ.get("FLEET_WORKIQ_CACHE_KEY")
            if not key:
                raise IncidentError("The operator's Work IQ connection has not been deployed.", 503)
            self.cipher = Fernet(key.encode())
            self.cache = msal.SerializableTokenCache()
            saved = store.get("workiq-token-cache")
            version = os.environ.get("FLEET_WORKIQ_CACHE_VERSION")
            encrypted = saved["ciphertext"] if saved and saved.get("version") == version else os.environ.get("FLEET_WORKIQ_CACHE_SEED")
            if not encrypted:
                raise IncidentError("Sign in to the Work IQ connection before running repair agents.", 503)
            self.cache.deserialize(self.cipher.decrypt(encrypted.encode()).decode())
        else:
            from msal_extensions import FilePersistenceWithDataProtection, PersistedTokenCache
            self.cache = PersistedTokenCache(FilePersistenceWithDataProtection(str(ROOT / ".local" / "workiq-auth.bin")))
        if not self.config.get("workiq_app_id"):
            raise IncidentError("The dedicated Work IQ application has not been provisioned.", 503)
        self.app = msal.PublicClientApplication(
            self.config["workiq_app_id"], authority=f"https://login.microsoftonline.com/{self.config['tenant_id']}",
            token_cache=self.cache,
        )

    def token(self, scope: str = WORK_IQ_SCOPE) -> str:
        if scope not in {WORK_IQ_SCOPE, FOUNDRY_SCOPE}:
            raise IncidentError("The delegated repair connection cannot request an unrelated resource.", 403)
        with self.lock:
            accounts = self.app.get_accounts(username=self.config["report_recipient"])
            if (len(accounts) != 1 or accounts[0].get("realm") != self.config["tenant_id"]
                    or accounts[0].get("local_account_id") != self.config["admin_object_id"]):
                raise IncidentError("Work IQ requires the configured operator's delegated sign-in.", 503)
            result = self.app.acquire_token_silent([scope], account=accounts[0])
            if self.cipher and self.cache.has_state_changed:
                self.store.put("workiq-token-cache", {
                    "ciphertext": self.cipher.encrypt(self.cache.serialize().encode()).decode(),
                    "version": os.environ.get("FLEET_WORKIQ_CACHE_VERSION"),
                })
            if not result or "access_token" not in result:
                raise IncidentError("The Work IQ session needs sign-in: " + (result or {}).get("error_description", "No delegated token is available."), 503)
            claims = result.get("id_token_claims")
            if claims and (claims.get("tid") != self.config["tenant_id"] or claims.get("oid") != self.config["admin_object_id"]):
                raise IncidentError("Work IQ returned an unexpected identity.", 403)
            return result["access_token"]

    async def read_policy(self) -> dict:
        publication = json.loads(PUBLICATION_PATH.read_text(encoding="utf-8"))
        access = await asyncio.to_thread(self.token)
        async with streamablehttp_client(WORK_IQ_MCP, headers={"Authorization": "Bearer " + access}) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                downloaded = await session.call_tool("fetch_blob", {
                    "path": f"/drives/{publication['drive_id']}/items/{publication['drive_item_id']}/content",
                })
                if downloaded.isError:
                    raise IncidentError("Work IQ could not retrieve the controlled Word policy: " + downloaded.model_dump_json()[:1000], 502)
                blob = downloaded.structuredContent or {}
                if blob.get("statusCode") != 200 or not isinstance(blob.get("base64Content"), str):
                    raise IncidentError("Work IQ returned no verifiable Word policy content.", 502)
                content = base64.b64decode(blob["base64Content"], validate=True)
                metadata = await session.call_tool("fetch", {"entityUrls": [
                    f"/drives/{publication['drive_id']}/items/{publication['drive_item_id']}?$select=id,eTag,webUrl",
                ]})
                rows = (metadata.structuredContent or {}).get("results", [])
                if metadata.isError or len(rows) != 1 or rows[0].get("statusCode") != 200:
                    raise IncidentError("Work IQ could not verify the retrieved policy's source metadata.", 502)
                item = rows[0]["data"]
                if item.get("id") != publication["drive_item_id"] or not same_document(item.get("webUrl", ""), publication["document_url"]):
                    raise IncidentError("Work IQ returned a different policy document.", 502)
        document = word_text(content)
        expected = word_text(policy_document().read_bytes())
        if document != expected:
            raise IncidentError("The Word repair policy changed. Review and publish the matching approval rules before continuing.")
        return {
            "document_id": item["id"], "document_text": document, "citations": [item["webUrl"]],
            "retrieved_at": utc_text(datetime.now(UTC)), "server_url": WORK_IQ_MCP,
            "source": {**policy_reference(), "document_sha256": hashlib.sha256(content).hexdigest(), "etag": item["eTag"],
                       "document_text_sha256": hashlib.sha256(document.encode()).hexdigest()},
            "provider": "Microsoft Work IQ", "retrieval_tools": ["fetch_blob", "fetch"],
        }
