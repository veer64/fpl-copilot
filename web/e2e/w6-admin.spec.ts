import { expect, test, type BrowserContext, type Page } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import { createHash } from "node:crypto";
import { execFileSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { createTestUser, deleteUser, findTestUsers } from "./clerk-users";
import { sweepPage } from "../scripts/lib/sweep.mjs";
import { API, DB_PREFIX, apiCall, dbEnv, py, signIn, vis } from "./w4";
import { SHOTS5, shot5, sql1 } from "./w5";

/** Prompt W6 PART 3: the owner's /admin page against the scratchpad backend (clerk mode on :8010, the TEST-ONLY admin switch
 *  W6_ADMIN_EMAIL = w6a+clerk_test@example.com, FPL budget 5, Langfuse "dev") and the production build on :3002.
 *   1 user B (not admin): no "Admin" in the menu, /admin -> /home, the API 403
 *   2 B makes 2 real answers (general chat) and thumbs one up, one down   [Anthropic: <= 3 turns, <= $0.40]
 *   3 admin A: "Admin" in the menu -> /admin; every number vs a direct SQL count; 30 bars; sorting; the CSV
 *   4 the thumbs section shows B's thumbs-down with the right question / answer start / trace
 *   5 B deletes the account -> B's spend moves into "Deleted accounts", the totals unchanged
 *   6 Refresh, loading, empty and error states (route mocks), keyboard-only, axe, the contrast sweep (+ the --live script)
 *   7 the phone (390 x 844): stacks, the table scrolls sideways, the menu item, axe, the sweep
 *  Clerk test users w6a / w6b (<= 2, deleted at the end). FPL 0 expected (general chat, no team). */

test.describe.configure({ mode: "serial" });

const A = "w6a";
const B = "w6b";
const REUSE_B = process.env.W6_REUSE_B ? Number(process.env.W6_REUSE_B) : 0;
const STATE = path.join(SHOTS5, "w6_admin_storage_state.json");
const results: string[] = [];
const notes: string[] = [];
const log = (s: string) => console.log(`[W6] ${s}`);
const pass = (s: string) => {
  results.push(s);
  log(`PASS ${s}`);
};
const lowestSeen: { where: string; ratio: number; label: string }[] = [];
const turns: { step: string; seconds: number; usd: number }[] = [];

let ctxA: BrowserContext;
let ctxB: BrowserContext;
let pageA: Page;
let pageB: Page;
let userA = 0;
let userB = 0;
let bThread = "";
let bDown: { message_id: string; question: string; answer: string } | null = null;
let bUp: { message_id: string } | null = null;
let bUsd = 0;
let before: Record<string, number> = {};

const num = (v: unknown) => Number(v);
const close = (a: number, b: number, eps = 1e-6) => Math.abs(a - b) <= eps;

/** the page's raw numbers: every <b data-testid="v-<key>" data-value> */
async function pageValues(p: Page): Promise<Record<string, number>> {
  const pairs = await p.locator("[data-testid^='v-']:visible").evaluateAll((els) => els.map((e) => [e.getAttribute("data-testid")!.slice(2), Number(e.getAttribute("data-value"))]));
  return Object.fromEntries(pairs as [string, number][]);
}

/** the same numbers straight from the laptop database (UTC days), independent of admin.py */
function sqlValues(): Record<string, number> {
  // W7b: real people only (user_id >= 10001); the totals = real users + deleted accounts (turn_id 'deleted'); the owner and
  // the pre-launch testing rows (user_id NULL not 'deleted', 9001 / 9002) are two separate lines
  const day = "date_trunc('day', now() AT TIME ZONE 'UTC') AT TIME ZONE 'UTC'";
  const month = "date_trunc('month', now() AT TIME ZONE 'UTC') AT TIME ZONE 'UTC'";
  const week = "now() - interval '7 days'";
  const real = "user_id >= 10001";
  const counted = "(user_id >= 10001 OR (user_id IS NULL AND coalesce(turn_id, '') = 'deleted'))";
  const q = (sql: string) => num(sql1(sql));
  return {
    users_total: q(`SELECT count(*) FROM app_users WHERE ${real}`),
    sign_ups_today: q(`SELECT count(*) FROM app_users WHERE ${real} AND created_at >= ${day}`),
    sign_ups_7_days: q(`SELECT count(*) FROM app_users WHERE ${real} AND created_at >= ${week}`),
    active_today: q(`SELECT count(*) FROM app_users WHERE ${real} AND last_active_at >= ${day}`),
    active_7_days: q(`SELECT count(*) FROM app_users WHERE ${real} AND last_active_at >= ${week}`),
    answers_today: q(`SELECT count(*) FROM chat_usage WHERE ${counted} AND ts >= ${day}`),
    answers_total: q(`SELECT count(*) FROM chat_usage WHERE ${counted}`),
    usd_today: q(`SELECT coalesce(sum(usd), 0) FROM chat_usage WHERE ${counted} AND ts >= ${day}`),
    usd_month: q(`SELECT coalesce(sum(usd), 0) FROM chat_usage WHERE ${counted} AND ts >= ${month}`),
    usd_total: q(`SELECT coalesce(sum(usd), 0) FROM chat_usage WHERE ${counted}`),
    up_total: q(`SELECT count(*) FROM chat_messages WHERE ${real} AND feedback = 'up'`),
    down_total: q(`SELECT count(*) FROM chat_messages WHERE ${real} AND feedback = 'down'`),
    up_7_days: q(`SELECT count(*) FROM chat_messages WHERE ${real} AND feedback = 'up' AND feedback_at >= ${week}`),
    down_7_days: q(`SELECT count(*) FROM chat_messages WHERE ${real} AND feedback = 'down' AND feedback_at >= ${week}`),
    deleted_usd: q("SELECT coalesce(sum(usd), 0) FROM chat_usage WHERE user_id IS NULL AND coalesce(turn_id, '') = 'deleted'"),
    deleted_answers: q("SELECT count(*) FROM chat_usage WHERE user_id IS NULL AND coalesce(turn_id, '') = 'deleted'"),
    owner_usd: q("SELECT coalesce(sum(usd), 0) FROM chat_usage WHERE user_id = 1"),
    testing_usd: q("SELECT coalesce(sum(usd), 0) FROM chat_usage WHERE (user_id IS NULL AND coalesce(turn_id, '') <> 'deleted') OR user_id IN (9001, 9002)"),
    cap_hits_30: q(`SELECT count(*) FROM cap_hits WHERE ${real} AND hit_at >= ${day} - interval '29 days'`),
  };
}

async function openAdmin(p: Page) {
  await p.goto("/admin");
  await expect(p.locator('[data-testid="admin"][data-state="ready"]:visible')).toBeVisible({ timeout: 30_000 });
}

async function refresh(p: Page) {
  const req = p.waitForRequest((r) => r.url().endsWith("/admin/summary"), { timeout: 15_000 });
  await vis(p, "refresh").click();
  await req;
  await expect(p.locator('[data-testid="admin"][data-state="ready"]:visible')).toBeVisible({ timeout: 30_000 });
}

async function sweep(p: Page, where: string) {
  await p.waitForTimeout(400);
  const r = await sweepPage(p);
  if (r.lowest) lowestSeen.push({ where, ratio: r.lowest.ratio, label: r.lowest.label });
  log(`sweep ${where}: ${r.text.length} text controls, lowest ${r.lowest ? `${r.lowest.ratio.toFixed(2)}:1 ${r.lowest.label}` : "n/a"}, ${r.fails.length} below the bar`);
  expect(r.fails.map((f: { ratio: number; fg: string; bg: string; label: string }) => `${f.ratio}:1 ${f.fg} on ${f.bg} ${f.label}`), `contrast sweep ${where}`).toEqual([]);
}

async function axe(p: Page, where: string) {
  const r = await new AxeBuilder({ page: p }).disableRules(["color-contrast"]).analyze(); // contrast: the computed-colour sweep
  const bad = r.violations.filter((v) => v.impact === "serious" || v.impact === "critical");
  log(`axe ${where}: ${r.violations.length} violations, ${bad.length} serious/critical${r.violations.length ? " -- " + r.violations.map((v) => `${v.impact}:${v.id}`).join(", ") : ""}`);
  expect(bad.map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(" ")).join(" | ")}`), `axe ${where}`).toEqual([]);
}

/** after a full page load Clerk's session object appears a moment after the page is interactive: wait for it before reading a token */
async function clerkReady(p: Page) {
  await expect.poll(() => p.evaluate(() => !!(window as unknown as { Clerk?: { session?: unknown } }).Clerk?.session), { timeout: 20_000 }).toBe(true);
}

async function spent(p: Page): Promise<number> {
  await clerkReady(p);
  const me = await apiCall(p, "get", "/me");
  return Number(me.body.spent_today_usd ?? 0);
}

async function turn(p: Page, step: string, text: string, timeout = 120_000) {
  const total = turns.reduce((a, t) => a + t.usd, 0);
  expect(turns.length < 3 && total < 0.4, `the Anthropic cap (${turns.length} turns, $${total.toFixed(2)})`).toBe(true);
  const b = await spent(p);
  const nAnswers = await p.locator('[data-testid="assistant-message"]:visible').count();
  const t0 = Date.now();
  await vis(p, "chat-input").fill(text);
  await vis(p, "chat-input").press("Enter");
  await expect(p.locator('[data-testid="assistant-message"]:visible, [data-testid^="system-"]:visible')).toHaveCount(nAnswers + 1, { timeout });
  await expect(vis(p, "thinking")).toHaveCount(0, { timeout });
  const seconds = Math.round((Date.now() - t0) / 10) / 100;
  const usd = Math.max(0, (await spent(p)) - b);
  turns.push({ step, seconds, usd });
  log(`turn ${turns.length} (${step}): ${seconds} s, $${usd.toFixed(4)}`);
}

test.beforeAll(async ({ browser }) => {
  fs.mkdirSync(SHOTS5, { recursive: true });
  for (const n of [A, B]) for (const id of await findTestUsers(n)) await deleteUser(id);
  ctxB = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  ctxA = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  pageB = await ctxB.newPage();
  pageA = await ctxA.newPage();
  const counts = await (await pageA.request.get(`${API}/__w6/counts`)).json();
  log(`backend: admin switch ${counts.admin_switch ? "ON" : "OFF"}, langfuse ${counts.langfuse}, FPL budget ${counts.budget}`);
  expect(counts.admin_switch, "the scratchpad backend's W6_ADMIN_EMAIL switch is on").toBe(true);
});

test.afterAll(async ({}) => {
  const counts = await (await pageA.request.get(`${API}/__w6/counts`)).json().catch(() => null);
  for (const n of [A, B]) for (const id of await findTestUsers(n)) await deleteUser(id);
  const left = (await findTestUsers(A)).length + (await findTestUsers(B)).length;
  const lowest = lowestSeen.reduce<{ where: string; ratio: number; label: string } | null>((m, r) => (m === null || r.ratio < m.ratio ? r : m), null);
  const usd = turns.reduce((a, t) => a + t.usd, 0);
  log(`SUMMARY turns ${turns.length} $${usd.toFixed(4)} | FPL live ${counts?.fpl_live ?? "?"} local ${counts?.fpl_local ?? "?"} refused ${counts?.fpl_refused ?? "?"} | lowest contrast ${lowest ? `${lowest.ratio.toFixed(2)}:1 ${lowest.label} on ${lowest.where}` : "n/a"} | clerk test users left ${left} | users A ${userA} B ${userB}`);
  for (const n of notes) log(`NOTE ${n}`);
  for (const r of results) log(`RESULT ${r}`);
  try {
    fs.rmSync(STATE, { force: true });
  } catch {
    /* nothing to remove */
  }
  await ctxA?.close();
  await ctxB?.close();
});

// ---- 1: user B is not the admin --------------------------------------------------------------------------------------------------

test("1 user B (not admin): no Admin item, /admin -> /home, the API 403", async () => {
  test.setTimeout(180_000);
  const clerkB = await createTestUser(B);
  log(`Clerk test user ${B} created: ${clerkB.id.slice(0, 9)}…`);
  if (REUSE_B) {
    // W6_REUSE_B=<user_id>: an earlier run's user B row (test user >= 10001, this email) is re-linked to the fresh Clerk user
    expect(REUSE_B).toBeGreaterThanOrEqual(10_001);
    const n = num(sql1("SELECT count(*) FROM app_users WHERE user_id = %s AND email = %s", [REUSE_B, `${B}+clerk_test@example.com`]));
    expect(n, `user B ${REUSE_B} with that email exists on the laptop`).toBe(1);
    py(`${DB_PREFIX}
cur.execute("UPDATE app_users SET clerk_user_id = %s, profile_fetched_at = now() WHERE user_id = %s AND email = %s", (${JSON.stringify(clerkB.id)}, ${REUSE_B}, ${JSON.stringify(`${B}+clerk_test@example.com`)}))
assert cur.rowcount == 1
conn.commit()
print("relinked")`);
    log(`user B ${REUSE_B} re-linked to the fresh Clerk user (laptop write: app_users.clerk_user_id of that test row)`);
  }
  await signIn(pageB, `${B}+clerk_test@example.com`);
  userB = Number((await apiCall(pageB, "get", "/me")).body.user_id);
  expect(userB).toBeGreaterThanOrEqual(10_001);
  if (REUSE_B) expect(userB).toBe(REUSE_B);
  await vis(pageB, "account-menu").first().click();
  await expect(pageB.locator('[data-testid="delete-account"]')).toHaveAttribute("data-owner", "false", { timeout: 10_000 }); // /me answered
  await expect(pageB.locator('[data-testid="menu-admin"]')).toHaveCount(0);
  await pageB.keyboard.press("Escape");
  await pageB.goto("/admin");
  await pageB.waitForURL("**/home", { timeout: 30_000 });
  const r = await apiCall(pageB, "get", "/admin/summary");
  expect(r.status).toBe(403);
  expect(r.body.detail).toBe("admin only");
  pass(`1 user B ${userB}: no Admin item in the menu; /admin went to /home; GET /admin/summary 403 "admin only"`);
});

// ---- 2: B's two real answers and the thumbs -----------------------------------------------------------------------------------------

test("2 user B: two real answers (general chat), thumb up the first, thumb down the second", async () => {
  test.setTimeout(400_000);
  if (REUSE_B) {
    // a re-run under the Anthropic cap: the answers and thumbs of an earlier run's user B (whose Clerk user the earlier run
    // deleted) are reused -- that row is re-linked to the fresh Clerk user B, so the same account signs in again
    bThread = String(sql1("SELECT thread_id FROM chat_messages WHERE user_id = %s ORDER BY created_at LIMIT 1", [userB]));
    log(`reusing user B ${userB}'s thread ${bThread} from an earlier run (no new agent turns)`);
    notes.push(`2: re-run under the cap -- user B ${userB}'s two answers and thumbs come from an earlier run (W6_REUSE_B)`);
  } else {
    await pageB.goto("/chat");
    await expect(pageB.locator('[data-testid="chat"][data-ready="true"]:visible')).toBeVisible({ timeout: 30_000 });
    await turn(pageB, "B q1", "In one short sentence, what does the Bench Boost chip do in FPL?");
    await turn(pageB, "B q2", "In one short sentence, how many free transfers can an FPL manager bank at most?");
    await expect.poll(async () => pageB.locator('[data-testid="chat"]:visible').getAttribute("data-thread-id"), { timeout: 10_000 }).toMatch(/^th_/);
    bThread = (await pageB.locator('[data-testid="chat"]:visible').getAttribute("data-thread-id"))!;
    const answers = pageB.locator('[data-testid="assistant-message"]:visible');
    await expect(answers).toHaveCount(2);
    await answers.nth(0).locator('[data-testid="thumb-up"]').click();
    await expect(answers.nth(0).locator('[data-testid="thumb-up"]')).toHaveAttribute("aria-pressed", "true");
    await answers.nth(1).locator('[data-testid="thumb-down"]').click();
    await expect(answers.nth(1).locator('[data-testid="thumb-down"]')).toHaveAttribute("aria-pressed", "true");
  }
  await clerkReady(pageB);
  const rows = (await apiCall(pageB, "get", `/threads/${bThread}/messages`)).body as unknown as { role: string; text: string; message_id?: string; feedback?: string }[];
  const a = rows.filter((m) => m.role === "assistant");
  const u = rows.filter((m) => m.role === "user");
  expect(a.length).toBe(2);
  expect(a[0].feedback).toBe("up");
  expect(a[1].feedback).toBe("down");
  bUp = { message_id: a[0].message_id! };
  bDown = { message_id: a[1].message_id!, question: u[1].text, answer: a[1].text };
  bUsd = num(sql1("SELECT coalesce(sum(usd), 0) FROM chat_usage WHERE user_id = %s", [userB]));
  log(`B thread ${bThread}: up ${bUp.message_id.slice(0, 12)}… down ${bDown.message_id.slice(0, 12)}…; B's spend $${bUsd.toFixed(4)}; answer 2 is ${bDown.answer.length} chars`);
  pass(`2 user B: 2 real answers ($${turns.reduce((s, t) => s + t.usd, 0).toFixed(4)}), thumb up + thumb down stored (feedback rows up / down)`);
});

