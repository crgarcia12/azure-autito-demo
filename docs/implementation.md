# Caldova Drive: implementation and demo runbook

## Scope and operating boundaries

The approved demo is a UK rental-fleet insurance journey: telemetry detects a possible impact, the customer reports the incident and uploads photos, Foundry prepares a redacted repair brief, Studio agents generate quotations/recommendations with app-supplied policy, and the app sends real emails after validation and operator approval.

Everything is scoped to **Caldova**:

| Setting | Value |
| --- | --- |
| Local repository | `C:\gitrepos\github\crgarcia12\azure-autito-demo` |
| Tenant | `caldova08667473.onmicrosoft.com` |
| Tenant ID | `b6883271-971b-4198-92a5-8ad615765572` |
| Subscription | `d41fd8d2-efeb-4629-82ea-c8f25cd2cc64` |
| Resource group | `rg-caldova-drive-demo` |
| Application | <https://caldovadrive08667473.azurewebsites.net> |
| Fabric workspace | `19b68e4b-dd12-4e74-84d9-18fd9f1e2b49` |
| Shared F2 capacity | `apollofabric08667473` in Sweden Central |
| Copilot Studio environment | `Default-b6883271-971b-4198-92a5-8ad615765572` |
| Dataverse | `https://org1a562eb0.crm.dynamics.com` |
| Foundry resource | `caldovadrive08667473-foundry` (`AIServices`, project management enabled) |
| Foundry project | `caldova-insurance` |
| Foundry evidence agent | `caldova-incident-evidence`, version `2` |
| Authorized operator | `admin@caldova08667473.onmicrosoft.com` |
| Browser profile | Edge **Work 2 Profile**, identity verified as Caldova |

The user approved dedicated claims/garage shared mailboxes and required AI/agent consumption. **SMS is now a phone-message preview with a real reporting link**, explicitly requested instead of a paid delivery. No private endpoint or VNet is approved. The existing Apollo workspace must not be modified. No credential resets, MFA bypasses, corporate-tenant changes, or messages to real external garages are permitted.

## Current architecture: restored app-managed policy and email

The user requested rollback of the experimental agent-owned policy/email migration. `fleet\repair_workflow.py` again uses the four secured **Copilot Studio** agents, supplies `repair_policy()` and `policy_reference()` in their context, validates their results and invokes `RepairMail.send` directly. Initial customer notifications do not depend on a model or Work IQ connection.

The native Foundry repair functions/agents and the `work-iq` OAuth project connection remain in place as requested, but are not called by the active workflow. Their code is retained in `fleet\repair_agents.py` and `fleet\workiq.py`; the evidence and customer agents still use their existing working Foundry endpoints. No evidence-agent permission to send email was added.

The unattended evidence endpoint must use a **tool-free processing version**. User-authenticated Work IQ Mail and web tools belong in interactive agent versions, not the managed-identity photo-processing path. An HTTP 400 at that stage prevented any garage requests; restoring published version `6` resumed both submitted cases through three actual quotations. The added tools remain in the other Foundry versions. Local face/text masking remains enabled.

The attempted native path produced actual policy lookups, supplier messages and an isolated booking, but did not become a reliable hosted replacement. Do not present those retained functions as the current production path. Work IQ remains independently demonstrable through the verified Microsoft 365 Copilot conversation.

### Repeat the demo

For the two-stage presentation, run `.\.venv\Scripts\python.exe -m tools.prepare_mini_demo --new-run`. It cleans other pending cases and leaves exactly two active MINI incidents: one with both `crash2.png` and `crash1.png` processed and three actual offers ready for operator choice; one with zero photos, an unsubmitted form and a fresh customer email. Omit `--new-run` to resume without replacing the pair. Both remain unapproved.

Run `.\.venv\Scripts\python.exe -m tools.reset_mini` from the repository. It deletes only MINI incident records and their local evidence/tokens, archives other incidents while retaining their approvals/booking evidence, ingests a new MINI impact into Fabric and sends one real initial email through the original application-managed Exchange transport. It leaves the new case **awaiting_report**, with zero photos and no submitted narrative.

The reset manifest and event ID are durable. Interrupted runs resume without creating a second case. An impact cutoff prevents delayed old Fabric callbacks from recreating deleted cases. Unknown email outcomes block reset rather than discarding send receipts. Live telemetry/history and the 40-car register are retained; only the MINI is **Incident detected**, and the other 39 cars are **On hire**. Charging/low-battery scenarios and energy panels are removed from the active portal.

`GET /api/incidents` lists the current run. `?history=true` also returns archived records; their direct links remain readable, but they no longer hold cars or run procurement. Empty case/quote projections clear obsolete Lakehouse rows rather than retaining deleted MINI quotations.

**Restored run, 5 October:** build `4037779865184f7d`, case `CDI-CF6D654773`. The actual report-link email reached the configured admin inbox at `2026-10-05T02:13:28Z`; the case was left awaiting its customer report, with zero uploaded photos. Two consecutive reset runs verified replacement of the prior MINI case without reopening old impacts. Hosted browser checks confirmed 40 map markers, 39 On hire vehicles, one incident, the empty editable report and mobile layout.

**Deployment correction:** an existing compressed Oryx artifact was taking precedence over newer deployed files. Prebuilt startup now explicitly changes to `/home/site/wwwroot` before `python -m fleet.web`; `tools.deploy` waits for SCM after configuration and verifies the exact active build ID.

The sections below record earlier implementation milestones and case IDs. They are historical, not instructions to reuse an old MINI link after reset.

### Customer report and image privacy

The customer form no longer asks about safety or assistance; omitted fields remain `None`, while explicit legacy assistance requests still stop procurement. The submitted confirmation and future initial notification emails end at the case reference.

`fleet\privacy_detection.py` runs local YuNet face detection and PP-OCRv3 text-region detection. `fleet\evidence.py` maps their measured coordinates to the exact normalized raster, applies outward-rounded, padded masks, and sends that masked image to Foundry. The model no longer supplies mask coordinates. This corrects the reported face boxes being applied to the lower body and avoids relying on imprecise model-generated plate boxes.

The original PNG/JPEG/WebP and normalized JPEG are unchanged. `POST /api/incidents/{case}/reprocess-evidence` requires the current version and a review-stage case with no quotes/approval; it archives the previous report and derived artifacts before reprocessing. It never resubmits the customer's account.

