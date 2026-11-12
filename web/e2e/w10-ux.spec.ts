import { expect, test, type BrowserContext, type Page } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import fs from "node:fs";
import path from "node:path";
import { acquireUser, releaseUser, userName } from "./clerk-users";
import { API, signIn } from "./w4";

/** Prompt W10 (2026-11-12): four live UX bugs, desktop 1440x900 + phone 390x844. Seeded: every API call the pages make
 *  beyond /me and /deadlines is a route mock (teams, threads, messages, activate / deactivate, the card, POST /chat with a
 *  ~3,000-character answer and two tables, feedback) -- no agent turn, no FPL request. One Clerk test user for the run.
 *   1 dialogs: Home scrolled down -> Add team, Remove team, Delete account fully inside the viewport and centred (a sheet on
 *     the phone: inside, at the bottom); the page behind does not scroll; Tab stays inside; Esc and the backdrop close;
 *     focus returns to the opener. The chat's Delete chat the same.
 *   2 the scroll rule: on send the question sits at the top of the box; the view never moves while the answer arrives and
 *     writes itself out; scrolled away while thinking -> not moved; the down-arrow; a reopened chat lands on its last
 *     question.
 *   3 the reveal: grows over time, done <= 4.5 s, no raw markdown in any sampled frame, actions / Sources at the end, Copy =
 *     the whole answer, a new send / a hidden tab finish it at once, reduced motion and history at once.
 *   4 Start general chat / Ask about this team -> chat -> Back (and the header's Home link) -> the button is normal and
 *     works; a navigation that hangs gives the button back after 10 s with an error.
 *  W10_PHASE (before / after) prefixes the screenshots. */

test.describe.configure({ mode: "serial" });
const NAME = userName("w10ux");
const SHOTS = process.env.W10_SHOTS ?? path.join("C:", "dev", "fpl-backups", "w10_chat_ux_files");
const PHASE = process.env.W10_PHASE ?? "after";
const GAP = 16;
const TEAM = 4679878;
const NEW_TID = "w10-new-thread";
const SAVED_TID = "w10-saved-thread";
let userId: string | null = null;
let context: BrowserContext;
let page: Page;
const errors: string[] = [];
const notes: string[] = [];
const note = (s: string) => {
  notes.push(s);
  console.log(`[W10] ${s}`);
};

// ---- seed data ------------------------------------------------------------------------------------------------------------
const XI = [["GK", "Raya", "ARS", "ful (H)", "4.8"], ["DEF", "Gabriel", "ARS", "ful (H)", "4.6"], ["DEF", "Van Dijk", "LIV", "mci (A)", "3.9"], ["DEF", "Muñoz", "CRY", "bou (H)", "3.5"],
  ["MID", "Salah (C)", "LIV", "mci (A)", "7.4"], ["MID", "Palmer", "CHE", "whu (H)", "6.1"], ["MID", "Saka", "ARS", "ful (H)", "5.8"], ["MID", "Rogers", "AVL", "lee (H)", "4.4"],
  ["FWD", "Haaland", "MCI", "liv (H)", "7.9"], ["FWD", "Watkins", "AVL", "lee (H)", "5.0"], ["FWD", "Wood", "NFO", "eve (A)", "4.2"]];
