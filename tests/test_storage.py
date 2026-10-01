import sqlite3
import time

import pytest

from fleet.storage import LeaseBusyError, StateStore


def test_state_survives_restart_and_create_does_not_overwrite(tmp_path):
    path = tmp_path / "state.sqlite3"
    first = StateStore(path)
    first.put("checkpoint", {"through": "2026-09-30T07:00:00Z"})
    second = StateStore(path)
    assert second.get("checkpoint") == {"through": "2026-09-30T07:00:00Z"}
    assert not second.create("checkpoint", {"through": "wrong"})
    assert second.get("missing") is None


def test_only_one_worker_can_hold_a_lease(tmp_path):
    store = StateStore(tmp_path / "state.sqlite3")
    with store.lease("worker") as first:
        first.renew()
        with pytest.raises(LeaseBusyError):
            store.lease("worker")
    with store.lease("worker"):
        pass


def test_expired_lease_cannot_be_renewed_or_delete_new_owner(tmp_path):
    store = StateStore(tmp_path / "state.sqlite3")
    first = store.lease("worker")
    with store.connect() as db:
        db.execute("UPDATE leases SET expires = ?", (time.time() - 1,))
    second = store.lease("worker")
    with pytest.raises(LeaseBusyError):
        first.renew()
    first.release()
    second.renew()
    second.release()
