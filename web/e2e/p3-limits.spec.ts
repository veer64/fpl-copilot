import { expect, test, type Browser, type BrowserContext, type Page } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import fs from "node:fs";
import path from "node:path";
import { acquireUser, releaseUser, userName } from "./clerk-users";
import { API, signIn } from "./w4";

/** Prompt P3 (25 Nov 2026): the website fixes from P1 (eval/reports/p1_readiness.md sections 2 and 6), desktop 1440x900 +
 *  phone 390x844. SEEDED: every API call is a route mock; a catch-all answers anything unexpected with a 404 and records it
 *  (the test fails on any), so no request reaches a backend -- no agent turn, no FPL request, no write. One Clerk test user.
 *   a11y   the account button's accessible name holds its visible initials; one <main> on /login, Home, About and Privacy
 *          with the heroes inside; the guest banner is a named region; the chips are ul > li > button; axe: no critical or
 *          serious issue, and none of P1's rules (label-content-name-mismatch, landmark-one-main, region, aria-allowed-role)
 *   draft  Home: 429 draft_limited -> the amber note "within the hour" (no toast, no "--", not the server's words); 429 with
 *          a readable Retry-After -> a live countdown; 503 draft_busy -> the busy note; 503 draft_failed -> the failed dialog
 *          as before; the next build clears the note. Chat: a refused rebuild -> the same note in the thread
 *   site   the site's daily wallet: the page's own note (the "everyone" icon, not the guest's), a live countdown, the box
 *          disabled -- and enabled again by itself when the reset passes, with no reload. */

test.describe.configure({ mode: "serial" });
const NAME = userName("p3limits");
const SHOTS = process.env.P3_SHOTS ?? path.join("C:", "dev", "fpl-backups", "p3_files", "shots");
const DRAFT_TID = "p3-draft-thread";
const P1_RULES = ["label-content-name-mismatch", "landmark-one-main", "region", "aria-allowed-role"];
let userId: string | null = null;
let context: BrowserContext;
let page: Page;
const errors: string[] = [];
const unexpected: string[] = [];
const notes: string[] = [];
const note = (s: string) => {
  notes.push(s);
  console.log(`[P3] ${s}`);
};
const esc = (s: string) => s.replace(/[.*+?^${}()|[\]\\/]/g, "\\$&");

// ---- seed data -------------------------------------------------------------------------------------------------------------
const pl = (slot: number, id: number, short: string, club: string, position: string, price: number, pts: number, role: "C" | "VC" | null = null) => ({
  slot, id, short_name: short, full_name: short, club, position, price, form: 5.2, role, next: { opp: "FUL", home: true, n: 1 }, flag: null, pred: { points: pts, source: "ours" }, in_squad: true,
});
const PLAYERS = [
  pl(1, 1, "Raya", "ARS", "GK", 5.0, 4.8), pl(2, 2, "Gabriel", "ARS", "DEF", 5.8, 4.6, "VC"), pl(3, 3, "Van Dijk", "LIV", "DEF", 5.5, 3.9),
  pl(4, 4, "Muñoz", "CRY", "DEF", 4.5, 3.5), pl(5, 5, "Gvardiol", "MCI", "DEF", 5.0, 3.7), pl(6, 6, "Salah", "LIV", "MID", 12.5, 7.4),
  pl(7, 7, "Palmer", "CHE", "MID", 9.5, 6.1), pl(8, 8, "Saka", "ARS", "MID", 9.0, 5.8), pl(9, 9, "Rogers", "AVL", "MID", 5.5, 4.4),
  pl(10, 10, "Haaland", "MCI", "FWD", 14.0, 7.9, "C"), pl(11, 11, "Wood", "NFO", "FWD", 6.0, 4.2), pl(12, 12, "Sels", "NFO", "GK", 4.0, 3.3),
  pl(13, 13, "Lewis", "MCI", "DEF", 4.3, 2.4), pl(14, 14, "Ndiaye", "EVE", "MID", 4.5, 3.1), pl(15, 15, "Welbeck", "BHA", "FWD", 4.5, 3.0),
];
const draftCard = (over: Record<string, unknown> = {}) => ({
  version_id: 900000001, formation: "4-4-2", captain: { id: 10, short_name: "Haaland", full_name: "Haaland" }, vice: { id: 2, short_name: "Gabriel", full_name: "Gabriel" },
  predicted_xi_points: 64.2, predictions_gw: 12, predictions_updated_at: "2026-11-24T11:01:48.000Z", value: 99.6, budget: 100.0, left: 0.4, over: 0,
  built_at: "2026-11-24T15:00:00.000Z", built_from_predictions_at: "2026-11-24 11:01:48+00:00", built_from_run_id: 91, newer_predictions: false, n_changes: 0,
  updated_at: "2026-11-24T15:00:00.000Z", thread_id: DRAFT_TID, thread_ids: [DRAFT_TID], next_gw: 12, next_deadline: "2026-11-27T18:30:00Z", fpl_live: true,
  players: PLAYERS.map((p) => ({ ...p })), ...over,
});
const OPENING = "Here's your starting 15, built from our predictions. Does it sound good to you? Suggest any changes you'd like, or ask me why I picked a player.";
const opening = () => [{ role: "assistant", text: OPENING, at: null, message_id: null, sources: [], squad_preview: null, squad_applied: null, feedback: null, kind: "draft_opening" }];
// the server's own words, which the page must no longer show (P1: a raw "--" and no time)
const SERVER_LIMITED = "You've built or rebuilt your draft 10 times in the last hour -- please try again in a little while.";
const SERVER_BUSY = "Lots of drafts are being built right now -- please try again in a moment.";

