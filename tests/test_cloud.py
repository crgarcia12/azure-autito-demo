from unittest.mock import Mock

import pytest

from tools.cloud import Cloud


def test_deduplicated_fabric_job_does_not_wait_until_timeout(monkeypatch):
    cloud = Cloud.__new__(Cloud)
    cloud.request = Mock(return_value={"status": "Deduped", "failureReason": {"message": "Another refresh is running."}})
    monkeypatch.setattr("tools.cloud.time.sleep", lambda _: None)
    monkeypatch.setattr("tools.cloud.time.monotonic", Mock(side_effect=[0, 0, 901]))
    with pytest.raises(RuntimeError, match="Deduped"):
        cloud.wait("https://api.fabric.microsoft.com/v1/workspaces/example/items/graph/jobs/instances/job", {})
    cloud.request.assert_called_once()
