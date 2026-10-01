from __future__ import annotations

import asyncio
import base64
from datetime import UTC, datetime, timedelta
import html
import json
import logging
import re
from urllib.parse import quote, urlparse

import httpx

from fleet.config import agent_credential, settings
from fleet.domain import utc_text
from fleet.insurance import IncidentError, Incidents, assert_caldova_address, insurance_config

LOG = logging.getLogger("caldova.mail")
GRAPH = "https://graph.microsoft.com/v1.0"


def plain_body(body: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", " ", body)).strip()


class RepairMail:
    def __init__(self, cases: Incidents):
        self.cases = cases
        self.config = insurance_config()
        self.allowed = {self.config["claims_mailbox"].casefold(), *(garage["mailbox"].casefold() for garage in self.config["garages"])}
        self.credential = agent_credential()
        self.operator = assert_caldova_address(settings()["report_recipient"])

    def mailbox(self, address: str) -> str:
        if address.casefold() not in self.allowed:
            raise IncidentError("Email transport is restricted to the four approved Caldova inboxes.", 403)
        return quote(address, safe="")

    def recipient(self, sender: str, address: str) -> None:
        if sender.casefold() == self.config["claims_mailbox"].casefold() and address.casefold() == self.operator:
            return
        self.mailbox(address)

    async def request(self, method: str, path: str, body: dict | None = None) -> dict | None:
        url = GRAPH + path
        token = await asyncio.to_thread(self.credential.get_token, "https://graph.microsoft.com/.default")
        async with httpx.AsyncClient(timeout=90) as client:
            for attempt in range(5):
                response = await client.request(method, url, json=body, headers={
                    "Authorization": f"Bearer {token.token}", "Prefer": 'IdType="ImmutableId", outlook.body-content-type="text"',
                })
                if response.status_code != 429:
                    break
                if attempt == 4:
                    response.raise_for_status()
                await asyncio.sleep(min(int(response.headers.get("Retry-After", "15")), 90))
            response.raise_for_status()
            return response.json() if response.content else None

    async def inbox(self, address: str) -> list[dict]:
        mailbox = self.mailbox(address)
        earliest = utc_text(datetime.now(UTC) - timedelta(days=2))
        result = await self.request(
            "GET", f"/users/{mailbox}/mailFolders/inbox/messages?$top=50&$orderby=receivedDateTime%20desc&$filter=receivedDateTime%20ge%20{earliest}&$select=id,internetMessageId,conversationId,subject,from,toRecipients,receivedDateTime,body,webLink",
        )
        return result["value"]

    def operation(self, key: str) -> dict | None:
        with self.cases.store.connect() as db:
            row = db.execute("SELECT state,result,payload FROM incident_operations WHERE key=?", (key,)).fetchone()
        return {"state": row[0], "result": json.loads(row[1]) if row[1] else None, "payload": json.loads(row[2])} if row else None

    def reserve(self, key: str, case_id: str, payload: dict) -> dict | None:
        with self.cases.store.connect() as db:
            db.execute("INSERT OR IGNORE INTO incident_operations VALUES(?,?,?,?,?,?)",
                       (key, case_id, "pending", json.dumps(payload), None, utc_text(datetime.now(UTC))))
        return self.operation(key)

    def update(self, key: str, state: str, result: dict | None = None) -> None:
        with self.cases.store.connect() as db:
            db.execute("UPDATE incident_operations SET state=?,result=?,updated_at=? WHERE key=?",
                       (state, json.dumps(result) if result else None, utc_text(datetime.now(UTC)), key))

    def claim_draft(self, key: str) -> None:
        with self.cases.store.connect() as db:
            changed = db.execute(
                "UPDATE incident_operations SET state='draft_creating',updated_at=? WHERE key=? AND state IN ('pending','rejected')",
                (utc_text(datetime.now(UTC)), key),
            ).rowcount
        if changed != 1:
            raise IncidentError("Another worker already claimed this email operation; no second draft will be created.")

    async def send(
        self, *, key: str, case_id: str, sender: str, recipient: str, subject: str, body: str,
        attachment: bytes | None = None, reply_to_id: str | None = None,
    ) -> dict:
        self.recipient(sender, recipient)
        mailbox = self.mailbox(sender)
        operation = self.reserve(key, case_id, {"sender": sender, "recipient": recipient, "subject": subject})
        if operation["state"] == "sent":
            return operation["result"]
        if operation["state"] == "sending":
            draft_id = operation["result"]["draft_id"]
            try:
                sent = await self.request("GET", f"/users/{mailbox}/messages/{quote(draft_id, safe='')}?$select=id,isDraft,subject,body,from,toRecipients,sentDateTime,internetMessageId,webLink")
            except httpx.HTTPStatusError as error:
                raise IncidentError("An email send has an unknown outcome; reconcile it before retrying.") from error
            if sent["isDraft"]:
                raise IncidentError("An email send has not been confirmed. Wait for mailbox reconciliation.")
            result = self.correspondence(sent, "outbound", sender, recipient)
            self.update(key, "sent", result)
            return result
        if operation["state"] == "draft_creating":
            raise IncidentError("Draft creation was interrupted. Reconcile the outbox before retrying.")
        if operation["state"] == "draft":
            draft_id = operation["result"]["draft_id"]
        else:
            self.claim_draft(key)
            payload = {
                "subject": subject, "body": {"contentType": "Text", "content": body},
                "toRecipients": [{"emailAddress": {"address": recipient}}],
                "ccRecipients": [], "bccRecipients": [],
            }
            if attachment:
                if len(attachment) > 2_800_000:
                    raise IncidentError("The garage report attachment exceeds the email size limit.")
                payload["attachments"] = [{
                    "@odata.type": "#microsoft.graph.fileAttachment", "name": f"{case_id}-repair-brief.pdf",
                    "contentType": "application/pdf", "contentBytes": base64.b64encode(attachment).decode(),
                }]
            try:
                if reply_to_id:
                    created = await self.request("POST", f"/users/{mailbox}/messages/{quote(reply_to_id, safe='')}/createReply", {})
                    await self.request("PATCH", f"/users/{mailbox}/messages/{quote(created['id'], safe='')}", payload)
                else:
                    created = await self.request("POST", f"/users/{mailbox}/messages", payload)
            except httpx.HTTPStatusError:
                self.update(key, "rejected")
                raise
            draft_id = created["id"]
            self.update(key, "draft", {"draft_id": draft_id})
        self.update(key, "sending", {"draft_id": draft_id})
        await self.request("POST", f"/users/{mailbox}/messages/{quote(draft_id, safe='')}/send", {})
        # Immutable message IDs survive the move from Drafts to Sent Items.
        for attempt in range(10):
            await asyncio.sleep(2)
            sent = await self.request(
                "GET", f"/users/{mailbox}/messages/{quote(draft_id, safe='')}?$select=id,isDraft,subject,body,from,toRecipients,sentDateTime,internetMessageId,webLink",
            )
            if not sent["isDraft"]:
                result = self.correspondence(sent, "outbound", sender, recipient)
                self.update(key, "sent", result)
                return result
        raise RuntimeError("Exchange accepted the send but did not yet confirm it in Sent Items.")

    @staticmethod
    def correspondence(message: dict, direction: str, sender: str, recipient: str) -> dict:
        return {
            "id": message["id"], "internet_message_id": message.get("internetMessageId"),
            "direction": direction, "from": sender, "to": recipient,
            "subject": message.get("subject", ""), "body": plain_body(message.get("body", {}).get("content", "")),
            "at": message.get("sentDateTime") or message.get("receivedDateTime"),
            "web_url": message.get("webLink", ""),
        }

    def record(self, case_id: str, message: dict, kind: str, actor: str) -> None:
        if any(item["id"] == message["id"] for item in self.cases.get(case_id)["correspondence"]):
            return
        def transform(case):
            if not any(item["id"] == message["id"] for item in case["correspondence"]):
                case["correspondence"].append(message)
            return {"message_id": message["id"], "subject": message["subject"]}
        self.cases.change(case_id, kind, actor, transform)
