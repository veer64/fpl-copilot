import { expect, test, type BrowserContext, type Page } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import fs from "node:fs";
import path from "node:path";
import { acquireUser, releaseUser, userName } from "./clerk-users";
import { API, signIn } from "./w4";
// @ts-expect-error -- a plain .mjs module shared with scripts/contrast_public.mjs (W5b)
import { sweepPage } from "../scripts/lib/sweep.mjs";

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
// each club's GW11 fixture from the project's fixture calendar (data/history/forward_skeleton_2026_27.parquet, read 12 Nov):
// the seeded tokens show what the real card shows for these clubs (the real card reads FPL's fixtures for the same week)
const GW11: Record<string, { opp: string; home: boolean }> = {
  ARS: { opp: "NEW", home: false }, LIV: { opp: "MUN", home: true }, CRY: { opp: "COV", home: false }, MCI: { opp: "FUL", home: true },
  CHE: { opp: "LEE", home: true }, AVL: { opp: "SUN", home: true }, NFO: { opp: "BOU", home: false }, EVE: { opp: "BRE", home: false }, BHA: { opp: "HUL", home: false },
};
const pl = (slot: number, id: number, short: string, full: string, club: string, position: string, price: number, pts: number, role: "C" | "VC" | null = null) => ({
  slot, id, short_name: short, full_name: full, club, position, price, form: 5.2, role, next: { ...GW11[club], n: 1 }, flag: null, pred: { points: pts, source: "ours" }, in_squad: true,
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
    // the backend lists a draft chat once its first question is sent (W4's rule), titled by that question, is_draft true
    if (body.thread_id === DRAFT_TID && !(S.threads as { thread_id: string }[]).some((t) => t.thread_id === DRAFT_TID)) S.threads = [draftRow(body.message), ...S.threads];
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
  if (phone()) await expect(vis(page, "team-bar-line")).toHaveText("4-4-2 · C HAALAND");
  else await expect(vis(page, "card-line")).toHaveText("4-4-2 · £99.6m / £100.0m · £0.4m LEFT");
  // every token shows its own club's next fixture (Haaland: Man City at home to Fulham; Salah: Liverpool v Man Utd at home)
  if (!phone()) {
    const strips = await page.locator('[data-testid="fixture-strip"]:visible').evaluateAll((els) => els.map((e) => `${e.getAttribute("data-opp")}:${e.getAttribute("data-home")}`));
    const want = BASE_PLAYERS.map((p) => `${GW11[p.club].opp}:${GW11[p.club].home}`);
    expect(strips.sort()).toEqual(want.sort()); // the 15 tokens, each with its own club's GW11 fixture
    note(`fixture strips: ${new Set(strips).size} distinct over ${strips.length} tokens`);
  }
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
  if (!phone()) await expect(vis(page, "card-line")).toHaveText("4-4-2 · £99.9m / £100.0m · £0.1m LEFT", { timeout: 10_000 });
  else {
    await vis(page, "team-bar").click();
    await expect(vis(page, "panel-line")).toContainText("£0.1m LEFT", { timeout: 10_000 });
  }
  // the chat is listed in Past chats with the DRAFT tag once its first question was sent (fix 2)
  if (!phone()) {
    const row = page.locator(`[data-testid="thread-row"][data-thread-id="${DRAFT_TID}"]:visible`);
    await expect(row).toBeVisible({ timeout: 10_000 });
    await expect(row).toContainText("DRAFT");
    await expect(row).toContainText("Swap Lewis for Mykolenko");
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

// ---- home: the entry points (brief section 3) ----------------------------------------------------------------------------
const plainRow = (i: number) => ({ thread_id: `w11-plain-${i}`, created_at: "2026-11-12T10:00:00Z", last_active: `2026-11-12T1${i}:00:00Z`, is_default: false, title: `Who should I captain, question ${i}?`, team_label: null, fpl_team_id: null, team_name: null, updated_at: "2026-11-12T12:00:00Z", is_draft: false });
async function home(p: Page) {
  await p.goto("/home");
  await expect(p.locator('[data-testid="home"]:visible')).not.toHaveAttribute("data-state", "loading", { timeout: 30_000 });
  await p.waitForTimeout(300);
}

test("home new user: three ways in, Build -> the building card -> the chat; then Open your draft", async () => {
  reset();
  await home(page);
  await expect(vis(page, "new-user-choices").locator("section")).toHaveCount(3);
  await expect(vis(page, "greeting")).toContainText("Add your FPL team, build one from our predictions — or just ask a question.");
  const build = vis(page, "choice-draft");
  await expect(build).toHaveAttribute("data-state", "build");
  await expect(build.locator('[data-testid="draft-rules"] .dr-rule')).toHaveText(["£100.0m", "2 GK · 5 DEF · 5 MID · 3 FWD", "Max 3 per club"]);
  await expect(vis(page, "choice-general")).toHaveText("Start a general chat");
  await shot(page, "home_new_user");
  await vis(page, "build-draft").click();
  const bld = vis(page, "draft-building");
  await expect(bld).toBeVisible();
  await expect(bld.locator('[role="status"]')).toContainText("Building your draft…");
  await expect(bld.locator('[data-testid="build-dot"]')).toHaveCount(15);
  await page.waitForTimeout(700);
  await shot(page, "home_building");
  await page.waitForURL(`**/chat/${DRAFT_TID}`, { timeout: 15_000 });
  await expect(vis(page, "opening-chips")).toBeVisible({ timeout: 15_000 });
  note(`build -> chat: builds ${S.builds}`);
  await home(page); // a new user who now has a draft: "Open your draft" replaces Build
  await expect(vis(page, "choice-draft")).toHaveAttribute("data-state", "exists");
  await expect(vis(page, "draft-mini")).toHaveText("4-4-2 · C Haaland · £99.6m of £100.0m · not in FPL yet.");
  await shot(page, "home_new_user_with_draft");
  await vis(page, "open-draft").click();
  await page.waitForURL(`**/chat/${DRAFT_TID}`, { timeout: 15_000 });
});

test("home returning: the Build pill at 2 and at 3 of 3 teams; the Add team dialog's Build link starts the build", async () => {
  reset({ teams: 2, threads: [plainRow(1)] });
  await home(page);
  await expect(vis(page, "build-pill")).toBeVisible();
  await expect(vis(page, "teams-count")).toHaveText("2 of 3 teams");
  await shot(page, "home_pill_2teams");
  S.teams = 3;
  await home(page);
  await expect(vis(page, "build-pill")).toBeVisible(); // a draft never uses a slot
  await expect(vis(page, "teams-count")).toHaveText("3 of 3 teams");
  await shot(page, "home_pill_3teams");
  S.teams = 2;
  await home(page);
  await vis(page, "add-team-card").click();
  const link = vis(page, "add-team-draft-link");
  await expect(link).toHaveAttribute("data-kind", "build");
  await expect(link).toHaveText("Don’t have an FPL team? Build one");
  await shot(page, "home_add_dialog_build_link");
  await link.click();
  await expect(vis(page, "draft-building")).toBeVisible();
  await page.waitForURL(`**/chat/${DRAFT_TID}`, { timeout: 15_000 });
});

test("home with a draft: 3rd column / slim Add row / full-width row, '· 1 draft', no pill, the dialog says Open your draft", async () => {
  reset({ teams: 1, threads: [plainRow(1)] });
  withDraft();
  await home(page);
  const card = vis(page, "draft-card");
  await expect(card).toHaveAttribute("data-layout", "card");
  await expect(card).toHaveAttribute("aria-label", "Your draft team — not in FPL yet");
  await expect(card.locator('[data-testid="draft-summary"]')).toHaveText("4-4-2 · C Haaland · built from our predictions");
  await expect(card.locator('[data-testid="draft-pred"]')).toHaveText("64.2");
  await expect(card.locator('[data-testid="draft-value"]')).toHaveText("£99.6m");
  await expect(card.locator('[data-testid="draft-left"]')).toHaveText("£0.4m");
  await expect(vis(page, "add-team-card")).toBeVisible();
  await expect(vis(page, "build-pill")).toHaveCount(0);
  await expect(vis(page, "teams-count")).toHaveText("1 of 3 teams · 1 draft");
  await shot(page, "home_draft_1team");
  S.teams = 2;
  await home(page);
  await expect(vis(page, "draft-card")).toHaveAttribute("data-layout", "card");
  await expect(vis(page, "add-team-slim")).toBeVisible();
  await expect(vis(page, "add-team-card")).toHaveCount(0);
  await shot(page, "home_draft_2teams");
  await vis(page, "add-team-slim").click();
  await expect(vis(page, "add-team-draft-link")).toHaveAttribute("data-kind", "open");
  await page.keyboard.press("Escape");
  S.teams = 3;
  await home(page);
  await expect(vis(page, "draft-card")).toHaveAttribute("data-layout", "row");
  await expect(vis(page, "teams-count")).toHaveText("3 of 3 teams · 1 draft");
  await expect(vis(page, "teams-full")).toHaveCount(0);
  await shot(page, "home_draft_3teams");
  if (!phone()) {
    const cards = await page.locator('[data-testid="team-card"]:visible').evaluateAll((els) => els.map((e) => e.getBoundingClientRect().bottom));
    const row = await vis(page, "draft-card").boundingBox();
    expect(row!.y).toBeGreaterThan(Math.max(...cards)); // the row sits under the three team cards
    expect(row!.width).toBeGreaterThan(1000); // full width
  }
});

test("home card actions: the guide (Copy list, Add my team ID), Rebuild confirm, Delete confirm; building failed -> Try again", async () => {
  reset({ teams: 2, threads: [plainRow(1), draftRow("Why these players?")] });
  withDraft("Why these players?");
  await home(page);
  await expect(vis(page, "recent-tag-draft")).toHaveText("DRAFT"); // Recent chats: the amber DRAFT tag
  await shot(page, "home_recent_draft_tag");
  // the guide from the card
  await vis(page, "draft-guide").click();
  const guide = phone() ? vis(page, "guide-sheet") : vis(page, "guide-dialog");
  await expect(guide).toBeVisible();
  await vis(page, "guide-copy").click();
  await expect(page.getByText("List copied")).toBeVisible();
  const clip = (await page.evaluate(() => navigator.clipboard.readText())).replace(/\r\n/g, "\n");
  expect(clip.split("\n")).toHaveLength(16);
  expect(clip).toContain("FWD Haaland (Erling Haaland) · MCI · £14.0m · C");
  expect(clip).toContain("GK  Sels (Matz Sels) · NFO · £4.0m · BENCH");
  await vis(page, "guide-add-team").click();
  await expect(phone() ? vis(page, "add-team-sheet") : vis(page, "add-team-dialog")).toBeVisible();
  await page.keyboard.press("Escape");
  // Rebuild: the amber confirm; Keep my draft closes; Rebuild builds and stays on Home
  await vis(page, "draft-rebuild").click();
  const rb = phone() ? vis(page, "rebuild-confirm-sheet") : vis(page, "rebuild-confirm-dialog");
  await expect(rb).toHaveAttribute("role", "alertdialog");
  await expect(rb).toContainText("Rebuild from the best picks?");
  await page.waitForTimeout(400);
  await shot(page, "home_rebuild_confirm");
  await vis(page, "rebuild-keep").click();
  await expect(rb).toHaveCount(0);
  await expect(vis(page, "draft-rebuild")).toBeFocused();
  await vis(page, "draft-rebuild").click();
  await vis(page, "rebuild-confirm").click();
  await expect(vis(page, "draft-building")).toBeVisible();
  await expect(page.getByText("Draft rebuilt from the best picks.")).toBeVisible({ timeout: 10_000 });
  expect(S.rebuilds).toBe(1);
  // Delete: the red confirm names the chats; the card goes and the pill comes back
  await vis(page, "draft-delete").click();
  const del = phone() ? vis(page, "delete-draft-sheet") : vis(page, "delete-draft-dialog");
  await expect(del).toHaveAttribute("role", "alertdialog");
  await expect(del.locator('[data-testid="confirm-title"]')).toHaveText("Delete your draft?");
  await expect(del.locator('[data-testid="confirm-intro"]')).toHaveText("Your 15 players, every change you made and its 1 chat will be removed.");
  await page.waitForTimeout(400);
  await shot(page, "home_delete_confirm");
  await del.locator('[data-testid="confirm-delete"]').click();
  await expect(vis(page, "draft-card")).toHaveCount(0, { timeout: 10_000 });
  await expect(vis(page, "build-pill")).toBeVisible();
  expect(S.deletes).toBe(1);
  // building failed -> Try again
  S.buildFails = 1;
  await vis(page, "build-pill").click();
  const failed = vis(page, "draft-failed");
  await expect(failed).toBeVisible({ timeout: 10_000 });
  await expect(failed).toHaveAttribute("role", "alertdialog");
  await expect(failed).toContainText("Couldn’t build your draft");
  await page.waitForTimeout(400);
  await shot(page, "home_build_failed");
  await vis(page, "draft-failed-retry").click();
  await page.waitForURL(`**/chat/${DRAFT_TID}`, { timeout: 15_000 });
  expect(S.builds).toBe(2);
});

// ---- chat in draft mode: the rest of section 6 ----------------------------------------------------------------------------
test("chat: the guide chip sends nothing; chips send; used chips never return; the spend chip only from £0.5m left", async () => {
  reset();
  withDraft();
  await openChat(page, `/chat/${DRAFT_TID}`);
  const opening = vis(page, "opening-chips");
  await opening.getByText("How do I enter this in FPL?").click();
  await expect(phone() ? vis(page, "guide-sheet") : vis(page, "guide-dialog")).toBeVisible();
  await page.keyboard.press("Escape");
  expect(S.chatBodies).toEqual([]); // the guide chip sent nothing
  S.answers.push({ text: "Each of the 15 is there for his predicted points: **Haaland** 7.9, **Salah** 7.4. Does that sound good?" });
  await opening.getByText("Why these players?").click();
  await expect(vis(page, "answer-chips")).toBeVisible({ timeout: 15_000 });
  expect(S.chatBodies).toEqual(["Why these players?"]);
  const chips = await vis(page, "answer-chips").locator('[data-testid="draft-chip"]').allInnerTexts();
  expect(chips).not.toContain("How would you spend the £0.4m left?"); // £0.4m < £0.5m
  expect(chips).not.toContain("How do I enter this in FPL?"); // the guide was opened from a chip
  expect(chips).toContain("Why Haaland as captain?");
  await vis(page, "answer-chips").getByText("Why Haaland as captain?").click();
  await waitTyped(page);
  const again = await vis(page, "answer-chips").locator('[data-testid="draft-chip"]').allInnerTexts();
  expect(again).not.toContain("Why Haaland as captain?"); // used: never shown again
  // a draft with £1.2m left shows the spend chip
  reset();
  withDraft();
  S.draft = draftCard({ value: 98.8, left: 1.2 });
  await openChat(page, `/chat/${DRAFT_TID}`);
  S.answers.push({ text: "A reply." });
  await vis(page, "opening-chips").getByText("Suggest some changes").click();
  await expect(vis(page, "answer-chips")).toContainText("How would you spend the £1.2m left?", { timeout: 15_000 });
});

test("chat: over £100.0m after price rises (coral), Newer predictions -> the Rebuild confirm -> the system line", async () => {
  reset();
  withDraft();
  S.draft = draftCard({ value: 100.2, left: 0, over: 0.2, newer_predictions: true });
  await openChat(page, `/chat/${DRAFT_TID}`);
  if (phone()) {
    await vis(page, "team-bar").click();
    await expect(vis(page, "panel-line")).toHaveText("4-4-2 · £100.2m / £100.0m · £0.2m OVER");
  } else await expect(vis(page, "card-line")).toHaveText("4-4-2 · £100.2m / £100.0m · £0.2m OVER");
  await expect(page.locator(".ch-card-line b.over:visible, .line b.over:visible").first()).toHaveCSS("color", "rgb(255, 138, 122)");
  await expect(vis(page, "draft-newer")).toBeVisible();
  await shot(page, "chat_over_budget_newer");
  await vis(page, "draft-newer-rebuild").click();
  await vis(page, "rebuild-confirm").click();
  await expect(vis(page, "system-rebuilt")).toHaveText("Draft rebuilt from the best picks.", { timeout: 10_000 });
  expect(S.rebuilds).toBe(1);
  await shot(page, "chat_rebuilt_line");
  // Home shows the same over state on the card
  S.draft = draftCard({ value: 100.2, left: 0, over: 0.2 });
  S.teams = 1;
  await home(page);
  await expect(vis(page, "draft-left")).toHaveText("£0.2m over");
  await expect(vis(page, "draft-left")).toHaveCSS("color", "rgb(255, 138, 122)");
});

test("chat: a new draft chat (sidebar New chat) shows the draft's own chips; never the Team / General ones", async () => {
  reset();
  withDraft();
  await openChat(page, "/chat?draft=1");
  const empty = vis(page, "empty-draft");
  await expect(empty).toBeVisible();
  const chips = await empty.locator('[data-testid="empty-chip"]').allInnerTexts();
  expect(chips.length).toBe(4);
  for (const t of chips) expect(t).not.toMatch(/captain for GW|best transfer|in form right now|injured this week/i);
  S.answers.push({ text: "A reply." });
  await vis(page, "chat-input").fill("Is my bench good enough?");
  await page.keyboard.press("Enter");
  await expect(vis(page, "assistant-message")).toBeVisible({ timeout: 15_000 });
  await expect.poll(() => page.url()).toContain(`/chat/${NEW_DRAFT_TID}`);
});

// ---- accessibility, reduced motion, keyboard -------------------------------------------------------------------------------
test("axe: 0 serious / critical on /home with a draft and on /chat in draft mode", async () => {
  test.skip(phone(), "axe runs once, on desktop");
  reset({ teams: 2, threads: [draftRow("Why these players?")] });
  withDraft("Why these players?");
  for (const url of ["/home", `/chat/${DRAFT_TID}`]) {
    await page.goto(url);
    await page.waitForTimeout(1500);
    const r = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"]).analyze();
    const bad = r.violations.filter((v) => v.impact === "serious" || v.impact === "critical");
    note(`axe ${url}: ${r.violations.length} violations, serious/critical ${bad.length}${bad.length ? ` -- ${bad.map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(" ")).slice(0, 3).join(" | ")}`).join("; ")}` : ""}`);
    expect(bad, url).toEqual([]);
  }
});

test("reduced motion: the building card shows all 15 dots at once and nothing spins", async () => {
  reset({ teams: 2 });
  await page.emulateMedia({ reducedMotion: "reduce" });
  try {
    await home(page);
    await vis(page, "build-pill").click();
    const bld = vis(page, "draft-building");
    await expect(bld).toBeVisible();
    const st = await bld.evaluate((el) => {
      const dots = Array.from(el.querySelectorAll<HTMLElement>('[data-testid="build-dot"]'));
      const spin = el.querySelector<HTMLElement>(".dr-spin");
      return { n: dots.length, opaque: dots.filter((d) => getComputedStyle(d).opacity === "1").length, anim: dots.filter((d) => getComputedStyle(d).animationName !== "none").length, spin: spin ? getComputedStyle(spin).animationName : "?" };
    });
    note(`reduced motion: ${JSON.stringify(st)}`);
    expect(st).toEqual({ n: 15, opaque: 15, anim: 0, spin: "none" });
    await page.waitForURL(`**/chat/${DRAFT_TID}`, { timeout: 15_000 });
  } finally {
    await page.emulateMedia({ reducedMotion: "no-preference" });
  }
});

test("keyboard only: Build from Home, the guide opens / traps / closes back to its opener, the Rebuild confirm", async () => {
  test.skip(phone(), "keyboard run on desktop");
  reset({ teams: 1 });
  withDraft();
  await home(page);
  const tabTo = async (id: string, max = 60) => {
    for (let i = 0; i < max; i++) {
      await page.keyboard.press("Tab");
      if (await page.evaluate((t) => document.activeElement?.getAttribute("data-testid") === t, id)) return;
    }
    throw new Error(`Tab never reached ${id}`);
  };
  await page.locator("body").click({ position: { x: 5, y: 5 } });
  await tabTo("draft-guide");
  const ring = await page.evaluate(() => getComputedStyle(document.activeElement as HTMLElement).outlineColor);
  note(`focus ring on the amber link: ${ring}`);
  expect(ring).toBe("rgb(59, 232, 255)");
  await page.keyboard.press("Enter");
  await expect(vis(page, "guide-dialog")).toBeVisible();
  for (let i = 0; i < 6; i++) await page.keyboard.press("Tab");
  expect(await page.evaluate(() => !!document.activeElement?.closest('[data-slot="dialog-content"]') || !!document.activeElement?.hasAttribute("data-base-ui-focus-guard"))).toBe(true);
  await page.keyboard.press("Escape");
  await expect(vis(page, "guide-dialog")).toHaveCount(0);
  await expect(vis(page, "draft-guide")).toBeFocused();
  await tabTo("draft-rebuild");
  await page.keyboard.press("Enter");
  await expect(vis(page, "rebuild-keep")).toBeFocused();
  await page.keyboard.press("Escape");
  await expect(vis(page, "draft-rebuild")).toBeFocused();
  await tabTo("draft-chat");
  await page.keyboard.press("Enter");
  await page.waitForURL(`**/chat/${DRAFT_TID}`, { timeout: 15_000 });
});

// ---- contrast: every draft surface as the browser painted it (the W5b sweep: buttons, links, text controls) ------------------
test("contrast: the computed sweep over every draft surface (Home card + new-user card, guide, confirms, chat, over state)", async () => {
  const lows: { ratio: number; label: string; where: string }[] = [];
  const sweep = async (where: string) => {
    await page.waitForTimeout(500);
    const r = await sweepPage(page);
    if (r.lowest) lows.push({ ratio: r.lowest.ratio, label: r.lowest.label, where });
    note(`sweep ${where}: ${r.text.length} text controls, lowest ${r.lowest ? `${r.lowest.ratio.toFixed(2)}:1 ${r.lowest.label}` : "n/a"}, ${r.fails.length} below the bar`);
    expect(r.fails.map((f: { ratio: number; fg: string; bg: string; label: string }) => `${f.ratio}:1 ${f.fg} on ${f.bg} ${f.label}`), where).toEqual([]);
  };
  reset();
  await home(page);
  await sweep("home new user (Build card)");
  reset({ teams: 2, threads: [draftRow("Why these players?")] });
  withDraft("Why these players?");
  S.draft = draftCard({ newer_predictions: true });
  await home(page);
  await sweep("home draft card + pill-less header + Recent DRAFT tag");
  await vis(page, "draft-guide").click();
  await sweep("the guide");
  await page.keyboard.press("Escape");
  await vis(page, "draft-rebuild").click();
  await sweep("the Rebuild confirm");
  await page.keyboard.press("Escape");
  await vis(page, "draft-delete").click();
  await sweep("the Delete confirm");
  await page.keyboard.press("Escape");
  S.teams = 3;
  await home(page);
  await sweep("home full-width draft row");
  await openChat(page, `/chat/${DRAFT_TID}`);
  if (phone()) await vis(page, "team-bar").click();
  await sweep("chat: banner, opening chips, the draft card / panel, Newer predictions");
  S.answers.push({ text: "A reply.", preview: PREVIEW });
  await vis(page, "chat-input").fill("Swap Lewis for Mykolenko");
  await page.keyboard.press("Enter");
  await expect(vis(page, "preview-card")).toBeVisible({ timeout: 15_000 });
  await waitTyped(page);
  await sweep("chat: the draft preview card + value line");
  S.draft = draftCard({ value: 100.2, left: 0, over: 0.2 });
  await openChat(page, `/chat/${DRAFT_TID}`);
  if (phone()) await vis(page, "team-bar").click();
  await sweep("chat: over budget (coral)");
  const low = lows.sort((x, y) => x.ratio - y.ratio)[0];
  note(`SUMMARY lowest contrast over the draft surfaces: ${low ? `${low.ratio.toFixed(2)}:1 ${low.label} on ${low.where}` : "n/a"}`);
});