const BENCH = [["GK", "Sels", "NFO", "eve (A)", "3.3"], ["DEF", "Lewis", "MCI", "liv (H)", "2.4"], ["MID", "Ndiaye", "EVE", "nfo (H)", "3.1"], ["FWD", "Welbeck", "BHA", "tot (A)", "3.0"]];
const table = (rows: string[][]) => ["| Pos | Player | Club | Fixture | xPts |", "|---|---|---|---|---|", ...rows.map((r) => `| ${r.join(" | ")} |`)].join("\n");
const LONG = [
  "Here is your squad for GW11 with the model's **expected points** for the next fixture. The predictions use the Tuesday night run, the availability feed as of Wednesday 11:01 UTC and the latest odds; the captaincy stays on **Salah**, who edges Haaland on the ceiling even away at City.",
  "", "**Starting XI (3-4-3)**", "", table(XI), "",
  "Three things stand out. First, the defence is thin on clean-sheet odds this week: Arsenal at home to Fulham is the only fixture above 45%, so **Gabriel** is the pick among defenders. Second, Rogers and Watkins both face Leeds, whose expected goals conceded is the fourth highest in the league since GW6. Third, Wood's minutes are the risk: he came off at 71 minutes last week with cramp, but Forest had no concern on Thursday.",
  "", "**Bench**", "", table(BENCH), "",
  "Bench order matters less than usual: Lewis is the autosub most likely to come on, so keep him first. Sels is a straight backup. If you want to free the transfer for next week, the cheapest sensible move is Welbeck to a 4.5m forward with two home games, but the gain is under 0.3 points, so the recommendation is to roll it.",
  "", "**What to watch before the deadline**", "",
  "- **Salah**: the armband stays unless Liverpool's Friday press conference raises a doubt about his hamstring.",
  "- **Wood**: if Forest name him on the bench in the predicted line-ups, swap him for Welbeck at no cost.",
  "- **Gabriel**: Arsenal rotated twice in the last four home games; a 60-minute exit would cost him the clean-sheet points.",
  "", "The model's view of the next three gameweeks favours keeping the current spine: Haaland, Salah and Saka make up almost a third of the expected total, and none of them has a fixture rated worse than average before GW14. Fixture swings later in the month make the wildcard a better fit for GW15 than for now, so save it and use the free transfers to fix the bench instead.",
  "", "Expected total for the starting XI: **57.6 points**, bench **11.8**. Ask me to swap any two players and I will show you the preview first.",
].join("\n");
const SHORT = "**Haaland** is the safest captain: 7.9 expected points at home to Liverpool, a 94% chance of starting and two penalties' worth of share. *Salah* is the differential at 7.4.";
const SOURCES = [{ name: "Premier League", headline: "Team news: Liverpool v Manchester City", date: "2026-11-12", url: "https://www.premierleague.com/news" }];
const player = (id: number, name: string) => ({ slot: 1, id, short_name: name, full_name: name, club: "MCI", position: "FWD", price: 14.5, form: 8.1, role: null, next: { opp: "LIV", home: true, n: 1 }, flag: null, pred: { points: 7.9, source: "ours" }, in_squad: true });
const PREVIEW = { gw: 11, expires_at: new Date(Date.now() + 3 * 3600_000).toISOString(), changes: [{ type: "captain", out: player(1, "Salah"), in: player(2, "Haaland"), slot: null }], impact: { pts_delta: 0.5, pts_horizon_gws: 1, bank_after: null, ft_before: null, ft_after: null, hit_pts: null } };
const teamRow = (id: number, name: string) => ({ fpl_team_id: id, label: null, is_active: false, last_imported_gw: 10, entry_name: name, manager_name: "Test Manager", total_points: 825, overall_rank: 1, last_gw: 10, last_gw_points: 82, updated_after_gw: 10, summary_updated_at: "2026-11-12T12:00:00Z", last_used_at: "2026-11-12T12:00:00Z", created_at: "2026-11-12T11:00:00Z", last_imported_at: "2026-11-12T11:00:00Z" });
const threadRow = (i: number) => ({ thread_id: i === 0 ? SAVED_TID : `w10-old-${i}`, created_at: "2026-11-12T10:00:00Z", last_active: `2026-11-12T1${i % 10}:00:00Z`, is_default: false, title: `Old question number ${i} about captains and transfers`, team_label: null, fpl_team_id: null, team_name: null, updated_at: "2026-11-12T12:00:00Z" });
const savedRows = () => {
  const qs = ["Who should I captain this week?", "Which defenders are worth it?", "Show me my squad for GW11 with expected points."];
  const out: unknown[] = [];
  qs.forEach((q, i) => {
    out.push({ role: "user", text: q, at: `2026-11-12T12:0${i}:00Z` });
    out.push({ role: "assistant", text: i === 2 ? LONG : `${SHORT}\n\n${SHORT}`, at: `2026-11-12T12:0${i}:30Z`, message_id: `w10-saved-${i}`, sources: SOURCES, squad_preview: null, squad_applied: null, feedback: null });
  });
  return out;
};

type Answer = { text: string; delayMs: number; sources?: unknown[]; preview?: unknown };
const answer: Answer = { text: LONG, delayMs: 1500 };
let chatCalls = 0;
const esc = (s: string) => s.replace(/[.*+?^${}()|[\]\\/]/g, "\\$&");

async function seed(p: Page, opts: { teams?: number; threads?: number } = {}) {
  await p.unrouteAll({ behavior: "ignoreErrors" });
  const teams = [teamRow(TEAM, "W10 Test XI"), teamRow(TEAM + 1, "W10 Second XI")].slice(0, opts.teams ?? 2);
  const threads = Array.from({ length: opts.threads ?? 6 }, (_, i) => threadRow(i));
  await p.route(`${API}/me/teams`, (r) => (r.request().method() === "GET" ? r.fulfill({ json: teams }) : r.fallback()));
  await p.route(`${API}/threads`, (r) => (r.request().method() === "GET" ? r.fulfill({ json: threads }) : r.fulfill({ json: { thread_id: NEW_TID } })));
  await p.route(new RegExp(`^${esc(API)}/threads/([^/?]+)/messages$`), (r) => {
    const id = decodeURIComponent(r.request().url().split("/threads/")[1].split("/")[0]);
    return r.fulfill({ json: id === SAVED_TID ? savedRows() : [] });
  });
  await p.route(new RegExp(`^${esc(API)}/me/teams/\\d+/activate$`), (r) => r.fulfill({ json: { fpl_team_id: TEAM, thread_id: "w10-team-default", preview_tickets_cancelled: 0 } }));
  await p.route(`${API}/me/active-team`, (r) => r.fulfill({ json: { active_team: null, deactivated: null, thread_id: "w10-general-default", preview_tickets_cancelled: 0 } }));
  await p.route(new RegExp(`^${esc(API)}/me/teams/\\d+/card$`), (r) => r.fulfill({ status: 503, json: { detail: "card mocked away for W10" } }));
  await p.route(new RegExp(`^${esc(API)}/messages/[^/]+/feedback$`), (r) => r.fulfill({ json: { ok: true } }));
  await p.route(`${API}/chat`, async (r) => {
    chatCalls += 1;
    const a = { ...answer };
    await new Promise((res) => setTimeout(res, a.delayMs));
    await r.fulfill({ json: { answer: a.text, thread_id: NEW_TID, message_id: `w10-msg-${chatCalls}`, sources: a.sources ?? SOURCES, squad_preview: a.preview ?? null, squad_applied: null } }).catch(() => {});
  });
}

const shot = async (p: Page, name: string) => {
  fs.mkdirSync(SHOTS, { recursive: true });
  const vp = p.viewportSize();
  await p.screenshot({ path: path.join(SHOTS, `${PHASE}_${name}_${vp?.width}x${vp?.height}.png`) });
};
const vis = (p: Page, id: string) => p.locator(`[data-testid="${id}"]:visible`);

