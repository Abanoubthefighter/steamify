// library.exe and sort.exe, plus the details popup for a single game.
//
// Sorting and searching happen in Python (stats.py). This file only asks
// the server for the rows again and swaps the new HTML in, so the sort
// rules live in exactly one place.

import { openPopup, openWindow, showMessage } from "./desktop.js";

const SEARCH_DELAY = 150; // ms to wait after the last keystroke before asking the server

export function initLibrary() {
  const rows = document.querySelector("[data-library-rows]");
  if (!rows) return;

  const base = document.querySelector("[data-desktop]").dataset.base; // "/player/<id>"
  const sortForm = document.querySelector("[data-sort-form]");
  const search = document.querySelector("[data-library-search]");

  const view = { sort: new FormData(sortForm).get("sort"), q: "", all: false };
  let pending = null; // the request in flight, so a newer one can cancel it
  let typing = 0;

  async function refresh() {
    pending?.abort();
    pending = new AbortController();
    const query = new URLSearchParams({ sort: view.sort, q: view.q });
    if (view.all) query.set("all", "1");

    rows.classList.add("is-loading"); // the old rows stay on screen, dimmed, until the new ones arrive
    try {
      const reply = await fetch(`${base}/library?${query}`, { signal: pending.signal });
      if (reply.ok) rows.innerHTML = await reply.text(); // server-rendered and escaped by Jinja
    } catch (error) {
      if (error.name === "AbortError") return; // a newer request replaced this one
    }
    rows.classList.remove("is-loading");
  }

  sortForm.addEventListener("change", () => {
    view.sort = new FormData(sortForm).get("sort");
    view.all = false;
    refresh();
  });
  // "Ok" doesn't need to apply anything (picking a radio already did), so it takes you to the list.
  sortForm.addEventListener("submit", (event) => {
    event.preventDefault();
    openWindow("library");
  });

  search.addEventListener("input", () => {
    clearTimeout(typing);
    typing = setTimeout(() => {
      view.q = search.value;
      view.all = false;
      refresh();
    }, SEARCH_DELAY);
  });

  rows.addEventListener("click", (event) => {
    if (!event.target.closest("[data-library-all]")) return;
    view.all = true;
    refresh();
  });

  // Folders, documents and library rows all carry data-game, wherever they are on the page.
  document.addEventListener("click", (event) => {
    const game = event.target.closest("[data-game]");
    if (game) openGame(base, game.dataset.game);
  });
}

async function openGame(base, appId) {
  try {
    const reply = await fetch(`${base}/game/${appId}`);
    if (!reply.ok) throw new Error(`The server answered ${reply.status}`);
    const holder = document.createElement("template");
    holder.innerHTML = await reply.text(); // server-rendered and escaped by Jinja
    const card = holder.content.firstElementChild;
    openPopup({ title: card.dataset.title, content: card, color: "sand" });
  } catch {
    showMessage({ heading: "Can't open that", message: "The details for this game didn't load. Try again." });
  }
}
