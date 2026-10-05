from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from decimal import Decimal
import json
import logging
import re
from urllib.parse import urlparse

from fleet.domain import utc_text
from fleet.evidence import EvidenceService
from fleet.insurance import Incidents, IncidentError, Quote, compare_quotes, garage_offer, insurance_config, require_approved_quote
from fleet.mail import RepairMail, plain_body
from fleet.repair_policy import policy_email_text, policy_reference, repair_policy
from fleet.studio import StudioAgents
from fleet.config import settings

LOG = logging.getLogger("caldova.repairs")
QUOTE_START = "QUOTE_DATA_JSON:"
BOOKING_START = "BOOKING_DATA_JSON:"
INTERNAL_EMAIL_NOTE = re.compile(
    r"\b(?:no personal (?:identifiers|information|data)|privacy (?:check|verification)|"
    r"redaction (?:check|verification)|(?:system|developer) (?:prompt|instructions))\b",
    re.IGNORECASE,
)


def validate_external_rfq(answer: dict) -> None:
    if not isinstance(answer.get("body"), str) or len(answer["body"]) < 30:
        raise IncidentError("The coordinator did not produce a complete quotation request.")
    if INTERNAL_EMAIL_NOTE.search(answer["body"]):
        raise IncidentError("The quotation email contains internal processing notes and must be regenerated before sending.")


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
        self.mail = RepairMail(cases)
        self.studio = StudioAgents()
        self.config = insurance_config()
        self.lock = asyncio.Lock()

    async def notify_customer(self, case_id: str) -> None:
        case = self.cases.get(case_id)
        key = f"{case_id}/customer-incident-email"
        receipt = self.mail.operation(key)
        if receipt and receipt["state"] == "sent":
            self.mail.record(case_id, receipt["result"], "customer_notification_sent", "Claims mailbox")
            return
        if case["status"] != "awaiting_report" or case["report_received"] or case.get("evidence_history"):
            return
        content_key = key + "/content"
        content = self.cases.store.get(content_key)
        if content is None:
            link = self.cases.reporting_link(case_id, settings()["appUrl"])
            vehicle = case["vehicle"]
            vehicle_description = " ".join(value for value in (vehicle.get("Colour"), vehicle["Make"], vehicle["Model"]) if value)
            content = {
                "recipient": self.config["customer_notification_mailbox"],
                "subject": f"[{case_id}] [REPORT] Your secure incident report link",
                "url": link["url"],
                "body": (
                    "Incident report request\n\n"
                    f"We detected a possible impact involving your rental {vehicle_description} "
                    f"({vehicle['Registration']}).\n\n"
                    "Your safety comes first. In an emergency call 999. Please complete the report only when you are in a safe place.\n\n"
                    "Tell us what happened using your secure reporting page:\n"
                    f"{link['url']}\n\n"
                    "On the page, add photographs of the affected area and briefly describe what happened. "
                    "Avoid including faces, personal documents or other identifying details in the photographs.\n\n"
                    f"Your case reference is {case_id}."
                ),
            }
            self.cases.store.create(content_key, content)
            content = self.cases.store.get(content_key)
        # A retry must retain the original email's link, not silently send an expired or replaced one.
        self.cases.authorize(case_id, urlparse(content["url"]).fragment)
        message = await self.mail.send(
            key=key, case_id=case_id, sender=self.config["claims_mailbox"],
            recipient=content["recipient"], subject=content["subject"], body=content["body"],
        )
        self.mail.record(case_id, message, "customer_notification_sent", "Claims mailbox")

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
                "audience": "External garage. The body will be sent as an actual quotation-request email, not an internal report.",
                "vehicle": {key: case["vehicle"][key] for key in ("Make", "Model")},
                "redacted_report": report["summary"], "customer_description": report["redacted_description"],
                "photos": "Privacy-checked photographs are included in the attached repair brief PDF.",
                "requested_fields": ["total price including VAT in GBP", "start date", "return-to-service date", "scope", "exclusions", "warranty",
                                     "whether replacement parts are required", "each part's component, manufacturer, origin, condition and vehicle-manufacturer approval",
                                     "written parts declaration", "repair policy identifier and version"],
                "repair_policy": {**repair_policy(), **policy_reference()},
                "deadline": "Respond within the current operational review window.",
            })
            validate_external_rfq(generated["result"])
            self.cases.store.put(generated_key, generated)
        answer = generated["result"]
        validate_external_rfq(answer)
        if case["status"] == "report_ready":
            def started(current):
                if current["status"] != "report_ready":
                    raise IncidentError("The case changed before quotation requests began.")
                current["status"] = "requesting_quotes"
                current["rfq_agent"] = generated["agent"]
                return generated["agent"]
            self.cases.change(case_id, "quotes_requested", generated["agent"]["name"], started)
        attachment = (self.evidence.root / case_id / "repair-brief.pdf").read_bytes()
        for garage in self.config["garages"]:
            message = await self.mail.send(
                key=f"{case_id}/{garage['id']}/rfq", case_id=case_id,
                sender=self.config["claims_mailbox"], recipient=garage["mailbox"],
                subject=f"[{case_id}] [RFQ] Bumper repair and parts quotation",
                body=answer["body"] + f"\n\nCase reference: {case_id}\nQuotation only; no repair is authorised.\n\n" + policy_email_text(),
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
            offer = garage_offer(garage["id"], case_id, datetime.now(UTC), vehicle=case["vehicle"])
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
                    "repair_policy": {**repair_policy(), **policy_reference()},
                })
                result = generated["result"]
                if result.get("decision") != "quote" or result.get("quote") != offer:
                    self.cases.store.put(key + "/rejected", generated)
                    actual = result.get("quote")
                    changed = [field for field, value in offer.items() if not isinstance(actual, dict) or actual.get(field) != value]
                    raise IncidentError(
                        f"{garage['name']} did not return its approved quotation: decision={result.get('decision')}; "
                        f"changed fields={', '.join(changed[:8]) or 'none'}. The response has been retained for review."
                    )
                self.cases.store.put(key, generated)
            result = generated["result"]
            body = (
                result["body"] + "\n\nSupplier's binding parts declaration:\n" + result["quote"].get("parts_statement", "Not supplied; written clarification is required.")
                + "\n\n" + QUOTE_START + json.dumps(result["quote"], separators=(",", ":"))
            )
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
            accepted = require_approved_quote(case)
            commitment = self.booking_commitment(case)
            if generated is None:
                generated = await self.studio.invoke(garage["agent_schema"], {
                    "operation": "booking", "case_id": case_id, "garage_id": garage["id"],
                    "approved": True, "operator_approval": case["approval"], "accepted_quote": accepted,
                    "booking_commitment": commitment, "repair_policy": case["approval"]["policy"],
                    "incoming_email": plain_body(email["body"]["content"])[:6000],
                })
                reply = generated["result"]
                if reply.get("decision") != "confirmed" or any(reply.get(key) != value for key, value in commitment.items()):
                    raise IncidentError("The garage did not confirm the approved terms.")
                self.cases.store.put(key, generated)
            result = generated["result"]
            sent = await self.mail.send(
                key=f"{case_id}/{garage['id']}/booked", case_id=case_id, sender=garage["mailbox"],
                recipient=self.config["claims_mailbox"], subject=f"[{case_id}] [BOOKED] {garage['name']}",
                body=result["body"] + "\n\nConfirmed parts commitment:\n" + accepted["parts_statement"]
                + "\nNo parts substitution or additional work is authorised without a compliant revised quotation and operator approval.\n\n"
                + BOOKING_START + json.dumps(commitment), reply_to_id=email["id"],
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
            if case["status"] not in {"requesting_quotes", "awaiting_quotes", "recommendation_ready", "quote_review_required"}:
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
            require_approved_quote(case)
            if payload != self.booking_commitment(case):
                raise IncidentError("Booking confirmation differs from the approved terms.")
            trusted = self.cases.store.get(f"{case_id}/{garage['id']}/booking-agent")
            if not trusted or trusted["result"].get("decision") != "confirmed" or any(
                trusted["result"].get(key) != value for key, value in payload.items()
            ):
                raise IncidentError("The confirmation does not match a verified native-agent booking commitment.")
            message = self.mail.correspondence(email, "inbound", sender, self.config["claims_mailbox"])
            def booked(current):
                require_approved_quote(current)
                if current["status"] != "booking_requested" or self.booking_commitment(current) != payload:
                    raise IncidentError("The approved booking terms changed before confirmation.")
                current["status"] = "booked"
                current["booking"] = {**payload, "confirmed_at": utc_text(datetime.now(UTC)), "email_id": email["id"]}
                current["correspondence"].append(message)
                return current["booking"]
            self.cases.change(case_id, "repair_booked", garage["name"], booked)

    async def recommend(self, case_id: str) -> None:
        case = self.cases.get(case_id)
        recommendation = compare_quotes(list(case["quotes"].values()), case["created_at"])
        if not recommendation["garage_id"]:
            raise IncidentError(recommendation["rationale"])
        result = await self.studio.invoke("cdv_repaircoordinator", {
            "operation": "recommend", "case_id": case_id, "quotations": recommendation["quotes"],
            "policy": recommendation["policy"], "human_approval_required": True,
            "repair_policy_clauses": repair_policy()["clauses"],
            "eligible_garage_ids": recommendation["eligible_garage_ids"],
        })
        if result["result"].get("garage_id") != recommendation["garage_id"] or result["result"].get("requires_approval") is not True:
            raise IncidentError("The AI recommendation did not satisfy the explicit repair policy.")
        expected_exclusions = sorted(item["garage_id"] for item in recommendation["quotes"] if not item["compliance"]["eligible"])
        if (result["result"].get("policy_id") != recommendation["policy"]["id"]
                or result["result"].get("policy_version") != recommendation["policy"]["version"]
                or sorted(result["result"].get("excluded_garage_ids", [])) != expected_exclusions):
            raise IncidentError("The coordinator did not acknowledge the policy and excluded quotations.")
        latest = self.cases.get(case_id)
        if compare_quotes(list(latest["quotes"].values()), latest["created_at"])["quote_set_sha256"] != recommendation["quote_set_sha256"]:
            raise IncidentError("The quotations changed while the agent was reviewing them.")
        def prepared(current):
            if current["status"] != "recommendation_ready":
                raise IncidentError("The case changed during recommendation generation.")
            current["recommendation"] = {**recommendation, "agent": result["agent"], "ai_summary": result["result"]}
            return {"garage_id": recommendation["garage_id"], "agent": result["agent"]}
        self.cases.change(case_id, "recommendation_prepared", result["agent"]["name"], prepared, version=latest["version"])

    @staticmethod
    def booking_commitment(case: dict) -> dict:
        approval = case["approval"]
        quote = case["quotes"][approval["garage_id"]]
        return {
            "case_id": case["id"], "garage_id": approval["garage_id"], "ready_by": quote["ready_by"],
            "quote_sha256": approval["quote_sha256"], "policy_id": approval["policy"]["id"],
            "policy_version": approval["policy"]["version"],
        }

    async def book(self, case_id: str) -> None:
        case = self.cases.get(case_id)
        if case["status"] != "approved":
            raise IncidentError("Operator approval is required before booking.")
        current_choice = compare_quotes(list(case["quotes"].values()), case["created_at"])
        if (current_choice["garage_id"] != case["approval"].get("recommended_garage_id", case["approval"]["garage_id"])
                or current_choice["quote_set_sha256"] != case["approval"].get("quote_set_sha256")):
            raise IncidentError("The quotations changed after approval. Review refreshed quotations.")
        garage = next(item for item in self.config["garages"] if item["id"] == case["approval"]["garage_id"])
        offer = require_approved_quote(case)
        body = (
            f"Your quotation for {case_id} has been approved.\n"
            f"Approved total including VAT: GBP {offer['amount_gbp']}.\n"
            f"Start: {offer['available_from']}. Expected return: {offer['ready_by']}.\n"
            f"Scope: {offer['scope']}\nExclusions: {offer['exclusions']}\n"
            f"Approved parts declaration: {offer['parts_statement']}\n"
            f"Policy: {case['approval']['policy']['id']} v{case['approval']['policy']['version']} (RP-02, RP-07).\n"
            "Please confirm the booking on these exact terms. No parts substitution or additional work is authorised without a compliant revised quotation and further operator approval."
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
        ready = bool(recommendation["garage_id"])
        heading = "Repair booking confirmed" if booked else "Repair recommendation ready for your approval" if ready else "Repair quotations require policy review"
        rows = recommendation["quotes"]
        comparison = "\n".join(
            f"- {item['garage_name']}: repair GBP {item['amount_gbp']}; available {item['available_from']}; "
            f"return {item['ready_by']}; {item['downtime_days']} calendar downtime days; total expected GBP {item['total_expected_gbp']}.\n"
            f"  Parts decision: {item.get('compliance', {}).get('status', 'not assessed under current policy')}.\n"
            f"  Supplier declaration: {item.get('parts_statement', 'Not recorded in this historical quotation.')}\n"
            + "".join(f"  {finding['clause']}: {finding['reason']}\n" for finding in item.get("compliance", {}).get("findings", []))
            for item in rows
        )
        if recommendation["policy"].get("id"):
            for item in rows:
                original = next((message for message in case["correspondence"] if message["id"] == item["email_id"]), None)
                if not original:
                    raise IncidentError("The original quotation email is missing from the decision evidence.")
                copy = await self.mail.send(
                    key=f"{case_id}/{item['garage_id']}/operator-quote", case_id=case_id,
                    sender=self.config["claims_mailbox"], recipient=config["report_recipient"],
                    subject=f"[{case_id}] Quotation evidence - {item['garage_name']}",
                    body=(
                        f"Original quotation received from {original['from']} at {original['at']}.\n"
                        f"Original subject: {original['subject']}\nOriginal Outlook message: {original['web_url']}\n"
                        f"Policy: {recommendation['policy']['id']} v{recommendation['policy']['version']}\n"
                        f"Word policy: {recommendation['policy']['document_url']}\n\n"
                        "The following is the original supplier response, retained unchanged:\n\n" + original["body"]
                    ),
                )
                self.mail.record(case_id, copy, "quotation_evidence_shared", "Claims coordination")
        approval = case.get("approval") or {}
        chosen = next((item["garage_name"] for item in rows if item["garage_id"] == approval.get("garage_id")), approval.get("garage_id", ""))
        decision = (
            f"Operator decision: {approval['by']} approved {chosen}"
            + (f", overriding the recommendation. Reason: {approval['reason']}" if approval.get("override") else ", as recommended.")
            + "\n\n" if booked and approval else ""
        )
        body = (
            f"{heading}\n\nCase {case_id} | Vehicle {case['vehicle_id']} | {case['vehicle']['Make']} {case['vehicle']['Model']}\n\n"
            f"{case['repair_report']['summary']}\n\n"
            f"{recommendation['rationale']}\n\n"
            f"Quotation comparison at GBP {recommendation['policy']['downtime_cost_per_day']} per downtime day:\n{comparison}\n\n"
            f"{decision}"
            f"{'The selected garage has confirmed the approved booking.' if booked else 'No booking has been made. Only compliant quotations may be approved; a reason cannot override prohibited parts.'}\n\n"
            + (f"Controlled Word policy: {recommendation['policy']['document_url']}\n"
               f"{recommendation['policy']['id']} v{recommendation['policy']['version']}: RP-02 requires new genuine OEM; RP-03 requires explicit evidence; RP-05 excludes prohibited parts before ranking; RP-07 requires human approval.\n\n"
               if recommendation["policy"].get("id") else "")
            + f"Case dashboard: {config['appUrl']}/#incidents?case={case_id}\n"
            f"Sources: Fabric vehicle telemetry; the customer report; the three original quotation replies; "
            + (f"{recommendation['agent'].get('provider', 'Copilot Studio')} agent {recommendation['agent']['name']} ({recommendation['agent']['id']})."
               if recommendation.get("agent") else "deterministic repair-policy review. No eligible offer is recommended.")
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
                    if case["status"] == "awaiting_report":
                        await self.notify_customer(case["id"])
                    elif case["status"] == "evidence_received":
                        await self.evidence.assess(case["id"])
                    elif case["status"] in {"report_ready", "requesting_quotes"}:
                        await self.rfq(case["id"])
                    elif case["status"] == "recommendation_ready" and not case["recommendation"].get("agent"):
                        await self.recommend(case["id"])
                    elif case["status"] == "recommendation_ready":
                        await self.notify_operator(case["id"], booked=False)
                    elif case["status"] == "quote_review_required":
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