test.beforeAll(async ({ browser }, info) => {
  userId = await acquireUser(NAME);
  const use = info.project.use;
  context = await browser.newContext({ viewport: use.viewport, isMobile: use.isMobile, hasTouch: use.hasTouch, baseURL: use.baseURL, permissions: ["clipboard-read", "clipboard-write"] });
  page = await context.newPage();
  page.on("pageerror", (e) => errors.push(String(e).slice(0, 200)));
  await page.addInitScript(() => {
    (window as unknown as { __lt: number[] }).__lt = [];
    try {
      new PerformanceObserver((l) => l.getEntries().forEach((e) => (window as unknown as { __lt: number[] }).__lt.push(e.duration))).observe({ type: "longtask", buffered: true });
    } catch {
      /* no long-task API */
    }
  });
  await seed(page);
  await signIn(page, `${NAME}+clerk_test@example.com`);
});
test.afterAll(async ({}, info) => {
  note(`${info.project.name}: page errors ${errors.length}${errors.length ? ` -- ${errors.slice(0, 3).join(" | ")}` : ""}; chat mocks answered ${chatCalls}`);
  fs.mkdirSync(SHOTS, { recursive: true });
  fs.appendFileSync(path.join(SHOTS, `${PHASE}_notes.txt`), notes.map((n) => `${new Date().toISOString()} ${n}\n`).join(""));
  await context?.close();
  await releaseUser(NAME, userId);
});

// ---- helpers ----------------------------------------------------------------------------------------------------------------
type Rect = { top: number; bottom: number; left: number; right: number; width: number; height: number };
async function popupRect(p: Page): Promise<{ rect: Rect; vw: number; vh: number; kind: string } | null> {
  return p.evaluate(() => {
    const el = document.querySelector<HTMLElement>('[data-slot="dialog-content"][data-open], [data-slot="dialog-content"]:not([data-closed]), [data-slot="drawer-popup"]:not([data-closed])');
    if (!el) return null;
    const r = el.getBoundingClientRect();
    return { rect: { top: r.top, bottom: r.bottom, left: r.left, right: r.right, width: r.width, height: r.height }, vw: window.innerWidth, vh: window.innerHeight, kind: el.dataset.slot ?? "?" };
  });
}

async function checkDialog(p: Page, label: string, opener: () => Promise<void>, openerTestId: string) {
  const sy0 = await p.evaluate(() => window.scrollY);
  await opener();
  await expect(p.locator('[data-slot="dialog-content"], [data-slot="drawer-popup"]').first()).toBeVisible({ timeout: 10_000 });
  await p.waitForTimeout(500); // the open animation
  const m = await popupRect(p);
  expect(m, `${label}: a dialog is open`).not.toBeNull();
  const { rect, vw, vh, kind } = m!;
  note(`${label}: ${kind} at scrollY ${sy0}: top ${rect.top.toFixed(1)} bottom ${rect.bottom.toFixed(1)} (viewport ${vh}), left ${rect.left.toFixed(1)} right ${rect.right.toFixed(1)} (${vw})`);
  await shot(p, `bug1_${label}`);
  expect.soft(rect.top, `${label}: top inside`).toBeGreaterThanOrEqual(-0.5);
  expect.soft(rect.bottom, `${label}: bottom inside`).toBeLessThanOrEqual(vh + 0.5);
  expect.soft(rect.left, `${label}: left inside`).toBeGreaterThanOrEqual(-0.5);
  expect.soft(rect.right, `${label}: right inside`).toBeLessThanOrEqual(vw + 0.5);
  if (kind === "dialog-content") {
    expect.soft(Math.abs((rect.top + rect.bottom) / 2 - vh / 2), `${label}: centred vertically`).toBeLessThanOrEqual(2);
    expect.soft(Math.abs((rect.left + rect.right) / 2 - vw / 2), `${label}: centred horizontally`).toBeLessThanOrEqual(2);
  } else {
    expect.soft(Math.abs(rect.bottom - vh), `${label}: the sheet sits on the bottom edge`).toBeLessThanOrEqual(2);
  }
  // the page behind does not scroll while it is open
  await p.mouse.move(Math.min(20, vw / 2), Math.min(20, vh / 2));
  await p.mouse.wheel(0, 600);
  await p.waitForTimeout(300);
  expect.soft(await p.evaluate(() => window.scrollY), `${label}: the page behind did not scroll`).toBe(sy0);
  // focus stays inside
  for (let i = 0; i < 8; i++) {
    await p.keyboard.press("Tab");
    // Base UI's trap uses focus-guard spans at the popup's edges: Tab lands on one for a moment and the guard sends focus
    // back inside -- wait for focus to settle before judging where it is
    await p.waitForFunction(() => !document.activeElement?.hasAttribute("data-base-ui-focus-guard"), undefined, { timeout: 1000 }).catch(() => {});
    const where = await p.evaluate(() => {
      const a = document.activeElement as HTMLElement | null;
      const inside = !!a?.closest('[data-slot="dialog-content"], [data-slot="drawer-popup"]');
      return { inside, what: a ? `${a.tagName.toLowerCase()}${a.dataset.testid ? `[${a.dataset.testid}]` : ""}${a.className && typeof a.className === "string" ? `.${a.className.split(" ")[0]}` : ""}${a.hasAttribute("data-base-ui-focus-guard") ? "(focus-guard)" : ""}` : "none" };
    });
    if (!where.inside) note(`${label}: Tab ${i + 1} focused ${where.what} outside the dialog`);
    expect.soft(where.inside, `${label}: Tab ${i + 1} stays inside`).toBe(true);
  }
  // Esc closes, focus returns to the opener
  await p.keyboard.press("Escape");
  await expect(p.locator('[data-slot="dialog-content"], [data-slot="drawer-popup"]')).toHaveCount(0, { timeout: 5_000 });
  await p.waitForTimeout(300);
  const back = await p.evaluate(() => (document.activeElement as HTMLElement | null)?.dataset.testid ?? document.activeElement?.tagName ?? "");
  expect.soft(back, `${label}: focus returned to the opener`).toBe(openerTestId);
}

