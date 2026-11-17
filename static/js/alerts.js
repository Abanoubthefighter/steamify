// warning.exe: a stack of popups shown one at a time. "Ok" flips to the next
// one and closes the window after the last. The outlines behind the window
// (data-stack in the CSS) shrink as the pile gets smaller.

const MAX_OUTLINES = 2;

export function initAlerts() {
  const box = document.querySelector("[data-alerts]");
  if (!box) return;

  const win = box.closest(".win");
  const cards = [...box.querySelectorAll("[data-alert]")];
  const counter = win.querySelector("[data-meta]");
  let current = 0;

  function show(index) {
    current = index;
    cards.forEach((card, position) => {
      card.hidden = position !== index;
    });
    win.dataset.stack = Math.min(cards.length - 1 - index, MAX_OUTLINES);
    counter.textContent = cards.length > 1 ? `${index + 1} of ${cards.length}` : "";
  }

  box.querySelector("[data-alert-ok]").addEventListener("click", () => {
    if (current < cards.length - 1) show(current + 1);
    else win.querySelector('[data-action="close"]').click();
  });

  // Reopened from the start menu? Start again from the top of the pile.
  win.addEventListener("window:open", () => show(0));
  show(0);
}
