from __future__ import annotations

import asyncio
from datetime import UTC, datetime
import math
from zoneinfo import ZoneInfo

from fleet.agent import FleetAgent
from fleet.config import settings
from fleet.domain import previous_day, utc_text
from fleet.fabric import FabricData
from fleet.storage import StateStore


class BriefingService:
    def __init__(self, data: FabricData, agent: FleetAgent, store: StateStore, teams=None) -> None:
        self.data, self.agent, self.store, self.teams = data, agent, store, teams
        self.config = settings()
        self.lock = asyncio.Lock()

    async def generate(self) -> dict:
        now = datetime.now(UTC)
        day, start, end = previous_day(now, self.config["report_timezone"])
        rows = await asyncio.to_thread(self.data.mileage, day)
        if len(rows) != self.config["fleet_size"]:
            raise RuntimeError(f"Yesterday's mileage is incomplete: {len(rows)}/{self.config['fleet_size']} vehicles.")
        progress = await asyncio.to_thread(self.store.get, "injector-checkpoint.json")
        if not progress or progress["through"] < utc_text(end):
            raise RuntimeError("Telemetry has not yet covered the complete reporting day.")
        total = math.fsum(row["DistanceKm"] for row in rows)
        active = sum(row["DistanceKm"] > 0 for row in rows)
        refresh = await asyncio.to_thread(self.data.refresh_lakehouse)
        await asyncio.to_thread(self.store.put, "lakehouse-refresh.json", refresh)
        result = await self.agent.ask(
            f"Prepare the morning operations briefing for ReportDate '{day.isoformat()}' only. "
            f"The verified Eventhouse total is {total:.3f} km across {active} active vehicles "
            f"out of {len(rows)} registered vehicles, for [{utc_text(start)}, {utc_text(end)}). "
            "Query DailyMileage for this date and cross-check it against that total. "
            "Summarize the leading branches, top three vehicles and operational actions. "
            "If the Lakehouse total has not caught up, state the discrepancy explicitly. "
            "Do not include other dates or today's partial data."
        )
        briefing = {
            "reportDate": day.isoformat(), "periodStart": utc_text(start), "periodEnd": utc_text(end),
            "timeZone": self.config["report_timezone"], "totalKm": round(total, 3),
            "activeVehicles": active, "totalVehicles": len(rows),
            "text": f"**{total:,.1f} km driven yesterday**\n\n" + result["answer"],
            "generatedAt": utc_text(now), "source": result["source"], "rows": rows,
        }
        await asyncio.to_thread(self.store.put, "latest-briefing.json", briefing)
        return briefing

    async def deliver(self) -> dict:
        async with self.lock:
            day, _, _ = previous_day(datetime.now(UTC), self.config["report_timezone"])
            key = f"briefing-delivered-{day.isoformat()}.json"
            previous = await asyncio.to_thread(self.store.get, key)
            briefing = await asyncio.to_thread(self.store.get, "latest-briefing.json")
            if previous:
                return {"briefing": briefing, "message": f"Already delivered to Teams at {previous['sentAt']}."}
            if self.teams is None:
                raise RuntimeError("Teams delivery is not configured on this application instance.")
            if not briefing or briefing["reportDate"] != day.isoformat():
                briefing = await self.generate()
            message_id = await self.teams.send_briefing(briefing)
            receipt = {"reportDate": day.isoformat(), "sentAt": utc_text(datetime.now(UTC)), "messageId": message_id}
            await asyncio.to_thread(self.store.put, key, receipt)
            await asyncio.to_thread(self.store.put, "last-delivery.json", receipt)
            return {"briefing": briefing, "message": "Delivered to your Caldova Teams personal chat."}

    async def due(self, now: datetime) -> bool:
        local = now.astimezone(ZoneInfo(self.config["report_timezone"]))
        paused = await asyncio.to_thread(self.store.get, "briefing-control.json") or {}
        if local.hour < self.config["report_hour"] or paused.get("paused"):
            return False
        day, _, _ = previous_day(now, self.config["report_timezone"])
        return not await asyncio.to_thread(self.store.get, f"briefing-delivered-{day.isoformat()}.json")
