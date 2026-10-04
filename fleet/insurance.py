from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
import hashlib
import hmac
import json
import math
import secrets
import sqlite3
import re
from typing import Literal
import uuid
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from fleet.config import ROOT
from fleet.domain import parse_time, utc_text
from fleet.repair_policy import ReplacementPart, evaluate_parts, policy_reference, repair_policy
from fleet.storage import StateStore


def insurance_config() -> dict:
    config = json.loads((ROOT / "insurance.config.json").read_text(encoding="utf-8"))
    for address in [config["claims_mailbox"], *(garage["mailbox"] for garage in config["garages"])]:
        assert_caldova_address(address)
    policy = repair_policy()
    if any(config[key] != policy[key] for key in ("currency", "downtime_cost_per_day", "maximum_repair_quote")):
        raise IncidentError("The operating cost assumptions differ from the controlled repair policy.")
    return config


def assert_caldova_address(address: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._+-]*@caldova08667473\.onmicrosoft\.com", address, re.IGNORECASE):
        raise IncidentError("All workflow email addresses must remain in the approved Caldova tenant.", 403)
    return address.casefold()


class IncidentError(ValueError):
    def __init__(self, message: str, status: int = 409):
        super().__init__(message)
        self.status = status


class CustomerReport(BaseModel):
    model_config = ConfigDict(extra="forbid")
    safe: bool
    injuries: bool
    description: str = Field(min_length=15, max_length=5000)
    customer_name: str = Field(default="", max_length=150)
    customer_email: str = Field(default="", max_length=254)
    consent_to_share_redacted: bool

    @field_validator("description")
    @classmethod
    def not_blank(cls, value: str) -> str:
        if len(value.strip()) < 15:
            raise ValueError("Please describe what happened.")
        return value.strip()


class Quote(BaseModel):
    model_config = ConfigDict(extra="forbid")
    garage_id: str
    case_id: str
    amount_gbp: Decimal = Field(gt=0, le=100000, decimal_places=2)
    currency: Literal["GBP"] = "GBP"
    available_from: date
    ready_by: date
    valid_until: datetime
    warranty_months: int = Field(ge=0, le=120)
    scope: str = Field(min_length=10, max_length=1500)
    exclusions: str = Field(default="", max_length=1500)
    replacement_parts_required: bool | None = Field(default=None, strict=True)
    replacement_parts: list[ReplacementPart] = Field(default_factory=list, max_length=30)
    parts_statement: str = Field(default="", max_length=2000)
    policy_id: str = Field(default="", max_length=60)
    policy_version: str = Field(default="", max_length=30)
    email_id: str = Field(min_length=1, max_length=1000)
    agent_id: str = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def validate_dates(self):
        if self.ready_by < self.available_from:
            raise ValueError("Completion cannot precede availability.")
        if self.valid_until.tzinfo is None:
            raise ValueError("Quote validity requires a timezone.")
        return self


def business_day(start: date, offset: int) -> date:
    cursor = start
    for _ in range(offset):
        cursor += timedelta(days=1)
        while cursor.weekday() >= 5:
            cursor += timedelta(days=1)
    return cursor


def garage_offer(garage_id: str, case_id: str, received_at: datetime, *, vehicle: dict | None = None) -> dict:
    config = insurance_config()
    garage = next((entry for entry in config["garages"] if entry["id"] == garage_id), None)
    if garage is None:
        raise IncidentError("Unknown approved repair centre.", 400)
    today = received_at.astimezone(ZoneInfo("Europe/London")).date()
    starts = business_day(today, garage["lead_business_days"])
    ends = business_day(starts, garage["repair_business_days"])
    policy = policy_reference()
    maker = vehicle["Make"] if vehicle else "Vehicle manufacturer genuine parts supply"
    manufacturer = garage.get("parts_manufacturer", maker)
    genuine = garage["parts_origin"] == "genuine_oem"
    statement = (
        f"We propose a new genuine {maker} OEM rear bumper cover, supplied through the vehicle manufacturer's "
        "authorised parts network and approved by the vehicle manufacturer for this vehicle. "
        "No aftermarket, used, refurbished or remanufactured substitutions are included."
        if genuine else
        f"We propose a new {manufacturer} aftermarket rear bumper cover. This is a non-OEM pattern part, "
        "not a genuine vehicle-manufacturer part. Its lower supply cost and stock availability allow our lower price and earlier return. "
        "This offer does not meet Caldova's new genuine OEM requirement; no compliant alternative is included."
    )
    return {
        "garage_id": garage_id, "case_id": case_id,
        "amount_gbp": str(garage["bumper_cosmetic_quote"]), "currency": "GBP",
        "available_from": starts.isoformat(), "ready_by": ends.isoformat(),
        "valid_until": utc_text(received_at + timedelta(days=config["quote_validity_days"])),
        "warranty_months": garage["warranty_months"],
        "scope": "Rear bumper cover replacement and refinishing, including the declared parts, materials, labour and VAT.",
        "exclusions": "Subject to physical inspection and final part-number/fitment confirmation. Structural, sensor, electrical and concealed damage require a revised quotation.",
        "replacement_parts_required": True,
        "replacement_parts": [{
            "component": "Rear bumper cover", "manufacturer": manufacturer,
            "origin": garage["parts_origin"], "condition": "new", "approved_for_vehicle": genuine,
        }],
        "parts_statement": statement, "policy_id": policy["id"], "policy_version": policy["version"],
    }