type Refusal = { status: number; kind: string; detail: string; retryAfter?: number };
type State = { isGuest: boolean; teams: number; draft: ReturnType<typeof draftCard> | null; messages: unknown[]; refuse: Refusal[]; builds: number; rebuilds: number; chat: unknown[] };
const S: State = { isGuest: false, teams: 0, draft: null, messages: [], refuse: [], builds: 0, rebuilds: 0, chat: [] };
function reset(over: Partial<State> = {}) {
  Object.assign(S, { isGuest: false, teams: 0, draft: null, messages: [], refuse: [], builds: 0, rebuilds: 0, chat: [] }, over);
}
const teamRow = (id: number) => ({ fpl_team_id: id, label: null, is_active: false, last_imported_gw: 11, entry_name: "P3 Test XI", manager_name: "Test Manager", total_points: 825, overall_rank: 1200, last_gw: 11, last_gw_points: 62, updated_after_gw: 11, summary_updated_at: "2026-11-24T12:00:00Z", last_used_at: "2026-11-24T12:00:00Z", created_at: "2026-11-24T11:00:00Z", last_imported_at: "2026-11-24T11:00:00Z" });

async function refusalOr(r: import("@playwright/test").Route, ok: () => Promise<void>) {
  const x = S.refuse.shift();
  if (!x) return ok();
  const headers: Record<string, string> = { "access-control-allow-origin": "http://localhost:3002" };
  if (x.retryAfter !== undefined) {
    headers["retry-after"] = String(x.retryAfter);
    headers["access-control-expose-headers"] = "Retry-After";
  }
  await new Promise((res) => setTimeout(res, 200));
  return r.fulfill({ status: x.status, headers, json: { detail: x.detail, error_kind: x.kind } });
}