// ---- 3: the admin's page vs SQL ----------------------------------------------------------------------------------------------------

test("3 admin A: the Admin item -> /admin; every number matches SQL; 30 bars; sorting; the CSV", async () => {
  test.setTimeout(300_000);
  log(`Clerk test user ${A} created: ${(await createTestUser(A)).id.slice(0, 9)}…`);
  await signIn(pageA, `${A}+clerk_test@example.com`);
  const me = (await apiCall(pageA, "get", "/me")).body;
  userA = Number(me.user_id);
  expect(me.is_admin, "the switch makes A's /me say is_admin (the row is untouched)").toBe(true);
  expect(num(sql1("SELECT is_admin::int FROM app_users WHERE user_id = %s", [userA])), "the laptop row stays is_admin FALSE").toBe(0);
  await vis(pageA, "account-menu").first().click();
  await expect(pageA.locator('[data-testid="menu-admin"]')).toBeVisible({ timeout: 10_000 });
  await shot5(pageA, "w6_menu_admin_item");
  await pageA.locator('[data-testid="menu-admin"]').click();
  await pageA.waitForURL("**/admin", { timeout: 30_000 });
  await expect(pageA.locator('[data-testid="admin"][data-state="ready"]:visible')).toBeVisible({ timeout: 30_000 });
  await expect(pageA).toHaveTitle(/^Admin/);
  await expect(pageA.locator("h1:visible")).toHaveCount(1);
  await expect(vis(pageA, "as-of")).toContainText("UTC");

  // every number vs SQL
  const pv = await pageValues(pageA);
  const sv = sqlValues();
  const keys = ["users_total", "sign_ups_today", "sign_ups_7_days", "active_today", "active_7_days", "answers_today", "answers_total", "usd_today", "usd_month", "usd_total", "up_total", "down_total", "up_7_days", "down_7_days"];
  const diffs: string[] = [];
  for (const k of keys) {
    const ok = close(pv[k], sv[k]);
    log(`SQL vs page ${k}: ${sv[k]} vs ${pv[k]} ${ok ? "=" : "DIFFERENT"}`);
    if (!ok) diffs.push(k);
  }
  expect(diffs, "every top number equals its SQL count").toEqual([]);
  const userRows = await pageA.locator('[data-testid="user-row"]:visible').count();
  log(`SQL vs page users rows: ${sv.users_total} vs ${userRows}`);
  expect(userRows).toBe(sv.users_total);
  const hitRows = await pageA.locator('[data-testid="cap-hit"]:visible').count();
  log(`SQL vs page limit hits (30 days): ${sv.cap_hits_30} vs ${hitRows}`);
  expect(hitRows).toBe(sv.cap_hits_30);
  const deletedRow = pageA.locator('[data-testid="deleted-row"]:visible');
  const delUsd = (await deletedRow.count()) ? num(await deletedRow.getAttribute("data-usd")) : 0;
  log(`SQL vs page deleted-accounts spend: ${sv.deleted_usd} vs ${delUsd} (${sv.deleted_answers} anonymous rows)`);
  expect(close(delUsd, sv.deleted_usd)).toBe(true);
  // W7b: the two grey lines outside the totals
  const ownerRow = pageA.locator('[data-testid="owner-row"]:visible');
  const ownerUsd = (await ownerRow.count()) ? num(await ownerRow.getAttribute("data-usd")) : 0;
  const testingRow = pageA.locator('[data-testid="testing-row"]:visible');
  const testingUsd = (await testingRow.count()) ? num(await testingRow.getAttribute("data-usd")) : 0;
  log(`SQL vs page owner line: ${sv.owner_usd} vs ${ownerUsd}; testing line: ${sv.testing_usd} vs ${testingUsd}`);
  expect(close(ownerUsd, sv.owner_usd)).toBe(true);
  expect(close(testingUsd, sv.testing_usd)).toBe(true);
  const splitTotal = await pageA.locator('[data-testid="signin-split"] li:visible').evaluateAll((els) => els.reduce((a, e) => a + Number(e.getAttribute("data-count")), 0));
  log(`SQL vs page sign-in split total: ${sv.users_total} vs ${splitTotal}`);
  expect(splitTotal).toBe(sv.users_total);
  before = { ...pv, deleted_usd: delUsd, users_rows: userRows };

  // the chart: 30 bars, hover shows the date + count
  const bars = pageA.locator('[data-testid="signups-chart"]:visible .ad-bar');
  await expect(bars).toHaveCount(30);
  const lastDay = (await bars.last().getAttribute("data-day"))!;
  const lastN = (await bars.last().getAttribute("data-n"))!;
  await bars.last().hover();
  await expect(vis(pageA, "chart-tip")).toHaveClass(/on/);
  const tip = (await vis(pageA, "chart-tip").textContent())!;
  expect(tip).toContain(`${lastN} sign-up`);
  expect(lastDay).toBe(new Date().toISOString().slice(0, 10));
  log(`chart: 30 bars, last ${lastDay} (${lastN}); tip "${tip}"`);
  await expect(pageA.locator('[data-testid="signups-chart"]:visible table.ad-sr tbody tr')).toHaveCount(30);

  // sorting on 3 columns
  const table = vis(pageA, "users-table");
  await expect(table).toHaveAttribute("data-sort", "last_active");
  await expect(table).toHaveAttribute("data-dir", "desc");
  const namesOf = async () => table.locator("[data-testid='user-row'] td.ad-name").evaluateAll((tds) => tds.map((td) => (td.firstChild?.textContent ?? "").trim().toLowerCase()));
  await vis(pageA, "sort-name").click();
  await expect(table.locator("th").nth(0)).toHaveAttribute("aria-sort", "ascending");
  const names = (await namesOf()).filter((n) => n !== "—");
  expect(names, "names ascending").toEqual([...names].sort((x, y) => x.localeCompare(y, "en")));
  await vis(pageA, "sort-name").click();
  await expect(table.locator("th").nth(0)).toHaveAttribute("aria-sort", "descending");
  const names2 = (await namesOf()).filter((n) => n !== "—");
  expect(names2, "names descending").toEqual([...names2].sort((x, y) => y.localeCompare(x, "en")));
  await vis(pageA, "sort-answers").click();
  await expect(table.locator("th").nth(5)).toHaveAttribute("aria-sort", "descending");
  const answers = await table.locator("[data-testid='user-row'] td:nth-child(6)").evaluateAll((tds) => tds.map((td) => Number(td.textContent)));
  expect(answers, "answers descending").toEqual([...answers].sort((x, y) => y - x));
  await vis(pageA, "sort-joined").click();
  await expect(table.locator("th").nth(3)).toHaveAttribute("aria-sort", "descending");
  const idsPage = await table.locator("[data-testid='user-row']").evaluateAll((trs) => trs.map((tr) => Number(tr.getAttribute("data-user-id"))));
  const idsSql = sql1("SELECT json_agg(user_id ORDER BY created_at DESC NULLS LAST, user_id) FROM app_users WHERE user_id >= 10001") as number[];
  expect(idsPage, "joined newest first = SQL order").toEqual(idsSql);
  log(`sorting: name asc/desc, answers desc, joined desc all in order (${idsPage.length} rows)`);

  // the CSV: the P7 file, through the page's button, row count = the table's user rows
  const dl = pageA.waitForEvent("download", { timeout: 30_000 });
  await vis(pageA, "download-csv").click();
  const download = await dl;
  const csvPath = path.join(SHOTS5, "w6_users.csv");
  await download.saveAs(csvPath);
  const csv = fs.readFileSync(csvPath, "utf8");
  const lines = csv.split("\n").filter((l) => l.length > 0);
  expect(lines[0]).toBe("name,email,sign-in method,joined,last active,answers,$ total");
  log(`CSV: ${download.suggestedFilename()}, ${lines.length - 1} data rows vs ${userRows} table rows`);
  expect(lines.length - 1).toBe(userRows);
  fs.rmSync(csvPath, { force: true }); // real emails live in it: not kept
  await shot5(pageA, "w6_admin_desktop", true);
  pass(`3 admin A ${userA}: Admin item -> /admin; ${keys.length} numbers + users rows + limit hits + deleted spend + split = SQL; 30 bars; sorting on name / answers / joined; CSV ${lines.length - 1} rows = table`);
});

