import { expect, test, type BrowserContext, type Page } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import fs from "node:fs";
import path from "node:path";
import { acquireUser, releaseUser, userName } from "./clerk-users";
import { API, signIn } from "./w4";

/** Prompt W11 (2026-11-12): the draft team on the website, desktop 1440x900 + phone 390x844, against the brief's acceptance
 *  checklist. SEEDED: every API call the pages make is a route mock (me, deadlines, teams, threads, the draft and its routes,
 *  messages, POST /chat answers) -- no agent turn, no FPL request; the real turns are the Part 3 eval. One Clerk test user.
 *   cp2  the checkpoint-2 screenshots: chat in draft mode (the opening message + chips, a pending change preview, "Saved to
 *        your draft.") and the guide (desktop dialog / phone sheet)
 *   home new user (3 ways in, Build -> building -> the chat), returning (the pill, also at 3 of 3), with a draft (3rd column /
 *        slim Add row / full-width row, "· 1 draft", the pill gone, "Open your draft"), the Add team dialog's link, the
 *        card's actions (guide + Copy list, Rebuild confirm, Delete confirm), building failed + Try again
 *   chat draft mode: tag, banner, card (no chips row, Rebuild, footer), chips (guide chip sends nothing; used chips never
 *        shown; the answer row after the reveal), the draft value line, Saved to your draft + the card reloads, over budget,
 *        newer predictions, Rebuild from the card -> the system line; DRAFT tags in Recent and Past chats
 *   a11y axe 0 serious / critical on /home and /chat with a draft; reduced motion (all dots, no spin); keyboard only. */

test.describe.configure({ mode: "serial" });
const NAME = userName("w11draft");
const SHOTS = process.env.W11_SHOTS ?? path.join("C:", "dev", "fpl-backups", "w11_draft_team_files");
const DRAFT_TID = "w11-draft-thread";
const NEW_DRAFT_TID = "w11-new-draft-thread";
let userId: string | null = null;
let context: BrowserContext;
let page: Page;
const errors: string[] = [];
const notes: string[] = [];
const note = (s: string) => {
  notes.push(s);
  console.log(`[W11] ${s}`);
};

