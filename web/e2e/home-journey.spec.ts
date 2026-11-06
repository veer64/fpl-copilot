import { expect, test, type Page } from "@playwright/test";
import { execFileSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { createTestUser, deleteUser, findTestUsers, testEmail } from "./clerk-users";

/** Prompt W3 PART 3: ONE continuous journey through /login -> /home -> the backend -> FPL (desktop 1440x900), and a short
 *  form of it at 390x844 (mobile). The laptop backend runs in clerk mode on http://localhost:8000 (branch home); every value
 *  on the page comes from it. FPL is read from the test only to pick team ids (leagues-classic/314, page 1) and to check
 *  the cards' numbers and the deadline against FPL's own answers -- each request >= 1 s apart, counted and printed.
 *  Clerk test users: w3home (desktop) and w3mob (mobile), code 424242, deleted at the end. */

test.describe.configure({ mode: "serial" });

const API = process.env.W3_API_BASE ?? "http://localhost:8000";
const SHOTS = process.env.W3_SHOTS ?? path.join("C:", "dev", "fpl-backups", "w3_home_files");
const REPO = path.resolve(process.cwd(), "..");
const FPL = "https://fantasy.premierleague.com/api";
const NAMES = { desktop: "w3home", mobile: "w3mob" };
const LIMIT_TEXT = "You can add up to 3 teams";

const mask = (id: number | string) => `***${String(id).slice(-3)}`;
let fplRequests = 0;
let lastFpl = 0;

async function fplGet<T>(p: string): Promise<T> {
  const wait = 1100 - (Date.now() - lastFpl);
  if (wait > 0) await new Promise((r) => setTimeout(r, wait));
  lastFpl = Date.now();
  fplRequests++;
  const r = await fetch(`${FPL}/${p}`, { headers: { "User-Agent": "Mozilla/5.0 (fpl-copilot W3 browser check; contact: repo owner)" } });
  if (!r.ok) throw new Error(`FPL ${p}: HTTP ${r.status}`);
  return (await r.json()) as T;
}

type Entry = { id: number; name: string; summary_overall_points: number; summary_overall_rank: number; summary_event_points: number; current_event: number };
type Boot = { events: { id: number; deadline_time: string; finished: boolean; is_next: boolean }[] };

function shotName(page: Page, name: string) {
  const vp = page.viewportSize()!;
  return path.join(SHOTS, `${name}_${vp.width}x${vp.height}.png`);
}
const shot = (page: Page, name: string) => page.screenshot({ path: shotName(page, name), fullPage: true });

async function token(page: Page): Promise<string> {
  const t = await page.evaluate(() => (window as unknown as { Clerk?: { session?: { getToken: () => Promise<string | null> } } }).Clerk?.session?.getToken());
  if (!t) throw new Error("no Clerk session token in the page");
  return t;
}

async function apiCall(page: Page, method: "get" | "post" | "delete", p: string, json?: unknown) {
  const t = await token(page);
  const r = await page.request[method](`${API}${p}`, { headers: { Authorization: `Bearer ${t}` }, data: json });
  let body: unknown = null;
  try {
    body = await r.json();
  } catch {
    body = null;
  }
  return { status: r.status(), body: body as Record<string, unknown> & { detail?: string } };
}

async function signIn(page: Page, email: string) {
  await page.goto("/login");
  await page.getByTestId("skip-intro").click();
  await expect(page.locator(".stage")).toHaveAttribute("data-phase", "login");
  await page.locator("#c-email").fill(email);
  await page.getByTestId("send-code").click();
  await expect(page.getByTestId("code-sent-title")).toHaveText("Check your email");
  await page.getByTestId("otp").fill("424242");
  await page.waitForURL("**/home", { timeout: 30_000 });
}

async function signOut(page: Page) {
  await page.getByTestId("account-menu").click();
  await expect(page.getByTestId("sign-out")).toBeVisible();
  await page.getByTestId("sign-out").click();
  await page.waitForURL("**/login**", { timeout: 20_000 });
}

const card = (page: Page, id: number) => page.locator(`[data-testid="team-card"][data-team-id="${id}"]`);

async function openAddDialog(page: Page, via: "choice" | "card") {
  await page.getByTestId(via === "choice" ? "choice-add-team" : "add-team-card").click();
  await expect(page.getByTestId("add-team-input")).toBeVisible();
}

async function submitTeam(page: Page, value: string, label?: string) {
  await page.getByTestId("add-team-input").fill(value);
  if (label !== undefined) await page.getByTestId("add-team-label").fill(label);
  await page.getByTestId("add-team-submit").click();
}

async function expectAddError(page: Page, text: string) {
  const err = page.getByTestId("add-team-error");
  await expect(err).toHaveText(text, { timeout: 30_000 });
  await expect(err).toHaveAttribute("role", "alert");
  await expect(page.getByTestId("add-team-input")).toHaveAttribute("aria-invalid", "true");
}

function dbEnv(): Record<string, string> {
  // DB_* for the weekly job run from here, read from the repo's .env and never printed
  const out: Record<string, string> = {};
  const env = fs.readFileSync(path.join(REPO, ".env"), "utf8");
  for (const line of env.split(/\r?\n/)) {
    const m = line.match(/^(DB_HOST|DB_PORT|DB_NAME|DB_USER|DB_PASSWORD)=(.*)$/);
    if (m) out[m[1]] = m[2].trim().replace(/^"|"$/g, "");
  }
  return out;
}

let entries: number[] = [];
let boot: Boot | null = null;
const log = (s: string) => console.log(`[W3] ${s}`);

test.beforeAll(async () => {
  fs.mkdirSync(SHOTS, { recursive: true });
});

test.afterAll(async () => {
  // every project cleans up its own user; the mobile project also removes the desktop's (it signs in as it at the end)
  const names = test.info().project.name === "mobile" ? [NAMES.mobile, NAMES.desktop] : [NAMES.desktop];
  let found = 0;
  let deleted = 0;
  for (const n of names) {
    const ids = await findTestUsers(n);
    found += ids.length;
    for (const id of ids) if (await deleteUser(id)) deleted++;
  }
  log(`Clerk test users (${names.join(", ")}) found ${found}, deleted ${deleted}; FPL requests from the test: ${fplRequests}`);
  if (test.info().project.name === "mobile") for (const n of names) expect(await findTestUsers(n)).toHaveLength(0);
});

test("W3 desktop: login -> home -> teams -> chat -> refresh -> job -> sign out -> back", async ({ page, context }) => {
  test.skip(test.info().project.name !== "desktop", "the full journey runs once, on desktop");
  test.setTimeout(900_000);

  // --- team ids from FPL's overall league, page 1 ---------------------------------------------------------------------------
  const league = await fplGet<{ standings: { results: { entry: number }[] } }>("leagues-classic/314/standings/?page_standings=1");
  entries = league.standings.results.slice(0, 3).map((r) => r.entry);
  expect(entries).toHaveLength(3);
  log(`team ids from leagues-classic/314 page 1: ${entries.map(mask).join(", ")}`);
  boot = await fplGet<Boot>("bootstrap-static/");
  const nextEv = boot.events.find((e) => e.is_next) ?? boot.events.find((e) => new Date(e.deadline_time) > new Date())!;
  const lastFinished = Math.max(...boot.events.filter((e) => e.finished).map((e) => e.id));
  log(`FPL next deadline GW${nextEv.id} ${nextEv.deadline_time}; last finished GW${lastFinished}`);

  // --- a brand-new user signs in --------------------------------------------------------------------------------------------
  expect(await findTestUsers(NAMES.desktop)).toHaveLength(0);
  const u = await createTestUser(NAMES.desktop);
  log(`Clerk test user created (${NAMES.desktop})`);
  await signIn(page, u.email);
  const home = page.getByTestId("home");
  await expect(home).toHaveAttribute("data-state", "new", { timeout: 30_000 });
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Welcome, manager.");
  await expect(page.getByTestId("new-user-choices")).toBeVisible();
  await expect(page.getByTestId("teams-section")).toHaveCount(0);
  await expect(page.getByTestId("recent-chats")).toHaveCount(0);
  await expect(page.getByTestId("chip")).toHaveCount(4);
  await page.waitForTimeout(600);
  await shot(page, "new_user");
  log("new-user state: PASS (Welcome, two choices, chips, no team grid, no recent chats)");

  // --- the deadline pill against FPL ---------------------------------------------------------------------------------------
  const pill = page.getByTestId("deadline-pill");
  await expect(pill).toHaveAttribute("data-deadline", nextEv.deadline_time, { timeout: 20_000 });
  await expect(pill).toHaveAttribute("data-gw", String(nextEv.id));
  await expect(pill).toContainText(`GW${nextEv.id} DEADLINE`);
  await expect(pill).toContainText(/in \d+ (d|h|m)/);
  log(`deadline pill: GW${nextEv.id} ${nextEv.deadline_time} = FPL's is_next event -> PASS; text "${(await pill.textContent())?.trim()}"`);

  // --- team 1 by ID ----------------------------------------------------------------------------------------------------------
  await openAddDialog(page, "choice");
  await expect(page.getByTestId("add-team-dialog")).toBeVisible();
  await page.getByTestId("help-toggle").click();
  await expect(page.getByTestId("help-panel")).toBeVisible();
  await expect(page.getByTestId("help-panel")).toContainText("Your ID is the number after /entry/");
  await shot(page, "add_team_dialog");
  await submitTeam(page, String(entries[0]), "Journey team one");
  await expect(page.getByTestId("add-team-submit")).toContainText("Fetching your team from FPL");
  await expect(page.getByTestId("add-team-dialog")).toBeHidden({ timeout: 60_000 });
  await expect(card(page, entries[0])).toBeVisible({ timeout: 30_000 });
  await expect(page.getByTestId("teams-count")).toHaveText("1 of 3 teams");
  log(`team 1 (${mask(entries[0])}) added by ID -> card shown; toast note: ${(await page.locator("[data-sonner-toast]").first().textContent())?.slice(0, 120)}`);

  // --- team 2 by pasted link ------------------------------------------------------------------------------------------------
  await openAddDialog(page, "card");
  await submitTeam(page, `https://fantasy.premierleague.com/entry/${entries[1]}/event/${lastFinished}`);
  await expect(page.getByTestId("add-team-dialog")).toBeHidden({ timeout: 60_000 });
  await expect(card(page, entries[1])).toBeVisible({ timeout: 30_000 });
  await expect(page.getByTestId("teams-count")).toHaveText("2 of 3 teams");
  log(`team 2 (${mask(entries[1])}) added by pasted link -> card shown`);

  // --- the cards' numbers against FPL ---------------------------------------------------------------------------------------
  for (const id of entries.slice(0, 2)) {
    const e = await fplGet<Entry>(`entry/${id}/`);
    const c = card(page, id);
    const total = (await c.getByTestId("stat-total").textContent())!.replace(/,/g, "");
    const rank = (await c.getByTestId("stat-rank").textContent())!.replace(/,/g, "");
    const gw = (await c.getByTestId("stat-gw").textContent())!.replace(/,/g, "");
    expect(Number(total)).toBe(e.summary_overall_points);
    expect(Number(rank)).toBe(e.summary_overall_rank);
    if (e.current_event === lastFinished) expect(Number(gw)).toBe(e.summary_event_points);
    await expect(c.getByTestId("freshness")).toHaveAttribute("data-updated-after-gw", String(lastFinished));
    await expect(c).toContainText(e.name);
    log(`card ${mask(id)}: total ${total} rank ${rank} GW${lastFinished} ${gw} = FPL entry/ (${e.summary_overall_points} / ${e.summary_overall_rank} / ${e.summary_event_points}) -> PASS`);
  }
  await expect(card(page, entries[0])).toHaveAttribute("data-last-used", "true"); // the first import is active: highlighted
  await expect(card(page, entries[0]).getByTestId("ask-team")).toHaveClass(/hm-btn-p/);
  await expect(card(page, entries[1]).getByTestId("ask-team")).toHaveClass(/hm-btn-s/);

  // --- the errors (while a slot is free: the backend's 3-team check comes before any FPL request) ---------------------------
  await openAddDialog(page, "card");
  await submitTeam(page, "not-an-id");
  await expectAddError(page, "That’s not a valid ID or FPL link");
  await shot(page, "add_team_error_invalid");
  await submitTeam(page, "99999999"); // no such FPL entry: FPL answers 404
  await expectAddError(page, "We couldn’t find that team ID");
  await shot(page, "add_team_error_not_found");
  await submitTeam(page, String(entries[0]));
  await expectAddError(page, "You’ve already added this team");
  await shot(page, "add_team_error_duplicate");
  log("errors: invalid input / unknown ID (FPL 404) / duplicate -> PASS, each in role=alert under the field");

  // --- team 3 (the same dialog) and the 4th refused ---------------------------------------------------------------------------
  const page2 = await context.newPage(); // a second tab still showing 2 teams and the Add card
  await page2.setViewportSize({ width: 1440, height: 900 });
  await page2.goto("/home");
  await expect(page2.getByTestId("teams-count")).toHaveText("2 of 3 teams", { timeout: 30_000 });
  await submitTeam(page, String(entries[2]), "Journey team three");
  await expect(page.getByTestId("add-team-dialog")).toBeHidden({ timeout: 60_000 });
  await expect(card(page, entries[2])).toBeVisible({ timeout: 30_000 });
  await expect(page.getByTestId("teams-count")).toHaveText("3 of 3 teams");
  await expect(page.getByTestId("add-team-card")).toHaveCount(0);
  log(`team 3 (${mask(entries[2])}) added -> "3 of 3 teams", Add team card gone`);
  await page.waitForTimeout(400);
  await shot(page, "returning_3_teams");
  log("waiting 61 s: the backend allows 5 imports a minute per user (5 used: 3 teams, the unknown id, the duplicate)");
  await page.waitForTimeout(61_000);
  const fourth = await apiCall(page, "post", "/me/teams", { fpl_team_id: 1 });
  expect(fourth.status).toBe(409);
  expect(fourth.body.detail).toBe(LIMIT_TEXT);
  await openAddDialog(page2, "card"); // the stale tab tries a 4th
  await submitTeam(page2, "1");
  await expectAddError(page2, LIMIT_TEXT);
  await shot(page2, "add_team_error_limit");
  await page2.close();
  log(`4th team: API 409 "${fourth.body.detail}" and the dialog shows it -> PASS`);

  // --- Ask about this team (team 2) -> active -> /chat ------------------------------------------------------------------------
  await card(page, entries[1]).getByTestId("ask-team").click();
  await page.waitForURL(`**/chat?team=${entries[1]}`, { timeout: 30_000 });
  const chat = page.getByTestId("chat-placeholder");
  await expect(chat).toHaveAttribute("data-context", "team", { timeout: 30_000 });
  await expect(page.getByTestId("chat-context")).toContainText(`ID ${entries[1]}`);
  await expect(page.getByTestId("chat-thread")).toContainText("th_");
  const me1 = await apiCall(page, "get", "/me");
  expect((me1.body.active_team as { fpl_team_id: number }).fpl_team_id).toBe(entries[1]);
  const teamThread = await chat.getAttribute("data-thread");
  await shot(page, "chat_team");
  log(`Ask about this team (${mask(entries[1])}): /me active_team = it, /chat context "${await page.getByTestId("chat-context").textContent()}", thread ${teamThread} -> PASS`);
  await page.getByTestId("back-home").click();
  await expect(card(page, entries[1])).toHaveAttribute("data-last-used", "true", { timeout: 30_000 });
  await expect(card(page, entries[1])).toContainText("LAST USED");
  await expect(card(page, entries[0])).toContainText("NOT USED YET");

  // --- Ask without a team -> general -> /chat ----------------------------------------------------------------------------------
  await page.getByTestId("start-general").click();
  await page.waitForURL("**/chat", { timeout: 30_000 });
  await expect(chat).toHaveAttribute("data-context", "general", { timeout: 30_000 });
  await expect(page.getByTestId("chat-context")).toHaveText("general");
  const me2 = await apiCall(page, "get", "/me");
  expect(me2.body.active_team).toBeNull();
  const generalThread = await chat.getAttribute("data-thread");
  expect(generalThread).not.toBe(teamThread);
  await shot(page, "chat_general");
  log(`Ask without a team: /me active_team null, /chat context general, thread ${generalThread} -> PASS`);
  await page.getByTestId("back-home").click();

  // --- a chip -> /chat?q= ----------------------------------------------------------------------------------------------------
  const chipText = (await page.getByTestId("chip").nth(1).textContent())!.trim();
  expect(chipText).toBe(`Best captain for GW${nextEv.id}?`);
  await page.getByTestId("chip").nth(1).click();
  await page.waitForURL("**/chat?q=*", { timeout: 30_000 });
  await expect(page.getByTestId("chat-question")).toHaveText(chipText, { timeout: 30_000 });
  await expect(page.getByTestId("chat-context")).toHaveText("general");
  log(`chip "${chipText}" -> /chat?q= with the question prefilled -> PASS`);
  await page.getByTestId("back-home").click();

  // --- recent chats ------------------------------------------------------------------------------------------------------------
  const rows = page.getByTestId("recent-row");
  await expect(rows.first()).toBeVisible({ timeout: 30_000 });
  const n = await rows.count();
  expect(n).toBeGreaterThanOrEqual(2);
  const tags = await rows.locator(".hm-tag").allTextContents();
  expect(tags).toContain("GENERAL");
  expect(tags.some((t) => t !== "GENERAL")).toBe(true);
  const threadIds = await rows.evaluateAll((els) => els.map((e) => e.getAttribute("data-thread-id")));
  expect(threadIds).toContain(generalThread);
  expect(threadIds).toContain(teamThread);
  await rows.first().click();
  await page.waitForURL("**/chat/th_*", { timeout: 30_000 });
  await expect(page.getByTestId("chat-thread")).toHaveText(threadIds[0]!, { timeout: 30_000 });
  log(`recent chats: ${n} rows (tags ${tags.join(" / ")}) incl. the team and general threads; row 1 reopens ${threadIds[0]} -> PASS`);
  await page.getByTestId("back-home").click();

  // --- Refresh ---------------------------------------------------------------------------------------------------------------------
  const fresh0 = await card(page, entries[0]).getByTestId("freshness").getAttribute("data-summary-updated-at");
  await card(page, entries[0]).getByTestId("refresh").click();
  await expect(page.locator("[data-sonner-toast]").filter({ hasText: "refreshed from FPL" })).toBeVisible({ timeout: 60_000 });
  await expect
    .poll(async () => card(page, entries[0]).getByTestId("freshness").getAttribute("data-summary-updated-at"), { timeout: 30_000 })
    .not.toBe(fresh0);
  const fresh1 = await card(page, entries[0]).getByTestId("freshness").getAttribute("data-summary-updated-at");
  await expect(card(page, entries[0]).getByTestId("freshness")).toHaveAttribute("data-updated-after-gw", String(lastFinished));
  log(`Refresh ${mask(entries[0])}: summary_updated_at ${fresh0} -> ${fresh1}, updated_after_gw ${lastFinished} (= FPL's last finished) -> PASS`);

  // --- the weekly job, once, locally -------------------------------------------------------------------------------------------
  const py = path.join(REPO, ".venv", "Scripts", "python.exe");
  const out = execFileSync(py, [path.join(REPO, "eval", "refresh_team_scores.py"), "--force"], {
    cwd: REPO,
    env: { ...process.env, ...dbEnv() },
    encoding: "utf8",
    timeout: 120_000,
  });
  const summary = out.trim().split(/\r?\n/).pop() ?? "";
  expect(summary).toContain("SUCCESS");
  log(`weekly job: ${summary.replace(/\d{4,}/g, (m) => mask(m))}`);
  await page.reload();
  await expect
    .poll(async () => card(page, entries[0]).getByTestId("freshness").getAttribute("data-summary-updated-at"), { timeout: 30_000 })
    .not.toBe(fresh1);
  for (const id of entries) await expect(card(page, id).getByTestId("freshness")).toHaveAttribute("data-updated-after-gw", String(lastFinished));
  log("after the job: every card reloads with a newer summary_updated_at -> PASS");

  // --- keyboard run-through with visible focus ------------------------------------------------------------------------------------
  await page.reload();
  await expect(page.getByTestId("teams-count")).toHaveText("3 of 3 teams", { timeout: 30_000 });
  await page.locator("body").click({ position: { x: 5, y: 5 } });
  const seen: string[] = [];
  let badOutline = 0;
  for (let i = 0; i < 16; i++) {
    await page.keyboard.press("Tab");
    const info = await page.evaluate(() => {
      const el = document.activeElement as HTMLElement | null;
      if (!el || el === document.body) return null;
      const cs = getComputedStyle(el);
      return {
        id: el.getAttribute("data-testid") ?? el.getAttribute("aria-label") ?? el.tagName.toLowerCase() + (el.textContent?.trim().slice(0, 18) ?? ""),
        visible: el.matches(":focus-visible"),
        outline: `${cs.outlineStyle} ${cs.outlineWidth} ${cs.outlineColor}`,
        portal: !!el.closest("nextjs-portal"),
      };
    });
    if (!info || info.portal) continue;
    seen.push(`${info.id} [${info.outline}]`);
    if (!(info.visible && info.outline.startsWith("solid 2px") && info.outline.includes("rgb(59, 232, 255)"))) badOutline++;
  }
  expect(seen.length).toBeGreaterThanOrEqual(10);
  expect(badOutline).toBe(0);
  log(`keyboard: ${seen.length} stops, all with the 2px cyan focus outline: ${seen.slice(0, 8).join(" | ")} ...`);
  // the account menu by keyboard: opens, Esc closes
  await page.getByTestId("account-menu").focus();
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("sign-out")).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByTestId("sign-out")).toBeHidden();

  // --- copy the ID ------------------------------------------------------------------------------------------------------------------
  await context.grantPermissions(["clipboard-read", "clipboard-write"]);
  await card(page, entries[2]).getByTestId("copy-id").click();
  await expect(page.locator("[data-sonner-toast]").filter({ hasText: "Team ID copied" })).toBeVisible();
  expect(await page.evaluate(() => navigator.clipboard.readText())).toBe(String(entries[2]));

  // --- sign out, the redirects, sign back in -------------------------------------------------------------------------------------
  await signOut(page);
  await page.goto("/home");
  await page.waitForURL("**/login**", { timeout: 20_000 });
  await page.goto("/chat");
  await page.waitForURL("**/login**", { timeout: 20_000 });
  log("signed out: /home and /chat both end on /login -> PASS");
  await signIn(page, u.email);
  await expect(home).toHaveAttribute("data-state", "returning", { timeout: 30_000 });
  await expect(page.getByTestId("team-card")).toHaveCount(3);
  await expect(page.getByRole("heading", { level: 1 })).toContainText("What are we scouting?");
  await page.reload(); // refresh keeps the session
  await expect(page.getByTestId("team-card")).toHaveCount(3, { timeout: 30_000 });
  await page.goto("/login"); // signed in: straight to /home, no intro
  await page.waitForURL("**/home", { timeout: 20_000 });
  await expect(page.locator(".stage[data-phase='intro']")).toHaveCount(0);
  await expect(page.getByTestId("team-card")).toHaveCount(3, { timeout: 30_000 });
  await page.goto("/teams");
  await page.waitForURL("**/home", { timeout: 20_000 });
  log("sign back in: returning state with 3 teams; reload keeps the session; /login -> /home with no intro; /teams -> /home -> PASS");
  await signOut(page);
});

