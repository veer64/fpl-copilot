import { expect, test, type BrowserContext, type Page } from "@playwright/test";
import { acquireUser, releaseUser, userName } from "./clerk-users";
import { API, signIn } from "./w4";

/** Prompt W8a (2026-11-12): the chat thread must scroll to the top of a long answer and must never move a reader who has
 *  scrolled up. Seeded, no agent turn, no FPL request: the backend's /threads, /threads/{id}/messages, the team card and
 *  POST /chat are route mocks in the browser (the real :8010 backend answers /me, /deadlines). Cases from the live bug:
 *  general mode on a desktop (the thread was flex-centred in the scroll box, half of a long answer unreachable), team mode,
 *  the phone (touch swipe), music playing / muted / never started, idle and while a new answer is thinking; a new answer
 *  while scrolled up never yanks; at the bottom the thread follows; the message list does not re-render on music, timers
 *  or a card reload. Clerk test user w8a (deleted at the end). Anthropic $0, FPL 0.
 *  W10 (2026-11-12) replaced "a new answer follows at the bottom" with: on send and when a saved chat opens, the latest
 *  question sits at the top of the box (16 px gap); an arriving answer -- which now writes itself out -- never moves the
 *  view; the round down-arrow takes the reader to the end. The assertions below follow that rule. */

test.describe.configure({ mode: "serial" });
const NAME = userName("w8a"); // W10: E2E_SHARED_USER runs it on the run's one test user
const GAP = 16;
const TEAM = 4679878;
const TID = "w8a-long-thread";
let userId: string | null = null;

const XI = [["GK", "Raya", "ARS", "ful (H)", "4.8"], ["DEF", "Gabriel", "ARS", "ful (H)", "4.6"], ["DEF", "Van Dijk", "LIV", "mci (A)", "3.9"], ["DEF", "Muñoz", "CRY", "bou (H)", "3.5"],
  ["MID", "Salah (C)", "LIV", "mci (A)", "7.4"], ["MID", "Palmer", "CHE", "whu (H)", "6.1"], ["MID", "Saka", "ARS", "ful (H)", "5.8"], ["MID", "Rogers", "AVL", "lee (H)", "4.4"],
  ["FWD", "Haaland", "MCI", "liv (H)", "7.9"], ["FWD", "Watkins", "AVL", "lee (H)", "5.0"], ["FWD", "Wood", "NFO", "eve (A)", "4.2"]];
const BENCH = [["GK", "Sels", "NFO", "eve (A)", "3.3"], ["DEF", "Lewis", "MCI", "liv (H)", "2.4"], ["MID", "Ndiaye", "EVE", "nfo (H)", "3.1"], ["FWD", "Welbeck", "BHA", "tot (A)", "3.0"]];
const table = (rows: string[][]) => ["| Pos | Player | Club | Fixture | xPts |", "|---|---|---|---|---|", ...rows.map((r) => `| ${r.join(" | ")} |`)].join("\n");
/** ~3,000 characters, two tables -- the shape of the answer in the owner's screenshot */
export const LONG_ANSWER = [
  "Here is your squad for GW11 with the model's expected points for the next fixture. The predictions use the Tuesday night run (GW11, nightly), the availability feed as of Wednesday 11:01 UTC and the latest odds; the captaincy stays on Salah, who edges Haaland on the ceiling even away at City.",
  "", "**Starting XI (3-4-3)**", "", table(XI), "",
  "Three things stand out. First, the defence is thin on clean-sheet odds this week: Arsenal at home to Fulham is the only fixture above 45%, so Gabriel is the pick for the armband among defenders if you ever need one. Second, Rogers and Watkins both face Leeds, whose expected goals conceded is the fourth highest in the league since GW6, which is why the model keeps both despite the recent blank. Third, Wood's minutes are the risk: he came off at 71 minutes last week with cramp, but Forest's press conference on Thursday had no concern, so he stays as the third forward.",
  "", "**Bench**", "", table(BENCH), "",
  "Bench order matters less than usual: Lewis is the autosub most likely to come on (Van Dijk carries a 12% chance of rotation after the midweek), so keep him first. Sels is a straight backup. If you want to free the free transfer for next week, the cheapest sensible move is Welbeck to a 4.5m forward with two home games, but the model's gain is under 0.3 points, so the recommendation is to roll it.",
  "", "Expected total for the starting XI: **57.6 points**, bench **11.8**. Ask me to swap any two players and I will show you the preview before anything changes.",
].join("\n");
const QUESTION = "Show me my squad for GW11 with expected points for each player.";

