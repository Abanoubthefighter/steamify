// wallpaper.exe: changes the desktop wallpaper. A click shows the change
// straight away and saves it on the server (wallpaper.py), so there's no
// Apply button. If saving fails, the wallpaper goes back to how it was.

import { addMenuAction, openTemplatePopup, showMessage } from "./desktop.js";

const layer = document.querySelector("[data-wallpaper]");
let saved = null; // the wallpaper as the server last confirmed it
let dialog = null; // the open wallpaper.exe window, if there is one

export function initWallpaper() {
  if (!layer) return;
  saved = readLayer();
  addMenuAction("wallpaper", openDialog);
}

// --- The wallpaper layer -----------------------------------------------------

/** The wallpaper the page was drawn with: { pattern, dim, picture_url }. */
function readLayer() {
  const pattern = [...layer.classList].find((name) => name.startsWith("pattern--"));
  return {
    pattern: pattern?.slice("pattern--".length),
    dim: Number(layer.dataset.dim),
    picture_url: layer.querySelector("[data-wallpaper-picture]")?.getAttribute("src") ?? null,
  };
}

/** Draw a wallpaper: swap the pattern class, the dim level and the picture. */
function showOnDesktop({ pattern, dim, picture_url }) {
  layer.className = `wallpaper pattern--${pattern}`;
  layer.dataset.dim = dim;
  layer.style.setProperty("--wallpaper-dim", dim / 100);

  let picture = layer.querySelector("[data-wallpaper-picture]");
  if (!picture_url) {
    picture?.remove();
    return;
  }
  if (!picture) {
    picture = document.createElement("img");
    picture.className = "wallpaper__picture";
    picture.alt = "";
    picture.dataset.wallpaperPicture = "";
    layer.append(picture);
  }
  if (picture.getAttribute("src") !== picture_url) picture.src = picture_url;
}

// --- The window --------------------------------------------------------------

function openDialog() {
  if (dialog?.isConnected) {
    dialog.querySelector("input:checked")?.focus(); // already open: just point at it
    return;
  }
  dialog = openTemplatePopup("wallpaper");
  const form = dialog.querySelector("[data-wallpaper-form]");
  showInDialog(saved);
  form.querySelector("input:checked")?.focus();
  form.addEventListener("change", onChange);
  form.querySelector("[data-wallpaper-reset]").addEventListener("click", () => save("/wallpaper/reset"));
}

/** Tick the current choice in wallpaper.exe (if it's open). */
function showInDialog({ pattern, picture_url }) {
  if (!dialog?.isConnected) return;
  const form = dialog.querySelector("[data-wallpaper-form]");
  const pictureChoice = form.querySelector("[data-picture-choice]");
  pictureChoice.hidden = !picture_url;
  if (picture_url) form.querySelector("[data-picture-thumb]").src = picture_url;
  const radio = form.querySelector(`input[name="pattern"][value="${CSS.escape(pattern)}"]`);
  if (radio) radio.checked = true;
}

function onChange(event) {
  const input = event.target;
  if (input.name !== "pattern") return;
  const body = new FormData();
  body.set("pattern", input.value);
  showOnDesktop({ ...saved, pattern: input.value }); // show it now, save it in the background
  save("/wallpaper", body);
}

// --- Saving ------------------------------------------------------------------

async function save(url, body) {
  try {
    const reply = await fetch(url, { method: "POST", body });
    const answer = await reply.json().catch(() => ({}));
    if (!reply.ok) throw answer;
    saved = answer;
  } catch (problem) {
    // The server explains itself with { title, message }. Anything else
    // (no answer at all, say) gets a general note instead of raw error text.
    showMessage({
      heading: problem?.title ?? "That didn't work",
      message: problem?.title ? problem.message : "The wallpaper couldn't be saved. Try again in a moment.",
    });
  }
  showOnDesktop(saved);
  showInDialog(saved);
}