test("W3 mobile (390x844): the short journey -- new user, sheet + errors, team, general, chip; then the returning user", async ({ page }) => {
  test.skip(test.info().project.name !== "mobile", "the phone run");
  test.setTimeout(600_000);
  const league = await fplGet<{ standings: { results: { entry: number }[] } }>("leagues-classic/314/standings/?page_standings=1");
  const id = league.standings.results[3].entry; // the 4th team of page 1: not one of the desktop user's
  const u = await createTestUser(NAMES.mobile);
  log(`Clerk test user created (${NAMES.mobile}); team ${mask(id)}`);
  await signIn(page, u.email);
  const home = page.getByTestId("home");
  await expect(home).toHaveAttribute("data-state", "new", { timeout: 30_000 });
  await expect(page.getByTestId("deadline-band")).toContainText(/in \d+ (d|h|m)/, { timeout: 20_000 });
  await expect(page.getByTestId("deadline-pill")).toBeHidden(); // the header pill is gone at this width
  await page.waitForTimeout(600);
  await shot(page, "new_user");
  await openAddDialog(page, "choice");
  await expect(page.getByTestId("add-team-sheet")).toBeVisible();
  await page.waitForTimeout(600);
  await shot(page, "add_team_sheet");
  await submitTeam(page, "fantasy.premierleague.com/entry/abc");
  await expectAddError(page, "That’s not a valid ID or FPL link");
  await shot(page, "add_team_error_invalid");
  await submitTeam(page, "99999998");
  await expectAddError(page, "We couldn’t find that team ID");
  await shot(page, "add_team_error_not_found");
  await submitTeam(page, `https://fantasy.premierleague.com/entry/${id}/history`);
  await expect(page.getByTestId("add-team-sheet")).toBeHidden({ timeout: 60_000 });
  await expect(card(page, id)).toBeVisible({ timeout: 30_000 });
  const chip = card(page, id).getByTestId("copy-id");
  expect((await chip.boundingBox())!.height).toBeGreaterThanOrEqual(44); // touch target
  await openAddDialog(page, "card");
  await submitTeam(page, String(id));
  await expectAddError(page, "You’ve already added this team");
  await shot(page, "add_team_error_duplicate");
  await page.getByTestId("add-team-cancel").click();
  await expect(page.getByTestId("add-team-sheet")).toBeHidden();
  log("mobile new user: sheet, invalid / unknown / duplicate errors, one team by link -> PASS");
  await card(page, id).getByTestId("ask-team").click();
  await page.waitForURL(`**/chat?team=${id}`, { timeout: 30_000 });
  await expect(page.getByTestId("chat-placeholder")).toHaveAttribute("data-context", "team", { timeout: 30_000 });
  await shot(page, "chat_team");
  await page.getByTestId("back-home").click();
  await expect(card(page, id)).toContainText("LAST USED", { timeout: 30_000 });
  await page.getByTestId("start-general").click();
  await page.waitForURL("**/chat", { timeout: 30_000 });
  await expect(page.getByTestId("chat-placeholder")).toHaveAttribute("data-context", "general", { timeout: 30_000 });
  await shot(page, "chat_general");
  await page.getByTestId("back-home").click();
  await page.getByTestId("chip").first().click();
  await page.waitForURL("**/chat?q=*", { timeout: 30_000 });
  await expect(page.getByTestId("chat-question")).toContainText("in form", { timeout: 30_000 });
  await page.getByTestId("back-home").click();
  await expect(page.getByTestId("recent-row").first()).toBeVisible({ timeout: 30_000 });
  await page.waitForTimeout(400);
  await shot(page, "returning_1_team");
  await signOut(page);
  // the desktop user's three teams at phone width
  const ids = await findTestUsers(NAMES.desktop);
  expect(ids).toHaveLength(1);
  await signIn(page, testEmail(NAMES.desktop));
  await expect(home).toHaveAttribute("data-state", "returning", { timeout: 30_000 });
  await expect(page.getByTestId("team-card")).toHaveCount(3);
  await expect(page.getByTestId("add-team-card")).toHaveCount(0);
  await page.waitForTimeout(600);
  await shot(page, "returning_3_teams");
  log("mobile returning user: 3 stacked cards, no Add row -> PASS");
  await signOut(page);
});
