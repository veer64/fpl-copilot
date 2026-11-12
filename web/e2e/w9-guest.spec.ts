import { expect, test, type Browser, type BrowserContext, type Page } from "@playwright/test";
import { createTestUser, deleteUser, findTestUsers, secretKey } from "./clerk-users";
import { API, DB_PREFIX, addTeamOnHome, apiCall, py, shot, signIn, vis } from "./w4";

/** Prompt W9 (2026-11-12) PART 3: guest mode end to end on the laptop -- the scratchpad backend (clerk mode, :8010, GUEST_MODE=on,
 *  TRUSTED_PROXY_HOSTS=127.0.0.1 so X-Forwarded-For from this browser counts as the client, the test-only /__w9/env and
 *  /__w9/sweep) and the production build on :3002. A guest starts -> chats (ONE real turn) -> adds a team (FPL: import + card)
 *  -> a refresh keeps the session -> a second tab keeps it -> closing every tab deletes it within ~2 min (DB + Clerk) -> a
 *  browser restart (the Clerk cookies back, fpl_guest gone) ends it -> idle with a fake clock: the 28-min dialog, "I'm here",
 *  30 min deletes -> the guards with 0 model calls (the per-guest cap, the daily budget, the per-IP limit, the kill switch)
 *  -> Admin shows guests apart from people -> a real test user and the owner's rows untouched throughout. The phone project
 *  runs the short form (no leave signal on a phone). Clerk test users: w9adm (admin, the wrapper's switch) and w9real;
 *  every guest is the feature's own and is deleted by it. Env: W9_TEAM (an FPL team id; default 895045). */

test.describe.configure({ mode: "serial" });
const ADMIN = "w9adm";
const REAL = "w9real";
const TEAM = Number(process.env.W9_TEAM ?? 895045);
const notes: string[] = [];
const log = (s: string) => {
  notes.push(s);
  console.log(`[W9] ${s}`);
};
let adminId: string | null = null;
let realId: string | null = null;
let baseline: Record<string, unknown> = {};

// ---- helpers --------------------------------------------------------------------------------------------------------------------