// ---- 4: the thumbs section -----------------------------------------------------------------------------------------------------------

test("4 the thumbs section lists B's thumbs-down with the right question, answer start and trace", async () => {
  test.setTimeout(120_000);
  expect(bDown).not.toBeNull();
  const fb = vis(pageA, "feedback");
  const row = fb.locator('[data-testid="down-row"]').first();
  await expect(row).toHaveAttribute("data-message-id", bDown!.message_id);
  const name = (await row.locator('[data-testid="down-name"]').textContent())!.trim();
  const dbName = sql1("SELECT name FROM app_users WHERE user_id = %s", [userB]) as string | null;
  expect(name).toBe(dbName ?? `user #${userB}`);
  const q = (await row.locator('[data-testid="down-question"]').textContent())!.trim();
  expect(q).toBe(`“${bDown!.question}”`);
  const a = (await row.locator('[data-testid="down-answer"]').textContent())!;
  expect(a.startsWith(bDown!.answer.slice(0, 300))).toBe(true);
  if (bDown!.answer.length > 300) expect(a).toContain(`(${bDown!.answer.length} chars)`);
  const traceId = (await row.getAttribute("data-trace-id"))!;
  expect(traceId).toBe(createHash("sha256").update(bDown!.message_id).digest("hex").slice(0, 32));
  const link = row.locator('[data-testid="open-langfuse"]');
  let traceNote = "";
  if (await link.count()) {
    const href = (await link.getAttribute("href"))!;
    expect(href).toMatch(new RegExp(`/project/[^/]+/traces/${traceId}$`));
    expect(await link.getAttribute("target")).toBe("_blank");
    const env = dbEnv();
    if (env.LANGFUSE_PUBLIC_KEY && env.LANGFUSE_SECRET_KEY && env.LANGFUSE_BASE_URL) {
      const auth = Buffer.from(`${env.LANGFUSE_PUBLIC_KEY}:${env.LANGFUSE_SECRET_KEY}`).toString("base64");
      const host = env.LANGFUSE_BASE_URL.replace(/\/$/, "");
      expect(href.startsWith(host), "the link is on the configured host").toBe(true);
      let found: { value?: string; stringValue?: string }[] = [];
      let traceOk = false;
      let observations = 0;
      let traceStatus = 0;
      for (let i = 0; i < 12 && !(traceOk && found.length); i++) {
        if (i) await pageA.waitForTimeout(5000);
        // the v5 SDK's traces are read through the observations (the Langfuse v1 lesson: the root is isRootObservation); the
        // /traces/{id} status is reported beside it
        const t = await fetch(`${host}/api/public/traces/${traceId}`, { headers: { Authorization: `Basic ${auth}` } });
        traceStatus = t.status;
        const o = await fetch(`${host}/api/public/v2/observations?traceId=${traceId}&limit=50`, { headers: { Authorization: `Basic ${auth}` } });
        if (o.status === 200) observations = (((await o.json()) as { data?: unknown[] }).data ?? []).length;
        traceOk = traceStatus === 200 || observations > 0;
        const s = await fetch(`${host}/api/public/v3/scores?traceId=${traceId}&name=user_feedback`, { headers: { Authorization: `Basic ${auth}` } });
        if (s.status === 200) found = ((await s.json()) as { data: { value?: string; stringValue?: string }[] }).data ?? [];
      }
      log(`Langfuse: trace ${traceId}: /traces/{id} HTTP ${traceStatus}, ${observations} observations; user_feedback scores ${JSON.stringify(found.map((x) => x.stringValue ?? x.value))}`);
      expect(traceOk, "the linked trace exists on the host (observations under that trace id)").toBe(true);
      expect(found.some((x) => (x.stringValue ?? x.value) === "down"), "it carries user_feedback = down").toBe(true);
      traceNote = `link ${href.replace(traceId, "<trace>")} -> the trace exists (${observations} observations${traceStatus === 200 ? ", /traces 200" : `, /traces HTTP ${traceStatus}`}) with user_feedback=down (API); the UI open itself NOT DETERMINED (needs the owner's Langfuse login)`;
    } else {
      traceNote = `link ${href}; Langfuse API check skipped (no keys in .env)`;
      notes.push("4: the Langfuse trace was not checked through the API (no keys)");
    }
  } else {
    await expect(row.locator('[data-testid="trace-id-only"]')).toContainText(traceId);
    traceNote = "no project id (Langfuse off on the harness): the trace id alone is shown -- NOT DETERMINED whether the link opens the right trace";
    notes.push("4: Langfuse off on the harness -> trace id only; the link NOT DETERMINED");
  }
  const pv = await pageValues(pageA);
  const sv = sqlValues();
  for (const k of ["up_total", "down_total", "up_7_days", "down_7_days"]) {
    log(`SQL vs page ${k}: ${sv[k]} vs ${pv[k]}`);
    expect(pv[k]).toBe(sv[k]);
  }
  await fb.scrollIntoViewIfNeeded();
  await shot5(pageA, "w6_admin_thumbs");
  pass(`4 thumbs: up/down totals = SQL; B's thumbs-down row by message_id with the question, the answer's first ${Math.min(300, bDown!.answer.length)} chars, trace ${traceId.slice(0, 8)}…; ${traceNote}`);
});