async function seed(p: Page) {
  await p.unrouteAll({ behavior: "ignoreErrors" });
  // the catch-all first: routes registered later win, so it only answers what nothing else does
  await p.route(new RegExp(`^${esc(API)}/`), (r) => {
    unexpected.push(`${r.request().method()} ${r.request().url()}`);
    return r.fulfill({ status: 404, json: { detail: "P3 spec: not mocked" } });
  });
  await p.route(`${API}/guest/status`, (r) => r.fulfill({ json: { enabled: true, idle_minutes: 30, cap_usd: 0.25, leave_grace_seconds: 90 } }));
  await p.route(`${API}/me`, (r) => {
    if (r.request().method() !== "GET") return r.fulfill({ json: { deleted: true } }); // never a real delete
    return r.fulfill({
      json: { user_id: 10077, is_admin: false, is_owner: false, daily_cap_usd: 1, spent_today_usd: 0, active_team: null, is_guest: S.isGuest, guest: S.isGuest ? { idle_minutes: 30, leave_grace_seconds: 90, cap_usd: 0.25, spent_usd: 0, budget_open: true } : null },
    });
  });
  await p.route(`${API}/me/ping`, (r) => r.fulfill({ json: { ok: true } }));
  await p.route(`${API}/me/leave`, (r) => r.fulfill({ json: { ok: true } }));
  await p.route(`${API}/deadlines`, (r) => r.fulfill({ json: { events: [{ gw: 12, deadline_time: "2026-11-27T18:30:00Z", finished: false }, { gw: 13, deadline_time: "2026-12-01T18:30:00Z", finished: false }], fetched_at: new Date().toISOString() } }));
  await p.route(`${API}/me/teams`, (r) => r.fulfill({ json: [teamRow(4679901)].slice(0, S.teams) }));
  await p.route(`${API}/me/active-team`, (r) => r.fulfill({ json: { active_team: null } }));
  await p.route(`${API}/threads`, (r) => (r.request().method() === "GET" ? r.fulfill({ json: [] }) : r.fulfill({ json: { thread_id: "p3-general-thread" } })));
  await p.route(new RegExp(`^${esc(API)}/threads/([^/?]+)/messages$`), (r) => r.fulfill({ json: r.request().url().includes(DRAFT_TID) ? S.messages : [] }));
  await p.route(`${API}/me/draft`, async (r) => {
    if (r.request().method() === "GET") return r.fulfill({ json: { draft: S.draft } });
    S.builds += 1;
    return refusalOr(r, async () => {
      await new Promise((res) => setTimeout(res, 300));
      S.draft = draftCard();
      S.messages = opening();
      await r.fulfill({ json: { draft: S.draft, existing: false, thread_id: DRAFT_TID } });
    });
  });
  await p.route(`${API}/me/draft/rebuild`, async (r) => {
    S.rebuilds += 1;
    return refusalOr(r, async () => {
      S.draft = draftCard({ version_id: 900000002 });
      await r.fulfill({ json: { draft: S.draft } });
    });
  });
  await p.route(`${API}/chat`, async (r) => {
    const body = r.request().postDataJSON() as { message: string; thread_id?: string };
    const a = (S.chat.shift() as Record<string, unknown> | undefined) ?? { answer: "A reply.", sources: [] };
    await new Promise((res) => setTimeout(res, 300));
    await r.fulfill({ json: { thread_id: body.thread_id ?? "p3-general-thread", message_id: "p3-msg", sources: [], squad_preview: null, squad_applied: null, ...a } });
  });
}

const vis = (p: Page, id: string) => p.locator(`[data-testid="${id}"]:visible`);
const phone = (p: Page) => p.viewportSize()!.width < 600;
const shot = async (p: Page, name: string) => {
  fs.mkdirSync(SHOTS, { recursive: true });
  const v = p.viewportSize()!;
  await p.screenshot({ path: path.join(SHOTS, `p3_${name}_${v.width}x${v.height}.png`) });
};
async function home(p: Page) {
  await p.goto("/home");
  await expect(p.locator('[data-testid="home"]:visible')).not.toHaveAttribute("data-state", "loading", { timeout: 30_000 });
  await p.waitForTimeout(300);
}
async function openChat(p: Page, href: string) {
  await p.goto(href);
  await expect(p.locator('[data-testid="chat"][data-ready="true"]:visible')).toBeVisible({ timeout: 30_000 });
  await p.waitForTimeout(300);
}
/** axe on the page as it is: no critical / serious issue and none of P1's four rules; the counts go to the notes */
async function axe(p: Page, label: string) {
  const r = await new AxeBuilder({ page: p }).analyze();
  const v = r.violations.map((x) => `${x.impact}:${x.id}x${x.nodes.length}`);
  note(`axe ${label} (${p.viewportSize()!.width}px): ${r.violations.length} violations${v.length ? ` [${v.join(", ")}]` : ""}`);
  expect(r.violations.filter((x) => x.impact === "critical" || x.impact === "serious").map((x) => x.id)).toEqual([]);
  expect(r.violations.filter((x) => P1_RULES.includes(x.id)).map((x) => `${x.id}: ${x.nodes.map((n) => n.target.join(" ")).join(" | ")}`)).toEqual([]);
}
async function noToast(p: Page) {
  await expect(p.locator("[data-sonner-toast]")).toHaveCount(0);
}

test.beforeAll(async ({ browser }, info) => {
  userId = await acquireUser(NAME);
  const use = info.project.use;
  context = await browser.newContext({ viewport: use.viewport, isMobile: use.isMobile, hasTouch: use.hasTouch, baseURL: use.baseURL });
  page = await context.newPage();
  page.on("pageerror", (e) => errors.push(String(e).slice(0, 200)));
  await seed(page);
  await signIn(page, `${NAME}+clerk_test@example.com`);
});
test.afterAll(async ({}, info) => {
  note(`${info.project.name}: page errors ${errors.length}${errors.length ? ` -- ${errors.slice(0, 3).join(" | ")}` : ""}; unmocked API calls ${unexpected.length}${unexpected.length ? ` -- ${unexpected.slice(0, 5).join(" | ")}` : ""}`);
  fs.mkdirSync(SHOTS, { recursive: true });
  fs.appendFileSync(path.join(SHOTS, "notes.txt"), notes.map((n) => `${new Date().toISOString()} ${n}\n`).join(""));
  await context?.close();
  await releaseUser(NAME, userId);
});
test.afterEach(() => {
  expect(unexpected, "every API call the pages made is mocked").toEqual([]);
});