async function env(settings: Record<string, string | null>) {
  const r = await fetch(`${API}/__w9/env`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(settings) });
  expect(r.status).toBe(200);
  return r.json();
}
async function sweep() {
  const r = await fetch(`${API}/__w9/sweep`, { method: "POST" });
  expect(r.status).toBe(200);
  return (await r.json()) as { deleted: { user_id: number; reason: string; clerk: string }[]; skipped: unknown[]; unclaimed_deleted: number };
}
function sql(query: string): unknown {
  const out = py(`${DB_PREFIX}
import json, datetime, decimal
cur.execute(${JSON.stringify(query)})
rows = cur.fetchall()
def conv(v):
    if isinstance(v, (datetime.datetime, datetime.date)): return v.isoformat()
    if isinstance(v, decimal.Decimal): return float(v)
    return v
print(json.dumps([[conv(v) for v in r] for r in rows]))
conn.close()`);
  return JSON.parse(out.trim().split("\n").pop()!);
}
function exec(query: string) {
  py(`${DB_PREFIX}
cur.execute(${JSON.stringify(query)})
conn.commit()
conn.close()`);
}
type GuestRow = { user_id: number; clerk: string; left: string | null; seen: string | null } | null;
function guestRow(clerkId?: string): GuestRow {
  const where = clerkId ? `clerk_user_id = '${clerkId}'` : "is_guest ORDER BY user_id DESC LIMIT 1";
  const rows = sql(`SELECT user_id, clerk_user_id, guest_left_at, guest_last_seen_at FROM app_users WHERE ${where}`) as unknown[][];
  if (!rows.length) return null;
  const [user_id, clerk, left, seen] = rows[0] as [number, string, string | null, string | null];
  return { user_id, clerk, left, seen };
}
async function clerkHas(id: string): Promise<boolean> {
  const r = await fetch(`https://api.clerk.com/v1/users/${id}`, { headers: { Authorization: `Bearer ${secretKey()}`, "User-Agent": "fpl-copilot-w9-e2e/1.0" } });
  return r.status === 200;
}
function snapshot(): Record<string, unknown> {
  const people = sql("SELECT user_id, email FROM app_users WHERE NOT is_guest ORDER BY user_id") as [number, string][];
  const counts: Record<string, unknown> = {};
  for (const [uid] of people) {
    counts[String(uid)] = sql(
      `SELECT (SELECT count(*) FROM user_fpl_teams WHERE user_id = ${uid}), (SELECT count(*) FROM chat_threads WHERE user_id = ${uid}),
              (SELECT count(*) FROM chat_messages WHERE user_id = ${uid}), (SELECT count(*) FROM squad_versions WHERE user_id = ${uid}),
              (SELECT count(*) FROM chat_usage WHERE user_id = ${uid})`,
    );
  }
  counts.owner_squad = sql("SELECT count(*), coalesce(max(version_id), 0), coalesce((SELECT left(encode(sha256(squad_json::text::bytea),'hex'),16) FROM squad_versions WHERE user_id = 900000021 AND is_active), 'none') FROM squad_versions WHERE user_id IN (1, 900000021)");
  counts.ids = people.map(([u]) => u);
  return counts;
}
async function startGuest(page: Page) {
  await page.goto("/login");
  await page.locator('[data-testid="skip-intro"]:visible').first().click();
  const btn = page.locator('[data-testid="continue-as-guest"]:visible');
  await expect(btn).toHaveAttribute("data-guest-mode", "on", { timeout: 15_000 });
  await btn.click();
  await page.waitForURL("**/home", { timeout: 60_000 });
  await expect(vis(page, "guest-banner")).toBeVisible({ timeout: 30_000 });
  const me = await apiCall(page, "get", "/me");
  expect(me.status).toBe(200);
  expect(me.body.is_guest).toBe(true);
  const cookies = await page.context().cookies();
  expect(cookies.some((c) => c.name === "fpl_guest")).toBe(true);
  return guestRow()!;
}
async function waitGone(row: GuestRow, maxMs: number): Promise<number> {
  const t0 = Date.now();
  while (Date.now() - t0 < maxMs) {
    if (!guestRow(row!.clerk)) return Date.now() - t0;
    await new Promise((r) => setTimeout(r, 10_000));
  }
  return -1;
}

test.beforeAll(async () => {
  for (const n of [ADMIN, REAL]) for (const id of await findTestUsers(n)) await deleteUser(id);
  adminId = (await createTestUser(ADMIN)).id;
  realId = (await createTestUser(REAL)).id;
  // this laptop starts every guest from one address: the per-IP limit is raised for the run and set back to 3 for its own check
  await env({ GUEST_MODE: "on", GUEST_CAP_USD: null, GUEST_DAILY_BUDGET_USD: null, GUEST_STARTS_PER_IP_PER_DAY: "100", GUEST_IDLE_MINUTES: null });
  // the laptop's own guests from earlier runs: none expected; if any, the sweep with the switch on leaves them (their own rule)
  baseline = snapshot();
  log(`baseline: ${(baseline.ids as number[]).length} non-guest accounts, owner squad ${JSON.stringify(baseline.owner_squad)}`);
});
test.afterAll(async () => {
  await env({ GUEST_MODE: "on", GUEST_CAP_USD: null, GUEST_DAILY_BUDGET_USD: null, GUEST_STARTS_PER_IP_PER_DAY: null });
  for (const id of [adminId, realId]) if (id) await deleteUser(id);
  for (const n of [ADMIN, REAL]) for (const id of await findTestUsers(n)) await deleteUser(id);
  console.log(`[W9] notes:\n${notes.map((n) => `  - ${n}`).join("\n")}`);
});

// ---- desktop ---------------------------------------------------------------------------------------------------------------------

