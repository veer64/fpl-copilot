import { expect, test } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";
import { userName } from "./clerk-users";
import { API, apiCall, py, DB_PREFIX, signIn } from "./w4";

/** Prompt W11 Part 4: the draft against the REAL laptop backend (clerk mode on :8010, the laptop database, the real best picks),
 *  desktop only, run LAST (it deletes the shared Clerk test user through Delete account):
 *   G  a guest: Home (new user) -> Build my draft team -> the building card -> the draft chat with the opening message ->
 *      End guest session -> the guest AND its draft and chats are deleted (database), no real model call
 *   A  the shared test user: Build -> ONE real question in the draft chat -> Past chats lists it with DRAFT, Home's Recent chats
 *      too -> Delete account with the draft present -> the draft, its chats and the account are deleted (database + Clerk)
 *  Costs: one agent turn; FPL through the backend wrapper's budget; Clerk: one guest user (made and deleted by the backend). */

test.describe.configure({ mode: "serial" });
const NAME = userName("w11draft");
const SHOTS = process.env.W11_SHOTS ?? path.join("C:", "dev", "fpl-backups", "w11_draft_team_files");
const vis = (p: import("@playwright/test").Page, id: string) => p.locator(`[data-testid="${id}"]:visible`);
const shot = async (p: import("@playwright/test").Page, name: string) => {
  fs.mkdirSync(SHOTS, { recursive: true });
  await p.screenshot({ path: path.join(SHOTS, `real_${name}_1440x900.png`) });
};
const rows = (uid: number) =>
  JSON.parse(
    py(`${DB_PREFIX}
import json
out = {}
for t in ("app_users", "user_drafts", "chat_threads", "chat_messages", "squad_versions"):
    cur.execute("SELECT to_regclass(%s) IS NOT NULL", ("public." + t,))
    out[t] = 0 if not cur.fetchone()[0] else (cur.execute(f"SELECT count(*) FROM {t} WHERE user_id = %s", (${uid},)) or cur.fetchone()[0])
print(json.dumps(out))`).trim().split("\n").pop()!,
  ) as Record<string, number>;

test("G: a guest builds a draft, opens its chat, ends the session -> the guest and its draft are deleted", async ({ page }, info) => {
  test.skip(info.project.name !== "desktop", "desktop only");
  test.setTimeout(180_000);
  await page.goto("/login");
  await page.locator('[data-testid="skip-intro"]:visible').first().click().catch(() => {});
  const btn = vis(page, "continue-as-guest");
  await expect(btn).toHaveAttribute("data-guest-mode", "on", { timeout: 30_000 });
  await btn.click();
  await page.waitForURL("**/home", { timeout: 60_000 });
  const me = (await apiCall(page, "get", "/me")).body as { user_id: number; is_guest: boolean };
  expect(me.is_guest).toBe(true);
  await expect(vis(page, "choice-draft")).toHaveAttribute("data-state", "build", { timeout: 30_000 });
  const t0 = Date.now();
  await vis(page, "build-draft").click();
  await expect(vis(page, "draft-building")).toBeVisible();
  await page.waitForURL(/\/chat\/th_/, { timeout: 60_000 });
  await expect(vis(page, "opening-chips")).toBeVisible({ timeout: 30_000 });
  console.log(`[W11] guest ${me.user_id}: build -> chat ${Date.now() - t0} ms`);
  await expect(vis(page, "card-line")).toContainText(" / £100.0m · ");
  await shot(page, "guest_draft_chat");
  const before = rows(me.user_id);
  console.log(`[W11] guest rows before: ${JSON.stringify(before)}`);
  expect(before.user_drafts).toBe(1);
  await vis(page, "account-menu").click();
  await vis(page, "end-guest-session").click();
  await page.locator('[data-testid="confirm-delete"]:visible').click();
  await page.waitForURL(/\/login\?reason=guest_ended/, { timeout: 60_000 });
  const after = rows(me.user_id);
  console.log(`[W11] guest rows after: ${JSON.stringify(after)}`);
  expect(after).toEqual({ app_users: 0, user_drafts: 0, chat_threads: 0, chat_messages: 0, squad_versions: 0 });
});

test("A: build, one real question -> Past chats + Recent chats say DRAFT; Delete account with the draft -> all deleted", async ({ page }, info) => {
  test.skip(info.project.name !== "desktop", "desktop only");
  test.setTimeout(300_000);
  await signIn(page, `${NAME}+clerk_test@example.com`);
  const me = (await apiCall(page, "get", "/me")).body as { user_id: number };
  console.log(`[W11] signed-in test user ${me.user_id} (>= 10001: ${me.user_id >= 10001})`);
  expect(me.user_id).toBeGreaterThanOrEqual(10001);
  await page.goto("/home");
  const build = page.locator('[data-testid="build-draft"]:visible, [data-testid="build-pill"]:visible').first();
  await expect(build).toBeVisible({ timeout: 30_000 });
  await build.click();
  await page.waitForURL(/\/chat\/th_/, { timeout: 60_000 });
  await expect(vis(page, "opening-chips")).toBeVisible({ timeout: 30_000 });
  await vis(page, "chat-input").fill("Is my bench good enough?");
  await page.keyboard.press("Enter");
  await expect(page.locator('[data-testid="assistant-message"][data-revealing="false"]:visible').nth(1)).toBeVisible({ timeout: 150_000 });
  const tid = new URL(page.url()).pathname.split("/").pop()!;
  const row = page.locator(`[data-testid="thread-row"][data-thread-id="${tid}"]:visible`);
  await expect(row).toBeVisible({ timeout: 20_000 });
  await expect(row).toContainText("DRAFT");
  await expect(row).toContainText("Is my bench good enough?");
  await shot(page, "past_chats_draft_tag");
  await page.goto("/home");
  await expect(page.locator('[data-testid="recent-row"]:visible').filter({ hasText: "Is my bench good enough?" }).locator('[data-testid="recent-tag-draft"]')).toHaveText("DRAFT", { timeout: 30_000 });
  await shot(page, "recent_chats_draft_tag");
  const before = rows(me.user_id);
  console.log(`[W11] account rows before: ${JSON.stringify(before)}`);
  expect(before.user_drafts).toBe(1);
  await vis(page, "account-menu").click();
  await vis(page, "delete-account").click();
  await page.locator('[data-testid="confirm-delete"]:visible').click();
  await page.waitForURL(/\/login/, { timeout: 60_000 });
  const after = rows(me.user_id);
  console.log(`[W11] account rows after: ${JSON.stringify(after)}`);
  expect(after).toEqual({ app_users: 0, user_drafts: 0, chat_threads: 0, chat_messages: 0, squad_versions: 0 });
  void API;
});
