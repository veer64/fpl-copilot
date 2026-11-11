import { expect, test, type BrowserContext, type Page } from "@playwright/test";
import { createTestUser, deleteUser, findTestUsers } from "./clerk-users";
import { DB_PREFIX, apiCall, py, signIn, vis } from "./w4";
import { shot5, sql1 } from "./w5";

/** Prompt W5b PART 3 step 7: the W5 flows re-run with NO agent turn and NO FPL request (the W5b caps are $0 / 0): the test
 *  user's team and chat are seeded on the laptop database the way the app writes them (a squad version under a fresh squad
 *  key + a user_fpl_teams row; a chat_threads row with a real LangGraph checkpoint written through the app's own thread
 *  graph), then Delete chat, Remove team and Delete account run through the UI on desktop and the phone; the login intro and
 *  the deleted-account note are checked on the way. Clerk test user w5br, deleted by the flow. */

test.describe.configure({ mode: "serial" });
const NAME = "w5br";
const FPL_ID = 7_000_001;
let context: BrowserContext;
let page: Page;
let userId = 0;
let threadId = "";
const log = (s: string) => console.log(`[W5br] ${s}`);
const results: string[] = [];
const pass = (s: string) => {
  results.push(s);
  log(`PASS ${s}`);
};

/** One team + one chat for `uid`, written like the app does (no FPL, no model): the squad from the thread tests' legal
 *  document under a new squad key, the chat with a checkpoint + transcript so /threads lists it. Returns the thread id. */
function seed(uid: number): string {
  const out = py(`${DB_PREFIX}
import json, sys
sys.path.insert(0, r"C:\\dev\\fpl-copilot\\Tests")
import thread_fakes as tf, squad_store, fpl_teams, threads, agent_graph, chat_messages
fpl_teams.ensure_schema(conn)
doc = tf.legal_document()
with conn.cursor() as c2:
    c2.execute("INSERT INTO user_fpl_teams (user_id, fpl_team_id, label, is_active, last_imported_at, last_imported_gw, entry_name, manager_name) VALUES (%s, %s, %s, TRUE, now(), 10, %s, %s) RETURNING squad_key", (${uid}, ${FPL_ID}, "Seeded XI", "Seeded XI", "Test Manager"))
    key = c2.fetchone()[0]
conn.commit()
squad_store.write_version(None, doc, 10, "W5b seed", True, user_id=key)
tid = threads.create_thread(${uid})
g = agent_graph.thread_graph()
cfg = {"configurable": {"thread_id": tid}}
msgs = [{"role": "user", "content": "Who is my captain?"}, {"role": "assistant", "content": "Your captain is P13."}]
entry = {"q": 0, "user": "Who is my captain?", "user_at": "2026-11-10T20:00:00.000Z", "answer": "Your captain is P13.", "answer_at": "2026-11-10T20:00:05.000Z", "message_id": "w5bseed" + tid[3:11]}
g.update_state(cfg, {"messages": msgs, "transcript": [entry]}, as_node="finalize")
chat_messages.record(entry["message_id"], tid, ${uid}, 0, entry["answer_at"])
print(tid)
`);
  return out.trim().split("\n").pop()!;
}

test.beforeAll(async ({ browser }) => {
  for (const id of await findTestUsers(NAME)) await deleteUser(id);
  await createTestUser(NAME);
  context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  page = await context.newPage();
});

test.afterAll(async () => {
  for (const id of await findTestUsers(NAME)) await deleteUser(id);
  log(`clerk test users left ${(await findTestUsers(NAME)).length}`);
  for (const r of results) log(`RESULT ${r}`);
  await context?.close();
});