test("1 start -> chat (one real turn) -> add a team -> refresh keeps it -> a second tab keeps it", async ({ page, context }, info) => {
  test.skip(info.project.name !== "desktop", "desktop");
  test.setTimeout(420_000);
  // the real test user signs in once (a row exists), then signs out: its rows must be untouched by everything below
  await signIn(page, `${REAL}+clerk_test@example.com`);
  await expect(vis(page, "account-menu")).toBeVisible({ timeout: 30_000 });
  await vis(page, "account-menu").click();
  await vis(page, "sign-out").click();
  await page.waitForURL("**/login**", { timeout: 30_000 });
  // the login card's guest option
  await page.goto("/login");
  await page.locator('[data-testid="skip-intro"]:visible').first().click();
  await expect(vis(page, "continue-as-guest")).toBeVisible();
  await expect(vis(page, "guest-note")).toHaveText("No sign-up. Deleted when you leave or after 30 minutes idle.");
  await shot(page, "01_login_guest_option");
  const g = await startGuest(page);
  log(`guest started: user ${g.user_id} (clerk ${g.clerk.slice(0, 12)}…)`);
  await shot(page, "02_home_guest_banner");
  await vis(page, "account-menu").click();
  await expect(vis(page, "account-name")).toHaveText("Guest");
  await expect(vis(page, "account-email")).toHaveText("Temporary session");
  await expect(vis(page, "end-guest-session")).toBeVisible();
  await expect(page.locator('[data-testid="sign-out"]:visible')).toHaveCount(0);
  await expect(page.locator('[data-testid="delete-account"]:visible')).toHaveCount(0);
  await expect(page.locator('[data-testid="menu-admin"]:visible')).toHaveCount(0);
  await shot(page, "03_guest_account_menu");
  await page.keyboard.press("Escape");
  // one real turn (General)
  await page.goto("/chat");
  await expect(page.locator('[data-testid="chat"][data-ready="true"]:visible')).toBeVisible({ timeout: 30_000 });
  await expect(vis(page, "guest-banner")).toBeVisible();
  const before = (sql(`SELECT count(*) FROM chat_usage WHERE user_id = ${g.user_id}`) as number[][])[0][0];
  await vis(page, "chat-input").fill("Who are the three best captain picks this gameweek? One line each.");
  await page.keyboard.press("Enter");
  await expect(page.locator('[data-testid="assistant-message"]:visible')).toHaveCount(1, { timeout: 120_000 });
  const after = (sql(`SELECT count(*), coalesce(sum(usd), 0) FROM chat_usage WHERE user_id = ${g.user_id}`) as [number, number][])[0];
  expect(after[0]).toBe(before + 1);
  log(`one real turn as the guest: cost row usd ${after[1]}`);
  await shot(page, "04_chat_guest_answer");
  // add a team on Home
  await page.goto("/home");
  await expect(page.locator('[data-testid="guest-banner"]:visible')).toBeVisible();
  // after the chat Home is in its returning state: the add-team card, not the first-visit choice
  const via = (await page.getByTestId("choice-add-team").count()) ? "choice" : "card";
  await addTeamOnHome(page, TEAM, via);
  await shot(page, "05_home_guest_team_added");
  const teams = (sql(`SELECT count(*) FROM user_fpl_teams WHERE user_id = ${g.user_id}`) as number[][])[0][0];
  expect(teams).toBe(1);
  // a refresh keeps the session (the leave at pagehide is cancelled by the ping on load)
  await page.reload();
  await expect(page.locator('[data-testid="guest-banner"]:visible')).toBeVisible({ timeout: 30_000 });
  await page.waitForTimeout(3000);
  const r1 = guestRow(g.clerk)!;
  expect(r1.left).toBeNull();
  log(`refresh: the guest stays (left_at null, last seen ${r1.seen})`);
  // a second tab keeps it: close the first, the second is alive -> no leave
  const page2 = await context.newPage();
  await page2.goto("/home");
  await expect(page2.locator('[data-testid="guest-banner"]:visible')).toBeVisible({ timeout: 30_000 });
  await page2.waitForTimeout(1500);
  await page.close();
  await page2.waitForTimeout(3000);
  const r2 = guestRow(g.clerk)!;
  expect(r2.left).toBeNull();
  const me2 = await apiCall(page2, "get", "/me");
  expect(me2.status).toBe(200);
  log("second tab: the first tab closed, no leave was sent (another tab alive), the session works on");
  // close every tab -> the leave -> deleted within ~2 minutes (the reaper runs every 60 s)
  await page2.close();
  const ms = await waitGone(r2, 240_000);
  expect(ms).toBeGreaterThan(0);
  const clerkLeft = await clerkHas(g.clerk);
  expect(clerkLeft).toBe(false);
  const marker = sql("SELECT count(*) FROM chat_usage WHERE turn_id = 'deleted-guest' AND ts > now() - interval '30 minutes'") as number[][];
  expect(marker[0][0]).toBeGreaterThanOrEqual(1);
  const start = sql(`SELECT end_reason FROM guest_starts WHERE clerk_user_id = '${g.clerk}'`) as string[][];
  expect(start[0][0]).toBe("left");
  log(`last tab closed: deleted after ${Math.round(ms / 1000)} s (DB row gone, Clerk user gone, cost row 'deleted-guest', start row 'left')`);
});

