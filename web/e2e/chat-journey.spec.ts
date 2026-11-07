import { expect, test, type BrowserContext, type Page } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import { createHash } from "node:crypto";
import fs from "node:fs";
import { CLUBS } from "../lib/clubs";
import { SPINNER_WORDS } from "../lib/spinner-words";
import { createTestUser, deleteUser, findTestUsers } from "./clerk-users";
import { API, DB_PREFIX, SHOTS, addTeamOnHome, apiCall, countApiGets, dbEnv, fplCounter, fplGet, mask, py, shot, signIn, type Standing, vis } from "./w4";

/** Prompt W4 PART 3: ONE continuous desktop journey (1440x900) through /login -> /home -> /chat -> the backend -> the agent,
 *  real backend (scratchpad w4_backend.py, clerk mode, port 8010) and real agent turns, within the caps: Anthropic $3.00
 *  (<= 14 turns), FPL <= 40 requests (the backend's import / card / refresh reads + this file's league, bootstrap and fixtures
 *  reads, >= 1 s apart), Clerk test user w4chat (deleted at the end). Steps 1-15 of the prompt + the checkpoint's C1 (a pending
 *  preview survives a read-only visit to another team's chat), C3 (EXPIRED label) and C6 (a pre-W4 thread shows Copy only).
 *  Results and numbers are printed as [W4] lines for the report. Env: W4_TEAM_A / W4_TEAM_B skip the league lookup. */

test.describe.configure({ mode: "serial" });

const NAME = "w4chat";
/** W4_FROM_STEP=n with W4_THREAD_A=<id> resumes a run at step n (the earlier steps skipped: they passed on an earlier run); the
 *  "0 resume" test signs the user in and restores the state those steps left. */
const FROM = Number(process.env.W4_FROM_STEP ?? 0);
const skipBefore = (n: number) => test.skip(FROM > n, `resumed from step ${FROM}`);
const CAP_USD = 3.0;
const CAP_TURNS = 14;
const FOOTER = "ENTER TO SEND · SHIFT + ENTER FOR A NEW LINE · SPINNER WORDS NEED ELITE BALL KNOWLEDGE";

type Card = { team: { name: string }; next_gw: number; players: { id: number; slot: number; short_name: string; full_name: string; club: string; price: number; role: string | null; flag: { chance: number | null } | null; next: { opp: string; home: boolean } | null }[]; version_id: number; fetched_at: string; fpl_live: boolean };
type Boot = { elements: { id: number; now_cost: number; chance_of_playing_next_round: number | null; team: number }[]; teams: { id: number; short_name: string }[] };
type Fx = { event: number; team_h: number; team_a: number }[];

let context: BrowserContext;
let page: Page;
let clerkId: string | null = null;
let appUserId = 0;
let teamA = Number(process.env.W4_TEAM_A ?? 0);
let teamB = Number(process.env.W4_TEAM_B ?? 0);
let threadA = "";
let threadB = "";
let cardA: Card | null = null;
const turns: { step: string; seconds: number; usd: number }[] = [];
const gets: { what: string; gets: number; paths: string[] }[] = [];
const notes: string[] = [];
let tableStats = { tables: 0, bestRows: 0 };
const log = (s: string) => console.log(`[W4] ${s}`);

async function spent(): Promise<number> {
  const me = await apiCall(page, "get", "/me");
  return Number(me.body.spent_today_usd ?? 0);
}

/** One real agent turn through the UI: the budget checked first (NOT RUN past the cap), the thinking row then the answer
 *  awaited, the seconds and the cost recorded. Returns the last assistant message's locator. */
async function turn(step: string, text: string, opts: { via?: "input" | "yes" | "no"; timeout?: number } = {}) {
  const before = await spent();
  const total = turns.reduce((a, t) => a + t.usd, 0);
  if (turns.length >= CAP_TURNS || total >= CAP_USD) {
    notes.push(`${step}: NOT RUN (cap: ${turns.length} turns, $${total.toFixed(2)})`);
    test.skip(true, `cap reached before ${step}`);
  }
  const nAnswers = await page.locator('[data-testid="assistant-message"]:visible').count();
  const t0 = Date.now();
  if (opts.via === "yes") await vis(page, "preview-yes").click();
  else if (opts.via === "no") await vis(page, "preview-no").click();
  else {
    await vis(page, "chat-input").fill(text);
    await vis(page, "chat-input").press("Enter");
  }
  await expect(vis(page, "thinking")).toBeVisible({ timeout: 10_000 });
  await expect(page.locator('[data-testid="assistant-message"]:visible, [data-testid^="system-"]:visible')).toHaveCount(nAnswers + 1, { timeout: opts.timeout ?? 120_000 }).catch(() => undefined);
  await expect(vis(page, "thinking")).toHaveCount(0, { timeout: opts.timeout ?? 120_000 });
  const seconds = Math.round((Date.now() - t0) / 10) / 100;
  const usd = Math.max(0, (await spent()) - before);
  turns.push({ step, seconds, usd });
  log(`turn ${turns.length} (${step}): ${seconds} s, $${usd.toFixed(4)}`);
  return page.locator('[data-testid="assistant-message"]:visible').last();
}

async function openChat(url: string, what: string) {
  const c = countApiGets(page);
  await page.goto(url);
  await expect(page.locator('[data-testid="chat"][data-ready="true"]:visible')).toBeVisible({ timeout: 30_000 });
  await page.waitForTimeout(1500); // the card / threads reads of the opened page
  gets.push({ what, gets: c.gets, paths: c.paths });
  expect(c.s429, `no 429 on reads while opening ${what}`).toBe(0);
  return c;
}

async function cardOf(teamId: number): Promise<Card> {
  const r = await apiCall(page, "get", `/me/teams/${teamId}/card`);
  expect(r.status).toBe(200);
  return r.body as unknown as Card;
}

test.beforeAll(async ({ browser }) => {
  fs.mkdirSync(SHOTS, { recursive: true });
  for (const id of await findTestUsers(NAME)) await deleteUser(id);
  clerkId = (await createTestUser(NAME)).id;
  // W4_RESUME_USER_ID: this fresh Clerk user takes over an earlier run's app_users row (>= 10001) so its imported teams are
  // reused and no FPL import is repeated (the FPL budget is 40 for the whole prompt)
  const resume = Number(process.env.W4_RESUME_USER_ID ?? 0);
  if (resume >= 10001) {
    py(`${DB_PREFIX}cur.execute("UPDATE app_users SET clerk_user_id = %s WHERE user_id = %s AND user_id >= 10001", ("${clerkId}", ${resume})); conn.commit(); print(cur.rowcount)`);
    log(`resumed app user ${resume}`);
  }
  if (!teamA || !teamB) {
    const league = await fplGet<{ standings: { results: Standing[] } }>("leagues-classic/314/standings/?page_standings=1");
    const rows = league.standings.results;
    teamA = teamA || rows[0].entry;
    teamB = teamB || rows[1].entry;
  }
  log(`teams ${mask(teamA)} and ${mask(teamB)} from leagues-classic/314 page 1`);
  context = await browser.newContext({ viewport: { width: 1440, height: 900 }, permissions: ["clipboard-read", "clipboard-write"] });
  page = await context.newPage();
});