// ---- seed data ------------------------------------------------------------------------------------------------------------
type P = ReturnType<typeof pl>;
const pl = (slot: number, id: number, short: string, full: string, club: string, position: string, price: number, pts: number, role: "C" | "VC" | null = null) => ({
  slot, id, short_name: short, full_name: full, club, position, price, form: 5.2, role, next: { opp: "FUL", home: true, n: 1 }, flag: null, pred: { points: pts, source: "ours" }, in_squad: true,
});
const BASE_PLAYERS: P[] = [
  pl(1, 1, "Raya", "David Raya", "ARS", "GK", 5.0, 4.8),
  pl(2, 2, "Gabriel", "Gabriel dos Santos Magalhães", "ARS", "DEF", 5.8, 4.6, "VC"),
  pl(3, 3, "Van Dijk", "Virgil van Dijk", "LIV", "DEF", 5.5, 3.9),
  pl(4, 4, "Muñoz", "Daniel Muñoz", "CRY", "DEF", 4.5, 3.5),
  pl(5, 5, "Gvardiol", "Joško Gvardiol", "MCI", "DEF", 5.0, 3.7),
  pl(6, 6, "Salah", "Mohamed Salah", "LIV", "MID", 12.5, 7.4),
  pl(7, 7, "Palmer", "Cole Palmer", "CHE", "MID", 9.5, 6.1),
  pl(8, 8, "Saka", "Bukayo Saka", "ARS", "MID", 9.0, 5.8),
  pl(9, 9, "Rogers", "Morgan Rogers", "AVL", "MID", 5.5, 4.4),
  pl(10, 10, "Haaland", "Erling Haaland", "MCI", "FWD", 14.0, 7.9, "C"),
  pl(11, 11, "Wood", "Chris Wood", "NFO", "FWD", 6.0, 4.2),
  pl(12, 12, "Sels", "Matz Sels", "NFO", "GK", 4.0, 3.3),
  pl(13, 13, "Lewis", "Rico Lewis", "MCI", "DEF", 4.3, 2.4),
  pl(14, 14, "Ndiaye", "Iliman Ndiaye", "EVE", "MID", 4.5, 3.1),
  pl(15, 15, "Welbeck", "Danny Welbeck", "BHA", "FWD", 4.5, 3.0),
];
const MYKO = pl(13, 16, "Mykolenko", "Vitalii Mykolenko", "EVE", "DEF", 4.6, 2.9);
type Draft = Record<string, unknown> & { players: P[]; version_id: number };
function draftCard(over: Partial<Draft> = {}): Draft {
  return {
    version_id: 800000001, formation: "4-4-2", captain: { id: 10, short_name: "Haaland", full_name: "Erling Haaland" }, vice: { id: 2, short_name: "Gabriel", full_name: "Gabriel dos Santos Magalhães" },
    predicted_xi_points: 64.2, predictions_gw: 11, predictions_updated_at: "2026-11-12T11:01:48.000Z", value: 99.6, budget: 100.0, left: 0.4, over: 0,
    built_at: "2026-11-12T15:00:00.000Z", built_from_predictions_at: "2026-11-12 11:01:48+00:00", built_from_run_id: 73, newer_predictions: false, n_changes: 0,
    updated_at: "2026-11-12T15:00:00.000Z", thread_id: DRAFT_TID, thread_ids: [DRAFT_TID], next_gw: 11, next_deadline: "2026-11-21T11:00:00Z", fpl_live: true,
    players: BASE_PLAYERS.map((p) => ({ ...p })), ...over,
  };
}
const OPENING = "Here's your starting 15, built from our predictions. Does it sound good to you? Suggest any changes you'd like, or ask me why I picked a player.";
const teamRow = (id: number, name: string) => ({ fpl_team_id: id, label: null, is_active: false, last_imported_gw: 10, entry_name: name, manager_name: "Test Manager", total_points: 825, overall_rank: 1200, last_gw: 10, last_gw_points: 62, updated_after_gw: 10, summary_updated_at: "2026-11-12T12:00:00Z", last_used_at: "2026-11-12T12:00:00Z", created_at: "2026-11-12T11:00:00Z", last_imported_at: "2026-11-12T11:00:00Z" });
const draftRow = (title: string) => ({ thread_id: DRAFT_TID, created_at: "2026-11-12T15:00:00Z", last_active: new Date(Date.now() - 3600_000).toISOString(), is_default: false, title, team_label: null, fpl_team_id: null, team_name: null, updated_at: new Date(Date.now() - 3600_000).toISOString(), is_draft: true });
const PREVIEW = {
  gw: 11, expires_at: new Date(Date.now() + 25 * 60_000).toISOString(),
  changes: [{ type: "transfer", out: BASE_PLAYERS[12], in: { ...MYKO, in_squad: false }, slot: 13 }],
  impact: { pts_delta: null, pts_horizon_gws: null, bank_after: null, ft_before: null, ft_after: null, hit_pts: null, value_before: 99.6, value_after: 99.9, left_after: 0.1, over_after: 0 },
  draft: true, kind: "change",
};

type State = { teams: number; threads: unknown[]; draft: Draft | null; messages: unknown[]; buildFails: number; answers: { text: string; preview?: unknown; applied?: unknown; after?: () => void }[]; chatBodies: string[]; deletes: number; rebuilds: number; builds: number };
const S: State = { teams: 0, threads: [], draft: null, messages: [], buildFails: 0, answers: [], chatBodies: [], deletes: 0, rebuilds: 0, builds: 0 };
const esc = (s: string) => s.replace(/[.*+?^${}()|[\]\\/]/g, "\\$&");

