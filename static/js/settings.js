// settings.exe: the app's own settings (preferences.py on the server).
// Ticking a box saves it straight away, so there's no Apply button. If
// saving fails, the box goes back to how it was.

import { addMenuAction, openTemplatePopup, showMessage } from "./desktop.js";

let saved = null; // the settings as the server last confirmed them: { keep_running: true, start_with_windows: false, ... }
let dialog = null; // the open settings.exe window, if there is one

export function initSettings() {
  const data = document.getElementById("settings-data");
  if (!data) return;
  saved = JSON.parse(data.textContent);
  addMenuAction("settings", openDialog);
}

function openDialog() {
  if (dialog?.isConnected) {
    dialog.querySelector("input")?.focus(); // already open: just point at it
    return;
  }
  dialog = openTemplatePopup("settings");
  const form = dialog.querySelector("[data-settings-form]");
  showInDialog(form);
  form.querySelector("input")?.focus();
  form.addEventListener("change", (event) => {
    if (event.target.type === "checkbox") save(form, event.target.name, event.target.checked);
  });
}

/** Tick each box to match the saved settings. */
function showInDialog(form) {
  for (const box of form.querySelectorAll("input[type=checkbox]")) {
    box.checked = Boolean(saved[box.name]);
  }
}

async function save(form, name, on) {
  const body = new FormData();
  body.set(name, on ? "1" : "0");
  try {
    const reply = await fetch("/settings", { method: "POST", body });
    const answer = await reply.json().catch(() => ({}));
    if (!reply.ok) throw answer;
    saved = answer;
  } catch (problem) {
    // The server explains itself with { title, message }; anything else gets a general note.
    showMessage({
      heading: problem?.title ?? "That didn't work",
      message: problem?.title ? problem.message : "The setting couldn't be saved. Try again in a moment.",
    });
  }
  showInDialog(form);
}
