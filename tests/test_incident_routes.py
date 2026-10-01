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
