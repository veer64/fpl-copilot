import { expect, test, type Page } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";
import { DB_PREFIX, addTeamOnHome, apiCall, py } from "./w4";

/** Prompt X1 (13 Nov 2026): a squad change is saved ONLY by the user's explicit Yes to THAT preview. On 13 Nov the owner's
 *  "No" to two draft previews was read by the model as a yes and both swaps were saved. Against the REAL laptop backend
 *  (clerk mode on :8010 with GUEST_MODE=on, the laptop database) and the production build on :3002, desktop only, one guest
 *  per test (made and deleted by the feature):
 *   D  draft: build -> "Make <X> my captain." (a real model turn: the preview) -> click No -> "No change made.", the draft's
 *      version, the pitch's captain and the card unchanged -> ask again -> click Yes -> saved: a new version, X wears the armband
 *   T  team: add an FPL team -> its chat -> the same with the team's squad (squad_versions under the team's key)
 *  Costs: four agent turns (the previews); the Yes / No clicks are answered by code ($0). Env: X1_TEAM (default 895045). */

test.describe.configure({ mode: "serial" });
const TEAM = Number(process.env.X1_TEAM ?? 895045);
const SHOTS = process.env.X1_SHOTS ?? path.join("C:", "dev", "fpl-backups", "x1_no_applied_files", "shots");
const vis = (p: Page, id: string) => p.locator(`[data-testid="${id}"]:visible`);
const shot = async (p: Page, name: string) => {
  fs.mkdirSync(SHOTS, { recursive: true });
  await p.screenshot({ path: path.join(SHOTS, `x1_${name}_1440x900.png`) });
};
const last = (out: string) => JSON.parse(out.trim().split("\n").pop()!);

/** The squad a case works on: the draft (user_drafts) or the team's active version; its captain and an XI MID/FWD with a
 *  unique web name (not captain or vice) to make captain. */
function squadState(uid: number, kind: "draft" | "team"): { version: number; n: number; captain: string; pick: string } {
  return last(
    py(`${DB_PREFIX}
import json, team_card
boot = team_card._local_snapshot()
web = {int(e["id"]): e["web_name"] for e in boot["elements"]}
names = [e["web_name"] for e in boot["elements"]]
if "${kind}" == "draft":
    cur.execute("SELECT version_id, squad_json, n_changes FROM user_drafts WHERE user_id = %s", (${uid},))
    v, doc, n = cur.fetchone()
else:
    cur.execute("SELECT squad_key FROM user_fpl_teams WHERE user_id = %s AND fpl_team_id = %s", (${uid}, ${TEAM}))
    key = cur.fetchone()[0]
    cur.execute("SELECT version_id, squad_json FROM squad_versions WHERE user_id = %s AND is_active", (key,))
    v, doc = cur.fetchone()
    cur.execute("SELECT count(*) FROM squad_versions WHERE user_id = %s", (key,))
    n = cur.fetchone()[0]
ps = doc["players"]
cap = next(p for p in ps if str(p["role"]).upper() == "CAPTAIN")
pick = next(p for p in ps if p["role"] == "start" and p["position"] in ("MID", "FWD") and names.count(web[int(p["element"])]) == 1)
print(json.dumps({"version": v, "n": n, "captain": web[int(cap["element"])], "pick": web[int(pick["element"])]}))`),
  );
}

/** The pitch token that wears the captain's armband (its visible name). */
async function pitchCaptain(page: Page) {
  const tok = page.locator('[data-testid="token"]:visible', { has: page.locator('[data-testid="badge-c"]') }).first();
  await expect(tok).toBeVisible({ timeout: 30_000 });
  return (await tok.innerText()).replace(/\s+/g, " ").trim();
}

async function startGuest(page: Page) {
  await page.goto("/login");
  await page.locator('[data-testid="skip-intro"]:visible').first().click().catch(() => {});
  const btn = vis(page, "continue-as-guest");
  await expect(btn).toHaveAttribute("data-guest-mode", "on", { timeout: 30_000 });
  await btn.click();
  await page.waitForURL("**/home", { timeout: 60_000 });
  const me = (await apiCall(page, "get", "/me")).body as { user_id: number; is_guest: boolean };
  expect(me.is_guest).toBe(true);
  expect(me.user_id).toBeGreaterThanOrEqual(10001);
  return me.user_id;
}

