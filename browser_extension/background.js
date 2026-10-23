/**
 * SmartSort Companion - background service worker (Manifest V3).
 *
 * Responsibilities:
 *   - observe chrome.downloads lifecycle events,
 *   - forward download metadata to the SmartSort desktop app through the
 *     native messaging host,
 *   - answer status requests from the popup.
 *
 * Design notes
 * ------------
 * `chrome.runtime.sendNativeMessage` is used instead of a long-lived port on
 * purpose: an MV3 service worker is suspended after ~30s of inactivity, which
 * kills any open port and produces confusing "disconnected" states. One-shot
 * messages are stateless and always work, at the cost of starting the host
 * process per message.
 *
 * The extension never decides where a file goes and never touches the file
 * system. It only reports facts about a finished download.
 */

const HOST_NAME = "com.smartsort.host";
const PROTOCOL_VERSION = 1;
const PING_ALARM = "smartsort-ping";
const HISTORY_KEY = "smartsort:recent";
const MAX_HISTORY = 5;

// ---------------------------------------------------------------------------
// helpers
// ---------------------------------------------------------------------------

function detectBrowser() {
  const ua = (self.navigator && self.navigator.userAgent) || "";
  if (ua.includes("Edg/")) return "edge";
  if (ua.includes("OPR/")) return "opera";
  if (ua.includes("Brave")) return "brave";
  if (ua.includes("Vivaldi")) return "vivaldi";
  if (ua.includes("Chrome/")) return "chrome";
  return "unknown";
}

function toIso(value) {
  if (!value) return null;
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return null;
  return parsed.toISOString();
}

function buildDownloadPayload(item) {
  const payload = {
    id: String(item.id),
    state: item.state || null,
    exists: item.exists !== false,
  };

  if (item.filename) payload.filename = item.filename;
  if (item.url) payload.url = item.url;
  else if (item.finalUrl) payload.url = item.finalUrl;
  if (item.mime) payload.mime = item.mime;

  const size =
    typeof item.fileSize === "number" && item.fileSize > 0
      ? item.fileSize
      : typeof item.totalBytes === "number"
        ? item.totalBytes
        : null;
  if (size !== null && size >= 0) payload.totalBytes = size;

  const completed = toIso(item.endTime);
  if (completed) payload.completedAt = completed;

  if (item.danger) payload.danger = String(item.danger);

  return payload;
}

function buildMessage(type, item) {
  return {
    type,
    protocolVersion: PROTOCOL_VERSION,
    browser: detectBrowser(),
    extensionId: chrome.runtime.id,
    download: buildDownloadPayload(item),
  };
}

/**
 * Send a message to the desktop app. Never throws: every failure is turned
 * into a structured result so the caller can show something useful.
 */
async function sendNative(message) {
  try {
    const response = await chrome.runtime.sendNativeMessage(HOST_NAME, message);
    if (!response) {
      return { ok: false, error: "empty_response" };
    }
    return response;
  } catch (error) {
    const text = String(error && error.message ? error.message : error);
    // Chrome reports a missing host with a very specific message.
    const missingHost = /not found|Access to the specified native messaging host/i.test(text);
    return {
      ok: false,
      error: missingHost ? "host_not_installed" : "host_error",
      detail: text,
    };
  }
}

async function recordHistory(entry) {
  try {
    const stored = await chrome.storage.local.get(HISTORY_KEY);
    const list = Array.isArray(stored[HISTORY_KEY]) ? stored[HISTORY_KEY] : [];
    list.unshift(entry);
    await chrome.storage.local.set({ [HISTORY_KEY]: list.slice(0, MAX_HISTORY) });
  } catch (error) {
    console.warn("SmartSort: could not store history", error);
  }
}

async function report(type, item) {
  const message = buildMessage(type, item);
  const response = await sendNative(message);

  const name = item.filename ? item.filename.split(/[\\/]/).pop() : String(item.id);
  await recordHistory({
    at: new Date().toISOString(),
    name,
    type,
    ok: Boolean(response && response.ok),
    status: response && (response.status || response.error),
  });
  return response;
}

// ---------------------------------------------------------------------------
// download events
// ---------------------------------------------------------------------------

chrome.downloads.onCreated.addListener(async (item) => {
  // Announced so the desktop app knows a download started; it is never acted
  // on until the download completes.
  try {
    await report("download_started", item);
  } catch (error) {
    console.warn("SmartSort: onCreated failed", error);
  }
});

chrome.downloads.onChanged.addListener(async (delta) => {
  if (!delta || !delta.state) return;
  const state = delta.state.current;
  if (state !== "complete" && state !== "interrupted") return;

  try {
    const matches = await chrome.downloads.search({ id: delta.id });
    const item = matches && matches[0];
    if (!item) return;

    if (state === "complete") {
      await report("download_completed", item);
      return;
    }

    const cancelled =
      item.error === "USER_CANCELED" ||
      item.error === "USER_SHUTDOWN" ||
      delta.error && delta.error.current === "USER_CANCELED";
    await report(cancelled ? "download_cancelled" : "download_interrupted", item);
  } catch (error) {
    console.warn("SmartSort: onChanged failed", error);
  }
});

// ---------------------------------------------------------------------------
// popup / status
// ---------------------------------------------------------------------------

chrome.runtime.onMessage.addListener((request, _sender, sendResponse) => {
  if (!request || request.type !== "smartsort:status") return undefined;

  (async () => {
    const response = await sendNative({
      type: "ping",
      protocolVersion: PROTOCOL_VERSION,
      browser: detectBrowser(),
      extensionId: chrome.runtime.id,
    });
    const stored = await chrome.storage.local.get(HISTORY_KEY);
    sendResponse({
      response,
      history: Array.isArray(stored[HISTORY_KEY]) ? stored[HISTORY_KEY] : [],
      extensionId: chrome.runtime.id,
    });
  })();

  return true; // keep the message channel open for the async response
});

// ---------------------------------------------------------------------------
// lifecycle
// ---------------------------------------------------------------------------

chrome.runtime.onInstalled.addListener(async () => {
  await chrome.alarms.create(PING_ALARM, { periodInMinutes: 5 });
  // A first ping tells the desktop app which extension is talking to it.
  await sendNative({
    type: "hello",
    protocolVersion: PROTOCOL_VERSION,
    browser: detectBrowser(),
    extensionId: chrome.runtime.id,
  });
});

chrome.runtime.onStartup.addListener(async () => {
  await chrome.alarms.create(PING_ALARM, { periodInMinutes: 5 });
});

chrome.alarms.onAlarm.addListener(async (alarm) => {
  if (alarm.name !== PING_ALARM) return;
  await sendNative({
    type: "ping",
    protocolVersion: PROTOCOL_VERSION,
    browser: detectBrowser(),
    extensionId: chrome.runtime.id,
  });
});