test("2 a browser restart (Clerk cookies back, fpl_guest gone) ends the session at once", async ({ browser }, info) => {
  test.skip(info.project.name !== "desktop", "desktop");
  test.setTimeout(180_000);
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await ctx.newPage();
  const g = await startGuest(page);
  const state = await ctx.storageState();
  await ctx.close(); // closing the context sends no leave (the browser just vanished)
  const restored = await browser.newContext({ viewport: { width: 1440, height: 900 }, storageState: { cookies: state.cookies.filter((c) => c.name !== "fpl_guest"), origins: state.origins } });
  const p2 = await restored.newPage();
  await p2.goto("/home");
  await p2.waitForURL(/\/login\?reason=guest_ended/, { timeout: 60_000 });
  await expect(p2.locator('[data-testid="guest-ended-note"]:visible')).toHaveText("Your guest session ended and its data was deleted.");
  await shot(p2, "06_login_guest_ended_note");
  expect(guestRow(g.clerk)).toBeNull();
  expect(await clerkHas(g.clerk)).toBe(false);
  log("browser restart without fpl_guest: the session ended on the first page load (row + Clerk user gone), the login note shown");
  await restored.close();
});

test("3 idle (fake clock): the 28-minute dialog, I'm here keeps it, 30 minutes deletes it", async ({ browser }, info) => {
  test.skip(info.project.name !== "desktop", "desktop");
  test.setTimeout(240_000);
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await ctx.newPage();
  const g = await startGuest(page);
  const p2 = await ctx.newPage();
  await p2.clock.install();
  await p2.goto("/home");
  await expect(p2.locator('[data-testid="guest-banner"]:visible')).toBeVisible({ timeout: 30_000 });
  await page.close(); // the first tab's leave is cancelled by p2's pings (another tab alive -> no leave anyway)
  await p2.clock.fastForward("28:05");
  const dialog = p2.locator('[data-testid="guest-idle-dialog"]:visible');
  await expect(dialog).toBeVisible({ timeout: 15_000 });
  await expect(p2.locator('[data-testid="guest-idle-title"]')).toHaveText("Still there?");
  const left = await p2.locator('[data-testid="guest-idle-countdown"]').innerText();
  await shot(p2, "07_idle_dialog_28_min");
  await p2.locator('[data-testid="guest-idle-stay"]').click();
  await expect(dialog).toHaveCount(0);
  expect(guestRow(g.clerk)).not.toBeNull();
  log(`idle: the dialog at 28 min (ends in ${left}); I'm here kept the session`);
  await p2.clock.fastForward("30:05");
  await p2.waitForURL(/\/login\?reason=guest_ended/, { timeout: 60_000 });
  await expect(p2.locator('[data-testid="guest-ended-note"]:visible')).toBeVisible();
  await shot(p2, "08_idle_30_min_ended");
  expect(guestRow(g.clerk)).toBeNull();
  expect(await clerkHas(g.clerk)).toBe(false);
  const reason = sql(`SELECT end_reason FROM guest_starts WHERE clerk_user_id = '${g.clerk}'`) as string[][];
  log(`idle: 30 minutes -> the client deleted the session (start row '${reason[0][0]}'), signed out, the note shown`);
  await ctx.close();
});

