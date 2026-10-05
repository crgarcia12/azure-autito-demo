"use strict";
const $ = (id) => document.getElementById(id);
const caseId = location.pathname.split("/").pop();
const key = `caldova-report-${caseId}`;
const accessToken = location.hash.slice(1) || sessionStorage.getItem(key);
if (accessToken) { sessionStorage.setItem(key, accessToken); history.replaceState(null, "", location.pathname); }
let photoCount = 0, uploading = false;
async function request(path, method = "GET", body) {
  const headers = { "X-Incident-Token": accessToken || "", "X-Caldova-Request": "fleet-app", Accept: "application/json" };
  if (body && !(body instanceof FormData)) headers["Content-Type"] = "application/json";
  const response = await fetch(`/customer/${encodeURIComponent(caseId)}${path}`, { method, headers, body: body instanceof FormData ? body : body ? JSON.stringify(body) : undefined, credentials: "omit", referrerPolicy: "no-referrer" });
  if (!(response.headers.get("content-type") || "").includes("application/json")) throw new Error("This reporting link is not available. Contact rental support for assistance.");
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || "The report could not be processed.");
  return result;
}
function showError(error) { $("error").textContent = error.message; $("error").hidden = false; }
function complete(message) { $("content").hidden = true; $("loading").hidden = true; $("complete").hidden = false; $("confirmation").textContent = `${message} Your case reference is ${caseId}.`; }
$("photos").addEventListener("change", async (event) => {
  if (uploading) return;
  uploading = true; $("submit").disabled = true; $("photos").disabled = true;
  try {
    for (const file of event.target.files) {
      if (photoCount >= 6) throw new Error("Six photos have already been added.");
      if (file.size > 10 * 1024 * 1024) throw new Error("Each photo must be 10 MB or smaller.");
      const form = new FormData(); form.append("photo", file);
      $("upload-status").textContent = `Uploading photo ${photoCount + 1}...`;
      await request("/photos", "POST", form); photoCount++;
      const figure = document.createElement("figure"), image = document.createElement("img"), label = document.createElement("figcaption");
      const url = URL.createObjectURL(file); image.src = url; image.alt = `Uploaded incident photo ${photoCount}`; image.onload = () => URL.revokeObjectURL(url); label.textContent = `Photo ${photoCount} received`; figure.append(image, label); $("photo-list").append(figure);
    }
    $("upload-status").textContent = `${photoCount} photo${photoCount === 1 ? "" : "s"} uploaded securely.`;
  } catch (error) { showError(error); }
  finally { uploading = false; $("submit").disabled = false; $("photos").disabled = false; event.target.value = ""; }
});
$("report-form").addEventListener("submit", async (event) => {
  event.preventDefault(); if (uploading) return;
  if (!photoCount) { showError(new Error("Please add at least one photo.")); return; }
  $("submit").disabled = true; $("error").hidden = true;
  try {
    const result = await request("/submit", "POST", { description: $("description").value.trim(), customer_name: $("name").value.trim(), customer_email: $("email").value.trim(), consent_to_share_redacted: $("consent").checked });
    complete(result.status === "assistance_required" ? "Your report has been routed for assistance. In an emergency call 999." : "The claims team is reviewing your report.");
  } catch (error) { showError(error); $("submit").disabled = false; }
});
async function showWeather() {
  $("weather-context").hidden = false;
  try {
    const weather = await request("/weather");
    $("weather-status").textContent = `Web IQ search: ${weather.summary}`;
    $("weather-day").textContent = weather.day_summary;
    const checkedAt = new Date(weather.checked_at).toLocaleString("en-GB", { timeZone: "Europe/London", timeZoneName: "short" });
    $("weather-details").textContent = `${weather.station_name} · Search checked ${checkedAt}`;
    if (weather.source_url) {
      $("weather-source").href = weather.source_url;
      $("weather-source").hidden = false;
    }
  } catch (error) {
    $("weather-status").textContent = `Weather unavailable: ${error.message}`;
  }
}
request("").then((record) => {
  $("loading").hidden = true;
  if (["closed", "not_an_incident"].includes(record.status)) {
    complete("This report is closed. Use the latest reporting email if a replacement report was requested.");
    $("complete").querySelector("h1").textContent = "Report closed";
    return;
  }
  if (record.report_received) {
    complete(record.booking ? `Your repair is booked with ${record.booking.garage_name}. Expected return: ${record.booking.ready_by}.` : "Your report has been received by the claims team.");
    return;
  }
  photoCount = record.photo_count || 0;
  $("name").value = record.report_defaults.customer_name;
  $("email").value = record.report_defaults.customer_email;
  $("description").value = record.report_defaults.description;
  if (record.follow_up) $("content").querySelector(".intro").textContent = record.follow_up;
  if (photoCount) $("upload-status").textContent = `${photoCount} photo${photoCount === 1 ? "" : "s"} already received securely.`;
  $("content").hidden = false; const title = document.createElement("b"), info = document.createElement("small");
  title.textContent = `${record.vehicle.Make} ${record.vehicle.Model}${record.vehicle.Colour ? ` · ${record.vehicle.Colour}` : ""} · ${record.vehicle.Registration}`;
  info.textContent = `${caseId} · ${new Date(record.created_at).toLocaleString("en-GB")}`; $("vehicle").append(title, info);
  const place = document.createElement("small"); place.textContent = record.vehicle.City; $("vehicle").append(place);
  if (record.weather_supported) showWeather();
}).catch((error) => { $("loading").querySelector("p").textContent = error.message; });
