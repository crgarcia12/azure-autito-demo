from __future__ import annotations

import argparse
import asyncio
from datetime import UTC, datetime
import json
import os
import re
import uuid
import httpx

from fleet.domain import utc_text
from fleet.evidence import EvidenceService
from fleet.fabric import FabricData
from fleet.insurance import CustomerReport, IncidentError, Incidents
from fleet.repair_workflow import RepairWorkflow
from fleet.storage import StateStore
from fleet.demo_case import DESCRIPTION, PHOTO, VEHICLE_ID
from tools.cloud import Cloud, ROOT, load_state
from tools.deploy import app_path


async def main(approve: bool, reuse_brief: str | None = None):
    cloud, state = Cloud(), load_state()
    app_settings = cloud.request("POST", app_path(state) + "/config/appsettings/list?api-version=2023-12-01")["properties"]
    os.environ["FLEET_AGENT_SECRET"] = app_settings["FLEET_AGENT_SECRET"]
    os.environ["FLEET_STUDIO_CHANNEL_SECRETS"] = app_settings["FLEET_STUDIO_CHANNEL_SECRETS"]
    store = StateStore(ROOT / ".local" / "repair-verification.sqlite3")
    cases = Incidents(store)
    current = store.get("verification-case")
    if current:
        case = cases.get(current["id"])
    else:
        vehicle = next(row for row in FabricData().latest() if row["VehicleId"] == VEHICLE_ID)
        event = {
            "EventId": str(uuid.uuid4()), "VehicleId": vehicle["VehicleId"],
            "Timestamp": utc_text(datetime.now(UTC)), "PeakAccelerationG": 3.7, "DeltaVKmh": 6,
            "SpeedBeforeKmh": 6, "SpeedAfterKmh": 0,
            "Latitude": vehicle["Latitude"], "Longitude": vehicle["Longitude"],
        }
        case = cases.create(event, vehicle)
        store.put("verification-case", {"id": case["id"], "token": case["token"]})
    print("Verification case:", case["id"], flush=True)
    workflow = RepairWorkflow(cases)
    if case["status"] == "awaiting_report":
        if reuse_brief:
            if not re.fullmatch(r"CDI-[A-F0-9]{10}", reuse_brief):
                raise ValueError("Invalid source case.")
            token = cloud.credential.get_token(f"api://{state['agent_app_id']}/.default").token
            async with httpx.AsyncClient(headers={"Authorization": "Bearer " + token}, timeout=120) as client:
                source = await client.get(state["appUrl"] + "/api/incidents/" + reuse_brief)
                source.raise_for_status()
                source = source.json()
                report = source.get("repair_report", {})
                if (source["vehicle_id"] != VEHICLE_ID or not report.get("privacy_passed")
                        or report.get("requires_manual_review") or report.get("repair_category") != "bumper_cosmetic"):
                    raise RuntimeError("Only an already privacy-cleared, eligible MINI brief can be replayed. No review gate is bypassed.")
                pdf = await client.get(state["appUrl"] + "/api/incidents/" + reuse_brief + "/brief.pdf")
                pdf.raise_for_status()
                if not pdf.content.startswith(b"%PDF"):
                    raise RuntimeError("The source case did not return its actual repair brief PDF.")
            directory = workflow.evidence.root / case["id"]
            directory.mkdir(exist_ok=True)
            (directory / "repair-brief.pdf").write_bytes(pdf.content)
            def replay(record):
                record.update(status="report_ready", repair_report=report,
                              verification_replay={"source_case_id": reuse_brief, "scope": "Agent tools; image assessment is not repeated."})
                return record["verification_replay"]
            cases.change(case["id"], "verified_brief_replayed", "Agent-tool integration verification", replay)
        else:
            workflow.evidence.add_photo(case["id"], PHOTO.read_bytes())
            cases.submit(case["id"], CustomerReport(
                safe=True, injuries=False,
                description=DESCRIPTION,
                customer_name="Jordan Example", customer_email="jordan.example@caldova08667473.onmicrosoft.com",
                consent_to_share_redacted=True,
            ))
    for _ in range(24):
        case = cases.get(case["id"])
        print("Stage:", case["status"], flush=True)
        if case["status"] == "report_review_required":
            print("Evidence review:", json.dumps(case["repair_report"], ensure_ascii=True))
            raise RuntimeError("The real evidence model required manual review; no quote was fabricated.")
        if case["status"] == "recommendation_ready" and case["recommendation"].get("agent"):
            await workflow.notify_operator(case["id"], booked=False)
            case = cases.get(case["id"])
            assert case["recommendation"]["garage_id"] == "metro"
            assert set(case["recommendation"]["eligible_garage_ids"]) == {"metro", "riverside"}
            assert all(q["agent_id"] == state["studio_agents"]["cdv_" + q["garage_id"] + "repairs"]["id"] for q in case["quotes"].values())
            if not approve:
                print(json.dumps({"case": case["id"], "recommendation": case["recommendation"]}, ensure_ascii=True))
                return
            try:
                cases.approve(case["id"], case["version"], "Agent-tool verification",
                              garage_id="alder", reason="Attempt to choose the cheapest aftermarket offer.")
            except IncidentError as error:
                if "RP-02" not in str(error):
                    raise
            else:
                raise RuntimeError("The aftermarket override was not blocked.")
            cases.approve(case["id"], case["version"], "Caldova end-to-end verification")
        if case["status"] == "booked":
            await workflow.notify_operator(case["id"], booked=True)
            case = cases.get(case["id"])
            assert case["approval"]["quote_sha256"] == case["booking"]["quote_sha256"]
            result = cases.public(case)
            result["timeline"] = cases.timeline(case["id"])
            (ROOT / ".local" / "repair-verified.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
            print(json.dumps({"case": case["id"], "status": case["status"], "booking": case["booking"], "emails": len(case["correspondence"])}))
            return
        await workflow.cycle()
        failure = store.get("repair-error/" + case["id"])
        if failure:
            raise RuntimeError("Repair verification stopped with preserved receipts: " + failure["message"])
        await asyncio.sleep(10)
    raise TimeoutError("The real-service workflow did not complete within the verification window.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Verify actual Foundry evidence, secured Studio agents and app-managed Exchange delivery with isolated case state.")
    parser.add_argument("--approve", action="store_true")
    parser.add_argument("--reuse-brief", help="Replay an actual already-cleared MINI brief to test agent tools without repeating image assessment.")
    args = parser.parse_args()
    asyncio.run(main(args.approve, args.reuse_brief))
