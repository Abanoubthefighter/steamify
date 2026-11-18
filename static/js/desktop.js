// Makes the page behave like a small desktop. Windows can be dragged by
// their title bar, minimised to the taskbar, maximised and closed, and the
// start menu can bring any of them back. Popups are windows too, they just
// float above the grid and disappear for good when closed.

const LAYOUT_KEY = "steam-stats-layout";
const CASCADE = 22; // px each extra popup is shifted, so it doesn't hide the one before
const KEEP_VISIBLE = 80; // px of a dragged window that must stay reachable

export const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

const popupLayer = document.querySelector("[data-popups]");
const tray = document.querySelector("[data-tray]");
const startButton = document.querySelector("[data-start]");
const startMenu = document.querySelector("[data-start-menu]");

const closeHandlers = new WeakMap(); // popup -> function to run after it closes
let topZ = 10;
let popupCount = 0;

export function initDesktop() {
  restoreLayout();
  renderTray();
  startClock();
  document.addEventListener("pointerdown", onPointerDown);
  document.addEventListener("click", onClick);
  document.addEventListener("dblclick", onDoubleClick);
  document.addEventListener("keydown", onKeyDown);
  // "error" doesn't bubble, so listen on the way down instead. A picture that
  // fails to load (offline, or Steam moved it) is hidden rather than shown broken.
  document.addEventListener("error", onImageError, true);
}

// --- Small helpers ---------------------------------------------------------

function desktopWindows() {
  return [...document.querySelectorAll("[data-desktop] [data-win]")];
}

function titleOf(win) {
  return win.querySelector("[data-title]").textContent;
}

function isPopup(win) {
  return win.parentElement === popupLayer;
}

/** Build an element with a class and some text. textContent keeps it safe to pass in names from Steam. */
export function element(tag, className = "", text = "") {
  const node = document.createElement(tag);
  node.className = className;
  node.textContent = text;
  return node;
}

/** Play a CSS animation class from the start, even if it's already on the element. */
function replay(win, className) {
  win.classList.remove(className);
  void win.offsetWidth; // reading a layout value makes the browser notice the class went away
  win.classList.add(className);
  win.addEventListener("animationend", () => win.classList.remove(className), { once: true });
}

// --- Position and stacking -------------------------------------------------

function offsetOf(win) {
  return { x: Number(win.dataset.x) || 0, y: Number(win.dataset.y) || 0 };
}

/** Move a window this far from its home spot. The CSS turns --dx / --dy into a transform. */
function place(win, x, y) {
  win.dataset.x = Math.round(x);
  win.dataset.y = Math.round(y);
  win.style.setProperty("--dx", `${win.dataset.x}px`);
  win.style.setProperty("--dy", `${win.dataset.y}px`);
}

function raise(win) {
  win.style.setProperty("--z", ++topZ);
}

function startDrag(win, event) {
  if (event.button !== 0 || win.classList.contains("is-max")) return;

  const bar = event.target.closest(".titlebar");
  const home = offsetOf(win);
  const grab = { x: event.clientX, y: event.clientY };
  const drag = new AbortController(); // one switch to remove every listener below
  let frame = 0;

  const onMove = (move) => {
    // Pointer events can fire faster than the screen redraws, so move at most once per frame.
    cancelAnimationFrame(frame);
    frame = requestAnimationFrame(() => place(win, home.x + move.clientX - grab.x, home.y + move.clientY - grab.y));
  };
  const onDrop = () => {
    drag.abort();
    win.classList.remove("is-dragging");
    requestAnimationFrame(() => {
      keepReachable(win);
      saveLayout();
    });
  };

  bar.setPointerCapture(event.pointerId);
  win.classList.add("is-dragging");
  bar.addEventListener("pointermove", onMove, { signal: drag.signal });
  bar.addEventListener("pointerup", onDrop, { signal: drag.signal });
  bar.addEventListener("pointercancel", onDrop, { signal: drag.signal });
}

/** Nudge a window back if it was dropped where its title bar can't be grabbed again. */
function keepReachable(win) {
  const box = win.getBoundingClientRect();
  const { x, y } = offsetOf(win);
  const top = isPopup(win) ? 0 : -window.scrollY; // the desktop scrolls, the popup layer doesn't
  let dx = 0;
  let dy = 0;
  if (box.right < KEEP_VISIBLE) dx = KEEP_VISIBLE - box.right;
  if (box.left > window.innerWidth - KEEP_VISIBLE) dx = window.innerWidth - KEEP_VISIBLE - box.left;
  if (box.top < top) dy = top - box.top;
  if (dx || dy) place(win, x + dx, y + dy);
}