def quote_compliance(quote: Quote) -> dict:
    return evaluate_parts(
        quote.replacement_parts_required, quote.replacement_parts, quote.parts_statement,
        policy_id=quote.policy_id, policy_version=quote.policy_version,
    )


def quote_fingerprint(raw: dict) -> str:
    quote = Quote.model_validate(raw)
    return hashlib.sha256(json.dumps(quote.model_dump(mode="json"), sort_keys=True).encode()).hexdigest()


def require_compliant_quote(raw: dict) -> dict:
    compliance = quote_compliance(Quote.model_validate(raw))
    if not compliance["eligible"]:
        details = "; ".join(f"{item['clause']}: {item['reason']}" for item in compliance["findings"])
        raise IncidentError("This quotation cannot be approved or booked. " + details)
    return compliance


def require_approved_quote(case: dict) -> dict:
    approval = case.get("approval")
    if not approval or approval["garage_id"] not in case["quotes"]:
        raise IncidentError("A recorded operator approval for the selected quotation is required.")
    quote = case["quotes"][approval["garage_id"]]
    require_compliant_quote(quote)
    if approval.get("quote_sha256") != quote_fingerprint(quote):
        raise IncidentError("The selected quotation differs from the approved terms. Review and approve a current quotation.")
    if approval.get("policy", {}).get("source_sha256") != policy_reference()["source_sha256"]:
        raise IncidentError("The repair policy changed after approval. A new policy review and approval are required.")
    return quote


