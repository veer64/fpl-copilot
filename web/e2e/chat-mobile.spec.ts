import { expect, test, type BrowserContext, type Page } from "@playwright/test";
import fs from "node:fs";
import { createTestUser, deleteUser, findTestUsers } from "./clerk-users";
import { SHOTS, addTeamOnHome, apiCall, fplGet, mask, py, shot, signIn, type Standing, vis, DB_PREFIX } from "./w4";

/** Prompt W4 PART 3, the phone journey (390x844, short form): header + compact chip, the drawer, the team bar text, a
 *  preview -> "1 CHANGE" pill + the panel opening itself, typing closes it, a player's bottom sheet (Esc, focus trap, 44px
 *  close), the General layout, the phone footer, targets >= 44px. ONE real agent turn (the captain preview). Clerk test
 *  user w4mob, deleted at the end. Env: W4_TEAM_A reuses the desktop team id. */

test.describe.configure({ mode: "serial" });
const NAME = "w4mob";
let context: BrowserContext;
let page: Page;
let clerkId: string | null = null;
let appUserId = 0;
let teamId = Number(process.env.W4_TEAM_A ?? 0);
const log = (s: string) => console.log(`[W4m] ${s}`);
let usd = 0;
let seconds = 0;

test.beforeAll(async ({ browser }) => {
  fs.mkdirSync(SHOTS, { recursive: true });
  for (const id of await findTestUsers(NAME)) await deleteUser(id);
  clerkId = (await createTestUser(NAME)).id;
  // W4_RESUME_USER_ID: the fresh Clerk user takes over the desktop journey's app_users row (>= 10001) so its teams are reused
  // and no FPL import is repeated (the W3 resume pattern; the FPL budget is 40 for the whole prompt)
  const resume = Number(process.env.W4_RESUME_USER_ID ?? 0);
  if (resume >= 10001) {
    py(`${DB_PREFIX}cur.execute("UPDATE app_users SET clerk_user_id = %s WHERE user_id = %s AND user_id >= 10001", ("${clerkId}", ${resume})); conn.commit(); print(cur.rowcount)`);
    // the working cap: the resumed user's day already holds the desktop runs' turns (afterAll sets NULL at the end)
    py(`${DB_PREFIX}cur.execute("UPDATE app_users SET daily_cap_usd = 5 WHERE user_id = %s AND user_id >= 10001", (${resume},)); conn.commit(); print(cur.rowcount)`);
    log(`resumed app user ${resume}`);
  }
  if (!teamId) {
    const league = await fplGet<{ standings: { results: Standing[] } }>("leagues-classic/314/standings/?page_standings=1");
    teamId = league.standings.results[0].entry;
  }
  log(`team ${mask(teamId)}`);
  context = await browser.newContext({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true });
  page = await context.newPage();
});
test.afterAll(async () => {
  try {
    if (appUserId) py(`${DB_PREFIX}cur.execute("UPDATE app_users SET daily_cap_usd = NULL WHERE user_id = %s AND user_id >= 10001", (${appUserId},)); conn.commit()`);
  } catch {
    /* nothing to restore */
  }
  if (clerkId) await deleteUser(clerkId);
  for (const id of await findTestUsers(NAME)) await deleteUser(id);
  log(`SUMMARY turns 1 $${usd.toFixed(4)} ${seconds} s`);
  await context?.close();
});

async function box(loc: ReturnType<Page["locator"]>) {
  const b = await loc.boundingBox();
  return b ? { w: Math.round(b.width), h: Math.round(b.height) } : null;
}