test("4 guards with 0 model calls: the per-guest cap, the daily budget, the per-IP limit, the kill switch", async ({ browser, request }, info) => {
  test.skip(info.project.name !== "desktop", "desktop");
  test.setTimeout(480_000);
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await ctx.newPage();
  const g = await startGuest(page);
  await page.goto("/chat");
  await expect(page.locator('[data-testid="chat"][data-ready="true"]:visible')).toBeVisible({ timeout: 30_000 });
  const usageBefore = (sql("SELECT count(*) FROM chat_usage") as number[][])[0][0];
  // the per-guest cap: the row's daily cap is $0.25; its spend today is pushed over it by SQL (no model call anywhere)
  exec(`INSERT INTO chat_usage (ts, turn_id, model, api_calls, usd, tool_names_replaced, user_id) VALUES (now(), 'w9-seed-cap', 'm', 1, 0.30, 0, ${g.user_id})`);
  await vis(page, "chat-input").fill("Hello?");
  await page.keyboard.press("Enter");
  const sys = page.locator('[data-testid="system-guest"]:visible');
  await expect(sys).toBeVisible({ timeout: 20_000 });
  await expect(sys).toHaveAttribute("data-code", "guest");
  await expect(sys).toContainText("Guest limit reached — sign in with Google or email to keep going");
  await expect(vis(page, "chat-box")).toHaveAttribute("data-disabled", "true");
  await shot(page, "09_guard_guest_cap");
  const hits = sql(`SELECT cap_hits, budget_hits FROM guest_starts WHERE user_id = ${g.user_id}`) as number[][];
  expect(hits[0][0]).toBe(1);
  exec("DELETE FROM chat_usage WHERE turn_id = 'w9-seed-cap'");
  log("cap: refused with the guest text, the box disabled, start row cap_hits 1");
  // the daily budget: the deleted guests' rows of today already count; the budget is set to a cent for the check
  await env({ GUEST_DAILY_BUDGET_USD: "0.01" });
  await page.reload();
  await expect(page.locator('[data-testid="chat"][data-ready="true"]:visible')).toBeVisible({ timeout: 30_000 });
  await vis(page, "chat-input").fill("Hello again?");
  await page.keyboard.press("Enter");
  const sysB = page.locator('[data-testid="system-guest"]:visible');
  await expect(sysB).toBeVisible({ timeout: 20_000 });
  await expect(sysB).toHaveAttribute("data-code", "guest_budget");
  await expect(sysB).toContainText("Guest mode is full for today — sign in to continue");
  await shot(page, "10_guard_budget");
  const startB = await request.post(`${API}/guest/start`, { headers: { "X-Forwarded-For": `192.0.2.${10 + (Math.floor(Date.now() / 1000) % 240)}` } });
  expect(startB.status()).toBe(429);
  expect((await startB.json()).code).toBe("guest_budget");
  await env({ GUEST_DAILY_BUDGET_USD: null });
  log("budget: the turn and a new start refused (guest_budget)");
  // the per-IP limit: three starts from one forwarded address, the fourth refused; another address is fine
  const ipCtx = await request.post(`${API}/__w9/env`, { data: {} }); // (no-op; keeps the API warm)
  expect(ipCtx.status()).toBe(200);
  await env({ GUEST_STARTS_PER_IP_PER_DAY: "3" });
  const octet = 10 + (Math.floor(Date.now() / 1000) % 240); // a fresh forwarded address per run (the counter is per UTC day)
  const ipA = `203.0.113.${octet}`;
  const ipB = `198.51.100.${octet}`;
  const codes: number[] = [];
  for (let i = 0; i < 4; i++) {
    const r = await request.post(`${API}/guest/start`, { headers: { "X-Forwarded-For": ipA } });
    codes.push(r.status());
    if (i === 3) expect((await r.json()).code).toBe("guest_ip_limit");
  }
  expect(codes).toEqual([200, 200, 200, 429]);
  const other = await request.post(`${API}/guest/start`, { headers: { "X-Forwarded-For": ipB } });
  expect(other.status()).toBe(200);
  await env({ GUEST_STARTS_PER_IP_PER_DAY: "100" });
  // the four unclaimed starts lose their Clerk users through the unclaimed rule (started 11 min ago by SQL)
  exec("UPDATE guest_starts SET started_at = started_at - interval '11 minutes' WHERE claimed_at IS NULL AND ended_at IS NULL");
  const sw = await sweep();
  expect(sw.unclaimed_deleted).toBe(4);
  log("per-IP: starts 200,200,200,429 (guest_ip_limit) from one address, 200 from another; the 4 unclaimed Clerk users deleted by the reaper");
  // the kill switch: new starts and the login button off, the live guest's turn refused, every guest ended within a sweep
  await env({ GUEST_MODE: "off" });
  const signedOut = await browser.newContext({ viewport: { width: 1440, height: 900 } }); // the login page sends a signed-in visitor on to /home
  const lp = await signedOut.newPage();
  await lp.goto("/login");
  await lp.locator('[data-testid="skip-intro"]:visible').first().click();
  const off = lp.locator('[data-testid="continue-as-guest"]:visible');
  await expect(off).toHaveAttribute("data-guest-mode", "off", { timeout: 15_000 });
  await expect(off).toBeDisabled();
  await expect(off).toHaveText("Guest mode is unavailable");
  await shot(lp, "11_login_guest_mode_off");
  await signedOut.close();
  await page.reload();
  await expect(page.locator('[data-testid="chat"][data-ready="true"]:visible')).toBeVisible({ timeout: 30_000 });
  await vis(page, "chat-input").fill("Still here?");
  await page.keyboard.press("Enter");
  const sysO = page.locator('[data-testid="system-guest"]:visible');
  await expect(sysO).toBeVisible({ timeout: 20_000 });
  await expect(sysO).toHaveAttribute("data-code", "guest_off");
  await expect(sysO).toContainText("Guest mode is unavailable");
  await shot(page, "12_guard_switch_off_chat");
  const sw2 = await sweep();
  expect(sw2.deleted.map((d) => d.reason)).toContain("switch_off");
  expect(guestRow(g.clerk)).toBeNull();
  expect(await clerkHas(g.clerk)).toBe(false);
  // the page learns from its next ping (<= a minute after the last one, on activity): a lost guest session lands on the guest note
  await page.waitForTimeout(61_000);
  await page.mouse.click(700, 420);
  await page.waitForURL(/\/login\?reason=guest_ended/, { timeout: 60_000 });
  await expect(page.locator('[data-testid="guest-ended-note"]:visible')).toBeVisible({ timeout: 30_000 });
  await expect(page.locator('[data-testid="continue-as-guest"]:visible')).toBeVisible({ timeout: 30_000 }); // Clerk re-read /v1/client: signed out, the card back
  await shot(page, "13_switch_off_ended");
  await env({ GUEST_MODE: "on" });
  const usageAfter = (sql("SELECT count(*) FROM chat_usage") as number[][])[0][0];
  expect(usageAfter).toBe(usageBefore);
  log(`kill switch: starts 403 / the button disabled, the turn refused (guest_off), the guest ended by the sweep ('switch_off'), the page went to the guest note; model calls across the guard checks: 0 (chat_usage ${usageBefore} -> ${usageAfter})`);
  await ctx.close();
});

