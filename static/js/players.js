// Forgetting a saved player, from the red button next to their name in the
// start menu. The app deletes everything it saved about them (library,
// history, achievements); their Steam account isn't touched, and they can be
// scanned again any time.

import { askToConfirm, closeStartMenu, showMessage } from "./desktop.js";

export function initPlayers() {
  document.addEventListener("click", (event) => {
    const button = event.target.closest("[data-forget-player]");
    if (!button) return;
    closeStartMenu();
    const { forgetPlayer: steamId, name } = button.dataset;
    askToConfirm({
      title: "forget.exe",
      heading: `Forget ${name}?`,
      message:
        "Their library, play history and achievements are deleted from this app. " +
        "Their Steam account isn't touched, and you can scan them again any time.",
      confirm: "Forget",
      onConfirm: () => forget(steamId),
    });
  });
}

async function forget(steamId) {
  try {
    const reply = await fetch(`/player/${encodeURIComponent(steamId)}/forget`, { method: "POST" });
    const answer = await reply.json().catch(() => ({}));
    if (!reply.ok) throw answer;
  } catch (problem) {
    showMessage({
      heading: problem?.title ?? "That didn't work",
      message: problem?.title ? problem.message : "The player couldn't be forgotten. Try again in a moment.",
    });
    return;
  }

  const desktop = document.querySelector("[data-desktop]");
  if (desktop?.dataset.player === steamId) {
    location.href = "/"; // they were on screen: go to whoever's left
  } else if (desktop?.dataset.friend === steamId) {
    location.href = desktop.dataset.base; // they were the friend in versus.exe: same player, no friend
  } else {
    document.querySelector(`[data-player-item="${CSS.escape(steamId)}"]`)?.remove();
  }
}
