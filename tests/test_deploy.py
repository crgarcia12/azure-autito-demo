from types import SimpleNamespace
from unittest.mock import Mock

import httpx
import pytest

from tools.deploy import PREBUILT_STARTUP, wait_for_deployment_host


def test_prebuilt_startup_uses_the_deployed_tree_not_a_stale_oryx_archive():
    assert PREBUILT_STARTUP.startswith("cd /home/site/wwwroot && ")
    assert "PYTHONPATH=/home/site/wwwroot/.python_packages/lib/site-packages" in PREBUILT_STARTUP
    assert PREBUILT_STARTUP.endswith("python -m fleet.web")


def test_deployment_waits_for_scm_restart_and_consecutive_healthy_responses(monkeypatch):
    sleeps, responses = [], [503, 200, 502, 200, 200, 200]

    class Client:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def get(self, url):
            assert url == "https://demo.scm.azurewebsites.net/api/deployments"
            return httpx.Response(responses.pop(0), request=httpx.Request("GET", url))

    monkeypatch.setattr("tools.deploy.httpx.Client", lambda **_: Client())
    monkeypatch.setattr("tools.deploy.time.sleep", sleeps.append)
    monkeypatch.setattr("tools.deploy.time.monotonic", Mock(return_value=0))
    cloud = SimpleNamespace(credential=SimpleNamespace(get_token=lambda _: SimpleNamespace(token="test")))
    wait_for_deployment_host(cloud, {"appName": "demo"})
    assert sleeps == [30, 5, 5, 5, 5, 5]
    assert responses == []


def test_scm_authentication_failure_is_not_treated_as_a_warmup(monkeypatch):
    class Client:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def get(self, url):
            return httpx.Response(403, request=httpx.Request("GET", url))

    monkeypatch.setattr("tools.deploy.httpx.Client", lambda **_: Client())
    monkeypatch.setattr("tools.deploy.time.sleep", lambda _: None)
    monkeypatch.setattr("tools.deploy.time.monotonic", Mock(return_value=0))
    cloud = SimpleNamespace(credential=SimpleNamespace(get_token=lambda _: SimpleNamespace(token="test")))
    with pytest.raises(httpx.HTTPStatusError):
        wait_for_deployment_host(cloud, {"appName": "demo"})
