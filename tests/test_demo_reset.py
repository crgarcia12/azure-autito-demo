from datetime import UTC, datetime
import json
import uuid

import pytest

from fleet.demo_case import POSITION, VEHICLE_ID
from fleet.demo_reset import prepare_mini_reset, remove_reset_evidence
from fleet.domain import fleet_vehicles, utc_text
from fleet.insurance import IncidentError, Incidents, RetiredImpact
from fleet.storage import StateStore


@pytest.fixture
def setup(tmp_path):
    cases = Incidents(StateStore(tmp_path / "state.sqlite3"))
    vehicle = {**next(v for v in fleet_vehicles() if v["VehicleId"] == VEHICLE_ID), **POSITION, "OdometerKm": 12000}
    return cases, vehicle


def impact(vehicle):
    return {"EventId": str(uuid.uuid4()), "VehicleId": vehicle["VehicleId"],
            "Timestamp": utc_text(datetime.now(UTC)), "PeakAccelerationG": 3.7, "DeltaVKmh": 6}


def test_reset_deletes_only_mini_records_and_archives_other_journeys(setup):
    cases, vehicle = setup
    old = cases.create(impact(vehicle), vehicle)
    older = cases.create(impact(vehicle), vehicle)
    other_vehicle = fleet_vehicles()[0]
    other = cases.create(impact(other_vehicle), other_vehicle)
    cases.change(other["id"], "booking", "test", lambda record: (
        record.update(status="booked", booking={"garage_id": "metro"}, approval={"by": "operator"}) or {}
    ))
    for key in (f"{old['id']}/rfq-agent", f"repair-error/{old['id']}", f"incident-weather/{old['id']}", f"vehicle-hold/{old['id']}"):
        cases.store.put(key, {"kept": False})
    cases.store.put("routes.json", {"keep": True})
    with cases.store.connect() as db:
        db.execute("INSERT INTO incident_operations VALUES(?,?,?,?,?,?)", ("sent", old["id"], "sent", "{}", "{}", "now"))
    receipt = prepare_mini_reset(cases, str(uuid.uuid4()), vehicle, "operator")
    assert set(receipt["deleted_case_ids"]) == {old["id"], older["id"]}
    assert receipt["archived_case_ids"] == [other["id"]]
    assert cases.list() == []
    archived = cases.get(other["id"])
    assert archived["status"] == "archived" and archived["demo_archive"]["previous_status"] == "booked"
    assert archived["booking"] == {"garage_id": "metro"} and archived["approval"] == {"by": "operator"}
    assert len(cases.list(include_archived=True)) == 1
    assert cases.store.get("routes.json") == {"keep": True}
    with pytest.raises(IncidentError, match="not found"):
        cases.authorize(old["id"], old["token"])
    with cases.store.connect() as db:
        assert db.execute("SELECT count(*) FROM incident_operations").fetchone()[0] == 0
        assert db.execute("SELECT count(*) FROM incident_events WHERE case_id=?", (old["id"],)).fetchone()[0] == 0
    assert not any(old["id"] in key for key in cases.store.export())
    with pytest.raises(RetiredImpact):
        cases.create(old["telemetry"], vehicle)
    fresh = cases.create(receipt["event"], vehicle)
    assert fresh["id"] == receipt["case_id"]
    assert fresh["status"] == "awaiting_report" and not fresh["report_received"]
    assert fresh["photos"] == [] and fresh["quotes"] == {}


def test_same_reset_id_does_not_delete_a_new_customer_report(setup):
    cases, vehicle = setup
    reset_id = str(uuid.uuid4())
    first = prepare_mini_reset(cases, reset_id, vehicle, "operator")
    fresh = cases.create(first["event"], vehicle)
    cases.change(fresh["id"], "submitted", "test", lambda record: (record.update(report_received=True) or {}))
    repeated = prepare_mini_reset(cases, reset_id, vehicle, "operator")
    assert first == repeated
    assert cases.get(fresh["id"])["report_received"] is True
    with pytest.raises(IncidentError, match="unfinished"):
        prepare_mini_reset(cases, str(uuid.uuid4()), vehicle, "operator")


def test_completed_reset_can_be_repeated_with_a_new_case_and_token(setup):
    cases, vehicle = setup
    first = prepare_mini_reset(cases, str(uuid.uuid4()), vehicle, "operator")
    old = cases.create(first["event"], vehicle)
    cases.store.put("mini-reset/" + first["reset_id"], {**first, "stage": "complete"})
    second = prepare_mini_reset(cases, str(uuid.uuid4()), vehicle, "operator")
    new = cases.create(second["event"], vehicle)
    assert new["id"] != old["id"] and new["token"] != old["token"]
    assert second["deleted_case_ids"] == [old["id"]]
    assert len(cases.list()) == 1
    assert new["telemetry"]["OdometerKm"] == first["event"]["OdometerKm"]


@pytest.mark.parametrize("state", ["sending", "draft_creating"])
def test_uncertain_mail_stops_reset_before_any_deletion(setup, state):
    cases, vehicle = setup
    old = cases.create(impact(vehicle), vehicle)
    with cases.store.connect() as db:
        db.execute("INSERT INTO incident_operations VALUES(?,?,?,?,?,?)", ("mail", old["id"], state, "{}", "{}", "now"))
    with pytest.raises(IncidentError, match="uncertain"):
        prepare_mini_reset(cases, str(uuid.uuid4()), vehicle, "operator")
    assert cases.get(old["id"])["status"] == "awaiting_report"
    assert cases.store.get("impact-reset.json") is None


def test_reset_refuses_wrong_vehicle_or_location(setup):
    cases, vehicle = setup
    for change in ({"VehicleId": "CD-007"}, {"Make": "Toyota"}, {"Latitude": 51.5}, {"City": "London"}):
        with pytest.raises(IncidentError):
            prepare_mini_reset(cases, str(uuid.uuid4()), {**vehicle, **change}, "operator")
    assert not cases.store.get("mini-reset-current")


def test_evidence_cleanup_is_case_scoped_and_rejects_traversal(tmp_path):
    root = tmp_path / "evidence"
    deleted, retained = root / "CDI-0000000001", root / "CDI-0000000002"
    for directory in (deleted, retained):
        directory.mkdir(parents=True)
        (directory / "photo.jpg").write_bytes(b"original")
    remove_reset_evidence(root, [deleted.name])
    assert not deleted.exists() and (retained / "photo.jpg").read_bytes() == b"original"
    remove_reset_evidence(root, [deleted.name])
    with pytest.raises(IncidentError):
        remove_reset_evidence(root, [".."])
    assert retained.exists()
