// Prompt W5: the five Claude Design references rendered at the journey's sizes (desktop 1440x900, phone 390x844) beside the
// page's screenshots. Static HTML as in W4 (the custom canvas format's support.js is not in the handoff: the template syntax
// stays visible). Run from web/: node scripts/render_references_w5.mjs
import fs from "node:fs";
import path from "node:path";
import { chromium } from "playwright";

const REF = path.resolve("design-handoff/about-privacy/fpl-copilot-about-privacy-handoff/reference");
const OUT = process.env.W5_SHOTS ?? "C:\\dev\\fpl-backups\\w5_about_privacy_files";
const FILES = [
  ["about-desktop", 1440, 900, true],
  ["privacy-desktop", 1440, 900, true],
  ["delete-account-states", 1440, 1300, true],
  ["about-mobile", 390, 844, true],
  ["privacy-mobile", 390, 844, true],
];
fs.mkdirSync(OUT, { recursive: true });
const browser = await chromium.launch({ channel: "msedge", headless: true });
for (const [name, w, h, full] of FILES) {
  const page = await browser.newPage({ viewport: { width: w, height: h } });
  let html = fs.readFileSync(path.join(REF, `${name}.reference.html`), "utf8");
  html = html.replace('<script src="./support.js"></script>', "");
  html = html.replace(/\/_blob\/6ac2b1965381c3601c51ff7c3b83e073/g, "file:///" + path.resolve("public/images/about-bg.webp").replace(/\\/g, "/"));
  html = html.replace(/\/_blob\/58b8185a71fe1b7881428b069e03e9b7/g, "file:///" + path.resolve("public/images/privacy-bg.webp").replace(/\\/g, "/"));
  html = html.replace(/<sc-if[^>]*>/g, "").replace(/<\/sc-if>/g, "");
  await page.setContent(html, { waitUntil: "load" });
  await page.waitForTimeout(800);
  const file = path.join(OUT, `reference_${name}_${w}x${h}.png`);
  await page.screenshot({ path: file, fullPage: !!full });
  const viewportFile = path.join(OUT, `reference_${name}_${w}x${h}_viewport.png`);
  await page.screenshot({ path: viewportFile, fullPage: false });
  console.log(`rendered ${file}`);
  await page.close();
}
await browser.close();