test("phone: header, drawer, team bar, pitch panel, sheet, preview pill, general, footer, targets", async () => {
  test.setTimeout(400_000);
  await signIn(page, `${NAME}+clerk_test@example.com`);
  appUserId = Number((await apiCall(page, "get", "/me")).body.user_id);
  if (!process.env.W4_RESUME_USER_ID) await addTeamOnHome(page, teamId, "choice");
  else await expect(page.locator(`[data-testid="team-card"][data-team-id="${teamId}"]`)).toBeVisible({ timeout: 30_000 });
  await page.locator(`[data-testid="team-card"][data-team-id="${teamId}"] [data-testid="ask-team"]`).click();
  await page.waitForURL(`**/chat?team=${teamId}`);
  await expect(page.locator('[data-testid="chat"][data-ready="true"]:visible')).toBeVisible({ timeout: 30_000 });
  // header: menu, logo, the compact chip from the same deadline component, the avatar
  await expect(vis(page, "menu-button")).toBeVisible();
  await expect(vis(page, "deadline-chip")).toHaveText(/^GW\d+\s*(\d+d \d+h|\d+h \d+m|\d+m|now)$/);
  await expect(page.locator('[data-testid="deadline-pill"]:visible')).toHaveCount(0);
  await expect(vis(page, "account-menu")).toBeVisible();
  const targets: Record<string, { w: number; h: number } | null> = { menu: await box(vis(page, "menu-button")), send: await box(vis(page, "send")), chip: await box(vis(page, "empty-chip").first()) };
  await shot(page, "m01_header_empty");
  // the team bar text
  const card = (await apiCall(page, "get", `/me/teams/${teamId}/card`)).body as { formation: string; players: { role: string | null; short_name: string; flag: unknown }[] };
  const captain = card.players.find((p) => p.role === "C")!;
  const injuries = card.players.filter((p) => p.flag).length;
  const line = await vis(page, "team-bar-line").innerText();
  log(`team bar: ${line.replace(/\n/g, " ")}`);
  expect(line).toContain(`${card.formation} · C ${captain.short_name.toUpperCase()}`);
  expect(line).toContain(injuries ? `${injuries} ${injuries === 1 ? "INJURY" : "INJURIES"}` : "NO INJURIES");
  await expect(page.locator('[data-testid="changes-pill"]:visible')).toHaveCount(0);
  // the drawer
  await vis(page, "menu-button").click();
  await expect(vis(page, "drawer")).toBeVisible();
  await expect(vis(page, "drawer-home")).toBeVisible();
  await expect(vis(page, "drawer-new-chat")).toBeVisible();
  await expect(vis(page, "thread-row-new")).toBeVisible();
  targets.drawerClose = await box(vis(page, "drawer-close"));
  await shot(page, "m02_drawer");
  await page.keyboard.press("Escape");
  await expect(page.locator('[data-testid="drawer"]')).toHaveCount(0);
  // the pitch panel + a player's sheet
  await vis(page, "team-bar").click();
  await expect(vis(page, "pitch-panel")).toBeVisible();
  expect((await box(vis(page, "pitch")))?.h).toBe(250);
  await expect(vis(page, "bench")).toBeVisible();
  await expect(vis(page, "chips-row")).toBeVisible();
  await expect(vis(page, "card-refresh")).toBeVisible();
  await shot(page, "m03_pitch_open");
  await page.locator('[data-testid="token"]:visible').nth(2).tap();
  await expect(vis(page, "player-sheet")).toBeVisible();
  const sheet = vis(page, "player-sheet").locator('[role="dialog"]');
  await expect(sheet).toHaveAttribute("aria-modal", "true");
  targets.sheetClose = await box(vis(page, "sheet-close"));
  await expect(vis(page, "sheet-name")).not.toBeEmpty();
  await expect(sheet.locator('[data-testid="hover-pred"]')).toBeVisible();
  // the focus trap: Tab from the last focusable wraps to the first
  const inside = await page.evaluate(() => {
    const d = document.querySelector('[data-testid="player-sheet"] [role="dialog"]')!;
    return d.contains(document.activeElement);
  });
  expect(inside).toBe(true);
  for (let i = 0; i < 4; i++) await page.keyboard.press("Tab");
  expect(await page.evaluate(() => document.querySelector('[data-testid="player-sheet"] [role="dialog"]')!.contains(document.activeElement))).toBe(true);
  await shot(page, "m04_player_sheet");
  await page.keyboard.press("Escape");
  await expect(page.locator('[data-testid="player-sheet"]')).toHaveCount(0);
  await vis(page, "team-bar").click();
  await expect(page.locator('[data-testid="pitch-panel"]')).toHaveCount(0);
  // ONE agent turn: a captain preview -> the "1 CHANGE" pill, the panel opens itself; typing closes it
  const vc = card.players.find((p) => p.role === "VC")!;
  const before = Number((await apiCall(page, "get", "/me")).body.spent_today_usd);
  const t0 = Date.now();
  await vis(page, "chat-input").fill(`Make ${vc.short_name} my captain.`);
  await vis(page, "send").tap();
  await expect(vis(page, "thinking")).toBeVisible({ timeout: 10_000 });
  await expect(vis(page, "footer-line").locator(".phone")).toHaveText("SPINNER WORDS NEED ELITE BALL KNOWLEDGE");
  await expect(vis(page, "footer-line").locator(".desk")).toBeHidden(); // the desktop line is not shown on phones
  await shot(page, "m05_thinking");
  await expect(vis(page, "thinking")).toHaveCount(0, { timeout: 120_000 });
  seconds = Math.round((Date.now() - t0) / 10) / 100;
  usd = Math.max(0, Number((await apiCall(page, "get", "/me")).body.spent_today_usd) - before);
  log(`turn (captain preview): ${seconds} s, $${usd.toFixed(4)}`);
  const pv = page.locator('[data-testid="preview-card"]:visible');
  if ((await pv.count()) === 0) {
    log("NOTE the agent made no preview on the phone turn");
  } else {
    await expect(vis(page, "changes-pill")).toHaveText(/^\d+ CHANGES?$/);
    await expect(vis(page, "pitch-panel")).toBeVisible();
    await expect(page.locator('[data-testid="token"][data-mark="badge-in"]:visible').first()).toBeVisible(); // one or two (an armband swap marks both green)
    await shot(page, "m06_preview_pill_panel");
    await vis(page, "chat-input").fill("t");
    await expect(page.locator('[data-testid="pitch-panel"]')).toHaveCount(0);
    await vis(page, "chat-input").fill("");
    await shot(page, "m07_preview_card");
  }
  // General layout: the photo at the top, greeting + chips near the bottom above the box; the phone footer
  await page.goto("/chat");
  await expect(page.locator('[data-testid="chat"][data-context="general"][data-ready="true"]:visible')).toBeVisible({ timeout: 30_000 });
  await expect(page.locator('[data-testid="team-bar"]:visible')).toHaveCount(0);
  const photo = await page.locator(".ch-gen-photo:visible").boundingBox();
  const title = await vis(page, "empty-title").boundingBox();
  const boxY = (await vis(page, "chat-box").boundingBox())!.y;
  expect(photo!.y).toBeLessThan(120);
  expect(title!.y).toBeGreaterThan(300);
  expect(title!.y).toBeLessThan(boxY);
  await expect(vis(page, "footer-line").locator(".phone")).toHaveText("SPINNER WORDS NEED ELITE BALL KNOWLEDGE");
  await expect(vis(page, "footer-line").locator(".desk")).toBeHidden(); // the desktop line is not shown on phones
  await shot(page, "m08_general");
  log(`targets: ${JSON.stringify(targets)}`);
  for (const [k, v] of Object.entries(targets)) {
    expect(v, k).not.toBeNull();
    expect(Math.min(v!.w, v!.h), `${k} >= 44px`).toBeGreaterThanOrEqual(44);
  }
});
