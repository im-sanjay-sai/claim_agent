const state = {
  claims: [],
  selected: new Set(),
  activeSessionId: null,
  ediSource: null,
  ediSamples: [],
  config: null,
  pollTimer: null,
};

const els = {
  tabBtns: document.querySelectorAll("[data-tab-target]"),
  tabPanels: document.querySelectorAll(".tab-panel"),
  claimCount: document.querySelector("#claim-count"),
  selectedCount: document.querySelector("#selected-count"),
  refreshBtn: document.querySelector("#refresh-btn"),
  callForm: document.querySelector("#call-form"),
  startCallBtn: document.querySelector("#start-call-btn"),
  ediImportForm: document.querySelector("#edi-import-form"),
  ediSampleSelect: document.querySelector("#edi-sample-select"),
  ediLoadSampleBtn: document.querySelector("#edi-load-sample-btn"),
  ediSaveBtn: document.querySelector("#edi-save-btn"),
  ediSourcePill: document.querySelector("#edi-source-pill"),
  ediExtractedCount: document.querySelector("#edi-extracted-count"),
  ediSegmentCount: document.querySelector("#edi-segment-count"),
  ediFile: document.querySelector("#edi-file"),
  ediPayerPhone: document.querySelector("#edi-payer-phone"),
  ediPayerName: document.querySelector("#edi-payer-name"),
  ediImportBtn: document.querySelector("#edi-import-btn"),
  ediMessage: document.querySelector("#edi-message"),
  ediPreview: document.querySelector("#edi-preview"),
  ediJson: document.querySelector("#edi-json"),
  ediRaw: document.querySelector("#edi-raw"),
  payerName: document.querySelector("#payer-name"),
  payerPhone: document.querySelector("#payer-phone"),
  fromNumber: document.querySelector("#from-number"),
  initialKeypadDigits: document.querySelector("#initial-keypad-digits"),
  dryRun: document.querySelector("#dry-run"),
  message: document.querySelector("#message"),
  claimsBody: document.querySelector("#claims-body"),
  sessionStatus: document.querySelector("#session-status"),
  sessionSummary: document.querySelector("#session-summary"),
  recordings: document.querySelector("#recordings"),
  transcript: document.querySelector("#transcript"),
  results: document.querySelector("#results"),
  history: document.querySelector("#history"),
};

function money(value) {
  if (value === null || value === undefined || value === "") return "";
  return Number(value).toLocaleString(undefined, { style: "currency", currency: "USD" });
}

function shortDate(value) {
  if (!value) return "";
  return String(value).slice(0, 10);
}

function duration(value) {
  if (!value) return "";
  const minutes = Math.floor(Number(value) / 60);
  const seconds = Math.round(Number(value) % 60).toString().padStart(2, "0");
  return `${minutes}:${seconds}`;
}

function html(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function setMessage(text, kind = "") {
  els.message.textContent = text;
  els.message.className = `message ${kind}`;
}

function setEdiMessage(text, kind = "") {
  els.ediMessage.textContent = text;
  els.ediMessage.className = `message ${kind}`;
}

function showTab(tabId) {
  els.tabPanels.forEach((panel) => {
    panel.classList.toggle("active", panel.id === tabId);
  });
  els.tabBtns.forEach((button) => {
    button.classList.toggle("active", button.dataset.tabTarget === tabId);
  });
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(data.detail || `Request failed: ${response.status}`);
  }
  return data;
}

