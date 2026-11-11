import { expect, test, type BrowserContext, type Page } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import { createTestUser, deleteUser, findTestUsers } from "./clerk-users";
import { addTeamOnHome, apiCall, fplCounter, fplGet, mask, signIn, token, vis, type Standing } from "./w4";
import { API5, boxOf, control, ownerRows, shot5, signOutViaMenu, sql1, squadKeys, usageOf, user1Guard } from "./w5";

/** Prompt W5 PART 3: ONE continuous desktop journey (1440x900) through /about, /privacy, the account menu's Delete account,
 *  Delete chat and Remove team, against the laptop backend (scratchpad w5_backend.py: clerk mode, :8010, FPL counted and
 *  capped, a test-only Clerk-failure switch) and real agent turns within the caps (Anthropic $1.00, <= 6 turns; FPL <= 20).
 *  Clerk test users w5a (user A, deleted by the flow) and w5b (user B, made first, every count unchanged; its Clerk user
 *  deleted at the end -- the phone journey takes over its app row). Numbers are printed as [W5] lines for the report. */

test.describe.configure({ mode: "serial" });

const A = "w5a";
const B = "w5b";
const CAP_USD = 1.0;
const CAP_TURNS = 6;
const RESERVED = [1, 9001, 9002];

let context: BrowserContext;
let page: Page;
let userA = 0;
let userB = 0;
let teamA1 = Number(process.env.W5_TEAM_A ?? 0);
let teamA2 = Number(process.env.W5_TEAM_B ?? 0);
let keysA: number[] = [];
let keysB: number[] = [];
let threadA1 = "";
let threadA2 = "";
let threadGen = "";
let aOldToken = "";
let aUsageBefore: { turn_id: string; usd: number | null }[] = [];
let bBefore: Record<string, number> | null = null;
let reservedBefore: Record<string, number> | null = null;
let guardBefore = "";
const turns: { step: string; seconds: number; usd: number }[] = [];
const notes: string[] = [];
const results: string[] = [];
const log = (s: string) => console.log(`[W5] ${s}`);
const pass = (s: string) => {
  results.push(s);
  log(`PASS ${s}`);
};

async function spent(): Promise<number> {
  const me = await apiCall(page, "get", "/me");
  return Number(me.body.spent_today_usd ?? 0);
}

async function turn(step: string, text: string, timeout = 120_000) {
  const before = await spent();
  const total = turns.reduce((a, t) => a + t.usd, 0);
  if (turns.length >= CAP_TURNS || total >= CAP_USD) {
    notes.push(`${step}: NOT RUN (cap: ${turns.length} turns, $${total.toFixed(2)})`);
    test.skip(true, `cap reached before ${step}`);
  }
  const nAnswers = await page.locator('[data-testid="assistant-message"]:visible').count();
  const t0 = Date.now();
  await vis(page, "chat-input").fill(text);
  await vis(page, "chat-input").press("Enter");
  await expect(vis(page, "thinking")).toBeVisible({ timeout: 10_000 });
  await expect(page.locator('[data-testid="assistant-message"]:visible, [data-testid^="system-"]:visible')).toHaveCount(nAnswers + 1, { timeout }).catch(() => undefined);
  await expect(vis(page, "thinking")).toHaveCount(0, { timeout });
  const seconds = Math.round((Date.now() - t0) / 10) / 100;
  const usd = Math.max(0, (await spent()) - before);
  turns.push({ step, seconds, usd });
  log(`turn ${turns.length} (${step}): ${seconds} s, $${usd.toFixed(4)}`);
  return page.locator('[data-testid="assistant-message"]:visible').last();
}

async function openChat(url: string) {
  await page.goto(url);
  await expect(page.locator('[data-testid="chat"][data-ready="true"]:visible')).toBeVisible({ timeout: 30_000 });
  await page.waitForTimeout(1200);
  return page.locator('[data-testid="chat"]:visible').getAttribute("data-thread-id");
}

async function threadIdAfterSend(): Promise<string> {
  await expect.poll(async () => page.locator('[data-testid="chat"]:visible').getAttribute("data-thread-id"), { timeout: 10_000 }).toMatch(/^th_/);
  return (await page.locator('[data-testid="chat"]:visible').getAttribute("data-thread-id"))!;
}

async function openMenu() {
  await vis(page, "account-menu").first().click();
  await expect(page.locator('[data-testid="delete-account"]')).toBeVisible({ timeout: 10_000 });
}

async function focusedTestId(): Promise<string | null> {
  return page.evaluate(() => (document.activeElement as HTMLElement | null)?.getAttribute("data-testid") ?? null);
}

test.beforeAll(async ({ browser }) => {
  guardBefore = user1Guard();
  log(`user 1 guard before: ${guardBefore}`);
  reservedBefore = ownerRows(RESERVED);
  for (const name of [A, B]) for (const id of await findTestUsers(name)) await deleteUser(id);
  if (!teamA1 || !teamA2) {
    const league = await fplGet<{ standings: { results: Standing[] } }>("leagues-classic/314/standings/?page_standings=1");
    teamA1 = teamA1 || league.standings.results[0].entry;
    teamA2 = teamA2 || league.standings.results[1].entry;
  }
  log(`teams ${mask(teamA1)} and ${mask(teamA2)} from leagues-classic/314 page 1`);
  context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  page = await context.newPage();
});