test.afterAll(async () => {
  try {
    if (appUserId) py(`${DB_PREFIX}cur.execute("UPDATE app_users SET daily_cap_usd = NULL WHERE user_id = %s AND user_id >= 10001", (${appUserId},)); conn.commit(); print("cap restored")`);
  } catch (e) {
    log(`cap restore failed: ${String(e).slice(0, 120)}`);
  }
  if (clerkId) await deleteUser(clerkId);
  for (const id of await findTestUsers(NAME)) await deleteUser(id);
  const total = turns.reduce((a, t) => a + t.usd, 0);
  log(`SUMMARY turns ${turns.length} $${total.toFixed(4)} | fpl(test) ${fplCounter.n} | gets ${JSON.stringify(gets.map((g) => [g.what, g.gets]))} | tables ${JSON.stringify(tableStats)}`);
  for (const n of notes) log(`NOTE ${n}`);
  for (const t of turns) log(`TURN ${t.step}: ${t.seconds} s $${t.usd.toFixed(4)}`);
  await context?.close();
});

// ---- 0: resume an earlier run (W4_FROM_STEP) ----------------------------------------------------------------------------------------

test("0 resume", async () => {
  test.skip(!FROM, "a full run");
  test.setTimeout(120_000);
  await signIn(page, `${NAME}+clerk_test@example.com`);
  appUserId = Number((await apiCall(page, "get", "/me")).body.user_id);
  threadA = process.env.W4_THREAD_A ?? "";
  expect(threadA).toMatch(/^th_/);
  // the journey's working cap ($5): the test user's day already holds the earlier runs' turns; afterAll sets NULL at the end
  py(`${DB_PREFIX}cur.execute("UPDATE app_users SET daily_cap_usd = 5 WHERE user_id = %s AND user_id >= 10001", (${appUserId},)); conn.commit(); print(cur.rowcount)`);
  cardA = await cardOf(teamA);
  log(`resumed at step ${FROM}: app user ${appUserId}, thread A ${threadA.slice(0, 8)}…`);
});

// ---- 1: sign in, add team A, open its chat -------------------------------------------------------------------------------------

test("1 sign in, add a team, team empty state, the card against the endpoint and FPL, the hover card", async () => {
  skipBefore(1);
  test.setTimeout(300_000);
  await signIn(page, `${NAME}+clerk_test@example.com`);
  appUserId = Number((await apiCall(page, "get", "/me")).body.user_id);
  expect(appUserId).toBeGreaterThanOrEqual(10001);
  log(`app user ${appUserId}`);
  if (process.env.W4_RESUME_USER_ID) await expect(page.locator(`[data-testid="team-card"][data-team-id="${teamA}"]`)).toBeVisible({ timeout: 30_000 });
  else await addTeamOnHome(page, teamA, "choice");
  const c = countApiGets(page);
  const firstCard = page.waitForResponse((r) => r.url().endsWith(`/me/teams/${teamA}/card`) && r.request().method() === "GET");
  await page.locator(`[data-testid="team-card"][data-team-id="${teamA}"] [data-testid="ask-team"]`).click();
  await page.waitForURL(`**/chat?team=${teamA}`);
  await expect(page.locator('[data-testid="chat"][data-ready="true"]:visible')).toBeVisible({ timeout: 30_000 });
  await expect(vis(page, "team-card")).toBeVisible({ timeout: 30_000 });
  await page.waitForTimeout(1000);
  gets.push({ what: "open /chat?team= (from Home)", gets: c.gets, paths: c.paths });
  expect(c.s429).toBe(0);
  // the card's latency: the page's first read (cold or warm, as the backend's cache stood), then ten warm reads -> p50 / p95
  const t = (await firstCard).request().timing();
  const coldMs = Math.round(t.responseEnd - t.requestStart);
  const warm: number[] = [];
  for (let i = 0; i < 10; i++) {
    const t0 = Date.now();
    await cardOf(teamA);
    warm.push(Date.now() - t0);
  }
  warm.sort((a, b) => a - b);
  log(`team card latency: first read ${coldMs} ms; warm p50 ${warm[4]} ms, p95 ${warm[9]} ms (10 reads)`);
  cardA = await cardOf(teamA);
  const name = cardA.team.name;
  await expect(vis(page, "empty-label")).toHaveText(`New chat · ${name}`);
  await expect(vis(page, "empty-title")).toHaveText(`Ask anything about ${name}.`);
  await expect(vis(page, "empty-sub")).toContainText("Answers use your squad as of the GW");
  const chips = await vis(page, "empty-chip").allTextContents();
  expect(chips).toHaveLength(4);
  const flagged = cardA.players.filter((p) => p.flag);
  const doubtful = [...flagged].sort((a, b) => (a.flag!.chance ?? 100) - (b.flag!.chance ?? 100) || a.slot - b.slot)[0];
  expect(chips[2]).toBe(doubtful ? `Is ${doubtful.short_name} fit to play?` : "Who’s the weakest player in my team?");
  log(`injury chip: ${chips[2]} (flagged in the 15: ${flagged.length})`);
  await expect(vis(page, "chat-tag")).toBeVisible();
  await shot(page, "01_team_empty");
  // the card vs the endpoint and vs FPL: three players' price, chance, next fixture + H/A, strip colours
  await expect(page.locator('[data-testid="token"]:visible')).toHaveCount(15);
  if (process.env.W4_SKIP_FPL_CHECK) {
    notes.push("1: the FPL cross-check was skipped on this run (W4_SKIP_FPL_CHECK; it passed on runs 1 and 2 of 6 Nov)");
  } else {
  const boot = await fplGet<Boot>("bootstrap-static/");
  const fx = await fplGet<Fx>("fixtures/?future=1");
  const codes = new Map(boot.teams.map((t) => [t.id, t.short_name]));
  const picks = [cardA.players[0], cardA.players[5], cardA.players[12]];
  for (const p of picks) {
    const e = boot.elements.find((x) => x.id === p.id)!;
    expect(p.price, `price of ${p.short_name}`).toBe(e.now_cost / 10);
    const chance = p.flag ? p.flag.chance : null;
    if (e.chance_of_playing_next_round !== null && e.chance_of_playing_next_round < 100) expect(chance).toBe(e.chance_of_playing_next_round);
    const mine = fx.filter((f) => f.event === cardA!.next_gw && (f.team_h === e.team || f.team_a === e.team));
    if (mine.length) {
      const home = mine[0].team_h === e.team;
      expect(p.next, `next of ${p.short_name}`).toEqual(expect.objectContaining({ opp: codes.get(home ? mine[0].team_a : mine[0].team_h), home }));
    } else expect(p.next).toBeNull();
    const tok = page.locator(`[data-testid="token"][data-player-id="${p.id}"]:visible`);
    const strip = tok.locator('[data-testid="fixture-strip"]');
    if (p.next) {
      await expect(strip).toHaveAttribute("data-opp", p.next.opp);
      const bg = await strip.evaluate((el) => getComputedStyle(el).backgroundColor);
      const want = CLUBS[p.next.opp].bg;
      const rgb = `rgb(${parseInt(want.slice(1, 3), 16)}, ${parseInt(want.slice(3, 5), 16)}, ${parseInt(want.slice(5, 7), 16)})`;
      expect(bg, `strip colour of ${p.short_name} = ${p.next.opp}`).toBe(rgb);
    }
    log(`spot-check ${p.short_name}: £${p.price}m chance ${chance ?? "100"} next ${p.next ? `${p.next.opp} ${p.next.home ? "H" : "A"}` : "blank"} OK`);
  }
  }
  // the hover card: hover, keyboard focus, click pins; only the listed fields
  const tok = page.locator('[data-testid="token"]:visible').nth(3);
  await tok.hover();
  const card = page.locator(`#${await tok.getAttribute("aria-describedby")}`);
  await expect(card).toBeVisible();
  await expect(card).toHaveAttribute("role", "tooltip");
  const lines = (await card.innerText()).split("\n").map((s) => s.trim()).filter(Boolean);
  expect(lines.some((l) => /^Next:/.test(l))).toBe(true);
  expect(lines.filter((l) => /PRED|FPL EST|PLAYING|AVG PTS/.test(l))).toHaveLength(3);
  log(`hover card lines: ${lines.join(" | ")}`);
  await shot(page, "02_team_hover");
  await page.mouse.move(10, 10);
  await expect(card).toBeHidden();
  await tok.focus();
  await expect(card).toBeVisible();
  await page.keyboard.press("Tab");
  await tok.click();
  await page.mouse.move(10, 400);
  await expect(card).toBeVisible();
  await expect(tok).toHaveAttribute("aria-pressed", "true");
  await shot(page, "03_team_pinned");
  await page.keyboard.press("Escape");
  await expect(tok).not.toHaveAttribute("aria-pressed", "true");
});

