// trophies.exe: every game with achievements, opened from "View all games"
// in achievements.exe.
//
// Like library.exe, sorting and searching happen in Python (stats.py). This
// file only asks the server for the rows again and swaps the new HTML in.

import { openPopup, showMessage } from "./desktop.js";

const SEARCH_DELAY = 150; // ms to wait after the last keystroke before asking the server

let trophiesWindow = null; // the open trophies.exe, if there is one

export function initTrophies() {
  const desktop = document.querySelector("[data-desktop]");
  if (!desktop) return;
  const base = desktop.dataset.base; // "/player/<id>"

  document.addEventListener("click", (event) => {
    if (event.target.closest("[data-open-trophies]")) openTrophies(base);
  });
}

/** Fetch a server-rendered piece of HTML and return its first element. */
async function fetchPart(url) {
  const reply = await fetch(url);
  if (!reply.ok) throw new Error(`The server answered ${reply.status}`);
  const holder = document.createElement("template");
  holder.innerHTML = await reply.text(); // server-rendered and escaped by Jinja
  return holder.content.firstElementChild;
}

async function openTrophies(base) {
  if (trophiesWindow?.isConnected) {
    trophiesWindow.querySelector("[data-trophy-search]")?.focus(); // already open: just point at it
    return;
  }
  try {
    const content = await fetchPart(`${base}/trophies`);
    trophiesWindow = openPopup({ title: content.dataset.title, content, color: "red", big: true });
    wireControls(base, content);
  } catch {
    showMessage({ heading: "Can't open that", message: "trophies.exe didn't load. Try again." });
  }
}

/** The search box and the "Show" radios ask for a freshly sorted list. */
function wireControls(base, content) {
  const form = content.querySelector("[data-trophy-form]");
  const rows = content.querySelector("[data-trophy-rows]");
  let pending = null; // the request in flight, so a newer one can cancel it
  let typing = 0;

  async function refresh() {
    pending?.abort();
    pending = new AbortController();
    const query = new URLSearchParams(new FormData(form)); // sort=...&q=...
    rows.classList.add("is-loading"); // the old rows stay on screen, dimmed, until the new ones arrive
    try {
      const reply = await fetch(`${base}/trophies/rows?${query}`, { signal: pending.signal });
      if (reply.ok) rows.innerHTML = await reply.text();
    } catch (error) {
      if (error.name === "AbortError") return; // a newer request replaced this one
    }
    rows.classList.remove("is-loading");
  }

  form.addEventListener("change", (event) => {
    if (event.target.name === "sort") refresh();
  });
  form.addEventListener("input", (event) => {
    if (event.target.name !== "q") return;
    clearTimeout(typing);
    typing = setTimeout(refresh, SEARCH_DELAY);
  });
  form.addEventListener("submit", (event) => event.preventDefault()); // Enter in the search box
}
