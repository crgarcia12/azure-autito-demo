from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from decimal import Decimal
import json
import logging
import re

from fleet.domain import utc_text
from fleet.evidence import EvidenceService
from fleet.insurance import Incidents, IncidentError, Quote, compare_quotes, garage_offer, insurance_config
from fleet.mail import RepairMail, plain_body
from fleet.studio import StudioAgents
from fleet.config import settings

LOG = logging.getLogger("caldova.repairs")
QUOTE_START = "CALDOVA_QUOTE_JSON:"
BOOKING_START = "CALDOVA_BOOKING_JSON:"


def extract_payload(body: str, marker: str) -> dict:
    match = re.search(re.escape(marker) + r"\s*(\{[^\n]+\})", body)
    if not match:
        raise IncidentError("The repair-centre email lacks its required structured quotation.")
    value = json.loads(match.group(1))
    if not isinstance(value, dict):
        raise IncidentError("Invalid repair-centre payload.")
    return value


class RepairWorkflow:
    def __init__(self, cases: Incidents):
        self.cases = cases
        self.evidence = EvidenceService(cases)
        self.studio = StudioAgents()
        self.mail = RepairMail(cases)
        self.config = insurance_config()
        self.lock = asyncio.Lock()

    async def rfq(self, case_id: str) -> None:
        case = self.cases.get(case_id)
        if case["status"] not in {"report_ready", "requesting_quotes"}:
            raise IncidentError("The privacy-checked repair brief is not ready for distribution.")
        report = case["repair_report"]
        if not report["privacy_passed"] or report["requires_manual_review"] or report["repair_category"] != "bumper_cosmetic":
            raise IncidentError("Evidence needs manual review before it can be sent to garages.")
        generated_key = case_id + "/rfq-agent"
        generated = self.cases.store.get(generated_key)
        if not generated:
            generated = await self.studio.invoke("cdv_repaircoordinator", {
                "operation": "quote_request", "case_id": case_id,
                "vehicle": {key: case["vehicle"][key] for key in ("Make", "Model")},
                "redacted_report": report["summary"], "customer_description": report["redacted_description"],
                "photos": "Privacy-checked photographs are included in the attached repair brief PDF.",
                "requested_fields": ["total price including VAT in GBP", "start date", "return-to-service date", "scope", "exclusions", "warranty"],
                "deadline": "Respond within the current operational review window.",
            })
            self.cases.store.put(generated_key, generated)
        answer = generated["result"]
        if not isinstance(answer.get("body"), str) or len(answer["body"]) < 30:
            raise RuntimeError("The coordinator did not produce a complete quotation request.")
        if case["status"] == "report_ready":
            def started(current):
                if current["status"] != "report_ready":
                    raise IncidentError("The case changed before quotation requests began.")
                current["status"] = "requesting_quotes"
                current["rfq_agent"] = generated["agent"]
                return generated["agent"]
            self.cases.change(case_id, "quotes_requested", "Copilot Studio", started)
        attachment = (self.evidence.root / case_id / "repair-brief.pdf").read_bytes()
        for garage in self.config["garages"]:
            message = await self.mail.send(
                key=f"{case_id}/{garage['id']}/rfq", case_id=case_id,
                sender=self.config["claims_mailbox"], recipient=garage["mailbox"],
                subject=f"[{case_id}] [RFQ] Cosmetic bumper repair quotation",
                body=answer["body"] + f"\n\nCase reference: {case_id}\nQuotation only; no repair is authorised.",
                attachment=attachment,
            )
            self.mail.record(case_id, message, "rfq_email_sent", "Claims mailbox")
        def waiting(current):
            if current["status"] == "requesting_quotes":
                current["status"] = "awaiting_quotes"
            return {"repair_centres": 3}
        self.cases.change(case_id, "awaiting_garage_responses", "Workflow", waiting)

    async def garage_message(self, garage: dict, email: dict) -> None:
        sender = email.get("from", {}).get("emailAddress", {}).get("address", "").casefold()
        if sender != self.config["claims_mailbox"].casefold():
            return
        match = re.search(r"\[(CDI-[A-F0-9]{10})\]", email.get("subject", ""))
        if not match:
            return
        case_id = match.group(1)
        try:
            case = self.cases.get(case_id)
        except IncidentError as error:
            if error.status != 404:
                raise
            LOG.info("Ignoring garage message for a case not registered in this workflow: %s", case_id)
            return
        subject = email["subject"]
        if "[RFQ]" in subject and "[QUOTE]" not in subject:
            receipt = self.mail.operation(f"{case_id}/{garage['id']}/quote")
            if receipt and receipt["state"] == "sent":
                return
            key = f"{case_id}/{garage['id']}/quote-agent"
            generated = self.cases.store.get(key)
            offer = garage_offer(garage["id"], case_id, datetime.now(UTC))
            if generated is None:
                if case["status"] not in {"awaiting_quotes", "requesting_quotes"}:
                    return
                if not self.mail.operation(f"{case_id}/{garage['id']}/rfq"):
                    raise IncidentError("No matching outbound RFQ exists.")
                generated = await self.studio.invoke(garage["agent_schema"], {
                    "operation": "quote", "case_id": case_id, "repair_category": "bumper_cosmetic",
                    "redacted_report": case["repair_report"]["summary"],
                    "incoming_email": plain_body(email["body"]["content"])[:6000],
                    "trusted_offer": offer,
                })
                result = generated["result"]
                if result.get("decision") != "quote" or result.get("quote") != offer:
                    raise IncidentError(f"{garage['name']} needs further information or returned terms outside its approved rate card.")
                self.cases.store.put(key, generated)
            result = generated["result"]
            body = result["body"] + "\n\n" + QUOTE_START + json.dumps(result["quote"], separators=(",", ":"))
            sent = await self.mail.send(
                key=f"{case_id}/{garage['id']}/quote", case_id=case_id, sender=garage["mailbox"],
                recipient=self.config["claims_mailbox"], subject=f"[{case_id}] [QUOTE] {garage['name']}",
                body=body, reply_to_id=email["id"],
            )
            self.mail.record(case_id, sent, "garage_quote_sent", generated["agent"]["name"])
        elif "[BOOK]" in subject and "[BOOKED]" not in subject:
            receipt = self.mail.operation(f"{case_id}/{garage['id']}/booked")
            if receipt and receipt["state"] == "sent":
                return
            if case["status"] not in {"approved", "booking_requested"} or case.get("approval", {}).get("garage_id") != garage["id"]:
                return
            key = f"{case_id}/{garage['id']}/booking-agent"
            generated = self.cases.store.get(key)
            accepted = case["quotes"][garage["id"]]
            if generated is None:
                generated = await self.studio.invoke(garage["agent_schema"], {
                    "operation": "booking", "case_id": case_id, "garage_id": garage["id"],
                    "approved": True, "operator_approval": case["approval"], "accepted_quote": accepted,
                    "incoming_email": plain_body(email["body"]["content"])[:6000],
                })
                reply = generated["result"]
                if reply.get("decision") != "confirmed" or reply.get("case_id") != case_id or reply.get("garage_id") != garage["id"] or reply.get("ready_by") != accepted["ready_by"]:
                    raise IncidentError("The garage did not confirm the approved terms.")
                self.cases.store.put(key, generated)
            result = generated["result"]
            sent = await self.mail.send(
                key=f"{case_id}/{garage['id']}/booked", case_id=case_id, sender=garage["mailbox"],
                recipient=self.config["claims_mailbox"], subject=f"[{case_id}] [BOOKED] {garage['name']}",
                body=result["body"] + "\n\n" + BOOKING_START + json.dumps({
                    "case_id": case_id, "garage_id": garage["id"], "ready_by": accepted["ready_by"],
                }), reply_to_id=email["id"],
            )
            self.mail.record(case_id, sent, "garage_booking_confirmed", generated["agent"]["name"])

    async def claims_message(self, email: dict) -> None:
        sender = email.get("from", {}).get("emailAddress", {}).get("address", "").casefold()
        garage = next((item for item in self.config["garages"] if item["mailbox"].casefold() == sender), None)
        if garage is None:
            return
        match = re.search(r"\[(CDI-[A-F0-9]{10})\]", email.get("subject", ""))
        if not match:
            return
        case_id = match.group(1)
        try:
            case = self.cases.get(case_id)
        except IncidentError as error:
            if error.status != 404:
                raise
            LOG.info("Ignoring claims message for a case not registered in this workflow: %s", case_id)
            return
        body = plain_body(email["body"]["content"])
        if "[QUOTE]" in email["subject"]:
            if case["quotes"].get(garage["id"], {}).get("email_id") == email["id"]:
                return
            if case["status"] not in {"requesting_quotes", "awaiting_quotes", "recommendation_ready"}:
                return
            payload = extract_payload(body, QUOTE_START)
            trusted = self.cases.store.get(f"{case_id}/{garage['id']}/quote-agent")
            if trusted is None or payload != trusted["result"]["quote"]:
                raise IncidentError("A quote email does not match the verified native-agent response.")
            if payload["garage_id"] != garage["id"] or payload["case_id"] != case_id:
                raise IncidentError("Quote identity does not match the sender and case.")
            quote_value = Quote.model_validate({**payload, "email_id": email["id"], "agent_id": trusted["agent"]["id"]})
            message = self.mail.correspondence(email, "inbound", sender, self.config["claims_mailbox"])
            updated = self.cases.add_quote(quote_value, message)
            if updated["status"] == "recommendation_ready":
                await self.recommend(case_id)
        elif "[BOOKED]" in email["subject"]:
            payload = extract_payload(body, BOOKING_START)
            if case["status"] != "booking_requested" or case["approval"]["garage_id"] != garage["id"]:
                return
            if payload != {"case_id": case_id, "garage_id": garage["id"], "ready_by": case["quotes"][garage["id"]]["ready_by"]}:
                raise IncidentError("Booking confirmation differs from the approved terms.")
            message = self.mail.correspondence(email, "inbound", sender, self.config["claims_mailbox"])
            def booked(current):
                current["status"] = "booked"
                current["booking"] = {**payload, "confirmed_at": utc_text(datetime.now(UTC)), "email_id": email["id"]}
                current["correspondence"].append(message)
                return current["booking"]
            self.cases.change(case_id, "repair_booked", garage["name"], booked)

    async def recommend(self, case_id: str) -> None:
        case = self.cases.get(case_id)
        recommendation = compare_quotes(list(case["quotes"].values()), case["created_at"])
        result = await self.studio.invoke("cdv_repaircoordinator", {
            "operation": "recommend", "case_id": case_id, "quotations": recommendation["quotes"],
            "policy": recommendation["policy"], "human_approval_required": True,
        })
        if result["result"].get("garage_id") != recommendation["garage_id"] or result["result"].get("requires_approval") is not True:
            raise IncidentError("The AI recommendation did not satisfy the explicit repair policy.")
        def prepared(current):
            if current["status"] != "recommendation_ready":
                raise IncidentError("The case changed during recommendation generation.")
            current["recommendation"]["agent"] = result["agent"]
            current["recommendation"]["ai_summary"] = result["result"]
            return {"garage_id": recommendation["garage_id"], "agent": result["agent"]}
        self.cases.change(case_id, "recommendation_prepared", "Copilot Studio", prepared)

    async def book(self, case_id: str) -> None:
        case = self.cases.get(case_id)
        if case["status"] != "approved":
            raise IncidentError("Operator approval is required before booking.")
        current_choice = compare_quotes(list(case["quotes"].values()), case["created_at"])
        if current_choice["garage_id"] != case["approval"]["garage_id"]:
            raise IncidentError("The approved recommendation is no longer current. Review refreshed quotations.")
        garage = next(item for item in self.config["garages"] if item["id"] == case["approval"]["garage_id"])
        offer = case["quotes"][garage["id"]]
        body = (
            f"Caldova approves your quotation for {case_id}.\n"
            f"Approved total including VAT: GBP {offer['amount_gbp']}.\n"
            f"Start: {offer['available_from']}. Expected return: {offer['ready_by']}.\n"
            f"Scope: {offer['scope']}\nExclusions: {offer['exclusions']}\n"
            "Please confirm the booking on these terms. Additional work requires further approval."
        )
        sent = await self.mail.send(
            key=f"{case_id}/{garage['id']}/booking-request", case_id=case_id,
            sender=self.config["claims_mailbox"], recipient=garage["mailbox"],
            subject=f"[{case_id}] [BOOK] Approved repair request", body=body,
        )
        def requested(current):
            if current["status"] != "approved":
                raise IncidentError("The case changed before booking dispatch.")
            current["status"] = "booking_requested"
            current["correspondence"].append(sent)
            return {"garage_id": garage["id"], "message_id": sent["id"]}
        self.cases.change(case_id, "booking_request_sent", "Claims mailbox", requested)

    async def notify_operator(self, case_id: str, *, booked: bool) -> None:
        case = self.cases.get(case_id)
        recommendation = case["recommendation"]
        key = f"{case_id}/operator-{'booking' if booked else 'decision'}"
        receipt = self.mail.operation(key)
        if receipt and receipt["state"] == "sent":
            return
        config = settings()
        heading = "Repair booking confirmed" if booked else "Repair recommendation ready for your approval"
        rows = recommendation["quotes"]
        comparison = "\n".join(
            f"- {item['garage_name']}: repair GBP {item['amount_gbp']}; available {item['available_from']}; "
            f"return {item['ready_by']}; {item['downtime_days']} calendar downtime days; total expected GBP {item['total_expected_gbp']}."
            for item in rows
        )
        body = (
            f"{heading}\n\nCase {case_id} | Vehicle {case['vehicle_id']} | {case['vehicle']['Make']} {case['vehicle']['Model']}\n\n"
            f"{case['repair_report']['summary']}\n\n"
            f"{recommendation['rationale']}\n\n"
            f"Quotation comparison at GBP {recommendation['policy']['downtime_cost_per_day']} per downtime day:\n{comparison}\n\n"
            f"{'The selected garage has confirmed the approved booking.' if booked else 'No booking has been made. Open the case and select Approve & book only after reviewing the evidence and quotes.'}\n\n"
            f"Case dashboard: {config['appUrl']}/#incidents?case={case_id}\n"
            f"Sources: Fabric vehicle telemetry; the customer report; the three original quotation replies; "
            f"Copilot Studio agent {recommendation['agent']['name']} ({recommendation['agent']['id']})."
        )
        message = await self.mail.send(
            key=key, case_id=case_id, sender=self.config["claims_mailbox"],
            recipient=config["report_recipient"], subject=f"[{case_id}] {heading}", body=body,
        )
        self.mail.record(case_id, message, "operator_notified", "Claims coordination")

    async def cycle(self) -> None:
        async with self.lock:
            for case in self.cases.list():
                try:
                    if case["status"] == "evidence_received":
                        await self.evidence.assess(case["id"])
                    elif case["status"] in {"report_ready", "requesting_quotes"}:
                        await self.rfq(case["id"])
                    elif case["status"] == "recommendation_ready" and not case["recommendation"].get("agent"):
                        await self.recommend(case["id"])
                    elif case["status"] == "recommendation_ready":
                        await self.notify_operator(case["id"], booked=False)
                    elif case["status"] == "approved":
                        await self.book(case["id"])
                    elif case["status"] == "booked":
                        await self.notify_operator(case["id"], booked=True)
                    self.cases.store.put(f"repair-error/{case['id']}", None)
                except Exception as error:
                    LOG.exception("Case %s processing failed", case["id"])
                    self.cases.store.put(f"repair-error/{case['id']}", {"at": utc_text(datetime.now(UTC)), "message": str(error)[:1200]})
            for garage in self.config["garages"]:
                for email in reversed(await self.mail.inbox(garage["mailbox"])):
                    await self.garage_message(garage, email)
            for email in reversed(await self.mail.inbox(self.config["claims_mailbox"])):
                await self.claims_message(email)