async function endGuest(page: Page, uid: number) {
  await vis(page, "account-menu").click();
  await vis(page, "end-guest-session").click();
  await page.locator('[data-testid="confirm-delete"]:visible').click();
  await page.waitForURL(/\/login\?reason=guest_ended/, { timeout: 60_000 });
  const left = last(
    py(`${DB_PREFIX}
import json
cur.execute("SELECT (SELECT count(*) FROM app_users WHERE user_id = %s) + (SELECT count(*) FROM user_drafts WHERE user_id = %s) + (SELECT count(*) FROM user_fpl_teams WHERE user_id = %s) + (SELECT count(*) FROM chat_threads WHERE user_id = %s)", (${uid}, ${uid}, ${uid}, ${uid}))
print(json.dumps({"left": cur.fetchone()[0]}))`),
  );
  expect(left).toEqual({ left: 0 });
}

/** Ask for the captain change, wait for the preview card, answer it with the button; returns the answer's text. */
async function previewThenClick(page: Page, pick: string, button: "preview-no" | "preview-yes") {
  const before = await page.locator('[data-testid="assistant-message"]').count();
  await vis(page, "chat-input").fill(`Make ${pick} my captain.`);
  await page.keyboard.press("Enter");
  const card = page.locator('[data-testid="preview-card"]:visible').last();
  await expect(card).toBeVisible({ timeout: 120_000 });
  await expect(card.locator(`[data-testid="${button}"]`)).toBeVisible({ timeout: 30_000 });
  await card.locator(`[data-testid="${button}"]`).click();
  const answers = page.locator('[data-testid="assistant-message"]:visible');
  await expect(answers).toHaveCount(before + 2, { timeout: 60_000 }); // the preview + the button's answer
  await expect(answers.last()).toHaveAttribute("data-revealing", "false", { timeout: 15_000 });
  return (await answers.last().innerText()).trim();
}

async function checkNoThenYes(page: Page, uid: number, kind: "draft" | "team") {
  const s0 = squadState(uid, kind);
  const cap0 = await pitchCaptain(page);
  console.log(`[X1] ${kind}: user ${uid} version ${s0.version} (${s0.n}) captain ${s0.captain}; asking for ${s0.pick}; pitch captain "${cap0}"`);
  expect(cap0).toContain(s0.captain);
  const no = await previewThenClick(page, s0.pick, "preview-no");
  expect(no).toBe("No change made.");
  await page.waitForTimeout(1500); // a reload, if anything had been saved, would land here
  const s1 = squadState(uid, kind);
  expect({ version: s1.version, n: s1.n, captain: s1.captain }).toEqual({ version: s0.version, n: s0.n, captain: s0.captain });
  expect(await pitchCaptain(page)).toBe(cap0);
  await expect(vis(page, "saved-block")).toHaveCount(0);
  await shot(page, `${kind}_after_no`);
  const yes = await previewThenClick(page, s0.pick, "preview-yes");
  expect(yes).toContain(`Done — saved to your ${kind === "draft" ? "draft" : "squad"}.`);
  const s2 = squadState(uid, kind);
  expect(s2.version).not.toBe(s0.version);
  expect(s2.captain).toBe(s0.pick);
  await expect.poll(() => pitchCaptain(page), { timeout: 30_000 }).toContain(s0.pick);
  await expect(vis(page, "saved-block")).toHaveCount(1);
  await shot(page, `${kind}_after_yes`);
  console.log(`[X1] ${kind}: No -> "${no}" (unchanged); Yes -> "${yes.slice(0, 80)}" version ${s0.version} -> ${s2.version}`);
}

test("D: draft -- No leaves the draft, the pitch and the card as they were; Yes saves that change", async ({ page }, info) => {
  test.skip(info.project.name !== "desktop", "desktop only");
  test.setTimeout(420_000);
  const uid = await startGuest(page);
  await expect(vis(page, "choice-draft")).toHaveAttribute("data-state", "build", { timeout: 30_000 });
  await vis(page, "build-draft").click();
  await page.waitForURL(/\/chat\/th_/, { timeout: 60_000 });
  await expect(vis(page, "opening-chips")).toBeVisible({ timeout: 30_000 });
  await checkNoThenYes(page, uid, "draft");
  await endGuest(page, uid);
});

test("T: team -- No leaves the squad, the pitch and the card as they were; Yes saves that change", async ({ page }, info) => {
  test.skip(info.project.name !== "desktop", "desktop only");
  test.setTimeout(420_000);
  const uid = await startGuest(page);
  const via = (await page.getByTestId("choice-add-team").count()) ? "choice" : "card";
  await addTeamOnHome(page, TEAM, via);
  await page.locator(`[data-testid="team-card"][data-team-id="${TEAM}"] [data-testid="ask-team"]`).click();
  await page.waitForURL(/\/chat\?team=/, { timeout: 60_000 });
  await expect(vis(page, "team-card")).toBeVisible({ timeout: 60_000 });
  await checkNoThenYes(page, uid, "team");
  await endGuest(page, uid);
});
