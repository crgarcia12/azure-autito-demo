from datetime import UTC, datetime, timedelta
import json as jsonlib
from types import SimpleNamespace

import httpx
import pytest

from fleet.domain import utc_text
from fleet.insurance import IncidentError
from fleet.storage import StateStore
from fleet.weather import WeatherService, web_iq_weather_context


def test_web_iq_weather_context_preserves_search_citations_without_claiming_observations():
    incident = datetime(2026, 10, 4, 21, 55, tzinfo=UTC)
    checked_at = incident + timedelta(minutes=2)
    payload = {"results": [{
        "title": "Stornoway weather report",
        "url": "https://weather.example/report",
        "snippet": "Rain showers reported at 21:00 UTC.",
    }]}
    result = web_iq_weather_context(payload, "Stornoway", utc_text(incident), checked_at)
    assert result["provider"] == "Microsoft Web IQ"
    assert result["summary"] == "Stornoway weather report: Rain showers reported at 21:00 UTC."
    assert result["source_url"] == "https://weather.example/report"
    assert result["sources"][0]["title"] == "Stornoway weather report"
    assert result["rain"] is None and result["fog"] is None
    assert "timestamp" in result["day_summary"]


def test_web_iq_weather_context_rejects_unreadable_responses():
    with pytest.raises(IncidentError, match="no readable weather results"):
        web_iq_weather_context({"unexpected": []}, "London", "2026-10-04T21:55:00Z", datetime.now(UTC))


async def test_weather_service_uses_web_iq_and_caches_citations(tmp_path, monkeypatch):
    now = datetime.now(UTC)
    case = {"id": "CDI-0000000001", "vehicle": {"City": "Stornoway"},
            "telemetry": {"Timestamp": utc_text(now)}}
    store = StateStore(tmp_path / "weather.sqlite3")
    captured = []

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def post(self, url, *, headers, json):
            captured.append({"url": url, "headers": headers, "payload": json})
            if url == "https://api.microsoft.ai/v3/search/web":
                return httpx.Response(200, json={"results": [{
                    "title": "Local weather report", "url": "https://weather.example/stornoway",
                    "snippet": "Wind 12 mph from the west. Light rain. Mist patches.",
                }]}, request=httpx.Request("POST", url))
            return httpx.Response(200, json={"output": [{
                    "type": "message", "content": [{"type": "output_text", "text": jsonlib.dumps({
                    "wind": "Westerly at 12 mph", "rain": "Light rain", "mist": "Mist patches",
                })}],
            }]}, request=httpx.Request("POST", url))

    monkeypatch.setenv("WEB_IQ_API_KEY", "test-web-iq-key")
    monkeypatch.setattr("fleet.weather.httpx.AsyncClient", lambda **_: Client())
    monkeypatch.setattr("fleet.weather.settings", lambda: {
        "foundry_project_endpoint": "https://example.services.ai.azure.com/api/projects/test",
        "foundry_model_deployment": "incident-vision",
    })
    monkeypatch.setattr("fleet.weather.data_credential", lambda: SimpleNamespace(
        get_token=lambda scope: SimpleNamespace(token="foundry-test-token")
    ))
    result = await WeatherService(store).for_case(case)
    assert captured[0]["url"] == "https://api.microsoft.ai/v3/search/web"
    assert captured[0]["headers"]["x-apikey"] == "test-web-iq-key"
    assert captured[0]["payload"]["region"] == "GB"
    assert captured[0]["payload"]["safeSearch"] == "strict"
    assert "Stornoway" in captured[0]["payload"]["query"]
    assert captured[1]["url"] == "https://example.services.ai.azure.com/api/projects/test/openai/v1/responses"
    assert captured[1]["headers"]["Authorization"] == "Bearer foundry-test-token"
    assert captured[1]["payload"]["model"] == "incident-vision"
    assert captured[1]["payload"]["text"]["format"]["schema"]["required"] == ["wind", "rain", "mist"]
    assert result["source_url"] == "https://weather.example/stornoway"
    assert result["weather_facts"] == {
        "wind": "Westerly at 12 mph", "rain": "Light rain", "mist": "Mist patches",
    }
    assert result["summary"] == "Wind: Westerly at 12 mph · Rain: Light rain · Mist: Mist patches"
    monkeypatch.setattr("fleet.weather.httpx.AsyncClient", lambda **_: pytest.fail("A fresh cached search must not trigger another request."))
    assert await WeatherService(store).for_case(case) == result


async def test_weather_service_requires_an_environment_key(tmp_path, monkeypatch):
    now = datetime.now(UTC)
    case = {"id": "CDI-0000000001", "vehicle": {"City": "London"},
            "telemetry": {"Timestamp": utc_text(now)}}
    monkeypatch.delenv("WEB_IQ_API_KEY", raising=False)
    with pytest.raises(IncidentError, match="WEB_IQ_API_KEY"):
        await WeatherService(StateStore(tmp_path / "weather.sqlite3")).for_case(case)


async def test_weather_service_failure_is_explicit_and_does_not_return_stale_cache(tmp_path, monkeypatch):
    now = datetime.now(UTC)
    case = {"id": "CDI-0000000001", "vehicle": {"City": "Stornoway"}, "telemetry": {"Timestamp": utc_text(now)}}
    store = StateStore(tmp_path / "weather.sqlite3")
    old = web_iq_weather_context({"results": [{"title": "Old weather", "url": "https://weather.example/old"}]},
                                "Stornoway", utc_text(now), now)
    old["checked_at"] = utc_text(now - timedelta(hours=1))
    store.put("incident-weather/" + case["id"], old)
    monkeypatch.setenv("WEB_IQ_API_KEY", "test-web-iq-key")
    monkeypatch.setattr("fleet.weather.settings", lambda: {
        "foundry_project_endpoint": "https://example.services.ai.azure.com/api/projects/test",
        "foundry_model_deployment": "incident-vision",
    })
    monkeypatch.setattr("fleet.weather.data_credential", lambda: SimpleNamespace(
        get_token=lambda scope: SimpleNamespace(token="foundry-test-token")
    ))

    class Unavailable:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def post(self, url, **kwargs):
            return httpx.Response(503, request=httpx.Request("POST", url))

    monkeypatch.setattr("fleet.weather.httpx.AsyncClient", lambda **_: Unavailable())
    with pytest.raises(IncidentError, match="Weather context could not be extracted"):
        await WeatherService(store).for_case(case)
