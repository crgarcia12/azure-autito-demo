from __future__ import annotations

import asyncio
import base64
from contextlib import suppress
from datetime import UTC, datetime
import json
import logging
import math
import os
import re
import time
from urllib.parse import urlparse
import uuid

from aiohttp import web
from pydantic import BaseModel, ValidationError

from fleet.agent import ChatRequest, FleetAgent
from fleet.briefing import BriefingService
from fleet.capacity import morning_wakeup
from fleet.config import ROOT, data_credential, settings
from fleet.domain import BRANCHES, previous_day, utc_text
from fleet.fabric import FabricData
from fleet.simulator import motions, tick
from fleet.storage import LeaseBusyError, StateStore
from fleet.teams import TeamsAgent
from fleet.insurance import INACTIVE_STATUSES, IncidentError
from fleet.demo_case import POSITION_KEY, VEHICLE_ID
from fleet.incident_routes import attach as attach_incidents, detect_impacts

LOG = logging.getLogger("caldova")


class InjectorControl(BaseModel):
    paused: bool


@web.middleware
async def errors(request, handler):
    try:
        return await handler(request)
    except web.HTTPException as error:
        if request.path.startswith(("/api/", "/customer/", "/integrations/")):
            return web.json_response({"error": error.reason}, status=error.status)
        raise
    except IncidentError as error:
        LOG.warning("Incident request rejected at %s: %s", request.path, error)
        return web.json_response({"error": str(error)}, status=error.status)
    except (ValidationError, json.JSONDecodeError) as error:
        LOG.warning("Invalid request %s: %s", request.path, error)
        return web.json_response({"error": "Invalid request. Check field types, lengths and required values."}, status=400)
    except Exception:
        reference = uuid.uuid4().hex[:10]
        LOG.exception("Request failed [%s]: %s", reference, request.path)
        return web.json_response(
            {"error": f"The operation could not be completed. No data was substituted. Reference: {reference}"},
            status=502,
        )


