"use strict";

const $ = (id) => document.getElementById(id);
const number = (value, digits = 0) => new Intl.NumberFormat("en-GB", { maximumFractionDigits: digits }).format(value);
const escapeHtml = (value) => String(value ?? "").replace(/[&<>"']/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[char]));
const state = { vehicles: [], city: "all", status: "all", search: "", selected: null, map: null, markers: new Map(), mapReady: false, history: [], busy: false, briefing: null, controls: null, config: null, view: "overview", requestedCase: new URLSearchParams(location.hash.split("?")[1] || "").get("case") };
const titles = {
  overview: ["Overview", "Fleet overview", "Vehicle status and location."],
  vehicles: ["Vehicles", "Vehicle register", "Current vehicle and rental records."],
  intelligence: ["Fleet intelligence", "Fleet data", "Query mileage, locations and incident status."],
  briefings: ["Morning briefing", "Mileage briefing", "Previous-day mileage and scheduled delivery."],
  injector: ["Telemetry studio", "Telemetry", "Inspect and control vehicle-data ingestion."],
  incidents: ["Incident centre", "Incidents", "Customer reports, quotations and approvals."],
};

const carSvg = (light = false) => `<svg viewBox="0 0 48 30" fill="none" aria-hidden="true"><path d="M8 19l4-8h18l7 8 5 2v4H5v-5l3-1z" fill="${light ? "#ffffff" : "#aabb9c"}"/><path d="M15 12h7v7H12l3-7zm10 0h4l6 7H25v-7z" fill="${light ? "#547e55" : "#e3ebdb"}"/><circle cx="13" cy="25" r="4" fill="${light ? "#ffffff" : "#526a43"}"/><circle cx="35" cy="25" r="4" fill="${light ? "#ffffff" : "#526a43"}"/><circle cx="13" cy="25" r="1.5" fill="${light ? "#547e55" : "#e3ebdb"}"/><circle cx="35" cy="25" r="1.5" fill="${light ? "#547e55" : "#e3ebdb"}"/></svg>`;

async function api(path, body) {
  const response = await fetch(path, {
    method: body === undefined ? "GET" : "POST",
    headers: body === undefined ? { Accept: "application/json" } : { Accept: "application/json", "Content-Type": "application/json", "X-Caldova-Request": "fleet-app" },
    body: body === undefined ? undefined : JSON.stringify(body),
    credentials: "same-origin",
  });
  const type = response.headers.get("content-type") || "";
  if (!type.includes("application/json")) throw new Error("Your session has expired. Reload and sign in with the configured operator account.");
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || `The request failed (${response.status}).`);
  return result;
}

function displayError(error) {
  $("error-banner").textContent = error.message;
  $("error-banner").hidden = false;
}

function toast(message) {
  $("toast").textContent = message;
  $("toast").hidden = false;
  clearTimeout(state.toastTimer);
  state.toastTimer = setTimeout(() => { $("toast").hidden = true; }, 6000);
}

function statusLabel(vehicle) {
  return { "on-hire": "On hire", incident: "Incident detected" }[vehicle.Status] || vehicle.Status;
}

function filteredVehicles() {
  return state.vehicles.filter((vehicle) =>
    (state.city === "all" || vehicle.City === state.city) &&
    (state.status === "all" || (state.status === "attention" ? Boolean(vehicle.Alert) : vehicle.Status === state.status)) &&
    `${vehicle.VehicleId} ${vehicle.Registration} ${vehicle.Make} ${vehicle.Model} ${vehicle.Colour || ""} ${vehicle.City}`.toLowerCase().includes(state.search)
  );
}

function vehicleRow(vehicle) {
  return `<button class="vehicle-row" data-vehicle="${escapeHtml(vehicle.VehicleId)}" aria-label="${escapeHtml(`${vehicle.Make} ${vehicle.Model}, ${vehicle.Registration}, ${statusLabel(vehicle)}`)}"><span class="car-icon">${carSvg()}</span><span class="vehicle-info"><span class="vehicle-name">${escapeHtml(vehicle.Make)} ${escapeHtml(vehicle.Model)}</span><span class="vehicle-reg">${escapeHtml(vehicle.Registration)} · ${escapeHtml(vehicle.VehicleId)}</span><span class="mini-status ${vehicle.Alert ? "attention" : ""}"><i></i>${escapeHtml(statusLabel(vehicle))}</span></span><span class="vehicle-right"><span class="vehicle-speed">${number(vehicle.SpeedKmh)} <small>km/h</small></span><span class="vehicle-city">${escapeHtml(vehicle.City)}</span></span></button>`;
}

function renderVehicles() {
  const vehicles = filteredVehicles();
  $("vehicle-list").innerHTML = vehicles.length ? vehicles.map(vehicleRow).join("") : '<p class="loading-copy">No vehicles match your filters.</p>';
  $("activity-count").textContent = vehicles.length;
  $("vehicles-table").innerHTML = state.vehicles.map((vehicle) => `<tr><td><button class="text-link" data-vehicle="${escapeHtml(vehicle.VehicleId)}">${escapeHtml(vehicle.Make)} ${escapeHtml(vehicle.Model)}<br>${escapeHtml(vehicle.VehicleId)}</button></td><td>${escapeHtml(vehicle.Registration)}</td><td>${escapeHtml(vehicle.City)}</td><td><span class="status-badge ${vehicle.Alert ? "attention" : ""}">${escapeHtml(statusLabel(vehicle))}</span></td><td>${number(vehicle.SpeedKmh)} km/h</td><td>${number(vehicle.OdometerKm)} km</td></tr>`).join("");
  $("telemetry-table").innerHTML = state.vehicles.map((vehicle) => `<tr><td>${escapeHtml(new Date(vehicle.Timestamp).toLocaleTimeString("en-GB"))}</td><td>${escapeHtml(vehicle.VehicleId)}</td><td>${Number(vehicle.Latitude).toFixed(5)}</td><td>${Number(vehicle.Longitude).toFixed(5)}</td><td>${number(vehicle.SpeedKmh, 1)} km/h</td><td>${number(vehicle.DistanceKm, 3)} km</td><td>${escapeHtml(statusLabel(vehicle))}</td><td title="${escapeHtml(vehicle.EventId)}">${escapeHtml(vehicle.EventId.slice(0, 12))}…</td></tr>`).join("");
  renderSelected();
  updateMap();
}

function renderMetrics(data) {
  const vehicles = state.vehicles;
  const active = vehicles.filter((vehicle) => vehicle.Status === "on-hire").length;
  const alerts = vehicles.filter((vehicle) => vehicle.Alert);
  $("total-fleet").textContent = number(vehicles.length);
  $("nav-count").textContent = vehicles.length;
  $("on-road").textContent = number(active);
  $("branch-count").textContent = data.branches.length;
  $("utilization").textContent = `${number(active / vehicles.length * 100)}%`;
  $("utilization-bar").style.width = `${active / vehicles.length * 100}%`;
  $("yesterday-km").innerHTML = `${number(data.yesterday.totalKm)}<small>km</small>`;
  $("mileage-period").textContent = new Date(`${data.yesterday.reportDate}T12:00:00Z`).toLocaleDateString("en-GB", { day: "numeric", month: "short" }) + " · Europe/Madrid";
  $("alert-count").textContent = alerts.length;
  $("alert-summary").textContent = `${alerts.length} ${alerts.length === 1 ? "vehicle" : "vehicles"} with an open incident`;
  const max = Math.max(...data.branches.map((branch) => branch.distanceKm), 1);
  $("branches").innerHTML = data.branches.map((branch) => `<div class="branch-row"><span class="branch-initial">${escapeHtml(branch.branchId)}</span><span class="branch-name">${escapeHtml(branch.city)}<span class="branch-count">${branch.vehicles} vehicles</span></span><span class="branch-track"><i style="width:${Math.max(branch.distanceKm / max * 100, 1)}%"></i></span><span class="branch-distance">${number(branch.distanceKm)}</span></div>`).join("");
  if (data.trend.length > 1) {
    const values = data.trend.map((day) => day.distanceKm);
    const low = Math.min(...values), range = Math.max(...values) - low || 1;
    const points = values.map((v, i) => `${i / (values.length - 1) * 120},${25 - (v - low) / range * 20}`).join(" ");
    $("mileage-sparkline").innerHTML = `<polyline points="${points}" fill="none" stroke="#9fbe83" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"/>`;
  }
}

async function refresh() {
  try {
    const data = await api("/api/fleet");
    const firstLoad = state.vehicles.length === 0;
    state.vehicles = data.vehicles;
    state.controls = data.injector;
    state.briefing = data.briefing;
    $("error-banner").hidden = true;
    const newest = Math.max(...data.vehicles.map((vehicle) => new Date(vehicle.Timestamp).getTime()));
    const age = (Date.now() - newest) / 1000;
    const fresh = age < 90;
    $("connection").classList.toggle("stale", !fresh);
    $("connection").innerHTML = `<i></i> ${fresh ? "Fabric connected" : "Telemetry delayed"}`;
    $("map-subtitle").textContent = `${data.vehicles.length} vehicles · ${new Date(newest).toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit", second: "2-digit" })} latest event`;
    $("last-updated").textContent = `Updated ${new Date(data.asOf).toLocaleTimeString("en-GB")}`;
    $("intelligence-freshness").textContent = data.lakehouse?.asOf ? `Copilot data last refreshed ${new Date(data.lakehouse.asOf).toLocaleString("en-GB")}. Live telemetry is read directly from Eventhouse.` : "Copilot data refresh has not completed.";
    $("injector-state").textContent = data.injector.paused ? "Telemetry paused" : "Telemetry flowing";
    $("toggle-injector").textContent = data.injector.paused ? "Resume telemetry" : "Pause telemetry";
    $("injector-checkpoint").textContent = `${number(data.injector.events || 0)} live events committed · Checkpoint ${data.injector.through || "not available"}`;
    $("briefing-date").textContent = `${data.yesterday.reportDate} · Europe/Madrid calendar day`;
    $("delivery-state").textContent = data.delivery.connected ? `Teams connected. ${data.delivery.lastSent ? `Last delivered ${new Date(data.delivery.lastSent).toLocaleString("en-GB")}.` : "Awaiting scheduled delivery."}` : "Open the fleet app in Teams to connect your personal chat.";
    renderMetrics(data);
    renderVehicles();
    if (firstLoad) fitMap();
    if (data.briefing && !state.generatingBriefing) renderBriefing(data.briefing);
  } catch (error) {
    $("connection").classList.add("stale");
    $("connection").innerHTML = "<i></i> Connection needs attention";
    displayError(error);
  } finally {
    state.refreshTimer = setTimeout(refresh, 15000);
  }
}

function initMap() {
  if (!window.atlas) throw new Error("Azure Maps could not load. Check access to atlas.microsoft.com.");
  state.map = new atlas.Map("fleet-map", {
    center: [-2.0, 54.0], zoom: 5.3, style: "grayscale_light",
    language: "en-GB", view: "Auto", showLogo: true,
    authOptions: {
      authType: "anonymous", clientId: state.config.mapsClientId,
      getToken: async (resolve, reject) => {
        try { resolve((await api("/api/maps/token")).token); }
        catch (error) { displayError(error); reject(error); }
      },
    },
  });
  state.map.events.add("ready", () => {
    state.mapReady = true;
    $("map-loading")?.remove();
    state.map.controls.add(new atlas.control.ZoomControl(), { position: "bottom-right" });
    state.routeSource = new atlas.source.DataSource();
    state.map.sources.add(state.routeSource);
    state.map.layers.add(new atlas.layer.LineLayer(state.routeSource, "vehicle-trail", { strokeColor: "#699755", strokeWidth: 3, strokeOpacity: .7 }));
    updateMap();
    fitMap();
  });
  state.map.events.add("error", (event) => {
    console.error("Azure Maps:", event.error);
    displayError(new Error("Azure Maps reported an error. Vehicle data remains available in the fleet register."));
  });
}

function updateMap() {
  if (!state.mapReady) return;
  const visible = new Set(filteredVehicles().map((vehicle) => vehicle.VehicleId));
  for (const vehicle of state.vehicles) {
    let marker = state.markers.get(vehicle.VehicleId);
    if (!marker) {
      const element = document.createElement("button");
      element.className = "map-vehicle";
      element.innerHTML = carSvg(true);
      element.title = `${vehicle.Make} ${vehicle.Model} · ${vehicle.Registration}`;
      element.setAttribute("aria-label", element.title);
      element.addEventListener("click", () => selectVehicle(vehicle.VehicleId));
      marker = new atlas.HtmlMarker({ htmlContent: element, position: [vehicle.Longitude, vehicle.Latitude], anchor: "center" });
      state.map.markers.add(marker);
      state.markers.set(vehicle.VehicleId, marker);
    }
    const element = marker.getOptions().htmlContent;
    element.classList.add("map-vehicle");
    for (const status of ["attention", "on-hire"]) {
      element.classList.toggle(status, status === (vehicle.Alert ? "attention" : vehicle.Status));
    }
    element.classList.toggle("selected", state.selected === vehicle.VehicleId);
    marker.setOptions({ position: [vehicle.Longitude, vehicle.Latitude], visible: visible.has(vehicle.VehicleId) });
  }
}

function fitMap() {
  if (!state.mapReady) return;
  const positions = filteredVehicles().map((vehicle) => [vehicle.Longitude, vehicle.Latitude]);
  if (positions.length) state.map.setCamera({ bounds: atlas.data.BoundingBox.fromPositions(positions), padding: 75, maxZoom: 12, type: "ease", duration: 750 });
}

async function selectVehicle(vehicleId) {
  state.selected = vehicleId;
  if (state.view !== "overview") setView("overview");
  const vehicle = state.vehicles.find((item) => item.VehicleId === vehicleId);
  if (!vehicle) return;
  if (state.mapReady) state.map.setCamera({ center: [vehicle.Longitude, vehicle.Latitude], zoom: 12, type: "ease", duration: 700 });
  renderSelected();
  updateMap();
  try {
    const data = await api(`/api/vehicles/${encodeURIComponent(vehicleId)}/history`);
    if (state.selected !== vehicleId || !state.routeSource) return;
    state.routeSource.clear();
    if (data.points.length > 1) state.routeSource.add(new atlas.data.Feature(new atlas.data.LineString(data.points.map((point) => [point.Longitude, point.Latitude]))));
  } catch (error) { toast(error.message); }
}

function renderSelected() {
  const vehicle = state.vehicles.find((item) => item.VehicleId === state.selected);
  $("selected-vehicle").hidden = !vehicle;
  if (!vehicle) return;
  $("selected-vehicle").innerHTML = `<span class="car-icon">${carSvg()}</span><span><b class="vehicle-name">${escapeHtml(vehicle.Make)} ${escapeHtml(vehicle.Model)}</b><span class="vehicle-reg">${escapeHtml(vehicle.Registration)} · ${escapeHtml(vehicle.City)}</span></span><span class="selected-metrics"><span><b>${number(vehicle.SpeedKmh)} km/h</b><small>Current speed</small></span><span><b>${number(vehicle.OdometerKm)} km</b><small>Odometer</small></span></span><button class="selected-close" id="clear-selection" aria-label="Clear vehicle selection">×</button>`;
  $("clear-selection").addEventListener("click", () => { state.selected = null; state.routeSource?.clear(); renderSelected(); updateMap(); });
  if (vehicle.Colour) $("selected-vehicle").querySelector(".vehicle-reg").textContent += ` · ${vehicle.Colour}`;
  if (vehicle.IncidentId) {
    const button = document.createElement("button");
    button.className = "button button-light";
    button.textContent = "Open incident";
    button.addEventListener("click", () => window.openIncident?.(vehicle.IncidentId));
    $("selected-vehicle").insertBefore(button, $("clear-selection"));
    delete state.simulating?.[vehicle.VehicleId];
  } else {
    state.simulating ||= {};
    const pending = state.simulating[vehicle.VehicleId];
    const button = document.createElement("button");
    button.className = "button button-dark";
    button.textContent = pending ? "Detecting impact…" : "Simulate incident";
    button.disabled = Boolean(pending);
    button.addEventListener("click", async () => {
      button.disabled = true; button.textContent = "Detecting impact…";
      state.simulating[vehicle.VehicleId] = true;
      try {
        await api("/api/telemetry/impact", { vehicle_id: vehicle.VehicleId, event_id: crypto.randomUUID() });
        toast(`Impact telemetry for ${vehicle.Registration} sent to Fabric. Waiting for Fabric to open the incident…`);
        for (let attempt = 0; attempt < 40; attempt++) {
          await new Promise((resolve) => setTimeout(resolve, 5000));
          const { cases } = await api("/api/incidents");
          const opened = cases.find((item) => item.vehicle_id === vehicle.VehicleId && !["closed", "not_an_incident"].includes(item.status));
          if (opened) {
            delete state.simulating[vehicle.VehicleId];
            vehicle.IncidentId = opened.id;
            toast(`Fabric opened incident ${opened.id} for ${vehicle.Registration}.`);
            await window.openIncident?.(opened.id);
            return;
          }
        }
        throw new Error("Fabric has not opened the incident yet. Check that the Fabric capacity is running.");
      } catch (error) {
        delete state.simulating[vehicle.VehicleId];
        button.disabled = false; button.textContent = "Simulate incident";
        toast(error.message);
      }
    });
    $("selected-vehicle").insertBefore(button, $("clear-selection"));
  }
}

function setView(view) {
  if (!titles[view]) return;
  state.view = view;
  document.querySelectorAll(".view-panel").forEach((panel) => { panel.hidden = panel.id !== `${view}-view`; });
  document.querySelectorAll(".nav-item[data-view]").forEach((item) => item.classList.toggle("active", item.dataset.view === view));
  $("page-name").textContent = titles[view][0];
  $("page-title").textContent = titles[view][1];
  $("page-description").textContent = titles[view][2];
  window.history.replaceState(null, "", view === "overview" ? "/" : `/#${view}`);
  if (view === "overview" && state.mapReady) requestAnimationFrame(() => state.map.resize());
}

function openCopilot() {
  $("copilot-drawer").hidden = false;
  $("drawer-backdrop").hidden = false;
  $("chat-input").focus();
}
function closeCopilot() {
  $("copilot-drawer").hidden = true;
  $("drawer-backdrop").hidden = true;
  $("open-copilot").focus();
}

function markdown(text) {
  const lines = escapeHtml(text).split("\n");
  let html = "", inTable = false;
  for (const line of lines) {
    if (/^\s*\|.*\|\s*$/.test(line)) {
      if (/^\s*\|[\s:|-]+\|\s*$/.test(line)) continue;
      if (!inTable) { html += '<div class="table-scroll"><table>'; inTable = true; }
      html += `<tr>${line.trim().slice(1, -1).split("|").map((cell) => `<td>${cell.trim()}</td>`).join("")}</tr>`;
    } else {
      if (inTable) { html += "</table></div>"; inTable = false; }
      if (/^#{1,3}\s/.test(line)) html += `<h3>${line.replace(/^#{1,3}\s/, "")}</h3>`;
      else if (/^\s*[-*]\s/.test(line)) html += `<div>• ${line.replace(/^\s*[-*]\s/, "")}</div>`;
      else html += `${line}<br>`;
    }
  }
  if (inTable) html += "</table></div>";
  return html.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>").replace(/`([^`]+)`/g, "<code>$1</code>");
}

async function sendQuestion(question) {
  if (state.busy || !question.trim()) return;
  openCopilot();
  state.busy = true;
  $("chat-send").disabled = true;
  $("chat-messages").querySelector(".chat-welcome")?.remove();
  const user = document.createElement("div");
  user.className = "chat-bubble user";
  user.textContent = question;
  $("chat-messages").append(user);
  const pending = document.createElement("div");
  pending.className = "chat-pending";
  pending.textContent = "Querying your Fabric data…";
  $("chat-messages").append(pending);
  $("chat-input").value = "";
  $("chat-messages").scrollTop = $("chat-messages").scrollHeight;
  try {
    const result = await api("/api/chat", { question, history: state.history.slice(-8) });
    const answer = document.createElement("div");
    answer.className = "chat-bubble assistant";
    answer.innerHTML = markdown(result.answer);
    const source = document.createElement("a");
    source.className = "source"; source.href = result.sourceUrl; source.target = "_blank"; source.rel = "noreferrer";
    source.textContent = `◈ Microsoft Fabric IQ · ${new Date(result.asOf).toLocaleTimeString("en-GB")} ↗`;
    answer.append(source);
    $("chat-messages").append(answer);
    state.history.push({ role: "user", content: question }, { role: "assistant", content: result.answer.slice(0, 12000) });
  } catch (error) {
    const failure = document.createElement("div");
    failure.className = "chat-bubble error";
    failure.textContent = error.message;
    $("chat-messages").append(failure);
  } finally {
    pending.remove(); state.busy = false; $("chat-send").disabled = false;
    $("chat-messages").scrollTop = $("chat-messages").scrollHeight;
  }
}

function renderBriefing(briefing) {
  $("briefing-content").innerHTML = markdown(briefing.text);
  $("briefing-date").textContent = `${briefing.reportDate} · ${number(briefing.totalKm, 1)} km · ${briefing.activeVehicles} vehicles on the road`;
}

async function briefingAction(send) {
  if (state.generatingBriefing) return;
  state.generatingBriefing = true;
  $("generate-briefing").disabled = $("send-briefing").disabled = true;
  $("briefing-status").textContent = send ? "Preparing and delivering the Fabric briefing to Teams…" : "The Fabric data agent is preparing your briefing…";
  try {
    const result = await api(send ? "/api/briefing/send" : "/api/briefing/generate", {});
    renderBriefing(result.briefing);
    $("briefing-status").textContent = send ? result.message : `Generated from Fabric at ${new Date(result.briefing.generatedAt).toLocaleTimeString("en-GB")}.`;
  } catch (error) { $("briefing-status").textContent = error.message; }
  finally { state.generatingBriefing = false; $("generate-briefing").disabled = $("send-briefing").disabled = false; }
}

function exportFleet() {
  const keys = ["VehicleId", "Registration", "Make", "Model", "City", "Status", "SpeedKmh", "OdometerKm", "Alert", "Timestamp"];
  const quote = (value) => `"${String(value ?? "").replace(/"/g, '""')}"`;
  const csv = [keys.join(","), ...state.vehicles.map((vehicle) => keys.map((key) => quote(vehicle[key])).join(","))].join("\r\n");
  const url = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" }));
  const anchor = document.createElement("a"); anchor.href = url; anchor.download = `fleet-${new Date().toISOString().slice(0, 10)}.csv`; anchor.click(); URL.revokeObjectURL(url);
}

async function start() {
  $("today").textContent = new Date().toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });
  document.addEventListener("click", (event) => {
    const navigation = event.target.closest("[data-view]");
    if (navigation) setView(navigation.dataset.view);
    const vehicle = event.target.closest("[data-vehicle]");
    if (vehicle) selectVehicle(vehicle.dataset.vehicle);
    const question = event.target.closest("[data-question]");
    if (question) sendQuestion(question.dataset.question);
  });
  document.querySelectorAll("[data-city]").forEach((button) => button.addEventListener("click", () => {
    state.city = button.dataset.city;
    document.querySelectorAll("[data-city]").forEach((item) => item.classList.toggle("active", item === button));
    renderVehicles(); fitMap();
  }));
  document.querySelectorAll("[data-status]").forEach((button) => button.addEventListener("click", () => {
    state.status = button.dataset.status;
    document.querySelectorAll("[data-status]").forEach((item) => item.classList.toggle("active", item === button));
    renderVehicles();
  }));
  $("fleet-search").addEventListener("input", (event) => { state.search = event.target.value.trim().toLowerCase(); renderVehicles(); });
  $("review-alerts").addEventListener("click", () => { document.querySelector('[data-status="attention"]').click(); });
  $("fit-map").addEventListener("click", fitMap);
  $("open-copilot").addEventListener("click", openCopilot);
  $("close-copilot").addEventListener("click", closeCopilot);
  $("drawer-backdrop").addEventListener("click", closeCopilot);
  document.addEventListener("keydown", (event) => { if (event.key === "Escape" && !$("copilot-drawer").hidden) closeCopilot(); });
  $("chat-form").addEventListener("submit", (event) => { event.preventDefault(); sendQuestion($("chat-input").value.trim()); });
  $("chat-input").addEventListener("keydown", (event) => { if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); sendQuestion(event.target.value.trim()); } });
  $("briefing-open").addEventListener("click", () => setView("briefings"));
  $("generate-briefing").addEventListener("click", () => briefingAction(false));
  $("send-briefing").addEventListener("click", () => briefingAction(true));
  $("export-fleet").addEventListener("click", exportFleet);
  $("toggle-injector").addEventListener("click", async () => {
    if (!state.controls) return;
    $("toggle-injector").disabled = true;
    try {
      const result = await api("/api/injector/control", { paused: !state.controls.paused });
      state.controls = result; toast(result.paused ? "Telemetry paused. Existing Fabric data is preserved." : "Telemetry resumed.");
      clearTimeout(state.refreshTimer); refresh();
    } catch (error) { toast(error.message); }
    finally { $("toggle-injector").disabled = false; }
  });
  setView(window.location.hash.slice(1).split("?")[0] || "overview");
  try {
    state.config = await api("/api/config");
    $("fabric-link").href = state.config.fabricUrl;
    $("ontology-link").href = state.config.ontologyUrl;
    $("teams-link").href = state.config.copilotUrl;
    $("teams-link").textContent = "Continue in Microsoft 365 Copilot ↗";
    initMap();
  } catch (error) { displayError(error); }
  await refresh();
}
start();
