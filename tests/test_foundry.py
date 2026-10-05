import json
from types import SimpleNamespace

import httpx
import pytest

from fleet.foundry import AGENT_INSTRUCTIONS, FoundryEvidenceAgent, validate_project_endpoint


CONFIG = {
    "foundry_project_endpoint": "https://caldova.services.ai.azure.com/api/projects/insurance",
    "foundry_agent_name": "caldova-incident-evidence",
    "foundry_agent_version": "2",
}


def test_evidence_instructions_start_with_the_task_not_the_removed_intro():
    assert AGENT_INSTRUCTIONS.startswith("Perform the application's requested evidence task:")
    assert "You are" not in AGENT_INSTRUCTIONS


@pytest.mark.parametrize("endpoint", [
    "https://caldova.openai.azure.com",
    "https://caldova.openai.azure.com/openai/v1",
    "https://example.com/api/projects/insurance",
    "http://caldova.services.ai.azure.com/api/projects/insurance",
    "https://caldova.services.ai.azure.com/api/projects/",
    "https://user@caldova.services.ai.azure.com/api/projects/insurance",
    "https://caldova.services.ai.azure.com/api/projects/insurance?token=anything",
])
def test_only_foundry_project_endpoints_are_accepted(endpoint):
    with pytest.raises(ValueError):
        validate_project_endpoint(endpoint)


def test_actual_agent_endpoint_not_raw_model_endpoint(monkeypatch):
    seen = []
    scopes = []
    real_client = httpx.Client

    def handle(request):
        seen.append(request)
        return httpx.Response(200, json={
            "id": "resp-foundry-1", "status": "completed", "model": "incident-vision",
            "output": [{"type": "message", "content": [{"type": "output_text", "text": '{"usable":true}'}]}],
        })

    monkeypatch.setattr("fleet.foundry.httpx.Client", lambda **kwargs: real_client(transport=httpx.MockTransport(handle), **kwargs))
    credential = SimpleNamespace(get_token=lambda scope: (scopes.append(scope) or SimpleNamespace(token="unit-test-token")))
    result = FoundryEvidenceAgent(CONFIG, credential).invoke("Return JSON with usable.", "Inspect this photo.", b"photo")
    assert scopes == ["https://ai.azure.com/.default"]
    assert seen[0].url.path.endswith("/agents/caldova-incident-evidence/endpoint/protocols/openai/responses")
    body = json.loads(seen[0].content)
    assert "model" not in body
    assert "temperature" not in body
    assert "text" not in body
    assert body["input"][0]["type"] == "message"
    assert body["input"][1]["content"][1]["type"] == "input_image"
    assert body["input"][1]["content"][1]["image_url"].startswith("data:image/jpeg;base64,")
    assert body["tool_choice"] == "none"
    assert result.data == {"usable": True}
    assert result.trace["provider"] == "Microsoft Foundry Agent Service"
    assert result.trace["agent_version"] == "2"
    assert result.trace["response_id"] == "resp-foundry-1"


@pytest.mark.parametrize("response", [
    {"status": "incomplete", "output": []},
    {"status": "completed", "output": []},
    {"status": "completed", "output": [{"type": "message", "content": [{"type": "output_text", "text": "[]"}]}]},
])
def test_incomplete_or_invalid_agent_outputs_are_not_success_shaped(monkeypatch, response):
    real_client = httpx.Client
    monkeypatch.setattr("fleet.foundry.httpx.Client", lambda **kwargs: real_client(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=response)), **kwargs
    ))
    agent = FoundryEvidenceAgent(CONFIG, SimpleNamespace(get_token=lambda _: SimpleNamespace(token="unit-test-token")))
    with pytest.raises(RuntimeError):
        agent.invoke("Return JSON.", "Inspect evidence.")


def test_foundry_error_details_are_visible_in_the_case_instead_of_only_http_400(monkeypatch):
    real_client = httpx.Client
    monkeypatch.setattr("fleet.foundry.httpx.Client", lambda **kwargs: real_client(
        transport=httpx.MockTransport(lambda _: httpx.Response(400, json={
            "error": {"message": "The connected tool requires delegated user authentication."},
        })), **kwargs,
    ))
    agent = FoundryEvidenceAgent(CONFIG, SimpleNamespace(get_token=lambda _: SimpleNamespace(token="unit-test-token")))
    with pytest.raises(RuntimeError, match="requires delegated user authentication"):
        agent.invoke("Return JSON.", "Inspect evidence.")
