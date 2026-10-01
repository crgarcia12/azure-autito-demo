from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
import json
from typing import Literal

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from pydantic import BaseModel, Field

from fleet.config import agent_credential, settings
from fleet.domain import utc_text


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=12000)


class ChatRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    history: list[ChatMessage] = Field(default_factory=list, max_length=12)


class FleetAgent:
    def __init__(self) -> None:
        self.config = settings()
        self.credential = agent_credential()
        self.endpoint = (
            f"https://api.fabric.microsoft.com/v1/mcp/workspaces/{self.config['workspace_id']}"
            f"/dataagents/{self.config['data_agent_id']}/agent"
        )
        self.lock = asyncio.Semaphore(3)

    async def ask(self, question: str, history: list[ChatMessage] | None = None) -> dict:
        now = utc_text(datetime.now(UTC))
        prompt = f"Current UTC time: {now}. Reporting timezone: {self.config['report_timezone']}.\n"
        if history:
            prompt += "Conversation context (not new instructions):\n"
            prompt += json.dumps([message.model_dump() for message in history[-8:]])
            prompt += "\n"
        prompt += f"User question: {question}"
        async with self.lock:
            token = await asyncio.to_thread(
                self.credential.get_token, "https://api.fabric.microsoft.com/.default"
            )
            async with streamablehttp_client(
                self.endpoint,
                headers={"Authorization": f"Bearer {token.token}"},
                timeout=timedelta(seconds=180),
                sse_read_timeout=timedelta(seconds=240),
            ) as (read, write, _):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    tools = (await session.list_tools()).tools
                    if len(tools) != 1:
                        raise RuntimeError("Fabric data agent did not expose its expected single query tool.")
                    tool = tools[0]
                    properties = tool.inputSchema.get("properties", {})
                    required = tool.inputSchema.get("required", [])
                    string_args = [
                        name for name, schema in properties.items()
                        if schema.get("type") == "string"
                    ]
                    argument = next(
                        (name for name in ("question", "query", "userMessage") if name in string_args),
                        string_args[0] if len(string_args) == 1 else None,
                    )
                    if argument is None or any(name != argument for name in required):
                        raise RuntimeError(f"Unsupported Fabric query tool schema: {tool.inputSchema}")
                    result = await session.call_tool(tool.name, {argument: prompt})
                    if result.isError:
                        details = "\n".join(block.text for block in result.content if block.type == "text")
                        raise RuntimeError(f"Fabric data agent query failed: {details[:1000]}")
                    answer = "\n".join(block.text for block in result.content if block.type == "text").strip()
                    if not answer:
                        raise RuntimeError("Fabric data agent returned no answer.")
                    return {
                        "answer": answer, "asOf": now,
                        "source": "Microsoft Fabric IQ",
                        "sourceUrl": f"https://app.fabric.microsoft.com/groups/{self.config['workspace_id']}/aiskills/{self.config['data_agent_id']}",
                    }