type Mode = "team" | "general";
const rows = () => [
  { role: "user", text: QUESTION, at: "2026-11-12T01:10:00Z" },
  { role: "assistant", text: LONG_ANSWER, at: "2026-11-12T01:10:21Z", message_id: "w8a-msg-1", sources: [], squad_preview: null, squad_applied: null, feedback: null },
];
const threadRow = (mode: Mode) => ({ thread_id: TID, created_at: "2026-11-12T01:10:00Z", last_active: "2026-11-12T01:10:21Z", is_default: false, title: null, team_label: null, fpl_team_id: mode === "team" ? TEAM : null, team_name: mode === "team" ? "W8a Test XI" : null, updated_at: "2026-11-12T01:10:21Z" });

type Metrics = { scrollTop: number; maxScroll: number; threadTop: number; firstMsgTop: number; lastUserTop: number; renders: number };
async function metrics(page: Page): Promise<Metrics> {
  return page.locator('[data-testid="thread-scroll"]:visible').first().evaluate((el) => {
    const r = el.getBoundingClientRect();
    const t = el.querySelector(".ch-thread")!.getBoundingClientRect();
    const first = el.querySelector('[data-testid="user-message"]')?.getBoundingClientRect();
    const users = el.querySelectorAll('[data-testid="user-message"]');
    const lastUser = users.length ? users[users.length - 1].getBoundingClientRect() : null;
    const list = el.querySelector('[data-testid="message-list"]') as HTMLElement | null;
    return { scrollTop: Math.round(el.scrollTop), maxScroll: el.scrollHeight - el.clientHeight, threadTop: Math.round(t.top - r.top), firstMsgTop: first ? Math.round(first.top - r.top) : -9999, lastUserTop: lastUser ? Math.round(lastUser.top - r.top) : -9999, renders: Number(list?.dataset.renders ?? -1) };
  });
}
const toTop = (page: Page) => page.locator('[data-testid="thread-scroll"]:visible').first().evaluate((el) => { el.scrollTop = 0; });
const toBottom = (page: Page) => page.locator('[data-testid="thread-scroll"]:visible').first().evaluate((el) => { el.scrollTop = el.scrollHeight; });

/** mocks + open the seeded chat; the POST /chat mock answers after `delay()` ms with the long answer */
async function openSeeded(page: Page, mode: Mode, delay: { ms: number }) {
  let n = 1;
  await page.route(`${API}/threads`, (r) => r.fulfill({ json: [threadRow(mode)] }));
  await page.route(`${API}/threads/${TID}/messages`, (r) => r.fulfill({ json: rows() }));
  await page.route(`${API}/me/teams/${TEAM}/card`, (r) => r.fulfill({ status: 503, json: { detail: "card mocked away for the scroll test" } }));
  await page.route(`${API}/me/teams/${TEAM}/activate`, (r) => r.fulfill({ json: { ok: true } }));
  await page.route(`${API}/chat`, async (r) => {
    n += 1;
    await new Promise((res) => setTimeout(res, delay.ms));
    await r.fulfill({ json: { answer: LONG_ANSWER, thread_id: TID, message_id: `w8a-msg-${n}`, sources: [], squad_preview: null, squad_applied: null } });
  });
  await page.goto(`/chat/${TID}`);
  await expect(page.locator('[data-testid="chat"][data-ready="true"]:visible')).toBeVisible({ timeout: 60_000 });
  await expect(page.locator('[data-testid="assistant-message"]:visible')).toHaveCount(1);
  await page.waitForTimeout(500);
}

