"""Create one real hosted case and verify secured native agents through booking."""

import json
import time
from urllib.parse import urlparse
import uuid

import httpx

from tools.cloud import Cloud, ROOT, load_state


def main():
    cloud, state = Cloud(), load_state()
    token = cloud.credential.get_token(f"api://{state['agent_app_id']}/.default").token
    origin = state["appUrl"]
    headers = {"Authorization": f"Bearer {token}", "X-Caldova-Request": "fleet-app"}
    event_id = uuid.uuid4()
    case_id = "CDI-" + uuid.uuid5(uuid.NAMESPACE_URL, str(event_id)).hex[:10].upper()
    with httpx.Client(headers=headers, timeout=120) as operator:
        response = operator.get(origin + "/api/fleet")
        response.raise_for_status()
        vehicle = next(item for item in response.json()["vehicles"] if not item.get("IncidentId") and item["Status"] != "maintenance")
        response = operator.post(origin + "/api/telemetry/impact", json={"vehicle_id": vehicle["VehicleId"], "event_id": str(event_id)})
        response.raise_for_status()
        start = time.monotonic()
        case = None
        while time.monotonic() - start < 170:
            time.sleep(8)
            response = operator.get(origin + "/api/incidents")
            response.raise_for_status()
            case = next((item for item in response.json()["cases"] if item["id"] == case_id), None)
            if case and case.get("detection_origin") == "fabric_pipeline":
                break
        if not case or case.get("detection_origin") != "fabric_pipeline":
            raise RuntimeError("The native Fabric trigger did not open the verification case.")
        response = operator.post(origin + f"/api/incidents/{case_id}/link", json={})
        response.raise_for_status()
        capability = urlparse(response.json()["url"]).fragment
        with httpx.Client(headers={"X-Incident-Token": capability, "X-Caldova-Request": "fleet-app"}, timeout=120) as customer:
            with (ROOT / "static" / "demo-assets" / "bumper-dent.jpg").open("rb") as photograph:
                response = customer.post(origin + f"/customer/{case_id}/photos", files={"photo": ("bumper.jpg", photograph, "image/jpeg")})
                response.raise_for_status()
            response = customer.post(origin + f"/customer/{case_id}/submit", json={
                "safe": True, "injuries": False, "description": "The rear bumper contacted a low bollard while reversing. There is a dent and light paint scuffing on the plastic bumper. Nobody was injured and no other vehicle was involved.",
                "customer_name": "Morgan Example", "customer_email": "morgan.example@caldova08667473.onmicrosoft.com",
                "consent_to_share_redacted": True,
            })
            response.raise_for_status()
        approved = False
        deadline = time.monotonic() + 600
        while time.monotonic() < deadline:
            time.sleep(10)
            response = operator.get(origin + f"/api/incidents/{case_id}")
            response.raise_for_status()
            case = response.json()
            if case["status"] in {"report_review_required", "assistance_required"}:
                raise RuntimeError("The genuine model routed the test for manual review; no fabricated quote is accepted.")
            if case["status"] == "recommendation_ready" and case["recommendation"].get("agent") and not approved:
                assert len(case["quotes"]) == 3
                assert case["recommendation"]["garage_id"] == "metro"
                for quote in case["quotes"].values():
                    native = state["studio_agents"]["cdv_" + quote["garage_id"] + "repairs"]
                    assert quote["agent_id"] == native["id"]
                response = operator.post(origin + f"/api/incidents/{case_id}/approve", json={"version": case["version"]})
                response.raise_for_status()
                approved = True
            if case["status"] == "booked":
                assert approved and case["approval"]["by"] == "admin@caldova08667473.onmicrosoft.com"
                assert case["booking"]["email_id"]
                evidence_agent = case["repair_report"]["evidence_agent"]
                assert evidence_agent["provider"] == "Microsoft Foundry Agent Service"
                assert evidence_agent["name"] == state["foundry_agent_name"]
                assert len(evidence_agent["responses"]) == 3
                result = {
                    "case_id": case_id, "vehicle_id": vehicle["VehicleId"], "status": case["status"],
                    "pipeline_run_id": case["fabric_pipeline_run_id"],
                    "native_agents": [quote["agent_id"] for quote in case["quotes"].values()],
                    "coordinator_agent": case["recommendation"]["agent"],
                    "evidence_agent": evidence_agent,
                    "confirmed_by": case["booking"]["garage_id"],
                    "correspondence_records": len(case["correspondence"]),
                    "elapsed_seconds": round(time.monotonic() - start, 2),
                }
                (ROOT / ".local" / "secured-hosted-e2e.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
                print(json.dumps(result))
                return
        raise TimeoutError(f"The hosted workflow did not complete; last state: {case['status']}")


if __name__ == "__main__":
    main()