/** focus an element WITHOUT scrolling the page, then press Enter (opens it where the page is) */
async function openWithKey(p: Page, testId: string) {
  await p.evaluate((id) => document.querySelector<HTMLElement>(`[data-testid="${id}"]:not([hidden])`)?.focus({ preventScroll: true }), testId);
  await p.keyboard.press("Enter");
}

async function chatMetrics(p: Page) {
  return p.locator('[data-testid="thread-scroll"]:visible').first().evaluate((el) => {
    const r = el.getBoundingClientRect();
    const users = el.querySelectorAll('[data-testid="user-message"]');
    const last = users.length ? users[users.length - 1].getBoundingClientRect() : null;
    return { scrollTop: Math.round(el.scrollTop), maxScroll: el.scrollHeight - el.clientHeight, lastUserTop: last ? Math.round(last.top - r.top) : -9999 };
  });
}

async function send(p: Page, text: string) {
  await vis(p, "chat-input").fill(text);
  await p.keyboard.press("Enter");
}

type Frame = { t: number; len: number; raw: string | null; scrollTop: number; actions: number; revealing: boolean };
/** sample the newest answer every ~100 ms from the moment it lands until it has written itself out */
async function sampleReveal(p: Page, n: number): Promise<{ frames: Frame[]; doneMs: number }> {
  const msg = p.locator('[data-testid="assistant-message"]:visible').nth(n - 1);
  await expect(msg).toBeVisible({ timeout: 30_000 });
  const t0 = Date.now();
  const frames: Frame[] = [];
  for (let i = 0; i < 80; i++) {
    const f = await msg.evaluate((el, scroller) => {
      const md = el.querySelector('[data-testid="answer-typing"]') ?? el.querySelector(".ch-md");
      const txt = (md as HTMLElement | null)?.innerText ?? "";
      const raw = txt.includes("**") ? "**" : txt.includes("|") ? "|" : /^#{1,6}\s/m.test(txt) ? "#" : null;
      const sc = document.querySelector<HTMLElement>(scroller);
      return { len: txt.length, raw, scrollTop: Math.round(sc?.scrollTop ?? -1), actions: el.querySelectorAll('[data-testid="answer-actions"]').length, revealing: el.getAttribute("data-revealing") === "true" };
    }, '[data-testid="thread-scroll"]');
    frames.push({ t: Date.now() - t0, ...f });
    if (!f.revealing) break;
    await p.waitForTimeout(100);
  }
  const doneAt = frames.find((f) => !f.revealing)?.t ?? -1;
  return { frames, doneMs: doneAt };
}

// ---- bug 4 first (a fresh page: /chat has not been visited, so its first navigation really goes to the server) -------------
test("bug 4: Start general chat / Ask about this team -> chat -> Back or the Home link -> the button is normal and works; a hung navigation gives it back after 10 s", async ({}, info) => {
  test.setTimeout(240_000);
  await seed(page, { teams: 1, threads: 1 });
  // a hung navigation (the /chat payload never comes for 13 s): after 10 s the button is back, with an error
  await page.goto("/home");
  await expect(page.locator('[data-testid="home"][data-state="returning"]:visible')).toBeVisible({ timeout: 60_000 });
  const toChat = (u: URL) => u.pathname === "/chat";
  const hang = async (r: import("@playwright/test").Route) => {
    if (r.request().resourceType() === "document") return r.fallback();
    await new Promise((res) => setTimeout(res, 13_000));
    await r.fallback().catch(() => {});
  };
  await page.route(toChat, hang);
  const start = vis(page, "start-general");
  await start.click();
  await expect(start).toContainText("Opening chat", { timeout: 5_000 });
  await page.waitForTimeout(10_800);
  const hungText = (await start.innerText()).trim();
  const hungToast = await page.locator("[data-sonner-toast]").filter({ hasText: "Couldn’t open" }).count();
  note(`bug4 hung navigation: after 10.8 s the button reads "${hungText}", enabled ${await start.isEnabled()}, error toast ${hungToast}, url ${new URL(page.url()).pathname}`);
  expect.soft(hungText).toBe("Start a general chat");
  expect.soft(hungToast).toBeGreaterThan(0);
  await page.unroute(toChat, hang);
  await page.waitForTimeout(3000);
  // the round trips
  for (const how of ["back", "home-link"] as const) {
    await page.goto("/home");
    await expect(page.locator('[data-testid="home"][data-state="returning"]:visible')).toBeVisible({ timeout: 60_000 });
    await vis(page, "start-general").click();
    await page.waitForURL(/\/chat(\?|$)/, { timeout: 30_000 });
    await expect(page.locator('[data-testid="chat"][data-ready="true"]:visible')).toBeVisible({ timeout: 30_000 });
    if (how === "back") await page.goBack();
    else if (info.project.name === "mobile") {
      await vis(page, "menu-button").click(); // the phone's Home link lives in the chat's menu drawer
      await vis(page, "drawer-home").click();
    } else await vis(page, "back-home").click();
    await page.waitForURL(/\/home/, { timeout: 30_000 });
    await expect(page.locator('[data-testid="home"]:visible')).toBeVisible({ timeout: 30_000 });
    const b = vis(page, "start-general");
    await page.waitForTimeout(300);
    const text = (await b.innerText()).trim();
    note(`bug4 Start general chat via ${how}: back on Home it reads "${text}", enabled ${await b.isEnabled()}`);
    await shot(page, `bug4_home_after_${how}`);
    expect.soft(text).toBe("Start a general chat");
    await expect(b).toBeEnabled();
    await b.click();
    await page.waitForURL(/\/chat(\?|$)/, { timeout: 30_000 });
  }
  // Ask about this team: chat -> Back -> normal -> works
  await page.goto("/home");
  await expect(page.locator('[data-testid="home"][data-state="returning"]:visible')).toBeVisible({ timeout: 60_000 });
  await vis(page, "ask-team").first().click();
  await page.waitForURL(/\/chat\?team=/, { timeout: 30_000 });
  await page.goBack();
  await page.waitForURL(/\/home/, { timeout: 30_000 });
  const ask = vis(page, "ask-team").first();
  await page.waitForTimeout(300);
  const askText = (await ask.innerText()).trim();
  note(`bug4 Ask about this team via back: "${askText}", enabled ${await ask.isEnabled()}`);
  expect.soft(askText).toBe("Ask about this team");
  await ask.click();
  await page.waitForURL(/\/chat\?team=/, { timeout: 30_000 });
  // a chip and a recent chat (no pending state of their own): still navigate after a round trip
  await page.goBack();
  await page.waitForURL(/\/home/, { timeout: 30_000 });
  await vis(page, "chip").first().click();
  await page.waitForURL(/\/chat\?q=/, { timeout: 30_000 });
  await page.goBack();
  await page.waitForURL(/\/home/, { timeout: 30_000 });
  await vis(page, "recent-row").first().click();
  await page.waitForURL(/\/chat\/w10-/, { timeout: 30_000 });
  note(`bug4 ${info.project.name}: chip and recent chat navigate after a round trip`);
});