test.beforeAll(async () => {
  userId = await acquireUser(NAME);
});
test.afterAll(async () => {
  await releaseUser(NAME, userId);
});

for (const mode of ["general", "team"] as Mode[]) {
  test(`${mode} mode: the whole long answer is reachable; wheel / keys / scrollbar; music, idle, thinking never move a reader who scrolled up; a new answer follows only from the bottom`, async ({ page }, info) => {
    test.setTimeout(240_000);
    test.skip(info.project.name !== "desktop", "desktop case");
    await signIn(page, `${NAME}+clerk_test@example.com`);
    const delay = { ms: 12_000 };
    await openSeeded(page, mode, delay);
    const m0 = await metrics(page);
    expect(m0.maxScroll).toBeGreaterThan(300); // a long answer: the thread overflows the box
    expect(Math.abs(m0.lastUserTop - GAP)).toBeLessThanOrEqual(4); // W10: a chat opens with its last question at the top
    // wheel up to the very top: the question (the first message) is fully inside the box
    const box = (await page.locator('[data-testid="thread-scroll"]:visible').first().boundingBox())!;
    await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
    for (let i = 0; i < 8; i++) await page.mouse.wheel(0, -600);
    await page.waitForTimeout(400);
    const top = await metrics(page);
    expect(top.scrollTop).toBe(0);
    expect(top.threadTop).toBeGreaterThanOrEqual(0);
    expect(top.firstMsgTop).toBeGreaterThanOrEqual(0);
    await expect(page.locator('[data-testid="user-message"]:visible').first()).toBeInViewport();
    // keyboard: End then Home after clicking the thread
    await page.locator('[data-testid="thread-scroll"]:visible').first().click({ position: { x: 20, y: 20 } });
    await page.keyboard.press("End");
    await page.waitForTimeout(200);
    expect((await metrics(page)).scrollTop).toBe(m0.maxScroll);
    await page.keyboard.press("Home");
    await page.waitForTimeout(200);
    expect((await metrics(page)).scrollTop).toBe(0);
    // music playing (the sound toggle), 10 s idle while scrolled up: still at the top, and the message list did not re-render
    const toggle = page.locator('[data-testid="sound-toggle"]:visible').first();
    const audio = page.locator('[data-testid="site-audio"]');
    const playingBefore = (await audio.getAttribute("data-playing")) === "true";
    if (!playingBefore) await toggle.click();
    await expect(audio).toHaveAttribute("data-playing", "true", { timeout: 10_000 });
    const r0 = (await metrics(page)).renders;
    await page.waitForTimeout(10_000);
    const idle = await metrics(page);
    expect(idle.scrollTop).toBe(0);
    expect(idle.renders).toBe(r0); // the music and the page's 1 s / 60 s ticks never reach the list
    // muted: still at the top
    await toggle.click();
    await expect(audio).toHaveAttribute("data-playing", "false", { timeout: 10_000 });
    await page.waitForTimeout(1500);
    expect((await metrics(page)).scrollTop).toBe(0);
    // a card reload (team mode: the card's Retry) must not re-render the list either
    if (mode === "team") {
      const retry = page.locator('[data-testid="team-card-panel"] button:has-text("Retry"), .ch-right button:has-text("Retry")').first();
      if (await retry.count()) {
        const r1 = (await metrics(page)).renders;
        await retry.click();
        await page.waitForTimeout(1500);
        expect((await metrics(page)).renders).toBe(r1);
        expect((await metrics(page)).scrollTop).toBe(0);
      }
    }
    // thinking: send (W10: the question goes to the top of the box), scroll up during the wait, stay there, no yank
    await page.locator('[data-testid="chat-input"]:visible').fill("And who should I bench this week?");
    await page.keyboard.press("Enter");
    await expect(page.locator('[data-testid="thinking"]:visible')).toBeVisible({ timeout: 5_000 });
    await page.waitForTimeout(300);
    const sent = await metrics(page);
    expect(Math.abs(sent.lastUserTop - GAP)).toBeLessThanOrEqual(4);
    await toTop(page);
    await page.waitForTimeout(3000);
    expect((await metrics(page)).scrollTop).toBe(0);
    await page.waitForTimeout(3000);
    expect((await metrics(page)).scrollTop).toBe(0);
    await expect(page.locator('[data-testid="assistant-message"]:visible')).toHaveCount(2, { timeout: 30_000 });
    await page.waitForTimeout(400);
    const landed = await metrics(page);
    expect(landed.scrollTop).toBe(0); // not yanked
    expect(landed.firstMsgTop).toBeGreaterThanOrEqual(0);
    // W10: from the bottom, send -> the question at the top; the answer arrives and writes itself out: the view never moves
    delay.ms = 1500;
    await toBottom(page);
    await page.waitForTimeout(300);
    await page.locator('[data-testid="chat-input"]:visible').fill("Thanks, once more please.");
    await page.keyboard.press("Enter");
    await page.waitForTimeout(300);
    const asked = await metrics(page);
    expect(Math.abs(asked.lastUserTop - GAP)).toBeLessThanOrEqual(4);
    await expect(page.locator('[data-testid="assistant-message"]:visible')).toHaveCount(3, { timeout: 30_000 });
    for (let k = 0; k < 12; k++) {
      expect((await metrics(page)).scrollTop).toBe(asked.scrollTop);
      await page.waitForTimeout(400);
    }
    await expect(page.locator('[data-testid="assistant-message"][data-revealing="false"]:visible')).toHaveCount(3, { timeout: 10_000 });
    expect((await metrics(page)).scrollTop).toBe(asked.scrollTop);
    // the down-arrow takes the reader to the end
    await page.locator('[data-testid="scroll-down"]:visible').click();
    await page.waitForTimeout(1200);
    const end = await metrics(page);
    expect(end.maxScroll - end.scrollTop).toBeLessThanOrEqual(24);
    await expect(page.locator('[data-testid="scroll-down"]:visible')).toHaveCount(0);
    // and the top is still reachable afterwards
    await toTop(page);
    await page.waitForTimeout(200);
    expect((await metrics(page)).firstMsgTop).toBeGreaterThanOrEqual(0);
  });
}

