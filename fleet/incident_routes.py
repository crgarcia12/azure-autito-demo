from __future__ import annotations

import asyncio
from datetime import UTC, datetime
import hashlib
import hmac
import os
import re
import secrets
import uuid

from aiohttp import web
from pydantic import BaseModel, ConfigDict, Field

from fleet.config import ROOT
from fleet.domain import utc_text
from fleet.insurance import CustomerReport, IncidentError, Incidents, insurance_config
from fleet.repair_workflow import RepairWorkflow


class ImpactRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    vehicle_id: str = Field(pattern=r"^CD-\d{3}$")
    event_id: uuid.UUID


class ApprovalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: int = Field(gt=0)
    garage_id: str | None = Field(default=None, max_length=40)
    reason: str = Field(default="", max_length=500)


class EvidenceFollowUp(ApprovalRequest):
    reason: str = Field(min_length=15, max_length=1000)


def customer_auth(request):
    return request.app["incidents"].authorize(
        request.match_info["case"], request.headers.get("X-Incident-Token", ""),
    )


async def case_list(request):
    cases = request.app["incidents"].list()
    for case in cases:
        case["last_error"] = request.app["store"].get("repair-error/" + case["id"])
    return web.json_response({"cases": cases})


async def case_detail(request):
    cases = request.app["incidents"]
    case = cases.public(cases.get(request.match_info["case"]))
    case["timeline"] = cases.timeline(case["id"])
    case["last_error"] = request.app["store"].get("repair-error/" + case["id"])
    return web.json_response(case)


async def impact(request):
    body = ImpactRequest.model_validate(await request.json())
    if any(case["vehicle_id"] == body.vehicle_id and case["status"] not in {"closed", "not_an_incident"}
           for case in request.app["incidents"].list()):
        raise IncidentError("This vehicle already has an active incident. Select another vehicle for a new journey.")
    data = request.app["data"]
    rows = await asyncio.to_thread(data.query, "declare query_parameters(vehicle:string); FleetLatest() | where VehicleId == vehicle", {"vehicle": body.vehicle_id})
    if len(rows) != 1:
        raise IncidentError("The selected vehicle has no current Fabric state.", 404)
    vehicle = rows[0]
    event = {
        "EventId": str(body.event_id), "VehicleId": body.vehicle_id,
        "Timestamp": utc_text(datetime.now(UTC)), "PeakAccelerationG": 3.7,
        "DeltaVKmh": 6.0, "SpeedBeforeKmh": 6.0, "SpeedAfterKmh": 0.0,
        "Latitude": vehicle["Latitude"], "Longitude": vehicle["Longitude"],
        "OdometerKm": vehicle["OdometerKm"], "Source": "vehicle-telemetry",
    }
    await asyncio.to_thread(data.ingest, "VehicleImpacts", [event])
    return web.json_response({"event_id": event["EventId"], "status": "ingested", "message": "Impact telemetry ingested into Fabric. The detection workflow will open an incident."})


async def detect_impacts(app, *, reconciliation: bool = False) -> list[dict]:
    data, cases = app["data"], app["incidents"]
    query = "SuspectedImpacts() | where Timestamp > ago(2d)"
    if reconciliation:
        query += " | where Timestamp < ago(3m)"
    events = await asyncio.to_thread(data.query, query + " | order by Timestamp asc")
    created = []
    for event in events:
        rows = await asyncio.to_thread(data.query, "declare query_parameters(vehicle:string); FleetLatest() | where VehicleId == vehicle", {"vehicle": event["VehicleId"]})
        if len(rows) != 1:
            raise RuntimeError("Impact telemetry could not be associated with its Fabric vehicle.")
        case = await asyncio.to_thread(cases.create, event, rows[0])
        if "token" in case:
            app["store"].put(f"incident-link/{case['id']}", {"token": case["token"]})
            created.append(case)
    return created


async def detection_callback(request):
    expected = os.environ.get("FLEET_FABRIC_TRIGGER_SECRET", "")
    actual = request.headers.get("X-Caldova-Fabric", "")
    if not expected or not hmac.compare_digest(expected, actual):
        raise web.HTTPForbidden(text="Invalid Fabric integration credentials.")
    body = await request.json()
    run_id = str(uuid.UUID(body["pipeline_run_id"])) if body.get("pipeline_run_id") else None
    created = await detect_impacts(request.app)
    for case in created:
        def mark_origin(record):
            record["detection_origin"] = "fabric_pipeline"
            record["fabric_pipeline_run_id"] = run_id
            return {"pipeline_run_id": run_id}
        request.app["incidents"].change(case["id"], "fabric_action_executed", "Fabric pipeline", mark_origin)
    request.app["store"].put("fabric-callback-health", {
        "at": utc_text(datetime.now(UTC)), "opened": [case["id"] for case in created],
        "source": "Fabric pipeline callback",
        "pipeline_run_id": run_id,
    })
    return web.json_response({"opened": [case["id"] for case in created]})


async def report_link(request):
    cases = request.app["incidents"]
    case_id = request.match_info["case"]
    cases.get(case_id)
    saved = request.app["store"].get(f"incident-link/{case_id}")
    token = saved["token"] if saved else None
    if token:
        try:
            cases.authorize(case_id, token)
        except IncidentError as error:
            if error.status != 403:
                raise
            token = None
    if not token:
        token = cases.new_link(case_id)
    url = request.app["config"]["appUrl"] + f"/report/{case_id}#{token}"
    request.app["store"].put(f"incident-link/{case_id}", {"token": token})
    return web.json_response({
        "url": url,
        "text": "Caldova: We detected a possible impact involving your rental car. In an emergency call 999. When it is safe, use this link to report the incident.",
    })