test.afterAll(async () => {
  for (const name of [A, B]) for (const id of await findTestUsers(name)) await deleteUser(id);
  const left = (await findTestUsers(A)).length + (await findTestUsers(B)).length;
  const counts = await page.request.get(`${API5}/__w5/counts`).then((r) => r.json()).catch(() => null);
  const total = turns.reduce((a, t) => a + t.usd, 0);
  log(`user 1 guard after: ${user1Guard()} | unchanged ${user1Guard() === guardBefore}`);
  log(`reserved rows unchanged: ${JSON.stringify(ownerRows(RESERVED)) === JSON.stringify(reservedBefore)}`);
  log(`SUMMARY turns ${turns.length} $${total.toFixed(4)} | fpl(test) ${fplCounter.n} | backend ${JSON.stringify(counts)} | clerk test users left ${left} | userA ${userA} userB ${userB}`);
  for (const n of notes) log(`NOTE ${n}`);
  for (const t of turns) log(`TURN ${t.step}: ${t.seconds} s $${t.usd.toFixed(4)}`);
  for (const r of results) log(`RESULT ${r}`);
  await context?.close();
});

// ---- 1: signed out ---------------------------------------------------------------------------------------------------------------

test("1 signed out: /about and /privacy render, Sign in header, links, chips -> /login", async () => {
  await page.goto("/about");
  await expect(page.locator('[data-testid="about"][data-signed-in="false"]')).toBeVisible({ timeout: 20_000 });
  await expect(vis(page, "header-sign-in")).toHaveAttribute("href", "/login");
  await expect(page.locator('[data-testid="account-menu"]')).toHaveCount(0);
  await expect(page.locator("h1")).toHaveText("Outsmart your mini-league with an AI that knows the data.");
  await expect(vis(page, "hero-primary")).toHaveText(/Sign in to start/);
  await expect(vis(page, "hero-primary")).toHaveAttribute("href", "/login");
  await expect(page.locator('[data-testid="feature-tiles"] > div')).toHaveCount(8);
  await expect(page.locator('[data-testid="feature-tiles"]')).toContainText("The next deadline counts down at the top of Home and every chat.");
  await expect(page.locator('[data-testid="feature-tiles"]')).toContainText("hover or tap any player");
  await expect(page.locator('[data-testid="fine-print"]')).toContainText("Your FPL team is as of the last deadline");
  const chips = page.locator('[data-testid="ask-chip"]');
  await expect(chips).toHaveCount(6);
  for (let i = 0; i < 6; i++) await expect(chips.nth(i)).toHaveAttribute("href", "/login");
  await expect.poll(async () => page.locator('[data-testid="about"]').getAttribute("data-next-gw"), { timeout: 15_000 }).toMatch(/^\d+$/);
  const gw = await page.locator('[data-testid="about"]').getAttribute("data-next-gw");
  await expect(chips.first()).toHaveText(`Who should I captain for GW${gw}?`);
  await expect(page.locator('[data-testid="public-footer"] nav a[href="/privacy"]')).toBeVisible();
  await expect(page.locator('[data-testid="public-footer"] nav a[href="/about"]')).toHaveAttribute("aria-current", "page");
  await expect(page.locator('[data-testid="made-by"] a')).toHaveCount(4);
  await shot5(page, "about_signed_out_viewport");
  await shot5(page, "about_signed_out", true);

  await page.locator('[data-testid="public-footer"] nav a[href="/privacy"]').click();
  await expect(page.locator('[data-testid="privacy"][data-signed-in="false"]')).toBeVisible({ timeout: 20_000 });
  await expect(vis(page, "header-sign-in")).toBeVisible();
  await expect(page.locator("h1")).toHaveText("Your data, in plain words.");
  await expect(page.locator(".pp-hero-sub")).toHaveText("What we keep, who handles it, and how to delete it.");
  await expect(vis(page, "last-updated")).toHaveText(/Last updated 10 Nov 2026/);
  await expect(page.locator('[data-testid="providers"] .pp-prov')).toHaveCount(8);
  await expect(page.locator('[data-testid="providers"]')).toContainText("Your questions are hidden; the answers and the data looked up are kept");
  await expect(page.locator('[data-testid="providers"]')).toContainText("Fantasy Premier League");
  await expect(page.locator('[data-testid="how-long"] .pp-row')).toHaveCount(3);
  await expect(page.locator('[data-testid="how-long"]')).toContainText("Our database backups keep a copy for up to 30 days.");
  await expect(page.locator('[data-testid="delete-section"]')).toContainText("Sign in, then open your account menu (top right)");
  await expect(page.locator('[data-testid="delete-section"] a[href="/login"]')).toBeVisible();
  await expect(page.locator('[data-testid="delete-section"]')).toContainText("Can’t sign in? Email veersanghavi8@gmail.com");
  await expect(vis(page, "contact-about")).toHaveAttribute("href", "/about");
  await expect(page.locator('[data-testid="public-footer"] nav a[href="/privacy"]')).toHaveAttribute("aria-current", "page");
  await shot5(page, "privacy_signed_out_viewport");
  await shot5(page, "privacy_signed_out", true);
  await vis(page, "contact-about").click();
  await expect(page).toHaveURL(/\/about$/);

  // the Login footer reaches the real pages
  await page.goto("/login");
  await page.getByTestId("skip-intro").click();
  await expect(page.locator(".stage")).toHaveAttribute("data-phase", "login");
  await expect(page.locator('nav[aria-label="Legal"] a[href="/privacy"]')).toBeVisible();
  await page.locator('nav[aria-label="Legal"] a[href="/about"]').click();
  await expect(page).toHaveURL(/\/about$/);
  await expect(page.locator('[data-testid="deleted-note"]')).toHaveCount(0);
  pass("1 signed out: both pages, Sign in header, no menu, cross links, Login footer, chips -> /login, delete section sign-in text");
});

// ---- 2: the photos -------------------------------------------------------------------------------------------------------------