test("1920x1080 general: the top of the long answer is reachable", async ({ browser }, info) => {
  test.skip(info.project.name !== "desktop", "desktop case");
  const ctx: BrowserContext = await browser.newContext({ viewport: { width: 1920, height: 1080 } });
  const page = await ctx.newPage();
  await signIn(page, `${NAME}+clerk_test@example.com`);
  await openSeeded(page, "general", { ms: 1000 });
  await toTop(page);
  await page.waitForTimeout(200);
  const m = await metrics(page);
  expect(m.scrollTop).toBe(0);
  expect(m.firstMsgTop).toBeGreaterThanOrEqual(0);
  await ctx.close();
});

test("phone 390x844 (touch): swipe to the top of the long answer in team and general mode; a new answer while scrolled up does not yank", async ({ page, context }, info) => {
  test.skip(info.project.name !== "mobile", "phone case");
  test.setTimeout(240_000);
  await signIn(page, `${NAME}+clerk_test@example.com`);
  for (const mode of ["team", "general"] as Mode[]) {
    await page.unrouteAll({ behavior: "ignoreErrors" });
    const delay = { ms: 8000 };
    await openSeeded(page, mode, delay);
    const m0 = await metrics(page);
    expect(m0.maxScroll).toBeGreaterThan(300);
    expect(Math.abs(m0.lastUserTop - GAP)).toBeLessThanOrEqual(4); // W10: the last question at the top on open
    const box = (await page.locator('[data-testid="thread-scroll"]:visible').first().boundingBox())!;
    const cdp = await context.newCDPSession(page);
    const x = box.x + box.width / 2;
    for (let s = 0; s < 6; s++) {
      await cdp.send("Input.dispatchTouchEvent", { type: "touchStart", touchPoints: [{ x, y: box.y + 80 }] });
      for (let k = 1; k <= 12; k++) await cdp.send("Input.dispatchTouchEvent", { type: "touchMove", touchPoints: [{ x, y: box.y + 80 + k * 40 }] });
      await cdp.send("Input.dispatchTouchEvent", { type: "touchEnd", touchPoints: [] });
      await page.waitForTimeout(250);
    }
    await page.waitForTimeout(600);
    const top = await metrics(page);
    expect(top.scrollTop).toBe(0);
    expect(top.firstMsgTop).toBeGreaterThanOrEqual(0);
    await expect(page.locator('[data-testid="user-message"]:visible').first()).toBeInViewport();
    // a new answer while scrolled up: not yanked
    await page.locator('[data-testid="chat-input"]:visible').fill("And who should I bench?");
    await page.keyboard.press("Enter");
    await expect(page.locator('[data-testid="thinking"]:visible')).toBeVisible({ timeout: 5_000 });
    await toTop(page);
    await page.waitForTimeout(2000);
    expect((await metrics(page)).scrollTop).toBe(0);
    await expect(page.locator('[data-testid="assistant-message"]:visible')).toHaveCount(2, { timeout: 30_000 });
    await page.waitForTimeout(400);
    expect((await metrics(page)).scrollTop).toBe(0);
    await cdp.detach();
  }
});