// ---- 5: B deletes the account ------------------------------------------------------------------------------------------------------------

test("5 B deletes the account -> B's spend moves into Deleted accounts; totals unchanged", async () => {
  test.setTimeout(180_000);
  const bAnswers = num(sql1("SELECT count(*) FROM chat_usage WHERE user_id = %s", [userB]));
  await pageB.goto("/home");
  await vis(pageB, "account-menu").first().click();
  await expect(pageB.locator('[data-testid="delete-account"]')).toHaveAttribute("data-owner", "false", { timeout: 10_000 });
  await pageB.locator('[data-testid="delete-account"]').click();
  await expect(vis(pageB, "delete-account-dialog")).toBeVisible();
  await vis(pageB, "confirm-delete").click();
  await pageB.waitForURL("**/login**", { timeout: 60_000 });
  await expect(pageB.locator('[data-testid="deleted-note"]')).toBeVisible({ timeout: 20_000 });
  expect(num(sql1("SELECT count(*) FROM app_users WHERE user_id = %s", [userB]))).toBe(0);
  await refresh(pageA);
  const pv = await pageValues(pageA);
  const sv = sqlValues();
  const deletedRow = pageA.locator('[data-testid="deleted-row"]:visible');
  await expect(deletedRow).toBeVisible();
  const delUsd = num(await deletedRow.getAttribute("data-usd"));
  log(`deleted accounts: before $${before.deleted_usd.toFixed(4)} + B $${bUsd.toFixed(4)} = page $${delUsd.toFixed(4)} (SQL $${sv.deleted_usd.toFixed(4)}, ${sv.deleted_answers} anonymous rows)`);
  expect(close(delUsd, before.deleted_usd + bUsd)).toBe(true);
  expect(close(delUsd, sv.deleted_usd)).toBe(true);
  log(`totals: usd_total ${before.usd_total} -> ${pv.usd_total}; answers_total ${before.answers_total} -> ${pv.answers_total}; users ${before.users_total} -> ${pv.users_total}`);
  expect(close(pv.usd_total, before.usd_total)).toBe(true);
  expect(pv.answers_total).toBe(before.answers_total);
  expect(pv.users_total).toBe(before.users_total - 1);
  expect(await pageA.locator('[data-testid="user-row"]:visible').count()).toBe(before.users_rows - 1);
  expect(await pageA.locator(`[data-testid="down-row"][data-message-id="${bDown!.message_id}"]`).count(), "the deleted account's thumbs go with its messages").toBe(0);
  expect(pv.down_total).toBe(sv.down_total);
  await pageA.locator('[data-testid="card-users"]:visible').scrollIntoViewIfNeeded();
  await shot5(pageA, "w6_admin_deleted_accounts");
  pass(`5 B deleted: Deleted accounts $${delUsd.toFixed(4)} = $${before.deleted_usd.toFixed(4)} + $${bUsd.toFixed(4)} (${bAnswers} rows anonymised); usd_total and answers_total unchanged; users -1; B's thumbs-down row gone`);
});