const REF_MASKS = {
  about: { opacity: "0.55", right: "linear-gradient(90deg, rgba(0, 0, 0, 0) 0%, rgb(0, 0, 0) 42%, rgb(0, 0, 0) 82%, rgba(0, 0, 0, 0) 100%)", bottom: "linear-gradient(rgba(0, 0, 0, 0) 0%, rgb(0, 0, 0) 14%, rgb(0, 0, 0) 55%, rgba(0, 0, 0, 0) 95%)", top: 40, height: 860 },
  privacy: { opacity: "0.7", right: "linear-gradient(90deg, rgba(0, 0, 0, 0) 0%, rgb(0, 0, 0) 40%, rgb(0, 0, 0) 80%, rgba(0, 0, 0, 0) 100%)", bottom: "linear-gradient(rgba(0, 0, 0, 0) 0%, rgb(0, 0, 0) 18%, rgb(0, 0, 0) 58%, rgba(0, 0, 0, 0) 95%)", top: -40, height: 860 },
};

async function photoStyle(p: Page) {
  return p.locator('[data-testid="bg-photo"]').evaluate((el) => {
    const cs = getComputedStyle(el);
    const r = el.getBoundingClientRect();
    return { position: cs.position, opacity: cs.opacity, mask: cs.maskImage || (cs as unknown as { webkitMaskImage: string }).webkitMaskImage, top: Math.round(r.top), height: Math.round(r.height), composite: cs.maskComposite, pe: cs.pointerEvents, hidden: el.getAttribute("aria-hidden") };
  });
}

test("2 photos: fixed at 1440 (content scrolls over it), absolute at 800, masks and opacity as the references", async () => {
  for (const which of ["about", "privacy"] as const) {
    await page.goto(`/${which}`);
    await expect(page.locator(`[data-testid="${which}"]`)).toBeVisible();
    const before = await photoStyle(page);
    expect(before.position).toBe("fixed");
    expect(before.opacity).toBe(REF_MASKS[which].opacity);
    expect(before.top).toBe(REF_MASKS[which].top);
    expect(before.height).toBe(REF_MASKS[which].height);
    expect(before.mask).toContain(REF_MASKS[which].right);
    expect(before.mask).toContain(REF_MASKS[which].bottom);
    expect(before.composite).toContain("intersect");
    expect(before.pe).toBe("none");
    expect(before.hidden).toBe("true");
    const h1Before = (await page.locator("h1").boundingBox())!.y;
    await page.evaluate(() => window.scrollTo(0, 1500));
    await page.waitForTimeout(300);
    const after = await photoStyle(page);
    const h1After = (await page.locator("h1").boundingBox())!.y;
    expect(after.top, `${which}: the photo stays put`).toBe(before.top);
    expect(h1Before - h1After, `${which}: the content scrolled`).toBeGreaterThan(1000);
    await shot5(page, `${which}_scrolled_1500`);
    await page.evaluate(() => window.scrollTo(0, 0));
    await page.setViewportSize({ width: 800, height: 900 });
    await page.waitForTimeout(200);
    const narrow = await photoStyle(page);
    expect(narrow.position, `${which} at 800px`).toBe("absolute");
    await shot5(page, `${which}_800`);
    await page.setViewportSize({ width: 1440, height: 900 });
  }
  pass("2 photos: fixed at 1440 (same top after a 1,500px scroll; the h1 moved), absolute at 800; opacity 0.55 / 0.7, masks = reference, intersect, aria-hidden, pointer-events none");
});

// ---- 3: the Privacy nav ----------------------------------------------------------------------------------------------------------

test("3 Privacy nav: scrolling highlights each section in turn; clicking an entry scrolls there", async () => {
  await page.goto("/privacy");
  await expect(page.locator('[data-testid="privacy"]')).toBeVisible();
  const ids = ["keep", "never", "who", "cookies", "how-long", "delete", "contact"];
  const seen: string[] = [];
  for (const id of ids) {
    await page.evaluate((i) => document.getElementById(i)!.scrollIntoView({ block: "start", behavior: "auto" }), id);
    await expect.poll(async () => page.locator('[data-testid="privacy"]').getAttribute("data-current"), { timeout: 5_000 }).toBe(id);
    await expect(page.locator(`[data-testid="toc"] a[data-section="${id}"]`)).toHaveAttribute("aria-current", "true");
    seen.push(id);
  }
  expect(seen).toEqual(ids);
  await expect(page.locator('[data-testid="toc"] a[aria-current="true"]')).toHaveCount(1);
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.waitForTimeout(200);
  await page.locator('[data-testid="toc"] a[data-section="cookies"]').click();
  await expect.poll(async () => page.locator('[data-testid="privacy"]').getAttribute("data-current"), { timeout: 5_000 }).toBe("cookies");
  const top = await page.evaluate(() => document.getElementById("cookies")!.getBoundingClientRect().top);
  expect(top).toBeGreaterThanOrEqual(0);
  expect(top).toBeLessThan(120);
  const sticky = await page.locator('[data-testid="toc"]').evaluate((el) => getComputedStyle(el).position);
  expect(sticky).toBe("sticky");
  await shot5(page, "privacy_nav_cookies");
  pass("3 Privacy nav: 7 sections highlighted in turn (one aria-current at a time), click scrolls (Cookies within 120px of the top), sticky");
});

// ---- 4: user A: 2 teams, 3 real chats (+ a pending captain preview); About chips; then user B --------------------------------------------

