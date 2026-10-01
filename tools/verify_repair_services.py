from __future__ import annotations

import argparse
import asyncio
from datetime import UTC, datetime
import json
import os
import uuid

from fleet.domain import utc_text
from fleet.evidence import EvidenceService
from fleet.fabric import FabricData
from fleet.insurance import CustomerReport, Incidents
from fleet.repair_workflow import RepairWorkflow
from fleet.storage import StateStore
from tools.cloud import Cloud, ROOT, load_state
from tools.deploy import app_path


async def main(approve: bool):
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
        vehicle = FabricData().latest()[2]
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
        workflow.evidence.add_photo(case["id"], (ROOT / "static" / "demo-assets" / "bumper-dent.jpg").read_bytes())
        cases.submit(case["id"], CustomerReport(
            safe=True, injuries=False,
            description="The rear bumper contacted a low bollard while parking. There is a dent and scuffing on the plastic bumper. Nobody was injured and no other vehicle was involved.",
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
            if not approve:
                print(json.dumps({"case": case["id"], "recommendation": case["recommendation"]}, ensure_ascii=True))
                return
            cases.approve(case["id"], case["version"], "Caldova end-to-end verification")
        if case["status"] == "booked":
            result = cases.public(case)
            result["timeline"] = cases.timeline(case["id"])
            (ROOT / ".local" / "repair-verified.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
            print(json.dumps({"case": case["id"], "status": case["status"], "booking": case["booking"], "emails": len(case["correspondence"])}))
            return
        await workflow.cycle()
        await asyncio.sleep(10)
    raise TimeoutError("The real-service workflow did not complete within the verification window.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Verify actual model, Copilot Studio and Exchange services using isolated local case state.")
    parser.add_argument("--approve", action="store_true")
    args = parser.parse_args()
    asyncio.run(main(args.approve))
