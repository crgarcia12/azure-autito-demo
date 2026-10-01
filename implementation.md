# Caldova Drive: implementation and demo runbook

## Scope and operating boundaries

The approved demo is a UK rental-fleet insurance journey: telemetry detects a possible impact, the customer reports the incident and uploads photos, an agent prepares a redacted repair brief, three Copilot Studio garage agents respond to real quotation emails, and the operator approves a repair recommendation before a booking is sent.

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
| Authorized operator | `admin@caldova08667473.onmicrosoft.com` |
| Browser profile | Edge **Work 2 Profile**, identity verified as Caldova |

The user approved dedicated claims/garage shared mailboxes and required AI/agent consumption. **SMS is now a phone-message preview with a real reporting link**, explicitly requested instead of a paid delivery. No private endpoint or VNet is approved. The existing Apollo workspace must not be modified. No credential resets, MFA bypasses, corporate-tenant changes, or messages to real external garages are permitted.

## Current result: working hosted insurance journey

The hosted incident journey has been exercised against **actual Fabric, Azure model inference, Copilot Studio and Exchange Online**, including a real operator approval in the browser and a subsequent real garage confirmation.

Start at <https://caldovadrive08667473.azurewebsites.net/#incidents>. Sign in with the Caldova operator in **Work 2 Profile**.

| Ready-to-present case | Vehicle | State | What to demonstrate |
| --- | --- | --- | --- |
| `CDI-168C31C660` | CD-002, Volvo EX30 | Recommendation ready | Three actual quotes, the native agent rationale, the downtime sensitivity slider and **Approve & book**. This case is deliberately left unapproved. |
| `CDI-05E0A06690` | CD-001, Polestar 2 | Booked | Completed end-to-end case, actual approval by the operator, original correspondence and confirmed return date. |
| `CDI-BCB6A3CE7C` | CD-003, Volkswagen Golf | Evidence review required | The real model found the wider damage photo warranted inspection. No RFQ or quotation was fabricated. |
| `CDI-816DB5A515` | CD-004, BMW 330e | Awaiting customer report | A fresh incident opened by the native Fabric pipeline in 91.8 seconds. Use its phone-message link for a live customer submission. |
| `CDI-A14808C265` | CD-005, Kia EV6 | Booked | Final secured-channel end-to-end verification, completed in 238.14 seconds. |

The selected Metro option in the verified cases is **GBP 600 repair + two calendar downtime days at GBP 100 = GBP 800**. Alder quotes GBP 450 but returns the car later, giving GBP 1,350 total expected cost; Riverside gives GBP 1,250. The additional GBP 150 repair spend versus Alder avoids seven downtime days and reduces expected total cost by GBP 550. Exact dates change with the live business-day calendar when a new case is created.

**Real versus generated:** telemetry, rental identities and garage rate/capacity data are generated for the demonstration. The Fabric rule, pipeline, data agent, four Copilot Studio agents, image-model calls, emails, PDF generation, authentication, uploads and approval processing are real. The phone notification is an in-app preview, not a paid SMS.

**Validation:** 51 unit/API tests pass, including an additional run with cloud configuration and credentials deliberately unavailable. A separate hosted browser run uses a legitimate user-delegated Caldova token and checks the deployed application, all 40 map markers, quote comparison, emails, mobile layout and access boundaries. The core real-service and hosted end-to-end runs are recorded below.

**Microsoft 365:** in the same Caldova profile, open [Microsoft 365 Copilot](https://m365.cloud.microsoft/chat/?auth=2&tenantId=b6883271-971b-4198-92a5-8ad615765572), select **Agents > Caldova Fleet IQ** (created by Fabric Data Agent), and ask which repairs await approval. A real Microsoft 365 conversation returned `CDI-168C31C660` and `metro` from the live data after the capacity was resumed.

**Work IQ:** switch to the main Copilot chat with Work IQ enabled and ask: “Find the email from Caldova Claims Operations about case CDI-168C31C660. Summarize the repair recommendation, its cost trade-off, and what I need to approve. Cite the email.” This was tested: Copilot found the actual delivered email, cited its subject, and explained the GBP 800 Metro recommendation.

**Final build verified:** `ba5a179f9713fc84`. At final handoff the hosted worker was running, all five case states were persisted, all four native anonymous token endpoints returned HTTP 403, credential-authenticated agent execution had passed, and the awaiting-approval case was open in the confirmed Caldova Edge profile.

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
9. Compare total expected cost: quoted repair cost plus the configured cost of vehicle downtime. The cheapest repair is not necessarily the cheapest outcome.
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
- Foundry IQ knowledge-base retrieval is not configured. Photo processing uses a real regional Azure OpenAI model; the business agents run in Copilot Studio.
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
| Repair agents | Four native Copilot Studio workspaces under `copilot\`, in the Caldova default Power Platform environment |
| Original emails | Four dedicated shared mailboxes; the app displays the actual message bodies, timestamps and Outlook links |
| Work context | Two real emails delivered to the operator: the pending decision and the confirmed booking |

## Implementation inventory

| Files | Responsibility |
| --- | --- |
| `fleet\domain.py`, `fleet\simulator.py` | Deterministic road-following telemetry, mileage intervals and incident holds |
| `fabric\schema.kql`, `fabric\insurance.kql` | Deduplication, daily distance accounting and suspected-impact detection |
| `tools\insurance_fabric.py` | Actual Fabric schema, authenticated Web connection, pipeline and Activator deployment |
| `fleet\insurance.py`, `fleet\storage.py` | Transactional case state, access tokens, histories, quote policy, approvals and leases |
| `fleet\evidence.py` | Image validation, private originals, actual vision inference, privacy masks/check and PDF |
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
2. **Signal to case, 60–90 seconds:** use a vehicle without an active case and select **Send impact telemetry**, or open the fresh BMW case to avoid waiting during a short presentation. Show the Fabric source event and pipeline provenance.
3. **Customer intake, 60 seconds:** open the phone-message preview, follow the secure link, upload `static\demo-assets\bumper-detail.jpg`, enter a brief account and submit.
4. **Evidence and correspondence, 60 seconds:** show the protected original, redacted copy/PDF, and original quotation requests and replies. For a time-bounded presentation, use the already prepared Volvo case.
5. **Business decision, 60 seconds:** compare GBP 450/600/550 repair quotes and their different completion dates. Move the downtime slider to zero and back to GBP 100 to explain why the recommendation changes. The actual approval policy is not changed.
6. **Approval, 30–60 seconds:** click **Approve & book** on the Volvo case. Wait for the real Metro confirmation and show the distinct approval and confirmation events.
7. **IQ context, 60 seconds:** ask `Caldova Fleet IQ` for live approval/booking status, then use main Copilot with Work IQ to find the claims decision email and cite it. Use live Fabric facts for current status and email context for the recorded communication.
8. **Trust boundary, 30 seconds:** open the Golf case. Its broader damage image requires inspection and has **zero quotation emails**, demonstrating that uncertain evidence does not silently become an approved repair.

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

The source image is public domain: [Jetta Mk. IV Bumper Damage, TWikisto](https://commons.wikimedia.org/wiki/File:Jetta_Mk._IV_Bumper_Damage.jpg). `static\demo-assets\attribution.txt` records the source and crop. The cropped lower-bumper photo exercises the quotation path; the original full view is retained to exercise an inspection-required branch. These are test/presentation artifacts, not customer photographs.
