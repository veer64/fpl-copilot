// Prompt W1 Part 5: paint timings of /login at a phone viewport, measured in the browser (Lighthouse could not get a
// first paint out of headless Edge/Chrome here, NO_FCP twice). Usage: node scripts/paint_timing.mjs [baseUrl]
import { chromium } from "@playwright/test";

const base = process.argv[2] ?? "http://localhost:3001";
const browser = await chromium.launch({ channel: "msedge" });
const context = await browser.newContext({ viewport: { width: 390, height: 844 }, deviceScaleFactor: 2, isMobile: true, hasTouch: true });
const page = await context.newPage();
await page.addInitScript(() => {
  const w = window;
  w.__lcp = 0;
  new PerformanceObserver((list) => {
    for (const e of list.getEntries()) w.__lcp = e.startTime;
  }).observe({ type: "largest-contentful-paint", buffered: true });
  w.__cls = 0;
  new PerformanceObserver((list) => {
    for (const e of list.getEntries()) if (!e.hadRecentInput) w.__cls += e.value;
  }).observe({ type: "layout-shift", buffered: true });
});
await page.goto(`${base}/login`, { waitUntil: "load" });
await page.waitForTimeout(3000);
const m = await page.evaluate(() => {
  const nav = performance.getEntriesByType("navigation")[0];
  const paints = Object.fromEntries(performance.getEntriesByType("paint").map((p) => [p.name, Math.round(p.startTime)]));
  const res = performance.getEntriesByType("resource");
  const byType = {};
  for (const r of res) {
    const k = r.initiatorType || "other";
    byType[k] = (byType[k] || 0) + (r.transferSize || 0);
  }
  const total = res.reduce((s, r) => s + (r.transferSize || 0), 0) + (nav.transferSize || 0);
  const long = performance.getEntriesByType("longtask")?.length ?? "n/a";
  return {
    ttfb_ms: Math.round(nav.responseStart),
    dom_content_loaded_ms: Math.round(nav.domContentLoadedEventEnd),
    load_ms: Math.round(nav.loadEventEnd),
    fcp_ms: paints["first-contentful-paint"],
    lcp_ms: Math.round(window.__lcp),
    cls: +window.__cls.toFixed(4),
    requests: res.length + 1,
    transfer_bytes_total: total,
    transfer_bytes_by_initiator: byType,
    long_tasks: long,
  };
});
console.log(JSON.stringify(m, null, 2));
await browser.close();