async function seed(p: Page) {
  await p.unrouteAll({ behavior: "ignoreErrors" });
  await p.route(`${API}/guest/status`, (r) => r.fulfill({ json: { enabled: false, idle_minutes: 30, cap_usd: 0.25, leave_grace_seconds: 90 } }));
  await p.route(`${API}/me`, (r) => (r.request().method() === "GET" ? r.fulfill({ json: { user_id: 10050, is_admin: false, is_owner: false, daily_cap_usd: 1, spent_today_usd: 0, active_team: null, is_guest: false, guest: null } }) : r.fallback()));
  await p.route(`${API}/deadlines`, (r) => r.fulfill({ json: { events: [{ gw: 11, deadline_time: "2026-11-21T11:00:00Z", finished: false }, { gw: 12, deadline_time: "2026-11-28T18:30:00Z", finished: false }], fetched_at: new Date().toISOString() } }));
  await p.route(`${API}/me/teams`, (r) => r.fulfill({ json: [teamRow(4679878, "W11 Test XI"), teamRow(4679879, "W11 Second XI"), teamRow(4679880, "W11 Third XI")].slice(0, S.teams) }));
  await p.route(`${API}/threads`, async (r) => {
    if (r.request().method() === "GET") return r.fulfill({ json: S.threads });
    const body = r.request().postDataJSON?.() as { draft?: boolean } | null;
    return r.fulfill({ json: body?.draft ? { thread_id: NEW_DRAFT_TID, draft: true } : { thread_id: "w11-plain" } });
  });
  await p.route(new RegExp(`^${esc(API)}/threads/([^/?]+)/messages$`), (r) => {
    const id = decodeURIComponent(r.request().url().split("/threads/")[1].split("/")[0]);
    return r.fulfill({ json: id === DRAFT_TID ? S.messages : [] });
  });
  await p.route(`${API}/me/draft`, async (r) => {
    const m = r.request().method();
    if (m === "GET") return r.fulfill({ json: { draft: S.draft } });
    if (m === "DELETE") {
      S.deletes += 1;
      S.draft = null;
      S.threads = (S.threads as { is_draft?: boolean }[]).filter((t) => !t.is_draft);
      return r.fulfill({ json: { deleted: true, removed_chats: 1, removed_previews: 0 } });
    }
    S.builds += 1;
    await new Promise((res) => setTimeout(res, 300));
    if (S.buildFails > 0) {
      S.buildFails -= 1;
      return r.fulfill({ status: 503, json: { detail: "Couldn't build your draft. Nothing was saved -- please try again.", error_kind: "draft_failed" } });
    }
    const existing = !!S.draft;
    if (!S.draft) {
      S.draft = draftCard();
      S.messages = [{ role: "assistant", text: OPENING, at: null, message_id: null, sources: [], squad_preview: null, squad_applied: null, feedback: null, kind: "draft_opening" }];
    }
    return r.fulfill({ json: { draft: S.draft, existing, thread_id: existing ? S.draft.thread_id : DRAFT_TID } });
  });
  await p.route(`${API}/me/draft/rebuild`, async (r) => {
    S.rebuilds += 1;
    await new Promise((res) => setTimeout(res, 200));
    S.draft = draftCard({ version_id: (S.draft?.version_id ?? 800000001) + 1 });
    return r.fulfill({ json: { draft: S.draft } });
  });
  await p.route(new RegExp(`^${esc(API)}/messages/[^/]+/feedback$`), (r) => r.fulfill({ json: { ok: true } }));
  await p.route(`${API}/chat`, async (r) => {
    const body = r.request().postDataJSON() as { message: string; thread_id?: string };
    S.chatBodies.push(body.message);
    const a = S.answers.shift() ?? { text: "A reply. Does that sound good? Any other changes?" };
    await new Promise((res) => setTimeout(res, 600));
    a.after?.();
    await r.fulfill({ json: { answer: a.text, thread_id: body.thread_id ?? NEW_DRAFT_TID, message_id: `w11-msg-${S.chatBodies.length}`, sources: [], squad_preview: a.preview ?? null, squad_applied: a.applied ?? null } }).catch(() => {});
  });
}

const vp = (p: Page) => p.viewportSize()!;
const shot = async (p: Page, name: string) => {
  fs.mkdirSync(SHOTS, { recursive: true });
  const v = vp(p);
  await p.screenshot({ path: path.join(SHOTS, `${name}_${v.width}x${v.height}.png`) });
};
const vis = (p: Page, id: string) => p.locator(`[data-testid="${id}"]:visible`);
const phone = () => vp(page).width < 600;
async function openChat(p: Page, href: string) {
  await p.goto(href);
  await expect(p.locator('[data-testid="chat"][data-ready="true"]:visible')).toBeVisible({ timeout: 30_000 });
}
async function waitTyped(p: Page) {
  await expect(p.locator('[data-testid="assistant-message"][data-revealing="true"]:visible')).toHaveCount(0, { timeout: 15_000 });
}
function reset(over: Partial<State> = {}) {
  Object.assign(S, { teams: 0, threads: [], draft: null, messages: [], buildFails: 0, answers: [], chatBodies: [], deletes: 0, rebuilds: 0, builds: 0 }, over);
}
function withDraft(title?: string) {
  S.draft = draftCard();
  S.messages = [{ role: "assistant", text: OPENING, at: null, message_id: null, sources: [], squad_preview: null, squad_applied: null, feedback: null, kind: "draft_opening" }];
  if (title) S.threads = [draftRow(title)];
}

