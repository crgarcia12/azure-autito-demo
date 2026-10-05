from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Literal
from urllib.parse import parse_qs, urlparse

from pydantic import BaseModel, ConfigDict, Field

from fleet.config import ROOT

POLICY_PATH = ROOT / "policies" / "repair-policy.json"
PUBLICATION_PATH = ROOT / "policies" / "publication.json"


class ReplacementPart(BaseModel):
    model_config = ConfigDict(extra="forbid")
    component: str = Field(min_length=3, max_length=200)
    manufacturer: str = Field(default="", max_length=200)
    origin: Literal["genuine_oem", "aftermarket", "unspecified"] = "unspecified"
    condition: Literal["new", "used", "refurbished", "remanufactured", "unspecified"] = "unspecified"
    approved_for_vehicle: bool | None = Field(default=None, strict=True)


def repair_policy() -> dict:
    policy = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
    if policy["replacement_parts_origin"] != "genuine_oem" or policy["replacement_parts_condition"] != "new":
        raise ValueError("The approved repair policy requires new genuine OEM replacement parts.")
    return policy


def policy_reference() -> dict:
    policy = repair_policy()
    digest = hashlib.sha256(POLICY_PATH.read_bytes()).hexdigest()
    reference = {
        "id": policy["id"], "title": policy["title"], "version": policy["version"],
        "effective_date": policy["effective_date"], "source_sha256": digest,
        "document_url": None, "document_sha256": None,
        "parts_clause": "RP-02", "evidence_clause": "RP-03", "selection_clause": "RP-05",
    }
    if PUBLICATION_PATH.exists():
        publication = json.loads(PUBLICATION_PATH.read_text(encoding="utf-8"))
        if publication["source_sha256"] != digest:
            raise ValueError("The repair policy changed after its Word document was published. Republish before using it.")
        reference.update({key: publication[key] for key in ("document_url", "document_sha256", "drive_item_id", "etag")})
    return reference


def policy_document() -> Path:
    reference = policy_reference()
    names = parse_qs(urlparse(reference["document_url"] or "").query).get("file", [])
    if len(names) != 1 or Path(names[0]).name != names[0] or not names[0].endswith(".docx"):
        raise ValueError("The policy publication must identify its controlled Word file.")
    document = POLICY_PATH.parent / names[0]
    if document.resolve().parent != POLICY_PATH.parent.resolve():
        raise ValueError("The controlled Word file must remain inside the policy directory.")
    return document


def evaluate_parts(
    replacement_parts_required: bool | None, parts: list[ReplacementPart], statement: str,
    *, policy_id: str, policy_version: str,
) -> dict:
    policy = repair_policy()
    findings = []
    if (policy_id, policy_version) != (policy["id"], policy["version"]):
        findings.append(("clarification_required", "RP-03", "The quotation has not addressed the current repair policy and version."))
    if replacement_parts_required is None:
        findings.append(("clarification_required", "RP-03", "The quotation does not say whether replacement parts are required."))
    elif replacement_parts_required:
        if not parts:
            findings.append(("clarification_required", "RP-03", "Replacement parts are proposed but none are identified."))
    elif parts:
        findings.append(("clarification_required", "RP-03", "The no-replacement declaration conflicts with the listed replacement parts."))
    elif not policy["allow_repair_without_replacement"]:
        findings.append(("noncompliant", "RP-04", "Repair without replacement is outside the current policy."))
    if len(statement.strip()) < 10:
        findings.append(("clarification_required", "RP-03", "An explicit written supplier parts declaration is required."))
    for part in parts:
        if part.origin == "aftermarket":
            findings.append(("noncompliant", "RP-02", f"{part.component}: aftermarket/non-OEM replacement parts are not permitted."))
        elif part.origin == "unspecified":
            findings.append(("clarification_required", "RP-03", f"{part.component}: genuine OEM origin has not been confirmed."))
        if part.condition in {"used", "refurbished", "remanufactured"}:
            findings.append(("noncompliant", "RP-02", f"{part.component}: {part.condition} replacement parts are not permitted."))
        elif part.condition == "unspecified":
            findings.append(("clarification_required", "RP-03", f"{part.component}: new condition has not been confirmed."))
        if not part.manufacturer.strip():
            findings.append(("clarification_required", "RP-03", f"{part.component}: the part manufacturer or genuine manufacturer supply is not identified."))
        if part.approved_for_vehicle is False:
            findings.append(("noncompliant", "RP-02", f"{part.component}: the part is not approved by the vehicle manufacturer for this vehicle."))
        elif part.approved_for_vehicle is None:
            findings.append(("clarification_required", "RP-03", f"{part.component}: vehicle-manufacturer approval is not confirmed."))
    status = "noncompliant" if any(item[0] == "noncompliant" for item in findings) else "clarification_required" if findings else "compliant"
    if not findings:
        findings = [("compliant", "RP-02" if replacement_parts_required else "RP-04",
                     "All proposed replacement parts are declared new genuine OEM and approved for the vehicle."
                     if replacement_parts_required else "The supplier explicitly confirms repair of the existing component without replacement parts.")]
    return {
        "status": status, "eligible": status == "compliant",
        "findings": [{"status": level, "clause": clause, "reason": reason} for level, clause, reason in findings],
        "statement": statement,
    }


def policy_email_text() -> str:
    reference = policy_reference()
    policy = repair_policy()
    lines = [f"Repair policy {reference['id']} v{reference['version']}"]
    if reference["document_url"]:
        lines.append("Controlled Word policy: " + reference["document_url"])
    lines.extend([
        "RP-02: Replacement parts must be new genuine OEM parts approved by the vehicle manufacturer. "
        "Aftermarket, used, refurbished and remanufactured replacements are not permitted.",
        "RP-03: Identify each proposed component, manufacturer, origin, condition and vehicle approval. "
        "Include your written parts declaration in the quotation.",
    ])
    if policy["allow_repair_without_replacement"]:
        lines.append("RP-04: If no replacement parts are needed, explicitly confirm that the existing component will be repaired, subject to inspection.")
    lines.append("Quotation only. No repair is authorised without a subsequent written approval.")
    return "\n".join(lines)