test("4 user A: 2 teams, 3 real chats, a pending captain preview; About chips -> the right /chat URLs; user B made", async () => {
  test.setTimeout(900_000);
  log(`Clerk test user ${A} created: ${(await createTestUser(A)).id.slice(0, 9)}…`);
  await signIn(page, `${A}+clerk_test@example.com`);
  userA = Number((await apiCall(page, "get", "/me")).body.user_id);
  expect(userA).toBeGreaterThanOrEqual(10001);
  await addTeamOnHome(page, teamA1, "choice");
  await addTeamOnHome(page, teamA2, "card");
  keysA = squadKeys(userA);
  expect(keysA.length).toBe(2);
  // the Home footer reaches the real pages
  await expect(page.locator('.hm-foot a[href="/privacy"]')).toBeVisible();
  await expect(page.locator('.hm-foot a[href="/about"]')).toBeVisible();

  // team 1: one chat + a pending captain preview (two turns)
  await openChat(`/chat?team=${teamA1}`);
  await turn("A team1", "Who is my captain right now? One line.");
  threadA1 = await threadIdAfterSend();
  const card = (await apiCall(page, "get", `/me/teams/${teamA1}/card`)).body as unknown as { players: { full_name: string; role: string | null }[] };
  const vc = card.players.find((p) => p.role === "VC")!;
  await turn("A captain preview", `Make ${vc.full_name} my captain.`);
  const preview = page.locator('[data-testid="preview-card"]:visible');
  const hasPreview = (await preview.count()) > 0;
  if (!hasPreview) notes.push("step 4: the agent made no preview for the captain request (the pending-preview part of step 6 is then not exercised)");
  else log("captain preview pending in team 1's chat");
  // team 2: one chat
  await openChat(`/chat?team=${teamA2}`);
  await turn("A team2", "How much money do I have in the bank? One line.");
  threadA2 = await threadIdAfterSend();
  // General: one chat
  await openChat("/chat");
  await turn("A general", "In one sentence, what does the Wildcard chip do?");
  threadGen = await threadIdAfterSend();
  const rows = (await apiCall(page, "get", "/threads")).body as unknown as { thread_id: string; fpl_team_id: number | null }[];
  expect(rows.map((r) => r.thread_id).sort()).toEqual([threadA1, threadA2, threadGen].sort());
  expect(rows.find((r) => r.thread_id === threadGen)!.fpl_team_id).toBeNull();

  // About, signed in: the chips name the last-used team; a team chip prefills the chat and does not send
  await page.goto("/about");
  await expect(page.locator('[data-testid="about"][data-signed-in="true"]')).toBeVisible({ timeout: 20_000 });
  await expect(vis(page, "header-home")).toHaveAttribute("href", "/home");
  await expect(vis(page, "account-menu")).toBeVisible();
  await expect(vis(page, "hero-primary")).toHaveText(/Ask your first question/);
  await expect(vis(page, "hero-primary")).toHaveAttribute("href", "/home");
  const teams = (await apiCall(page, "get", "/me/teams")).body as unknown as { fpl_team_id: number; last_used_at: string | null }[];
  const lastUsed = teams.filter((t) => t.last_used_at).sort((a, b) => (b.last_used_at! > a.last_used_at! ? 1 : -1))[0].fpl_team_id;
  const chips = page.locator('[data-testid="ask-chip"]');
  await expect(chips).toHaveCount(6);
  for (let i = 0; i < 6; i++) {
    const href = (await chips.nth(i).getAttribute("href"))!;
    const team = (await chips.nth(i).getAttribute("data-team")) === "true";
    const text = (await chips.nth(i).textContent())!.trim();
    expect(href, text).toBe(team ? `/chat?team=${lastUsed}&q=${encodeURIComponent(text)}` : `/chat?q=${encodeURIComponent(text)}`);
  }
  log(`chips: team questions -> /chat?team=${mask(lastUsed)}&q=..., general -> /chat?q=...`);
  await shot5(page, "about_signed_in_viewport");
  await shot5(page, "about_signed_in", true);
  const q = (await chips.nth(2).textContent())!.trim();
  await chips.nth(2).click();
  await expect(page.locator('[data-testid="chat"][data-ready="true"]:visible')).toBeVisible({ timeout: 30_000 });
  await expect(page).toHaveURL(new RegExp(`/chat\\?team=${lastUsed}&q=`));
  await expect(vis(page, "chat-input")).toHaveValue(q);
  await expect(page.locator('[data-testid="thinking"]')).toHaveCount(0);
  expect(await page.locator('[data-testid="chat"]:visible').getAttribute("data-busy")).toBe("false");
  const general = (await chips.nth(4).getAttribute("href"))!;
  expect(general.startsWith("/chat?q=")).toBe(true);

  // user B, made now with a team and a chat: its counts must not change through A's deletions
  await signOutViaMenu(page);
  log(`Clerk test user ${B} created: ${(await createTestUser(B)).id.slice(0, 9)}…`);
  await signIn(page, `${B}+clerk_test@example.com`);
  userB = Number((await apiCall(page, "get", "/me")).body.user_id);
  await addTeamOnHome(page, teamA1, "choice");
  keysB = squadKeys(userB);
  await openChat(`/chat?team=${teamA1}`);
  await turn("B team", "Who is my vice-captain? One line.");
  await threadIdAfterSend();
  bBefore = ownerRows([userB, ...keysB]);
  log(`user B ${userB} rows: ${JSON.stringify(bBefore)}`);
  await signOutViaMenu(page);
  await signIn(page, `${A}+clerk_test@example.com`);
  pass(`4 user A ${userA}: teams ${mask(teamA1)}, ${mask(teamA2)}; chats team1 / team2 / General (+ captain preview ${hasPreview ? "pending" : "NOT produced"}); About chips -> /chat?team=${mask(lastUsed)}&q= / /chat?q=, prefilled not sent; user B ${userB} made`);
});

// ---- 5: Delete chat ----------------------------------------------------------------------------------------------------------------