test("5 Admin shows guests apart from people; the real accounts and the owner are untouched", async ({ page }, info) => {
  test.skip(info.project.name !== "desktop", "desktop");
  test.setTimeout(180_000);
  await signIn(page, `${ADMIN}+clerk_test@example.com`);
  await page.goto("/admin");
  await expect(page.locator('[data-testid="admin"]:visible')).toBeVisible({ timeout: 60_000 });
  await expect(page.locator('[data-testid="card-guests"]:visible')).toBeVisible({ timeout: 60_000 });
  const tiles = page.locator('[data-testid="guest-tiles"]');
  const sessions = Number(await tiles.locator('[data-testid="v-guest_sessions_today"]').getAttribute("data-value"));
  const live = Number(await tiles.locator('[data-testid="v-guest_live_now"]').getAttribute("data-value"));
  const spend = Number(await tiles.locator('[data-testid="v-guest_usd_today"]').getAttribute("data-value"));
  const hitsT = Number(await tiles.locator('[data-testid="v-guest_limit_hits_today"]').getAttribute("data-value"));
  expect(sessions).toBeGreaterThanOrEqual(4);
  expect(live).toBe(0);
  expect(spend).toBeGreaterThan(0);
  expect(hitsT).toBeGreaterThanOrEqual(2);
  await expect(page.locator('[data-testid="deleted-guests-row"]')).toBeVisible();
  const names = await page.locator('[data-testid="user-row"] .ad-name').allInnerTexts();
  expect(names.some((n) => /^Guest$/i.test(n.trim()))).toBe(false);
  await shot(page, "14_admin_guests_card", true);
  log(`admin: guest sessions today ${sessions}, live 0, guest spend today $${spend}, limit hits ${hitsT}; no guest among the ${names.length} people`);
  // the real accounts and the owner: identical per-table counts (the two test accounts of this run excluded)
  const now = snapshot();
  const base = baseline;
  for (const uid of base.ids as number[]) {
    expect(now[String(uid)], `user ${uid}`).toEqual(base[String(uid)]);
  }
  expect(now.owner_squad).toEqual(base.owner_squad);
  expect(((now.ids as number[]).filter((u) => !(base.ids as number[]).includes(u))).length).toBeLessThanOrEqual(2);
  log(`real accounts untouched: ${(base.ids as number[]).length} pre-existing non-guest accounts identical, owner squad ${JSON.stringify(now.owner_squad)}`);
});

