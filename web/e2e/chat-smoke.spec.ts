import { expect, test } from "@playwright/test";
import { createTestUser, deleteUser, findTestUsers } from "./clerk-users";
import { API, addTeamOnHome, apiCall, fplGet, mask, shot, signIn, type Standing, vis } from "./w4";

/** Prompt W4 PART 3 smoke (no agent turns): one Clerk test user, a team added on Home, /chat?team= opened -- the empty state,
 *  the card against the endpoint, General mode, the prefilled box. Screenshots only; the journey proper is chat-journey.spec.ts.
 *  Env: W4_TEAM_ID (skips the league lookup). */

test.describe.configure({ mode: "serial" });
const NAME = "w4smoke";
let userId: string | null = null;
let teamId = Number(process.env.W4_TEAM_ID ?? 0);

test.beforeAll(async () => {
  for (const id of await findTestUsers(NAME)) await deleteUser(id);
  userId = (await createTestUser(NAME)).id;
  if (!teamId) {
    const league = await fplGet<{ standings: { results: Standing[] } }>("leagues-classic/314/standings/?page_standings=1");
    teamId = league.standings.results[0].entry;
    console.log(`[W4 smoke] team ${mask(teamId)} from leagues-classic/314 page 1`);
  }
});
test.afterAll(async () => {
  if (userId) await deleteUser(userId);
  for (const id of await findTestUsers(NAME)) await deleteUser(id);
});

test("smoke: team chat empty state, card, general mode", async ({ page }) => {
  test.setTimeout(240_000);
  await signIn(page, `${NAME}+clerk_test@example.com`);
  await addTeamOnHome(page, teamId, "choice");
  await page.locator(`[data-testid="team-card"][data-team-id="${teamId}"] [data-testid="ask-team"]`).click();
  await page.waitForURL(`**/chat?team=${teamId}`);
  const chat = page.locator('[data-testid="chat"][data-ready="true"]:visible');
  await expect(chat).toBeVisible({ timeout: 30_000 });
  await expect(vis(page, "empty-team")).toHaveAttribute("data-ready", "true", { timeout: 30_000 });
  await expect(vis(page, "team-card")).toBeVisible({ timeout: 30_000 });
  await shot(page, "smoke_team_empty");
  const card = await apiCall(page, "get", `/me/teams/${teamId}/card`);
  console.log(`[W4 smoke] card ${card.status} players ${(card.body.players as unknown[])?.length} live ${card.body.fpl_live} next_gw ${card.body.next_gw}`);
  expect(card.status).toBe(200);
  await expect(page.locator('[data-testid="token"]:visible')).toHaveCount(15);
  await page.locator('[data-testid="token"]:visible').nth(3).hover();
  await page.waitForTimeout(300);
  await shot(page, "smoke_team_hover");
  await vis(page, "empty-chip").first().click();
  await expect(vis(page, "chat-input")).not.toHaveValue("");
  await shot(page, "smoke_team_chip_filled");
  await page.goto("/chat?q=Who%E2%80%99s%20in%20form%20right%20now%3F");
  await expect(page.locator('[data-testid="chat"][data-context="general"]:visible')).toBeVisible({ timeout: 30_000 });
  await expect(vis(page, "from-home-tag")).toBeVisible();
  await shot(page, "smoke_general_prefilled");
  const counts = await page.request.get(`${API}/__w4/counts`);
  console.log(`[W4 smoke] backend FPL requests so far: ${JSON.stringify(await counts.json())}`);
});
