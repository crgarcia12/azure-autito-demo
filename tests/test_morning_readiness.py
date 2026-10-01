from datetime import UTC, datetime
from types import SimpleNamespace

from fleet.capacity import morning_wakeup
from fleet.storage import StateStore


def test_capacity_resumes_before_the_morning_demo_once_per_day(tmp_path, monkeypatch):
    import fleet.capacity as capacity
    store = StateStore(tmp_path / "state.sqlite3")
    calls = []
    config = {
        "report_timezone": "Europe/Madrid", "capacity_resume_hour": 6, "capacity_resume_minute": 45,
        "fabric_capacity_resource_id": "/subscriptions/demo/resourceGroups/demo/providers/Microsoft.Fabric/capacities/demo",
    }
    monkeypatch.setattr(capacity, "settings", lambda: config)
    monkeypatch.setattr(capacity, "data_credential", lambda: SimpleNamespace(get_token=lambda _: SimpleNamespace(token="test-token")))

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"properties": {"state": "Paused"}}

    class Client:
        def __init__(self, **_):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

        def get(self, url, **_):
            calls.append(("GET", url))
            return Response()

        def post(self, url, **_):
            calls.append(("POST", url))
            return Response()

    monkeypatch.setattr(capacity.httpx, "Client", Client)
    morning_wakeup(store, datetime(2026, 10, 1, 4, 44, tzinfo=UTC))
    assert not calls
    morning_wakeup(store, datetime(2026, 10, 1, 4, 45, tzinfo=UTC))
    assert [method for method, _ in calls] == ["GET", "POST"]
    assert calls[-1][1].endswith("/resume")
    morning_wakeup(store, datetime(2026, 10, 1, 5, 15, tzinfo=UTC))
    assert len(calls) == 2
    assert store.get("capacity-wakeup-2026-10-01.json")["status"] == "ResumeRequested"
