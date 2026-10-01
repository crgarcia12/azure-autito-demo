from datetime import UTC, datetime
import io
import json
from pathlib import Path
import uuid

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
from PIL import Image
import pytest

from fleet.domain import utc_text
from fleet.evidence import EvidenceService
from fleet.incident_routes import customer_case, report_page, submit, upload
from fleet.insurance import Incidents
from fleet.storage import StateStore
from fleet.web import errors


@pytest.fixture
async def customer_app(tmp_path):
    cases = Incidents(StateStore(tmp_path / "state.sqlite3"))
    vehicle = {"VehicleId": "CD-001", "Registration": "LO24 AAD", "Make": "Polestar", "Model": "2", "City": "London", "BranchId": "LON"}
    event = {"EventId": str(uuid.uuid4()), "Timestamp": utc_text(datetime.now(UTC)), "PeakAccelerationG": 3.7, "DeltaVKmh": 6}
    case = cases.create(event, vehicle)
    app = web.Application(middlewares=[errors], client_max_size=11 * 1024 * 1024)
    app["incidents"] = cases
    app["repairs"] = type("Repairs", (), {"evidence": EvidenceService(cases)})()
    app.router.add_get("/customer/{case}", customer_case)
    app.router.add_post("/customer/{case}/photos", upload)
    app.router.add_post("/customer/{case}/submit", submit)
    async with TestClient(TestServer(app)) as client:
        yield client, cases, case


async def test_invalid_or_missing_token_never_exposes_a_customer_record(customer_app):
    client, _, case = customer_app
    response = await client.get(f"/customer/{case['id']}")
    assert response.status == 403
    assert "vehicle" not in await response.json()
    response = await client.get(f"/customer/{case['id']}", headers={"X-Incident-Token": "wrong"})
    assert response.status == 403


async def test_real_upload_and_report_api_shape(customer_app):
    from aiohttp import FormData
    client, cases, case = customer_app
    headers = {"X-Incident-Token": case["token"]}
    image = io.BytesIO()
    Image.new("RGB", (600, 400), "white").save(image, format="JPEG")
    form = FormData()
    form.add_field("photo", image.getvalue(), filename="incident.jpg", content_type="image/jpeg")
    response = await client.post(f"/customer/{case['id']}/photos", data=form, headers=headers)
    assert response.status == 201
    assert len(cases.get(case["id"])["photos"]) == 1
    response = await client.post(f"/customer/{case['id']}/submit", json={
        "safe": True, "injuries": False, "description": "I grazed the bumper while reversing next to a bollard.",
        "customer_name": "Test Customer", "customer_email": "test@caldova08667473.onmicrosoft.com",
        "consent_to_share_redacted": True,
    }, headers=headers)
    assert response.status == 200
    assert (await response.json())["status"] == "evidence_received"
    public = await (await client.get(f"/customer/{case['id']}", headers=headers)).json()
    assert "customer_report" not in public
    assert "quotes" not in public
    assert "correspondence" not in public
    assert "token_hash" not in public


async def test_upload_rejects_html_disguised_as_jpeg(customer_app):
    from aiohttp import FormData
    client, cases, case = customer_app
    form = FormData()
    form.add_field("photo", b"<html>not an image</html>", filename="photo.jpg", content_type="image/jpeg")
    response = await client.post(f"/customer/{case['id']}/photos", data=form, headers={"X-Incident-Token": case["token"]})
    assert response.status == 400
    assert not cases.get(case["id"])["photos"]


def test_customer_agent_reports_once_with_photo_and_provenance(tmp_path):
    from fleet.customer_agent import simulate_customer
    from fleet.foundry import EvidenceResult
    from fleet.insurance import IncidentError

    cases = Incidents(StateStore(tmp_path / "state.sqlite3"))
    vehicle = {"VehicleId": "CD-007", "Registration": "LO24 AGD", "Make": "Mercedes-Benz", "Model": "C-Class", "City": "London", "BranchId": "LON"}
    case = cases.create({"EventId": str(uuid.uuid4()), "Timestamp": utc_text(datetime.now(UTC)), "PeakAccelerationG": 3.7, "DeltaVKmh": 6}, vehicle)
    evidence = EvidenceService(cases)
    evidence.config = {"customer_agent_name": "caldova-customer", "customer_agent_version": "1"}
    seen = {}

    class Agent:
        def invoke(self, instructions, text, image=None):
            seen.update(text=text, image=image)
            return EvidenceResult({"description": "I reversed slowly into a bollard and dented the rear bumper."},
                                  {"response_id": "resp_1", "agent_name": "caldova-customer", "agent_version": "1"})

    result = simulate_customer(cases, evidence, case["id"], Agent())
    assert result["status"] == "evidence_received"
    record = cases.get(case["id"])
    assert len(record["photos"]) == 1 and seen["image"]
    assert "Mercedes-Benz C-Class" in seen["text"] and "LO24" not in seen["text"]
    assert record["customer_report"]["consent_to_share_redacted"] is True
    assert record["customer_agent"]["response_id"] == "resp_1"
    with pytest.raises(IncidentError):
        simulate_customer(cases, evidence, case["id"], Agent())