// --- Open, minimised, closed -----------------------------------------------

function setState(win, state) {
  const wasHidden = win.hidden;
  win.dataset.state = state;
  win.hidden = state !== "open";
  if (state !== "open") win.classList.remove("is-max");
  if (state === "open" && wasHidden) {
    replay(win, "is-opening");
    win.dispatchEvent(new CustomEvent("window:open")); // e.g. alerts.js starts its stack over
  }
  renderTray();
  saveLayout();
}

const windowActions = {
  close: (win) => (isPopup(win) ? closePopup(win) : setState(win, "closed")),
  minimize: (win) => setState(win, "minimized"),
  maximize: (win) => {
    win.classList.toggle("is-max");
    raise(win);
  },
};

/** Bring a desktop window back (if needed) and to the front. Returns it, or null if there's no such window. */
export function openWindow(id) {
  const win = document.querySelector(`[data-desktop] [data-win="${CSS.escape(id)}"]`);
  if (!win) return null;
  setState(win, "open");
  raise(win);
  win.scrollIntoView({ block: "nearest", behavior: reducedMotion ? "auto" : "smooth" });
  replay(win, "is-flashing");
  return win;
}

/** One chip in the taskbar for every minimised window. */
function renderTray() {
  const minimised = desktopWindows().filter((win) => win.dataset.state === "minimized");
  tray.replaceChildren(
    ...minimised.map((win) => {
      const chip = element("button", "chip chip--window", titleOf(win));
      chip.type = "button";
      chip.title = `Restore ${titleOf(win)}`;
      chip.addEventListener("click", () => openWindow(win.dataset.win));
      return chip;
    }),
  );
}

// --- Remembering the layout ------------------------------------------------
// Saved as { scan: { x: 0, y: 0, state: "open" }, ... } so a reload (after a
// sync, say) doesn't put every window back where it started.

function readLayout() {
  try {
    return JSON.parse(localStorage.getItem(LAYOUT_KEY)) ?? {};
  } catch {
    return {};
  }
}

function saveLayout() {
  const layout = {};
  for (const win of desktopWindows()) {
    layout[win.dataset.win] = { ...offsetOf(win), state: win.dataset.state };
  }
  try {
    localStorage.setItem(LAYOUT_KEY, JSON.stringify(layout));
  } catch {
    // Storage can be switched off. The windows still work, they just won't be remembered.
  }
}

function restoreLayout() {
  const saved = readLayout();
  for (const win of desktopWindows()) {
    const { x = 0, y = 0, state = "open" } = saved[win.dataset.win] ?? {};
    place(win, x, y);
    win.dataset.state = state;
    win.hidden = state !== "open";
  }
}

function tidyUp() {
  for (const win of desktopWindows()) {
    place(win, 0, 0);
    win.classList.remove("is-max");
    setState(win, "open");
  }
  window.scrollTo({ top: 0, behavior: reducedMotion ? "auto" : "smooth" });
}

// --- Popups ----------------------------------------------------------------

/**
 * Open a floating window. `content` is a DOM node (or fragment) for its body.
 * `onClose` runs after the popup is closed, however that happens.
 */
export function openPopup({ title, content, color = "lilac", onClose }) {
  const win = document.getElementById("popup-template").content.firstElementChild.cloneNode(true);
  const heading = win.querySelector("[data-title]");
  heading.textContent = title;
  heading.id = `popup-${++popupCount}-title`;
  win.setAttribute("aria-labelledby", heading.id);
  win.classList.add(`win--${color}`);
  win.querySelector("[data-popup-body]").append(content);
  closeHandlers.set(win, { onClose, cameFrom: document.activeElement });

  const shift = (popupLayer.childElementCount % 5) * CASCADE;
  place(win, shift, shift);
  popupLayer.append(win);
  raise(win);
  replay(win, "is-opening");
  (win.querySelector("[data-autofocus]") ?? win.querySelector(".btn"))?.focus();
  return win;
}

export function closePopup(win) {
  const { onClose, cameFrom } = closeHandlers.get(win) ?? {};
  win.remove();
  if (cameFrom?.isConnected) cameFrom.focus(); // hand the keyboard back to wherever it was
  onClose?.();
}

