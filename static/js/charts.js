// The media player window.
//
// charts.py sends a list of "tracks" (one per chart). Each track has one or
// more "views", for example 30D / 6M / 1Y / ALL. This file draws the current
// view with Chart.js and wires up the buttons under the screen.
//
// Every colour and font is read from theme.css, so a reskin there recolours
// the charts as well.

import { element, reducedMotion } from "./desktop.js";

const STATE_KEY = "steam-stats-media"; // remembers the track and view across reloads
const DESCRIBED_BARS = 12; // how many bars get spelled out for screen readers

const css = getComputedStyle(document.documentElement);
const theme = (name) => css.getPropertyValue(`--${name}`).trim();

let tracks = [];
let ui = null;
let chart = null;
let trackIndex = 0;
let viewKey = "";
let tableOn = false;

export function initCharts() {
  const data = document.getElementById("tracks-data");
  if (!data || !window.Chart) return;
  tracks = JSON.parse(data.textContent);

  const win = document.querySelector('[data-win="media"]');
  ui = {
    title: win.querySelector("[data-title]"),
    canvas: win.querySelector("[data-chart]"),
    chartBox: win.querySelector("[data-chart-box]"),
    empty: win.querySelector("[data-chart-empty]"),
    table: win.querySelector("[data-chart-table]"),
    tableToggle: win.querySelector("[data-table-toggle]"),
    viewKeys: win.querySelector("[data-view-keys]"),
    legend: win.querySelector("[data-chart-legend]"),
    caption: win.querySelector("[data-chart-caption]"),
    thumb: win.querySelector("[data-track-thumb]"),
  };

  for (const button of win.querySelectorAll("[data-track]")) {
    button.addEventListener("click", () => showTrack(trackIndex + Number(button.dataset.track)));
  }
  ui.tableToggle.addEventListener("click", () => {
    tableOn = !tableOn;
    draw();
  });

  const saved = readState();
  tableOn = Boolean(saved.table);
  // Chart.js draws its text on a canvas, which can't swap fonts in later the
  // way normal text does. So wait for the fonts before the first drawing.
  document.fonts.ready.then(() => showTrack(saved.track ?? firstTrackWithData(), saved.view));
}

/** A freshly scanned player has no history yet, so open on a chart that has something to show. */
function firstTrackWithData() {
  const index = tracks.findIndex((track) => track.views.some((view) => view.values.some(Boolean)));
  return Math.max(index, 0);
}

// --- Switching tracks and views --------------------------------------------

function showTrack(index, view) {
  trackIndex = ((Number(index) || 0) + tracks.length) % tracks.length; // wraps around at both ends
  const track = tracks[trackIndex];
  viewKey = track.views.some((each) => each.key === view) ? view : track.start;

  ui.title.textContent = track.file;
  ui.caption.textContent = track.caption;
  ui.thumb.style.setProperty("--at", `${tracks.length > 1 ? (trackIndex / (tracks.length - 1)) * 100 : 0}%`);
  renderViewKeys(track);
  renderLegend(track);
  draw();
}

/** One button per view. A track with a single view needs none. */
function renderViewKeys(track) {
  const keys = track.views.map((view) => view.key);
  const buttons = (keys.length > 1 ? keys : []).map((key) => {
    const button = element("button", "", key);
    button.type = "button";
    button.setAttribute("aria-pressed", String(key === viewKey));
    button.addEventListener("click", () => {
      viewKey = key;
      renderViewKeys(track);
      draw();
    });
    return button;
  });
  ui.viewKeys.replaceChildren(...buttons);
}

/** Says in words what the highlighted bar colours mean, so colour is never the only clue. */
function renderLegend(track) {
  const items = track.legend.map(([color, meaning]) => {
    const item = element("span", "legend__item");
    const swatch = element("span", "legend__swatch");
    swatch.style.setProperty("--swatch", theme(color));
    item.append(swatch, meaning);
    return item;
  });
  ui.legend.replaceChildren(...items, track.footnote);
}

// --- Drawing ---------------------------------------------------------------

function draw() {
  const track = tracks[trackIndex];
  const view = track.views.find((each) => each.key === viewKey);
  const empty = !view.values.some(Boolean);

  ui.empty.textContent = track.empty;
  ui.empty.hidden = !empty;
  ui.chartBox.hidden = empty || tableOn;
  ui.table.hidden = empty || !tableOn;
  ui.tableToggle.setAttribute("aria-pressed", String(tableOn));
  ui.canvas.setAttribute("aria-label", describe(track, view));
  renderTable(track, view);
  saveState();
  if (empty || tableOn) return;

  const config = { data: dataFor(view), options: optionsFor(track, view) };
  if (chart && chart.$trackIndex === trackIndex) {
    // Same chart, new numbers: update it in place so the bars slide to their new heights.
    Object.assign(chart, config);
    chart.$now = { track, view };
    chart.update();
  } else {
    chart?.destroy();
    chart = new window.Chart(ui.canvas, { type: "bar", ...config, plugins: [valueLabels] });
    chart.$trackIndex = trackIndex;
    chart.$now = { track, view };
  }
}

function dataFor(view) {
  return {
    labels: view.labels,
    datasets: [
      {
        data: view.values,
        backgroundColor: view.colors.map(theme),
        hoverBackgroundColor: theme("sand"),
        borderColor: theme("ink"),
        borderWidth: 2,
        borderSkipped: false, // outline all four sides, like everything else in the app
        maxBarThickness: 46,
        categoryPercentage: 0.82,
        barPercentage: 0.86,
      },
    ],
  };
}