// ---- bug 1 --------------------------------------------------------------------------------------------------------------------
test("bug 1: every dialog opens inside the viewport and centred (the phone's sheets on the bottom edge) wherever Home is scrolled; no page scroll behind; focus trapped; Esc / backdrop close; focus returns", async ({}, info) => {
  test.setTimeout(240_000);
  const phone = info.project.name === "mobile";
  await seed(page, { teams: 2, threads: 6 });
  await page.goto("/home");
  await expect(page.locator('[data-testid="home"][data-state="returning"]:visible')).toBeVisible({ timeout: 60_000 });
  await page.waitForTimeout(800);
  const maxY = await page.evaluate(() => document.documentElement.scrollHeight - window.innerHeight);
  note(`bug1 ${info.project.name}: Home scrolls ${maxY}px`);
  const scrollDown = async () => {
    await page.evaluate(() => window.scrollTo(0, document.documentElement.scrollHeight));
    await page.waitForTimeout(400);
  };
  // Add team
  await scrollDown();
  await checkDialog(page, "add_team", () => openWithKey(page, "add-team-card"), "add-team-card");
  // the backdrop closes it too
  await scrollDown();
  await openWithKey(page, "add-team-card");
  await expect(page.locator('[data-slot="dialog-content"], [data-slot="drawer-popup"]').first()).toBeVisible({ timeout: 10_000 });
  await page.waitForTimeout(500);
  if (!phone) {
    await page.mouse.click(8, 8);
    await expect(page.locator('[data-slot="dialog-content"]')).toHaveCount(0, { timeout: 5_000 });
  } else {
    await page.keyboard.press("Escape");
    await expect(page.locator('[data-slot="drawer-popup"]')).toHaveCount(0, { timeout: 5_000 });
  }
  // Remove team
  await scrollDown();
  await checkDialog(page, "remove_team", () => openWithKey(page, "remove-team"), "remove-team");
  // Delete account (account menu -> Delete account), page scrolled
  await scrollDown();
  await page.evaluate(() => document.querySelector<HTMLElement>('[data-testid="account-menu"]')?.focus({ preventScroll: true }));
  await page.keyboard.press("Enter");
  await expect(page.locator('[data-testid="delete-account"]')).toBeVisible({ timeout: 5_000 });
  await checkDialog(page, "delete_account", async () => {
    await page.locator('[data-testid="delete-account"]').focus();
    await page.keyboard.press("Enter");
  }, "account-menu");
  // Delete chat on the chat page (its scroll is the thread box, not the page)
  await page.goto("/chat");
  await expect(page.locator('[data-testid="chat"][data-ready="true"]:visible')).toBeVisible({ timeout: 30_000 });
  if (phone) {
    await vis(page, "menu-button").click();
    await page.waitForTimeout(500);
  }
  await checkDialog(page, "delete_chat", async () => {
    await page.locator('[data-testid="thread-delete"]:visible').first().focus();
    await page.keyboard.press("Enter");
  }, "thread-delete");
});

