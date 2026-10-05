from datetime import UTC, datetime
from contextlib import asynccontextmanager
import base64
import io
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock
import uuid
import zipfile

import httpx
import pytest

from fleet.domain import fleet_vehicles, utc_text
from fleet.insurance import IncidentError, Incidents, insurance_config
from fleet.mail import RepairMail
from fleet.repair_agents import RepairAgents
from fleet.repair_policy import policy_document, policy_reference
from fleet.storage import StateStore
from fleet.workiq import WORK_IQ_MCP, WorkIQSession, same_document, word_text


def response(output, ident="resp_1"):
    return {"status": "completed", "id": ident, "output": output}


def call(name, arguments):
    return {"type": "function_call", "name": name, "call_id": "call_" + name, "arguments": json.dumps(arguments)}


def answer(value):
    return {"type": "message", "content": [{"type": "output_text", "text": json.dumps(value)}]}


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    cases = Incidents(StateStore(tmp_path / "state.sqlite3"))
    case = cases.create({"EventId": str(uuid.uuid4()), "Timestamp": utc_text(datetime.now(UTC)),
                         "PeakAccelerationG": 3.7, "DeltaVKmh": 6}, fleet_vehicles()[0])
    mail = RepairMail.__new__(RepairMail)
    mail.cases, mail.config = cases, insurance_config()
    mail.operator = mail.customer = mail.config["customer_notification_mailbox"]
    mail.allowed = {mail.config["claims_mailbox"], *(g["mailbox"] for g in mail.config["garages"])}

    async def delivered(**delivery):
        mail.recipient(delivery["sender"], delivery["recipient"])
        mail.reserve(delivery["key"], case["id"], {"recipient": delivery["recipient"]})
        sent = {"id": "actual-message-id", "subject": delivery["subject"], "body": delivery["body"],
                "from": delivery["sender"], "to": delivery["recipient"], "at": utc_text(datetime.now(UTC)),
                "web_url": "https://outlook.office.com/mail/id/actual-message-id"}
        mail.update(delivery["key"], "sent", sent)
        return sent

    mail.send = AsyncMock(side_effect=delivered)
    agent = RepairAgents.__new__(RepairAgents)
    agent.cases, agent.mail = cases, mail
    agent.endpoint = "https://test.services.ai.azure.com/api/projects/repair"
    agent.config = {
        "foundry_project_id": "/subscriptions/test/project",
        "repair_tool_agents": {"cdv_repaircoordinator": {
            "name": "repair", "id": "repair:1", "version": "1", "display_name": "Repair coordinator",
        }},
    }
    policy = {"source": policy_reference(), "citations": [policy_reference()["document_url"]],
              "document_text": "Word text retrieved through Work IQ.", "answer": "Grounded policy answer.",
              "document_id": policy_reference()["drive_item_id"],
              "retrieved_at": utc_text(datetime.now(UTC))}
    agent.workiq = SimpleNamespace(read_policy=AsyncMock(return_value=policy), token=lambda _: "unit-test-token")
    replies, requests = [], []

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def post(self, url, **kwargs):
            requests.append(kwargs["json"])
            value = replies.pop(0)
            return value if isinstance(value, httpx.Response) else httpx.Response(200, json=value, request=httpx.Request("POST", url))

    monkeypatch.setattr("fleet.repair_agents.httpx.AsyncClient", lambda **_: Client())
    return agent, cases, case, replies, requests


async def test_agent_must_request_policy_and_receives_real_tool_output(runtime):
    agent, cases, case, replies, requests = runtime
    replies.extend([
        response([call("read_repair_policy", {"case_id": case["id"]})]),
        response([answer({"garage_id": "metro"})], "resp_2"),
    ])
    result = await agent.invoke("cdv_repaircoordinator", {"operation": "recommend", "case_id": case["id"]})
    agent.workiq.read_policy.assert_awaited_once()
    assert "Word text retrieved" not in json.dumps(requests[0])
    outputs = [item for item in requests[1]["input"] if item["type"] == "function_call_output"]
    assert json.loads(outputs[0]["output"])["document_text"] == "Word text retrieved through Work IQ."
    assert result["agent"]["provider"] == "Microsoft Foundry Agent Service"
    record = cases.get(case["id"])
    assert record["work_iq_policy"]["document_id"] == policy_reference()["drive_item_id"]
    assert requests[0]["agent_reference"]["version"] == "1"
    assert requests[0]["tool_choice"] == {"type": "function", "name": "read_repair_policy"}
    assert requests[1]["tool_choice"] == "none"
    assert all(request["parallel_tool_calls"] is False for request in requests)
    assert record["agent_actions"][0]["tool"] == "read_repair_policy"
    assert "document_text" not in record["work_iq_policy"]