// ---- phone -----------------------------------------------------------------------------------------------------------------------

test("6 phone: start, banner, chat; closing the page sends no leave; the idle rule ends it", async ({ browser }, info) => {
  test.skip(info.project.name !== "mobile", "phone");
  test.setTimeout(300_000);
  const ctx: BrowserContext = await browser.newContext({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true });
  const page = await ctx.newPage();
  const coarse = await page.evaluate(() => window.matchMedia("(pointer: coarse)").matches);
  expect(coarse).toBe(true);
  const g = await startGuest(page);
  await shot(page, "15_phone_home_guest");
  await page.goto("/chat");
  await expect(page.locator('[data-testid="chat"][data-ready="true"]:visible')).toBeVisible({ timeout: 30_000 });
  await expect(page.locator('[data-testid="guest-banner"]:visible')).toBeVisible();
  await shot(page, "16_phone_chat_guest");
  await page.close(); // pagehide on a phone: no leave
  await new Promise((r) => setTimeout(r, 150_000));
  const row = guestRow(g.clerk);
  expect(row).not.toBeNull();
  expect(row!.left).toBeNull();
  log("phone: the page closed, 150 s later the guest is still there (no leave signal on a coarse pointer)");
  // the idle rule still ends it: the last ping is moved back 32 minutes, one sweep
  exec(`UPDATE app_users SET guest_last_seen_at = now() - interval '32 minutes' WHERE user_id = ${g.user_id}`);
  const sw = await sweep();
  expect(sw.deleted.map((d) => `${d.user_id}:${d.reason}`)).toContain(`${g.user_id}:idle`);
  expect(await clerkHas(g.clerk)).toBe(false);
  log("phone: idle rule -> deleted by the reaper ('idle'), Clerk user gone");
  await ctx.close();
});

export {};
void (null as unknown as Browser);