// ---- bugs 2 + 3 ---------------------------------------------------------------------------------------------------------------
test("bugs 2 + 3: question at the top on send; the answer writes itself out (<= 4.5 s, no raw markdown, actions at the end) without moving the view; the down-arrow; scrolled away -> not moved; a new send / a hidden tab finish it", async ({}, info) => {
  test.setTimeout(300_000);
  await seed(page, { teams: 1, threads: 0 });
  answer.text = LONG;
  answer.delayMs = 1500;
  answer.preview = PREVIEW;
  await page.goto("/chat");
  await expect(page.locator('[data-testid="chat"][data-ready="true"]:visible')).toBeVisible({ timeout: 30_000 });
  // 1. send: the question at the top, thinking under it
  await send(page, "Show me my squad for GW11 with expected points.");
  await expect(vis(page, "thinking")).toBeVisible({ timeout: 5_000 });
  await page.waitForTimeout(300);
  const sent = await chatMetrics(page);
  note(`bug2 ${info.project.name} on send: lastUserTop ${sent.lastUserTop} (gap ${GAP}), scrollTop ${sent.scrollTop}`);
  await shot(page, "bug2_on_send");
  expect.soft(Math.abs(sent.lastUserTop - GAP)).toBeLessThanOrEqual(4);
  // 2. the answer arrives and writes itself out; the view never moves
  const { frames, doneMs } = await sampleReveal(page, 1);
  const lens = frames.map((f) => f.len);
  const growing = new Set(lens).size;
  const rawFrames = frames.filter((f) => f.revealing && f.raw);
  const moved = frames.filter((f) => f.scrollTop !== sent.scrollTop);
  const earlyActions = frames.filter((f) => f.revealing && f.actions > 0);
  note(`bug3 ${info.project.name}: ${frames.length} samples, ${growing} distinct lengths (first ${lens[0]}, last ${lens[lens.length - 1]}), done after ${doneMs} ms, raw-markdown frames ${rawFrames.length}${rawFrames.length ? ` (${rawFrames.map((f) => f.raw).join("")})` : ""}, frames where scrollTop moved ${moved.length}, frames with actions while typing ${earlyActions.length}`);
  expect.soft(growing, "the text grows over time").toBeGreaterThanOrEqual(5);
  expect.soft(doneMs, "done within 4.5 s").toBeGreaterThan(0);
  expect.soft(doneMs, "done within 4.5 s").toBeLessThanOrEqual(4500);
  expect.soft(rawFrames.length, "no raw markdown in any frame").toBe(0);
  expect.soft(moved.length, "the view never moved").toBe(0);
  expect.soft(earlyActions.length, "actions only at the end").toBe(0);
  await shot(page, "bug3_done");
  const last = vis(page, "assistant-message").last();
  await expect(last.locator('[data-testid="answer-actions"]')).toHaveCount(1);
  await expect(last.locator('[data-testid="sources"]')).toHaveCount(1);
  await expect(last.locator('[data-testid="preview-card"]')).toHaveCount(1);
  const earlyCards = frames.filter((f) => f.revealing).length;
  note(`bug3 the preview card and Sources appear with the actions (frames while typing ${earlyCards} had none: checked by the actions count)`);
  // Copy = the whole answer
  await last.locator('[data-testid="copy"]').click();
  const clip = (await page.evaluate(() => navigator.clipboard.readText()).catch((e) => `ERR ${e}`)).replace(/\r\n/g, "\n"); // Windows' clipboard writes CRLF
  note(`bug3 copy: clipboard ${clip.length} chars (CRLF normalised), the answer ${LONG.length}, equal ${clip === LONG}`);
  expect.soft(clip).toBe(LONG);
  // long tasks during the reveal
  const lt = await page.evaluate(() => (window as unknown as { __lt: number[] }).__lt.slice());
  note(`bug3 long tasks so far: ${lt.length}, max ${lt.length ? Math.max(...lt).toFixed(0) : 0} ms`);
  // 3. the down-arrow: shown away from the bottom, takes the reader there, hidden at the bottom (Copy's click above
  // scrolled the copy button into view, i.e. to the bottom -- go back to where the send left the reader first)
  await page.locator('[data-testid="thread-scroll"]:visible').first().evaluate((el, top) => (el.scrollTop = top), sent.scrollTop);
  await page.waitForTimeout(300);
  const before = await chatMetrics(page);
  await expect(vis(page, "scroll-down")).toBeVisible({ timeout: 5_000 });
  await vis(page, "scroll-down").click();
  await page.waitForTimeout(1500);
  const after = await chatMetrics(page);
  note(`bug2 down-arrow: scrollTop ${before.scrollTop} -> ${after.scrollTop} of ${after.maxScroll}`);
  expect.soft(after.maxScroll - after.scrollTop).toBeLessThanOrEqual(24);
  await expect(vis(page, "scroll-down")).toHaveCount(0);
  // 4. scrolled away while thinking: not moved when it arrives
  answer.text = SHORT;
  answer.delayMs = 2500;
  answer.preview = undefined;
  await send(page, "Who is the safest captain?");
  await expect(vis(page, "thinking")).toBeVisible({ timeout: 5_000 });
  await page.waitForTimeout(300);
  const q2 = await chatMetrics(page);
  expect.soft(Math.abs(q2.lastUserTop - GAP)).toBeLessThanOrEqual(4);
  await page.locator('[data-testid="thread-scroll"]:visible').first().evaluate((el) => (el.scrollTop = 0));
  await page.waitForTimeout(200);
  const r2 = await sampleReveal(page, 2);
  const moved2 = r2.frames.filter((f) => f.scrollTop !== 0);
  note(`bug2 scrolled away while thinking: frames moved ${moved2.length} of ${r2.frames.length}, done ${r2.doneMs} ms`);
  expect.soft(moved2.length).toBe(0);
  await shot(page, "bug2_scrolled_away_not_moved");
  // 5. a new send finishes a running reveal at once
  answer.text = LONG;
  answer.delayMs = 400;
  await send(page, "And the bench?");
  await expect(vis(page, "assistant-message")).toHaveCount(3, { timeout: 30_000 });
  await expect(page.locator('[data-testid="assistant-message"][data-revealing="true"]:visible')).toHaveCount(1, { timeout: 3_000 });
  await send(page, "One more question.");
  await page.waitForTimeout(150);
  const third = vis(page, "assistant-message").nth(2);
  const thirdState = await third.getAttribute("data-revealing");
  const thirdText = (await third.locator(".ch-md").innerText()).length;
  note(`bug3 a new send mid-reveal: the earlier answer revealing=${thirdState}, ${thirdText} chars shown`);
  expect.soft(thirdState).toBe("false");
  // 6. a hidden tab finishes the running reveal at once
  await expect(vis(page, "assistant-message")).toHaveCount(4, { timeout: 30_000 });
  await expect(page.locator('[data-testid="assistant-message"][data-revealing="true"]:visible')).toHaveCount(1, { timeout: 3_000 });
  await page.evaluate(() => {
    Object.defineProperty(document, "hidden", { configurable: true, get: () => true });
    Object.defineProperty(document, "visibilityState", { configurable: true, get: () => "hidden" });
    document.dispatchEvent(new Event("visibilitychange"));
  });
  await page.waitForTimeout(150);
  const hiddenState = await vis(page, "assistant-message").nth(3).getAttribute("data-revealing");
  note(`bug3 a hidden tab mid-reveal: revealing=${hiddenState}`);
  expect.soft(hiddenState).toBe("false");
  await page.evaluate(() => {
    delete (document as unknown as Record<string, unknown>).hidden;
    delete (document as unknown as Record<string, unknown>).visibilityState;
  });
  // 7. screen readers: while typing, the visible text is aria-hidden and a hidden copy holds the whole answer
  answer.delayMs = 400;
  await send(page, "Last one for the screen reader check.");
  await expect(vis(page, "assistant-message")).toHaveCount(5, { timeout: 30_000 });
  const sr = await page.evaluate(() => {
    const msgs = document.querySelectorAll('[data-testid="assistant-message"]');
    const m = msgs[msgs.length - 1];
    const typing = m.querySelector('[data-testid="answer-typing"]');
    const copy = m.querySelector('[data-testid="answer-sr"]');
    return { revealing: m.getAttribute("data-revealing"), typingHidden: typing?.getAttribute("aria-hidden"), srLen: (copy?.textContent ?? "").length, typingLen: (typing?.textContent ?? "").length };
  });
  note(`bug3 screen reader: revealing ${sr.revealing}, typing aria-hidden ${sr.typingHidden}, hidden copy ${sr.srLen} chars vs typed so far ${sr.typingLen}`);
  expect.soft(sr.typingHidden).toBe("true");
  expect.soft(sr.srLen).toBeGreaterThan(2000);
  // 8. leaving the chat mid-reveal: no error; back on the chat the answer is complete
  if (info.project.name === "mobile") {
    await vis(page, "menu-button").click();
    await vis(page, "drawer-home").click();
  } else await vis(page, "back-home").click();
  await page.waitForURL(/\/home/, { timeout: 30_000 });
  await page.goBack();
  await page.waitForURL(/\/chat/, { timeout: 30_000 });
  await page.waitForTimeout(500);
  const stillRevealing = await page.locator('[data-testid="assistant-message"][data-revealing="true"]:visible').count();
  note(`bug3 left mid-reveal and came back: answers still revealing ${stillRevealing}`);
  expect.soft(stillRevealing).toBe(0);
  const lt2 = await page.evaluate(() => (window as unknown as { __lt: number[] }).__lt.slice());
  note(`bug3 long tasks in the whole chat run: ${lt2.length}, max ${lt2.length ? Math.max(...lt2).toFixed(0) : 0} ms`);
});