Models are bundled with SHA-256 verification and upstream licences: [YuNet, MIT](https://github.com/opencv/opencv_zoo/tree/f12e12798e8314f7c074a6656816c048dcc95b7a/models/face_detection_yunet) and [PP-OCRv3, Apache-2.0](https://github.com/opencv/opencv_zoo/tree/25f423d0e04c31a17254620e58febd7386da523b/models/text_detection_ppocr). Neither detector identifies a person or transcribes text. `tools.provision_foundry --agent-only` updates the evidence instructions while preserving the existing tools, model and response settings.

## Historical verification: 4 October, before the tool-runtime migration

The hosted incident journey has been exercised against **actual Fabric, Azure model inference, Copilot Studio and Exchange Online**, including a real operator approval in the browser and a subsequent real garage confirmation.

Start at <https://caldovadrive08667473.azurewebsites.net/#incidents>. Sign in with the Caldova operator in **Work 2 Profile**.

| Ready-to-present case | Vehicle | State | What to demonstrate |
| --- | --- | --- | --- |
| `CDI-4170F5EC25` | CD-006, green MINI Cooper in Stornoway | Awaiting customer report | Editable contact prefills, empty explanation, source-linked weather observations and `media\crash1.png` upload. |
| `CDI-008FC82110` | CD-002, Volvo EX30 | Recommendation ready | OEM policy; fastest/cheapest aftermarket offer excluded; real quotation emails; compliant-only slider and **Approve & book**. Deliberately unapproved. |
| `CDI-EDB4612D4F` | CD-003, Volkswagen Golf | Booked | New genuine OEM approval, actual native garage confirmation, identical approved and confirmed quotation hashes. |
| `CDI-E277BBAC5C` | CD-001, Polestar 2 | Booked | Prior completed booking; original historical terms preserved. |

For `CDI-008FC82110`, **Alder is cheapest and fastest: GBP 450 repair, return 6 October, GBP 850 including downtime. It is excluded because it proposes aftermarket parts.** Metro offers new genuine OEM parts: GBP 600 repair, return 7 October, GBP 1,100 total. Riverside is also compliant: GBP 550 repair, return 9 October, GBP 1,250 total. Metro saves GBP 150 versus the lower-price compliant option, Riverside. At zero downtime cost the slider selects Riverside, never Alder. Exact dates change with the live business-day calendar.

Earlier case IDs and cost comparisons below are historical verification records. The fleet was reset before the OEM-policy extension; use the current cases above for the presentation.

**Real versus generated:** telemetry, rental identities and garage rate/capacity data are generated for the demonstration. The Fabric rule, pipeline, data agent, four Copilot Studio agents, image-model calls, emails, PDF generation, authentication, uploads and approval processing are real. The phone notification is an in-app preview, not a paid SMS.

**Validation:** 129 unit/API tests pass after the Stornoway form and weather update, including customer-email idempotency, atomic reporting links, photo/vehicle matching, operational labels and the existing repair-policy checks. The earlier 51-test suite also passed with cloud configuration and credentials deliberately unavailable. A separate hosted browser run uses a legitimate user-delegated Caldova token and checks the deployed application, all 40 map markers, quote comparison, emails, mobile layout and access boundaries. The core real-service and hosted end-to-end runs are recorded below.

**Microsoft 365:** in the same Caldova profile, open [Microsoft 365 Copilot](https://m365.cloud.microsoft/chat/?auth=2&tenantId=b6883271-971b-4198-92a5-8ad615765572), select **Agents > Caldova Fleet IQ** (created by Fabric Data Agent), and ask about case `CDI-008FC82110`. The published native Fabric agent was verified against the actual new `RepairQuotes` fields: Alder is noncompliant under RP-02, Metro and Riverside are eligible, and the policy is CD-REP-001 v1.0.

**Work IQ:** in main Copilot with Work IQ enabled, open the actual saved conversation **Caldova Repair Policy Comparison** (`da2d62d2-7c44-4d87-bad6-68aecbc648c0`). It retrieved `Caldova-Repair-Policy.docx` and all three quotation-evidence emails for `CDI-008FC82110`, cited the Word clauses and emails, excluded the fastest/cheapest aftermarket offer, and recommended Metro at GBP 1,100. This was verified in the real Caldova browser conversation, not inferred from file publication or a Graph email adapter.

**Current build verified:** `17c7390f5aba814c`, including the Stornoway location, editable contact prefills, an empty explanation, weather observations and external-only garage email copy. The hosted worker is running, the prepared case states remain persisted, all four Copilot Studio channels reject anonymous access, and evidence processing uses the real Foundry project agent. The earlier Foundry cutover build was `c7b7fa81d26b90fb`; the overnight build was `ba5a179f9713fc84`.

## Status at the start of autonomous implementation

| Area | Verified state |
| --- | --- |
| Azure application | Recovered with a prebuilt Linux dependency bundle; `/health/live` returns HTTP 200. Deployment `5340cdbc-694b-4c54-9ce3-cc50be28103a`. |
| Fleet | 40 cars across London, Manchester, Birmingham, Bristol, Leeds and Edinburgh; actual Azure Maps routes. |
| Fabric telemetry | Seven days of generated driving data were ingested into Eventhouse. Live ingestion runs in Azure with a persisted checkpoint. |
| IQ ontology | `Caldova_Fleet_Digital_Twin`, ID `184b9f5e-914f-49a0-ab7f-542eaf243b83`; five bound entity types and relationships. |
| Fabric data agent | `Caldova Drive`, ID `eacd7e3a-9686-4d88-9aee-3656bc90e4f0`; published native LakehouseTables source. User and service-principal answers were verified against KQL totals. |
| Teams application | Published through the verified Caldova browser session and installed only for the operator. |
| Morning briefing | A real Adaptive Card containing 15,289.6 km for 2026-09-29 was delivered to the operator's Teams chat; receipt persisted. Two-way chat displayed a Teams client restriction and needs further verification. |
| Copilot Studio | Caldova Dataverse author identity verified. No existing agents in the selected default environment. Native authoring tooling is being prepared. |
| Work IQ content generator | Single-tenant app and code created. The three approved authors have not completed delegated sign-in; no generated content was published. |
| Baseline tests | 23 Python tests passing. Earlier real-data browser checks verified 40 visible map markers, filters, navigation and mobile layout. |

## Demo story and intended presentation

1. Open the fleet operations dashboard and select a London vehicle.
2. Produce a low-speed impact through the telemetry injector. Show the actual event and the Fabric detection record.
3. Open **Customer journey** to show the phone-message preview with the real secure reporting link. No real SMS is sent.
4. Confirm everyone is safe. Explain that UK emergencies use 999, and the report should be completed only when safe. A suspected injury or unsafe vehicle goes to assistance/manual review, not automatic repair procurement.
5. Upload incident photos and a short explanation. Customer identity stays in the protected original; garage material uses a case reference.
6. Show the repair brief and its source evidence. Photo observations are not a definitive damage diagnosis.
7. Send actual RFQ emails to three dedicated Caldova garage mailboxes.
8. Show the inbox broker invoking the actual published Copilot Studio agents for those messages. Each returns its own validated quote using its rate/availability rules. The replies are sent through the corresponding real Caldova shared mailbox.
9. Apply the new genuine OEM parts policy first, retaining but excluding the fastest/cheapest aftermarket offer. Compare repair plus calendar downtime only for the compliant alternatives.
10. Open the vehicle marked **Repair recommendation ready**. Inspect photos, customer explanation, redacted report, original emails, replies, comparison and rationale.
11. Click **Approve & book**. Only then is the booking request sent. Garage confirmation changes the case to booked and updates the vehicle's expected availability.
12. Ask the fleet copilot about affected cars, outstanding approvals and yesterday's mileage, with the reporting period and source visible.

## Implementation task ledger

| Task | State | Notes |
| --- | --- | --- |
| Restore Azure hosting | Verified | Prebuilt Linux wheels avoid the failing Oryx Python SDK extraction. |
| Discover Studio capabilities | Verified | PAC 2.12.2 created real standard-harness agents in the Caldova default environment. |
| Provision scoped mailboxes | Verified | Claims plus three repair-centre inboxes. Application read/write/send scope excludes the operator's personal mailbox. |
| Incident state and APIs | Verified | Durable state, idempotent intake, sender/case correlation, atomic email claims, stale-version rejection and approval checks. |
| Fabric impact detection | Verified | Actual KQL data, running Activator, Web-connected Data Factory pipeline and authenticated callback. An autonomous run and a negative-control sample were verified. |
| Mobile evidence intake | Verified | Real hosted mobile browser upload, expiring capability link, consent, explanation and confirmation. |
| Redacted repair brief | Verified | Actual image analysis, privacy masking/check, protected originals and PDF report. Inspection-required branch blocks emails. |
| Garage Studio agents | Verified | Three real published agents, actual mailbox replies, separate rate/availability policies and secured native channels. |
| Claims coordination | Verified | Real native coordinator writes the RFQ and recommendation. Deterministic policy validation checks the AI output. |
| Operator review | Verified | Real browser approval triggered an actual booking request and received confirmation. |
| End-to-end verification | Verified | Both an isolated real-service run and the deployed browser/customer journey completed. |
| Demo enhancements | Implemented | Downtime trade-off/sensitivity, three seeded case states, inspection guardrail, source lineage, original evidence hashes, vehicle holds, operator decision emails and Fabric incident chat. |
| Native channel security | Verified | Four distinct protected credentials; anonymous acquisition denied; actual responding agent identity checked. |

## Technical details already implemented

- Python/aiohttp application; Azure App Service B1, single-instance and Always On.
- Azure Maps uses Entra tokens rather than client-side account keys.
- Vehicle telemetry contains deterministic event IDs and interval distances. KQL deduplicates retries.
- The reporting calendar is Europe/Madrid; UK operating locations use Europe/London. DST and midnight boundaries are explicit.
- OneLake Delta tables: `Vehicles`, `Branches`, `Rentals`, `VehicleState`, `DailyMileage`, `Incidents`, `RepairQuotes`.
- Copilot reads actual Lakehouse tables because unattended Fabric data-agent access to KQL is not supported in the current service.
- App state uses SQLite on App Service persistent disk at `/home/data/caldova/state.sqlite3`.
- The worker holds a renewable lease. Checkpoints and delivery receipts survive deployments.
- The app can read/resume the specific shared Fabric capacity at **06:45 Europe/Madrid**, allowing catch-up before the operator returns and before the 08:00 report, with a narrow custom Azure role. The original overnight shutdown automation is unchanged.
- Web APIs require the configured Caldova operator. Bot activities are JWT validated and tenant/user checked.
- Secrets live in App Service configuration, not source or deployment-state files.

## Recovery and deployment notes

The original Oryx build failed while extracting Python. A later source deployment left the app unavailable. The successful recovery bundles Linux wheels locally:

```powershell
uv --native-tls pip install --target .local\linux-packages --python-platform x86_64-manylinux_2_28 --python-version 3.12 --only-binary :all: -r requirements.txt
.\.venv\Scripts\python.exe -m tools.deploy app --prebuilt
```

Using pip cross-platform on Windows incorrectly evaluated an MCP Windows-only dependency. `uv` correctly resolved the target platform. Native TLS uses the machine's trusted certificate store; TLS verification is not disabled.

After the full compatible dependency bundle exists in Azure, use the smaller code update:

```powershell
.\.venv\Scripts\python.exe -m tools.deploy app --prebuilt --code-only
```

The deployer now waits for the **new deployment ID** to complete, restarts the app, and verifies the exact source/configuration build hash returned by `/health/live`. A previous build's HTTP 200 is not accepted as proof. Full-bundle rsync was unreliable; the code-only update also includes the two newly required image/PDF packages.

## Verification commands

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m compileall -q fleet tools content_studio
.\.venv\Scripts\python.exe tests\browser_smoke.py
.\.venv\Scripts\python.exe -m tests.hosted_browser
```

The local browser smoke test expects a live preview at `http://127.0.0.1:8097`. It reads actual Fabric data. Keep `FLEET_WORKER_ENABLED=false` and `FLEET_REPAIR_WORKER_ENABLED=false` locally while Azure owns the workers. The hosted test uses a real delegated token for the configured operator and only attaches it to the application's exact origin, never to map/font/CDN requests.

## Known limitations and blockers

- The real agents are published. Mail arrival is handled by a Graph inbox broker, which invokes them through Direct Line; **native Outlook connector event triggers are not configured**. This is an explicit integration adapter, not a mock responder.
- User-dependent sign-ins cannot be completed by guessing passwords or bypassing MFA. Such blockers will be recorded instead of replaced by fake integrations.
- Work IQ is an explicit integration, not a label for ordinary Graph or Outlook connector automation.
- The workflow sends the operator actual decision/booking emails so Microsoft 365 Copilot can use its authorized work context. Both Exchange delivery and actual Work IQ retrieval/citation were verified. Indexing remains asynchronous; no custom Work IQ MCP write connection is claimed.
- Photo processing now uses a real **Microsoft Foundry resource, project and versioned evidence agent**. The standalone `caldovadrive08667473-ai` OpenAI account was removed after the hosted Foundry workflow passed. The agent uses a GPT-4.1 model deployment inside Foundry; the protocol's OpenAI-compatible naming does not mean a standalone OpenAI resource exists. Foundry IQ knowledge-base retrieval is a separate feature and is not claimed here.
- Direct attachment of the generation-2 ontology to the data agent failed schema discovery in this tenant. The working published agent reads the same governed Lakehouse data bound by the ontology.
- There is no native Fabric feature named “Evidence Map” or “Governed Binding”. Any incident evidence presentation is application functionality.
- Sending a message and persisting its receipt are not one transaction; unknown outcomes must be reconciled rather than blindly retried.
- Exact originals are preserved for uploads made after the original-file enhancement. The earliest validation upload predates that enhancement and retains its normalized processing copy; it is not falsely represented as an exact binary original.
- SQLite is intentionally a **single-App-Service-instance** design. Do not scale this app horizontally without moving operational state to a transactional shared database. Reading its live database from the separate SCM container during a restart can produce a transient I/O error; use the authenticated application APIs for routine diagnostics.
- The older `Caldova Drive` Teams notification app delivered real cards, but its Teams client showed an unavailable chat composer. The distinct native **Caldova Fleet IQ** agent is the Fabric agent published to Microsoft 365 Copilot; do not confuse the two.

## Change and verification log

### Autonomous continuation, 30 September 2026

- Reconfirmed the exact Caldova subscription and tenant.
- Verified successful Azure recovery deployment and HTTP 200 health response.
- Ran the full existing Python suite: 23 passed.
- Began this persistent implementation/runbook document as explicitly requested.
- Installed PAC 2.12.2 using the official NuGet v2 endpoint after v3/feed connectivity failures; native `pac auth` verified the Caldova tenant, operator and environment.
- Created and published four actual standard-harness Copilot Studio agents:
  - Coordinator `02d7a04b-93fc-4cb3-b07c-49156794520c`.
  - Alder `808cb5b3-a41d-45b3-92bd-35819f5f6789`.
  - Metro `988bbfcb-a31e-4a36-8d4b-ea88da60f225`.
  - Riverside `e9317e40-0ecc-4ccd-a167-a692f75373ee`.
- Created the four dedicated shared inboxes: `claims`, `alder.repairs`, `metro.repairs`, `riverside.repairs`, all at the Caldova domain. Granted the operator mailbox access/Send As. Exchange application RBAC restricts the service identity to these four mailboxes; an explicit negative check excludes the operator mailbox. No tenant-wide Entra Mail application grant was added.
- Native Studio runtime is invoked through its supported Direct Line channel. The Graph mailbox broker supplies the verified email/case payload to the real native agent, validates its structured answer, and sends the answer through the correct mailbox. There were no existing Outlook connections. **This is a native-agent plus Graph-trigger adapter architecture, not a claim that Outlook connector triggers have been configured.**
- Deployed a regional `gpt-4.1` vision model, `incident-vision`, for actual photo interpretation and a second privacy-redaction verification pass.
- Implemented protected mobile intake, bounded JPEG/PNG/WebP uploads, EXIF removal, SHA-256 evidence hashes, privacy masks, protected original/processed images and a real PDF brief.
- Implemented mailbox-scoped RFQ/reply/booking delivery with immutable Exchange message IDs, durable draft/send receipts, correlation checks and loop protection.
- Implemented deterministic policy comparison with actual agent rationale and strict operator approval before booking.
- Deployed `VehicleImpacts`, `SuspectedImpacts()`, native Activator `5178d1e4-ed4e-438a-ba63-27e968d0fcda`, and pipeline `cc0eaf11-e878-40a1-b041-12d086b223c0`. Read-back confirms the rule is running; actual trigger execution remains to be verified.
- Extended the dashboard with incident cards, phone-message preview, original and redacted evidence, quote comparison, correspondence, native-agent links and a decision timeline.
- Added insurance tests; full suite now **39 passing**.
- **Real-service end-to-end verification passed:** case `CDI-9076122125` progressed from evidence received to report ready, quotations, recommendation and **booked**. Used the actual Azure vision model, all three native garage agents, native coordinator and actual Exchange emails. Metro was selected and its confirmation recorded with expected return `2026-10-02`. The operator-approval transition was exercised explicitly by the verification runner. Twelve correspondence records represent eight actual sent emails plus the received copies.
- The real-service test uses isolated local case storage; it proves the services and workflow, not yet the hosted browser/Activator journey. Full output is retained in ignored `.local\repair-verified.json`; raw customer or token data is not committed.
- Fixed App Service web sign-in configuration: its hybrid `code id_token` flow required ID-token issuance enabled on the app registration. User consent is being completed in the verified Caldova browser profile.
- The current larger prebuilt update was accepted but its file synchronization is slow. Future code-only updates reuse the compatible deployed Linux dependencies; deployment status is checked rather than blindly resubmitting.
- **Hosted end-to-end passed:** `CDI-05E0A06690`, from dashboard impact emission through real mobile evidence upload, privacy analysis, PDF, three garage quotations, native recommendation, browser **Approve & book**, and the actual confirmation email. The approval record names the Caldova operator and is separate from the garage confirmation.
- **Autonomous Fabric execution passed:** after emitting a fresh impact and a below-threshold control sample, pipeline run `036d14ce-524b-4ed9-96b3-c0c4ba61fb1d` completed without manually starting that run. Only the valid impact produced `CDI-168C31C660`; the control did not create an incident.
- Fabric Web activities required a real `WebForPipeline` connection plus `externalReferences.connection`. The initial missing-connection error was repaired and subsequent callback runs completed.
- Reconciliation now waits three minutes before opening a missed impact, so the native Activator callback is the primary detection path rather than being pre-empted by application polling.
- Added a decision-cost sensitivity slider. At GBP 0/day the cheapest repair-price option wins; at the recorded GBP 100/day policy Metro wins. Exploration never changes the recorded approval policy.
- Added an inspection-required scenario, evidence follow-up with preserved history, and explicit safety/consent gates.
- Affected vehicles now stop accumulating distance and remain on an incident hold. The first hold anchor never moves the odometer backwards when an older case is first loaded by a newer deployment.
- Added actual `Incident` and `RepairQuotation` ontology entities and relationships, plus approval rules.
- Fixed two native Fabric metadata issues: ontology updates preserve existing lineage tags; newly added SQL columns require SQL endpoint metadata synchronization and a refreshed native agent source schema. The generic agent rejection for unknown columns was resolved by synchronizing the actual schema, without disabling governance.
- Verified the Fabric agent correctly identifies `CDI-168C31C660` as awaiting approval and `CDI-05E0A06690` as confirmed booked, using explicit boolean facts rather than guessing from status labels.
- Published the Fabric agent to the native Microsoft 365 Agent Store and renamed it **Caldova Fleet IQ** to distinguish it from the notification app.
- **Microsoft 365 live chat verified:** the native agent connected to the Data Agent MCP server and returned the real awaiting-approval case and recommended garage. The first attempt occurred during the existing overnight capacity shutdown and correctly reported unavailable data; after the approved resume, the actual query succeeded.
- Added proper delegated API access for Azure CLI to the application's own `access_as_user` scope. This does not widen Graph permissions; the API still requires the exact configured Caldova operator.
- Exchange message trace confirmed **Delivered** for the two actual operator emails: the pending recommendation and the confirmed booking. These provide genuine work-context material for the IQ presentation.
- Replaced scaffold escalation prose with a real operations-review instruction. PAC can return exit code zero after a failed publish; `tools\publish_agents.ps1` now requires explicit publication success. All four corrected agents subsequently published successfully.
- **Primary-trigger timing verified:** fresh impact `e3b42069-e2e2-4efc-a5cf-7aae2c7fd641` created `CDI-816DB5A515` through actual Fabric pipeline run `8c12473e-1fc1-4306-b179-2b5467ebb451` in **91.8 seconds**. The test deadline is shorter than the three-minute reconciliation delay and requires persisted `fabric_pipeline` provenance, so application polling cannot satisfy this check.
- The Activator time-axis query now uses an exclusive lower watermark and inclusive upper watermark to avoid repeatedly firing on the previous interval's boundary event.
- **Work IQ retrieval verified:** the main Microsoft 365 Copilot chat found one matching claims email, cited `[CDI-168C31C660] Repair recommendation ready for your approval`, and accurately explained the Metro cost trade-off.
- Added hard validation that workflow mailboxes and the operator notification address remain in the Caldova domain. Configuration changes cannot silently enable emails to outside garages or the corporate tenant.
- Preserved exactly one operator decision/booking notice per case, without granting the service read access to the operator's mailbox.
- Stopped the obsolete local preview; the persistent Azure app is the presentation endpoint.
- Cleaned up the obsolete extracted CLI installer and an unused downloaded image. Retained deployment tooling, encrypted credentials and validation artifacts under ignored `.local`.
- **Native channel hardening verified:** all four anonymous token endpoints now return **HTTP 403**, while authenticated native inference succeeds. Credentials were obtained through supported masked Studio controls, validated against the actual responding agent identities, encrypted locally with Windows DPAPI and stored at runtime only in protected Azure app settings. Production cannot fall back to anonymous invocation, and a response from the wrong native runtime ID is rejected.
- Native web-security changes are eventually consistent. Actual endpoint rejection was checked rather than assuming the UI toggle was already enforced.
- The browser automation helper now sets and reads back the complete allowed URL atomically; long URL typing had occasionally truncated a settings route. It still refuses to act in a profile other than the confirmed Caldova profile.
- Ran all **51 unit/API tests** with cloud configuration and credentials deliberately replaced by fail-fast functions. They still passed, so the offline tests do not depend on local deployment state.
- **Final secured hosted journey passed:** `CDI-A14808C265` on CD-005, native pipeline `6b3c52ca-667b-4051-b30e-5b79c09c4d71`, all three actual garage agents, actual coordinator identity, real internal emails, explicit delegated-operator approval and a Metro booking confirmation. Total measured time: **238.14 seconds**. The prepared Volvo case remains unapproved for the presentation.

## Where the data and real agents are

| Surface | Item |
| --- | --- |
| Live telemetry | `CaldovaFleet` Eventhouse / KQL database: `Telemetry`, `Vehicles`, `Branches`, `VehicleImpacts` |
| Detection query | `SuspectedImpacts()` in the same KQL database |
| Native alert | `Caldova_Incident_Activator`, `5178d1e4-ed4e-438a-ba63-27e968d0fcda` |
| Native callback pipeline | `Caldova_Impact_Response`, `cc0eaf11-e878-40a1-b041-12d086b223c0` |
| Governed facts | `FleetIntelligence` Lakehouse: seven tables, including actual `Incidents` and `RepairQuotes` projections |
| Digital-twin context | `Caldova_Fleet_Digital_Twin` ontology |
| Natural-language data access | `Caldova Fleet IQ` Fabric data agent, also published to Microsoft 365 |
| Photo evidence agent | Foundry → `caldovadrive08667473-foundry` → `caldova-insurance` → `caldova-incident-evidence` |
| Repair agents | Four native Copilot Studio workspaces under `copilot\`, in the Caldova default Power Platform environment |
| Original emails | Four dedicated shared mailboxes; the app displays the actual message bodies, timestamps and Outlook links |
| Work context | Two real emails delivered to the operator: the pending decision and the confirmed booking |

## Fabric workspace items explained

Items in **Caldova Drive - Fleet Intelligence**, in data-flow order:

| Item | Type | What it is | Who writes / uses it |
| --- | --- | --- | --- |
| `CaldovaFleet` | Eventhouse | Real-Time Intelligence container (the Kusto cluster) holding the live telemetry database. | Hosts the KQL database below. |
| `CaldovaFleet` | KQL Database | Raw streaming data: `Telemetry` (~2-minute samples per car), `Vehicles`, `Branches`, `VehicleImpacts`, plus functions `FleetLatest()`, `FleetDailyMileage()`, `SuspectedImpacts()` (`fabric\schema.kql`). | Written by the App Service worker/simulator and **Send impact telemetry**. Read by the dashboard, the Activator and the Lakehouse refresh. |
| `Caldova_Incident_Activator` | Activator | Detection rule: polls `SuspectedImpacts()` every minute (≥2.5 g, Δv ≥4 km/h, ≤1 km/h after) and fires an action. | Triggers the pipeline below. |
| `Caldova_Impact_Response` | Pipeline | Data Factory pipeline with a Web activity that calls the app's authenticated callback to open the incident. | Started by the Activator; its run ID is stored as case provenance. |
| `FleetIntelligence` | Lakehouse | Curated OneLake Delta tables: `Vehicles`, `Branches`, `Rentals`, `VehicleState`, `DailyMileage`, `Incidents`, `RepairQuotes`. | Rewritten by the app every ~2 minutes from KQL and case state (`fleet\fabric.py` `refresh_lakehouse`). The single source of truth for the ontology, graph and data agent. |
| `FleetIntelligence` | SQL analytics endpoint | Read-only T-SQL view over the same Lakehouse tables, auto-created with the Lakehouse. | Queried by the data agent and the ontology bindings. Needs a metadata sync after schema changes (`--refresh-schema`). |
| `Caldova_Fleet_Digital_Twin` | Ontology | Fabric IQ business model: 7 entity types with keys, 7 relationships and the rules `MileageAccounting` and `RepairApproval`, all bound to the Lakehouse tables. | Generated by `tools\intelligence.py`. Shown in storyline step 14. |
| `Caldova_Fleet_Digital_Twin_graph_<ontologyId>` | Graph model | The ontology materialized as a graph: entities become nodes and relationships become edges, loaded from the Lakehouse Delta tables. Powers **Explore graph** and path queries (GQL). | Created by the ontology. Definition and refresh come from `materialize_graph` in `tools\intelligence.py`. A refresh is a snapshot, so rerun it after data changes. |
| `Caldova_Fleet_Digital_Twin_eh_<ontologyId>` | Eventhouse + KQL Database | System infrastructure that the ontology creates automatically for its own use. It is not part of the demo data. | Managed by Fabric. Do not delete it or write to it. |
| `Caldova Fleet IQ` | Data agent | Natural-language Q&A over the Lakehouse tables, with governed instructions (units, Europe/Madrid calendar, approval vs. booking semantics). Published to Microsoft 365 Copilot. | Configured by `tools\intelligence.py`. Used in storyline step 15. |

## Implementation inventory

| Files | Responsibility |
| --- | --- |
| `fleet\domain.py`, `fleet\simulator.py` | Deterministic road-following telemetry, mileage intervals and incident holds |
| `fabric\schema.kql`, `fabric\insurance.kql` | Deduplication, daily distance accounting and suspected-impact detection |
| `tools\insurance_fabric.py` | Actual Fabric schema, authenticated Web connection, pipeline and Activator deployment |
| `fleet\insurance.py`, `fleet\storage.py` | Transactional case state, access tokens, histories, quote policy, approvals and leases |
| `fleet\evidence.py` | Image validation, private originals, actual vision inference, privacy masks/check and PDF |
| `fleet\foundry.py`, `infra\foundry.bicep`, `tools\provision_foundry.py` | Actual Foundry resource/project, versioned evidence agent, agent endpoint and project-scoped runtime authorization |
| `fleet\studio.py`, `copilot\` | Actual published native agents and server-side Direct Line invocation |
| `fleet\mail.py`, `fleet\repair_workflow.py` | Scoped real mail transport, receipts, inbox events, native-agent orchestration and booking |
| `fleet\incident_routes.py`, `fleet\web.py` | Authenticated operator APIs, public capability-link customer APIs and workers |
| `static\report.*`, `static\repairs.*` | Mobile customer experience and operator incident centre |
| `tools\configure_api_access.py` | Legitimate delegated operator API access for automated hosted verification |
| `tools\secure_agent_channels.py` | Encrypted native channel credential staging and Azure publication |
| `tests\test_*.py` | Offline unit/API regression tests |
| `tests\hosted_browser.py` | Actual deployed UI and access-boundary checks |
| `tests\live_activator.py` | Real primary-Activator timing/provenance check |
| `tests\live_insurance.py` | Full hosted case, secured real agents, emails, API approval and confirmation |

## Presenting an eight-minute version

1. **Fleet overview, 45 seconds:** show 40 cars and the vehicles needing attention.
2. **Signal to case, 60–90 seconds:** use a vehicle without an active case and select **Send impact telemetry**, or show the pipeline provenance of prepared case `CDI-008FC82110`.
3. **Customer intake, 60 seconds:** open the phone-message preview, follow the secure link, upload `static\demo-assets\bumper-dent.jpg`, enter a brief account and submit.
4. **Evidence and correspondence, 60 seconds:** show the protected original, redacted PDF and actual replies in the prepared Volvo case. Open the Word policy's RP-02, RP-03 and RP-05 clauses.
5. **Business decision, 60 seconds:** Alder is GBP 450 and returns first, but its new aftermarket parts make it ineligible. At GBP 0/day the compliant-only slider selects Riverside; at GBP 100/day it selects Metro. Alder never becomes selectable.
6. **Approval, 30–60 seconds:** show the valid Riverside override with a reason, then return to Metro. Use **Approve & book** only when ready to consume the prepared case; the separately completed `CDI-EDB4612D4F` already proves the real confirmation path.
7. **IQ context, 60 seconds:** use main Copilot's saved **Caldova Repair Policy Comparison** chat. Open its Word-policy and supplier-email citations, then ask Fabric IQ for live quote eligibility.
8. **Trust boundary, 30 seconds:** explain that the API also rejected an attempted Alder override with a reason. A cheaper or faster prohibited part is not an exception, and the same chosen quote/policy fingerprints are rechecked for booking.

## Verification artifacts

All artifacts below are local and ignored by Git; credentials and access links must not be committed.

- `.local\repair-verified.json`: completed actual-service case and its provenance.
- `.local\hosted-browser-results.json`: final hosted checks and prepared case IDs.
- `.local\primary-activator-result.json`: native pipeline ID and measured detection time.
- `.local\secured-hosted-e2e.json`: completed final hosted journey with secured native channels.
- `.local\hosted-recommendation.png`: actual quote comparison and decision trail.
- `.local\hosted-phone-journey.png`: actual phone-message preview.
- `.local\customer-report-mobile.png` and `.local\customer-report-received.png`: real hosted mobile intake.
- `.local\hosted-incident-mobile.png`: responsive operator view.
- `.local\build-id.txt`: expected deployed source/configuration hash.
- `.local\oem-ready-case.json`: current unapproved OEM-policy case and rejected aftermarket-override proof.
- `.local\fabric-oem-answer.json`: actual native Fabric answer from the new parts-compliance columns.
- `.local\oem-workiq-browser.txt`: actual main Microsoft 365 Copilot answer, including Word and original-email citation labels.
- `.local\oem-workiq-comparison.png`: real Caldova Work IQ conversation screenshot.

The recurring CLI continuation schedule was stopped after the completed demo, final verification and runbook were persisted. The Azure application and its morning automation continue independently.

## Running and pausing the demo

The complete repository was relocated to `C:\gitrepos\github\crgarcia12\azure-autito-demo` on 1 October 2026. All 20,319 original files, including hidden deployment state and local tooling, were moved. The old nested location is empty. Python activation and executable launchers were repaired for the new path; package versions and encrypted credentials were preserved.

The Azure site, workers, native rules and agents do not depend on the CLI session staying open. The obsolete localhost preview has been stopped to avoid presenting stale code.

Keep App Service at one instance and preserve `/home/data/caldova`. For a temporary operational pause, use App Service settings `FLEET_WORKER_ENABLED=false` and `FLEET_REPAIR_WORKER_ENABLED=false`, or stop this demo's App Service. Do not delete or repurpose the shared Apollo capacity. The telemetry studio's pause control pauses only injection; it is not a complete infrastructure shutdown.

The expected morning sequence is capacity readiness at 06:45 Europe/Madrid, telemetry catch-up, and the daily report at 08:00. Existing completed-send receipts prevent ordinary duplicate delivery across restarts.

## Real-service verification

The isolated runner makes actual requests and sends only to the four dedicated Caldova mailboxes and the configured Caldova operator notification address:

```powershell
.\.venv\Scripts\python.exe -m tools.verify_repair_services --approve
```

It refuses to invent a response if image review, native agent execution, quote validation or mail delivery fails. Its state persists under `.local\repair-verification.sqlite3`; rerunning does not resend the completed case.

For a new, fully hosted verification using the actual primary Fabric trigger and all secured agents:

```powershell
.\.venv\Scripts\python.exe -m tests.live_insurance
```

This command deliberately creates a real demo incident, uploads the approved evidence asset, sends real internal emails and exercises approval. It chooses an available vehicle rather than changing the prepared awaiting-approval case.

Image sources and licensing are recorded in `static\demo-assets\attribution.txt`. The clearer Foundry-positive input is [Dented car bumper, Mark Holmberg](https://www.publicdomainpictures.net/en/view-image.php?image=498350&picture=dented-car-bumper), released under CC0. The older [Jetta Mk. IV Bumper Damage, TWikisto](https://commons.wikimedia.org/wiki/File:Jetta_Mk._IV_Bumper_Damage.jpg) is public domain; its full view supports an inspection-required branch. Foundry correctly treated the old faint cropped detail as insufficient evidence rather than inventing damage. No image was altered to force a model decision.

## Foundry cutover, 1 October 2026

- Created an actual `AIServices` Foundry resource with managed identity and project management, plus the `caldova-insurance` project. No new VNet or private endpoint was created.
- Deployed `incident-vision` inside Foundry and registered `caldova-incident-evidence:2` in Foundry Agent Service. Its endpoint routes 100% to that version.
- The operator has project-scoped Foundry Project Manager access. The application managed identity has project-scoped Foundry Agent Consumer access.
- The application uses the supported Foundry agent Responses endpoint under `services.ai.azure.com/api/projects/.../agents/...`, not a standalone model endpoint. JSON mode and sampling settings belong to the managed agent definition.
- Each report records the actual Foundry agent, version, project endpoint and response IDs for photo inspection, privacy verification and report assembly.
- The first uploaded fixture was honestly routed for review because it lacked clear visible damage. A verified CC0 photograph with a visible bumper dent passed without weakening the review guardrails.
- The Azure user session encountered a Continuous Access Evaluation challenge. It was renewed through Microsoft's supported device sign-in using only the Caldova account.
- A cold Fabric pipeline callback arrived after the three-minute reconciliation window. The incident was preserved by reconciliation; that run is not claimed as a successful primary-trigger timing test.
- **Hosted Foundry-backed workflow passed:** case `CDI-447819C9E7`, CD-006, reached `booked` after three real Foundry responses, all real Copilot Studio quotation agents, actual email, operator approval and Metro confirmation. Measured time from continuing the detected case: **173.41 seconds**.
- Only after that verification, `tools\retire_openai.py` removed the superseded `caldovadrive08667473-ai` account and cleared obsolete endpoint settings. All operational case data and the new Foundry resource were retained.
- `storyline.md` provides the requested chronological story, what to open, feature names and presenter narration for all 15 steps.

## Genuine OEM policy extension, 2 October 2026

- **Controlled policy:** `policies\repair-policy.json` is the versioned clause source; `policies\Caldova-Repair-Policy.docx` is the generated Word document. `policies\publication.json` records the actual Microsoft 365 item, URL, ETag and source/document SHA-256 values. A source change without corresponding publication is rejected.
- **Publication:** the Word file is in the Caldova operator's OneDrive for Business library, **Caldova Drive / Policies**. The root communication site had no accessible document library; the existing operator-only Content Studio Files.ReadWrite consent was used instead. Downloaded cloud bytes exactly matched the local Word file. No anonymous sharing or tenant-wide application file permissions were added.
- **Rules:** RP-02 requires new genuine OEM replacements; RP-03 requires explicit component, manufacturer, origin, condition and vehicle approval; RP-04 permits genuine repair without replacement; RP-05 excludes noncompliant quotes before ranking; RP-07 prohibits policy-waiving overrides and requires human approval. Used, refurbished and remanufactured replacements are also blocked.
- **Supplier story:** Alder discloses new Northline Components aftermarket parts, with the earliest return and lowest price. Metro and Riverside explicitly declare new genuine vehicle-manufacturer OEM parts. The garage agents must copy the trusted structured offer unchanged, including the honest noncompliance declaration.
- **Deterministic enforcement:** every component is evaluated. Missing fields require clarification; if no offer qualifies, `quote_review_required` has no default winner. Approval verifies the quote set and current policy; the chosen quotation's fingerprint and policy hash are retained. Dispatch and actual garage confirmation revalidate the commitment. Completed historical cases retain their original terms.
- **Real agents and email:** all four agents were pushed and published with explicit success confirmations. Each anonymous token endpoint still returns HTTP 403. Requests include the policy; actual supplier replies include binding parts declarations. The operator receives three unchanged quotation-evidence copies with original sender/date/Outlook link, plus the policy-linked decision packet.
- **Fabric:** `RepairQuotes` now includes `PartsItems`, `PartsDeclaration`, `PartsComplianceStatus`, `PartsEligible`, `PartsComplianceReasons`, policy identity/version/document link and source-email references. SQL metadata was refreshed, the actual native source rediscovered and published, and the ontology/graph updated without changing existing keys or relationships. The data agent still queries LakehouseTables, not a direct ontology source.
- **Hosted ready case:** `CDI-008FC82110`, CD-002, reached a genuine policy-aware recommendation in **210.44 seconds**, via Fabric pipeline `ace6ac9d-72e9-4a1d-babc-1961826e7823`. The API rejected selecting Alder even with an override reason. The case remains unapproved.
- **Hosted booking case:** `CDI-EDB4612D4F`, CD-003, completed in **289.06 seconds**, via pipeline `1d7632d7-3571-45d1-80f4-dcf4913c913d`. Foundry evidence, all three Studio suppliers, the coordinator, real email, human approval and Metro confirmation were exercised. Approved and confirmed quotation hashes both equal `59b52f9498efb028089d94022b3e12d6a56d8f9f3a4f979fac9b2a8309cced45`.
- **Work IQ:** the actual main Copilot conversation found the Word document and all three relevant supplier-evidence emails, with citations. It independently produced the correct GBP 850 excluded Alder / GBP 1,100 eligible Metro / GBP 1,250 eligible Riverside comparison and cited RP-02, RP-03, RP-05, RP-06 and RP-07.
- **Verification access:** an optional standalone Work IQ CLI hit its Windows broker-window limitation, and a temporary operator-only Copilot API consent probe required interactive sign-in. Its extra delegated scopes were removed; the exact original operator grant was restored and verified. No permissions were added to the other content authors or application mailbox grants. The successful proof uses the existing Caldova Copilot browser session.
- **Regression evidence:** the full Python suite, real hosted browser controls, real prepared and booked cases, native data-agent query, exact published Word bytes and actual Work IQ cross-source reasoning were exercised. Hosted browser evidence explicitly records that there is no currently prepared inspection-review case; that branch retains its unit/API coverage.

To prepare another unapproved policy case:

```powershell
.\.venv\Scripts\python.exe -m tests.live_insurance --leave-ready
```

## Customer email and operational MINI portal, 4 October 2026

- Initial incident notifications are real emails from the claims mailbox to `admin@caldova08667473.onmicrosoft.com`, selected by the user as the customer inbox. The subject is `[case] [REPORT] Your secure incident report link`.
- The email and **Open customer journey** share the same expiring capability. Case creation, link rotation and the stored token now commit atomically. A durable outbox receipt prevents duplicate initial emails; confirmed sends are reconciled into the case even after an interrupted audit write.
- The first verified customer email was for `CDI-5D489A69A8` at `2026-10-04T20:06:47Z`. After the vehicle/photo update, the MINI email was sent for `CDI-2DFF4DB375` at `2026-10-04T20:54:41Z`. Its actual emailed link opened the hosted form; no report was submitted by verification.
- Primary supplied image: `media\crash1.png`, SHA-256 `b9f7f397c18b3445173a3a6ba222584265f739adc7dcdaff6a0915cc88458291`. The original PNG is packaged unchanged and preserved on upload. Model processing uses the existing normalized JPEG path.
- Vehicle CD-006 is now MINI Cooper, Green, registration YK23 LZP. `tools\sync_demo_vehicle.py` changes only this register entry; `RegisterVersion=2` disambiguates it from prior ingested metadata. Routes, telemetry event IDs, odometers and existing incident snapshots are unchanged. The tool clears only the Vehicles streaming-schema cache before using added columns, then verifies the exact ingested values.
- The customer-report simulator is limited to the matching MINI. Other vehicles retain manual photo upload. Garage offer text now refers to the damaged bumper rather than incorrectly hard-coding a rear bumper.
- Removed promotional headings and company branding from portal chrome, customer-form copy, new PDF briefs and new system notices. The logo is a neutral vehicle icon. Historical correspondence and infrastructure identifiers retain their original values.
- The genuine Foundry assessment of the MINI image redacted the plate, but classified possible fender involvement as `inspection_required`. That review gate remains intact. Use the existing prepared quotation case for the cost comparison rather than misrepresenting the MINI result.
- Hosted checks verified the operational headings, actual map tiles, green MINI metadata, customer form, and blocked anonymous API access. Bearer-authenticated operator API checks succeeded after normal redeployment; authentication was not disabled or broadened.
- Receipts: `.local\live-customer-email-CD-006.json`, `.local\mini-vehicle-sync.json`, `.local\mini-photo-check.json`. Visual evidence: `.local\hosted-operational-mini.png`, `.local\hosted-mini-incident.png`, `.local\customer-email-report-form.png`.
- Fabric chat returned the actual `CD-006` values MINI / Cooper / Green after the new source columns were synchronized and selected. The ontology's automatic graph-refresh job `781c692a-f74a-4951-9377-f21998337a01` completed successfully. An additional request was marked `Deduped`; tooling now treats that as terminal and avoids requesting a second refresh after a graph-definition update.

## Stornoway customer form and external garage copy

- Weather context uses the Microsoft Web IQ web-search endpoint. The App Service must have `WEB_IQ_API_KEY` configured outside source control; search results retain their source URLs and are not presented as verified incident-time observations.
- Original unapproved MINI case `CDI-2DFF4DB375` was closed with an explicit reason; its photos, customer report, assessed report, quotations and correspondence were verified unchanged. New case `CDI-4170F5EC25` received its reporting email at `2026-10-04T22:48:47Z`.
- The MINI is parked at the configured Stornoway coordinates. Its prior odometer is retained, subsequent parked distance is zero, and other vehicles are unchanged. Historical telemetry is retained; the current map trail starts after relocation rather than drawing an artificial London-to-Stornoway journey.
- The form no longer has the safe-place checkbox or safety-information banner. Name and email appear first and are editable, defaulting to Alex Morgan / alex.morgan@example.com. The final requested behaviour leaves **What happened? empty** and required.
- Missing safe-place confirmation is stored as `safe=null`, not invented as true. Reported assistance or injury still stops automatic repair procurement; consent remains required for the normal route.
- Weather context is searched through Web IQ for the incident location and timestamp. Results include source URLs and are explicitly labeled as web context, not confirmed station observations. Weather never fills or rewrites the customer's explanation. Missing or failed searches are shown as unavailable.
- The coordinator is instructed to write an actual email to an external garage, not an internal report. The evidence-report prompt and RFQ validation reject processing notes such as “No personal identifiers or license plate information are included.” The external policy footer contains quote requirements, not internal ranking or prompt instructions.
- A real coordinator invocation omitted the unwanted privacy commentary even when it appeared in its input brief. The customer form was exercised under its actual CSP without enabling unsafe evaluation, and its empty explanation/contact defaults/weather fields were verified on the deployed site.
- Receipts: `.local\live-customer-email-CD-006-v3.json`, `.local\stornoway-case-setup.json`, `.local\stornoway-weather-check.json`, `.local\external-garage-email-check.json`.