test.beforeAll(async ({ browser }, info) => {
  userId = await acquireUser(NAME);
  const use = info.project.use;
  context = await browser.newContext({ viewport: use.viewport, isMobile: use.isMobile, hasTouch: use.hasTouch, baseURL: use.baseURL, permissions: ["clipboard-read", "clipboard-write"] });
  page = await context.newPage();
  page.on("pageerror", (e) => errors.push(String(e).slice(0, 200)));
  await seed(page);
  await signIn(page, `${NAME}+clerk_test@example.com`);
});
test.afterAll(async ({}, info) => {
  note(`${info.project.name}: page errors ${errors.length}${errors.length ? ` -- ${errors.slice(0, 3).join(" | ")}` : ""}`);
  fs.mkdirSync(SHOTS, { recursive: true });
  fs.appendFileSync(path.join(SHOTS, "notes.txt"), notes.map((n) => `${new Date().toISOString()} ${n}\n`).join(""));
  await context?.close();
  await releaseUser(NAME, userId);
});

// ---- cp2: the checkpoint-2 screenshots -------------------------------------------------------------------------------------
test("cp2: chat in draft mode -- the opening message + chips, a pending change, Saved to your draft; the guide", async () => {
  reset();
  withDraft();
  await openChat(page, `/chat/${DRAFT_TID}`);
  if (phone()) await expect(vis(page, "team-bar").locator('[data-testid="draft-badge"]')).toHaveText("DRAFT"); // the phone has no title row
  else await expect(vis(page, "chat-tag")).toHaveText("DRAFT");
  await expect(vis(page, "draft-banner")).toContainText("Not in FPL yet");
  await expect(vis(page, "opening-chips").locator('[data-testid="draft-chip"]')).toHaveCount(4);
  if (phone()) await expect(vis(page, "team-bar-line")).toHaveText("DRAFT · 4-4-2 · C HAALAND");
  else await expect(vis(page, "card-line")).toHaveText("4-4-2 · £99.6m OF £100.0M · £0.4m LEFT");
  await page.waitForTimeout(400);
  await shot(page, "cp2_chat_opening");
  // a pending change
  S.answers.push({ text: "Here's the swap: **Mykolenko** (EVE, £4.6m) in for **Lewis** (MCI, £4.3m). It takes the draft to £99.9m with £0.1m left. Say yes to save it.", preview: PREVIEW });
  await vis(page, "chat-input").fill("Swap Lewis for Mykolenko");
  await page.keyboard.press("Enter");
  await expect(vis(page, "preview-card")).toBeVisible({ timeout: 15_000 });
  await waitTyped(page);
  await expect(vis(page, "impact-line")).toHaveText("Value £99.6m → £99.9m · £0.1m left");
  await page.waitForTimeout(400);
  await shot(page, "cp2_chat_preview_pending");
  if (phone()) {
    await vis(page, "team-bar").click(); // the panel opened itself for the preview: close it for the Yes
  }
  // Yes -> Saved to your draft, the card reloads with the change
  S.answers.push({
    text: "Done — **Mykolenko** is in for Lewis. Does that sound good? Any other changes?",
    applied: { gw: 11, version_id: 800000002, draft: true, kind: "change" },
    after: () => {
      S.draft = draftCard({ version_id: 800000002, value: 99.9, left: 0.1, n_changes: 1, players: BASE_PLAYERS.map((p) => (p.id === 13 ? { ...MYKO } : { ...p })) });
    },
  });
  await vis(page, "preview-yes").click();
  await expect(vis(page, "saved-block")).toHaveText("Saved to your draft.", { timeout: 15_000 });
  await waitTyped(page);
  if (!phone()) await expect(vis(page, "card-line")).toHaveText("4-4-2 · £99.9m OF £100.0M · £0.1m LEFT", { timeout: 10_000 });
  else {
    await vis(page, "team-bar").click();
    await expect(vis(page, "panel-line")).toContainText("£0.1m LEFT", { timeout: 10_000 });
  }
  await page.waitForTimeout(400);
  await shot(page, "cp2_chat_saved");
  if (phone()) await vis(page, "team-bar").click();
  // the guide
  await vis(page, "draft-banner-guide").click();
  const guide = phone() ? vis(page, "guide-sheet") : vis(page, "guide-dialog");
  await expect(guide).toBeVisible();
  await expect(guide.locator('[data-testid="guide-row"]')).toHaveCount(15);
  await page.waitForTimeout(500);
  await shot(page, phone() ? "cp2_guide_sheet" : "cp2_guide_dialog");
  await page.evaluate(() => document.querySelector(".dr-guide-body")?.scrollTo({ top: 99999 }));
  await expect(guide.locator('[data-testid="guide-steps"] li')).toHaveCount(5);
  await page.waitForTimeout(300);
  await shot(page, phone() ? "cp2_guide_sheet_steps" : "cp2_guide_dialog_steps");
  await page.keyboard.press("Escape");
  await expect(guide).toHaveCount(0);
});