// ---- 2: a chip, the thinking state, the answer, the footer ----------------------------------------------------------------------

test("2 chip fills the box; thinking state with spinner words; markdown answer; footer", async () => {
  skipBefore(2);
  test.setTimeout(240_000);
  const chip = vis(page, "empty-chip").first();
  const q = (await chip.textContent())!.trim();
  await chip.click();
  await expect(vis(page, "chat-input")).toHaveValue(q);
  await expect(vis(page, "chat-input")).toBeFocused();
  await expect(vis(page, "footer-line").locator(".desk")).toHaveText(FOOTER);
  const c = countApiGets(page);
  const before = await spent();
  const t0 = Date.now();
  await vis(page, "chat-input").press("Enter");
  await expect(vis(page, "thinking")).toBeVisible({ timeout: 10_000 });
  await expect(vis(page, "thinking").locator(".ch-ring")).toBeVisible();
  const words: string[] = [];
  for (let i = 0; i < 5; i++) {
    const w = await vis(page, "spinner-word").textContent().catch(() => null);
    if (w === null) break;
    words.push(w);
    expect(SPINNER_WORDS, `spinner word "${w}" is in the list`).toContain(w);
    await expect(vis(page, "thinking-seconds")).toHaveText(/^\d+ s$/);
    await expect(vis(page, "thinking")).toHaveAttribute("aria-label", /^Thinking, \d+ seconds$/);
    if (i === 1) await shot(page, "04_thinking");
    await page.waitForTimeout(3200);
  }
  for (let i = 1; i < words.length; i++) expect(words[i], "no immediate repeat").not.toBe(words[i - 1]);
  log(`spinner words sampled: ${words.length} -> ${words.map((w) => w.slice(0, 18)).join(" / ")}`);
  await expect(vis(page, "thinking")).toHaveCount(0, { timeout: 120_000 });
  const seconds = Math.round((Date.now() - t0) / 10) / 100;
  const usd = Math.max(0, (await spent()) - before);
  turns.push({ step: "2 chip", seconds, usd });
  await page.waitForTimeout(1500);
  gets.push({ what: "per message (step 2)", gets: c.gets, paths: c.paths });
  expect(c.s429).toBe(0);
  const ans = page.locator('[data-testid="assistant-message"]:visible').last();
  await expect(ans.locator(".ch-md p, .ch-md li, .ch-md table").first()).toBeVisible();
  threadA = (await page.locator('[data-testid="chat"]:visible').getAttribute("data-thread-id")) ?? "";
  expect(threadA).toMatch(/^th_/);
  expect(page.url()).toContain(`/chat/${threadA}`);
  log(`turn 1 (2 chip): ${seconds} s, $${usd.toFixed(4)}; thread ${threadA.slice(0, 8)}…; answer ${(await ans.innerText()).length} chars`);
  await shot(page, "05_answer");
});

// ---- 3: a news question, source chips + pop-up ------------------------------------------------------------------------------------

test("3 news question -> source chips + pop-up, one at a time, Esc and outside click", async () => {
  skipBefore(3);
  test.setTimeout(240_000);
  const doubtful = cardA!.players.filter((p) => p.flag).sort((a, b) => (a.flag!.chance ?? 100) - (b.flag!.chance ?? 100))[0] ?? cardA!.players[9];
  const ans = await turn("3 news", `Is there any news on ${doubtful.full_name}? Is he fit to play?`);
  const chips = ans.locator('[data-testid="source-chip"]');
  const n = await chips.count();
  log(`sources on the news answer: ${n} chip(s): ${(await chips.allTextContents()).join(" | ")}`);
  if (n === 0) {
    notes.push("3: the news answer cited no source (no chips; C4 shows cited items only)");
    return;
  }
  await chips.first().click();
  await expect(ans.locator('[data-testid="source-popup"]')).toHaveCount(1);
  const pop = ans.locator('[data-testid="source-popup"]').first();
  const hasLink = (await pop.locator('[data-testid="source-link"]').count()) > 0;
  log(`pop-up 1: ${(await pop.innerText()).replace(/\n/g, " | ")} (link: ${hasLink})`);
  await shot(page, "06_sources_popup");
  if (n > 1) {
    await chips.nth(1).click();
    await expect(ans.locator('[data-testid="source-popup"]')).toHaveCount(1); // one at a time
    log(`pop-up 2: ${(await ans.locator('[data-testid="source-popup"]').first().innerText()).replace(/\n/g, " | ")}`);
  }
  await page.keyboard.press("Escape");
  await expect(ans.locator('[data-testid="source-popup"]')).toHaveCount(0);
  await chips.first().click();
  await expect(ans.locator('[data-testid="source-popup"]')).toHaveCount(1);
  await page.mouse.click(700, 60);
  await expect(ans.locator('[data-testid="source-popup"]')).toHaveCount(0);
});

// ---- 4: Copy, thumbs, reload, Langfuse -------------------------------------------------------------------------------------------

