// Prompt W4: the six Claude Design references rendered at the journey's sizes (desktop 1440x900, phone 390x844) beside the
// page's screenshots. They use a custom canvas format (<x-dc>, sc-if / sc-for, {{ }} and a support.js that is not in the
// handoff), so they render as static HTML: the layout and CSS show, the template syntax stays visible and the mock data
// is partly placeholders. Run from web/: node scripts/render_references.mjs
import fs from "node:fs";
import path from "node:path";
import { chromium } from "playwright";

const REF = path.resolve("design-handoff/chat/reference");
const OUT = process.env.W4_SHOTS ?? "C:\\dev\\fpl-backups\\w4_chat_files";
const FILES = [
  ["chat-team-desktop", 1440, 900],
  ["chat-general-desktop", 1440, 900],
  ["chat-states", 1440, 900],
  ["chat-mobile-team-thinking", 390, 844],
  ["chat-mobile-team-pitch-open", 390, 844],
  ["chat-mobile-general", 390, 844],
];
fs.mkdirSync(OUT, { recursive: true });
const browser = await chromium.launch({ channel: "msedge", headless: true });
for (const [name, w, h] of FILES) {
  const page = await browser.newPage({ viewport: { width: w, height: h } });
  let html = fs.readFileSync(path.join(REF, `${name}.reference.html`), "utf8");
  html = html.replace('<script src="./support.js"></script>', "");
  // the blobs are the two photos copied to public/images
  html = html.replace(/\/_blob\/c8f1cb1f9aa719ad396c8040f81c1e9d/g, "file:///" + path.resolve("public/images/chat-team-bg.webp").replace(/\\/g, "/"));
  html = html.replace(/\/_blob\/f66a08aa82f238d1650f6f610c57de46/g, "file:///" + path.resolve("public/images/chat-general-bg.webp").replace(/\\/g, "/"));
  await page.setContent(html, { waitUntil: "load" });
  await page.waitForTimeout(800);
  const file = path.join(OUT, `reference_${name}_${w}x${h}.png`);
  await page.screenshot({ path: file, fullPage: name === "chat-states" });
  console.log(`rendered ${file}`);
  await page.close();
}
await browser.close();