async function apiForm(path, formData) {
  const response = await fetch(path, {
    method: "POST",
    body: formData,
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(data.detail || `Request failed: ${response.status}`);
  }
  return data;
}

function selectedClaims() {
  return state.claims.filter((claim) => state.selected.has(claim.claim_id));
}

function claimPatientKey(claim) {
  return [
    claim.member_id || "",
    claim.patient_dob || "",
    String(claim.patient_last_name || "").toUpperCase(),
    String(claim.patient_first_name || "").toUpperCase(),
  ].join("|");
}

function groupedClaims(claims) {
  const groups = [];
  const byKey = new Map();
  for (const claim of claims) {
    const key = claimPatientKey(claim);
    if (!byKey.has(key)) {
      const group = {
        key,
        patientName: `${claim.patient_first_name || ""} ${claim.patient_last_name || ""}`.trim() || "Unknown patient",
        patientDob: claim.patient_dob || "",
        memberId: claim.member_id || "",
        claims: [],
      };
      byKey.set(key, group);
      groups.push(group);
    }
    byKey.get(key).claims.push(claim);
  }
  return groups;
}

function ediOverrideParams() {
  const params = new URLSearchParams();
  if (els.ediPayerPhone.value.trim()) {
    params.set("payer_phone", els.ediPayerPhone.value.trim());
  }
  if (els.ediPayerName.value.trim()) {
    params.set("payer_name", els.ediPayerName.value.trim());
  }
  return params;
}

function ediOverrideFormData() {
  const formData = new FormData();
  if (els.ediPayerPhone.value.trim()) {
    formData.append("payer_phone", els.ediPayerPhone.value.trim());
  }
  if (els.ediPayerName.value.trim()) {
    formData.append("payer_name", els.ediPayerName.value.trim());
  }
  return formData;
}

function syncCallForm() {
  const selected = selectedClaims();
  if (!els.payerName.value && selected[0]?.payer_name) {
    els.payerName.value = selected[0].payer_name;
  }
  if (!els.payerPhone.value && selected[0]?.payer_phone) {
    els.payerPhone.value = selected[0].payer_phone;
  }
  els.selectedCount.textContent = `${state.selected.size} selected`;
  els.startCallBtn.disabled = state.selected.size === 0 || state.selected.size > 3;

  document.querySelectorAll("[data-claim-checkbox]").forEach((checkbox) => {
    const checked = state.selected.has(checkbox.value);
    checkbox.checked = checked;
    checkbox.disabled = !checked && state.selected.size >= 3;
  });
}

function applyCallDefaults() {
  const defaults = state.config?.default_call || {};
  if (!els.payerName.value && defaults.payer_name) {
    els.payerName.value = defaults.payer_name;
  }
  if (!els.payerPhone.value && defaults.payer_phone) {
    els.payerPhone.value = defaults.payer_phone;
  }
  if (!els.fromNumber.value && defaults.from_number) {
    els.fromNumber.value = defaults.from_number;
  }
}

function renderClaims() {
  els.claimsBody.innerHTML = "";
  for (const group of groupedClaims(state.claims)) {
    const groupRow = document.createElement("tr");
    groupRow.className = "claim-group-row";
    groupRow.innerHTML = `
      <td colspan="7">
        <strong>${html(group.patientName)}</strong>
        <span>${html(group.claims.length)} claim${group.claims.length === 1 ? "" : "s"} - DOB ${html(group.patientDob || "")} - Member ${html(group.memberId || "")}</span>
      </td>
    `;
    els.claimsBody.appendChild(groupRow);

    for (const claim of group.claims) {
      const row = document.createElement("tr");
      row.innerHTML = `
        <td><input data-claim-checkbox type="checkbox" value="${html(claim.claim_id)}" aria-label="Select ${html(claim.claim_id)}"></td>
        <td><strong>${html(claim.claim_id)}</strong><span>${html(claim.payer_name || "")}</span></td>
        <td>${html(claim.patient_first_name)} ${html(claim.patient_last_name)}</td>
        <td>${html(claim.date_of_service || "")}</td>
        <td>${html(claim.member_id || "")}</td>
        <td>${html(claim.provider_npi || "")}</td>
        <td>${money(claim.billed_amount)}</td>
      `;
      els.claimsBody.appendChild(row);
    }
  }

  document.querySelectorAll("[data-claim-checkbox]").forEach((checkbox) => {
    checkbox.addEventListener("change", (event) => {
      const claimId = event.target.value;
      if (event.target.checked) {
        if (state.selected.size >= 3) {
          event.target.checked = false;
          setMessage("Select up to 3 claims.", "warn");
          return;
        }
        state.selected.add(claimId);
      } else {
        state.selected.delete(claimId);
      }
      syncCallForm();
    });
  });
  syncCallForm();
}

function renderImportPreview(data) {
  const people = data.people || [];
  const claims = data.claims || [];
  const warnings = data.warnings || [];
  const sourceLabel = data.file_name || "Uploaded EDI";

  els.ediSourcePill.textContent = sourceLabel;
  els.ediExtractedCount.textContent = `${claims.length} parsed`;
  els.ediSegmentCount.textContent = `${data.segment_count || 0} segments`;
  els.ediRaw.textContent = data.raw_text || "";
  els.ediJson.textContent = JSON.stringify(
    {
      file_name: data.file_name,
      parsed_count: data.parsed_count,
      people,
      claims,
      warnings,
    },
    null,
    2
  );
  els.ediSaveBtn.disabled = claims.length === 0;

  if (!people.length) {
    els.ediPreview.innerHTML = `<p class="empty">No claims extracted yet.</p>`;
    return;
  }

  els.ediPreview.innerHTML = `
    <div class="import-summary">
      <strong>${html(data.parsed_count)} parsed</strong>
      <span>${html(data.segment_count || 0)} EDI segments</span>
    </div>
  `;

  if (warnings.length) {
    const warning = document.createElement("div");
    warning.className = "import-warning";
    warning.textContent = warnings.join(" ");
    els.ediPreview.appendChild(warning);
  }

  for (const person of people) {
    const item = document.createElement("section");
    item.className = "import-person";
    const claimRows = (person.claims || [])
      .map(
        (claim) => `
          <li>
            <strong>${html(claim.claim_id)}</strong>
            <span>${html(claim.date_of_service || "")} - ${money(claim.billed_amount)} - ${html(claim.payer_name || "")}</span>
          </li>
        `
      )
      .join("");
    item.innerHTML = `
      <header>
        <strong>${html(person.patient_name || "Unknown patient")}</strong>
        <span>DOB ${html(person.patient_dob || "")} - Member ${html(person.member_id || "")}</span>
      </header>
      <ul>${claimRows}</ul>
    `;
    els.ediPreview.appendChild(item);
  }
}

function clearEdiPreview() {
  state.ediSource = null;
  els.ediSourcePill.textContent = "No file loaded";
  els.ediExtractedCount.textContent = "0 parsed";
  els.ediSegmentCount.textContent = "0 segments";
  els.ediPreview.innerHTML = `<p class="empty">Load a sample or parse an upload.</p>`;
  els.ediJson.textContent = "";
  els.ediRaw.textContent = "";
  els.ediSaveBtn.disabled = true;
}

function renderSession(session) {
  state.activeSessionId = session.session_id;
  const recordings = session.recordings || [];
  const recordingsById = new Map(recordings.map((recording) => [recording.recording_id, recording]));
  els.sessionStatus.textContent = session.status;
  els.sessionStatus.dataset.status = session.status;
  els.sessionSummary.innerHTML = `
    <div><span>Session</span><strong>${html(session.session_id)}</strong></div>
    <div><span>Call SID</span><strong>${html(session.call_sid || "")}</strong></div>
    <div><span>Payer</span><strong>${html(session.payer_name)}</strong></div>
    <div><span>Initial digits</span><strong>${html(session.initial_keypad_digits || "")}</strong></div>
    <div><span>Claims</span><strong>${html(session.claim_ids.join(", "))}</strong></div>
    <div><span>Recordings</span><strong>${html(recordings.length)}</strong></div>
  `;

  els.recordings.innerHTML = "";
  if (recordings.length) {
    for (const recording of recordings) {
      const item = document.createElement("article");
      item.className = `recording-item ${recording.track}`;
      item.innerHTML = `
        <div>
          <strong>${html(recording.label)}</strong>
          <span>${html(recording.track)} - ${html(duration(recording.duration_seconds))} - ${html(recording.sample_rate)} Hz</span>
        </div>
        <audio controls preload="metadata" src="${html(recording.url)}"></audio>
        <a class="recording-download" href="${html(recording.url)}" download="${html(recording.file_name)}">Download</a>
      `;
      els.recordings.appendChild(item);
    }
  }

  els.transcript.innerHTML = "";
  for (const entry of session.transcript || []) {
    const item = document.createElement("div");
    item.className = `turn ${entry.role}`;
    const recording = entry.recording_id ? recordingsById.get(entry.recording_id) : null;
    item.innerHTML = `
      <span>${html(shortDate(entry.timestamp))} ${html(entry.role)}</span>
      <p>${html(entry.text)}</p>
      ${
        recording
          ? `<audio class="transcript-audio" controls preload="metadata" src="${html(recording.url)}"></audio>`
          : ""
      }
    `;
    els.transcript.appendChild(item);
  }

  els.results.innerHTML = "";
  if (!session.results?.length) {
    els.results.innerHTML = `<p class="empty">No structured results yet.</p>`;
  } else {
    for (const result of session.results) {
      const item = document.createElement("article");
      item.className = "result-item";
      item.innerHTML = `
        <header>
          <strong>${html(result.claim_id)}</strong>
          <span>${html(result.status)}</span>
        </header>
        <dl>
          <div><dt>Payer claim</dt><dd>${html(result.payer_claim_number || "")}</dd></div>
          <div><dt>Allowed</dt><dd>${money(result.allowed_amount)}</dd></div>
          <div><dt>Paid</dt><dd>${money(result.paid_amount)}</dd></div>
          <div><dt>Patient resp.</dt><dd>${money(result.patient_responsibility)}</dd></div>
          <div><dt>Denials</dt><dd>${html((result.denial_codes || []).join(", "))}</dd></div>
          <div><dt>Payment date</dt><dd>${html(result.payment_date || "")}</dd></div>
          <div><dt>Check/EFT</dt><dd>${html(result.check_or_eft_number || "")}</dd></div>
          <div><dt>Rep</dt><dd>${html(result.rep_name || "")}</dd></div>
          <div><dt>Reference</dt><dd>${html(result.reference_number || "")}</dd></div>
        </dl>
      `;
      els.results.appendChild(item);
    }
  }
}

function renderHistory(sessions) {
  els.history.innerHTML = "";
  for (const session of sessions.slice(0, 8)) {
    const button = document.createElement("button");
    button.className = "history-item";
    button.type = "button";
    button.innerHTML = `
      <strong>${html(session.payer_name)}</strong>
      <span>${html(session.status)} - ${html(session.claim_ids.join(", "))}</span>
    `;
    button.addEventListener("click", () => loadSession(session.session_id));
    els.history.appendChild(button);
  }
}

async function loadClaims() {
  const data = await api("/api/claims");
  state.claims = data.claims;
  els.claimCount.textContent = `${state.claims.length} parsed claims`;
  renderClaims();
}

async function loadConfig() {
  state.config = await api("/api/config");
  applyCallDefaults();
}

async function loadSessions() {
  const data = await api("/api/calls");
  renderHistory(data.sessions || []);
  if (!state.activeSessionId && data.sessions?.[0]) {
    renderSession(data.sessions[0]);
  }
}

async function loadSession(sessionId) {
  const session = await api(`/api/calls/${sessionId}`);
  renderSession(session);
}

async function loadEdiSamples() {
  const data = await api("/api/edi/samples");
  state.ediSamples = data.samples || [];
  els.ediSampleSelect.innerHTML = "";

  if (!state.ediSamples.length) {
    const option = document.createElement("option");
    option.value = "";
    option.textContent = "No samples found";
    els.ediSampleSelect.appendChild(option);
    els.ediLoadSampleBtn.disabled = true;
    return;
  }

  for (const sample of state.ediSamples) {
    const option = document.createElement("option");
    option.value = sample.file_name;
    option.textContent = `${sample.file_name} (${sample.size_bytes} bytes)`;
    els.ediSampleSelect.appendChild(option);
  }
  els.ediLoadSampleBtn.disabled = false;
}

async function loadSelectedEdiSample() {
  const fileName = els.ediSampleSelect.value;
  if (!fileName) {
    setEdiMessage("Choose a sample EDI file.", "error");
    return;
  }

  const params = ediOverrideParams();
  const suffix = params.toString() ? `?${params.toString()}` : "";
  els.ediLoadSampleBtn.disabled = true;
  setEdiMessage("Loading sample EDI...");
  try {
    const response = await api(`/api/edi/samples/${encodeURIComponent(fileName)}${suffix}`);
    state.ediSource = { type: "sample", fileName };
    renderImportPreview(response);
    setEdiMessage(`Loaded ${response.parsed_count} claims from ${fileName}.`, "ok");
  } catch (error) {
    setEdiMessage(error.message, "error");
  } finally {
    els.ediLoadSampleBtn.disabled = false;
  }
}

function startPolling(sessionId) {
  clearInterval(state.pollTimer);
  state.pollTimer = setInterval(() => {
    loadSession(sessionId).catch((error) => setMessage(error.message, "error"));
    loadSessions().catch(() => {});
  }, 2000);
}

async function startCall(event) {
  event.preventDefault();
  const payload = {
    payer_name: els.payerName.value.trim() || null,
    payer_phone: els.payerPhone.value.trim(),
    from_number: els.fromNumber.value.trim(),
    initial_keypad_digits: els.initialKeypadDigits.value.trim() || null,
    claim_ids: [...state.selected],
    dry_run: els.dryRun.checked,
  };

  els.startCallBtn.disabled = true;
  setMessage("Starting call...");
  try {
    const response = await api("/api/calls", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    setMessage(response.call_sid ? `Call started: ${response.call_sid}` : "Dry run session created.", "ok");
    await loadSession(response.session_id);
    await loadSessions();
    startPolling(response.session_id);
  } catch (error) {
    setMessage(error.message, "error");
  } finally {
    syncCallForm();
  }
}

async function importEdi(event) {
  event.preventDefault();
  const file = els.ediFile.files?.[0];
  if (!file) {
    setEdiMessage("Choose a raw 837 EDI file.", "error");
    return;
  }

  const formData = new FormData();
  formData.append("file", file);
  for (const [key, value] of ediOverrideFormData().entries()) {
    formData.append(key, value);
  }

  els.ediImportBtn.disabled = true;
  setEdiMessage("Parsing EDI...");
  try {
    const response = await apiForm("/api/edi/parse", formData);
    state.ediSource = { type: "upload", file };
    renderImportPreview(response);
    setEdiMessage(`Parsed ${response.parsed_count} claims from ${file.name}.`, "ok");
  } catch (error) {
    setEdiMessage(error.message, "error");
  } finally {
    els.ediImportBtn.disabled = false;
  }
}

async function saveEdiExtraction() {
  if (!state.ediSource) {
    setEdiMessage("Load or parse an EDI file first.", "error");
    return;
  }

  const formData = ediOverrideFormData();
  let path = "";
  if (state.ediSource.type === "sample") {
    path = `/api/edi/samples/${encodeURIComponent(state.ediSource.fileName)}/import`;
  } else {
    formData.append("file", state.ediSource.file);
    path = "/api/claims/import-edi";
  }

  els.ediSaveBtn.disabled = true;
  setEdiMessage("Saving extracted claims...");
  try {
    const response = await apiForm(path, formData);
    renderImportPreview(response);
    setEdiMessage(
      `Saved ${response.parsed_count} claims: ${response.created} new, ${response.updated} updated.`,
      "ok"
    );
    await loadClaims();
    showTab("claims-view");
  } catch (error) {
    setEdiMessage(error.message, "error");
  } finally {
    els.ediSaveBtn.disabled = false;
  }
}

async function refreshAll() {
  setMessage("");
  setEdiMessage("");
  await loadConfig();
  await loadEdiSamples();
  await loadClaims();
  await loadSessions();
  if (!state.ediSource) {
    clearEdiPreview();
  }
}

els.tabBtns.forEach((button) => {
  button.addEventListener("click", () => showTab(button.dataset.tabTarget));
});
els.callForm.addEventListener("submit", startCall);
els.ediImportForm.addEventListener("submit", importEdi);
els.ediLoadSampleBtn.addEventListener("click", loadSelectedEdiSample);
els.ediSaveBtn.addEventListener("click", saveEdiExtraction);
els.refreshBtn.addEventListener("click", () => refreshAll().catch((error) => setMessage(error.message, "error")));

refreshAll().catch((error) => setMessage(error.message, "error"));