// ---- 1. accessibility --------------------------------------------------------------------------------------------------------
test("a11y: the account button's name holds its initials; Home has one <main> with the greeting; axe clean (new + with a draft)", async () => {
  reset();
  await home(page);
  const btn = vis(page, "account-menu");
  const ini = ((await btn.locator(".hm-avatar").textContent()) ?? "").trim();
  expect(ini).toMatch(/^[A-Z?]{1,2}$/);
  await expect(btn).toHaveAttribute("aria-label", `${ini}, account menu`);
  await expect(page.getByRole("button", { name: `${ini}, account menu` })).toBeVisible();
  await expect(page.locator("main:visible")).toHaveCount(1);
  await expect(page.locator('main.hm-main:visible [data-testid="greeting"]')).toBeVisible();
  await axe(page, "home new user");
  reset({ teams: 1, draft: draftCard(), messages: opening() });
  await home(page);
  await expect(page.locator('main.hm-main:visible [data-testid="teams-section"]')).toBeVisible();
  await axe(page, "home with a team + draft");
  await shot(page, "home_with_draft");
});

test("a11y: the chips are ul > li > button (general and draft chats); axe clean on both", async () => {
  reset();
  await openChat(page, "/chat");
  const list = page.locator('ul[aria-label="Suggested questions"]:visible');
  await expect(list).toHaveCount(1);
  const n = await list.locator(':scope > li > button[data-testid="empty-chip"]').count();
  expect(n).toBeGreaterThanOrEqual(2);
  await expect(page.locator('[role="listitem"]')).toHaveCount(0);
  note(`general chat: ${n} chips as ul > li > button`);
  // the grid / column look is unchanged: every chip fills its row (equal widths on the desktop's two columns)
  const boxes = await list.locator('button[data-testid="empty-chip"]').evaluateAll((els) => els.map((e) => Math.round(e.getBoundingClientRect().width)));
  if (!phone(page)) expect(new Set(boxes).size).toBe(1);
  await axe(page, "chat general (empty)");
  await shot(page, "chat_general_chips");
  reset({ draft: draftCard(), messages: opening() });
  await openChat(page, `/chat/${DRAFT_TID}`);
  const chips = page.locator('ul.dr-chips[aria-label="Suggested questions"]:visible > li > button[data-testid="draft-chip"]');
  await expect(chips).toHaveCount(4);
  await axe(page, "chat draft (opening chips)");
  await shot(page, "chat_draft_chips");
});

test("a11y: the guest banner is a named region on Home and Chat (axe: no region issue)", async () => {
  reset({ isGuest: true });
  await page.evaluate(() => (document.cookie = "fpl_guest=1; Path=/; SameSite=Lax")); // a live guest tab keeps its session cookie
  await home(page);
  const banner = page.locator('section[aria-label="Guest mode"][data-testid="guest-banner"]:visible');
  await expect(banner).toBeVisible();
  await expect(page.getByRole("region", { name: "Guest mode" })).toBeVisible();
  await axe(page, "home as a guest");
  await shot(page, "home_guest_banner");
  await openChat(page, "/chat");
  await expect(banner).toBeVisible();
  await axe(page, "chat as a guest");
  reset();
  await page.evaluate(() => (document.cookie = "fpl_guest=; Path=/; Max-Age=0; SameSite=Lax"));
});

async function signedOut(browser: Browser, info: { project: { use: { viewport?: { width: number; height: number } | null; isMobile?: boolean; hasTouch?: boolean; baseURL?: string } } }) {
  const use = info.project.use;
  const ctx = await browser.newContext({ viewport: use.viewport, isMobile: use.isMobile, hasTouch: use.hasTouch, baseURL: use.baseURL });
  const p = await ctx.newPage();
  await seed(p);
  return { ctx, p };
}