/** A popup with the round "!" icon, a heading, one line of explanation and an Ok button. */
export function showMessage({ heading, message, title = "error.exe", color = "red", onClose }) {
  const icon = element("div", "alert__icon", "!");
  icon.setAttribute("aria-hidden", "true");
  const ok = element("button", "btn", "Ok");
  ok.type = "button";
  ok.dataset.action = "close";

  const content = document.createDocumentFragment();
  content.append(icon, element("h3", "heading", heading), element("p", "", message), ok);
  return openPopup({ title, content, color, onClose });
}

/**
 * Open one of the ready-made popups that sit in the page as
 * <template data-popup="name" data-title="..." data-color="...">.
 */
export function openTemplatePopup(name) {
  const template = document.querySelector(`template[data-popup="${CSS.escape(name)}"]`);
  if (!template) return null;
  const { title, color } = template.dataset;
  return openPopup({ title, color, content: template.content.cloneNode(true) });
}

// --- Start menu and taskbar ------------------------------------------------

function toggleStartMenu(open = startMenu.hidden) {
  if (open) renderPrograms();
  startMenu.hidden = !open;
  startButton.setAttribute("aria-expanded", String(open));
  if (open) startMenu.querySelector(".menu-item")?.focus();
}

/** The "Programs" list is read off the page each time, so it always matches the windows that exist. */
function renderPrograms() {
  const items = desktopWindows().map((win) => {
    const button = element("button", "menu-item", titleOf(win));
    button.type = "button";
    button.addEventListener("click", () => {
      toggleStartMenu(false);
      openWindow(win.dataset.win);
    });
    const item = document.createElement("li");
    item.append(button);
    return item;
  });
  startMenu.querySelector("[data-programs]").replaceChildren(...items);
}

/** Let another file handle a start menu item, e.g. <button data-menu="wallpaper">. */
export function addMenuAction(name, action) {
  menuActions[name] = action;
}

const menuActions = {
  tidy: tidyUp,
  quit() {
    // Inside the desktop app, pywebview gives the page a small "api" object (see desktop.py).
    // In a normal browser tab there's nothing to shut down, so just say goodbye.
    if (window.pywebview?.api?.quit) window.pywebview.api.quit();
    else openTemplatePopup("shutdown");
  },
};

function startClock() {
  const clock = document.querySelector("[data-clock]");
  const tick = () => {
    const now = new Date();
    clock.dateTime = now.toISOString();
    clock.textContent = now.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  };
  tick();
  setInterval(tick, 15_000);
}

// --- Events ----------------------------------------------------------------
// One listener per kind of event for the whole page. Elements say what they
// do with data-* attributes, so new buttons need no new wiring.

function onPointerDown(event) {
  if (!startMenu.hidden && !event.target.closest("[data-start-menu], [data-start]")) toggleStartMenu(false);

  const win = event.target.closest(".win");
  if (!win) return;
  raise(win);
  if (event.target.closest(".titlebar") && !event.target.closest("button, a")) startDrag(win, event);
}

function onClick(event) {
  const target = event.target;

  const control = target.closest("[data-action]");
  if (control) {
    windowActions[control.dataset.action]?.(control.closest(".win"));
    return;
  }
  const menuItem = target.closest("[data-menu]");
  if (menuItem) {
    toggleStartMenu(false);
    menuActions[menuItem.dataset.menu]?.();
    return;
  }
  const popupOpener = target.closest("[data-popup-open]");
  if (popupOpener) {
    toggleStartMenu(false);
    openTemplatePopup(popupOpener.dataset.popupOpen);
    return;
  }
  const launcher = target.closest("[data-open-window]");
  if (launcher) {
    openWindow(launcher.dataset.openWindow);
    if (launcher.dataset.thenFocus) document.querySelector(launcher.dataset.thenFocus)?.focus();
    return;
  }
  if (target.closest("[data-start]")) toggleStartMenu();
}

function onDoubleClick(event) {
  const bar = event.target.closest(".titlebar");
  if (!bar || event.target.closest("button")) return;
  bar.querySelector('[data-action="maximize"]')?.click();
}

function onKeyDown(event) {
  if (event.key !== "Escape") return;
  if (!startMenu.hidden) {
    toggleStartMenu(false);
    startButton.focus();
  } else if (popupLayer.lastElementChild) {
    closePopup(popupLayer.lastElementChild);
  }
}

function onImageError(event) {
  const image = event.target;
  if (image.tagName !== "IMG") return;
  if ("hideOnError" in image.dataset) image.hidden = true;
  else image.style.visibility = "hidden";
}
