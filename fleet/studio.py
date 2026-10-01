from __future__ import annotations

import asyncio
import json
import os
import time
from urllib.parse import parse_qs, urlparse
import uuid

import httpx

from fleet.config import settings


def extract_object(text: str) -> dict | None:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
    if not stripped.startswith("{"):
        return None
    try:
        value = json.loads(stripped)
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


class StudioAgents:
    def __init__(self):
        self.config = settings()
        self.semaphore = asyncio.Semaphore(2)
        self.channel_secrets = json.loads(os.environ.get("FLEET_STUDIO_CHANNEL_SECRETS", "{}"))

    async def invoke(self, schema: str, payload: dict) -> dict:
        agents = self.config.get("studio_agents", {})
        if schema not in agents:
            raise RuntimeError(f"The real Copilot Studio agent {schema} has not been deployed.")
        agent = agents[schema]
        endpoint = agent["token_endpoint"]
        hostname = urlparse(endpoint).hostname or ""
        if not hostname.endswith((".powerapps.com", ".powerplatform.com", ".microsoft.com")):
            raise RuntimeError("Untrusted Studio runtime endpoint.")
        async with self.semaphore, httpx.AsyncClient(timeout=90) as client:
            base = "https://directline.botframework.com/v3/directline"
            if (os.environ.get("WEBSITE_INSTANCE_ID") or self.config.get("studio_channel_credentials_configured") or self.config.get("studio_channels_secured")) and not self.channel_secrets:
                raise RuntimeError("Secured native agent channel credentials are required; anonymous fallback is disabled.")
            if self.channel_secrets:
                secret = self.channel_secrets.get(schema)
                if not isinstance(secret, str) or not secret:
                    raise RuntimeError(f"The secured channel credential for {schema} is missing.")
                response = await client.post(base + "/tokens/generate", headers={"Authorization": f"Bearer {secret}"})
            else:
                response = await client.get(endpoint)
            response.raise_for_status()
            session = response.json()
            headers = {"Authorization": f"Bearer {session['token']}"}
            response = await client.post(base + "/conversations", headers=headers)
            response.raise_for_status()
            conversation = response.json()
            conversation_id = conversation["conversationId"]
            headers = {"Authorization": f"Bearer {conversation.get('token', session['token'])}"}
            request_id = str(uuid.uuid4())
            response = await client.post(
                f"{base}/conversations/{conversation_id}/activities",
                headers=headers, json={
                    "type": "message", "from": {"id": f"caldova-{request_id}"},
                    "text": json.dumps(payload, ensure_ascii=True), "textFormat": "plain", "locale": "en-GB",
                },
            )
            response.raise_for_status()
            activity_id = response.json()["id"]
            watermark = None
            deadline = time.monotonic() + 180
            received = []
            while time.monotonic() < deadline:
                await asyncio.sleep(2)
                response = await client.get(
                    f"{base}/conversations/{conversation_id}/activities",
                    headers=headers, params={"watermark": watermark} if watermark else {},
                )
                response.raise_for_status()
                batch = response.json()
                watermark = batch.get("watermark", watermark)
                for activity in batch.get("activities", []):
                    if activity.get("type") != "message" or activity.get("from", {}).get("role") != "bot":
                        continue
                    expected_runtime_id = parse_qs(urlparse(endpoint).query).get("botId", [None])[0]
                    if expected_runtime_id and activity.get("from", {}).get("id") != expected_runtime_id:
                        raise RuntimeError("The credential reached a different native agent than the configured one.")
                    text = activity.get("text", "")
                    received.append(text)
                    value = extract_object(text)
                    if value is not None:
                        if "error" in value:
                            raise RuntimeError(f"{agent['name']} rejected the request: {value['error']}")
                        return {"result": value, "agent": {
                            "name": agent["name"], "id": agent["id"], "schema": schema,
                            "conversation_id": conversation_id, "request_activity_id": activity_id,
                            "response_activity_id": activity.get("id"),
                            "response_from_name": activity.get("from", {}).get("name"),
                            "response_from_id": activity.get("from", {}).get("id"),
                        }}
                    if activity.get("attachments"):
                        raise RuntimeError(f"{agent['name']} requested interactive authentication or returned an unexpected card.")
            detail = " | ".join(received)[-1500:]
            raise RuntimeError(f"Copilot Studio did not return the required structured response: {detail}")