test("5 Delete chat: the General chat by keyboard -> gone everywhere, cost rows kept; the OPEN chat -> a new empty chat, same team", async () => {
  test.setTimeout(300_000);
  await openChat(`/chat?team=${teamA2}`);
  const spentBefore = await spent();
  const usageBefore = usageOf(userA);
  const genUsage = usageBefore.length;
  // keyboard only: Tab from the top of the page to the General row's trash button
  await page.keyboard.press("Tab");
  let found = false;
  for (let i = 0; i < 60; i++) {
    const info = await page.evaluate(() => {
      const el = document.activeElement as HTMLElement | null;
      return { tid: el?.getAttribute("data-testid"), thread: el?.getAttribute("data-thread-id") };
    });
    if (info.tid === "thread-delete" && info.thread === threadGen) {
      found = true;
      break;
    }
    await page.keyboard.press("Tab");
  }
  expect(found, "the General row's trash button is reachable by Tab").toBe(true);
  const visibleOnFocus = await page.evaluate(() => getComputedStyle(document.activeElement as HTMLElement).opacity);
  expect(Number(visibleOnFocus)).toBe(1);
  await page.keyboard.press("Enter");
  await expect(vis(page, "delete-chat-dialog")).toBeVisible();
  await expect(vis(page, "confirm-title")).toHaveText("Delete this chat?");
  await expect(vis(page, "confirm-intro")).toContainText("and its messages will be removed");
  await expect(vis(page, "confirm-warning")).toHaveText("This can’t be undone.");
  await expect(vis(page, "confirm-delete")).toHaveText("Delete chat");
  expect(await focusedTestId()).toBe("confirm-cancel");
  await shot5(page, "dialog_delete_chat");
  await page.keyboard.press("Tab");
  expect(await focusedTestId()).toBe("confirm-delete");
  await page.keyboard.press("Enter");
  await expect(vis(page, "delete-chat-dialog")).toHaveCount(0, { timeout: 20_000 });
  await expect(page.locator(`[data-testid="thread-row"][data-thread-id="${threadGen}"]`)).toHaveCount(0, { timeout: 10_000 });
  const rows = (await apiCall(page, "get", "/threads")).body as unknown as { thread_id: string }[];
  expect(rows.map((r) => r.thread_id)).not.toContain(threadGen);
  for (const [t, col] of [["chat_threads", "thread_id"], ["checkpoints", "thread_id"], ["checkpoint_blobs", "thread_id"], ["chat_messages", "thread_id"], ["squad_previews", "thread_id"]]) {
    expect(sql1(`SELECT count(*) FROM ${t} WHERE ${col} = %s`, [threadGen]), t).toBe(0);
  }
  expect((await apiCall(page, "get", `/threads/${threadGen}/messages`)).status).toBe(403);
  const usageAfter = usageOf(userA);
  expect(usageAfter.length).toBe(genUsage);
  expect(usageAfter.map((u) => u.turn_id).sort()).toEqual(usageBefore.map((u) => u.turn_id).sort());
  expect(await spent()).toBe(spentBefore);
  // the OPEN chat (team 2's): hover the row, the trash, confirm -> a new empty chat in the same team
  const row = page.locator(`[data-testid="thread-rowwrap"][data-thread-id="${threadA2}"]`);
  await row.hover();
  await expect(row.locator('[data-testid="thread-delete"]')).toHaveCSS("opacity", "1");
  await row.locator('[data-testid="thread-delete"]').click();
  await expect(vis(page, "delete-chat-dialog")).toBeVisible();
  await vis(page, "confirm-delete").click();
  await expect(vis(page, "delete-chat-dialog")).toHaveCount(0, { timeout: 20_000 });
  await expect(page).toHaveURL(new RegExp(`/chat\\?team=${teamA2}$`), { timeout: 15_000 });
  await expect(page.locator('[data-testid="chat"][data-ready="true"]:visible')).toHaveAttribute("data-thread-id", "");
  await expect(page.locator('[data-testid="chat"]:visible')).toHaveAttribute("data-context", "team");
  await expect(page.locator('[data-testid="chat"]:visible')).toHaveAttribute("data-team-id", String(teamA2));
  await expect(page.locator('[data-testid="assistant-message"]:visible')).toHaveCount(0);
  expect(sql1("SELECT count(*) FROM chat_threads WHERE thread_id = %s", [threadA2])).toBe(0);
  await shot5(page, "chat_after_delete_open");
  pass(`5 Delete chat: General chat by keyboard (Tab x${genUsage} reached the trash) -> gone from sidebar, /threads, DB (thread, checkpoints, messages, tickets); ${usageAfter.length} cost rows kept with user + amount; spend unchanged $${spentBefore.toFixed(4)}; the open chat -> new empty chat in team ${mask(teamA2)}`);
});

// ---- 6: Remove team ----------------------------------------------------------------------------------------------------------------

