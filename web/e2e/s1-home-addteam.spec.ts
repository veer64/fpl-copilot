import { expect, test, type Page } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";
import { createTestUser, deleteUser, findTestUsers } from "./clerk-users";
import { API, signIn } from "./w4";

/** Prompt S1 (2026-11-12): on the returning Home the add-team card's title "Add team" and its line "Paste your FPL team
 *  ID / or the link to your team" ran together on one line at desktop widths (the text wrapper was an inline span; only
 *  the <=980px layout made it a column). Seeded, no FPL request, no agent turn: GET /me/teams and GET /threads are route
 *  mocks (the real :8010 backend answers /me and /deadlines). Two returning states -- one team (the card beside it) and
 *  no team but a chat -- at 1440x900, 1920x1080 and 390x844: the title sits wholly above the line, neither overlaps the
 *  plus icon or the slots label, nothing leaves the card, and the phone (which hides the <br>) reads "ID or", not "IDor". Screenshots go to S1_SHOTS with the S1_PHASE prefix
 *  (before / after). Clerk test user s1home (deleted at the end). */

test.describe.configure({ mode: "serial" });
const NAME = "s1home";
const SHOTS = process.env.S1_SHOTS ?? path.join("C:", "dev", "fpl-backups", "s1_small_fixes_files");
const PHASE = process.env.S1_PHASE ?? "after";
const TEAM = 895045;
let userId: string | null = null;

const teamRow = {
  fpl_team_id: TEAM, label: null, is_active: true, last_imported_gw: 10, entry_name: "S1 Test XI", manager_name: "Test Manager",
  total_points: 825, overall_rank: 1, last_gw: 10, last_gw_points: 82, updated_after_gw: 10,
  summary_updated_at: "2026-11-12T12:00:00Z", last_used_at: "2026-11-12T12:00:00Z", created_at: "2026-11-12T11:00:00Z",
  last_imported_at: "2026-11-12T11:00:00Z",
};
const threadRow = {
  thread_id: "s1-thread", created_at: "2026-11-12T12:00:00Z", last_active: "2026-11-12T12:01:00Z", is_default: false,
  title: "Who are the three best captain picks this gameweek?", team_label: null, fpl_team_id: null, team_name: null,
  updated_at: "2026-11-12T12:01:00Z",
};
const STATES = { "one-team": { teams: [teamRow], threads: [threadRow] }, "no-team": { teams: [], threads: [threadRow] } } as const;
const VIEWPORTS = [
  { width: 1440, height: 900 },
  { width: 1920, height: 1080 },
  { width: 390, height: 844 },
];

type Box = { x: number; y: number; w: number; h: number };
type Geo = { card: Box; plus: Box; title: Box; sub: Box; slots: Box; subLines: number; subText: string };

async function geometry(page: Page): Promise<Geo> {
  return page.locator('[data-testid="add-team-card"]:visible').first().evaluate((card) => {
    const b = (el: Element | null): Box => {
      const r = (el as HTMLElement).getBoundingClientRect();
      return { x: r.left, y: r.top, w: r.width, h: r.height };
    };
    const sub = card.querySelector(".hm-add-sub") as HTMLElement;
    const lineH = parseFloat(getComputedStyle(sub).lineHeight) || 19;
    return {
      card: b(card), plus: b(card.querySelector(".hm-add-plus")), title: b(card.querySelector(".hm-add-title")), sub: b(sub),
      slots: b(card.querySelector(".hm-add-slots")), subLines: Math.round(sub.getBoundingClientRect().height / lineH),
      subText: sub.innerText.replace(/\s+/g, " ").trim(),
    };
  });
}
const overlaps = (a: Box, b: Box) => a.x < b.x + b.w - 0.5 && b.x < a.x + a.w - 0.5 && a.y < b.y + b.h - 0.5 && b.y < a.y + a.h - 0.5;
const inside = (a: Box, c: Box) => a.x >= c.x - 0.5 && a.y >= c.y - 0.5 && a.x + a.w <= c.x + c.w + 0.5 && a.y + a.h <= c.y + c.h + 0.5;

test.beforeAll(async () => {
  for (const id of await findTestUsers(NAME)) await deleteUser(id);
  userId = (await createTestUser(NAME)).id;
});
test.afterAll(async () => {
  if (userId) await deleteUser(userId);
  for (const id of await findTestUsers(NAME)) await deleteUser(id);
});

test("returning Home: the add-team card's title and its line never share a line or overlap", async ({ page }) => {
  test.setTimeout(240_000);
  fs.mkdirSync(SHOTS, { recursive: true });
  let state: keyof typeof STATES = "one-team";
  await page.route(`${API}/me/teams`, (r) => (r.request().method() === "GET" ? r.fulfill({ json: STATES[state].teams }) : r.fallback()));
  await page.route(`${API}/threads`, (r) => (r.request().method() === "GET" ? r.fulfill({ json: STATES[state].threads }) : r.fallback()));
  await signIn(page, `${NAME}+clerk_test@example.com`);
  const report: Record<string, Geo> = {};
  for (const s of Object.keys(STATES) as (keyof typeof STATES)[]) {
    state = s;
    for (const vp of VIEWPORTS) {
      await page.setViewportSize(vp);
      await page.goto("/home");
      await expect(page.locator('[data-testid="home"][data-state="returning"]:visible')).toBeVisible({ timeout: 60_000 });
      const card = page.locator('[data-testid="add-team-card"]:visible').first();
      await expect(card).toBeVisible();
      await card.scrollIntoViewIfNeeded();
      await page.waitForTimeout(400);
      const tag = `${PHASE}_${s}_${vp.width}x${vp.height}`;
      await page.screenshot({ path: path.join(SHOTS, `${tag}.png`) });
      await card.screenshot({ path: path.join(SHOTS, `${tag}_card.png`) });
      const g = await geometry(page);
      report[tag] = g;
      // the title wholly above its line (its own line), the line on two lines on desktop, one on the phone
      expect.soft(g.title.y + g.title.h, `${tag}: title bottom above the line's top`).toBeLessThanOrEqual(g.sub.y + 0.5);
      expect.soft(overlaps(g.title, g.sub), `${tag}: title overlaps the line`).toBe(false);
      expect.soft(overlaps(g.plus, g.title) || overlaps(g.plus, g.sub), `${tag}: the plus icon overlaps the text`).toBe(false);
      expect.soft(overlaps(g.slots, g.title) || overlaps(g.slots, g.sub), `${tag}: the slots label overlaps the text`).toBe(false);
      for (const [k, box] of Object.entries({ plus: g.plus, title: g.title, sub: g.sub, slots: g.slots })) {
        expect.soft(inside(box, g.card), `${tag}: ${k} leaves the card`).toBe(true);
      }
      // the rendered words: the phone hides the <br>, which must not glue "ID" to "or" ("IDor" before S1)
      expect.soft(g.subText, `${tag}: the line's words`).toBe("Paste your FPL team ID or the link to your team");
      if (vp.width > 980) expect.soft(g.subLines, `${tag}: the line breaks after "ID" on a desktop`).toBe(2);
    }
  }
  fs.writeFileSync(path.join(SHOTS, `${PHASE}_geometry.json`), JSON.stringify(report, null, 1));
});