test("a11y: /login, /about and /privacy each have one <main> holding the headline / hero; axe clean", async ({ browser }, info) => {
  const { ctx, p } = await signedOut(browser, info);
  try {
    await p.goto("/login");
    await p.locator('[data-testid="skip-intro"]:visible').first().click();
    await expect(p.locator(".stage").first()).toHaveAttribute("data-phase", "login");
    await expect(p.locator("main")).toHaveCount(1);
    await expect(p.locator("main .headline h1")).toBeVisible();
    await expect(p.locator("main .card-wrap")).toBeVisible();
    await p.waitForTimeout(1200); // the rise animation settles before axe reads colours
    await axe(p, "login");
    await shot(p, "login");
    for (const [href, hero] of [["/about", ".pp-hero h1"], ["/privacy", ".pp-phero h1"]] as const) {
      await p.goto(href);
      await expect(p.locator("main")).toHaveCount(1);
      await expect(p.locator(`main ${hero}`)).toBeVisible();
      await expect(p.locator("main aside")).toHaveCount(0);
      await p.waitForTimeout(800);
      await axe(p, href.slice(1));
      await shot(p, href.slice(1));
    }
  } finally {
    await ctx.close();
  }
});

// ---- 2. limit messages -----------------------------------------------------------------------------------------------------
test("draft on Home: 429 -> the amber note 'within the hour', Retry-After -> a live countdown, 503 busy -> the busy note, 503 failed -> the dialog; no toast", async () => {
  reset();
  await home(page);
  const noteBox = page.locator('main.hm-main [data-testid="draft-limit-note"]:visible');
  // 429, no Retry-After the browser can read (production today): "within the hour"
  S.refuse.push({ status: 429, kind: "draft_limited", detail: SERVER_LIMITED });
  await vis(page, "build-draft").click();
  await expect(noteBox).toBeVisible({ timeout: 15_000 });
  await expect(noteBox).toHaveAttribute("data-kind", "hourly");
  await expect(noteBox).toBeInViewport({ ratio: 1, timeout: 5000 }); // the phone's Build button is below the fold: the note comes into view
  await expect(noteBox).toHaveAttribute("role", "status");
  await expect(noteBox).toHaveText("You’ve reached the hourly limit for building drafts.You can build or rebuild again within the hour.");
  await expect(noteBox).toHaveCSS("border-top-color", "rgba(255, 194, 61, 0.4)");
  await expect(noteBox.locator(".ch-sys-ic")).toHaveCSS("color", "rgb(255, 194, 61)");
  await expect(vis(page, "draft-building")).toHaveCount(0);
  await expect(vis(page, "build-draft")).toBeEnabled();
  await noToast(page);
  expect(await page.locator("body").innerText()).not.toContain("--");
  expect(await page.locator("body").innerText()).not.toContain("a little while");
  await shot(page, "home_draft_429");
  // 429 with Retry-After (exposed to the page): the exact wait, counting down
  S.refuse.push({ status: 429, kind: "draft_limited", detail: SERVER_LIMITED, retryAfter: 754 });
  await vis(page, "build-draft").click();
  await expect(noteBox.locator('[data-testid="draft-limit-countdown"]')).toHaveText(/^1[0-2]:\d\d$/, { timeout: 15_000 });
  const first = await noteBox.locator('[data-testid="draft-limit-countdown"]').textContent();
  await expect(noteBox.locator('[data-testid="draft-limit-countdown"]')).not.toHaveText(first!, { timeout: 5000 });
  await expect(noteBox).toContainText("You can build or rebuild again in ");
  note(`429 + Retry-After 754: countdown ${first} -> ${await noteBox.locator('[data-testid="draft-limit-countdown"]').textContent()}`);
  await noToast(page);
  // 503 busy
  S.refuse.push({ status: 503, kind: "draft_busy", detail: SERVER_BUSY });
  await vis(page, "build-draft").click();
  await expect(noteBox).toHaveAttribute("data-kind", "busy", { timeout: 15_000 });
  await expect(noteBox).toBeInViewport({ ratio: 1, timeout: 5000 });
  await expect(noteBox).toHaveText("Lots of drafts are being built right now.Nothing was changed — try again in a moment.");
  await expect(noteBox).toHaveCSS("border-top-color", "rgba(255, 194, 61, 0.3)");
  await noToast(page);
  await shot(page, "home_draft_503_busy");
  // 503 draft_failed: still the "Couldn't build your draft" dialog (unchanged); the note goes when the build starts
  S.refuse.push({ status: 503, kind: "draft_failed", detail: "Couldn't build your draft. Nothing was saved -- please try again." });
  await vis(page, "build-draft").click();
  await expect(noteBox).toHaveCount(0);
  await expect(vis(page, "draft-failed")).toBeVisible({ timeout: 15_000 });
  await vis(page, "draft-failed-cancel").click();
  await noToast(page);
  // the next build goes through: no note, the draft chat opens
  await vis(page, "build-draft").click();
  await page.waitForURL(`**/chat/${DRAFT_TID}`, { timeout: 30_000 });
  expect(S.builds).toBe(5);
});