test("bugs 2 + 3: a reopened chat lands on its last question with the answer below, at once; reduced motion shows a new answer at once", async ({}, info) => {
  test.setTimeout(180_000);
  await seed(page, { teams: 1, threads: 3 });
  await page.goto(`/chat/${SAVED_TID}`);
  await expect(page.locator('[data-testid="chat"][data-ready="true"]:visible')).toBeVisible({ timeout: 30_000 });
  await expect(vis(page, "assistant-message")).toHaveCount(3, { timeout: 30_000 });
  await page.waitForTimeout(500);
  const m = await chatMetrics(page);
  const revealing = await page.locator('[data-testid="assistant-message"][data-revealing="true"]:visible').count();
  const lastAnsTop = await page.locator('[data-testid="thread-scroll"]:visible').first().evaluate((el) => {
    const a = el.querySelectorAll('[data-testid="assistant-message"]');
    return Math.round(a[a.length - 1].getBoundingClientRect().top - el.getBoundingClientRect().top);
  });
  note(`bug2 ${info.project.name} reopened: lastUserTop ${m.lastUserTop}, last answer top ${lastAnsTop}, scrollTop ${m.scrollTop}/${m.maxScroll}, revealing ${revealing}, actions ${await page.locator('[data-testid="answer-actions"]:visible').count()}`);
  await shot(page, "bug2_reopened_last_question_on_top");
  expect.soft(Math.abs(m.lastUserTop - GAP)).toBeLessThanOrEqual(4);
  expect.soft(lastAnsTop).toBeGreaterThan(m.lastUserTop);
  expect.soft(revealing).toBe(0);
  await expect(page.locator('[data-testid="answer-actions"]:visible')).toHaveCount(3);
  // reduced motion: a new answer at once
  await page.emulateMedia({ reducedMotion: "reduce" });
  answer.text = LONG;
  answer.delayMs = 600;
  await send(page, "Reduced motion please.");
  await expect(vis(page, "assistant-message")).toHaveCount(4, { timeout: 30_000 });
  const rm = await vis(page, "assistant-message").nth(3).getAttribute("data-revealing");
  const rmActions = await vis(page, "assistant-message").nth(3).locator('[data-testid="answer-actions"]').count();
  note(`bug3 reduced motion: the new answer revealing=${rm}, actions ${rmActions} on arrival`);
  expect.soft(rm).toBe("false");
  expect.soft(rmActions).toBe(1);
  await page.emulateMedia({ reducedMotion: "no-preference" });
});

