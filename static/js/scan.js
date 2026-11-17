// Scanning: the scan form, the sync window with its progress bar, and the
// API key form.
//
// A scan is a single POST to /scan. The reply doesn't arrive all at once:
// the server sends one line of JSON per step, and this file reads each line
// as it comes in and moves the progress bar. That's why the bar is honest.

import { openWindow, showMessage } from "./desktop.js";

const LOST_CONNECTION = {
  title: "Lost the app",
  message: "The page couldn't reach its own server. Close the app and open it again.",
};

let ui = null; // the bits of the page this file touches, filled in by initScan
let running = null; // an AbortController while a scan is in progress, otherwise null

export function initScan() {
  const desktop = document.querySelector("[data-desktop]");
  const scanForm = document.querySelector("[data-scan-form]");
  if (!scanForm) return;

  ui = {
    desktop,
    scanForm,
    scanButton: scanForm.querySelector("[data-scan-button]"),
    keyForm: document.querySelector("[data-key-form]"),
    sync: document.querySelector("[data-sync]"),
    label: document.querySelector("[data-sync-label]"),
    bar: document.querySelector("[data-sync-bar]"),
    syncButton: document.querySelector("[data-sync-button]"),
  };

  scanForm.addEventListener("submit", (event) => {
    event.preventDefault();
    runScan(new FormData(scanForm));
  });
  ui.syncButton.addEventListener("click", () => {
    if (running) running.abort();
    else runScan(playersOnScreen({ force: true }));
  });
  ui.keyForm.addEventListener("submit", saveKey);
  document.querySelector("[data-key-toggle]")?.addEventListener("click", toggleKeyForm);

  // The server sets this when the saved data is getting old: refresh quietly in the background.
  if (desktop.dataset.autosync === "true") runScan(playersOnScreen({ force: false }), { quiet: true });
}

/** The form fields for "scan whoever is on screen right now". */
function playersOnScreen({ force }) {
  const form = new FormData();
  form.set("player", ui.desktop.dataset.player);
  if (ui.desktop.dataset.friend) form.set("friend", ui.desktop.dataset.friend);
  if (force) form.set("force", "1");
  return form;
}

// --- Running a scan --------------------------------------------------------

/** `quiet` is for the automatic refresh: no popups, and no reload unless something changed. */
async function runScan(form, { quiet = false } = {}) {
  if (running && quiet) return; // a background refresh never interrupts a scan
  running?.abort(); // but a scan the user asked for replaces whatever was going on
  const mine = new AbortController();
  running = mine;
  setBusy(true);
  showStep(0, 1, "Starting");

  let result = null;
  try {
    const reply = await fetch(ui.scanForm.action, { method: "POST", body: form, signal: mine.signal });
    if (!reply.ok) throw new Error(`The server answered ${reply.status}`);
    for await (const event of jsonLines(reply)) {
      if (event.label) showStep(event.step, event.steps, event.label);
      else result = event;
    }
  } catch (error) {
    result = error.name === "AbortError" ? { cancelled: true } : { error: LOST_CONNECTION };
  }

  if (running !== mine) return; // a newer scan took over while this one was stopping, the page is its now
  running = null;
  setBusy(false);
  finish(result ?? { error: LOST_CONNECTION }, quiet);
}

/**
 * The server sends one JSON object per line. This hands them out one at a
 * time, as soon as each line has fully arrived.
 */
async function* jsonLines(reply) {
  const reader = reply.body.pipeThrough(new TextDecoderStream()).getReader();
  let unfinished = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    const lines = (unfinished + value).split("\n");
    unfinished = lines.pop(); // the last piece may be half a line, keep it for the next round
    for (const line of lines) {
      if (line.trim()) yield JSON.parse(line);
    }
  }
  if (unfinished.trim()) yield JSON.parse(unfinished);
}

function finish(result, quiet) {
  if (result.cancelled) {
    ui.label.textContent = "Cancelled. Showing what was saved before.";
    return;
  }

  if (result.error) {
    ui.label.textContent = `Couldn't sync. ${result.error.title}.`;
    if (quiet) return; // don't greet people with an error popup just because they're offline
    if (result.error.code === "missing-key") showKeyForm(true);
    showMessage({
      heading: result.error.title,
      message: result.error.message,
      // If a friend's scan failed, the player's own dashboard is still worth showing.
      onClose: () => result.url && window.location.assign(result.url),
    });
    return;
  }

  const alreadyHere = result.url === window.location.pathname + window.location.search;
  if (quiet && alreadyHere && !result.gained) {
    ui.label.textContent = "Up to date. Checked just now.";
    return;
  }
  window.location.assign(result.url);
}

function showStep(step, steps, label) {
  const percent = Math.round((step / steps) * 100);
  ui.bar.style.setProperty("--progress", `${percent}%`);
  ui.bar.setAttribute("aria-valuenow", percent);
  ui.label.textContent = step ? `${label}… (${step} of ${steps})` : `${label}…`;
}

function setBusy(busy) {
  ui.sync.classList.toggle("is-syncing", busy);
  ui.syncButton.textContent = busy ? "Cancel" : "Sync now";
  ui.scanButton.disabled = busy;
  ui.scanButton.textContent = busy ? "Scanning…" : "Scan";
  if (!busy) {
    ui.bar.style.setProperty("--progress", "100%");
    ui.bar.setAttribute("aria-valuenow", 100);
  }
}

// --- The API key form ------------------------------------------------------

function showKeyForm(show) {
  ui.keyForm.hidden = !show;
  ui.scanForm.hidden = show;
  if (show) {
    openWindow("scan");
    ui.keyForm.querySelector("input").focus();
  }
}

function toggleKeyForm(event) {
  const link = event.currentTarget;
  showKeyForm(ui.keyForm.hidden);
  // Swap the link's two labels ("Change API key" / "Back to scanning").
  [link.textContent, link.dataset.otherLabel] = [link.dataset.otherLabel, link.textContent];
}

async function saveKey(event) {
  event.preventDefault();
  const button = ui.keyForm.querySelector("[data-key-button]");
  button.disabled = true;
  button.textContent = "Checking…";

  try {
    const reply = await fetch(ui.keyForm.action, { method: "POST", body: new FormData(ui.keyForm) });
    const answer = await reply.json();
    if (reply.ok) {
      showMessage({
        title: "setup.exe",
        color: "lilac",
        heading: "Key saved",
        message: "Steam accepted it. You can scan real profiles now.",
        onClose: () => window.location.reload(),
      });
    } else {
      showMessage({ heading: answer.title, message: answer.message });
    }
  } catch {
    showMessage({ heading: LOST_CONNECTION.title, message: LOST_CONNECTION.message });
  }

  button.disabled = false;
  button.textContent = "Save key";
}