test("draft in the chat: a refused rebuild is the amber note in the thread (429, then 503 busy); no toast", async () => {
  reset({ draft: draftCard({ newer_predictions: true }), messages: opening() });
  await openChat(page, `/chat/${DRAFT_TID}`);
  const rebuild = async () => {
    if (phone(page)) await vis(page, "team-bar").click();
    await vis(page, "draft-newer-rebuild").click();
    await vis(page, "rebuild-confirm").click();
  };
  S.refuse.push({ status: 429, kind: "draft_limited", detail: SERVER_LIMITED });
  await rebuild();
  const notesIn = page.locator('[data-testid="draft-limit-note"]:visible');
  await expect(notesIn).toHaveCount(1, { timeout: 15_000 });
  await expect(notesIn.first()).toHaveAttribute("data-kind", "hourly");
  await expect(notesIn.first()).toContainText("within the hour");
  await expect(vis(page, "draft-building")).toHaveCount(0);
  await noToast(page);
  if (phone(page) && (await vis(page, "team-bar").getAttribute("aria-expanded")) === "true") await vis(page, "team-bar").click();
  S.refuse.push({ status: 503, kind: "draft_busy", detail: SERVER_BUSY });
  await rebuild();
  await expect(notesIn).toHaveCount(2, { timeout: 15_000 });
  await expect(notesIn.nth(1)).toHaveAttribute("data-kind", "busy");
  await noToast(page);
  expect(S.rebuilds).toBe(2);
  if (phone(page) && (await vis(page, "team-bar").getAttribute("aria-expanded")) === "true") await vis(page, "team-bar").click();
  await shot(page, "chat_rebuild_refused");
});

test("site wallet: the note (everyone icon, live countdown), the box disabled -- and enabled again at the reset, no reload", async () => {
  test.setTimeout(180_000); // a real 72 s wait: the countdown must tick 1 m -> 0 m by itself before the reset passes
  reset();
  await openChat(page, "/chat");
  await page.evaluate(() => ((window as unknown as { __p3: number }).__p3 = 1)); // gone if the page reloads
  const resetAt = new Date(Date.now() + 72_000).toISOString(); // the reset, 72 s ahead (the page counts to whatever reset_at says)
  S.chat.push({ answer: "SERVER WORDS: It resets at 00:00 UTC (in 0 h 1 m).", capped: true, limit: { kind: "site", reset_at: resetAt } });
  await vis(page, "chat-input").fill("Who should I captain this week?");
  await page.keyboard.press("Enter");
  const site = vis(page, "system-site");
  await expect(site).toBeVisible({ timeout: 15_000 });
  await expect(site).toContainText("FPL Copilot has reached its daily limit for everyone today.");
  await expect(site).not.toContainText("SERVER WORDS");
  await expect(site.locator('svg[data-icon="everyone"]')).toHaveCount(1);
  await expect(site.locator('path[d="M4 21c1-4.5 4.3-7 8-7s7 2.5 8 7"]')).toHaveCount(0); // the guest's single person
  await expect(site).toHaveCSS("border-top-color", "rgba(255, 194, 61, 0.4)");
  await expect(vis(page, "site-countdown")).toHaveText("1 m");
  await expect(vis(page, "chat-box")).toHaveAttribute("data-disabled", "true");
  await expect(vis(page, "chat-input")).toHaveAttribute("placeholder", "FPL Copilot’s daily limit reached — back at 00:00 UTC");
  await shot(page, "chat_site_limit");
  // live: 1 m -> 0 m by itself, then the box comes back when reset_at passes -- same page, no reload
  await expect(vis(page, "site-countdown")).toHaveText("0 m", { timeout: 30_000 });
  await expect(vis(page, "chat-box")).toHaveAttribute("data-disabled", "false", { timeout: 75_000 });
  expect(await page.evaluate(() => (window as unknown as { __p3?: number }).__p3)).toBe(1);
  await vis(page, "chat-input").fill("And now?");
  await expect(vis(page, "send")).toBeEnabled();
  await shot(page, "chat_site_limit_after_reset");
  note(`site limit: the box came back at ${new Date().toISOString()} (reset_at ${resetAt}), no reload`);
});