@web.middleware
async def access(request, handler):
    if request.path in {"/health/live", "/api/messages", "/privacy", "/terms", "/integrations/fabric/impacts"}:
        return await handler(request)
    customer_path = request.path.startswith(("/report/", "/customer/")) or request.path in {
        "/static/report.css", "/static/report.js", "/static/mark.svg",
    }
    if os.environ.get("WEBSITE_INSTANCE_ID") and not customer_path:
        principal = request.headers.get("X-MS-CLIENT-PRINCIPAL")
        if not principal:
            raise web.HTTPUnauthorized(text="Sign in with the configured operator account.")
        try:
            claims = json.loads(base64.b64decode(principal))["claims"]
            ids = {claim["val"] for claim in claims if claim["typ"].endswith("objectidentifier") or claim["typ"] == "oid"}
            tenants = {claim["val"] for claim in claims if claim["typ"].endswith("tenantid") or claim["typ"] == "tid"}
        except (ValueError, KeyError, TypeError) as error:
            raise web.HTTPUnauthorized() from error
        config = request.app["config"]
        if config["admin_object_id"] not in ids or config["tenant_id"] not in tenants:
            raise web.HTTPForbidden(text="This fleet workspace is restricted to its configured operator.")
    if request.method == "POST" and request.path != "/api/messages":
        if request.headers.get("X-Caldova-Request") != "fleet-app":
            raise web.HTTPForbidden(text="Missing same-origin request header.")
        origin = request.headers.get("Origin")
        if origin and urlparse(origin).netloc != request.host:
            raise web.HTTPForbidden(text="Cross-origin requests are not accepted.")
    response = await handler(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "same-origin"
    if customer_path:
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"
    if request.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    return response


async def index(request):
    return web.FileResponse(ROOT / "static" / "index.html")


async def config_endpoint(request):
    config = request.app["config"]
    return web.json_response({
        "mapsClientId": config["mapsClientId"],
        "fabricUrl": f"https://app.fabric.microsoft.com/groups/{config['workspace_id']}/list?experience=fabric",
        "ontologyUrl": f"https://app.fabric.microsoft.com/groups/{config['workspace_id']}/ontologies/{config['ontology_id']}",
        "teamsUrl": f"https://teams.microsoft.com/l/app/{config['agent_app_id']}?tenantId={config['tenant_id']}",
        "copilotUrl": f"https://m365.cloud.microsoft/chat/?auth=2&tenantId={config['tenant_id']}",
    })


async def map_token(request):
    token = await asyncio.to_thread(data_credential().get_token, "https://atlas.microsoft.com/.default")
    return web.json_response({"token": token.token, "expiresOn": token.expires_on})


def snapshot(app) -> dict:
    config, data, store = app["config"], app["data"], app["store"]
    vehicles = data.latest()
    if not vehicles:
        raise RuntimeError("Fabric has no vehicle telemetry. Run historical seeding.")
    day, _, _ = previous_day(datetime.now(UTC), config["report_timezone"])
    mileage = data.mileage(day)
    trend_rows = data.query("FleetDailyMileage() | where IsComplete | summarize distanceKm=sum(DistanceKm) by ReportDate | order by ReportDate asc")
    branches = [
        {
            "branchId": branch["BranchId"], "city": branch["City"],
            "vehicles": sum(vehicle["BranchId"] == branch["BranchId"] for vehicle in vehicles),
            "distanceKm": math.fsum(row["DistanceKm"] for row in mileage if row["BranchId"] == branch["BranchId"]),
        } for branch in BRANCHES
    ]
    delivery = store.get("last-delivery.json")
    open_cases = {}
    for case in app["incidents"].list():
        if case["status"] not in INACTIVE_STATUSES:
            open_cases.setdefault(case["vehicle_id"], case)
    for vehicle in vehicles:
        if vehicle["VehicleId"] in open_cases:
            case = open_cases[vehicle["VehicleId"]]
            vehicle["IncidentId"] = case["id"]
            vehicle["IncidentStatus"] = case["status"]
            vehicle["Status"] = "incident"
            vehicle["Alert"] = "Incident detected"
    return {
        "asOf": utc_text(datetime.now(UTC)), "vehicles": vehicles,
        "yesterday": {"reportDate": day.isoformat(), "totalKm": math.fsum(row["DistanceKm"] for row in mileage)},
        "trend": trend_rows, "branches": sorted(branches, key=lambda b: b["distanceKm"], reverse=True),
        "lakehouse": store.get("lakehouse-refresh.json"),
        "injector": {**(store.get("injector-checkpoint.json") or {}), **(store.get("injector-control.json") or {"paused": False})},
        "briefing": store.get("latest-briefing.json"),
        "delivery": {"connected": store.get("teams-reference.json") is not None, "lastSent": delivery["sentAt"] if delivery else None},
    }


async def fleet_endpoint(request):
    app = request.app
    async with app["snapshot_lock"]:
        cached = app.get("snapshot")
        if cached is None or time.monotonic() - app["snapshot_time"] > 10:
            app["snapshot"] = await asyncio.to_thread(snapshot, app)
            app["snapshot_time"] = time.monotonic()
        return web.json_response(app["snapshot"])


async def history_endpoint(request):
    vehicle = request.match_info["vehicle"]
    if not re.fullmatch(r"CD-\d{3}", vehicle):
        raise web.HTTPBadRequest(text="Invalid vehicle identifier.")
    position = request.app["store"].get(POSITION_KEY) if vehicle == VEHICLE_ID else None
    since = datetime.fromisoformat(position["effective_at"].replace("Z", "+00:00")) if position else None
    points = await asyncio.to_thread(request.app["data"].history, vehicle, since=since)
    return web.json_response({"vehicleId": vehicle, "points": points})


async def chat_endpoint(request):
    body = ChatRequest.model_validate(await request.json())
    return web.json_response(await request.app["agent"].ask(body.question, body.history))


async def control_endpoint(request):
    body = InjectorControl.model_validate(await request.json())
    await asyncio.to_thread(request.app["store"].put, "injector-control.json", body.model_dump())
    request.app["snapshot_time"] = 0
    return web.json_response(body.model_dump())


async def briefing_endpoint(request):
    service = request.app["briefing"]
    if request.match_info["action"] == "send":
        result = await service.deliver()
    elif request.match_info["action"] == "generate":
        result = {"briefing": await service.generate()}
    else:
        raise web.HTTPNotFound()
    request.app["snapshot_time"] = 0
    return web.json_response(result)


async def health(request):
    return web.json_response({"status": "running", "service": "Fleet Operations", "buildId": request.app.get("build_id", "local")})


async def legal(request):
    page = "Privacy" if request.path == "/privacy" else "Terms of use"
    return web.Response(
        text=f"""<!doctype html><html lang="en"><meta charset="utf-8"><title>{page} | Fleet Operations</title>
        <body style="max-width:700px;margin:60px auto;font:16px/1.8 system-ui"><h1>Fleet Operations: {page}</h1>
        <p>This internal fleet operations application is restricted to the configured operator.
        Vehicle telemetry and business data are stored in the configured Microsoft Fabric workspace.
        Chat questions are processed by the Fabric data agent. Teams conversation references,
        recent conversation context, telemetry checkpoints and delivery receipts are stored on the application's persistent disk.</p>
        <p>Use this application for the authorized rental-fleet demonstration. Do not upload confidential customer data.
        AI-generated answers should be checked against their reporting period and underlying Fabric records.
        Daily Teams briefings can be paused by sending <strong>stop briefings</strong> to the agent.</p>
        <p>Contact the workspace administrator for access, retention and deletion requests.</p></body></html>""",
        content_type="text/html",
    )


async def worker(app):
    store, data, service = app["store"], app["data"], app["briefing"]
    movement = await asyncio.to_thread(motions, store)
    last_refresh = 0.0
    last_briefing_attempt = 0.0
    lease = None
    heartbeat = None

    async def renew_lease(current):
        while True:
            await asyncio.sleep(15)
            await asyncio.to_thread(current.renew)

    while True:
        try:
            if lease is None:
                lease = await asyncio.to_thread(store.lease, "fleet-worker")
                heartbeat = asyncio.create_task(renew_lease(lease))
            if heartbeat.done():
                heartbeat.result()
            await asyncio.to_thread(lease.renew)
            await asyncio.to_thread(morning_wakeup, store, datetime.now(UTC))
            async with app["fleet_data_lock"]:
                result = await asyncio.to_thread(tick, data, store, movement)
                await asyncio.to_thread(lease.renew)
                if time.monotonic() - last_refresh > app["config"]["lakehouse_refresh_seconds"]:
                    refreshed = await asyncio.to_thread(data.refresh_lakehouse)
                    await asyncio.to_thread(store.put, "lakehouse-refresh.json", refreshed)
                    last_refresh = time.monotonic()
            if app["teams"] is not None and time.monotonic() - last_briefing_attempt > 300:
                last_briefing_attempt = time.monotonic()
                if await service.due(datetime.now(UTC)):
                    await service.deliver()
            await asyncio.to_thread(store.put, "worker-health.json", {"state": "running", "at": utc_text(datetime.now(UTC))})
            lag = (datetime.now(UTC) - datetime.fromisoformat(result["through"].replace("Z", "+00:00"))).total_seconds()
            await asyncio.sleep(1 if lag > 60 and result["state"] != "paused" else 10)
        except asyncio.CancelledError:
            if heartbeat:
                heartbeat.cancel()
                with suppress(asyncio.CancelledError):
                    await heartbeat
            if lease:
                await asyncio.to_thread(lease.release)
            raise
        except LeaseBusyError:
            if heartbeat:
                heartbeat.cancel()
                with suppress(asyncio.CancelledError, LeaseBusyError):
                    await heartbeat
            lease = None
            LOG.warning("Another process owns the fleet worker lease; waiting.")
            await asyncio.sleep(20)
        except Exception:
            LOG.exception("Fleet worker operation failed; will retry without advancing failed state.")
            await asyncio.to_thread(store.put, "worker-health.json", {"state": "error", "at": utc_text(datetime.now(UTC))})
            await asyncio.sleep(20)


async def background(app):
    bootstrap = ROOT / "bootstrap.json"
    if bootstrap.exists():
        values = json.loads(bootstrap.read_text(encoding="utf-8"))
        for name, value in values.items():
            app["store"].create(name, value)
    tasks = []
    if os.environ.get("FLEET_WORKER_ENABLED", "true") == "true":
        tasks.append(asyncio.create_task(worker(app)))
    if os.environ.get("FLEET_REPAIR_WORKER_ENABLED", "false") == "true":
        tasks.append(asyncio.create_task(repair_worker(app)))
    yield
    for task in tasks:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task


async def repair_worker(app):
    lease = None
    heartbeat = None

    async def renew(current):
        while True:
            await asyncio.sleep(15)
            await asyncio.to_thread(current.renew)

    try:
        while True:
            try:
                if lease is None:
                    lease = await asyncio.to_thread(app["store"].lease, "repair-worker")
                    heartbeat = asyncio.create_task(renew(lease))
                if heartbeat.done():
                    heartbeat.result()
                await asyncio.to_thread(lease.renew)
            # The native Activator callback is primary; this reconciliation read catches missed callbacks.
                async with app["repairs"].lock:
                    await detect_impacts(app, reconciliation=True)
                await app["repairs"].cycle()
                app["store"].put("repair-worker-health", {"state": "running", "at": utc_text(datetime.now(UTC))})
            except LeaseBusyError:
                if heartbeat:
                    heartbeat.cancel()
                    with suppress(asyncio.CancelledError, LeaseBusyError):
                        await heartbeat
                lease = None
                LOG.warning("Another process owns the repair worker; waiting.")
            except Exception as error:
                LOG.exception("Repair workflow failed; case and send receipts have been preserved.")
                app["store"].put("repair-worker-health", {"state": "error", "at": utc_text(datetime.now(UTC)), "message": str(error)[:1200]})
            await asyncio.sleep(20)
    finally:
        if heartbeat:
            heartbeat.cancel()
            with suppress(asyncio.CancelledError, LeaseBusyError):
                await heartbeat
        if lease:
            await asyncio.to_thread(lease.release)


def create_app() -> web.Application:
    app = web.Application(middlewares=[errors, access], client_max_size=11 * 1024 * 1024)
    app["config"] = settings()
    build_file = ROOT / ".build.json"
    app["build_id"] = json.loads(build_file.read_text(encoding="utf-8"))["id"] if build_file.exists() else "local"
    app["store"] = StateStore()
    app["data"] = FabricData()
    app["agent"] = FleetAgent()
    app["teams"] = TeamsAgent(app["agent"], app["store"]) if os.environ.get("FLEET_AGENT_SECRET") else None
    if os.environ.get("WEBSITE_INSTANCE_ID") and app["teams"] is None:
        raise RuntimeError("The deployed fleet app requires Teams credentials.")
    if app["teams"]:
        app["teams"].attach(app)
        app.router.add_post("/api/messages", app["teams"].endpoint)
    app["briefing"] = BriefingService(app["data"], app["agent"], app["store"], app["teams"])
    app["snapshot_lock"] = asyncio.Lock()
    app["fleet_data_lock"] = asyncio.Lock()
    app["snapshot_time"] = 0.0
    attach_incidents(app)
    app.router.add_get("/", index)
    app.router.add_static("/static", ROOT / "static", show_index=False)
    app.router.add_get("/api/config", config_endpoint)
    app.router.add_get("/api/maps/token", map_token)
    app.router.add_get("/api/fleet", fleet_endpoint)
    app.router.add_get("/api/vehicles/{vehicle}/history", history_endpoint)
    app.router.add_post("/api/chat", chat_endpoint)
    app.router.add_post("/api/injector/control", control_endpoint)
    app.router.add_post("/api/briefing/{action}", briefing_endpoint)
    app.router.add_get("/health/live", health)
    app.router.add_get("/privacy", legal)
    app.router.add_get("/terms", legal)
    app.cleanup_ctx.append(background)
    return app


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    logging.getLogger("azure").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    web.run_app(create_app(), host="0.0.0.0" if os.environ.get("WEBSITE_INSTANCE_ID") else "127.0.0.1", port=int(os.environ.get("PORT", "8000")))