async def test_recommendation_without_work_iq_call_is_not_accepted(runtime):
    agent, _, case, replies, _ = runtime
    replies.append(response([answer({"garage_id": "metro", "claimed_policy_lookup": True})]))
    with pytest.raises(IncidentError, match="did not retrieve"):
        await agent.invoke("cdv_repaircoordinator", {"operation": "recommend", "case_id": case["id"]})
    agent.workiq.read_policy.assert_not_awaited()
    agent.mail.send.assert_not_awaited()


def delivery(agent, case):
    return {"key": case["id"] + "/customer-incident-email", "case_id": case["id"],
            "sender": agent.mail.config["claims_mailbox"], "recipient": agent.mail.customer,
            "subject": "[" + case["id"] + "] [NOTICE] Reviewed case update", "body": "Reviewed incident email."}


async def test_only_a_real_native_email_tool_call_can_dispatch_and_retry_is_idempotent(runtime):
    agent, cases, case, replies, _ = runtime
    intent = delivery(agent, case)
    replies.extend([
        response([call("send_repair_email", {"delivery_id": intent["key"]})]),
        response([answer({"sent": True, "message_id": "actual-message-id"})], "resp_2"),
    ])
    first = await agent.send(**intent)
    repeated = await agent.send(**intent)
    assert first == repeated and first["id"] == "actual-message-id"
    agent.mail.send.assert_awaited_once_with(**intent)
    assert first["agent"]["call_id"] == "call_send_repair_email"
    assert cases.get(case["id"])["agent_actions"][0]["message_id"] == "actual-message-id"
    agent.workiq.read_policy.assert_not_awaited()


async def test_agent_cannot_claim_email_success_without_invoking_the_tool(runtime):
    agent, _, case, replies, _ = runtime
    replies.append(response([answer({"sent": True, "message_id": "invented"})]))
    with pytest.raises(IncidentError, match="No email was sent"):
        await agent.send(**delivery(agent, case))
    agent.mail.send.assert_not_awaited()


async def test_native_rate_limit_retries_do_not_duplicate_email_delivery(runtime, monkeypatch):
    agent, _, case, replies, requests = runtime
    intent = delivery(agent, case)
    limited = lambda: httpx.Response(429, headers={"Retry-After": "1"}, request=httpx.Request("POST", agent.endpoint))
    replies.extend([
        limited(), response([call("send_repair_email", {"delivery_id": intent["key"]})]),
        limited(), response([answer({"sent": True, "message_id": "actual-message-id"})], "resp_2"),
    ])
    sleeper = AsyncMock()
    monkeypatch.setattr("fleet.repair_agents.asyncio.sleep", sleeper)
    await agent.send(**intent)
    assert sleeper.await_count == 2 and len(requests) == 4
    assert all(request["max_output_tokens"] == 512 for request in requests)
    agent.mail.send.assert_awaited_once()


async def test_agent_cannot_substitute_a_different_delivery_or_extra_recipients(runtime):
    agent, _, case, replies, _ = runtime
    replies.append(response([call("send_repair_email", {"delivery_id": "another-case", "recipient": "outside@example.com"})]))
    with pytest.raises(IncidentError, match="outside its reviewed delivery"):
        await agent.send(**delivery(agent, case))
    agent.mail.send.assert_not_awaited()


async def test_function_tools_preserve_tenant_and_approval_boundaries(runtime):
    agent, _, case, replies, requests = runtime
    intent = delivery(agent, case)
    with pytest.raises(IncidentError):
        await agent.send(**{**intent, "recipient": "outside@example.com"})
    assert not requests
    intent["subject"] = "[" + case["id"] + "] [BOOK] Approved repair request"
    replies.append(response([call("send_repair_email", {"delivery_id": intent["key"]})]))
    with pytest.raises(IncidentError, match="revalidate"):
        await agent.send(**intent)
    agent.mail.send.assert_not_awaited()


async def test_initial_report_email_reads_work_iq_without_submitting_customer_evidence(runtime):
    agent, cases, case, replies, requests = runtime
    intent = {**delivery(agent, case), "subject": "[" + case["id"] + "] [REPORT] Your secure incident report link"}
    replies.extend([
        response([call("read_repair_policy", {"case_id": case["id"]})]),
        response([call("send_repair_email", {"delivery_id": intent["key"]})], "resp_2"),
        response([answer({"sent": True, "message_id": "actual-message-id"})], "resp_3"),
    ])
    await agent.send(**intent)
    record = cases.get(case["id"])
    assert [action["tool"] for action in record["agent_actions"]] == ["read_repair_policy", "send_repair_email"]
    assert record["status"] == "awaiting_report" and not record["report_received"] and not record["photos"]
    assert [request["tool_choice"] for request in requests] == [
        {"type": "function", "name": "read_repair_policy"},
        {"type": "function", "name": "send_repair_email"}, "none",
    ]