test("seeded resume (the W7b F3 shape): a pending row on load shows Still working with the question at the top, the answer appears on the next read (at once, not typed) and the view does not move", async ({ page }, info) => {
  test.skip(info.project.name !== "desktop", "desktop case");
  await signIn(page, `${NAME}+clerk_test@example.com`);
  let reads = 0;
  await page.route(`${API}/threads`, (r) => r.fulfill({ json: [threadRow("general")] }));
  await page.route(`${API}/threads/${TID}/messages`, (r) => {
    reads += 1;
    const base = rows();
    const pending = { role: "pending", text: "And who should I bench this week?", started_at: new Date(Date.now() - 4000).toISOString(), message_id: "w8a-pending" };
    const answer = { role: "assistant", text: LONG_ANSWER, at: new Date().toISOString(), message_id: "w8a-msg-9", sources: [], squad_preview: null, squad_applied: null, feedback: null };
    r.fulfill({ json: reads < 2 ? [...base, pending] : [...base, { role: "user", text: pending.text, at: pending.started_at }, answer] });
  });
  await page.goto(`/chat/${TID}`);
  await expect(page.locator('[data-testid="thinking"][data-resumed="true"]:visible')).toBeVisible({ timeout: 30_000 });
  const m0 = await metrics(page);
  expect(Math.abs(m0.lastUserTop - GAP)).toBeLessThanOrEqual(4); // W10: the pending question at the top, Still working under it
  await expect(page.locator('[data-testid="assistant-message"]:visible')).toHaveCount(2, { timeout: 30_000 });
  await expect(page.locator('[data-testid="assistant-message"][data-revealing="true"]:visible')).toHaveCount(0); // stored: at once
  await page.waitForTimeout(500);
  const m1 = await metrics(page);
  expect(m1.scrollTop).toBe(m0.scrollTop); // the answer arrived: the view did not move
  expect(reads).toBeGreaterThanOrEqual(2);
  await toTop(page);
  await page.waitForTimeout(200);
  expect((await metrics(page)).firstMsgTop).toBeGreaterThanOrEqual(0);
});
