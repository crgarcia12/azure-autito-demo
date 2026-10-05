from __future__ import annotations

from fleet.demo_case import CUSTOMER_EMAIL, CUSTOMER_NAME, PHOTO, VEHICLE_ID
from fleet.evidence import safe_image
from fleet.foundry import CUSTOMER_AGENT_NAME, FoundryEvidenceAgent
from fleet.insurance import CustomerReport, IncidentError

def customer_prompt(vehicle: dict, telemetry: dict) -> str:
    return (
        f"Your rental car: {vehicle.get('Colour', '')} {vehicle.get('Make', '')} {vehicle.get('Model', '')}. Incident area: {vehicle.get('City', '')}.\n"
        f"The vehicle recorded a low-speed impact: peak {telemetry.get('PeakAccelerationG', '?')} g, "
        f"velocity change {telemetry.get('DeltaVKmh', '?')} km/h, "
        f"speed before impact {telemetry.get('SpeedBeforeKmh', telemetry.get('DeltaVKmh', '?'))} km/h.\n"
        "The attached image is the photo you took of the damage."
    )


def simulate_customer(cases, evidence, case_id: str, agent: FoundryEvidenceAgent | None = None) -> dict:
    record = cases.get(case_id)
    if record["status"] != "awaiting_report":
        raise IncidentError("The customer has already reported this incident.")
    if record["vehicle_id"] != VEHICLE_ID:
        raise IncidentError("The supplied photograph is for the green MINI Cooper (CD-006). Upload matching photos manually for other vehicles.", 400)
    config = evidence.config
    if not config.get("customer_agent_name"):
        raise IncidentError("The Foundry customer agent is not provisioned.", 503)
    agent = agent or FoundryEvidenceAgent(
        config, evidence.credential,
        agent_name=config["customer_agent_name"], agent_version=config["customer_agent_version"],
    )
    photo = PHOTO.read_bytes()
    result = agent.invoke(
        "Write the customer's incident report for this case. Use factual wording without company names or slogans. Return the JSON object.",
        customer_prompt(record["vehicle"], record.get("telemetry", {})), safe_image(photo)[0],
    )
    report = CustomerReport(
        injuries=False, description=str(result.data.get("description", "")),
        customer_name=CUSTOMER_NAME, customer_email=CUSTOMER_EMAIL,
        consent_to_share_redacted=True,
    )
    if not record["photos"]:
        evidence.add_photo(case_id, photo)

    def mark(item):
        item["customer_agent"] = {**result.trace, "name": "Customer report agent"}
        return {"response_id": result.trace["response_id"], "agent": result.trace["agent_name"]}
    cases.change(case_id, "customer_agent_reported", "Microsoft Foundry customer agent", mark)
    return cases.submit(case_id, report)
