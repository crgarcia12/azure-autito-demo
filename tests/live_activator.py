"""Verify native Activator opens the case before delayed reconciliation can do so."""

from datetime import UTC, datetime
import json
import time
import uuid

import httpx

from tools.cloud import Cloud, ROOT, load_state


def main():
    cloud, state = Cloud(), load_state()
    token = cloud.credential.get_token(f"api://{state['agent_app_id']}/.default").token
    event_id = uuid.uuid4()
    case_id = "CDI-" + uuid.uuid5(uuid.NAMESPACE_URL, str(event_id)).hex[:10].upper()
    with httpx.Client(headers={"Authorization": f"Bearer {token}", "X-Caldova-Request": "fleet-app"}, timeout=90) as client:
        fleet = client.get(state["appUrl"] + "/api/fleet")
        fleet.raise_for_status()
        vehicle = next(item for item in fleet.json()["vehicles"] if not item.get("IncidentId") and item["Status"] != "maintenance")
        response = client.post(state["appUrl"] + "/api/telemetry/impact", json={"vehicle_id": vehicle["VehicleId"], "event_id": str(event_id)})
        response.raise_for_status()
        started = time.monotonic()
        while time.monotonic() - started < 170:
            time.sleep(8)
            response = client.get(state["appUrl"] + "/api/incidents")
            response.raise_for_status()
            case = next((item for item in response.json()["cases"] if item["id"] == case_id), None)
            if case and case.get("detection_origin") == "fabric_pipeline":
                assert case["status"] == "awaiting_report"
                assert case.get("fabric_pipeline_run_id")
                result = {
                    "case_id": case_id, "event_id": str(event_id),
                    "detected_by": case["detection_origin"],
                    "pipeline_run_id": case["fabric_pipeline_run_id"],
                    "elapsed_seconds": round(time.monotonic() - started, 2),
                    "verified_at": datetime.now(UTC).isoformat(),
                }
                (ROOT / ".local" / "primary-activator-result.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
                print(json.dumps(result))
                return
    raise RuntimeError("The native Activator did not open the case before the three-minute reconciliation delay.")


if __name__ == "__main__":
    main()