function optionsFor(track, view) {
  const labelAxis = track.horizontal ? "y" : "x";
  const valueAxis = track.horizontal ? "x" : "y";
  const text = { color: withAlpha(theme("cream"), 0.85), font: { family: theme("font-ui"), size: 11, weight: 500 } };

  return {
    indexAxis: labelAxis, // "y" turns the bars sideways
    responsive: true,
    maintainAspectRatio: false,
    animation: reducedMotion ? false : { duration: 350 },
    // room for the numbers printed at the end of the bars
    layout: { padding: track.horizontal ? { right: 62 } : { top: 22 } },
    plugins: { legend: { display: false }, tooltip: tooltipFor(track, view) },
    scales: {
      [labelAxis]: {
        grid: { display: false },
        border: { color: withAlpha(theme("cream"), 0.35) },
        ticks: { ...text, maxRotation: 0, autoSkipPadding: 10 },
      },
      [valueAxis]: track.horizontal
        ? { display: false, beginAtZero: true } // every bar carries its own number, so no axis needed
        : {
            beginAtZero: true,
            border: { display: false, dash: [3, 6] },
            grid: { color: withAlpha(theme("cream"), 0.15) },
            ticks: { ...text, maxTicksLimit: 4, precision: 0, callback: (value) => formatValue(value, track.unit) },
          },
    },
  };
}

/** The hover box: the number first and biggest, then what it belongs to. */
function tooltipFor(track, view) {
  return {
    backgroundColor: theme("paper"),
    titleColor: theme("ink"),
    bodyColor: theme("ink"),
    borderColor: theme("ink"),
    borderWidth: 2,
    cornerRadius: 0,
    padding: 10,
    displayColors: false,
    titleFont: { family: theme("font-ui"), size: 15, weight: 600 },
    bodyFont: { family: theme("font-body"), size: 13 },
    callbacks: {
      title: ([item]) => formatValue(view.values[item.dataIndex], track.unit, { spellOut: true }),
      label: (item) => view.titles[item.dataIndex],
      afterLabel: (item) => view.notes[item.dataIndex],
    },
  };
}

/** A tiny Chart.js plugin: prints the value on the bars charts.py marked as worth labelling. */
const valueLabels = {
  id: "valueLabels",
  afterDatasetsDraw(drawn) {
    const { track, view } = drawn.$now;
    const { ctx } = drawn;
    ctx.save();
    ctx.fillStyle = theme("cream");
    ctx.font = `600 12px ${theme("font-ui")}`;
    drawn.getDatasetMeta(0).data.forEach((bar, index) => {
      if (!view.marked.includes(index)) return;
      const label = formatValue(view.values[index], track.unit);
      if (track.horizontal) {
        ctx.textAlign = "left";
        ctx.textBaseline = "middle";
        ctx.fillText(label, bar.x + 8, bar.y);
      } else {
        ctx.textAlign = "center";
        ctx.textBaseline = "bottom";
        ctx.fillText(label, bar.x, bar.y - 6);
      }
    });
    ctx.restore();
  },
};

// --- The same numbers as text ----------------------------------------------

/** The table view: every value the chart shows, readable without hovering or seeing colour. */
function renderTable(track, view) {
  const table = document.createElement("table");
  table.createCaption().textContent = `${track.title} (${viewKey.toLowerCase()})`;

  const head = table.createTHead().insertRow();
  for (const heading of ["", track.unit === "h" ? "Hours" : "Games", "Note"]) {
    const cell = element("th", "", heading);
    cell.scope = "col";
    head.append(cell);
  }
  const body = table.createTBody();
  view.titles.forEach((title, index) => {
    const row = body.insertRow();
    row.append(
      element("td", "", title),
      element("td", "", formatValue(view.values[index], track.unit)),
      element("td", "", view.notes[index]),
    );
  });
  ui.table.replaceChildren(table);
}

/** One sentence for screen readers, since a canvas is just a picture to them. */
function describe(track, view) {
  const bars = view.titles
    .map((title, index) => `${title}: ${formatValue(view.values[index], track.unit, { spellOut: true })}`)
    .slice(-DESCRIBED_BARS);
  return `${track.title}. ${bars.join(", ")}.`;
}

// --- Helpers ---------------------------------------------------------------

function formatValue(value, unit, { spellOut = false } = {}) {
  // Same rule as formatting.hours in Python: one decimal under 10, whole numbers above.
  const number = value >= 10 ? Math.round(value) : value;
  const text = number.toLocaleString("en", { maximumFractionDigits: 1 });
  if (unit === "h") return `${text} h`;
  return spellOut ? `${text} ${value === 1 ? "game" : "games"}` : text;
}

/** Any CSS colour, made see-through. A canvas does the parsing, so theme.css can use any colour format. */
function withAlpha(color, alpha) {
  const probe = document.createElement("canvas").getContext("2d");
  probe.fillStyle = color;
  const [red, green, blue] = [1, 3, 5].map((start) => parseInt(probe.fillStyle.slice(start, start + 2), 16));
  return `rgba(${red}, ${green}, ${blue}, ${alpha})`;
}

function readState() {
  try {
    return JSON.parse(sessionStorage.getItem(STATE_KEY)) ?? {};
  } catch {
    return {};
  }
}

function saveState() {
  try {
    sessionStorage.setItem(STATE_KEY, JSON.stringify({ track: trackIndex, view: viewKey, table: tableOn }));
  } catch {
    // Storage switched off: the player just starts on the first track next time.
  }
}