// ---- 6: states, keyboard, axe, the sweep -----------------------------------------------------------------------------------------------------

test("6 Refresh, loading, empty and error states; keyboard-only; axe; the contrast sweep incl. the --live script", async () => {
  test.setTimeout(300_000);
  await openAdmin(pageA);
  // Refresh = one request, no polling
  const seen = { n: 0 };
  const onReq = (r: { url: () => string }) => {
    if (r.url().endsWith("/admin/summary")) seen.n++;
  };
  pageA.on("request", onReq);
  await refresh(pageA);
  await pageA.waitForTimeout(4000);
  pageA.off("request", onReq);
  expect(seen.n, "Refresh made exactly one read and nothing polled after it").toBe(1);

  // loading: a slow answer shows the shimmer
  await pageA.route("**/admin/summary", async (route) => {
    await new Promise((r) => setTimeout(r, 1500));
    await route.continue();
  });
  await vis(pageA, "refresh").click();
  await expect(vis(pageA, "admin-skeleton")).toBeVisible();
  await expect(pageA.locator('[data-testid="admin"][data-state="loading"]:visible')).toBeVisible();
  await shot5(pageA, "w6_admin_loading");
  await expect(pageA.locator('[data-testid="admin"][data-state="ready"]:visible')).toBeVisible({ timeout: 30_000 });
  await pageA.unroute("**/admin/summary");

  // empty: an all-zero summary
  const today = new Date();
  const days = Array.from({ length: 30 }, (_, i) => ({ day: new Date(today.getTime() - (29 - i) * 86_400_000).toISOString().slice(0, 10), n: 0 }));
  const empty = { at: today.toISOString(), users_total: 0, sign_ups_today: 0, sign_ups_7_days: 0, active_today: 0, active_7_days: 0, answers_today: 0, answers_total: 0, usd_today: 0, usd_month: 0, usd_total: 0, sign_ups_per_day: days, users: [], deleted_accounts: { answers: 0, usd: 0 }, owner_use: { answers: 0, usd: 0 }, testing_use: { answers: 0, usd: 0 }, cap_hits: [], cap_hits_today: 0, cap_hits_total: 0, sign_in_methods: {}, feedback: { up_total: 0, down_total: 0, up_7_days: 0, down_7_days: 0, recent_down: [] }, langfuse: { host: null, project_id: null } };
  await pageA.route("**/admin/summary", (route) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(empty) }));
  await refresh(pageA);
  await expect(vis(pageA, "signups-empty")).toHaveText("No sign-ups yet.");
  await expect(pageA.locator(".ad-empty-cell:visible")).toHaveText("No users yet.");
  await expect(vis(pageA, "hits-empty")).toHaveText("No limit hits in the last 30 days.");
  await expect(vis(pageA, "down-empty")).toHaveText("No thumbs-down yet.");
  await expect(pageA.locator('[data-testid="signups-chart"]:visible .ad-bar')).toHaveCount(30);
  await shot5(pageA, "w6_admin_empty", true);
  await pageA.unroute("**/admin/summary");

  // error: 500 -> the error card with Retry; Retry reads again
  await pageA.route("**/admin/summary", (route) => route.fulfill({ status: 500, contentType: "application/json", body: JSON.stringify({ detail: "boom" }) }));
  await vis(pageA, "refresh").click();
  await expect(vis(pageA, "error-admin-data")).toBeVisible({ timeout: 15_000 });
  await expect(pageA.locator('[data-testid="admin"][data-state="error"]:visible')).toBeVisible();
  await expect(vis(pageA, "error-admin-data")).toContainText("Couldn’t load admin data.");
  await shot5(pageA, "w6_admin_error");
  await pageA.unroute("**/admin/summary");
  await vis(pageA, "error-admin-data").getByRole("button", { name: "Retry" }).click();
  await expect(pageA.locator('[data-testid="admin"][data-state="ready"]:visible')).toBeVisible({ timeout: 30_000 });

  // keyboard-only: Tab to Refresh -> Enter; Tab to the Name header -> Enter sorts; Tab to a bar -> the tip shows; focus is visible
  const focused = () => pageA.evaluate(() => (document.activeElement as HTMLElement | null)?.getAttribute("data-testid") ?? (document.activeElement as HTMLElement | null)?.className ?? "");
  const outline = () => pageA.evaluate(() => {
    const cs = getComputedStyle(document.activeElement as Element);
    return `${cs.outlineWidth} ${cs.outlineStyle} ${cs.outlineColor}`;
  });
  await pageA.locator("body").click({ position: { x: 5, y: 400 } });
  let hops = 0;
  while ((await focused()) !== "refresh" && hops < 40) {
    await pageA.keyboard.press("Tab");
    hops++;
  }
  expect(await focused()).toBe("refresh");
  const refreshOutline = await outline();
  expect(refreshOutline, "the focus ring is 2px #3BE8FF").toBe("2px solid rgb(59, 232, 255)");
  const req = pageA.waitForRequest((r) => r.url().endsWith("/admin/summary"), { timeout: 15_000 });
  await pageA.keyboard.press("Enter");
  await req;
  await expect(pageA.locator('[data-testid="admin"][data-state="ready"]:visible')).toBeVisible({ timeout: 30_000 });
  hops = 0;
  while ((await focused()) !== "refresh" && hops < 40) {
    await pageA.keyboard.press("Tab");
    hops++;
  }
  hops = 0;
  while (!/^ad-bar/.test(await focused()) && hops < 40) {
    await pageA.keyboard.press("Tab");
    hops++;
  }
  expect(await focused()).toMatch(/^ad-bar/);
  await expect(vis(pageA, "chart-tip")).toHaveClass(/on/);
  const barOutline = await outline();
  expect(barOutline).toBe("2px solid rgb(59, 232, 255)");
  hops = 0;
  while ((await focused()) !== "sort-name" && hops < 60) {
    await pageA.keyboard.press("Tab");
    hops++;
  }
  expect(await focused()).toBe("sort-name");
  await pageA.keyboard.press("Enter");
  await expect(vis(pageA, "users-table").locator("th").nth(0)).toHaveAttribute("aria-sort", "ascending");
  log(`keyboard: Refresh reached and run by Enter (ring ${refreshOutline}); a chart bar focused (tip shown, ring ${barOutline}); the Name header sorted by Enter`);

  // axe + the sweep, desktop
  await axe(pageA, "/admin @1440");
  await sweep(pageA, "/admin signed in @1440");

  // the --live script with the admin session's storage state (adds /admin to its signed-out sweep)
  await ctxA.storageState({ path: STATE });
  let liveOut = "";
  let liveOk = false;
  try {
    liveOut = execFileSync("node", ["scripts/contrast_public.mjs", "--live", process.env.E2E_BASE_URL ?? "http://localhost:3002", "--storage", STATE], { cwd: process.cwd(), encoding: "utf8", timeout: 240_000 });
    liveOk = true;
  } catch (err) {
    liveOut = String((err as { stdout?: string }).stdout ?? err);
  }
  const liveLines = liveOut.split(/\r?\n/).filter((l) => /^live |^selftest|signed out/.test(l));
  for (const l of liveLines) log(`--live: ${l}`);
  if (!liveOk) notes.push("6: `node scripts/contrast_public.mjs --live --storage` did not pass (see the --live lines); the in-page sweep of /admin is the contrast evidence");
  expect(liveOk, "the --live sweep incl. /admin (signed in through the saved storage state) passes").toBe(true);
  pass(`6 Refresh (1 request, no polling), loading shimmer, empty states, error card + Retry; keyboard-only run with the 2px #3BE8FF ring; axe 0 serious/critical; sweep /admin @1440 PASS; --live sweep incl. /admin PASS`);
});