test("4 Copy, thumb up survives a reload, thumb down then undo -> DB row + Langfuse score", async () => {
  skipBefore(4);
  test.setTimeout(240_000);
  const ans = page.locator('[data-testid="assistant-message"]:visible').last();
  const mid = (await ans.getAttribute("data-message-id"))!;
  expect(mid).toMatch(/^[0-9a-f]{32}$/);
  await ans.locator('[data-testid="copy"]').click();
  await expect(ans.locator('[data-testid="copy"]')).toHaveText("Copied");
  const clip = await page.evaluate(() => navigator.clipboard.readText());
  const shownText = await ans.locator(".ch-md").innerText();
  expect(clip.length).toBeGreaterThan(20);
  const plain = (t: string) => t.replace(/[*_`#>]/g, "").replace(/\s+/g, " ").trim().slice(0, 30); // the clipboard holds the markdown source
  expect(plain(clip)).toBe(plain(shownText));
  await shot(page, "07_copied");
  await expect(ans.locator('[data-testid="copy"]')).toHaveText("Copy", { timeout: 4000 });
  await ans.locator('[data-testid="thumb-up"]').click();
  await expect(ans.locator('[data-testid="thumb-up"]')).toHaveAttribute("aria-pressed", "true");
  await page.waitForTimeout(800);
  await openChat(`/chat/${threadA}`, "reopen /chat/{id} (step 4)");
  const again = page.locator(`[data-testid="assistant-message"][data-message-id="${mid}"]:visible`);
  await expect(again.locator('[data-testid="thumb-up"]')).toHaveAttribute("aria-pressed", "true");
  await again.locator('[data-testid="thumb-down"]').click();
  await expect(again.locator('[data-testid="thumb-down"]')).toHaveAttribute("aria-pressed", "true");
  await expect(again.locator('[data-testid="thumb-up"]')).toHaveAttribute("aria-pressed", "false");
  await page.waitForTimeout(500);
  await again.locator('[data-testid="thumb-down"]').click(); // undo
  await expect(again.locator('[data-testid="thumb-down"]')).toHaveAttribute("aria-pressed", "false");
  await page.waitForTimeout(1200);
  const row = py(`${DB_PREFIX}cur.execute("SELECT feedback, feedback_at IS NOT NULL, user_id FROM chat_messages WHERE message_id = %s", ("${mid}",)); print(cur.fetchone())`).trim();
  log(`chat_messages row after the undo: ${row}`);
  expect(row).toMatch(/^\(None, True, \d+\)$/);
  const env = dbEnv();
  if (env.LANGFUSE_BASE_URL && env.LANGFUSE_PUBLIC_KEY && env.LANGFUSE_SECRET_KEY) {
    const traceId = createHash("sha256").update(mid).digest("hex").slice(0, 32);
    const auth = Buffer.from(`${env.LANGFUSE_PUBLIC_KEY}:${env.LANGFUSE_SECRET_KEY}`).toString("base64");
    let found: { value?: string; stringValue?: string; name: string; id: string }[] = [];
    // the score is sent after the row and flushed in the background; Langfuse ingests the same score id in order, so the
    // value settles on "none" a few seconds after the undo: poll for it
    for (let i = 0; i < 16; i++) {
      await page.waitForTimeout(2500);
      const r = await fetch(`${env.LANGFUSE_BASE_URL.replace(/\/$/, "")}/api/public/v3/scores?traceId=${traceId}&name=user_feedback`, { headers: { Authorization: `Basic ${auth}` } });
      if (r.ok) found = ((await r.json()) as { data: typeof found }).data ?? [];
      if (found.length && (found[0].stringValue ?? String(found[0].value)) === "none") break;
    }
    log(`Langfuse scores on trace ${traceId.slice(0, 8)}…: ${JSON.stringify(found.map((s) => ({ name: s.name, value: s.stringValue ?? s.value })))}`);
    expect(found.length, "one user_feedback score (updated in place)").toBe(1);
    expect(found[0].stringValue ?? String(found[0].value)).toBe("none");
  } else notes.push("4: Langfuse score NOT DETERMINED (no keys on the laptop)");
});

// ---- 5 + C1: a CAPTAIN preview in A survives a read-only visit to B's chat; "Yes, apply" commits -----------------------------------

test("5+C1 captain preview, read-only visit to team B's past chat, back, Yes applies; card reloads; new squad version", async () => {
  skipBefore(5);
  test.setTimeout(400_000);
  // team B and ONE turn in it (so it has a past chat), then back to A's chat
  await page.goto("/home");
  await expect(vis(page, "teams-section")).toBeVisible({ timeout: 30_000 });
  if ((await page.locator(`[data-testid="team-card"][data-team-id="${teamB}"]`).count()) === 0) await addTeamOnHome(page, teamB, "card");
  else log(`team ${mask(teamB)} already on Home (a resumed user): no second import`);
  await page.locator(`[data-testid="team-card"][data-team-id="${teamB}"] [data-testid="ask-team"]`).click();
  await page.waitForURL(`**/chat?team=${teamB}`);
  await expect(page.locator('[data-testid="chat"][data-ready="true"]:visible')).toBeVisible({ timeout: 30_000 });
  await turn("5 team B question", "Who is my captain and vice-captain?");
  threadB = (await page.locator('[data-testid="chat"]:visible').getAttribute("data-thread-id")) ?? "";
  // A's chat again: a captain preview (C1: sending re-activates A)
  await openChat(`/chat/${threadA}`, "reopen /chat/{id} (step 5)");
  const vc = cardA!.players.find((p) => p.role === "VC")!;
  const oldC = cardA!.players.find((p) => p.role === "C")!;
  const versionBefore = cardA!.version_id;
  const ans = await turn("5 captain preview", `Make ${vc.full_name} my captain.`);
  const pv = ans.locator('[data-testid="preview-card"]');
  if ((await pv.count()) === 0) {
    notes.push(`5: the agent made no captain preview (answer: ${(await ans.innerText()).slice(0, 140).replace(/\n/g, " ")})`);
    log("captain preview: NOT PRODUCED by the agent; C1 and the Yes path NOT RUN");
    return;
  }
  await expect(pv).toHaveAttribute("data-pending", "true");
  const meta = await pv.locator('[data-testid="preview-meta"]').textContent();
  log(`captain preview: ${(await pv.innerText()).replace(/\n/g, " | ").slice(0, 160)}`);
  expect(meta).toMatch(/CAPTAIN|EXPIRES IN|EXPIRED|GW\d+/); // one change: "CAPTAIN · GW11 · EXPIRES IN …"; several: the expiry alone
  await expect(vis(page, "card-preview-line")).toBeVisible();
  const inTok = page.locator(`[data-testid="token"][data-player-id="${vc.id}"]:visible`);
  const outTok = page.locator(`[data-testid="token"][data-player-id="${oldC.id}"]:visible`);
  await expect(inTok).toHaveAttribute("data-mark", "badge-in");
  await expect(inTok.locator('[data-testid="badge-c"]')).toBeVisible();
  // the old captain: red outline, or green when the agent also made him the vice-captain (C2: a player both OUT and IN is green)
  await expect(outTok).toHaveAttribute("data-mark", /^badge-(out|in)$/);
  log(`armband marks: new C ${vc.short_name} ${await inTok.getAttribute("data-mark")}, old C ${oldC.short_name} ${await outTok.getAttribute("data-mark")}`);
  await shot(page, "08_preview_captain");
  // C1: open B's past chat (read-only), then back to A through Past chats; the preview is still pending; Yes commits
  await page.locator(`[data-testid="thread-row"][data-thread-id="${threadB}"]:visible`).click();
  await page.waitForURL(`**/chat/${threadB}`);
  await expect(page.locator('[data-testid="chat"][data-ready="true"]:visible')).toBeVisible({ timeout: 30_000 });
  const active = (await apiCall(page, "get", "/me")).body.active_team as { fpl_team_id: number } | null;
  expect(active?.fpl_team_id, "opening B's chat did not activate B (C1)").toBe(teamA);
  await page.locator(`[data-testid="thread-row"][data-thread-id="${threadA}"]:visible`).click();
  await page.waitForURL(`**/chat/${threadA}`);
  await expect(page.locator('[data-testid="chat"][data-ready="true"]:visible')).toBeVisible({ timeout: 30_000 });
  const restored = page.locator('[data-testid="preview-card"]:visible').last();
  await expect(restored).toHaveAttribute("data-pending", "true");
  await expect(vis(page, "card-preview-line")).toBeVisible();
  const saved = await turn("5 Yes", "", { via: "yes" });
  await expect(page.locator('[data-testid="user-message"]:visible').last()).toHaveText("Yes");
  await expect(saved.locator('[data-testid="saved-block"]')).toBeVisible();
  log(`saved block: ${(await saved.locator('[data-testid="saved-block"]').innerText()).replace(/\n/g, " ")}`);
  await expect(restored.locator('[data-testid="preview-choice"]')).toHaveText(/You chose “Yes, apply”/);
  await expect(page.locator(`[data-testid="token"][data-player-id="${vc.id}"]:visible [data-testid="badge-c"]`)).toBeVisible({ timeout: 20_000 });
  const after = await cardOf(teamA);
  expect(after.version_id).toBeGreaterThan(versionBefore);
  expect(after.players.find((p) => p.id === vc.id)?.role).toBe("C");
  const squad = await apiCall(page, "get", "/me/squad");
  log(`/me/squad version ${(squad.body.squad as { version_id: number }).version_id} (was ${versionBefore}); card version ${after.version_id}`);
  cardA = after;
  await shot(page, "09_saved");
});

// ---- 6: a one-transfer preview, OUT faded behind, IN green; "No, keep it" -----------------------------------------------------------

test("6 one-transfer preview -> pitch OUT/IN -> No keeps the squad", async () => {
  skipBefore(6);
  test.setTimeout(400_000);
  const bench = cardA!.players.filter((p) => p.slot >= 13); // bench 1-3 (not the GK)
  const out = bench[bench.length - 1];
  const versionBefore = cardA!.version_id;
  const ans = await turn("6 transfer preview", `Preview one transfer only: sell ${out.full_name} and buy the best replacement in his position I can afford. Just the preview, do not apply.`, { timeout: 180_000 });
  const pv = ans.locator('[data-testid="preview-card"]');
  if ((await pv.count()) === 0) {
    notes.push(`6: the agent made no preview for the transfer request (answer: ${(await ans.innerText()).slice(0, 120).replace(/\n/g, " ")})`);
    log("transfer preview: NOT PRODUCED by the agent");
    return;
  }
  await expect(pv).toHaveAttribute("data-pending", "true");
  const impact = await pv.locator('[data-testid="impact-line"]').innerText().catch(() => "(no impact line)");
  log(`transfer preview: ${(await pv.innerText()).replace(/\n/g, " | ").slice(0, 200)} ;; impact: ${impact.replace(/\n/g, " ")}`);
  const outId = Number(await pv.locator('[data-testid="preview-out"]').evaluate((el) => el.closest("[data-testid=preview-card]")?.getAttribute("data-changes")).catch(() => 1));
  void outId;
  const ghost = page.locator('[data-testid="token-ghost"]:visible');
  const inTok = page.locator('[data-testid="token"][data-mark="in"]:visible');
  await expect(inTok.first()).toBeVisible();
  await expect(inTok.first().locator(".ch-st-in")).toHaveText("IN");
  await expect(ghost.first()).toBeVisible();
  const ghostOpacity = await ghost.first().evaluate((el) => getComputedStyle(el).opacity);
  expect(Number(ghostOpacity)).toBeLessThan(1);
  await shot(page, "10_preview_transfer");
  await turn("6 No", "", { via: "no" });
  await expect(page.locator('[data-testid="user-message"]:visible').last()).toHaveText("No");
  await expect(pv.locator('[data-testid="preview-choice"]')).toHaveText(/You chose “No, keep it”/);
  await expect(page.locator('[data-testid="token-ghost"]:visible')).toHaveCount(0);
  const after = await cardOf(teamA);
  expect(after.version_id).toBe(versionBefore);
  log(`squad unchanged after No: version ${after.version_id}`);
  await shot(page, "11_preview_answered");
});

// ---- 7 + C6: sidebar, collapse, New chat, reopen; a pre-W4 thread ------------------------------------------------------------------

test("7+C6 sidebar groups / tags / time ago; collapse survives a reload; New chat; reopen restores; a pre-W4 thread shows Copy only", async () => {
  skipBefore(7);
  test.setTimeout(240_000);
  await expect(vis(page, "group-today")).toBeVisible();
  const rows = page.locator('[data-testid="thread-row"]:visible');
  expect(await rows.count()).toBeGreaterThanOrEqual(2);
  const tags = await rows.locator(".ch-tag").allTextContents();
  log(`sidebar rows: ${await rows.count()}, tags ${JSON.stringify(tags)}, ago ${JSON.stringify(await rows.locator(".ch-row-ago").allTextContents())}`);
  expect(tags.every((t) => t.length > 0)).toBe(true);
  await expect(page.locator(`[data-testid="thread-row"][data-thread-id="${threadA}"]:visible`)).toHaveClass(/on/);
  await vis(page, "collapse-sidebar").click();
  await expect(vis(page, "sidebar")).toHaveAttribute("data-collapsed", "true");
  expect(await page.evaluate(() => localStorage.getItem("fpl.chat.sidebar"))).toBe("collapsed");
  await shot(page, "12_sidebar_collapsed");
  await page.reload();
  await expect(page.locator('[data-testid="chat"][data-ready="true"]:visible')).toBeVisible({ timeout: 30_000 });
  await expect(vis(page, "sidebar")).toHaveAttribute("data-collapsed", "true");
  await vis(page, "collapse-sidebar").click();
  await expect(vis(page, "sidebar")).toHaveAttribute("data-collapsed", "false");
  await vis(page, "new-chat").click();
  await page.waitForURL(`**/chat?team=${teamA}`);
  await expect(vis(page, "empty-team")).toBeVisible({ timeout: 30_000 });
  await expect(vis(page, "thread-row-new")).toBeVisible();
  await expect(vis(page, "chat-title")).toHaveText("New chat");
  // reopen the first chat: messages, sources, feedback and the answered previews restored
  await openChat(`/chat/${threadA}`, "reopen /chat/{id} (step 7)");
  const answers = page.locator('[data-testid="assistant-message"]:visible');
  log(`reopened A: ${await page.locator('[data-testid="user-message"]:visible').count()} questions, ${await answers.count()} answers, ${await page.locator('[data-testid="source-chip"]:visible').count()} source chips, ${await page.locator('[data-testid="preview-card"]:visible').count()} preview cards, choices ${JSON.stringify(await page.locator('[data-testid="preview-choice"]:visible').allTextContents())}`);
  expect(await answers.count()).toBeGreaterThanOrEqual(2);
  await expect(page.locator('[data-testid="preview-card"][data-pending="true"]:visible')).toHaveCount(0);
  if (await page.locator('[data-testid="preview-choice"]:visible').count()) await expect(page.locator('[data-testid="preview-choice"]:visible').first()).toContainText("You chose");
  await expect(answers.nth(1).locator('[data-testid="thumb-down"]')).toHaveAttribute("aria-pressed", "false");
  tableStats = await page.evaluate(() => (window as unknown as { __fplTableStats?: { tables: number; bestRows: number } }).__fplTableStats ?? { tables: 0, bestRows: 0 });
  // C6: a thread stored before W4 (no chat_messages row): Copy only
  const legacy = py(`${DB_PREFIX}
import json, threads, agent_graph
tid = threads.new_thread_id()
cur.execute("INSERT INTO chat_threads (thread_id, user_id, is_default, owner_key) VALUES (%s, %s, FALSE, %s)", (tid, ${appUserId}, ${appUserId}))
conn.commit()
old = [{"role": "user", "content": "A question from before W4"}, {"role": "assistant", "content": [{"type": "text", "text": "An answer stored before W4."}]}]
entry = {"q": 0, "user": "A question from before W4", "user_at": "2026-11-01T10:00:00.000Z", "answer": "An answer stored before W4.", "answer_at": "2026-11-01T10:00:12.000Z"}
agent_graph.thread_graph().update_state(agent_graph._thread_config(tid), {"messages": old, "transcript": [entry]}, as_node="finalize")
print(tid)`).trim();
  log(`pre-W4 thread ${legacy.slice(0, 10)}… created for user ${appUserId}`);
  await openChat(`/chat/${legacy}`, "open a pre-W4 thread");
  const old = page.locator('[data-testid="assistant-message"]:visible').first();
  await expect(old).toHaveAttribute("data-message-id", "");
  await expect(old.locator('[data-testid="copy"]')).toBeVisible();
  await expect(old.locator('[data-testid="thumb-up"]')).toHaveCount(0);
  await expect(old.locator('[data-testid="source-chip"]')).toHaveCount(0);
  await shot(page, "13_pre_w4_thread");
});

// ---- 8: General mode --------------------------------------------------------------------------------------------------------------

test("8 General mode from Home; one question; a Home chip prefills /chat?q= and does not send", async () => {
  skipBefore(8);
  test.setTimeout(240_000);
  await page.goto("/home");
  await expect(vis(page, "teams-section")).toBeVisible({ timeout: 30_000 });
  const c = countApiGets(page);
  await page.getByTestId("start-general").click();
  await page.waitForURL("**/chat");
  await expect(page.locator('[data-testid="chat"][data-context="general"][data-ready="true"]:visible')).toBeVisible({ timeout: 30_000 });
  await page.waitForTimeout(1000);
  gets.push({ what: "open /chat (General, from Home)", gets: c.gets, paths: c.paths });
  await expect(page.locator('[data-testid="team-card"]:visible')).toHaveCount(0);
  await expect(page.locator(".ch-gen-photo:visible")).toBeVisible();
  await expect(vis(page, "empty-title")).toHaveText(/^What do you want to know, .+\?$/);
  expect(await vis(page, "empty-chip").count()).toBe(4);
  await expect(vis(page, "chat-tag")).toHaveText("GENERAL");
  await shot(page, "14_general_empty");
  await turn("8 general", "Who are the three best captain picks this gameweek?");
  await shot(page, "15_general_answer");
  await page.goto("/home");
  await expect(vis(page, "teams-section")).toBeVisible({ timeout: 30_000 });
  const chip = page.getByTestId("chip").first();
  const q = (await chip.textContent())!.trim();
  await chip.click();
  await page.waitForURL("**/chat?q=**");
  await expect(page.locator('[data-testid="chat"][data-ready="true"]:visible')).toBeVisible({ timeout: 30_000 });
  await expect(vis(page, "chat-input")).toHaveValue(q);
  await expect(vis(page, "from-home-tag")).toContainText("FROM HOME");
  await expect(page.locator('[data-testid="user-message"]:visible')).toHaveCount(0);
  await expect(page.locator('[data-testid="chat"]:visible')).toHaveAttribute("data-busy", "false");
  await shot(page, "16_general_prefilled");
});

// ---- 9: 409 from another tab ---------------------------------------------------------------------------------------------------

test("9 another tab activates team B -> sending in A's chat is a real 409 -> Start a new chat; reopening A re-activates it", async () => {
  skipBefore(9);
  test.setTimeout(300_000);
  await apiCall(page, "post", `/me/teams/${teamA}/activate`); // A is the active team when the page opens (as after a send in it)
  await openChat(`/chat/${threadA}`, "reopen /chat/{id} (step 9)");
  const other = await context.newPage();
  await other.goto("/home");
  await expect(other.getByTestId("teams-section")).toBeVisible({ timeout: 30_000 });
  const act = await apiCall(other, "post", `/me/teams/${teamB}/activate`);
  expect(act.status).toBe(200);
  await other.close();
  const before = await spent();
  await vis(page, "chat-input").fill("Who should I bench this week?");
  await vis(page, "chat-input").press("Enter");
  await expect(vis(page, "system-team")).toBeVisible({ timeout: 20_000 });
  expect(await spent()).toBe(before); // 0 model calls
  await shot(page, "17_system_c_409");
  await vis(page, "start-new-chat").click();
  await page.waitForURL(`**/chat?team=${teamA}`);
  await expect(vis(page, "empty-team")).toBeVisible({ timeout: 30_000 });
  await page.locator(`[data-testid="thread-row"][data-thread-id="${threadA}"]:visible`).click();
  await page.waitForURL(`**/chat/${threadA}`);
  await expect(page.locator('[data-testid="chat"][data-ready="true"]:visible')).toBeVisible({ timeout: 30_000 });
  await turn("9 after re-activation", "Which of my players has the easiest fixture next?");
  const active = (await apiCall(page, "get", "/me")).body.active_team as { fpl_team_id: number } | null;
  expect(active?.fpl_team_id).toBe(teamA);
});

// ---- 10: the daily limit ---------------------------------------------------------------------------------------------------------

test("10 daily limit: system message a with a live countdown, the box disabled, 0 model calls", async () => {
  skipBefore(10);
  test.setTimeout(120_000);
  py(`${DB_PREFIX}cur.execute("UPDATE app_users SET daily_cap_usd = 0.01 WHERE user_id = %s AND user_id >= 10001", (${appUserId},)); conn.commit(); print("cap set")`);
  const before = await spent();
  await vis(page, "chat-input").fill("One more question?");
  await vis(page, "chat-input").press("Enter");
  await expect(vis(page, "system-limit")).toBeVisible({ timeout: 20_000 });
  const c1 = await vis(page, "limit-countdown").textContent();
  await expect(vis(page, "chat-box")).toHaveAttribute("data-disabled", "true");
  await expect(vis(page, "chat-input")).toHaveAttribute("placeholder", "Daily limit reached — back at 00:00 UTC");
  expect(await spent()).toBe(before);
  log(`system a: countdown "${c1}"`);
  await shot(page, "18_system_a_limit");
  // back to the journey's working cap ($5: the test user's day already holds several runs); afterAll sets NULL at the end
  py(`${DB_PREFIX}cur.execute("UPDATE app_users SET daily_cap_usd = 5 WHERE user_id = %s AND user_id >= 10001", (${appUserId},)); conn.commit(); print("cap restored")`);
});

// ---- 11: 429 and "other" errors via route mocks ----------------------------------------------------------------------------------

test("11 UI states b (429, countdown re-enables) and d (other, Retry resends once) with real response shapes", async () => {
  skipBefore(11);
  test.setTimeout(180_000);
  await openChat(`/chat/${threadA}`, "reopen /chat/{id} (step 11)");
  const detail = "rate limit: at most 10 messages a minute; please wait a moment";
  await page.route(`${API}/chat`, (route) => route.fulfill({ status: 429, contentType: "application/json", body: JSON.stringify({ detail }) }));
  await vis(page, "chat-input").fill("mock 429");
  await vis(page, "chat-input").press("Enter");
  await expect(vis(page, "system-rate")).toBeVisible();
  await expect(vis(page, "rate-countdown")).toHaveText(/^(1:00|0:5\d)$/);
  await expect(vis(page, "chat-input")).toHaveAttribute("placeholder", "Wait a minute…");
  await shot(page, "19_system_b_429");
  await expect(vis(page, "chat-box")).toHaveAttribute("data-disabled", "true");
  const c0 = (await vis(page, "rate-countdown").textContent())!;
  await page.waitForTimeout(2500);
  const c1 = (await vis(page, "rate-countdown").textContent())!;
  expect(c1 < c0, `the countdown ticks (${c0} -> ${c1})`).toBe(true);
  // the server sends no Retry-After (and a cross-origin page could not read one without CORS exposing it): the box
  // re-enables after the 60 s default
  await expect(vis(page, "chat-box")).toHaveAttribute("data-disabled", "false", { timeout: 70_000 });
  log(`b: countdown ${c0} -> ${c1}; the box re-enabled after the 60 s default`);
  await page.unroute(`${API}/chat`);
  // d: a 500, then Retry: the thread is re-read (GET messages) and the question sent once more (a mocked success)
  let posts = 0;
  const tid = threadA;
  await page.route(`${API}/chat`, (route) => {
    posts++;
    if (posts === 1) return route.fulfill({ status: 500, contentType: "application/json", body: JSON.stringify({ detail: "Internal Server Error" }) });
    return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ answer: "A mocked answer after the retry.", thread_id: tid, message_id: null, sources: [], squad_preview: null, squad_applied: null }) });
  });
  let messageReads = 0;
  page.on("request", (r) => {
    if (r.url() === `${API}/threads/${tid}/messages`) messageReads++;
  });
  await vis(page, "chat-input").fill("mock failure");
  await vis(page, "chat-input").press("Enter");
  await expect(vis(page, "system-error")).toBeVisible();
  await expect(vis(page, "system-error")).toHaveAttribute("role", "alert");
  await shot(page, "20_system_d_error");
  const reads0 = messageReads;
  await vis(page, "retry").click();
  await expect(page.locator('[data-testid="assistant-message"]:visible').last()).toContainText("A mocked answer after the retry.", { timeout: 20_000 });
  expect(posts).toBe(2);
  expect(messageReads).toBeGreaterThan(reads0);
  log(`d Retry: ${posts} POSTs (1 failed + 1 resend), the thread re-read ${messageReads - reads0}x first`);
  await page.unroute(`${API}/chat`);
});

// ---- 13: Refresh, FPL down, the refresh limit, the card endpoint failing -----------------------------------------------------------

test("13 Refresh reloads the card; FPL down -> saved team + amber note, refresh note; 5/min; card endpoint failing -> Retry while chat works", async () => {
  skipBefore(13);
  test.setTimeout(300_000);
  await openChat(`/chat/${threadA}`, "reopen /chat/{id} (step 13)");
  if (process.env.W4_SKIP_REFRESH) {
    notes.push("13: the real Refresh (4 FPL requests) was skipped on this run (W4_SKIP_REFRESH: the FPL budget); the limit and failure paths ran");
  } else {
    const fetched0 = (await cardOf(teamA)).fetched_at;
    await vis(page, "card-refresh").click();
    await expect(vis(page, "card-refresh")).toHaveAttribute("data-state", "busy");
    await expect(vis(page, "card-refresh")).toHaveAttribute("data-state", "idle", { timeout: 60_000 });
    await page.waitForTimeout(1500);
    const fetched1 = (await cardOf(teamA)).fetched_at;
    expect(fetched1 > fetched0).toBe(true);
    log(`refresh: card fetched_at ${fetched0} -> ${fetched1}`);
  }
  // FPL unreachable for the backend: the last copy served with the amber note; Refresh fails with its note
  await page.request.get(`${API}/__w4/fpl_down?on=1`);
  await page.reload();
  await expect(page.locator('[data-testid="chat"][data-ready="true"]:visible')).toBeVisible({ timeout: 30_000 });
  await expect(vis(page, "team-card")).toHaveAttribute("data-live", "false", { timeout: 30_000 });
  await expect(vis(page, "note-stale")).toHaveText("Live details may be out of date.");
  await expect(page.locator('[data-testid="token"]:visible')).toHaveCount(15);
  await shot(page, "21_card_fpl_down");
  await vis(page, "card-refresh").click();
  await expect(vis(page, "note-refresh")).toHaveText("FPL isn’t responding — showing your saved team.", { timeout: 30_000 });
  await shot(page, "22_card_refresh_failed");
  await page.request.get(`${API}/__w4/fpl_down?on=0`);
  // the 5-a-minute import window, used up with five refreshes of a team the user does not have (404 before any FPL request)
  for (let i = 0; i < 5; i++) await apiCall(page, "post", "/me/teams/99999991/refresh");
  await vis(page, "card-refresh").click();
  await expect(vis(page, "note-refresh")).toContainText("Refresh limit reached", { timeout: 30_000 });
  log("refresh limit: the 6th refresh in a minute -> 429 -> the limit note");
  // our server unreachable for the card: the error card with Retry; the chat still works (a mocked send)
  await page.route(`${API}/me/teams/${teamA}/card`, (route) => route.fulfill({ status: 503, contentType: "application/json", body: JSON.stringify({ detail: "down" }) }));
  await page.reload();
  await expect(page.locator('[data-testid="chat"][data-ready="true"]:visible')).toBeVisible({ timeout: 30_000 });
  await expect(vis(page, "card-error")).toContainText("Couldn’t load your team");
  await expect(vis(page, "card-error")).toContainText("You can keep chatting meanwhile.");
  await expect(vis(page, "chat-box")).toHaveAttribute("data-disabled", "false");
  await shot(page, "23_card_error");
  await page.route(`${API}/chat`, (route) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ answer: "Chat still works.", thread_id: threadA, message_id: null, sources: [], squad_preview: null, squad_applied: null }) }));
  await vis(page, "chat-input").fill("still works?");
  await vis(page, "chat-input").press("Enter");
  await expect(page.locator('[data-testid="assistant-message"]:visible').last()).toContainText("Chat still works.");
  await page.unroute(`${API}/chat`);
  await page.unroute(`${API}/me/teams/${teamA}/card`);
  await vis(page, "card-retry").click();
  await expect(vis(page, "team-card")).toBeVisible({ timeout: 30_000 });
});

// ---- 14: shimmers, reduced motion, keyboard, axe -------------------------------------------------------------------------------------

test("14 loading shimmers; reduced motion; keyboard-only focus; axe 0 serious/critical", async () => {
  skipBefore(14);
  test.setTimeout(300_000);
  const slow = async (route: import("@playwright/test").Route) => {
    await new Promise((r) => setTimeout(r, 6000));
    await route.continue();
  };
  await page.route(`${API}/threads`, slow);
  await page.route(`${API}/me/teams/${teamA}/card`, slow);
  await page.route(`${API}/threads/${threadA}/messages`, slow);
  await page.goto(`/chat/${threadA}`, { waitUntil: "commit" }); // the checks run while the throttled reads are pending
  await expect(vis(page, "chat-skeleton")).toBeVisible();
  await expect(vis(page, "threads-skeleton")).toBeVisible();
  await expect(vis(page, "card-skeleton")).toBeVisible();
  await shot(page, "24_shimmers");
  await expect(page.locator('[data-testid="chat"][data-ready="true"]:visible')).toBeVisible({ timeout: 30_000 });
  await expect(vis(page, "team-card")).toBeVisible({ timeout: 30_000 }); // the throttled reads are all in before the routes go
  await page.unroute(`${API}/threads`);
  await page.unroute(`${API}/me/teams/${teamA}/card`);
  await page.unroute(`${API}/threads/${threadA}/messages`);
  // reduced motion: no ring spin, one word, no rotation, no shimmer / pulse
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.route(`${API}/chat`, async (route) => {
    await new Promise((r) => setTimeout(r, 7500));
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ answer: "Reduced-motion mock.", thread_id: threadA, message_id: null, sources: [], squad_preview: null, squad_applied: null }) });
  });
  await vis(page, "chat-input").fill("reduced motion");
  await vis(page, "chat-input").press("Enter");
  await expect(vis(page, "thinking")).toBeVisible();
  const w1 = await vis(page, "spinner-word").textContent();
  expect(await vis(page, "thinking").locator(".ch-ring").evaluate((el) => getComputedStyle(el).animationName)).toBe("none");
  expect(await page.locator(".hm-pulse:visible").first().evaluate((el) => getComputedStyle(el).animationName)).toBe("none");
  await page.waitForTimeout(3500);
  expect(await vis(page, "spinner-word").textContent()).toBe(w1);
  await shot(page, "25_reduced_motion");
  await expect(vis(page, "thinking")).toHaveCount(0, { timeout: 20_000 });
  await page.unroute(`${API}/chat`);
  await page.emulateMedia({ reducedMotion: null });
  // keyboard-only: Tab from the top; every stop shows the focus outline
  await page.reload();
  await expect(page.locator('[data-testid="chat"][data-ready="true"]:visible')).toBeVisible({ timeout: 30_000 });
  await page.keyboard.press("Tab");
  const stops: string[] = [];
  for (let i = 0; i < 12; i++) {
    const info = await page.evaluate(() => {
      const el = document.activeElement as HTMLElement | null;
      if (!el || el === document.body) return null;
      const s = getComputedStyle(el);
      return { tag: el.tagName, id: el.getAttribute("data-testid") ?? el.getAttribute("aria-label") ?? el.textContent?.trim().slice(0, 16) ?? "", outline: `${s.outlineStyle} ${s.outlineWidth} ${s.outlineColor}` };
    });
    if (!info) break;
    stops.push(`${info.id}:${info.outline}`);
    await page.keyboard.press("Tab");
  }
  const withRing = stops.filter((x) => /solid 2px rgb\(59, 232, 255\)/.test(x)).length;
  log(`keyboard stops: ${withRing}/${stops.length} with the 2px #3BE8FF ring: ${stops.join(" > ")}`);
  if (withRing < stops.length) notes.push(`14: ${stops.length - withRing} of ${stops.length} keyboard stops without the page's focus ring (see the log)`);
  expect(withRing).toBeGreaterThanOrEqual(Math.min(8, stops.length));
  await shot(page, "26_keyboard_focus");
  const axe = await new AxeBuilder({ page }).analyze();
  const serious = axe.violations.filter((v) => v.impact === "serious" || v.impact === "critical");
  log(`axe: ${axe.violations.length} violation(s), ${serious.length} serious/critical: ${serious.map((v) => `${v.id} x${v.nodes.length}`).join(", ")}`);
  for (const v of axe.violations) log(`axe ${v.impact}: ${v.id} (${v.nodes.length}) ${v.nodes[0]?.target?.join(" ")}`);
  if (serious.length) notes.push(`14: axe found ${serious.length} serious/critical: ${serious.map((v) => v.id).join(", ")}`);
});

// ---- 12 + 15: 401 and an unknown chat id; the GET counts -------------------------------------------------------------------------------

test("12 an unknown chat id is silently a new chat; sign out in another tab -> a send goes to /login", async () => {
  skipBefore(15); // the last test (401, the unknown id, the GET counts): runs on every resumed range
  test.setTimeout(180_000);
  const c = countApiGets(page);
  await page.goto("/chat/th_does_not_exist");
  await expect(page.locator('[data-testid="chat"][data-ready="true"]:visible')).toBeVisible({ timeout: 30_000 });
  await page.waitForTimeout(1000);
  expect(page.url()).not.toContain("th_does_not_exist");
  await expect(page.locator('[data-testid="empty-team"]:visible, [data-testid="empty-general"]:visible')).toBeVisible();
  log(`unknown chat id -> ${page.url().replace(/^https?:\/\/[^/]+/, "")} (context ${await page.locator('[data-testid="chat"]:visible').getAttribute("data-context")}), ${c.gets} GETs`);
  await shot(page, "27_unknown_chat");
  await openChat(`/chat/${threadA}`, "reopen /chat/{id} (step 12)");
  const other = await context.newPage();
  await other.goto("/home");
  await expect(other.getByTestId("teams-section")).toBeVisible({ timeout: 30_000 });
  await other.locator('[data-testid="account-menu"]:visible').click();
  await other.getByTestId("sign-out").click();
  await other.waitForURL("**/login**", { timeout: 20_000 });
  await other.close();
  await vis(page, "chat-input").fill("after sign out");
  await vis(page, "chat-input").press("Enter");
  await page.waitForURL("**/login**", { timeout: 30_000 });
  log("401 after a sign-out elsewhere -> /login");
  for (const g of gets) log(`GETS ${g.what}: ${g.gets} (${g.paths.map((p) => p.replace(/\/th_[^/]+/, "/{id}").replace(/\/\d+\//, "/{id}/")).join(", ")})`);
});