def compare_quotes(quotes: list[dict], detected_at: str, *, now: datetime | None = None) -> dict:
    config = insurance_config()
    now = now or datetime.now(UTC)
    today = now.astimezone(ZoneInfo("Europe/London")).date()
    incident_day = parse_time(detected_at).astimezone(ZoneInfo("Europe/London")).date()
    allowed = {garage["id"]: garage for garage in config["garages"]}
    costs = []
    for raw in quotes:
        quote = Quote.model_validate(raw)
        if quote.garage_id not in allowed or not allowed[quote.garage_id]["approved"]:
            raise IncidentError("A quote is from an unapproved repair centre.")
        if quote.valid_until <= now or quote.available_from < today:
            raise IncidentError("A quotation or its offered start date has expired. Request refreshed quotes.")
        amount = quote.amount_gbp
        if amount > Decimal(str(config["maximum_repair_quote"])):
            raise IncidentError("A quote exceeds the delegated repair limit. Manual review is required.")
        days = max(0, (quote.ready_by - incident_day).days)
        downtime = Decimal(days) * Decimal(str(config["downtime_cost_per_day"]))
        costs.append({
            **quote.model_dump(mode="json"), "garage_name": allowed[quote.garage_id]["name"],
            "downtime_days": days, "downtime_cost_gbp": str(downtime),
            "total_expected_gbp": str((amount + downtime).quantize(Decimal(".01"), rounding=ROUND_HALF_UP)),
            "compliance": quote_compliance(quote),
        })
    if set(allowed) != {entry["garage_id"] for entry in costs} or len(costs) != len(allowed):
        raise IncidentError("All three distinct approved repair-centre quotes are required.")
    costs.sort(key=lambda item: (not item["compliance"]["eligible"], Decimal(item["total_expected_gbp"]), item["ready_by"], item["garage_id"]))
    eligible = [item for item in costs if item["compliance"]["eligible"]]
    policy = {
        **policy_reference(), "currency": "GBP", "downtime_cost_per_day": config["downtime_cost_per_day"],
        "maximum_repair_quote": config["maximum_repair_quote"],
    }
    result = {
        "garage_id": None, "quotes": costs, "eligible_garage_ids": [item["garage_id"] for item in eligible],
        "policy": policy, "tradeoff": None,
        "quote_set_sha256": hashlib.sha256("".join(sorted(quote_fingerprint(raw) for raw in quotes)).encode()).hexdigest(),
        "calculated_at": utc_text(now),
    }
    if not eligible:
        result.update({
            "status": "quote_review_required",
            "rationale": "No compliant repair quotation is available. Obtain written parts clarification or a revised new genuine OEM offer under RP-02, RP-03 and RP-05. No booking is authorised.",
        })
        return result
    winner = eligible[0]
    cheapest = min(eligible, key=lambda item: Decimal(item["amount_gbp"]))
    lowest_received = min(costs, key=lambda item: Decimal(item["amount_gbp"]))
    saved = Decimal(cheapest["total_expected_gbp"]) - Decimal(winner["total_expected_gbp"])
    return {
        **result, "garage_id": winner["garage_id"], "status": "recommendation_ready",
        "tradeoff": {
            "lowest_repair_price_garage": cheapest["garage_name"],
            "repair_premium_gbp": str(Decimal(winner["amount_gbp"]) - Decimal(cheapest["amount_gbp"])),
            "days_saved": cheapest["downtime_days"] - winner["downtime_days"],
            "total_saving_gbp": str(saved),
            "lowest_received_garage": lowest_received["garage_name"],
            "lowest_received_eligible": lowest_received["compliance"]["eligible"],
        },
        "rationale": (
            f"{winner['garage_name']} has the lowest total expected cost among compliant quotations: GBP {Decimal(winner['total_expected_gbp']):,.2f}, "
            f"including GBP {Decimal(winner['amount_gbp']):,.2f} repair and {winner['downtime_days']} calendar days "
            f"of downtime at GBP {config['downtime_cost_per_day']}/day. Expected return: {winner['ready_by']}. "
            f"Saving versus the lowest compliant repair-price option: GBP {saved:,.2f}. "
            + " ".join(
                f"{item['garage_name']} is excluded ({item['compliance']['status']}): "
                + "; ".join(f"{finding['clause']}: {finding['reason']}" for finding in item["compliance"]["findings"]) + "."
                for item in costs if not item["compliance"]["eligible"]
            )
            + " Booking requires operator approval; RP-07 prohibits overriding parts compliance."
        ),
    }


