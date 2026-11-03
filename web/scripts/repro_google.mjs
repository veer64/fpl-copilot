// Repro for the "Continue with Google spins forever" bug (2 Nov 2026): click Google on /login, capture console errors,
// page errors and every Clerk Frontend API exchange (method, path, status, JSON error codes -- never a token or a query
// string), and say whether the browser left for Google within 10 s. Usage: node scripts/repro_google.mjs [baseUrl]
import { chromium } from "@playwright/test";

const base = process.argv[2] ?? "http://localhost:3000";
const browser = await chromium.launch({ channel: "msedge", args: ["--autoplay-policy=no-user-gesture-required"] });
const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
const consoleMsgs = [];
const pageErrors = [];
const clerk = [];
const isClerk = (u) => /clerk\.accounts\.dev$|\.clerk\.com$|lclclerk\.com$|accounts\.dev$/.test(u.host);

page.on("console", (m) => {
  if (m.type() === "error" || m.type() === "warning") consoleMsgs.push(`[${m.type()}] ${m.text().slice(0, 600)}`);
});
page.on("pageerror", (e) => pageErrors.push(String(e).slice(0, 600)));
page.on("response", async (r) => {
  const u = new URL(r.url());
  if (!isClerk(u)) return;
  let detail = "";
  try {
    const j = await r.json();
    if (j && j.errors) detail = " errors=" + JSON.stringify(j.errors.map((e) => ({ code: e.code, message: e.message, long_message: e.long_message, meta: e.meta })));
    else if (j && j.response && j.response.status) detail = ` status=${j.response.status}`;
  } catch {
    /* not JSON */
  }
  clerk.push(`${r.request().method()} ${u.host}${u.pathname} -> ${r.status()}${detail}`);
});
page.on("requestfailed", (r) => {
  const u = new URL(r.url());
  if (isClerk(u)) clerk.push(`${r.method()} ${u.host}${u.pathname} -> FAILED ${r.failure()?.errorText}`);
});
page.on("framenavigated", (f) => {
  if (f === page.mainFrame()) clerk.push(`[navigated] ${new URL(f.url()).host}${new URL(f.url()).pathname}`);
});

// BLOCK=protect simulates a privacy/ad blocker that refuses Clerk Protect's bot-check domains; BLOCK=signins fails the
// sign-in request itself; BLOCK=slow makes it hang
const block = process.env.BLOCK ?? "";
if (block === "protect") await page.route(/protect\.clerk\.com/, (r) => r.abort("blockedbyclient"));
if (block === "signins") await page.route(/\/v1\/client\/sign_ins/, (r) => r.abort("failed"));
if (block === "slow") await page.route(/\/v1\/client\/sign_ins/, () => {});
console.log(`BLOCK=${block || "none"}`);

await page.goto(`${base}/login`);
await page.getByTestId("skip-intro").click();
const google = page.getByTestId("google");
await google.waitFor();
for (let i = 0; i < 100 && !(await google.isEnabled()); i++) await page.waitForTimeout(100);
console.log(`google enabled: ${await google.isEnabled()}`);
const t0 = Date.now();
await google.click();
let outcome;
try {
  await page.waitForURL(/accounts\.google\.com|accounts\.dev|clerk\.com/, { timeout: 10_000 });
  outcome = `LEFT for ${new URL(page.url()).host} after ${Date.now() - t0} ms`;
} catch {
  const card = page.getByTestId("sign-in-card");
  await page.waitForTimeout(5000); // give an error state 15 s in all
  const stepNow = await card.getAttribute("data-step");
  outcome = `STILL on ${new URL(page.url()).pathname} after ${Date.now() - t0} ms; card data-step=${stepNow} aria-busy=${await card.getAttribute("aria-busy")}; button text="${(await google.textContent().catch(() => "(gone)"))?.trim()}"`;
}
console.log("OUTCOME:", outcome);
console.log("CONSOLE:", consoleMsgs.length ? "\n  " + consoleMsgs.join("\n  ") : "none");
console.log("PAGE ERRORS:", pageErrors.length ? "\n  " + pageErrors.join("\n  ") : "none");
console.log("CLERK FAPI:", clerk.length ? "\n  " + clerk.join("\n  ") : "none");
await browser.close();
