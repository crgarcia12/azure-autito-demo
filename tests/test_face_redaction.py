from datetime import UTC, datetime
import hashlib
import io
from unittest.mock import AsyncMock
import uuid

import numpy as np
from PIL import Image
import pytest
from pydantic import ValidationError

from fleet.config import ROOT
from fleet.domain import fleet_vehicles, utc_text
from fleet.evidence import EvidenceService, PrivacyVerification, RedactionBox, face_redactions, text_redactions, redact_image, safe_image
from fleet.privacy_detection import FACE_MODEL_PATH, FACE_MODEL_SHA256, TEXT_MODEL_PATH, TEXT_MODEL_SHA256, detect_faces
from fleet.insurance import CustomerReport, IncidentError, Incidents
from fleet.storage import StateStore


def face_coverage(redacted: bytes) -> None:
    with Image.open(io.BytesIO(redacted)) as image:
        for region in [(275, 95, 352, 171), (1230, 160, 1290, 232)]:
            pixels = np.asarray(image.crop(region)).astype(np.int16)
            covered = np.max(np.abs(pixels - np.array([20, 39, 31])), axis=2) <= 5
            assert covered.mean() >= .99


def test_real_faces_are_covered_without_masking_the_damage_area():
    original, width, height = safe_image((ROOT / "media" / "crash2.png").read_bytes())
    assert (width, height) == (1536, 1024)
    boxes = face_redactions(original)
    assert len(boxes) == 2 and all(box.kind == "face" for box in boxes)
    result = redact_image(original, boxes)
    face_coverage(result)
    with Image.open(io.BytesIO(original)) as before, Image.open(io.BytesIO(result)) as after:
        damage = (600, 680, 760, 855)
        delta = np.abs(np.asarray(before.crop(damage)).astype(np.int16) - np.asarray(after.crop(damage)).astype(np.int16))
        assert delta.mean() < 3
    assert hashlib.sha256(FACE_MODEL_PATH.read_bytes()).hexdigest() == FACE_MODEL_SHA256


def test_photo_without_people_gets_no_face_boxes():
    original, _, _ = safe_image((ROOT / "media" / "crash1.png").read_bytes())
    assert face_redactions(original) == []


def test_exif_rotated_source_uses_the_same_upright_raster_for_detection_and_masking():
    with Image.open(ROOT / "media" / "crash2.png") as original:
        stored = original.rotate(90, expand=True)
        exif = Image.Exif()
        exif[274] = 6
        source = io.BytesIO()
        stored.save(source, format="JPEG", quality=95, exif=exif)
    normalized, width, height = safe_image(source.getvalue())
    assert (width, height) == (1536, 1024)
    boxes = face_redactions(normalized)
    assert len(boxes) == 2
    face_coverage(redact_image(normalized, boxes))


@pytest.mark.parametrize("x,y,width,height", [
    (.13, .495, .168, .978), (.876, .535, .186, .917), (.95, .1, .1, .1),
])
def test_the_reported_out_of_image_boxes_are_rejected(x, y, width, height):
    with pytest.raises(ValidationError, match="fit inside"):
        RedactionBox(x=x, y=y, width=width, height=height, reason="Face")


@pytest.mark.parametrize("file,region", [
    ("crash2.png", (935, 686, 1160, 752)),
    ("crash1.png", (1210, 478, 1530, 620)),
])
def test_readable_registrations_are_fully_covered_including_a_plate_at_the_image_edge(file, region):
    original, _, _ = safe_image((ROOT / "media" / file).read_bytes())
    boxes = text_redactions(original)
    assert boxes and all(box.x + box.width <= 1 + 1e-9 and box.y + box.height <= 1 + 1e-9 for box in boxes)
    with Image.open(io.BytesIO(redact_image(original, boxes))) as image:
        pixels = np.asarray(image.crop(region)).astype(np.int16)
        covered = np.max(np.abs(pixels - np.array([20, 39, 31])), axis=2) <= 5
        assert covered.mean() >= .99
    assert hashlib.sha256(TEXT_MODEL_PATH.read_bytes()).hexdigest() == TEXT_MODEL_SHA256


def test_privacy_clear_requires_a_real_boolean():
    with pytest.raises(ValidationError):
        PrivacyVerification(clear="true", reason="Not a boolean.")


def test_unreadable_detection_input_never_returns_a_success_shaped_empty_list():
    with pytest.raises(IncidentError, match="could not read"):
        detect_faces(b"not a photograph")


