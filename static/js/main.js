// Entry point. Each file below looks after one part of the page and does
// nothing if that part isn't on the current page.

import { initDesktop } from "./desktop.js";
import { initAlerts } from "./alerts.js";
import { initScan } from "./scan.js";
import { initLibrary } from "./library.js";
import { initCharts } from "./charts.js";
import { initWallpaper } from "./wallpaper.js";

initDesktop();
initAlerts();
initScan();
initLibrary();
initCharts();
initWallpaper();