test("desktop: the intro runs; seeded team + chat; Delete chat; Remove team; Delete account -> the note skips the intro and the music", async () => {
  test.setTimeout(600_000);
  await page.goto("/login");
  await expect(page.locator(".stage").first()).toHaveAttribute("data-phase", "intro");
  await expect(vis(page, "hud").first()).toBeVisible();
  await signIn(page, `${NAME}+clerk_test@example.com`);
  userId = Number((await apiCall(page, "get", "/me")).body.user_id);
  expect(userId).toBeGreaterThanOrEqual(10001);
  threadId = seed(userId);
  expect(threadId).toMatch(/^th_/);
  const rows = (await apiCall(page, "get", "/threads")).body as unknown as { thread_id: string; fpl_team_id: number | null }[];
  expect(rows.map((r) => r.thread_id)).toContain(threadId);
  // Delete chat from the sidebar
  await page.goto(`/chat/${threadId}`);
  await expect(page.locator('[data-testid="chat"][data-ready="true"]:visible')).toBeVisible({ timeout: 30_000 });
  await expect(page.locator('[data-testid="assistant-message"]:visible')).toHaveCount(1);
  const row = page.locator(`[data-testid="thread-rowwrap"][data-thread-id="${threadId}"]`);
  await row.hover();
  await row.locator('[data-testid="thread-delete"]').click();
  await expect(vis(page, "delete-chat-dialog")).toBeVisible();
  await vis(page, "confirm-delete").click();
  await expect(vis(page, "delete-chat-dialog")).toHaveCount(0, { timeout: 20_000 });
  await expect(page).toHaveURL(new RegExp(`/chat\\?team=${FPL_ID}$`), { timeout: 15_000 });
  expect(sql1("SELECT count(*) FROM chat_threads WHERE thread_id = %s", [threadId])).toBe(0);
  expect(sql1("SELECT count(*) FROM checkpoints WHERE thread_id = %s", [threadId])).toBe(0);
  // Remove team from Home
  await page.goto("/home");
  await expect(page.locator(`[data-testid="team-card"][data-team-id="${FPL_ID}"]`)).toBeVisible({ timeout: 30_000 });
  await page.locator(`[data-testid="team-card"][data-team-id="${FPL_ID}"] [data-testid="remove-team"]`).click();
  await expect(vis(page, "remove-team-dialog")).toBeVisible();
  await expect(vis(page, "confirm-intro")).toContainText("This removes the team, its saved squads from FPL Copilot.");
  await vis(page, "confirm-delete").click();
  await expect(vis(page, "remove-team-dialog")).toHaveCount(0, { timeout: 30_000 });
  await expect(page.locator(`[data-testid="team-card"][data-team-id="${FPL_ID}"]`)).toHaveCount(0, { timeout: 15_000 });
  expect(sql1("SELECT count(*) FROM user_fpl_teams WHERE user_id = %s", [userId])).toBe(0);
  expect((await apiCall(page, "get", "/me")).body.active_team).toBeNull();
  // Delete account -> /login with the note, no intro, no music
  await vis(page, "account-menu").first().click();
  await expect(page.locator('[data-testid="delete-account"]')).toHaveAttribute("data-owner", "false", { timeout: 10_000 });
  await page.locator('[data-testid="delete-account"]').click();
  await expect(vis(page, "delete-account-dialog")).toBeVisible();
  await vis(page, "confirm-delete").click();
  await page.waitForURL("**/login**", { timeout: 60_000 });
  await expect(page.locator('[data-testid="deleted-note"]')).toBeVisible({ timeout: 20_000 });
  await expect(page.locator(".stage").first()).toHaveAttribute("data-phase", "login");
  await expect(page.locator(".stage").first()).toHaveAttribute("data-music", "off");
  expect(await page.evaluate(() => (document.querySelector('[data-testid="site-audio"]') as HTMLAudioElement | null)?.paused ?? true)).toBe(true);
  await shot5(page, "w5b_regression_login_note");
  await page.reload();
  await expect(page.locator(".stage").first()).toHaveAttribute("data-phase", "intro", { timeout: 20_000 });
  await vis(page, "skip-intro").first().click();
  await expect(page.locator('[data-testid="deleted-note"]')).toHaveCount(0);
  expect(sql1("SELECT count(*) FROM app_users WHERE user_id = %s", [userId])).toBe(0);
  expect(await findTestUsers(NAME)).toEqual([]);
  pass(`desktop: intro ran; seeded team ${FPL_ID} + chat; Delete chat, Remove team, Delete account PASS; the note skipped the intro and the music; a reload is a normal visit again`);
});

test("phone: seeded team + chat; the three bottom sheets", async ({ browser }) => {
  test.setTimeout(600_000);
  await createTestUser(NAME);
  const ctx = await browser.newContext({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true });
  const p = await ctx.newPage();
  await signIn(p, `${NAME}+clerk_test@example.com`);
  const uid = Number((await apiCall(p, "get", "/me")).body.user_id);
  const tid = seed(uid);
  await p.goto(`/chat?team=${FPL_ID}`);
  await expect(p.locator('[data-testid="chat"][data-ready="true"]:visible')).toBeVisible({ timeout: 30_000 });
  await vis(p, "menu-button").click();
  await expect(vis(p, "drawer")).toBeVisible();
  await p.locator(`[data-testid="drawer"] [data-testid="thread-rowwrap"][data-thread-id="${tid}"] [data-testid="thread-delete"]`).click();
  await expect(vis(p, "delete-chat-sheet")).toBeVisible({ timeout: 10_000 });
  await p.waitForTimeout(700);
  await vis(p, "confirm-delete").click();
  await expect(p.locator('[data-testid="delete-chat-sheet"]')).toHaveCount(0, { timeout: 20_000 });
  expect(sql1("SELECT count(*) FROM chat_threads WHERE thread_id = %s", [tid])).toBe(0);
  await p.goto("/home");
  await expect(p.locator(`[data-testid="team-card"][data-team-id="${FPL_ID}"]`)).toBeVisible({ timeout: 30_000 });
  await p.locator(`[data-testid="team-card"][data-team-id="${FPL_ID}"] [data-testid="remove-team"]`).click();
  await expect(vis(p, "remove-team-sheet")).toBeVisible({ timeout: 10_000 });
  await p.waitForTimeout(700);
  await vis(p, "confirm-delete").click();
  await expect(p.locator('[data-testid="remove-team-sheet"]')).toHaveCount(0, { timeout: 30_000 });
  expect(sql1("SELECT count(*) FROM user_fpl_teams WHERE user_id = %s", [uid])).toBe(0);
  await vis(p, "account-menu").click();
  await expect(p.locator('[data-testid="delete-account"]')).toHaveAttribute("data-owner", "false", { timeout: 10_000 });
  await p.locator('[data-testid="delete-account"]').click();
  await expect(vis(p, "delete-account-sheet")).toBeVisible({ timeout: 10_000 });
  await p.waitForTimeout(700);
  await vis(p, "confirm-delete").click();
  await p.waitForURL("**/login**", { timeout: 60_000 });
  await expect(p.locator('[data-testid="deleted-note"]')).toBeVisible({ timeout: 20_000 });
  expect(sql1("SELECT count(*) FROM app_users WHERE user_id = %s", [uid])).toBe(0);
  await ctx.close();
  pass(`phone: seeded team + chat; Delete chat, Remove team, Delete account sheets PASS; user ${uid} gone`);
});