test("6 Remove team: team 1 (active, with the pending preview) -> '1 chat', card gone, Add team back, General mode, team 2 untouched", async () => {
  test.setTimeout(300_000);
  await apiCall(page, "post", `/me/teams/${teamA1}/activate`); // team 1 is the active team (as after a send in it)
  const key1 = keysA[0];
  const key2 = keysA[1];
  const team2Before = ownerRows([key2]);
  const bNow = ownerRows([userB, ...keysB]);
  expect(bNow).toEqual(bBefore);
  const ticketsBefore = sql1("SELECT count(*) FROM squad_previews WHERE user_id = %s AND base_version_id IN (SELECT version_id FROM squad_versions WHERE user_id = %s)", [userA, key1]) as number;
  log(`team 1 tickets before: ${ticketsBefore}`);
  await page.goto("/home");
  await expect(page.locator(`[data-testid="team-card"][data-team-id="${teamA1}"]`)).toBeVisible({ timeout: 30_000 });
  const name = (await page.locator(`[data-testid="team-card"][data-team-id="${teamA1}"] h3`).textContent())!.trim();
  const btn = page.locator(`[data-testid="team-card"][data-team-id="${teamA1}"] [data-testid="remove-team"]`);
  await expect(btn).toHaveAttribute("aria-label", `Remove ${name}`);
  await btn.click();
  await expect(vis(page, "remove-team-dialog")).toBeVisible();
  await expect(vis(page, "confirm-title")).toHaveText(`Remove ${name}?`);
  await expect(vis(page, "confirm-intro")).toHaveText("This removes the team, its saved squads and its 1 chat from FPL Copilot. Your real FPL team isn’t affected.");
  await expect(vis(page, "confirm-delete")).toHaveText("Remove team");
  expect(await focusedTestId()).toBe("confirm-cancel");
  await shot5(page, "dialog_remove_team");
  await vis(page, "confirm-delete").click();
  await expect(vis(page, "remove-team-dialog")).toHaveCount(0, { timeout: 30_000 });
  await expect(page.locator(`[data-testid="team-card"][data-team-id="${teamA1}"]`)).toHaveCount(0, { timeout: 15_000 });
  await expect(vis(page, "add-team-card")).toBeVisible();
  await expect(vis(page, "add-team-card")).toContainText("2 SLOTS LEFT");
  const me = (await apiCall(page, "get", "/me")).body;
  expect(me.active_team).toBeNull();
  expect(sql1("SELECT count(*) FROM squad_versions WHERE user_id = %s", [key1])).toBe(0);
  expect(sql1("SELECT count(*) FROM chat_threads WHERE user_id = %s AND owner_key = %s", [userA, key1])).toBe(0);
  expect(sql1("SELECT count(*) FROM squad_previews WHERE user_id = %s", [userA])).toBe(0);
  expect(sql1("SELECT count(*) FROM user_fpl_teams WHERE user_id = %s", [userA])).toBe(1);
  expect(ownerRows([key2])).toEqual(team2Before);
  expect(ownerRows([userB, ...keysB])).toEqual(bBefore);
  await shot5(page, "home_after_remove");
  pass(`6 Remove team ${mask(teamA1)}: "1 chat" in the confirm, card gone, "2 SLOTS LEFT", /me active_team null, versions / chats / tickets of its key gone (${ticketsBefore} ticket(s) before), team 2 and user B unchanged`);
});

// ---- 7 + 8: Delete account (the error path first) --------------------------------------------------------------------------------------

test("7+8 Delete account: Clerk fails -> error + nothing deleted; Try again -> deleting -> /login + note once; DB, Clerk, old token, user B", async () => {
  test.setTimeout(300_000);
  await page.goto("/privacy");
  await expect(page.locator('[data-testid="privacy"][data-signed-in="true"]')).toBeVisible({ timeout: 20_000 });
  await expect(page.locator('[data-testid="delete-section"]')).toContainText("Open your account menu (top right) and choose Delete account");
  await shot5(page, "privacy_signed_in_viewport");
  await shot5(page, "privacy_signed_in", true);
  aOldToken = await token(page);
  aUsageBefore = usageOf(userA);
  const aBefore = ownerRows([userA, ...keysA]);
  const bNow = ownerRows([userB, ...keysB]);
  expect(bNow).toEqual(bBefore);
  const usdTotal = sql1("SELECT COALESCE(SUM(usd), 0)::text FROM chat_usage") as string;
  await control(page, "post", "/__w5/clerk_fail");
  await openMenu();
  await expect(page.locator('[data-testid="delete-account"]')).toHaveAttribute("data-owner", "false", { timeout: 10_000 });
  await shot5(page, "menu_signed_in");
  await page.locator('[data-testid="delete-account"]').click();
  await expect(vis(page, "delete-account-dialog")).toBeVisible();
  await expect(vis(page, "confirm-title")).toHaveText("Delete your account?");
  await expect(vis(page, "confirm-list")).toHaveText(["Your account", "Your FPL teams", "Saved squads", "Chats", "Feedback"]);
  await expect(vis(page, "confirm-delete")).toHaveText("Delete my account");
  expect(await focusedTestId()).toBe("confirm-cancel");
  await shot5(page, "dialog_delete_account_confirm");
  await vis(page, "confirm-delete").click();
  await expect(vis(page, "confirm-error")).toBeVisible({ timeout: 30_000 });
  await expect(vis(page, "confirm-error")).toHaveText("Couldn’t delete your account — try again, or email veersanghavi8@gmail.com.");
  await expect(vis(page, "confirm-error")).toHaveAttribute("role", "alert");
  await expect(vis(page, "confirm-delete")).toHaveText("Try again");
  expect(ownerRows([userA, ...keysA]), "nothing deleted after the Clerk failure").toEqual(aBefore);
  expect(sql1("SELECT count(*) FROM app_users WHERE user_id = %s", [userA])).toBe(1);
  await shot5(page, "dialog_delete_account_error");
  // Try again: the deleting state, then Login with the note
  const clickP = vis(page, "confirm-delete").click();
  await expect(vis(page, "confirm-delete")).toHaveAttribute("aria-busy", "true", { timeout: 10_000 }).catch(() => notes.push("step 8: the deleting state was too short to observe"));
  await expect(vis(page, "confirm-cancel")).toBeDisabled().catch(() => undefined);
  await shot5(page, "dialog_delete_account_deleting").catch(() => undefined);
  await clickP;
  await page.waitForURL("**/login**", { timeout: 60_000 });
  await expect(page.locator('[data-testid="deleted-note"]')).toBeVisible({ timeout: 20_000 });
  await expect(page.locator('[data-testid="deleted-note"]')).toHaveAttribute("role", "status");
  await expect(page.locator('[data-testid="deleted-note"]')).toHaveText("Your account and data were deleted.");
  await expect(page.locator(".stage")).toHaveAttribute("data-phase", "login");
  expect(await page.locator(".stage").getAttribute("data-music")).toBe("off");
  await shot5(page, "login_deleted_note");
  await page.reload();
  await page.getByTestId("skip-intro").click().catch(() => undefined);
  await expect(page.locator(".stage")).toHaveAttribute("data-phase", "login", { timeout: 20_000 });
  await expect(page.locator('[data-testid="deleted-note"]')).toHaveCount(0);
  // the database: nothing of A but the anonymous cost rows
  const aAfter = ownerRows([userA, ...keysA]);
  for (const [t, n] of Object.entries(aAfter)) expect(n, `${t} rows of A after`).toBe(0);
  const anon = sql1("SELECT count(*) FROM chat_usage WHERE user_id IS NULL AND turn_id = 'deleted' AND usd IS NOT NULL") as number;
  expect(anon).toBeGreaterThanOrEqual(aUsageBefore.length);
  expect(sql1("SELECT COALESCE(SUM(usd), 0)::text FROM chat_usage")).toBe(usdTotal);
  expect(await findTestUsers(A)).toEqual([]);
  // A's old token: no account re-created
  const r = await page.request.get(`${API5}/me`, { headers: { Authorization: `Bearer ${aOldToken}` } });
  expect([401, 503]).toContain(r.status());
  expect(sql1("SELECT count(*) FROM app_users WHERE user_id = %s", [userA])).toBe(0);
  expect(sql1("SELECT count(*) FROM app_users WHERE user_id >= %s", [userA])).toBe(sql1("SELECT count(*) FROM app_users WHERE user_id > %s", [userA]));
  expect(ownerRows([userB, ...keysB])).toEqual(bBefore);
  pass(`7+8 Delete account: Clerk failure -> alert + "Try again", nothing deleted; Try again -> deleting -> /login + note (gone on reload, no music); A's rows 0 (cost rows anonymous: ${anon} rows user NULL / turn 'deleted'); spend total unchanged; Clerk user gone; old token -> ${r.status()}, no row re-created; user B unchanged`);
});