async def report_page(request):
    if not re.fullmatch(r"CDI-[A-F0-9]{10}", request.match_info["case"]):
        raise web.HTTPNotFound()
    return web.FileResponse(ROOT / "static" / "report.html", headers={
        "Referrer-Policy": "no-referrer", "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff",
        "Content-Security-Policy": "default-src 'self'; img-src 'self' blob: data:; style-src 'self'; script-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'",
    })


async def customer_case(request):
    case = customer_auth(request)
    return web.json_response(request.app["incidents"].public(case, customer=True))


async def upload(request):
    case = customer_auth(request)
    if not request.content_type.startswith("multipart/"):
        raise IncidentError("Upload the photo using multipart form data.", 400)
    reader = await request.multipart()
    field = await reader.next()
    if field is None or field.name != "photo":
        raise IncidentError("Upload one photo per request.", 400)
    payload = bytearray()
    limit = insurance_config()["maximum_photo_bytes"]
    while chunk := await field.read_chunk():
        payload.extend(chunk)
        if len(payload) > limit:
            raise IncidentError("Each photo must be 10 MB or smaller.", 413)
    result = await asyncio.to_thread(request.app["repairs"].evidence.add_photo, case["id"], bytes(payload))
    return web.json_response(result, status=201)


async def submit(request):
    case = customer_auth(request)
    report = CustomerReport.model_validate(await request.json())
    result = await asyncio.to_thread(request.app["incidents"].submit, case["id"], report)
    return web.json_response({"id": result["id"], "status": result["status"], "message": "Your incident report has been received."})


async def photo(request):
    if request.query.get("original") == "true":
        path, mime = request.app["repairs"].evidence.original_path(request.match_info["case"], request.match_info["photo"])
        return web.FileResponse(path, headers={
            "Content-Type": mime, "Content-Disposition": "attachment",
            "Cache-Control": "private, no-store",
        })
    path = request.app["repairs"].evidence.photo_path(
        request.match_info["case"], request.match_info["photo"],
        redacted=request.query.get("redacted") == "true",
    )
    return web.FileResponse(path, headers={"Cache-Control": "private, no-store"})


async def pdf(request):
    case_id = request.match_info["case"]
    request.app["incidents"].get(case_id)
    path = request.app["repairs"].evidence.root / case_id / "repair-brief.pdf"
    if not path.is_file():
        raise IncidentError("The repair brief has not been generated yet.", 404)
    return web.FileResponse(path, headers={"Content-Disposition": f'inline; filename="{case_id}-repair-brief.pdf"', "Cache-Control": "private, no-store"})


async def approve(request):
    body = ApprovalRequest.model_validate(await request.json())
    result = request.app["incidents"].approve(
        request.match_info["case"], body.version, request.app["config"]["report_recipient"],
        garage_id=body.garage_id, reason=body.reason,
    )
    return web.json_response(result)


async def follow_up(request):
    body = EvidenceFollowUp.model_validate(await request.json())
    result = request.app["incidents"].request_more_evidence(
        request.match_info["case"], body.version, request.app["config"]["report_recipient"], body.reason,
    )
    return web.json_response(result)


async def insurance_health(request):
    store, config = request.app["store"], request.app["config"]
    return web.json_response({
        "workflow": store.get("repair-worker-health"),
        "agents": [{"name": value["name"], "id": value["id"], "schema": key} for key, value in config.get("studio_agents", {}).items()],
        "mailboxes": [{"name": "Caldova Claims", "address": insurance_config()["claims_mailbox"]}] + [
            {"name": garage["name"], "address": garage["mailbox"]} for garage in insurance_config()["garages"]
        ],
        "fabric": {"workspace_id": config["workspace_id"], "activator_id": config.get("impact_activator_id"),
                   "last_callback": store.get("fabric-callback-health")},
        "evidence": {
            "provider": "Microsoft Foundry Agent Service",
            "project": config.get("foundry_project_name"),
            "project_endpoint": config.get("foundry_project_endpoint"),
            "agent": config.get("foundry_agent_name"),
            "version": config.get("foundry_agent_version"),
        },
    })


def attach(app):
    app["incidents"] = Incidents(app["store"])
    app["repairs"] = RepairWorkflow(app["incidents"])
    app.router.add_get("/api/incidents", case_list)
    app.router.add_get("/api/incidents/{case}", case_detail)
    app.router.add_post("/api/incidents/{case}/link", report_link)
    app.router.add_post("/api/incidents/{case}/approve", approve)
    app.router.add_post("/api/incidents/{case}/request-evidence", follow_up)
    app.router.add_get("/api/incidents/{case}/photos/{photo}", photo)
    app.router.add_get("/api/incidents/{case}/brief.pdf", pdf)
    app.router.add_get("/api/insurance/health", insurance_health)
    app.router.add_post("/api/telemetry/impact", impact)
    app.router.add_post("/integrations/fabric/impacts", detection_callback)
    app.router.add_get("/report/{case}", report_page)
    app.router.add_get("/customer/{case}", customer_case)
    app.router.add_post("/customer/{case}/photos", upload)
    app.router.add_post("/customer/{case}/submit", submit)
