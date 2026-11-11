import { expect, test, type BrowserContext, type Page } from "@playwright/test";
import { createTestUser, deleteUser, findTestUsers } from "./clerk-users";
import { DB_PREFIX, apiCall, py, signIn, vis } from "./w4";
import { boxOf, ownerRows, shot5, sql1, squadKeys, user1Guard } from "./w5";

/** Prompt W5 PART 3, the phone journey (390x844, short form): the About / Privacy headers (44px Home icon), the photos
 *  absolute, the Privacy section chips (swipe), and the three bottom sheets -- Delete chat (from the drawer), Remove team
 *  (Home), Delete account (the menu) -- Delete on top, full width, 44px targets. Clerk test user w5m takes over user B's
 *  app row from the desktop journey (its team + chat; no FPL import, no agent turn), so every delete here is real and B is
 *  gone at the end. Env: W5_RESUME_EMAIL (default w5b+clerk_test@example.com) names the row to take over. */

test.describe.configure({ mode: "serial" });
const NAME = "w5m";
const RESUME_EMAIL = process.env.W5_RESUME_EMAIL ?? "w5b+clerk_test@example.com";
let context: BrowserContext;
let page: Page;
let clerkId: string | null = null;
let userId = 0;
let teamId = 0;
let keys: number[] = [];
let guardBefore = "";
const log = (s: string) => console.log(`[W5m] ${s}`);
const results: string[] = [];
const pass = (s: string) => {
  results.push(s);
  log(`PASS ${s}`);
};

test.beforeAll(async ({ browser }) => {
  guardBefore = user1Guard();
  for (const id of await findTestUsers(NAME)) await deleteUser(id);
  clerkId = (await createTestUser(NAME)).id;
  userId = Number(sql1("SELECT user_id FROM app_users WHERE email = %s AND user_id >= 10001 ORDER BY user_id DESC LIMIT 1", [RESUME_EMAIL]) ?? 0);
  expect(userId, `an app row to take over (${RESUME_EMAIL.split("@")[0]}...)`).toBeGreaterThanOrEqual(10001);
  py(`${DB_PREFIX}cur.execute("UPDATE app_users SET clerk_user_id = %s WHERE user_id = %s AND user_id >= 10001", ("${clerkId}", ${userId})); conn.commit(); print(cur.rowcount)`);
  keys = squadKeys(userId);
  teamId = Number(sql1("SELECT fpl_team_id FROM user_fpl_teams WHERE user_id = %s ORDER BY id LIMIT 1", [userId]) ?? 0);
  log(`resumed app user ${userId} with ${keys.length} team(s)`);
  context = await browser.newContext({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true });
  page = await context.newPage();
});

test.afterAll(async () => {
  if (clerkId) await deleteUser(clerkId);
  for (const id of await findTestUsers(NAME)) await deleteUser(id);
  log(`user 1 guard unchanged: ${user1Guard() === guardBefore} | clerk test users left ${(await findTestUsers(NAME)).length}`);
  for (const r of results) log(`RESULT ${r}`);
  await context?.close();
});

async function sheetChecks(testId: string) {
  const sheet = vis(page, `${testId}-sheet`);
  await expect(sheet).toBeVisible({ timeout: 10_000 });
  const del = await boxOf(vis(page, "confirm-delete"));
  const cancel = await boxOf(vis(page, "confirm-cancel"));
  expect(del!.y, "Delete sits above Cancel").toBeLessThan(cancel!.y);
  expect(del!.w, "Delete is full width").toBeGreaterThan(330);
  expect(cancel!.w).toBeGreaterThan(330);
  expect(del!.h).toBeGreaterThanOrEqual(44);
  expect(cancel!.h).toBeGreaterThanOrEqual(44);
  expect(await page.evaluate(() => (document.activeElement as HTMLElement | null)?.getAttribute("data-testid"))).toBe("confirm-cancel");
  return sheet;
}

