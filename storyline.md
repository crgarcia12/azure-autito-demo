# Caldova Drive: from a bump to a booked repair

## The story

**A rental customer has a minor bump while parking. Caldova detects the possible incident, helps the customer report it, obtains repair options, and prepares a recommendation. The operations manager reviews the evidence and approves the booking.**

The customer tells the story once. The insurer, rental operations team and repair centres work from the same case.

This walkthrough uses the deployed **Microsoft Foundry** resource, project and evidence agent. The standalone Azure OpenAI account has been removed. Deployment and verification details are recorded in [implementation.md](implementation.md).

## Open these before presenting

Use **Edge Work 2**, signed in as `admin@caldova08667473.onmicrosoft.com` for the administration and employee experiences. The customer reporting page uses its own secure link and does not require a Microsoft 365 account.

| Window | Open |
| --- | --- |
| Operations dashboard | [Caldova Drive](https://caldovadrive08667473.azurewebsites.net) |
| Fabric | [Caldova Drive - Fleet Intelligence workspace](https://app.fabric.microsoft.com/groups/19b68e4b-dd12-4e74-84d9-18fd9f1e2b49/list?experience=fabric) |
| Foundry | [Microsoft Foundry](https://ai.azure.com) → resource **caldovadrive08667473-foundry** → project **caldova-insurance** → agent **caldova-incident-evidence** |
| Claims coordinator | [Caldova Repair Coordinator in Copilot Studio](https://copilotstudio.microsoft.com/environments/Default-b6883271-971b-4198-92a5-8ad615765572/bots/02d7a04b-93fc-4cb3-b07c-49156794520c/overview) |
| Repair agent | [Metro Rapid Repair in Copilot Studio](https://copilotstudio.microsoft.com/environments/Default-b6883271-971b-4198-92a5-8ad615765572/bots/988bbfcb-a31e-4a36-8d4b-ea88da60f225/overview) |
| Email | [Outlook](https://outlook.office.com/mail/) → profile → **Open another mailbox** → `claims@caldova08667473.onmicrosoft.com` |
| Microsoft 365 Copilot | [Caldova Microsoft 365 Copilot](https://m365.cloud.microsoft/chat/?auth=2&tenantId=b6883271-971b-4198-92a5-8ad615765572) |

For a short presentation, use the prepared cases at the matching stage. For a fresh run, select a vehicle without an active incident and follow the sequence from the beginning.

---

## 1. A customer is using a rental car

**Story:** Alex is driving a rental car in London. Caldova can see the vehicle's operational state and connect it to the rental and branch.

**Open and do:** Start on the dashboard's **Overview**. Show the fleet map, select a London car, and show its location, speed, energy level and status. Optional: open the Fabric ontology **Caldova_Fleet_Digital_Twin** in **Full ontology** view for 20 seconds to show Vehicle → Branch and Rental → Vehicle. The full ontology walkthrough is in [step 14](#14-show-the-ontology-behind-the-case).

**Feature:** Azure Maps; Fabric Eventhouse telemetry; Fabric IQ ontology and business context.

**Say:** “We are not looking at isolated GPS points. This car has a rental, a home branch and an operational state we understand.”

## 2. The customer has a bump while parking

**Story:** Alex catches the lower bumper on a bollard while reversing into a parking space. The vehicle records an impact signal and a sudden change in speed.

**Open and do:** In **Incident centre**, choose a vehicle without an active case and select **Send impact telemetry**. This injects an actual event into Fabric. To inspect the event, open the `CaldovaFleet` KQL database and run:

```kusto
VehicleImpacts
| top 5 by Timestamp desc
```

**Feature:** Telemetry ingestion into Fabric Real-Time Intelligence; timestamped vehicle events.

**Say:** “The vehicle has reported a possible impact. We have not yet decided that an accident occurred or that a claim is covered.”

## 3. Fabric detects the signal and starts the incident workflow

**Story:** Caldova's detection rule correlates the acceleration signal, velocity change and the vehicle coming to rest. It opens an incident for operations and prepares the customer reporting link.

**Open and do:** In Fabric, open **Caldova_Incident_Activator**. Show the running rule and its action. Then open **Caldova_Impact_Response** and its run history. Return to the dashboard as the new case appears.

The current rule checks:

- Peak acceleration of at least **2.5 g**.
- Velocity change of at least **4 km/h**.
- Speed after the event of at most **1 km/h**.

**Feature:** Fabric Activator conditions; a real Data Factory pipeline action; an authenticated application callback; incident correlation and deduplication.

**Say:** “Fabric turns the sensor event into an operational action. It opens the right case instead of sending someone an unstructured alert to investigate from scratch.”

**Presentation timing:** This configuration polls KQL every minute. A warm native trigger was verified at about 92 seconds; a cold pipeline run took longer than three minutes. Use that time to explain the detection rule or switch to the prepared fresh case for a shorter presentation. Delayed callbacks are reconciled rather than losing the incident.

## 4. The customer receives a clear next step

**Story:** The customer is contacted proactively, with emergency guidance and a simple way to report the incident.

**Open and do:** Open the incident and select **Open customer journey**. Show the phone-message preview:

> Caldova: We detected a possible impact involving your rental car. In an emergency call 999. When it is safe, use this link to report the incident.

Follow **Report your incident securely**.

**Feature:** Event-driven customer engagement; a secure, expiring incident link.

**Say:** “The first message is about safety and help, not a complicated claims form. The customer can report what happened when it is safe to do so.”

**Presenter detail:** The phone message is a preview. The link and the reporting site are real; no real SMS is sent.

## 5. The customer submits photos and an explanation

**Story:** Alex confirms everyone is safe, adds a photo and describes what happened. The vehicle and case are already identified.

**Open and do:** On the customer reporting page:

1. Confirm it is safe to complete the report.
2. Leave the injury checkbox clear for the main journey.
3. Upload a bumper photo. A clear, ready-to-use damage image is `static\demo-assets\bumper-dent.jpg`.
4. Enter an explanation such as:

   > “The rear bumper contacted a low bollard while reversing into a parking space. There is a dent and light paint scuffing on the plastic bumper. Nobody was injured and no other vehicle was involved.”

5. Confirm permission to share the redacted repair brief, then submit.

**Feature:** Mobile evidence capture; prefilled case context; consent; protected uploads and evidence hashes.

**Say:** “Alex tells the story once. We retain the original evidence securely and use a separate, privacy-processed version for the repair network.”

## 6. Foundry prepares the repair brief

**Story:** The evidence agent reviews the photos and customer account, identifies visible damage, checks image quality, and prepares a repair report with identifying details removed.

**Open and do:** In Foundry, open **caldova-insurance → Agents → caldova-incident-evidence**. Show its instructions and model configuration. In the dashboard, show **Incident evidence**, the privacy-processed photo and **Repair brief PDF**.

**Feature:** Microsoft Foundry Agent Service; multimodal reasoning; privacy redaction and verification; structured report output.

**Say:** “The agent assembles a useful case, but it does not decide liability, insurance coverage or whether the vehicle is safe to drive. It records what is visible and what still needs inspection.”

**Alternative branch:** Open case **CDI-BCB6A3CE7C**, whose wider photo requires inspection. Show that it has no quotation emails and cannot be approved automatically. The operator can request clearer evidence. This demonstrates that uncertain evidence stops the automation rather than becoming a confident-looking decision.

## 7. The claims coordinator asks three repair centres for quotes

**Story:** The claims coordinator sends the same privacy-cleared repair brief to three approved centres. It asks for price, availability and return-to-service date—not just the cheapest repair.

**Open and do:** Open **Caldova Repair Coordinator** in Copilot Studio. Show its instructions and approval boundary. Then open the case's **The actual correspondence**, or the **Sent Items** folder in the claims mailbox. Expand the three `[RFQ]` messages and show the attached repair brief.

**Feature:** A real Copilot Studio agent; grounded RFQ generation; real Microsoft 365 email delivery.

**Say:** “The coordinator does the repetitive preparation and correspondence. Each centre receives the same repair scope, so the responses can be compared fairly.”

**Implementation detail:** A Graph inbox adapter connects the real mailboxes to the published Copilot Studio agents. Do not describe this adapter as a native Outlook connector trigger.

## 8. The three centres respond with different trade-offs

**Story:** One centre is inexpensive but busy. Another can return the car much sooner at a higher repair price. A third offers a middle option.

**Open and do:** Show the three `[QUOTE]` replies in the case. Open **Metro Rapid Repair** in Copilot Studio to show that it is an actual agent using its own rate and availability rules.

| Centre | Agent | Shared mailbox |
| --- | --- | --- |
| Alder Bodyworks | [Open in Copilot Studio](https://copilotstudio.microsoft.com/environments/Default-b6883271-971b-4198-92a5-8ad615765572/bots/808cb5b3-a41d-45b3-92bd-35819f5f6789/overview) | `alder.repairs@caldova08667473.onmicrosoft.com` |
| Metro Rapid Repair | [Open in Copilot Studio](https://copilotstudio.microsoft.com/environments/Default-b6883271-971b-4198-92a5-8ad615765572/bots/988bbfcb-a31e-4a36-8d4b-ea88da60f225/overview) | `metro.repairs@caldova08667473.onmicrosoft.com` |
| Riverside Auto Care | [Open in Copilot Studio](https://copilotstudio.microsoft.com/environments/Default-b6883271-971b-4198-92a5-8ad615765572/bots/e9317e40-0ecc-4ccd-a167-a692f75373ee/overview) | `riverside.repairs@caldova08667473.onmicrosoft.com` |

**Feature:** Real agent-to-workflow interaction, independently configured supplier responses, actual email threads and structured quote extraction.

**Say:** “The centres have different commercial offers. The system preserves their actual replies, including dates, warranty and exclusions, rather than reducing everything to an invented score.”

**Presenter detail:** All three centres are represented inside Caldova. No outside garage is contacted.

## 9. The agent recommends the best business outcome

**Story:** The coordinator evaluates repair cost plus the cost of keeping a rental car off the road.

**Open and do:** Open **Repair options** on the incident. For the prepared Volvo case **CDI-168C31C660**, the comparison is:

| Centre | Repair including VAT | Calendar downtime | Total at GBP 100/day |
| --- | ---: | ---: | ---: |
| Alder Bodyworks | GBP 450 | 9 days | GBP 1,350 |
| **Metro Rapid Repair** | **GBP 600** | **2 days** | **GBP 800** |
| Riverside Auto Care | GBP 550 | 7 days | GBP 1,250 |

Show the native agent's rationale. Move the **downtime cost** slider to zero, then back to GBP 100.

**Feature:** Policy-grounded agent recommendations; validated calculations; an interactive business trade-off.

**Say:** “Metro costs GBP 150 more to repair the car, but returns it seven days earlier than the cheapest repair-price option. The overall expected saving is GBP 550.”

**Important:** These are the actual figures for the prepared Volvo case. New cases calculate dates and downtime from their own incident date and the centres' working-day calendars. The slider is exploration only; it does not change the recorded approval policy.

## 10. The operations manager reviews one complete case

**Story:** The manager opens the fleet dashboard. Several cars need attention, but this one already has its evidence, correspondence and recommendation organised.

**Open and do:** From **Overview**, select the affected vehicle and open its incident, or use **Incident centre** directly. Review:

- Customer account and original photos.
- Privacy-processed report and PDF.
- The three RFQs and the actual responses.
- Side-by-side quotes and total expected cost.
- The agent's recommendation and the decision timeline.

**Feature:** A unified operations experience; evidence provenance; human-in-the-loop control.

**Say:** “The manager is not reconstructing the case from five different screens. Everything needed to judge the recommendation is here.”

## 11. The manager accepts the recommendation

**Story:** After reviewing the case, the manager approves Metro. This is the point at which Caldova authorises the booking request.

**Open and do:** Click **Approve & book**. Show the status change and the new `[BOOK]` email to Metro.

**Feature:** Explicit human approval; version and quote-validity checks; controlled execution.

**Say:** “The agent recommends. The manager authorises. A recommendation on a screen is not permission to commit the business.”

## 12. The garage confirms the booking

**Story:** Metro's agent receives the approved request and confirms the agreed terms. Only then does the case become booked.

**Open and do:** Wait for the `[BOOKED]` reply. Show **Booking confirmed**, the return date and the distinct approval and confirmation entries in the timeline.

**Feature:** Closed-loop agent orchestration; real email confirmation; durable workflow state.

**Say:** “Approval and confirmation are different facts. We only mark the repair as booked when the garage actually confirms it.”

## 13. The customer sees the next step

**Story:** Alex can see that the repair is booked and when the car is expected back, without repeating the incident report.

**Open and do:** Reload the customer's secure reporting page. Show the confirmed repair centre and expected return date. In the operator's mailbox, show the actual booking-confirmation notification.

**Feature:** Consistent customer and operations status; a persistent case across channels.

**Say:** “The customer, the repair centre and the operations team now share one clear next step.”

## 14. Show the ontology behind the case

**Story:** The manager has approved a repair for one car. The business also needs to know how that car relates to the rental, the branch, its mileage and the quotes. The ontology is the shared business model connecting those facts.

**Before presenting (one-off, 2 minutes):**

1. Open the [Fabric workspace](https://app.fabric.microsoft.com/groups/19b68e4b-dd12-4e74-84d9-18fd9f1e2b49/list?experience=fabric). In the item list, select **Caldova_Fleet_Digital_Twin** (type **Ontology**).
2. Check whether the top ribbon shows **Explore graph**. If it does not, select **Manage graph**. Keep **Use the entire Ontology** selected, then select **Continue** → **Materialize**. Materialization takes a few minutes.
3. After any data change, open the item **Caldova_Fleet_Digital_Twin_graph_…** (type **Graph model**). Select **Schedule** → **Refresh now** so the graph shows the latest cases.

**Open and do (live, about 3 minutes):**

1. **The business model.** Open **Caldova_Fleet_Digital_Twin**. The canvas opens in **Full ontology** view and shows seven entity types:
   - **Vehicle**, **Branch** and **Rental**
   - **VehicleState** (live snapshot), **DailyMileage**
   - **Incident** and **RepairQuotation**

   Then switch the canvas to **Relationship** view. In the **Explorer** on the left, select **Vehicle** to centre it. Point at its links: Vehicle → Branch, Rental → Vehicle, Incident → Vehicle, RepairQuotation → Incident, and VehicleState/DailyMileage → Vehicle.
2. **What a "Vehicle" means.** With **Vehicle** selected, choose **View Entity Type details** in the ribbon. Show three things:
   - The properties: Registration, Make, Model, Powertrain, DailyRateGBP and ServiceDueKm.
   - The entity type key, **VehicleId**.
   - The binding to the Lakehouse table **FleetIntelligence → Vehicles**.
3. **Real instances.** Open the **Instances** tab and find **CD-002**. This is the car in case CDI-168C31C660. These are live rows from OneLake, not a separate copy.
4. **Business rules.** Open **Incident** the same way and show the rule **RepairApproval** attached to it. ApprovalRecorded is not the same as BookingConfirmed. Then open **DailyMileage** and its rule **MileageAccounting**: kilometres come from DailyMileage.DistanceKm, never from odometer readings.
5. **The connected graph.** Go back to the ontology canvas and select **Explore graph** in the ribbon.
   - Select the puzzle piece icon on the right to expand **Components**.
   - Under **Nodes**, select Incident, Vehicle, Branch, Rental and RepairQuotation. Under **Edges**, select all the edges.
6. **One case, fully connected.** Select **Path query** in the ribbon and confirm **Switch**. Enter:
   - **Start node:** Incident, filter **CaseId = CDI-168C31C660**
   - **End node:** Branch
   - **Max hops:** 3

   Select **Run**. The canvas draws the incident → car CD-002 (Volvo EX30) → London Heathrow, plus rental R-10402 for Meridian Travel on that car. Add **RepairQuotation** to show the three repair offers (Alder, Metro, Riverside) linked to the same incident.

**Feature:** Fabric IQ ontology: entity types, entity keys, relationships, OneLake data bindings, business rules, and the materialized ontology graph (Graph in Microsoft Fabric).

**Say:** “The dashboard, the Fabric data agent and Copilot all use the same definitions of a vehicle, a rental, an incident and a quote. When we ask Copilot a question next, it is grounded in this model and its rules, not guessing which table means what.”

**If something does not load:** The Instances tab reads the Lakehouse live, so it works even if the graph is still refreshing. If **Explore graph** is missing, stay in **Relationship** view and the **Instances** tab. That still tells the full story.

## 15. Ask Fabric IQ about the live operation

**Story:** The manager wants to know what still needs attention across the fleet, not just in this one case.

**Open and do:** In Microsoft 365 Copilot, choose **Agents → Caldova Fleet IQ**. Ask:

> “Which repair cases currently await operator approval? Include the case IDs and recommended repair centre.”

Then:

> “Which cases have confirmed bookings, and what are their expected return dates?”

**Feature:** Fabric IQ business context and governed facts; the real Fabric data agent surfaced in Microsoft 365 Copilot.

**Say:** “Fabric answers the operational question: what is true in the fleet and case data right now?”

## 16. Ask Work IQ about the communication and reasoning

**Story:** The manager needs the original work context behind a decision: what was communicated, and why the recommendation was made.

**Open and do:** Switch to the main Microsoft 365 Copilot chat with **Work IQ enabled**, rather than staying inside the Fabric agent. Ask:

> “Find the email from Caldova Claims Operations about case CDI-168C31C660. Summarize the repair recommendation, its cost trade-off, and what I need to approve. Cite the email.”

Open the email citation.

**Feature:** Work IQ retrieval and reasoning over the operator's actual Microsoft 365 work context.

**Say:** “Work IQ connects the decision to the work around it. Fabric supplies the operational facts; Work IQ finds the correspondence and its context.”

Use Fabric for current case state and email for the recorded communication. An older recommendation email is not proof that a case is still awaiting approval.

---

## The closing line

> “A customer had a bump. Before anyone had to piece the story together manually, Caldova had the vehicle context, the customer's evidence, three repair offers and a justified recommendation. A person approved the decision, the garage confirmed it, and every step remained traceable.”

## Prepared cases for the presentation

| Case | Open it for |
| --- | --- |
| [CDI-816DB5A515](https://caldovadrive08667473.azurewebsites.net/#incidents?case=CDI-816DB5A515) | Fresh customer-reporting journey |
| [CDI-168C31C660](https://caldovadrive08667473.azurewebsites.net/#incidents?case=CDI-168C31C660) | Quote comparison and the live approval moment |
| [CDI-05E0A06690](https://caldovadrive08667473.azurewebsites.net/#incidents?case=CDI-05E0A06690) | A completed booking with actual correspondence |
| [CDI-BCB6A3CE7C](https://caldovadrive08667473.azurewebsites.net/#incidents?case=CDI-BCB6A3CE7C) | Inspection-required guardrail |
| [CDI-447819C9E7](https://caldovadrive08667473.azurewebsites.net/#incidents?case=CDI-447819C9E7) | Completed Foundry-backed report, three real quotes and confirmed booking |

## Product names to use accurately

| What is happening | Name to use |
| --- | --- |
| Detect a telemetry condition | **Fabric Real-Time Intelligence / Activator** |
| Relate vehicle, rental, incident and quotation facts | **Fabric IQ ontology and data bindings** |
| Analyse photos and prepare the privacy-processed report | **Microsoft Foundry Agent Service** |
| Generate RFQs, supplier replies and recommendations | **Copilot Studio agents** |
| Move and monitor the actual emails | **Microsoft Graph inbox adapter** |
| Ask questions over governed operational tables | **Fabric data agent / Caldova Fleet IQ** |
| Find and cite the operator's email context | **Work IQ in Microsoft 365 Copilot** |

The application's decision timeline is custom application functionality. Do not call it a native Fabric feature named “Evidence Map” or “Governed Binding”. Foundry Agent Service is not the same feature as Foundry IQ knowledge-base retrieval.