class Incidents:
    def __init__(self, store: StateStore):
        self.store = store
        with store.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS incidents (
                    id TEXT PRIMARY KEY, source_event TEXT UNIQUE NOT NULL, vehicle_id TEXT NOT NULL,
                    created_at TEXT NOT NULL, updated_at TEXT NOT NULL, status TEXT NOT NULL,
                    version INTEGER NOT NULL, token_hash TEXT NOT NULL, token_expires TEXT NOT NULL,
                    data TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS incident_events (
                    id INTEGER PRIMARY KEY, case_id TEXT NOT NULL, at TEXT NOT NULL, kind TEXT NOT NULL,
                    actor TEXT NOT NULL, details TEXT NOT NULL, UNIQUE(case_id,kind,details)
                );
                CREATE TABLE IF NOT EXISTS incident_operations (
                    key TEXT PRIMARY KEY, case_id TEXT NOT NULL, state TEXT NOT NULL,
                    payload TEXT NOT NULL, result TEXT, updated_at TEXT NOT NULL
                );
            """)

    @staticmethod
    def public(record: dict, *, customer: bool = False) -> dict:
        result = {key: value for key, value in record.items() if key not in {"token_hash", "token", "token_expires"}}
        if customer:
            public = {key: result[key] for key in ("id", "vehicle_id", "created_at", "status", "vehicle", "report_received") if key in result}
            public["photo_count"] = len(record.get("photos", []))
            public["follow_up"] = record.get("follow_up", "")
            if result.get("booking"):
                garage = next(item for item in insurance_config()["garages"] if item["id"] == result["booking"]["garage_id"])
                public["booking"] = {"garage_name": garage["name"], "ready_by": result["booking"]["ready_by"]}
            return public
        result["repair_policy"] = policy_reference()
        result["quote_compliance"] = {
            garage: quote_compliance(Quote.model_validate(quote)) for garage, quote in record.get("quotes", {}).items()
        }
        return result

    def _row(self, row) -> dict:
        if row is None:
            raise IncidentError("Incident not found.", 404)
        data = json.loads(row[9])
        return {**data, "id": row[0], "source_event": row[1], "vehicle_id": row[2], "created_at": row[3],
                "updated_at": row[4], "status": row[5], "version": row[6], "token_hash": row[7], "token_expires": row[8]}

    def get(self, case_id: str) -> dict:
        with self.store.connect() as db:
            return self._row(db.execute("SELECT * FROM incidents WHERE id=?", (case_id,)).fetchone())

    def list(self) -> list[dict]:
        with self.store.connect() as db:
            return [self.public(self._row(row)) for row in db.execute("SELECT * FROM incidents ORDER BY created_at DESC LIMIT 100")]

    def timeline(self, case_id: str) -> list[dict]:
        with self.store.connect() as db:
            return [{"at": row[0], "kind": row[1], "actor": row[2], "details": json.loads(row[3])}
                    for row in db.execute("SELECT at,kind,actor,details FROM incident_events WHERE case_id=? ORDER BY id", (case_id,))]

    def create(self, event: dict, vehicle: dict) -> dict:
        case_id = "CDI-" + uuid.uuid5(uuid.NAMESPACE_URL, str(event["EventId"])).hex[:10].upper()
        token = secrets.token_urlsafe(32)
        now = utc_text(datetime.now(UTC))
        data = {
            "vehicle": {key: vehicle[key] for key in ("Registration", "Make", "Model", "City", "BranchId")},
            "telemetry": event, "report_received": False, "photos": [], "quotes": {}, "correspondence": [],
        }
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute("SELECT * FROM incidents WHERE source_event=?", (event["EventId"],)).fetchone()
            if existing:
                return self.public(self._row(existing))
            db.execute("INSERT INTO incidents VALUES (?,?,?,?,?,?,?,?,?,?)", (
                case_id, event["EventId"], vehicle["VehicleId"], now, now, "awaiting_report", 1,
                hashlib.sha256(token.encode()).hexdigest(),
                utc_text(datetime.now(UTC) + timedelta(hours=insurance_config()["customer_link_hours"])),
                json.dumps(data),
            ))
            self._event(db, case_id, "impact_detected", "Microsoft Fabric", {
                "event_id": event["EventId"], "peak_g": event["PeakAccelerationG"], "delta_v_kmh": event["DeltaVKmh"],
            })
            self._event(db, case_id, "customer_link_prepared", "Incident workflow", {
                "channel": "phone-preview", "expires_in_hours": insurance_config()["customer_link_hours"],
            })
        return {**self.public(self.get(case_id)), "token": token}

    def authorize(self, case_id: str, token: str) -> dict:
        record = self.get(case_id)
        if not token or not hmac.compare_digest(hashlib.sha256(token.encode()).hexdigest(), record["token_hash"]):
            raise IncidentError("This reporting link is invalid.", 403)
        if parse_time(record["token_expires"]) <= datetime.now(UTC):
            raise IncidentError("This reporting link has expired. Contact Caldova for a new link.", 403)
        return record

    def new_link(self, case_id: str) -> str:
        token = secrets.token_urlsafe(32)
        with self.store.connect() as db:
            changed = db.execute(
                "UPDATE incidents SET token_hash=?,token_expires=? WHERE id=?",
                (hashlib.sha256(token.encode()).hexdigest(), utc_text(datetime.now(UTC) + timedelta(hours=24)), case_id),
            ).rowcount
            if changed != 1:
                raise IncidentError("Incident not found.", 404)
        return token

    def change(self, case_id: str, kind: str, actor: str, transform, *, version: int | None = None) -> dict:
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            record = self._row(db.execute("SELECT * FROM incidents WHERE id=?", (case_id,)).fetchone())
            if version is not None and version != record["version"]:
                raise IncidentError("This case changed since you opened it. Refresh before approving.")
            details = transform(record)
            now = utc_text(datetime.now(UTC))
            db.execute(
                "UPDATE incidents SET updated_at=?,status=?,version=version+1,data=? WHERE id=?",
                (now, record["status"], json.dumps({key: value for key, value in record.items() if key not in {
                    "id", "source_event", "vehicle_id", "created_at", "updated_at", "status", "version", "token_hash", "token_expires",
                }}), case_id),
            )
            self._event(db, case_id, kind, actor, details)
        return self.public(self.get(case_id))

    @staticmethod
    def _event(db, case_id: str, kind: str, actor: str, details: dict) -> None:
        db.execute("INSERT OR IGNORE INTO incident_events(case_id,at,kind,actor,details) VALUES(?,?,?,?,?)",
                   (case_id, utc_text(datetime.now(UTC)), kind, actor, json.dumps(details, sort_keys=True)))

    def submit(self, case_id: str, report: CustomerReport) -> dict:
        if not report.consent_to_share_redacted and report.safe and not report.injuries:
            raise IncidentError("Consent is required before sharing a repair brief. Contact Caldova for assistance if you prefer not to share.", 400)
        def transform(record):
            if record["status"] != "awaiting_report":
                raise IncidentError("This incident report has already been submitted.")
            if not record["photos"]:
                raise IncidentError("Add at least one incident photo before submitting.", 400)
            record["customer_report"] = report.model_dump()
            record["report_received"] = True
            record["status"] = "assistance_required" if report.injuries or not report.safe else "evidence_received"
            return {"safe": report.safe, "injuries": report.injuries, "photo_count": len(record["photos"])}
        return self.change(case_id, "customer_reported", "Customer", transform)

    def add_quote(self, quote: Quote, original_email: dict) -> dict:
        config = insurance_config()
        expected = {garage["id"] for garage in config["garages"]}
        if quote.garage_id not in expected:
            raise IncidentError("Unapproved repair centre.", 403)
        def transform(record):
            if record["status"] not in {"requesting_quotes", "awaiting_quotes", "recommendation_ready", "quote_review_required"}:
                raise IncidentError("This case is not accepting repair quotations.")
            record["quotes"][quote.garage_id] = quote.model_dump(mode="json")
            if not any(message["id"] == original_email["id"] for message in record["correspondence"]):
                record["correspondence"].append(original_email)
            if set(record["quotes"]) == expected:
                record["recommendation"] = compare_quotes(list(record["quotes"].values()), record["created_at"])
                record["status"] = record["recommendation"]["status"]
            else:
                record["status"] = "awaiting_quotes"
            return {"garage_id": quote.garage_id, "email_id": quote.email_id, "agent_id": quote.agent_id}
        return self.change(quote.case_id, "quote_received", "Copilot Studio", transform)

    def approve(self, case_id: str, version: int, operator: str, garage_id: str | None = None, reason: str = "") -> dict:
        reason = reason.strip()
        def transform(record):
            if record["status"] != "recommendation_ready" or not record.get("recommendation", {}).get("agent"):
                raise IncidentError("A complete current recommendation is required before booking.")
            fresh = compare_quotes(list(record["quotes"].values()), record["created_at"])
            recommended = record["recommendation"]["garage_id"]
            if fresh["garage_id"] != recommended:
                raise IncidentError("The recommended option changed. Review it before approval.")
            if fresh["quote_set_sha256"] != record["recommendation"].get("quote_set_sha256"):
                raise IncidentError("The quotations changed or lack current parts evidence. Review refreshed quotations.")
            if fresh["policy"]["source_sha256"] != record["recommendation"]["policy"].get("source_sha256"):
                raise IncidentError("The repair policy changed. Review the current recommendation before approval.")
            chosen = garage_id or recommended
            if chosen not in record["quotes"]:
                raise IncidentError("Select one of the received repair quotations.", 400)
            require_compliant_quote(record["quotes"][chosen])
            override = chosen != recommended
            if override and not 10 <= len(reason) <= 500:
                raise IncidentError("Explain why you are choosing a different repair centre than the recommendation.", 400)
            record["approval"] = {
                "by": operator, "at": utc_text(datetime.now(UTC)), "garage_id": chosen,
                "recommended_garage_id": recommended, "override": override, "reason": reason if override else "",
                "quote_sha256": quote_fingerprint(record["quotes"][chosen]),
                "quote_set_sha256": fresh["quote_set_sha256"], "policy": fresh["policy"],
            }
            record["status"] = "approved"
            return record["approval"]
        return self.change(case_id, "operator_approved", operator, transform, version=version)

    def request_more_evidence(self, case_id: str, version: int, operator: str, reason: str) -> dict:
        if not 15 <= len(reason.strip()) <= 1000:
            raise IncidentError("Describe the additional evidence required.", 400)
        def transform(record):
            if record["status"] != "report_review_required":
                raise IncidentError("Only a case awaiting evidence review can be returned to the customer.")
            record.setdefault("evidence_history", []).append({
                "photos": record["photos"], "customer_report": record.get("customer_report"),
                "repair_report": record.get("repair_report"), "at": utc_text(datetime.now(UTC)),
            })
            record["photos"] = []
            record.pop("repair_report", None)
            record.pop("customer_report", None)
            record["report_received"] = False
            record["follow_up"] = reason.strip()
            record["status"] = "awaiting_report"
            return {"reason": reason.strip()}
        return self.change(case_id, "additional_evidence_requested", operator, transform, version=version)
