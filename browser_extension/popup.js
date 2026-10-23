/**
 * SmartSort Companion - popup.
 *
 * The popup never talks to the native host directly; it asks the background
 * service worker, which owns the single code path for native messaging.
 */

const statusEl = document.getElementById("status");
const destinationEl = document.getElementById("destination");
const extensionIdEl = document.getElementById("extension-id");
const historyEl = document.getElementById("history");
const hintEl = document.getElementById("hint");
const testButton = document.getElementById("test");

const MESSAGES = {
  app_not_running: {
    text: "App not running",
    pill: "warn",
    hint: "Start SmartSort on your computer, then press Test connection.",
  },
  host_not_installed: {
    text: "Not installed",
    pill: "err",
    hint: "The native messaging host is not registered. Open SmartSort → About and click “Install browser integration”.",
  },
  host_error: {
    text: "Error",
    pill: "err",
    hint: "Chrome could not start the SmartSort host. See SmartSort → About → Diagnostics.",
  },
  extension_not_allowed: {
    text: "Not allowed",
    pill: "err",
    hint: "This extension ID is not in SmartSort’s allow list. Re-run “Install browser integration”.",
  },
};

function setPill(text, kind) {
  statusEl.textContent = text;
  statusEl.className = `pill ${kind || ""}`.trim();
}

function renderHistory(history) {
  historyEl.replaceChildren();
  if (!history || history.length === 0) {
    const item = document.createElement("li");
    item.className = "empty";
    item.textContent = "Nothing reported yet.";
    historyEl.appendChild(item);
    return;
  }
  history.slice(0, 5).forEach((entry) => {
    const row = document.createElement("li");

    const name = document.createElement("span");
    name.className = "name";
    name.textContent = entry.name || "(unnamed)";
    name.title = entry.name || "";

    const state = document.createElement("span");
    state.className = "state";
    state.textContent = describe(entry);

    row.append(name, state);
    historyEl.appendChild(row);
  });
}

function describe(entry) {
  if (entry.ok && entry.status === "organized") return "organized";
  if (entry.ok && entry.status === "skipped") return "skipped";
  if (entry.ok && entry.status === "duplicate") return "already handled";
  if (entry.type === "download_started") return "downloading";
  return entry.status || "failed";
}

function applyResponse(response, extensionId) {
  if (extensionId) extensionIdEl.textContent = extensionId;

  if (!response) {
    setPill("No response", "err");
    return;
  }

  if (response.ok && response.app === "SmartSort") {
    setPill(response.paused ? "Paused" : "Connected", response.paused ? "warn" : "ok");
    destinationEl.textContent = response.destination || "Not configured";
    hintEl.textContent = response.ready
      ? "Downloads are sorted automatically when they finish."
      : "Open SmartSort and choose a destination folder to enable sorting.";
    return;
  }

  const known = MESSAGES[response.error];
  setPill(known ? known.text : "Disconnected", known ? known.pill : "err");
  destinationEl.textContent = "—";
  hintEl.textContent = known ? known.hint : response.detail || "Unknown error.";
}

async function refresh() {
  testButton.disabled = true;
  setPill("Checking…", "");
  try {
    const result = await chrome.runtime.sendMessage({ type: "smartsort:status" });
    applyResponse(result && result.response, result && result.extensionId);
    renderHistory(result && result.history);
  } catch (error) {
    setPill("Disconnected", "err");
    hintEl.textContent = String(error && error.message ? error.message : error);
  } finally {
    testButton.disabled = false;
  }
}

testButton.addEventListener("click", refresh);
document.addEventListener("DOMContentLoaded", refresh);
refresh();
