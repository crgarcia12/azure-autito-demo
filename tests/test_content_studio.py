from copy import deepcopy
from datetime import UTC, datetime
import io
import json
import uuid
from zipfile import ZipFile

import pytest

from content_studio.publish import Publisher, validate_plan, word_document
from content_studio.scenario import build_plan
from fleet.domain import fleet_vehicles, utc_text
from fleet.storage import StateStore
from tools.cloud import CONFIG, ROOT


@pytest.fixture
def prepared(monkeypatch):
    options = json.loads((ROOT / "content.config.json").read_text())
    upns = [item["upn"] for item in options["authors"]] + [options["observer"]]
    people = {upn.casefold(): {"id": str(uuid.uuid5(uuid.NAMESPACE_URL, upn.casefold())), "userPrincipalName": upn} for upn in upns}

    class TestFabric:
        config = {"workspace_id": "19b68e4b-dd12-4e74-84d9-18fd9f1e2b49"}

        def mileage(self, _):
            return [{**vehicle, "DistanceKm": float(vehicle["Index"] * 10)} for vehicle in fleet_vehicles()]

        def latest(self):
            return [{
                **vehicle, "Timestamp": utc_text(datetime.now(UTC)),
                "BatteryPct": 55, "Alert": "Low tyre pressure" if vehicle["Index"] == 21 else "",
            } for vehicle in fleet_vehicles()]

    monkeypatch.setattr("content_studio.scenario.FabricData", TestFabric)
    return build_plan(), people


def test_rich_scenario_matches_the_exact_approved_shape(prepared):
    plan, people = prepared
    validate_plan(plan, people)
    assert len(plan["conversations"]) == 8
    assert sum(len(chat["messages"]) for chat in plan["conversations"]) == 64
    assert len(plan["meetings"]) == 5
    assert len(plan["documents"]) == 6
    assert plan["source"]["totalKm"] == sum(index * 10 for index in range(40))
    assert len({chat["topic"] for chat in plan["conversations"]}) == 8
    assert all(len(message["text"]) > 70 for chat in plan["conversations"] for message in chat["messages"])


def test_every_conversation_and_meeting_includes_the_copilot_operator(prepared):
    plan, _ = prepared
    observer = CONFIG["report_recipient"].casefold()
    assert all(observer in {upn.casefold() for upn in chat["members"]} for chat in plan["conversations"])
    assert all(observer in {upn.casefold() for upn in event["attendees"]} for event in plan["meetings"])
    assert all(datetime.fromisoformat(event["start"]).weekday() < 5 for event in plan["meetings"])


@pytest.mark.parametrize("change", ["tenant", "member", "author", "duplicate", "volume"])
def test_cross_tenant_and_unapproved_plan_changes_are_rejected(prepared, change):
    plan, people = prepared
    changed = deepcopy(plan)
    if change == "tenant":
        changed["tenantId"] = str(uuid.uuid4())
    elif change == "member":
        changed["conversations"][0]["members"].append("someone@microsoft.com")
    elif change == "author":
        changed["conversations"][0]["messages"][0]["author"] = "someone@microsoft.com"
    elif change == "duplicate":
        changed["documents"][1]["id"] = changed["documents"][0]["id"]
    else:
        changed["conversations"][0]["messages"].pop()
    with pytest.raises(ValueError):
        validate_plan(changed, people)


def test_word_documents_are_real_office_files_with_complete_content(prepared):
    plan, _ = prepared
    for document in plan["documents"]:
        payload = word_document(document, plan["source"])
        with ZipFile(io.BytesIO(payload)) as archive:
            xml = archive.read("word/document.xml").decode()
            assert document["title"] in xml
            assert "Verified operating context" in xml
            assert "caldovadrive08667473.azurewebsites.net" in xml
            assert len(payload) > 20_000


def test_delivery_receipt_prevents_duplicate_requests(tmp_path):
    publisher = Publisher.__new__(Publisher)
    publisher.run = str(uuid.uuid4())
    publisher.store = StateStore(tmp_path / "receipts.sqlite3")
    publisher.lease_error = None
    calls = []

    def send():
        calls.append(True)
        return {"id": "message-1"}

    assert publisher.deliver("message", send) == {"id": "message-1"}
    assert publisher.deliver("message", send) == {"id": "message-1"}
    assert len(calls) == 1


def test_uncertain_message_delivery_is_not_silently_retried(tmp_path):
    publisher = Publisher.__new__(Publisher)
    publisher.run = str(uuid.uuid4())
    publisher.store = StateStore(tmp_path / "receipts.sqlite3")
    publisher.lease_error = None
    publisher.store.put(f"{publisher.run}/message", {"status": "sending"})
    with pytest.raises(RuntimeError, match="uncertain prior delivery"):
        publisher.deliver("message", lambda: pytest.fail("Must not send a duplicate."))
