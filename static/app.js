const state = {
  claims: [],
  selected: new Set(),
  activeSessionId: null,
  pollTimer: null,
};

const els = {
  claimCount: document.querySelector("#claim-count"),
  selectedCount: document.querySelector("#selected-count"),
  refreshBtn: document.querySelector("#refresh-btn"),
  callForm: document.querySelector("#call-form"),
  startCallBtn: document.querySelector("#start-call-btn"),
  payerPhone: document.querySelector("#payer-phone"),
  fromNumber: document.querySelector("#from-number"),
  initialKeypadDigits: document.querySelector("#initial-keypad-digits"),
  dryRun: document.querySelector("#dry-run"),
  message: document.querySelector("#message"),
  claimsBody: document.querySelector("#claims-body"),
  sessionStatus: document.querySelector("#session-status"),
  sessionSummary: document.querySelector("#session-summary"),
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

function selectedClaims() {
  return state.claims.filter((claim) => state.selected.has(claim.claim_id));
}

function syncCallForm() {
  const selected = selectedClaims();
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

function renderClaims() {
  els.claimsBody.innerHTML = "";
  for (const claim of state.claims) {
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

function renderSession(session) {
  state.activeSessionId = session.session_id;
  els.sessionStatus.textContent = session.status;
  els.sessionStatus.dataset.status = session.status;
  els.sessionSummary.innerHTML = `
    <div><span>Session</span><strong>${html(session.session_id)}</strong></div>
    <div><span>Call SID</span><strong>${html(session.call_sid || "")}</strong></div>
    <div><span>Payer</span><strong>${html(session.payer_name)}</strong></div>
    <div><span>Initial digits</span><strong>${html(session.initial_keypad_digits || "")}</strong></div>
    <div><span>Claims</span><strong>${html(session.claim_ids.join(", "))}</strong></div>
  `;

  els.transcript.innerHTML = "";
  for (const entry of session.transcript || []) {
    const item = document.createElement("div");
    item.className = `turn ${entry.role}`;
    item.innerHTML = `<span>${html(shortDate(entry.timestamp))} ${html(entry.role)}</span><p>${html(entry.text)}</p>`;
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

async function refreshAll() {
  setMessage("");
  await loadClaims();
  await loadSessions();
}

els.callForm.addEventListener("submit", startCall);
els.refreshBtn.addEventListener("click", () => refreshAll().catch((error) => setMessage(error.message, "error")));

refreshAll().catch((error) => setMessage(error.message, "error"));
