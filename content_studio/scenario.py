from __future__ import annotations

from datetime import UTC, datetime, timedelta
import json
import uuid
from zoneinfo import ZoneInfo

from fleet.domain import previous_day, utc_text
from fleet.fabric import FabricData
from tools.cloud import CONFIG, ROOT


def build_plan() -> dict:
    options = json.loads((ROOT / "content.config.json").read_text(encoding="utf-8"))
    data = FabricData()
    day, start, end = previous_day(datetime.now(UTC), CONFIG["report_timezone"])
    mileage = data.mileage(day)
    vehicles = data.latest()
    if len(mileage) != CONFIG["fleet_size"] or len(vehicles) != CONFIG["fleet_size"]:
        raise RuntimeError("The scenario needs complete real Fabric data for all 40 cars.")
    total = sum(row["DistanceKm"] for row in mileage)
    active = sum(row["DistanceKm"] > 0 for row in mileage)
    branches = {}
    for row in mileage:
        branches[row["City"]] = branches.get(row["City"], 0) + row["DistanceKm"]
    branch_summary = "; ".join(f"{city}: {km:,.1f} km" for city, km in sorted(branches.items(), key=lambda item: item[1], reverse=True))
    top = sorted(mileage, key=lambda row: row["DistanceKm"], reverse=True)[:3]
    leaders = "; ".join(f"{row['VehicleId']} ({row['Registration']}, {row['City']}): {row['DistanceKm']:,.1f} km" for row in top)
    alerts = [vehicle for vehicle in vehicles if vehicle["Alert"]]
    snapshot_at = max(vehicle["Timestamp"] for vehicle in vehicles)
    attention = "; ".join(f"{vehicle['VehicleId']} in {vehicle['City']}: {vehicle['Alert']}" for vehicle in alerts)
    electric = [vehicle for vehicle in vehicles if vehicle["Powertrain"] == "Electric"]
    low = [vehicle for vehicle in electric if vehicle["BatteryPct"] < 20]
    low_energy = "; ".join(f"{vehicle['VehicleId']} in {vehicle['City']} at {vehicle['BatteryPct']:.0f}%" for vehicle in low) or "No cars are below the 20% review threshold in the current snapshot"
    parked = ", ".join(row["VehicleId"] for row in mileage if row["DistanceKm"] == 0)
    source = (
        f"Fabric reporting date {day.isoformat()}, Europe/Madrid; "
        f"period [{utc_text(start)}, {utc_text(end)}). Latest vehicle snapshot: {snapshot_at}."
    )
    scenario_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"caldova-iq/{day.isoformat()}/rich-v1"))
    authors = [author["upn"] for author in options["authors"]]
    members = [*authors, options["observer"]]

    threads = [
        ("Morning fleet handover", [
            f"The {day:%d %B} handover is ready. Fabric records {total:,.1f} km from {active} active cars out of {len(mileage)}. Please align today's branch decisions to that closed-day baseline.",
            f"I have the branch split: {branch_summary}. London and Birmingham should get the first allocation review.",
            f"Accounting check passed: we are summing DailyMileage.DistanceKm, not odometer readings. {source}",
            "Aisha, review airport pick-up capacity and the return queue. Keep available cars separate from cars waiting on a health inspection.",
            f"Current exceptions are {attention}. I will exclude those cars from automatic reallocations until their release is confirmed.",
            f"The highest-distance cars were {leaders}. These belong in the maintenance planning discussion, not a blanket service hold.",
            "Let's use the dashboard for current positions and the closed-day table for yesterday's performance. We should not mix those time windows in the executive summary.",
            "Agreed. I will carry branch actions into the handover meeting and keep one owner and one next checkpoint for each exception.",
        ]),
        ("Heathrow peak-demand allocation", [
            f"London contributed {branches.get('London', 0):,.1f} km on {day.isoformat()}. Let's review Heathrow's ready-to-rent pool before shifting any vehicles from another branch.",
            "I will compare confirmed reservations with cars that are actually available. On-hire cars and cars still in turnaround are not spare capacity.",
            "For the comparison, use VehicleState.Status and Timestamp. The live map is fresher than the two-minute Copilot snapshot, so include the time of the decision.",
            "The proposed decision is to protect airport coverage first, then consider a small transfer only when the receiving branch has a confirmed requirement.",
            "Any transfer request will include the vehicle IDs, receiving branch, handover owner, and expected readiness. I won't allocate a car with an unresolved alert.",
            f"Cross-check against the closed-day network split before assuming a quiet depot: {branch_summary}. Mileage is context, not a reservation forecast.",
            "Good. Bring a documented transfer recommendation to the capacity meeting rather than moving cars solely because a point on the map looks idle.",
            "I will add the capacity decision criteria to the shared allocation brief and bring the unresolved questions to the meeting.",
        ]),
        ("EV charging readiness", [
            f"We have {len(electric)} electric vehicles in the current fleet snapshot. Charging readiness needs its own review before the next airport peak.",
            f"Battery exceptions right now: {low_energy}. I'll check charging access and the next collection time for each affected car.",
            "The 20% threshold is a review trigger, not a statement that a car is fit for every trip above that level. Use the customer's planned journey and charging opportunity.",
            "Prioritise customer commitments, then depot readiness. Repositioning a low-charge car without a charging plan just moves the problem.",
            "I will record the owner, charger location, target readiness time, and the battery reading used for the decision.",
            "Telemetry can arrive late. If a battery reading is stale, confirm the current state before changing a reservation or promising readiness.",
            "Let's discuss charging bottlenecks in the EV readiness meeting and separate equipment issues from scheduling issues.",
            "I will attach the charging-readiness procedure to this thread so branch teams use the same release criteria.",
        ]),
        ("Vehicle health and maintenance triage", [
            f"Today's health review starts with the actual Fabric exceptions: {attention}. These should be visible to operations and maintenance together.",
            "I will keep the affected cars out of any new allocation until the appropriate inspection or release decision is recorded.",
            "A tyre-pressure alert needs an approved workshop check against the manufacturer's specification. The telemetry alert itself is not a diagnosis.",
            f"Also review the zero-distance cars from the closed day: {parked}. We need to distinguish planned maintenance from an allocation issue.",
            "I'll add the current location and next reservation to each handover. Customer communication should reflect the agreed operational status.",
            f"The top mileage list is {leaders}. Compare cumulative odometers with ServiceDueKm before assigning additional service work.",
            "Please bring proposed actions and evidence to the triage meeting. Do not mark a vehicle as repaired just because an alert disappears.",
            "Agreed. We will keep a clear chain from the original exception to inspection evidence, release approval, and branch acknowledgement.",
        ]),
        ("Mileage reconciliation and reporting calendar", [
            f"I want the reporting standard locked down before this goes into leadership material. The closed-day total for {day.isoformat()} is {total:,.1f} km.",
            "The fleet operates in UK locations, but the morning report uses Europe/Madrid as agreed. I'll put that calendar explicitly on branch summaries.",
            "Correct. Yesterday means the previous local calendar date, not a rolling 24-hour window. The UTC boundaries change with daylight saving.",
            "How do we prevent duplicate telemetry from overstating kilometers when the injector retries or catches up after the capacity resumes?",
            "The presentation should explain the calculation plainly, with the reporting date and source, without making users interpret raw event rows.",
            "FleetEvents deduplicates EventId. FleetDistance apportions intervals at the requested boundaries. DailyMileage has one row per vehicle and reporting date.",
            "Use the same definitions in the shared metric guide, the Copilot instructions, and the daily briefing. Do not derive distance by summing snapshot speeds.",
            "I will link the metric guide in the management pack and flag any mismatch before a number is sent to a customer or leadership.",
        ]),
        ("Corporate rental service review", [
            "Let's prepare a joined-up corporate rental service review: account commitments, vehicle readiness, and the operational decisions behind any change.",
            "I will review the Northstar Consulting, Meridian Travel, Atlas Engineering, and Harbour Events accounts against their assigned rental vehicles.",
            "Use Rentals.RentalId and VehicleId to join the operational facts. Avoid joining every telemetry sample directly to a rental summary because it can duplicate totals.",
            "The customer discussion should focus on reliable readiness and clear alternatives, rather than quoting fleet-wide mileage as a customer-specific service measure.",
            "For every potential disruption I will record the agreed alternative, the owner of the customer update, and the next confirmation time.",
            f"For context, the network drove {total:,.1f} km on the closed day. That is an operating measure; it is not invoiced revenue or an SLA outcome.",
            "Bring account-specific questions to the service review meeting. We need the contract and reservation context before drawing conclusions.",
            "I'll attach the customer handover standard and keep the open commitments together so Copilot can distinguish a proposal from an approved action.",
        ]),
        ("Commercial performance and utilisation", [
            "For the commercial discussion, let's separate usage, fleet availability, and revenue. They answer different questions.",
            f"The closed-day usage picture is {active} active cars out of {len(mileage)}, with {total:,.1f} km. Today's on-hire count is a different, current-state measure.",
            "DailyRateGBP is a listed daily rate in the vehicle register. Multiplying it by a live status count is not recognized revenue and should not be labelled as such.",
            "Please compare branch utilisation with readiness constraints before recommending discounts or moving capacity.",
            "I will bring the reservation and turnaround questions to the commercial review. A parked car can be reserved, charging, or held for inspection.",
            f"The mileage context is {branch_summary}. Use it alongside, not in place of, the commercial evidence.",
            "Let's document which measures are governed and which questions need another data source. The executive brief should make those boundaries clear.",
            "Agreed. I will make sure the shared briefing asks for the missing evidence rather than filling gaps with assumptions.",
        ]),
        ("Executive decisions and next-week priorities", [
            f"The leadership story starts with {total:,.1f} km on {day.isoformat()}, across {active} active cars in six UK locations. What decisions need attention next?",
            "My priorities are airport readiness, charging coordination, and consistent customer handovers. Each needs an owner and a measurable next checkpoint.",
            f"The current health exceptions are {attention}. These are operational follow-ups, not evidence of completed repairs.",
            "Let's keep proposed actions separate from agreed decisions in the meeting pack. The point of the IQ demo is to connect business context to the underlying facts.",
            "I will use these discussions and the shared documents to prepare the leadership agenda. The operator is included so the same context is available in Copilot.",
            "For any numerical question, cite the Fabric reporting period and metric definition. For a decision question, cite the relevant conversation or shared document.",
            "The next review should answer what changed, why it changed, who owns the response, and which evidence would make us change course.",
            "I will close the loop with a concise decision log after the review, with links back to the fleet dashboard and the accountable branch actions.",
        ]),
    ]
    conversations = [
        {
            "id": f"chat-{index + 1}", "topic": f"{title} | {day.isoformat()}",
            "members": members, "creator": authors[0],
            "messages": [{"author": authors[number % 3], "text": text} for number, text in enumerate(messages)],
        }
        for index, (title, messages) in enumerate(threads)
    ]
    document_topics = [
        ("Fleet operating brief", f"{total:,.1f} km; {active}/{len(mileage)} active vehicles. {branch_summary}.",
         "Use this brief to align airport readiness, exception ownership and customer commitments."),
        ("Airport capacity and transfer standard", "Protect confirmed customer commitments before transferring cars between branches.",
         "A transfer needs source and destination owners, vehicle IDs, readiness checks and a recorded handover."),
        ("EV charging readiness procedure", f"Current electric fleet: {len(electric)} cars. Current exceptions: {low_energy}.",
         "Review battery freshness, expected journey, charger access and the next collection time before approving readiness."),
        ("Vehicle health and release standard", attention,
         "An approved inspection and release decision are required; disappearance of a telemetry alert is not a repair record."),
        ("Governed mileage and reporting guide", source + f" Verified total: {total:,.1f} km.",
         "Sum deduplicated interval distance, split midnight-crossing intervals, and preserve the Europe/Madrid reporting calendar."),
        ("Corporate service and executive decision pack", f"The three busiest cars on the closed day were {leaders}.",
         "Separate observed facts, proposed actions, approved decisions and outstanding evidence. Do not represent list rates as recognized revenue."),
    ]
    documents = [
        {
            "id": f"document-{index + 1}", "title": title, "author": authors[0], "readers": members,
            "sections": [
                {"heading": "Purpose", "paragraphs": [purpose]},
                {"heading": "Verified operating context", "paragraphs": [context, source]},
                {"heading": "Decision and ownership standard", "paragraphs": [
                    "Aadi coordinates the fleet operating review. Aisha coordinates branch readiness and customer handovers. Alan provides metric reconciliation and maintenance planning evidence.",
                    "Record the vehicle or branch, the observation time, the accountable owner, the proposed action, the approval status and the next checkpoint.",
                    "Do not claim an action is completed until its owner records the supporting evidence.",
                ]},
                {"heading": "Data and interpretation", "paragraphs": [
                    "Current vehicle state comes from Fabric Eventhouse. Copilot reads the governed Lakehouse tables refreshed from the same events.",
                    f"Closed-day total: {total:,.1f} km. Branch breakdown: {branch_summary}.",
                    "A vehicle snapshot, a calendar-day mileage fact and a customer service outcome are different measures. Preserve those distinctions.",
                ]},
                {"heading": "Review questions", "paragraphs": [
                    "Which commitments are at risk, and what evidence supports that assessment?",
                    "What has changed since the last review, who owns the response, and when will it be checked?",
                    "Which recommendation depends on data not yet available in the fleet model?",
                ]},
                {"heading": "Source", "paragraphs": [
                    "https://caldovadrive08667473.azurewebsites.net",
                    f"Fabric workspace: https://app.fabric.microsoft.com/groups/{data.config['workspace_id']}/list?experience=fabric",
                ]},
            ],
        } for index, (title, context, purpose) in enumerate(document_topics)
    ]
    meetings = []
    meeting_day = datetime.now(ZoneInfo(options["meeting_timezone"])).date()
    subjects = ["Fleet readiness and airport capacity", "EV charging and customer commitments", "Vehicle health and release decisions", "Corporate rental service review", "Executive fleet priorities and metric reconciliation"]
    for index, subject in enumerate(subjects):
        meeting_day += timedelta(days=1)
        while meeting_day.weekday() >= 5:
            meeting_day += timedelta(days=1)
        begins = datetime.combine(meeting_day, datetime.min.time().replace(hour=9, minute=30), ZoneInfo(options["meeting_timezone"]))
        meetings.append({
            "id": f"meeting-{index + 1}", "subject": subject,
            "organizer": authors[index % 3], "attendees": members,
            "start": begins.isoformat(), "end": (begins + timedelta(minutes=30)).isoformat(),
            "agenda": [
                f"Review the {day.isoformat()} closed-day fleet total of {total:,.1f} km and the relevant branch split.",
                subject + ": distinguish observations, recommendations and decisions.",
                "Confirm owners, evidence needed and the next checkpoint for every open action.",
                "Review the shared fleet operations documents and link any decision to its underlying fleet data.",
            ],
        })
    return {
        "runId": scenario_id, "tenantId": CONFIG["tenant_id"], "createdAt": utc_text(datetime.now(UTC)),
        "source": {"reportDate": day.isoformat(), "totalKm": round(total, 3), "vehicles": len(mileage), "activeVehicles": active, "reportTimezone": CONFIG["report_timezone"], "vehicleSnapshotAt": snapshot_at},
        "conversations": conversations, "meetings": meetings, "documents": documents,
    }
