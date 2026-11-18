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
  form.addEventListener("input", onSlide);
  form.querySelector("[data-picture-pick]").addEventListener("click", () => {
    form.querySelector("[data-picture-file]").click(); // opens Windows' own file picker
  });
  form.querySelector("[data-wallpaper-reset]").addEventListener("click", () => save("/wallpaper/reset"));
}

/** Make wallpaper.exe (if it's open) match a wallpaper. */
function showInDialog({ pattern, dim, picture_url }) {
  if (!dialog?.isConnected) return;
  const form = dialog.querySelector("[data-wallpaper-form]");

  form.querySelector("[data-picture-choice]").hidden = !picture_url;
  if (picture_url) form.querySelector("[data-picture-thumb]").src = picture_url;
  const radio = form.querySelector(`input[name="pattern"][value="${CSS.escape(pattern)}"]`);
  if (radio) radio.checked = true;

  // The slider only means something for a picture; patterns are never dimmed.
  const slider = form.elements.dim;
  slider.value = dim;
  slider.disabled = pattern !== "picture";
  form.querySelector("[data-dim-note]").hidden = !slider.disabled;
  showDimValue(dim);
}

function showDimValue(dim) {
  dialog.querySelector("[data-dim-value]").textContent = `${dim}%`;
}

function onChange(event) {
  const input = event.target;
  if ("pictureFile" in input.dataset) {
    importPicture(input);
  } else if (input.name === "pattern" || input.name === "dim") {
    const body = new FormData();
    body.set(input.name, input.value);
    showOnDesktop({ ...saved, [input.name]: input.value }); // show it now, save it in the background
    save("/wallpaper", body);
  }
}

/** While the slider is dragged, dim the picture live. It's saved when it's let go (onChange). */
function onSlide(event) {
  if (event.target.name !== "dim") return;
  const dim = Number(event.target.value);
  showOnDesktop({ ...saved, dim });
  showDimValue(dim);
}

async function importPicture(input) {
  const file = input.files[0];
  input.value = ""; // so picking the same file again still counts as a change
  if (!file) return;

  const maxBytes = Number(input.form.dataset.maxBytes);
  if (file.size > maxBytes) {
    showMessage({ heading: "That picture is too big", message: `Pick one under ${Math.round(maxBytes / 2 ** 20)} MB.` });
    return;
  }
  // Check it really opens as a picture before sending it, so a broken file
  // gives a clear message instead of an empty desktop.
  try {
    (await createImageBitmap(file)).close();
  } catch {
    showMessage({ heading: "That's not a picture the app can use", message: "Pick a PNG, JPG or WebP image." });
    return;
  }

  const button = input.form.querySelector("[data-picture-pick]");
  const label = button.textContent;
  button.disabled = true;
  button.textContent = "Importing…";
  const body = new FormData();
  body.set("picture", file);
  await save("/wallpaper/picture", body);
  button.disabled = false;
  button.textContent = label;
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