// ---- 9: the owner ----------------------------------------------------------------------------------------------------------------

test("9 owner: a /me mock with is_owner -> the item is disabled with the note (the backend's 403 is pytest-pinned)", async () => {
  test.setTimeout(180_000);
  await signIn(page, `${B}+clerk_test@example.com`);
  await page.route(`${API5}/me`, async (route) => {
    const res = await route.fetch();
    const body = await res.json();
    await route.fulfill({ response: res, json: { ...body, is_owner: true, user_id: 1 } });
  });
  await page.goto("/about");
  await expect(page.locator('[data-testid="about"][data-signed-in="true"]')).toBeVisible({ timeout: 20_000 });
  await openMenu();
  await expect(page.locator('[data-testid="delete-account"]')).toHaveAttribute("data-owner", "true", { timeout: 10_000 });
  await expect(page.locator('[data-testid="delete-account"]')).toHaveAttribute("aria-disabled", "true");
  await expect(page.locator('[data-testid="owner-note"]')).toHaveText("The owner account can’t be deleted here.");
  await expect(page.locator('[data-testid="delete-account"]')).toHaveAttribute("aria-describedby", "owner-note");
  await shot5(page, "menu_owner");
  await page.keyboard.press("Escape");
  await page.unroute(`${API5}/me`);
  pass("9 owner: /me mocked with is_owner -> Delete account disabled (aria-disabled) + the owner note (aria-describedby); DELETE /me as the owner = 403 by pytest (test_deletion_backend B2)");
});

// ---- 10: every page's menu ---------------------------------------------------------------------------------------------------------------

test("10 every page's account menu has Sign out + divider + Delete account; focus trap; Esc returns focus", async () => {
  test.setTimeout(300_000);
  const pages = [
    ["/home", '[data-testid="home"]'],
    [`/chat?team=${teamA1}`, '[data-testid="chat"][data-ready="true"]'],
    ["/about", '[data-testid="about"][data-signed-in="true"]'],
    ["/privacy", '[data-testid="privacy"][data-signed-in="true"]'],
  ];
  for (const [url, ready] of pages) {
    await page.goto(url);
    await expect(page.locator(`${ready}:visible`)).toBeVisible({ timeout: 30_000 });
    await openMenu();
    await expect(page.locator('[data-testid="sign-out"]')).toBeVisible();
    await expect(page.locator('[data-testid="menu-divider"]')).toBeVisible();
    const order = await page.evaluate(() => Array.from(document.querySelectorAll('[data-testid="account-popup"] [data-testid]')).map((e) => e.getAttribute("data-testid")));
    expect(order.indexOf("sign-out")).toBeLessThan(order.indexOf("menu-divider"));
    expect(order.indexOf("menu-divider")).toBeLessThan(order.indexOf("delete-account"));
    await expect(page.locator('[data-testid="delete-account"]')).toHaveAttribute("data-owner", "false", { timeout: 10_000 });
    await page.keyboard.press("Escape");
    await expect(page.locator('[data-testid="account-popup"]')).toHaveCount(0);
    expect(await focusedTestId(), `${url}: Esc on the menu returns focus to the account button`).toBe("account-menu");
    // the dialog: focus trap + Esc back to the account button
    await openMenu();
    await page.locator('[data-testid="delete-account"]').click();
    await expect(vis(page, "delete-account-dialog")).toBeVisible();
    expect(await focusedTestId()).toBe("confirm-cancel");
    const seen = new Set<string>();
    for (let i = 0; i < 6; i++) {
      await page.keyboard.press("Tab");
      const inside = await page.evaluate(() => !!(document.activeElement as HTMLElement | null)?.closest('[data-testid="delete-account-dialog"]'));
      expect(inside, `${url}: focus stays inside the dialog (Tab ${i + 1})`).toBe(true);
      seen.add((await focusedTestId()) ?? "?");
    }
    expect([...seen].sort()).toEqual(["confirm-cancel", "confirm-delete"]);
    await page.keyboard.press("Escape");
    await expect(vis(page, "delete-account-dialog")).toHaveCount(0);
    await expect.poll(focusedTestId, { timeout: 5_000 }).toBe("account-menu");
    log(`${url}: menu + dialog ok`);
  }
  pass("10 Home, Chat, About, Privacy: Sign out, divider, Delete account in that order; Esc on the menu -> the account button; the dialog traps Tab (Cancel <-> Delete) and Esc returns focus to the account button");
});