test("the W4 message steps, seeded: Sources pop-up, thumbs, the preview's Yes / No after the text, 429 and an error with Retry -- all with the new reveal and scroll rule", async ({}, info) => {
  test.setTimeout(240_000);
  await seed(page, { teams: 1, threads: 0 });
  await page.goto("/chat");
  await expect(page.locator('[data-testid="chat"][data-ready="true"]:visible')).toBeVisible({ timeout: 30_000 });
  // an answer with Sources and a captain preview
  answer.text = `${SHORT}\n\nMake **Haaland** captain instead of Salah?`;
  answer.delayMs = 500;
  answer.preview = PREVIEW;
  await send(page, "Should I change my captain?");
  await expect(page.locator('[data-testid="assistant-message"][data-revealing="false"]:visible')).toHaveCount(1, { timeout: 15_000 });
  const a1 = vis(page, "assistant-message").last();
  await expect(a1.locator('[data-testid="preview-yes"]')).toBeVisible();
  await expect(a1.locator('[data-testid="preview-no"]')).toBeVisible();
  // Sources: the chip opens its pop-up, Esc closes it
  await a1.locator('[data-testid="source-chip"]').first().click();
  await expect(page.locator('[data-testid="source-popup"]:visible')).toBeVisible({ timeout: 5_000 });
  await page.keyboard.press("Escape");
  await expect(page.locator('[data-testid="source-popup"]:visible')).toHaveCount(0, { timeout: 5_000 });
  // thumbs
  await a1.locator('[data-testid="thumb-up"]').click();
  await expect(a1.locator('[data-testid="thumb-up"]')).toHaveAttribute("aria-pressed", "true");
  await a1.locator('[data-testid="thumb-down"]').click();
  await expect(a1.locator('[data-testid="thumb-down"]')).toHaveAttribute("aria-pressed", "true");
  await expect(a1.locator('[data-testid="thumb-up"]')).toHaveAttribute("aria-pressed", "false");
  // Yes sends "Yes": the question at the top, the reply writes itself out
  answer.text = "Done: **Haaland** is your captain for GW11.";
  answer.preview = undefined;
  await a1.locator('[data-testid="preview-yes"]').click();
  await expect(vis(page, "user-message").last()).toHaveText("Yes");
  await page.waitForTimeout(250);
  const yes = await chatMetrics(page);
  expect.soft(Math.abs(yes.lastUserTop - GAP)).toBeLessThanOrEqual(4);
  await expect(page.locator('[data-testid="assistant-message"][data-revealing="false"]:visible')).toHaveCount(2, { timeout: 15_000 });
  // 429: the rate system message (0 answers added)
  await page.route(`${API}/chat`, (r) => r.fulfill({ status: 429, headers: { "retry-after": "2" }, json: { detail: "Too many requests -- wait a minute" } }));
  await send(page, "mock 429");
  await expect(vis(page, "system-rate")).toBeVisible({ timeout: 10_000 });
  await page.unroute(`${API}/chat`);
  await page.waitForTimeout(2500);
  // an error, then Retry: the question is sent once more and the mocked answer writes itself out
  let calls = 0;
  await page.route(`${API}/chat`, (r) => {
    calls += 1;
    if (calls === 1) return r.fulfill({ status: 500, json: { detail: "boom" } });
    return r.fulfill({ json: { answer: "A mocked answer after the **retry**.", thread_id: NEW_TID, message_id: "w10-retry", sources: [], squad_preview: null, squad_applied: null } });
  });
  await expect(vis(page, "chat-input")).toBeEnabled({ timeout: 70_000 });
  await send(page, "mock failure");
  await expect(vis(page, "system-error")).toBeVisible({ timeout: 10_000 });
  await vis(page, "retry").click();
  await expect(vis(page, "assistant-message").last()).toContainText("A mocked answer after the retry.", { timeout: 20_000 });
  await expect(vis(page, "assistant-message").last()).toHaveAttribute("data-revealing", "false", { timeout: 10_000 });
  await page.unroute(`${API}/chat`);
  note(`W4 message steps (seeded) ${info.project.name}: Sources pop-up, thumbs, Yes, 429, error + Retry PASS (chat calls on the retry route ${calls})`);
  await shot(page, "w4_steps_seeded");
});

test("axe: 0 serious / critical on /home and /chat (with the down-arrow and a revealing answer on screen)", async ({}, info) => {
  test.setTimeout(120_000);
  test.skip(info.project.name !== "desktop", "desktop run");
  await seed(page, { teams: 2, threads: 6 });
  await page.goto("/home");
  await expect(page.locator('[data-testid="home"][data-state="returning"]:visible')).toBeVisible({ timeout: 60_000 });
  const home = await new AxeBuilder({ page }).analyze();
  const homeBad = home.violations.filter((v) => v.impact === "serious" || v.impact === "critical");
  answer.text = LONG;
  answer.delayMs = 300;
  await page.goto(`/chat/${SAVED_TID}`);
  await expect(vis(page, "assistant-message")).toHaveCount(3, { timeout: 30_000 });
  await send(page, "Axe check.");
  await expect(vis(page, "assistant-message")).toHaveCount(4, { timeout: 30_000 });
  const chat = await new AxeBuilder({ page }).analyze();
  const chatBad = chat.violations.filter((v) => v.impact === "serious" || v.impact === "critical");
  note(`axe /home serious+critical ${homeBad.length}${homeBad.length ? ` ${homeBad.map((v) => v.id).join(",")}` : ""}; /chat ${chatBad.length}${chatBad.length ? ` ${chatBad.map((v) => v.id).join(",")}` : ""}`);
  for (const v of [...homeBad, ...chatBad]) note(`axe ${v.id} (${v.impact}): ${v.nodes.map((n) => `${n.target.join(" ")} -- ${(n.failureSummary ?? "").replace(/\s+/g, " ").slice(0, 160)}`).join(" || ").slice(0, 600)}`);
  expect(homeBad.length).toBe(0);
  expect(chatBad.length).toBe(0);
});