async def test_response_provenance_must_match_the_pinned_native_agent(runtime):
    agent, _, case, replies, _ = runtime
    replies.append(response([{
        **call("read_repair_policy", {"case_id": case["id"]}),
        "agent_reference": {"name": "another-agent", "version": "1"},
    }]))
    with pytest.raises(IncidentError, match="different repair agent"):
        await agent.invoke("cdv_repaircoordinator", {"operation": "recommend", "case_id": case["id"]})
    agent.workiq.read_policy.assert_not_awaited()


async def test_backend_access_denial_is_not_reported_as_invalid_user_json(runtime):
    agent, _, case, replies, _ = runtime
    replies.append(httpx.Response(403, content=b"", request=httpx.Request("POST", agent.endpoint)))
    with pytest.raises(IncidentError, match=r"\(403\)") as denied:
        await agent.invoke("cdv_repaircoordinator", {"operation": "recommend", "case_id": case["id"]})
    assert denied.value.status == 502
    agent.workiq.read_policy.assert_not_awaited()


def test_work_iq_source_must_match_the_controlled_document():
    source = policy_reference()["document_url"]
    assert same_document(source + "&DefaultItemOpen=1", source)
    assert not same_document("https://outside.example/" + source, source)


@pytest.mark.parametrize("fault", [None, "denied", "wrong_document", "changed_text"])
async def test_work_iq_reads_actual_mcp_bytes_and_metadata_without_a_local_fallback(monkeypatch, fault):
    reference = policy_reference()
    content = policy_document().read_bytes()
    if fault == "changed_text":
        output = io.BytesIO()
        with zipfile.ZipFile(io.BytesIO(content)) as original, zipfile.ZipFile(output, "w") as changed:
            for item in original.infolist():
                data = original.read(item)
                if item.filename == "word/document.xml":
                    data = data.replace(b"OEM", b"AFTERMARKET")
                changed.writestr(item, data)
        content = output.getvalue()
    called = []

    @asynccontextmanager
    async def transport(url, **kwargs):
        assert url == WORK_IQ_MCP
        assert kwargs["headers"]["Authorization"] == "Bearer delegated-test-token"
        yield None, None, None

    class Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def initialize(self):
            pass

        async def call_tool(self, name, arguments):
            called.append((name, arguments))
            if fault == "denied":
                return SimpleNamespace(isError=True, model_dump_json=lambda: '{"error":"Access denied"}')
            if name == "fetch_blob":
                result = {"statusCode": 200, "base64Content": base64.b64encode(content).decode()}
            else:
                result = {"results": [{"statusCode": 200, "data": {
                    "id": "wrong" if fault == "wrong_document" else reference["drive_item_id"],
                    "eTag": '"actual-live-etag"', "webUrl": reference["document_url"],
                }}]}
            return SimpleNamespace(isError=False, structuredContent=result)

    monkeypatch.setattr("fleet.workiq.streamablehttp_client", transport)
    monkeypatch.setattr("fleet.workiq.ClientSession", lambda *_: Session())
    workiq = WorkIQSession.__new__(WorkIQSession)
    workiq.token = lambda: "delegated-test-token"
    if fault:
        with pytest.raises(IncidentError):
            await workiq.read_policy()
    else:
        result = await workiq.read_policy()
        assert result["document_text"] == word_text(content)
        assert result["source"]["etag"] == '"actual-live-etag"'
        assert result["citations"] == [reference["document_url"]]
        assert result["document_id"] == reference["drive_item_id"]
        assert [name for name, _ in called] == ["fetch_blob", "fetch"]


def test_policy_text_comparison_ignores_word_run_formatting_but_not_wording():
    def document(text):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as package:
            package.writestr("word/document.xml", '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p>' + text + "</w:p></w:body></w:document>")
        return buffer.getvalue()
    original = document("<w:r><w:t>New genuine OEM parts only.</w:t></w:r>")
    formatted = document("<w:r><w:t>New genuine </w:t></w:r><w:r><w:t>OEM parts only.</w:t></w:r>")
    changed = document("<w:r><w:t>Aftermarket parts allowed.</w:t></w:r>")
    assert word_text(original) == word_text(formatted)
    assert word_text(original) != word_text(changed)
