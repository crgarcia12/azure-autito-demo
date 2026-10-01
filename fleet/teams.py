from __future__ import annotations

import asyncio
import logging
import os

from aiohttp import web
from microsoft_agents.activity import Activity, Attachment, ChannelAccount, ConversationParameters, ConversationReference
from microsoft_agents.authentication.msal import MsalConnectionManager
from microsoft_agents.hosting.aiohttp import CloudAdapter, jwt_authorization_middleware, start_agent_process
from microsoft_agents.hosting.core import AgentApplication, AgentAuthConfiguration, MemoryStorage, TurnContext

from fleet.agent import ChatMessage, FleetAgent
from fleet.config import settings
from fleet.storage import StateStore

LOG = logging.getLogger("caldova.teams")


class TeamsAgent:
    def __init__(self, agent: FleetAgent, store: StateStore) -> None:
        self.config = settings()
        self.store, self.agent = store, agent
        secret = os.environ.get("FLEET_AGENT_SECRET")
        if not secret:
            raise RuntimeError("Teams requires its registered application credential.")
        self.auth = AgentAuthConfiguration(
            client_id=self.config["agent_app_id"], tenant_id=self.config["tenant_id"],
            client_secret=secret, scopes=["https://api.botframework.com/.default"],
            anonymous_allowed=False,
        )
        connections = MsalConnectionManager({"SERVICE_CONNECTION": self.auth})
        self.adapter = CloudAdapter(connection_manager=connections)
        self.application = AgentApplication(storage=MemoryStorage(), adapter=self.adapter)
        self.application.activity("message")(self.on_message)
        self.application.conversation_update("membersAdded")(self.on_installed)
        self.application.activity("installationUpdate")(self.on_installed)
        self.adapter.on_turn_error = self.on_error

    def attach(self, app: web.Application) -> None:
        app["agent_configuration"] = self.auth
        app["agent_app"] = self.application
        app["adapter"] = self.adapter

    async def endpoint(self, request: web.Request) -> web.Response:
        async def process(req):
            return await start_agent_process(req, self.application, self.adapter)
        return await jwt_authorization_middleware(request, process)

    async def allowed(self, context: TurnContext) -> bool:
        activity = context.activity
        channel = activity.channel_data or {}
        tenant = channel.get("tenant", {}).get("id") or getattr(activity.conversation, "tenant_id", None)
        sender = activity.from_property
        user = getattr(sender, "aad_object_id", None)
        if tenant != self.config["tenant_id"] or user != self.config["admin_object_id"]:
            await context.send_activity("This fleet workspace is restricted to its configured Caldova demo operator.")
            return False
        if activity.conversation.conversation_type not in ("personal", None):
            await context.send_activity("Use your personal Caldova Drive chat to access this fleet workspace.")
            return False
        reference = activity.get_conversation_reference()
        await asyncio.to_thread(
            self.store.put, "teams-reference.json", reference.model_dump(mode="json", by_alias=True, exclude_none=True)
        )
        return True

    async def on_installed(self, context: TurnContext, _) -> None:
        if await self.allowed(context):
            await context.send_activity(
                "Welcome to Caldova Drive. Ask about your UK fleet, locations, vehicle health or yesterday's kilometers. "
                "Your daily fleet briefing arrives here at 08:00 Europe/Madrid."
            )

    async def on_message(self, context: TurnContext, _) -> None:
        if not await self.allowed(context):
            return
        text = (context.activity.text or "").strip()
        if not text or len(text) > 2000:
            await context.send_activity("Please send a fleet question between 1 and 2,000 characters.")
            return
        if text.lower() in {"stop briefings", "pause briefings"}:
            await asyncio.to_thread(self.store.put, "briefing-control.json", {"paused": True})
            await context.send_activity("Morning briefings are paused. Send 'resume briefings' to restart delivery.")
            return
        if text.lower() == "resume briefings":
            await asyncio.to_thread(self.store.put, "briefing-control.json", {"paused": False})
            await context.send_activity("Morning briefings will be delivered at 08:00 Europe/Madrid.")
            return
        key = f"teams-history-{context.activity.conversation.id}.json"
        prior = await asyncio.to_thread(self.store.get, key) or []
        history = [ChatMessage.model_validate(message) for message in prior[-8:]]
        await context.send_activity(Activity(type="typing"))
        result = await self.agent.ask(text, history)
        await context.send_activity(result["answer"] + "\n\n_Source: Microsoft Fabric IQ_")
        prior.extend([{"role": "user", "content": text}, {"role": "assistant", "content": result["answer"][:12000]}])
        await asyncio.to_thread(self.store.put, key, prior[-8:])

    async def on_error(self, context: TurnContext, error: Exception) -> None:
        LOG.error("Teams turn failed", exc_info=error)
        await context.send_activity("I couldn't complete the Fabric query. Please retry; no result has been substituted.")

    async def send_briefing(self, briefing: dict) -> str:
        saved = await asyncio.to_thread(self.store.get, "teams-reference.json")
        if not saved:
            async def created(context: TurnContext):
                reference = context.activity.get_conversation_reference()
                reference.user = ChannelAccount(
                    id=self.config["admin_object_id"], aad_object_id=self.config["admin_object_id"],
                    name="Caldova fleet operator",
                )
                await asyncio.to_thread(
                    self.store.put, "teams-reference.json",
                    reference.model_dump(mode="json", by_alias=True, exclude_none=True),
                )

            await self.adapter.create_conversation(
                self.config["agent_app_id"], "msteams",
                "https://smba.trafficmanager.net/teams/", "https://api.botframework.com",
                ConversationParameters(
                    is_group=False,
                    bot=ChannelAccount(id=self.config["agent_app_id"], name="Caldova Drive"),
                    members=[ChannelAccount(id=self.config["admin_object_id"], name="Caldova fleet operator")],
                    tenant_id=self.config["tenant_id"],
                    channel_data={"tenant": {"id": self.config["tenant_id"]}},
                ),
                created,
            )
            saved = await asyncio.to_thread(self.store.get, "teams-reference.json")
            if not saved:
                raise RuntimeError("Teams did not create the installed agent's personal conversation.")
        reference = ConversationReference.model_validate(saved)
        card = {
            "$schema": "http://adaptivecards.io/schemas/adaptive-card.json", "type": "AdaptiveCard", "version": "1.5",
            "body": [
                {"type": "TextBlock", "text": "CALDOVA DRIVE · MORNING BRIEFING", "size": "Small", "weight": "Bolder", "color": "Accent"},
                {"type": "TextBlock", "text": f"{briefing['totalKm']:,.1f} km", "size": "ExtraLarge", "weight": "Bolder"},
                {"type": "TextBlock", "text": f"{briefing['reportDate']} · Europe/Madrid · {briefing['activeVehicles']} vehicles on the road", "isSubtle": True, "wrap": True},
                {"type": "TextBlock", "text": briefing["text"][:12000], "wrap": True},
                {"type": "TextBlock", "text": "Source: Microsoft Fabric IQ. Send 'stop briefings' to pause daily delivery.", "size": "Small", "isSubtle": True, "wrap": True},
            ],
            "actions": [{"type": "Action.OpenUrl", "title": "Open fleet dashboard", "url": self.config["appUrl"]}],
        }
        sent_id = ""

        async def deliver(context: TurnContext):
            nonlocal sent_id
            result = await context.send_activity(Activity(
                type="message",
                attachments=[Attachment(content_type="application/vnd.microsoft.card.adaptive", content=card)],
            ))
            sent_id = result.id

        await self.adapter.continue_conversation(
            self.config["agent_app_id"], reference.get_continuation_activity(), deliver
        )
        if not sent_id:
            raise RuntimeError("Teams did not acknowledge delivery with a message ID.")
        return sent_id