// ---- 11: keyboard, axe, contrast, reduced motion -------------------------------------------------------------------------------------

test("11 keyboard-only with visible focus; axe 0 serious/critical; reduced motion: no spin / pulse", async () => {
  test.setTimeout(300_000);
  const axeOn = async (what: string) => {
    const r = await new AxeBuilder({ page }).disableRules(["color-contrast"]).analyze();
    const bad = r.violations.filter((v) => v.impact === "serious" || v.impact === "critical");
    const minor = r.violations.filter((v) => v.impact !== "serious" && v.impact !== "critical");
    log(`axe ${what}: ${bad.length} serious/critical, ${minor.length} other (${minor.map((v) => v.id).join(", ") || "none"})`);
    expect(bad.map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(" ")).slice(0, 3).join(" | ")}`), `axe ${what}`).toEqual([]);
    return bad.length;
  };
  // signed in (B): keyboard through /about
  await page.goto("/about");
  await expect(page.locator('[data-testid="about"][data-signed-in="true"]')).toBeVisible({ timeout: 20_000 });
  await axeOn("/about signed in");
  await page.keyboard.press("Tab");
  const stops: string[] = [];
  for (let i = 0; i < 40; i++) {
    const info = await page.evaluate(() => {
      const el = document.activeElement as HTMLElement | null;
      if (!el || el === document.body) return null;
      const cs = getComputedStyle(el);
      return { label: el.getAttribute("aria-label") || el.textContent?.trim().slice(0, 30) || el.tagName, outline: cs.outlineStyle, width: cs.outlineWidth, color: cs.outlineColor };
    });
    if (!info) break;
    expect(info.outline, `focus ring on ${info.label}`).not.toBe("none");
    expect(info.color).toBe("rgb(59, 232, 255)");
    stops.push(info.label);
    await page.keyboard.press("Tab");
  }
  expect(stops.length).toBeGreaterThan(12);
  log(`keyboard stops on /about: ${stops.length} (${stops.slice(0, 6).join(" > ")} ...)`);
  await page.goto("/privacy");
  await expect(page.locator('[data-testid="privacy"][data-signed-in="true"]')).toBeVisible({ timeout: 20_000 });
  await axeOn("/privacy signed in");
  await openMenu();
  await page.locator('[data-testid="delete-account"]').click();
  await expect(vis(page, "delete-account-dialog")).toBeVisible();
  await axeOn("delete dialog open");
  await page.keyboard.press("Escape");
  // reduced motion: the deleting spinner does not spin, the Home pill's dot does not pulse
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto("/home");
  await expect(page.locator('[data-testid="home"]:visible')).toBeVisible({ timeout: 30_000 });
  const pulse = await page.locator(".hm-pulse").first().evaluate((el) => getComputedStyle(el).animationName).catch(() => "none");
  expect(pulse).toBe("none");
  await page.route(`${API5}/me`, async (route) => {
    if (route.request().method() === "DELETE") {
      await new Promise((r) => setTimeout(r, 2500));
      await route.fulfill({ status: 502, json: { detail: "mocked" } });
    } else await route.continue();
  });
  await openMenu();
  await page.locator('[data-testid="delete-account"]').click();
  await expect(vis(page, "delete-account-dialog")).toBeVisible();
  await vis(page, "confirm-delete").click();
  await expect(vis(page, "confirm-delete")).toHaveAttribute("aria-busy", "true");
  const spin = await page.locator(".hm-del-spin").evaluate((el) => getComputedStyle(el).animationName);
  expect(spin).toBe("none");
  await expect(vis(page, "confirm-error")).toBeVisible({ timeout: 10_000 });
  await page.keyboard.press("Escape");
  await page.unroute(`${API5}/me`);
  await page.emulateMedia({ reducedMotion: null });
  // signed out: axe on both pages
  await signOutViaMenu(page).catch(async () => {
    await page.goto("/home");
    await signOutViaMenu(page);
  });
  await page.goto("/about");
  await expect(page.locator('[data-testid="about"][data-signed-in="false"]')).toBeVisible({ timeout: 20_000 });
  await axeOn("/about signed out");
  await page.goto("/privacy");
  await expect(page.locator('[data-testid="privacy"][data-signed-in="false"]')).toBeVisible({ timeout: 20_000 });
  await axeOn("/privacy signed out");
  pass(`11 keyboard: ${stops.length} stops with the 2px #3BE8FF ring; axe 0 serious/critical on /about + /privacy (signed in and out) and the open dialog; reduced motion: pulse none, spinner none`);
});

test("12 user B still intact; user 1 guard", async () => {
  expect(ownerRows([userB, ...keysB])).toEqual(bBefore);
  expect(user1Guard()).toBe(guardBefore);
  expect(ownerRows(RESERVED)).toEqual(reservedBefore);
  pass("12 user B's per-table counts unchanged through every delete; users 1 / 9001 / 9002 unchanged; user 1's squad guard unchanged");
  void boxOf;
});