test("phone: headers, photos absolute, section chips, the three bottom sheets, 44px targets", async () => {
  test.setTimeout(600_000);
  // signed out first: About / Privacy headers and photos
  await page.goto("/about");
  await expect(page.locator('[data-testid="about"][data-signed-in="false"]')).toBeVisible({ timeout: 20_000 });
  const signInBox = await boxOf(vis(page, "header-sign-in"));
  expect(signInBox!.h).toBeGreaterThanOrEqual(40);
  expect(await page.locator('[data-testid="bg-photo"]').evaluate((el) => getComputedStyle(el).position)).toBe("absolute");
  await shot5(page, "phone_about_signed_out");
  await shot5(page, "phone_about_signed_out_full", true);
  await page.goto("/privacy");
  await expect(page.locator('[data-testid="privacy"][data-signed-in="false"]')).toBeVisible({ timeout: 20_000 });
  expect(await page.locator('[data-testid="bg-photo"]').evaluate((el) => getComputedStyle(el).position)).toBe("absolute");
  const chipnav = page.locator("nav.pp-chipnav");
  await expect(chipnav).toBeVisible();
  await expect(page.locator('[data-testid="toc"]')).toBeHidden();
  const scroll = await chipnav.evaluate((el) => ({ sw: el.scrollWidth, cw: el.clientWidth, ox: getComputedStyle(el).overflowX }));
  expect(scroll.sw).toBeGreaterThan(scroll.cw);
  expect(scroll.ox).toBe("auto");
  await chipnav.evaluate((el) => el.scrollTo({ left: el.scrollWidth, behavior: "auto" }));
  expect(await chipnav.evaluate((el) => el.scrollLeft)).toBeGreaterThan(50);
  await chipnav.locator('a[data-section="cookies"]').click();
  await expect.poll(async () => page.locator('[data-testid="privacy"]').getAttribute("data-current"), { timeout: 5_000 }).toBe("cookies");
  await expect(chipnav.locator('a[aria-current="true"]')).toHaveAttribute("data-section", "cookies");
  await shot5(page, "phone_privacy_signed_out");
  await shot5(page, "phone_privacy_signed_out_full", true);

  // signed in (the resumed row): the 44px Home icon, the menu, the Delete account sheet (cancelled)
  await signIn(page, `${NAME}+clerk_test@example.com`);
  expect(Number((await apiCall(page, "get", "/me")).body.user_id)).toBe(userId);
  await page.goto("/about");
  await expect(page.locator('[data-testid="about"][data-signed-in="true"]')).toBeVisible({ timeout: 20_000 });
  const home = await boxOf(vis(page, "header-home"));
  expect(home!.w).toBeGreaterThanOrEqual(44);
  expect(home!.h).toBeGreaterThanOrEqual(44);
  await expect(vis(page, "header-home")).toHaveAttribute("aria-label", "Home");
  const acct = await boxOf(vis(page, "account-menu"));
  expect(acct!.h).toBeGreaterThanOrEqual(40);
  await shot5(page, "phone_about_signed_in");
  await vis(page, "account-menu").click();
  await expect(page.locator('[data-testid="delete-account"]')).toHaveAttribute("data-owner", "false", { timeout: 10_000 });
  await shot5(page, "phone_menu");
  await page.locator('[data-testid="delete-account"]').click();
  await sheetChecks("delete-account");
  await shot5(page, "phone_sheet_delete_account");
  await vis(page, "confirm-cancel").click();
  await expect(page.locator('[data-testid="delete-account-sheet"]')).toHaveCount(0);

  // Delete chat from the drawer (the trash always visible, 44px)
  await page.goto(`/chat?team=${teamId}`);
  await expect(page.locator('[data-testid="chat"][data-ready="true"]:visible')).toBeVisible({ timeout: 30_000 });
  await vis(page, "menu-button").click();
  await expect(vis(page, "drawer")).toBeVisible();
  const row = page.locator('[data-testid="drawer"] [data-testid="thread-rowwrap"]').first();
  await expect(row).toBeVisible();
  const threadId = (await row.getAttribute("data-thread-id"))!;
  const trash = row.locator('[data-testid="thread-delete"]');
  await expect(trash).toHaveCSS("opacity", "1");
  const tb = await boxOf(trash);
  expect(tb!.w).toBeGreaterThanOrEqual(44);
  expect(tb!.h).toBeGreaterThanOrEqual(44);
  await shot5(page, "phone_drawer_trash");
  await trash.click();
  await sheetChecks("delete-chat");
  await expect(vis(page, "confirm-title")).toHaveText("Delete this chat?");
  await shot5(page, "phone_sheet_delete_chat");
  await vis(page, "confirm-delete").click();
  await expect(page.locator('[data-testid="delete-chat-sheet"]')).toHaveCount(0, { timeout: 20_000 });
  expect(sql1("SELECT count(*) FROM chat_threads WHERE thread_id = %s", [threadId])).toBe(0);
  await expect(page.locator(`[data-testid="thread-rowwrap"][data-thread-id="${threadId}"]`)).toHaveCount(0);

  // Remove team from Home (44px trash)
  await page.goto("/home");
  await expect(page.locator(`[data-testid="team-card"][data-team-id="${teamId}"]`)).toBeVisible({ timeout: 30_000 });
  const rm = page.locator(`[data-testid="team-card"][data-team-id="${teamId}"] [data-testid="remove-team"]`);
  const rb = await boxOf(rm);
  expect(rb!.w).toBeGreaterThanOrEqual(44);
  expect(rb!.h).toBeGreaterThanOrEqual(44);
  await rm.click();
  await sheetChecks("remove-team");
  await expect(vis(page, "confirm-delete")).toHaveText("Remove team");
  await shot5(page, "phone_sheet_remove_team");
  await vis(page, "confirm-delete").click();
  await expect(page.locator('[data-testid="remove-team-sheet"]')).toHaveCount(0, { timeout: 30_000 });
  await expect(page.locator(`[data-testid="team-card"][data-team-id="${teamId}"]`)).toHaveCount(0, { timeout: 15_000 });
  expect(sql1("SELECT count(*) FROM user_fpl_teams WHERE user_id = %s", [userId])).toBe(0);
  for (const k of keys) expect(sql1("SELECT count(*) FROM squad_versions WHERE user_id = %s", [k])).toBe(0);

  // Delete account (the sheet, Delete on top) -> /login + the note
  await vis(page, "account-menu").click();
  await expect(page.locator('[data-testid="delete-account"]')).toHaveAttribute("data-owner", "false", { timeout: 10_000 });
  await page.locator('[data-testid="delete-account"]').click();
  await sheetChecks("delete-account");
  await vis(page, "confirm-delete").click();
  await page.waitForURL("**/login**", { timeout: 60_000 });
  await expect(page.locator('[data-testid="deleted-note"]')).toBeVisible({ timeout: 20_000 });
  await shot5(page, "phone_login_deleted_note");
  const left = ownerRows([userId, ...keys]);
  for (const [t, n] of Object.entries(left)) expect(n, `${t} rows after`).toBe(0);
  expect(await findTestUsers(NAME)).toEqual([]);
  clerkId = null;
  pass(`phone: Sign in header / 44px Home icon, photos absolute, chip nav scrolls (${scroll.sw} > ${scroll.cw}) and highlights, Delete account / Delete chat / Remove team sheets (Delete on top, full width, >= 44px), all three deletes real; user ${userId} gone`);
});