def test_missing_face_model_fails_closed(tmp_path, monkeypatch):
    from fleet import privacy_detection
    privacy_detection.verified_model.cache_clear()
    try:
        with pytest.raises(IncidentError, match="missing or damaged"):
            privacy_detection.verified_model(tmp_path / "missing.onnx", FACE_MODEL_SHA256)
    finally:
        privacy_detection.verified_model.cache_clear()


def make_case(tmp_path):
    cases = Incidents(StateStore(tmp_path / "state.sqlite3"))
    vehicle = next(v for v in fleet_vehicles() if v["VehicleId"] == "CD-006")
    case = cases.create({"EventId": str(uuid.uuid4()), "Timestamp": utc_text(datetime.now(UTC)),
                         "PeakAccelerationG": 3.7, "DeltaVKmh": 6}, vehicle)
    evidence = EvidenceService(cases)
    photo = evidence.add_photo(case["id"], (ROOT / "media" / "crash2.png").read_bytes())
    cases.submit(case["id"], CustomerReport(description="I scraped the front bumper while parking.", consent_to_share_redacted=True))
    return cases, cases.get(case["id"]), evidence, photo


def test_reprocessing_preserves_originals_customer_report_and_previous_derived_artifacts(tmp_path):
    cases, case, evidence, photo = make_case(tmp_path)
    directory = evidence.root / case["id"]
    original = (directory / (photo["id"] + ".source")).read_bytes()
    normalized = (directory / (photo["id"] + ".jpg")).read_bytes()
    (directory / (photo["id"] + "-redacted.jpg")).write_bytes(b"previous-redaction")
    (directory / "repair-brief.pdf").write_bytes(b"previous-pdf")
    old_report = {"summary": "Earlier privacy review.", "requires_manual_review": True}
    reviewed = cases.change(case["id"], "reviewed", "test", lambda record: (
        record.update(status="report_review_required", repair_report=old_report) or {}
    ))
    result = evidence.request_reassessment(case["id"], reviewed["version"], "operator")
    assert result["status"] == "evidence_received"
    assert result["customer_report"] == case["customer_report"]
    assert result["photos"] == case["photos"] and result["report_received"]
    assert result["assessment_history"][0]["repair_report"] == old_report
    assert "repair_report" not in result
    archive = directory / "assessment-history" / "1"
    assert (archive / "repair-brief.pdf").read_bytes() == b"previous-pdf"
    assert (archive / (photo["id"] + "-redacted.jpg")).read_bytes() == b"previous-redaction"
    assert (directory / (photo["id"] + ".source")).read_bytes() == original
    assert (directory / (photo["id"] + ".jpg")).read_bytes() == normalized
    with pytest.raises(IncidentError):
        evidence.request_reassessment(case["id"], reviewed["version"], "operator")


@pytest.mark.parametrize("status", ["awaiting_report", "report_ready", "recommendation_ready", "approved", "booked", "archived"])
def test_reprocessing_cannot_rewrite_an_approved_or_distributed_assessment(tmp_path, status):
    cases, case, evidence, _ = make_case(tmp_path)
    record = cases.change(case["id"], "changed", "test", lambda current: (current.update(status=status) or {}))
    with pytest.raises(IncidentError, match="awaiting review"):
        evidence.request_reassessment(case["id"], record["version"], "operator")


async def test_failed_privacy_verification_still_blocks_distribution(tmp_path):
    cases, case, evidence, _ = make_case(tmp_path)
    evidence.config = {
        "foundry_model_deployment": "vision", "foundry_agent_name": "evidence",
        "foundry_agent_version": "test", "foundry_agent_id": "evidence:test",
        "foundry_project_endpoint": "https://test.services.ai.azure.com/api/projects/test",
    }
    evidence.model = AsyncMock(side_effect=[
        {"observations": "Visible scuffing on the front bumper.", "usable": True, "retake_reason": "",
         "sensitive_content_uncertain": False},
        {"clear": False, "reason": "The registration remains visible."},
        {"summary": "Front bumper scuffing following a parking impact.", "redacted_description": "The bumper contacted an obstacle while parking.",
         "repair_category": "bumper_cosmetic", "visible_damage": ["Bumper scuffing"],
         "limitations": ["Physical inspection is required."], "requires_manual_review": False, "reasons": []},
    ])
    result = await evidence.assess(case["id"])
    face_coverage(evidence.model.call_args_list[0].args[2])
    assert result["status"] == "report_review_required"
    assert result["repair_report"]["privacy_passed"] is False
    assert result["repair_report"]["photos"][0]["face_detector"]["face_count"] == 2
    assert not result["quotes"]
