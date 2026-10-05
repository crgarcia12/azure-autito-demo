"""Prepare one quoted MINI incident and one untouched reporting journey."""
from __future__ import annotations

import argparse
from datetime import UTC, datetime
import hashlib
import json
import time
from urllib.parse import urlparse
import uuid

import httpx

from fleet.demo_case import CUSTOMER_EMAIL, CUSTOMER_NAME, DESCRIPTION, VEHICLE_ID
from fleet.domain import utc_text
from fleet.fabric import FabricData
from tools.cloud import FABRIC, ROOT, Cloud, load_state

PHOTOS = [ROOT / "media" / "crash2.png", ROOT / "media" / "crash1.png"]
RECEIPT = ROOT / ".local" / "two-mini-demo.json"


def save(receipt: dict) -> None:
    temporary = RECEIPT.with_suffix(".tmp")
    temporary.write_text(json.dumps(receipt, indent=2), encoding="utf-8")
    temporary.replace(RECEIPT)


def main(*, new_run: bool = False) -> None:
    cloud, state = Cloud(), load_state()
    receipt = json.loads(RECEIPT.read_text(encoding="utf-8")) if RECEIPT.exists() and not new_run else {
        "reset_id": str(uuid.uuid4()), "stage": "starting",
    }
    save(receipt)
    expected_photos = {hashlib.sha256(photo.read_bytes()).hexdigest() for photo in PHOTOS}
    origin = state["appUrl"]
    token = cloud.credential.get_token(f"api://{state['agent_app_id']}/.default").token
    headers = {"Authorization": "Bearer " + token, "X-Caldova-Request": "fleet-app"}
    with httpx.Client(headers=headers, timeout=180) as operator:
        def request(method: str, path: str, **kwargs):
            response = operator.request(method, origin + path, **kwargs)
            if response.is_error:
                raise RuntimeError(f"{method} {path} failed ({response.status_code}): {response.text[:1000]}")
            return response.json()

        if "ready_case_id" not in receipt:
            reset = request("POST", "/api/demo/reset-mini", json={
                "reset_id": receipt["reset_id"], "confirmation": "reset-mini",
            }, timeout=600)
            receipt.update(ready_case_id=reset["case_id"], stage="reporting")
            save(receipt)
        ready_id = receipt["ready_case_id"]
        case = request("GET", "/api/incidents/" + ready_id)
        if case.get("approval") or case.get("booking"):
            raise RuntimeError("This prepared case has already been approved. Use --new-run for a separate presentation.")
        if case["status"] == "awaiting_report":
            if case.get("evidence_history"):
                raise RuntimeError("The presenter requested additional evidence. That request will not be overwritten.")
            link = request("POST", f"/api/incidents/{ready_id}/link", json={})["url"]
            customer_headers = {"X-Incident-Token": urlparse(link).fragment, "X-Caldova-Request": "fleet-app"}
            with httpx.Client(headers=customer_headers, timeout=120) as customer:
                existing = {photo["sha256"] for photo in case["photos"]}
                if not existing.issubset(expected_photos):
                    raise RuntimeError("The case contains a different customer photograph; preparation stopped.")
                for photo in PHOTOS:
                    if hashlib.sha256(photo.read_bytes()).hexdigest() in existing:
                        continue
                    with photo.open("rb") as image:
                        response = customer.post(origin + f"/customer/{ready_id}/photos",
                                                 files={"photo": (photo.name, image, "image/png")})
                        response.raise_for_status()
                response = customer.post(origin + f"/customer/{ready_id}/submit", json={
                    "description": DESCRIPTION, "customer_name": CUSTOMER_NAME,
                    "customer_email": CUSTOMER_EMAIL, "consent_to_share_redacted": True,
                })
                response.raise_for_status()
            print("Customer report submitted with both MINI photos:", ready_id, flush=True)
        elif {photo["sha256"] for photo in case["photos"]} != expected_photos:
            raise RuntimeError("The existing submitted report does not contain exactly the two expected photographs.")

        if "fresh_event" not in receipt:
            vehicle = next(v for v in request("GET", "/api/fleet")["vehicles"] if v["VehicleId"] == VEHICLE_ID)
            event_id = str(uuid.uuid4())
            receipt.update(
                fresh_case_id="CDI-" + uuid.uuid5(uuid.NAMESPACE_URL, event_id).hex[:10].upper(),
                fresh_event={
                    "EventId": event_id, "VehicleId": VEHICLE_ID, "Timestamp": utc_text(datetime.now(UTC)),
                    "PeakAccelerationG": 3.7, "DeltaVKmh": 6.0, "SpeedBeforeKmh": 6.0, "SpeedAfterKmh": 0.0,
                    "Latitude": vehicle["Latitude"], "Longitude": vehicle["Longitude"],
                    "OdometerKm": vehicle["OdometerKm"], "Source": "vehicle-telemetry",
                },
            )
            save(receipt)
        if not receipt.get("fresh_impact_ingested"):
            # Two independent presentation stages intentionally use the same MINI, without changing normal UI guards.
            FabricData().ingest("VehicleImpacts", [receipt["fresh_event"]])
            receipt.update(fresh_impact_ingested=True, stage="awaiting_quotes")
            save(receipt)
        if not receipt.get("pipeline_requested"):
            cloud.request("POST", f"{FABRIC}/workspaces/{state['workspace_id']}/items/{state['impact_pipeline_id']}/jobs/instances?jobType=Pipeline", {}, wait=False)
            receipt["pipeline_requested"] = True
            save(receipt)
        fresh_id = receipt["fresh_case_id"]
        last = None
        deadline = time.monotonic() + 900
        while time.monotonic() < deadline:
            current = request("GET", "/api/incidents")["cases"]
            ready = next((case for case in current if case["id"] == ready_id), None)
            fresh = next((case for case in current if case["id"] == fresh_id), None)
            if ready is None:
                raise RuntimeError("The prepared case was removed during setup.")
            status = (ready["status"], len(ready["quotes"]), fresh["status"] if fresh else "detecting")
            if status != last:
                print(f"Prepared: {ready_id} {status[0]}, {status[1]}/3 offers | Fresh: {fresh_id} {status[2]}", flush=True)
                last = status
            for case in (ready, fresh):
                if case and case.get("last_error"):
                    raise RuntimeError(f"{case['id']}: {case['last_error']['message']}")
            if ready["status"] in {"report_review_required", "assistance_required", "quote_review_required"}:
                raise RuntimeError("The actual evidence/policy review requires attention; no review gate was bypassed.")
            if fresh and (fresh["status"] != "awaiting_report" or fresh["report_received"] or fresh["photos"]):
                raise RuntimeError("The fresh case has already been used; the presenter's report will not be overwritten.")
            notices = [m for m in (fresh or {}).get("correspondence", []) if "[REPORT]" in m["subject"]]
            if (ready["status"] == "recommendation_ready" and len(ready["quotes"]) == 3
                    and ready.get("recommendation", {}).get("agent") and fresh and len(notices) == 1):
                if {case["id"] for case in current} != {ready_id, fresh_id}:
                    raise RuntimeError("Other pending cases were created during preparation. They were not silently removed.")
                assert ready["repair_report"]["privacy_passed"]
                assert {photo["sha256"] for photo in ready["photos"]} == expected_photos
                assert ready["recommendation"]["garage_id"] == "metro"
                assert set(ready["recommendation"]["eligible_garage_ids"]) == {"metro", "riverside"}
                assert not ready.get("approval") and not fresh.get("approval")
                receipt.update(
                    stage="complete", verified_at=utc_text(datetime.now(UTC)),
                    ready_url=origin + "/#incidents?case=" + ready_id,
                    fresh_url=origin + "/#incidents?case=" + fresh_id,
                    fresh_email_subject=notices[0]["subject"], fresh_email_at=notices[0]["at"],
                    photos=[photo.name for photo in PHOTOS],
                )
                save(receipt)
                print(json.dumps({key: receipt[key] for key in (
                    "ready_case_id", "ready_url", "fresh_case_id", "fresh_url", "fresh_email_subject", "photos",
                )}, indent=2), flush=True)
                return
            time.sleep(5)
    raise TimeoutError("The two MINI cases did not reach their required states. Rerun to resume this preparation.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--new-run", action="store_true", help="Delete prior MINI cases and prepare a new pair.")
    main(new_run=parser.parse_args().new_run)
