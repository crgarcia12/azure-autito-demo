(() => {
  const labels = { awaiting_report: "Awaiting customer report", assistance_required: "Assistance required", evidence_received: "Analysing evidence", report_review_required: "Evidence review required", report_ready: "Preparing quotations", requesting_quotes: "Sending quotation requests", awaiting_quotes: "Awaiting repair centres", quote_review_required: "Parts policy review required", recommendation_ready: "Repair recommendation ready", approved: "Approved · preparing booking", booking_requested: "Awaiting booking confirmation", booked: "Repair booked", closed: "Closed", not_an_incident: "No incident", archived: "Archived run" };
  let chosen = /^CDI-[A-F0-9]{10}$/.test(state.requestedCase || "") ? state.requestedCase : null, current = null, timer, loadedVersion = null;
  const picks = {}, reasons = {};
  const money = (value) => new Intl.NumberFormat("en-GB", { style: "currency", currency: "GBP", maximumFractionDigits: 0 }).format(Number(value));
  const date = (value) => new Date(value).toLocaleString("en-GB", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
  const esc = escapeHtml;
  const agentLabel = (agent) => agent.name.replace(/^Caldova\s+/i, "");
  const studioLink = (agent) => `https://copilotstudio.microsoft.com/environments/${encodeURIComponent("Default-b6883271-971b-4198-92a5-8ad615765572")}/bots/${encodeURIComponent(agent.id)}/overview`;
  const agentLink = (agent) => agent.url || studioLink(agent);
  const agentPlatform = (agent) => agent.provider ? "Microsoft Foundry" : "Copilot Studio";
  function complianceFor(quote, caseData) {
    if (["booked", "closed", "archived"].includes(caseData.status)) {
      return quote.compliance || { eligible: false, status: "historical", findings: [] };
    }
    return caseData.quote_compliance?.[quote.garage_id] || quote.compliance || { eligible: false, status: "clarification_required", findings: [{ clause: "RP-03", reason: "Written parts evidence is required." }] };
  }
  const eligibleQuotes = (caseData) => (caseData.recommendation?.quotes || []).filter((quote) => complianceFor(quote, caseData).eligible);
  function policyPanel(caseData) {
    const retrieved = caseData.work_iq_policy;
    const policy = retrieved?.source || caseData.recommendation?.policy || caseData.repair_policy;
    if (!policy) return "";
    return `<div class="parts-policy"><b>${esc(policy.id)} v${esc(policy.version)} · New genuine OEM parts only</b>${retrieved ? `<p><b>Retrieved with Work IQ</b> · ${date(retrieved.retrieved_at)} · ${esc(retrieved.agent.name)}</p>` : ""}<p>Aftermarket, used, refurbished and remanufactured replacements are excluded before ranking. Missing parts evidence requires clarification. An operator override cannot waive this requirement.</p>${policy.document_url ? `<a href="${esc(retrieved?.citations[0] || policy.document_url)}" target="_blank" rel="noreferrer">Open the Word policy source ↗</a>` : ""}</div>`;
  }
  function agentActivity(caseData) {
    const actions = caseData.agent_actions || [];
    if (!actions.length) return "";
    return `<section class="case-section card"><h3>Agent activity</h3><p>Recorded tool calls and their actual sources and delivery receipts.</p>${actions.map((action) => `<details class="email-item"><summary>${esc(action.agent)} · ${action.tool === "read_repair_policy" ? "Read policy with Work IQ" : "Sent email"}<small>${date(action.at)} · ${esc(action.tool)}</small></summary>${action.subject ? `<p>${esc(action.subject)}<br>${esc(action.mailbox)} → ${esc(action.recipient)}</p>` : `<p>${esc(action.policy_id)} v${esc(action.policy_version)}<br>${action.work_iq_document_id ? "Work IQ document: " + esc(action.work_iq_document_id) : "Work IQ task: " + esc(action.work_iq_task_id)}</p>`}<p class="fabric-proof">Foundry response: ${esc(action.response_id)}<br>Tool call: ${esc(action.call_id)}</p>${action.source_url ? `<a href="${esc(action.source_url)}" target="_blank" rel="noreferrer">${action.tool === "read_repair_policy" ? "Open Word policy citation" : "Open sent email in Outlook"} ↗</a>` : ""}</details>`).join("")}</section>`;
  }
  function tradeoff(caseData) {
    const r = caseData.recommendation;
    const eligible = eligibleQuotes(caseData);
    if (!r?.garage_id || !eligible.length) return "";
    const selected = r.quotes.find((quote) => quote.garage_id === r.garage_id);
    const lowest = [...eligible].sort((a, b) => Number(a.amount_gbp) - Number(b.amount_gbp))[0];
    const premium = Number(selected.amount_gbp) - Number(lowest.amount_gbp);
    const days = lowest.downtime_days - selected.downtime_days;
    const saving = Number(lowest.total_expected_gbp) - Number(selected.total_expected_gbp);
    return `<div class="tradeoff-strip"><div><b>${money(premium)}</b><small>Premium over lowest compliant repair price</small></div><div><b>${days} days</b><small>Earlier than ${esc(lowest.garage_name || lowest.garage_id)}</small></div><div><b>${money(saving)}</b><small>Lower total expected cost</small></div></div><div class="sensitivity"><label for="downtime-sensitivity">What if downtime had a different cost?</label><input id="downtime-sensitivity" type="range" min="0" max="250" step="10" value="${r.policy.downtime_cost_per_day}"><span id="sensitivity-result"></span><small>Compliant offers only, at every rate. Exploration does not change the recorded ${money(r.policy.downtime_cost_per_day)}/day approval policy.</small></div>`;
  }
  function renderQuotes(caseData) {
    const recommendation = caseData.recommendation;
    const quotes = recommendation?.quotes || Object.values(caseData.quotes);
    if (!quotes.length) return '<p>Repair-centre quotations will appear here as actual replies arrive.</p>';
    const decidable = caseData.status === "recommendation_ready" && recommendation?.agent && eligibleQuotes(caseData).some((quote) => quote.garage_id === recommendation.garage_id);
    if (picks[caseData.id] && !eligibleQuotes(caseData).some((quote) => quote.garage_id === picks[caseData.id])) delete picks[caseData.id];
    const selected = decidable ? (picks[caseData.id] || recommendation.garage_id) : caseData.approval?.garage_id;
    const overridden = caseData.approval?.override;
    return `<div class="quote-grid${decidable ? " decidable" : ""}">${quotes.map((quote) => {
      const compliance = complianceFor(quote, caseData), enabled = compliance.eligible;
      const status = { compliant: "Compliant · new genuine OEM", noncompliant: "Noncompliant · cannot book", clarification_required: "Clarification required", historical: "Historical parts terms not recorded" }[compliance.status];
      const recommended = recommendation?.garage_id === quote.garage_id, isSelected = selected === quote.garage_id;
      const badge = [recommended && (enabled || compliance.status === "historical") ? '<span class="quote-recommend">Copilot recommends</span>' : "", !decidable && isSelected && overridden ? '<span class="quote-recommend operator">Operator choice</span>' : ""].join("");
      const terms = quote.replacement_parts_required === false ? "No replacement parts" : (quote.replacement_parts || []).map((part) => `${part.component}: ${part.condition}, ${part.origin === "genuine_oem" ? "genuine OEM" : part.origin} · ${part.manufacturer}`).join("; ");
      return `<article class="quote-card ${recommended && (enabled || compliance.status === "historical") ? "winner" : ""} ${isSelected && (enabled || compliance.status === "historical") ? "selected" : ""} ${enabled || compliance.status === "historical" ? "" : "blocked"}" data-garage="${esc(quote.garage_id)}" data-name="${esc(quote.garage_name || quote.garage_id)}"${decidable ? ` role="radio" tabindex="${enabled ? "0" : "-1"}" aria-checked="${enabled && isSelected}" aria-disabled="${!enabled}"` : ""}>${badge ? `<div class="quote-badges">${badge}</div>` : ""}<h4>${esc(quote.garage_name || quote.garage_id)}</h4><div class="quote-price">${money(quote.amount_gbp)} <small>incl. VAT</small></div><div class="parts-status ${esc(compliance.status)}">${esc(enabled && quote.replacement_parts_required === false ? "Compliant · no replacement parts" : status)}</div><p class="parts-terms">${esc(terms || "Parts declaration not supplied.")}</p><dl><dt>Start</dt><dd>${esc(quote.available_from)}</dd><dt>Return to service</dt><dd>${esc(quote.ready_by)}</dd><dt>Warranty</dt><dd>${quote.warranty_months} months</dd></dl>${quote.total_expected_gbp ? `<div class="quote-total"><span>Repair + downtime${enabled ? "" : " · not ranked"}</span><b>${money(quote.total_expected_gbp)}</b></div><p class="quote-exclusions">${quote.downtime_days} calendar days × ${money(recommendation.policy.downtime_cost_per_day)}/day</p>` : ""}<div class="parts-findings">${compliance.findings.map((finding) => `<p><b>${esc(finding.clause)}</b>: ${esc(finding.reason)}</p>`).join("")}</div><div class="quote-exclusions">${esc(quote.exclusions)}</div>${decidable ? `<div class="quote-pick">${!enabled ? "Excluded by repair policy" : isSelected ? "✓ Selected" : "Select this option"}</div>` : ""}</article>`;
    }).join("")}</div>`;
  }
  function decision(caseData) {
    const recommendation = caseData.recommendation, approval = caseData.approval;
    const name = (id) => recommendation.quotes.find((quote) => quote.garage_id === id)?.garage_name || id;
    if (caseData.status === "recommendation_ready" && recommendation.agent) {
      if (!eligibleQuotes(caseData).some((quote) => quote.garage_id === recommendation.garage_id)) return '<p>Written parts evidence and a current policy review are required before approval. Historical quotation terms are preserved.</p>';
      const pick = picks[caseData.id] || recommendation.garage_id, override = pick !== recommendation.garage_id;
      return `<div id="override-box" class="override-box" ${override ? "" : "hidden"}><label for="override-reason">You are choosing a different repair centre than Copilot recommended. Why?</label><textarea id="override-reason" maxlength="500" placeholder="e.g. Customer needs the car back sooner; preferred partner for this branch">${esc(reasons[caseData.id] || "")}</textarea></div><button class="button" id="approve-repair">Approve & book ${esc(name(pick))} →</button>`;
    }
    if (approval) {
      return `<p class="approval-record"><b>Approved by ${esc(approval.by)}:</b> ${esc(name(approval.garage_id))}${approval.override ? ` · <b>overrode</b> the Copilot recommendation (${esc(name(approval.recommended_garage_id))}). Reason: “${esc(approval.reason)}”` : " · the Copilot recommendation"}</p><span class="case-status">${esc(labels[caseData.status])}</span>`;
    }
    return `<span class="case-status">${esc(labels[caseData.status])}</span>`;
  }
  function bindDecision(caseData) {
    const recommendation = caseData.recommendation;
    document.querySelectorAll('.quote-grid.decidable .quote-card[aria-disabled="false"]').forEach((card) => {
      const choose = () => {
        picks[caseData.id] = card.dataset.garage;
        document.querySelectorAll('.quote-grid.decidable .quote-card[aria-disabled="false"]').forEach((other) => {
          const on = other === card;
          other.classList.toggle("selected", on); other.setAttribute("aria-checked", on);
          other.querySelector(".quote-pick").textContent = on ? "✓ Selected" : "Select this option";
        });
        $("override-box").hidden = card.dataset.garage === recommendation.garage_id;
        $("approve-repair").textContent = `Approve & book ${card.dataset.name} →`;
      };
      card.addEventListener("click", choose);
      card.addEventListener("keydown", (event) => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); choose(); } });
    });
    $("override-reason")?.addEventListener("input", (event) => { reasons[caseData.id] = event.target.value; });
  }
  function renderCase(caseData) {
    current = caseData; loadedVersion = caseData.version;
    const report = caseData.repair_report, recommendation = caseData.recommendation;
    const agent = recommendation?.agent ? { ...recommendation.agent, name: agentLabel(recommendation.agent) } : null;
    const elapsed = caseData.timeline.length > 1 ? Math.round((new Date(caseData.timeline[caseData.timeline.length - 1].at) - new Date(caseData.created_at)) / 60000) : 0;
    $("case-detail").innerHTML = `
      ${caseData.last_error ? `<div class="case-error" role="alert"><b>Action needs attention</b><br>${esc(caseData.last_error.message)}</div>` : ""}
      <section class="case-header card"><div class="case-header-top"><div><div class="eyebrow">${esc(caseData.id)}</div><h2>${esc(caseData.vehicle.Make)} ${esc(caseData.vehicle.Model)}</h2><p>${esc(caseData.vehicle.Registration)}${caseData.vehicle.Colour ? ` · ${esc(caseData.vehicle.Colour)}` : ""} · ${esc(caseData.vehicle.City)} · ${date(caseData.created_at)}</p></div><span class="case-status ${esc(caseData.status)}">${esc(labels[caseData.status] || caseData.status)}</span></div><div class="case-stats"><div><b>${number(caseData.telemetry.PeakAccelerationG, 1)} g</b><small>Impact signal</small></div><div><b>${number(caseData.telemetry.DeltaVKmh, 1)} km/h</b><small>Velocity change</small></div><div><b>${Object.keys(caseData.quotes).length}/3</b><small>Garage responses</small></div><div><b>${elapsed} min</b><small>Case progression</small></div></div><div class="case-action-row">${caseData.status === "awaiting_report" && caseData.customer_simulation_available ? '<button class="button button-dark" id="simulate-customer">Simulate customer report</button>' : ""}<button class="button button-light" id="show-customer-link">Open customer journey ↗</button>${report ? `<a class="button button-light" target="_blank" rel="noreferrer" href="/api/incidents/${esc(caseData.id)}/brief.pdf">Repair brief PDF ↗</a>` : ""}</div><div id="customer-phone"></div></section>
      <div class="case-sections">
      <section class="case-section card"><h3>Incident evidence</h3>${caseData.customer_report ? `<p>${esc(caseData.customer_report.description)}</p><p><b>Assistance:</b> ${caseData.customer_report.injuries || caseData.customer_report.safe === false ? "Assistance requested" : "No assistance requested"}</p>${caseData.customer_agent ? `<p class="fabric-proof">Reported by the Microsoft Foundry customer agent · ${esc(caseData.customer_agent.name)} v${esc(caseData.customer_agent.agent_version)}</p>` : ""}` : "<p>The customer has not yet submitted an incident report.</p>"}<div class="case-photos">${caseData.photos.map((photo, index) => `<div><a target="_blank" rel="noreferrer" href="/api/incidents/${esc(caseData.id)}/photos/${photo.id}"><img src="/api/incidents/${esc(caseData.id)}/photos/${photo.id}" alt="Incident photo ${index + 1}"></a><div class="photo-caption">Original evidence · Photo ${index + 1}</div></div>`).join("")}</div>${report ? `<h3>Redacted repair brief</h3><p>${esc(report.summary)}</p><p>${esc(report.redacted_description)}</p><div class="case-photos">${report.photos.map((photo, index) => `<div><img src="/api/incidents/${esc(caseData.id)}/photos/${photo.photo_id}?redacted=true" alt="Privacy-processed photo ${index + 1}"><div class="photo-caption">${photo.privacy_verified ? "Privacy check passed" : "Privacy review required"}</div></div>`).join("")}</div><p><b>Assessment limits:</b> ${report.limitations.map(esc).join(" ")}</p>${report.reasons.length ? `<p>${report.reasons.map(esc).join(" ")}</p>` : ""}` : ""}<div class="fabric-proof">Source: Fabric Eventhouse · ${esc(caseData.telemetry.DetectionRule || "LowSpeedImpact-v1")}<br>Telemetry event: ${esc(caseData.source_event)}<br>A telemetry signal starts a case; it does not confirm liability, coverage or roadworthiness.</div></section>
      <section class="case-section card"><h3>Repair options</h3>${policyPanel(caseData)}${renderQuotes(caseData)}${recommendation ? `<div class="recommendation"><h3>${agent ? "Repair agent recommendation" : recommendation.garage_id ? "Awaiting agent review" : "Parts policy review required"}</h3><p>${esc(recommendation.ai_summary?.operator_summary || recommendation.rationale)}</p><p>${esc(recommendation.ai_summary?.rationale || "")}</p>${decision(caseData)}<small>${agent ? `<a href="${esc(agentLink(agent))}" target="_blank" rel="noreferrer">Open ${esc(agent.name)} in ${agentPlatform(agent)} ↗</a>` : recommendation.garage_id ? "The explicit parts and cost policies have been applied; a native agent must complete its review before approval." : "Obtain a compliant or clarified quotation. No repair centre can be selected."}</small></div>` : ""}${caseData.booking ? `<p><b>Booking confirmed.</b> ${esc(caseData.booking.garage_id)} · expected return ${esc(caseData.booking.ready_by)}. Confirmation email recorded at ${date(caseData.booking.confirmed_at)}.</p>` : ""}</section>
      ${agentActivity(caseData)}
      <section class="case-section card"><h3>The actual correspondence</h3><p>Customer notifications, quotation requests and replies from the approved repair network.</p>${caseData.correspondence.map((message) => `<details class="email-item"><summary>${esc(message.subject)}<small>${esc(message.from)} → ${esc(message.to)} · ${message.at ? date(message.at) : ""}</small></summary><pre>${esc(message.body)}</pre>${message.web_url ? `<a href="${esc(message.web_url)}" target="_blank" rel="noreferrer">Open original in Outlook ↗</a>` : ""}</details>`).join("") || "<p>No emails have been dispatched for this case yet.</p>"}</section>
      <section class="case-section card"><h3>Decision trail</h3><div class="case-timeline">${caseData.timeline.map((event) => `<div class="case-event"><b>${esc(event.kind.replaceAll("_", " "))}</b><small>${date(event.at)} · ${esc(event.actor)}</small></div>`).join("")}</div></section></div>`;
    $("show-customer-link").addEventListener("click", showCustomer);
    $("simulate-customer")?.addEventListener("click", async (event) => {
      const button = event.currentTarget;
      button.disabled = true; button.textContent = "Customer is reporting…";
      try {
        await api(`/api/incidents/${chosen}/simulate-customer`, {});
        toast("The customer agent submitted the report. Evidence processing and garage emails start now.");
        loadedVersion = null; await update();
      } catch (error) { toast(error.message); button.disabled = false; button.textContent = "Simulate customer report"; }
    });
    $("approve-repair")?.addEventListener("click", approveCase);
    if (recommendation) bindDecision(caseData);
    if (caseData.weather_context) {
      const weather = caseData.weather_context, block = document.createElement("div");
      block.className = "fabric-proof";
      const checkedAt = new Date(weather.checked_at).toLocaleString("en-GB", { timeZone: "Europe/London", timeZoneName: "short" });
      const sources = (weather.sources || []).slice(0, 3).map(source =>
        `<a href="${esc(source.url)}" target="_blank" rel="noreferrer">${esc(source.title)} ↗</a>`
      ).join("<br>");
      block.innerHTML = `<b>Weather search · Web IQ</b><br>${esc(weather.summary)}<br>${esc(weather.station_name)} · Checked ${esc(checkedAt)}${sources ? `<br>${sources}` : ""}`;
      document.querySelector(".case-sections .case-section").append(block);
    }
    if (report?.evidence_agent) {
      const evidence = report.evidence_agent;
      const provenance = document.createElement("div");
      provenance.className = "fabric-proof";
      provenance.innerHTML = `<b>Microsoft Foundry Agent Service</b><br>Evidence agent · version ${esc(evidence.version)}<br>${evidence.responses.length} recorded evidence-processing responses<br><a href="https://ai.azure.com" target="_blank" rel="noreferrer">Open Microsoft Foundry ↗</a>`;
      document.querySelector(".case-sections .case-section").append(provenance);
    }
    if (caseData.status === "report_review_required") {
      const reprocess = document.createElement("button");
      reprocess.className = "button button-light";
      reprocess.textContent = "Reprocess existing evidence";
      reprocess.addEventListener("click", async () => {
        reprocess.disabled = true;
        try {
          await api(`/api/incidents/${chosen}/reprocess-evidence`, { version: current.version });
          loadedVersion = null; await update();
          toast("Reprocessing the existing photos. The prior assessment has been preserved.");
        } catch (error) { toast(error.message); reprocess.disabled = false; }
      });
      document.querySelector(".case-sections .case-section").append(reprocess);
      const button = document.createElement("button");
      button.className = "button button-light";
      button.textContent = "Request clearer evidence";
      button.addEventListener("click", async () => {
        button.disabled = true;
        try {
          await api(`/api/incidents/${chosen}/request-evidence`, {
            version: current.version,
            reason: "Please add a clear overview and a close-up of the affected area in good lighting. Avoid faces, registration plates and personal documents. An inspection may still be required.",
          });
          loadedVersion = null; await update(); toast("The case is ready for additional customer evidence. Existing evidence has been preserved.");
        } catch (error) { toast(error.message); button.disabled = false; }
      });
      document.querySelector(".case-sections .case-section").append(button);
    }
    if (recommendation) {
      const compare = document.querySelector(".quote-grid");
      compare?.insertAdjacentHTML("afterend", tradeoff(caseData));
      const slider = $("downtime-sensitivity");
      const showSensitivity = () => {
        const rate = Number(slider.value);
        const candidates = eligibleQuotes(caseData).map((quote) => ({ ...quote, cost: Number(quote.amount_gbp) + quote.downtime_days * rate })).sort((a, b) => a.cost - b.cost || a.ready_by.localeCompare(b.ready_by) || a.garage_id.localeCompare(b.garage_id));
        $("sensitivity-result").textContent = `${money(rate)}/day → ${candidates[0].garage_name || candidates[0].garage_id}, ${money(candidates[0].cost)} total · compliant offers only`;
      };
      slider?.addEventListener("input", showSensitivity);
      if (slider) showSensitivity();
    }
  }
  async function showCustomer() {
    try {
      const result = await api(`/api/incidents/${chosen}/link`, {});
      const url = new URL(result.url);
      if (location.hostname === "127.0.0.1") { url.host = location.host; url.protocol = location.protocol; }
      $("customer-phone").innerHTML = `<div class="phone-preview"><div class="phone-shell"><div class="phone-top">Incident notification</div><div class="sms-bubble">${esc(result.text)}<a class="sms-link" href="${esc(url.href)}" target="_blank" rel="noreferrer">Report your incident securely ↗</a></div><a class="button button-dark" href="${esc(url.href)}" target="_blank" rel="noreferrer">Open on this device →</a></div></div>`;
    } catch (error) { toast(error.message); }
  }
  async function approveCase() {
    $("approve-repair").disabled = true;
    const garage = picks[chosen] || current.recommendation.garage_id;
    const reason = (reasons[chosen] || "").trim();
    try {
      await api(`/api/incidents/${chosen}/approve`, { version: current.version, garage_id: garage, reason: garage === current.recommendation.garage_id ? "" : reason });
      toast("Approved. The booking request will be sent to the selected repair centre.");
      delete picks[chosen]; delete reasons[chosen];
      loadedVersion = null; await update();
    } catch (error) { toast(error.message); $("approve-repair").disabled = false; }
  }
  async function update() {
    try {
      const data = await api("/api/incidents?history=true");
      const visible = data.cases.filter((item) => item.status !== "archived");
      $("incident-count").textContent = visible.length || "";
      $("case-list-subtitle").textContent = `${visible.length} incident${visible.length === 1 ? "" : "s"} · Live workflow`;
      $("case-list").innerHTML = visible.length ? visible.map((item) => `<button class="case-item ${chosen === item.id ? "active" : ""}" data-case="${esc(item.id)}"><b>${esc(item.vehicle.Make)} ${esc(item.vehicle.Model)}</b><small>${esc(item.vehicle_id)} · ${esc(item.vehicle.City)}</small><span class="case-status ${esc(item.status)}">${esc(labels[item.status] || item.status)}</span></button>`).join("") : '<p class="loading-copy">No open incidents. Send an impact signal from the telemetry injector to begin the journey.</p>';
      if (!data.cases.some((item) => item.id === chosen)) {
        chosen = visible[0]?.id || null;
        loadedVersion = null;
        if (!chosen) $("case-detail").innerHTML = '<div class="case-empty card"><h2>No open incidents</h2></div>';
      }
      if (chosen) {
        const detail = await api(`/api/incidents/${chosen}`);
        if (detail.version !== loadedVersion || JSON.stringify(detail.last_error) !== JSON.stringify(current?.last_error)) renderCase(detail);
      }
      const select = $("impact-vehicle");
      if (!select.options.length && state.vehicles.length) {
        for (const vehicle of [...state.vehicles].sort((a, b) => Number(b.Make === "MINI" && b.Model === "Cooper") - Number(a.Make === "MINI" && a.Model === "Cooper"))) {
          const option = document.createElement("option");
          option.value = vehicle.VehicleId; option.textContent = `${vehicle.Registration} · ${vehicle.Make} ${vehicle.Model}${vehicle.Colour ? ` · ${vehicle.Colour}` : ""} · ${vehicle.City}`; select.append(option);
        }
      }
      for (const option of select.options) {
        option.disabled = Boolean(state.vehicles.find((vehicle) => vehicle.VehicleId === option.value)?.IncidentId);
      }
      if (select.selectedOptions[0]?.disabled) {
        const available = [...select.options].find((option) => !option.disabled);
        if (available) select.value = available.value;
      }
      const health = await api("/api/insurance/health");
      $("agent-service-status").innerHTML = `<b>${health.agents.length} Copilot Studio agents</b><br>${health.agents.map((agent) => `<a href="${esc(agentLink(agent))}" target="_blank" rel="noreferrer">${esc(agentLabel(agent))} ↗</a>`).join("<br>")}<br>Policy and email: application-managed<br>Workflow: ${esc(health.workflow?.state || "Not started")}`;
    } catch (error) { $("incident-action-status").textContent = error.message; }
  }
  window.openIncident = async (id) => { chosen = id; loadedVersion = null; setView("incidents"); await update(); };
  $("case-list").addEventListener("click", (event) => { const target = event.target.closest("[data-case]"); if (target) window.openIncident(target.dataset.case); });
  $("inject-impact").addEventListener("click", async () => {
    const vehicle = $("impact-vehicle").value;
    if (!vehicle) { toast("Wait for the live fleet to load."); return; }
    $("inject-impact").disabled = true;
    try {
      const result = await api("/api/telemetry/impact", { vehicle_id: vehicle, event_id: crypto.randomUUID() });
      $("incident-action-status").textContent = result.message; toast("Telemetry sent to Fabric. Waiting for incident detection.");
    } catch (error) { $("incident-action-status").textContent = error.message; }
    finally { $("inject-impact").disabled = false; }
  });
  async function poll() { await update(); timer = setTimeout(poll, 12000); }
  poll();
})();
