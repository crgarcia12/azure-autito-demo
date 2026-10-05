"""Reset the hosted MINI journey, retaining fleet history and leaving reporting unsubmitted."""
from __future__ import annotations

import json
import time
import uuid

import httpx

from fleet.demo_case import VEHICLE_ID
from tools.cloud import Cloud, ROOT, load_state


def main() -> None:
    cloud, state = Cloud(), load_state()
    path = ROOT / ".local" / "mini-reset-receipt.json"
    previous = json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
    reset_id = previous["reset_id"] if previous and previous["stage"] != "complete" else str(uuid.uuid4())
    path.write_text(json.dumps({"reset_id": reset_id, "stage": "requested"}, indent=2), encoding="utf-8")
    token = cloud.credential.get_token(f"api://{state['agent_app_id']}/.default").token
    with httpx.Client(timeout=600, headers={"Authorization": "Bearer " + token, "X-Caldova-Request": "fleet-app"}) as client:
        response = client.post(state["appUrl"] + "/api/demo/reset-mini", json={
            "reset_id": reset_id, "confirmation": "reset-mini",
        })
        if response.is_error:
            raise RuntimeError(f"MINI reset did not complete ({response.status_code}): {response.text[:1000]}. Rerun this command to resume the same reset.")
        receipt = response.json()
        deadline = time.monotonic() + 180
        while time.monotonic() < deadline:
            fleet_response = client.get(state["appUrl"] + "/api/fleet")
            fleet_response.raise_for_status()
            vehicles = fleet_response.json()["vehicles"]
            if (len(vehicles) == 40 and sum(v["Status"] == "on-hire" and not v["Alert"] for v in vehicles) == 39
                    and [v["VehicleId"] for v in vehicles if v["Status"] == "incident"] == [VEHICLE_ID]):
                break
            time.sleep(5)
        else:
            raise RuntimeError("The reset created its case, but Fabric has not yet confirmed 39 cars on hire and the MINI incident. Rerun to resume verification.")
        response = client.get(state["appUrl"] + "/api/incidents")
        response.raise_for_status()
        cases = response.json()["cases"]
        if len(cases) != 1 or cases[0]["id"] != receipt["case_id"]:
            raise RuntimeError("The incident list does not contain exactly the new MINI case.")
        case = cases[0]
        notices = [message for message in case["correspondence"] if "[REPORT]" in message["subject"]]
        if case["status"] != "awaiting_report" or case["report_received"] or case["photos"] or len(notices) != 1:
            raise RuntimeError("The MINI journey is not a fresh, emailed, unsubmitted customer report.")
        receipt.update(verified_at=time.time(), on_hire=39, incident_detected=1, customer_email_subject=notices[0]["subject"])
        path.write_text(json.dumps(receipt, indent=2), encoding="utf-8")
        print(f"Ready: {receipt['case_id']} | Green MINI Cooper | Stornoway")
        print("39 cars On hire; MINI Incident detected. Customer email sent; no report or photos submitted.")
        print(receipt["dashboard_url"])
        print("Email: " + notices[0]["subject"])


if __name__ == "__main__":
    main()