// ---- 7: the phone ----------------------------------------------------------------------------------------------------------------

test("7 phone 390x844: the Admin item, the page stacks, the table scrolls sideways, axe, the sweep", async ({ browser }) => {
  test.setTimeout(240_000);
  const ctx = await browser.newContext({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true });
  const p = await ctx.newPage();
  try {
    await signIn(p, `${A}+clerk_test@example.com`);
    await vis(p, "account-menu").first().click();
    await expect(p.locator('[data-testid="menu-admin"]')).toBeVisible({ timeout: 10_000 });
    await p.locator('[data-testid="menu-admin"]').click();
    await p.waitForURL("**/admin", { timeout: 30_000 });
    await expect(p.locator('[data-testid="admin"][data-state="ready"]:visible')).toBeVisible({ timeout: 30_000 });
    const scrollW = await p.evaluate(() => document.documentElement.scrollWidth);
    expect(scrollW, "no horizontal page overflow").toBeLessThanOrEqual(390);
    const two = p.locator(".ad-grid2:visible > section");
    const b0 = (await two.nth(0).boundingBox())!;
    const b1 = (await two.nth(1).boundingBox())!;
    expect(Math.round(b0.x)).toBe(Math.round(b1.x));
    expect(b1.y).toBeGreaterThan(b0.y + b0.height - 1);
    const tbl = p.locator("table.ad-table:visible");
    const dims = await tbl.evaluate((el) => ({ sw: el.scrollWidth, cw: el.clientWidth, ov: getComputedStyle(el).overflowX }));
    expect(dims.sw, "the table scrolls sideways").toBeGreaterThan(dims.cw);
    expect(dims.ov).toBe("auto");
    for (const id of ["account-menu", "sound-toggle"]) {
      const bb = (await vis(p, id).first().boundingBox())!;
      expect(bb.x + bb.width).toBeLessThanOrEqual(390);
    }
    await expect(p.locator('[data-testid="signups-chart"]:visible .ad-bar')).toHaveCount(30);
    log(`phone: scrollWidth ${scrollW}, the two cards stacked (x ${Math.round(b0.x)} / ${Math.round(b1.x)}), table ${dims.sw} > ${dims.cw} (${dims.ov})`);
    await shot5(p, "w6_admin_phone", true);
    await p.evaluate(() => window.scrollTo(0, 0));
    await shot5(p, "w6_admin_phone_top");
    await axe(p, "/admin @390");
    await sweep(p, "/admin signed in @390");
    pass(`7 phone: Admin item; /admin stacks (no overflow, scrollWidth ${scrollW}); the table scrolls sideways; axe 0 serious/critical; sweep PASS`);
  } finally {
    await ctx.close();
  }
});
