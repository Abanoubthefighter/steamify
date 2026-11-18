// badges.exe, the badge chip in the taskbar, the badges row in profile.exe,
// and the popup for a new badge.
//
// The app adds up how long it runs (badges.py, desktop app only). This file
// asks the server once a minute whether that earned a new badge; if so it
// shows a popup, swaps in a fresh chip and profile row, and tells the
// server it was shown.

import { addMenuAction, fetchPart, htmlToElement, openPopup, showMessage } from "./desktop.js";

const NEW_BADGE_CHECK = 60_000; // ms between "anything new?" questions

let badgesWindow = null; // the open badges.exe, if there is one
let announcing = false; // a "new badge" popup is on screen

export function initBadges() {
  if (!document.querySelector("[data-badge-chip]")) return;
  addMenuAction("badges", openBadges);
  document.addEventListener("click", (event) => {
    if (event.target.closest("[data-open-badges]")) openBadges();
  });
  checkForNewBadge();
  setInterval(checkForNewBadge, NEW_BADGE_CHECK);
}

async function openBadges() {
  if (badgesWindow?.isConnected) {
    badgesWindow.querySelector(".btn")?.focus(); // already open: just point at it
    return;
  }
  try {
    const content = await fetchPart("/badges");
    badgesWindow = openPopup({ title: content.dataset.title, content, color: "sand", wide: true });
  } catch {
    showMessage({ heading: "Can't open that", message: "badges.exe didn't load. Try again." });
  }
}

async function checkForNewBadge() {
  if (announcing) return;
  try {
    const reply = await fetch("/badges/new");
    if (reply.status !== 200) return; // 204: nothing new
    const news = await reply.json();
    announcing = true;
    const content = htmlToElement(news.popup);
    openPopup({ title: content.dataset.title, content, color: "red", onClose: () => (announcing = false) });
    document.querySelector("[data-badge-chip]")?.replaceWith(htmlToElement(news.chip));
    document.querySelector("[data-badge-profile]")?.replaceWith(htmlToElement(news.profile));
    // Marked as seen right away, so a reload doesn't show the same popup again.
    await fetch("/badges/seen", { method: "POST", body: new URLSearchParams({ key: news.key }) });
  } catch {
    // The server is busy or gone for a moment. Ask again next time.
  }
}
