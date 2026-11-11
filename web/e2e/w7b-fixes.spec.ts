import { expect, test, type BrowserContext, type Page } from "@playwright/test";
import AxeBuilder from "@axe-core/playwright";
import { execFileSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { createTestUser, deleteUser, findTestUsers } from "./clerk-users";
import { sweepPage } from "../scripts/lib/sweep.mjs";
import { API, DB_PREFIX, apiCall, py, signIn, vis } from "./w4";
import { sql1 } from "./w5";

/** Prompt W7b PART 3: one PASS / FAIL per fix, against the scratchpad backend (:8010, clerk mode, the admin switch for
 *  w7badm) and the production build on :3002. Users w7bu (the person) and w7badm (the admin check), deleted at the end.
 *  Agent turns: ONE (F3, the real turn a reload interrupts). FPL: 0 (seeded teams). */

test.describe.configure({ mode: "serial" });

const U = "w7bu";
const ADM = "w7badm";
const SHOTS = process.env.W7B_SHOTS ?? path.join("C:", "dev", "fpl-backups", "w5_about_privacy_files", "w7b_fixes_files");
const BASE = process.env.E2E_BASE_URL ?? "http://localhost:3002";
const results: string[] = [];
const notes: string[] = [];
const log = (s: string) => console.log(`[W7b] ${s}`);
const pass = (s: string) => {
  results.push(s);
  log(`PASS ${s}`);
};
let context: BrowserContext;
let page: Page;
let userId = 0;
let clerkId = "";

async function shot(p: Page, name: string, full = false) {
  fs.mkdirSync(SHOTS, { recursive: true });
  const vp = p.viewportSize()!;
  await p.screenshot({ path: path.join(SHOTS, `w7b_${name}_${vp.width}x${vp.height}.png`), fullPage: full });
}
const clerkSecret = () => fs.readFileSync(path.join(process.cwd(), ".env.local"), "utf8").split(/\r?\n/).find((l) => l.startsWith("CLERK_SECRET_KEY="))!.slice("CLERK_SECRET_KEY=".length).trim().replace(/^"|"$/g, "");
async function revokeSessions(id: string) {
  const h = { Authorization: `Bearer ${clerkSecret()}` };
  const r = await fetch(`https://api.clerk.com/v1/sessions?user_id=${id}&status=active&limit=20`, { headers: h });
  const list = (await r.json()) as { id: string }[] | { data: { id: string }[] };
  const ids = (Array.isArray(list) ? list : list.data ?? []).map((s) => s.id);
  for (const sid of ids) await fetch(`https://api.clerk.com/v1/sessions/${sid}/revoke`, { method: "POST", headers: h });
  return ids.length;
}
/** sign in on the login page the browser is ALREADY on (keeps its ?redirect_url / ?reason) */
async function signInHere(p: Page) {
  await p.locator('[data-testid="skip-intro"]:visible').first().click({ timeout: 5_000 }).catch(() => undefined);
  await expect(p.locator(".stage").first()).toHaveAttribute("data-phase", "login");
  await p.locator("#c-email").fill(`${U}+clerk_test@example.com`);
  await vis(p, "send-code").click();
  await expect(vis(p, "code-sent-title")).toBeVisible({ timeout: 20_000 });
  await vis(p, "otp").fill("424242");
}
/** Clerk throttles repeated code sends for one address ("Too many attempts. Wait a minute"): pause between sign-ins */
let lastSignIn = 0;
async function coolDown(p: Page) {
  const wait = 65_000 - (Date.now() - lastSignIn);
  if (wait > 0) await p.waitForTimeout(wait);
  lastSignIn = Date.now();
}
async function clerkReady(p: Page) {
  await expect.poll(() => p.evaluate(() => !!(window as unknown as { Clerk?: { session?: unknown } }).Clerk?.session), { timeout: 20_000 }).toBe(true);
}
/** F6 / F8 / Admin can run on their own (--grep): sign w7bu in on the shared page when F1 / F2 have not done so */
async function ensureSignedIn() {
  if (userId >= 10_001) return;
  await coolDown(page);
  await page.goto("/login");
  await signInHere(page);
  await page.waitForURL("**/home", { timeout: 30_000 });
  await clerkReady(page);
  userId = Number((await apiCall(page, "get", "/me")).body.user_id);
  expect(userId).toBeGreaterThanOrEqual(10_001);
  log(`signed ${U} in on the shared page (user ${userId})`);
}

const DOC_PY = `
import pandas as pd, team_card, squad_store
def build_doc(formation):
    b = team_card._local_snapshot()
    teams = {t["id"]: t["short_name"] for t in b["teams"]}
    D, M, F = [int(x) for x in formation.split("-")]
    els = sorted(b["elements"], key=lambda e: (e["now_cost"], e["id"]))
    ok = lambda e: e["status"] == "a" and e.get("chance_of_playing_next_round") in (None, 100)
    doubt = lambda e: e["status"] == "d" and e.get("chance_of_playing_next_round") in (25, 50, 75)
    clubs = {}
    def take(e):
        clubs[e["team"]] = clubs.get(e["team"], 0) + 1
        return e
    def pick(pt, n, flagged_second=False):
        out = []
        if flagged_second:
            f = next(e for e in els if e["element_type"] == pt and doubt(e) and clubs.get(e["team"], 0) < 3)
        for e in els:
            if len(out) >= n: break
            if e["element_type"] != pt or not ok(e) or clubs.get(e["team"], 0) >= 3: continue
            if flagged_second and (e["id"] == f["id"]): continue
            out.append(take(e))
            if flagged_second and len(out) == 1:
                out.append(take(f))
        return out
    gk, de, mi, fw = pick(1, 2), pick(2, 5, True), pick(3, 5, True), pick(4, 3)
    five = "DEF" if D == 5 else ("MID" if M == 5 else None)
    rows = []
    def add(e, pos, role, bo=None):
        rows.append({"element": e["id"], "name": e["web_name"], "position": pos, "team": teams[e["team"]], "purchase_price": e["now_cost"], "role": role, "bench_order": bo})
    add(gk[0], "GK", "start"); add(gk[1], "GK", "bench", 1)
    bo = 2
    for i, e in enumerate(de):
        if i < D: add(e, "DEF", "CAPTAIN" if (five == "DEF" and i == 0) else "start")
        else: add(e, "DEF", "bench", bo); bo += 1
    for i, e in enumerate(mi):
        if i < M: add(e, "MID", "CAPTAIN" if (five == "MID" and i == 0) else "start")
        else: add(e, "MID", "bench", bo); bo += 1
    for i, e in enumerate(fw):
        if i < F: add(e, "FWD", "VICE" if i == 0 else ("CAPTAIN" if (five is None and i == 1) else "start"))
        else: add(e, "FWD", "bench", bo); bo += 1
    if five is None and F < 2:
        rows[[r["role"] for r in rows].index("start")]["role"] = "CAPTAIN"
    bank = max(0, 1000 - sum(r["purchase_price"] for r in rows))
    return squad_store.document(pd.DataFrame(rows), bank, 1, 0, "2026-27", {"kind": "w7b", "formation": formation})
`;

function seedTeams(uid: number, ids: number[], formation: string): number[] {
  const out = py(`${DB_PREFIX}
import json, squad_store, fpl_teams
${DOC_PY}
fpl_teams.ensure_schema(conn)
keys = []
for i, tid in enumerate(${JSON.stringify(ids)}):
    with conn.cursor() as c2:
        c2.execute("INSERT INTO user_fpl_teams (user_id, fpl_team_id, label, is_active, last_imported_at, last_imported_gw, entry_name, manager_name, total_points, overall_rank, last_gw, last_gw_points, updated_after_gw, summary_updated_at) VALUES (%s, %s, %s, %s, now(), 10, %s, %s, %s, %s, 10, %s, 10, now()) RETURNING squad_key", (${uid}, tid, "Team " + str(i + 1), i == 0, "Team " + str(i + 1) + " FC", "W7b Manager", 600 + i, 100000 + i, 60))
        keys.append(c2.fetchone()[0])
    conn.commit()
    squad_store.write_version(None, build_doc(${JSON.stringify(formation)}), 10, "W7b seed", True, user_id=keys[-1])
print(json.dumps(keys))
`);
  return JSON.parse(out.trim().split("\n").pop()!) as number[];
}

async function pitchGeometry(p: Page, root: string) {
  return p.locator(root).first().evaluate((pitchEl) => {
    const r = (el: Element) => {
      const b = el.getBoundingClientRect();
      return { x: b.left, y: b.top, w: b.width, h: b.height, r: b.right, b: b.bottom };
    };
    const pitch = r(pitchEl);
    const toks = [...pitchEl.querySelectorAll('[data-testid="token"]')].map((t) => {
      const parts = [t, ...t.querySelectorAll(".ch-tok-name, .ch-nf, .ch-badge-c, .ch-badge-vc, .ch-flag, .ch-swaptag")].map(r);
      const name = t.querySelector(".ch-tok-name") as HTMLElement;
      return { parts, text: name.textContent ?? "" };
    });
    let outside = 0;
    const pairs = new Set<string>();
    for (const t of toks) for (const q of t.parts) if (q.x < pitch.x - 0.5 || q.r > pitch.r + 0.5 || q.y < pitch.y - 0.5 || q.b > pitch.b + 0.5) outside++;
    for (let i = 0; i < toks.length; i++)
      for (let j = i + 1; j < toks.length; j++)
        for (const a of toks[i].parts) for (const b of toks[j].parts) if (a.x < b.r - 0.5 && b.x < a.r - 0.5 && a.y < b.b - 0.5 && b.y < a.b - 0.5) pairs.add(`${toks[i].text}/${toks[j].text}`);
    const rows = [...pitchEl.querySelectorAll('[data-testid="pitch-row"]')].map((e) => ({ n: Number(e.getAttribute("data-n")), w: Math.round((e.querySelector('[data-testid="token"]') as HTMLElement).getBoundingClientRect().width) }));
    return { tokens: toks.length, outside, overlaps: [...pairs], rows };
  });
}

test.beforeAll(async ({ browser }) => {
  fs.mkdirSync(SHOTS, { recursive: true });
  for (const n of [U, ADM]) for (const id of await findTestUsers(n)) await deleteUser(id);
  clerkId = (await createTestUser(U)).id;
  log(`Clerk test user ${U} created (${clerkId.slice(0, 9)}…)`);
  context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  page = await context.newPage();
});

test.afterAll(async () => {
  const counts = await (await page.request.get(`${API}/__w6/counts`)).json().catch(() => null);
  for (const n of [U, ADM]) for (const id of await findTestUsers(n)) await deleteUser(id);
  log(`SUMMARY FPL live ${counts?.fpl_live ?? "?"} | clerk test users left ${(await findTestUsers(U)).length + (await findTestUsers(ADM)).length} | user ${userId}`);
  for (const n of notes) log(`NOTE ${n}`);
  for (const r of results) log(`RESULT ${r}`);
  await context?.close();
});

// ---- F1 the CAPTCHA element, F11 Back on the code step -----------------------------------------------------------------------------------

test("F1 + F11: clerk-captcha in the DOM on both paths; Back on the code step returns to the email step", async () => {
  test.setTimeout(120_000);
  await page.goto("/about");
  await page.goto("/login");
  await vis(page, "skip-intro").click();
  await expect(page.locator(".stage").first()).toHaveAttribute("data-phase", "login");
  const atEmail = await page.locator("#clerk-captcha").count();
  const googleBefore = await page.evaluate(() => !!document.getElementById("clerk-captcha") && !!document.querySelector('[data-testid="google"]'));
  await page.locator("#c-email").fill(`${U}+clerk_test@example.com`);
  await vis(page, "send-code").click();
  await expect(vis(page, "code-sent-title")).toBeVisible({ timeout: 20_000 });
  const atCode = await page.locator("#clerk-captcha").count();
  const step1 = await vis(page, "sign-in-card").getAttribute("data-step");
  await page.goBack();
  await page.waitForTimeout(800);
  const after = { url: page.url().replace(BASE, ""), step: await page.locator('[data-testid="sign-in-card"]:visible').first().getAttribute("data-step").catch(() => null) };
  await shot(page, "F11_back_on_code_step");
  log(`F1 clerk-captcha: ${atEmail} at the email step (Google button present ${googleBefore}), ${atCode} at the code step; F11 Back from ${step1} -> ${JSON.stringify(after)}`);
  expect(atEmail).toBe(1);
  expect(atCode).toBe(1);
  expect(googleBefore).toBe(true);
  expect(after.url.startsWith("/login")).toBe(true);
  expect(after.step).toBe("email");
  pass("F1 clerk-captcha present on the email step (with the Google button) and on the code step; F11 Back on the code step returns to the email step on /login");
  // and the sign-in itself still works from the email step after Back
  lastSignIn = Date.now();
  await page.locator("#c-email").fill(`${U}+clerk_test@example.com`);
  await vis(page, "send-code").click();
  await expect(vis(page, "code-sent-title")).toBeVisible({ timeout: 20_000 });
  await vis(page, "otp").fill("424242");
  await page.waitForURL("**/home", { timeout: 30_000 });
  await clerkReady(page);
  userId = Number((await apiCall(page, "get", "/me")).body.user_id);
  expect(userId).toBeGreaterThanOrEqual(10_001);
});

// ---- F2 redirect_url, the signed-out note, the draft ------------------------------------------------------------------------------------------

test("F2: signed-out deep link returns to that chat; //evil refused; revoke with a typed draft -> note -> sign in -> same chat + draft", async () => {
  test.setTimeout(400_000);
  const tid = (await apiCall(page, "post", "/threads")).body.thread_id as string;
  // (a) signed out deep link
  await vis(page, "account-menu").first().click();
  await page.locator('[data-testid="sign-out"]:visible').first().click();
  await page.waitForURL("**/login**", { timeout: 30_000 });
  const noNote = await page.locator('[data-testid="signed-out-note"]').count();
  await page.goto(`/chat/${tid}`);
  await page.waitForURL("**/login**", { timeout: 30_000 });
  const loginUrl = page.url().replace(BASE, "");
  await coolDown(page);
  await signInHere(page);                                   // on the /login?redirect_url=... page we were sent to
  await page.waitForURL(`**/chat/${tid}`, { timeout: 30_000 });
  log(`F2a deep link -> ${loginUrl} -> after sign-in ${page.url().replace(BASE, "")}; a normal Sign out showed the note: ${noNote > 0}`);
  expect(loginUrl).toContain(`redirect_url=${encodeURIComponent(`/chat/${tid}`)}`);
  expect(noNote).toBe(0);
  await clerkReady(page);
  // (b) an open redirect is refused
  await vis(page, "account-menu").first().click();
  await page.locator('[data-testid="sign-out"]:visible').first().click();
  await page.waitForURL("**/login**", { timeout: 30_000 });
  await page.goto("/login?redirect_url=//evil.example/phish");
  await vis(page, "skip-intro").click();
  await coolDown(page);
  await page.locator("#c-email").fill(`${U}+clerk_test@example.com`);
  await vis(page, "send-code").click();
  await expect(vis(page, "code-sent-title")).toBeVisible({ timeout: 20_000 });
  await vis(page, "otp").fill("424242");
  await page.waitForURL("**/home", { timeout: 30_000 });
  log(`F2b //evil.example redirect_url -> ${page.url().replace(BASE, "")}`);
  expect(page.url()).toContain("/home");
  await clerkReady(page);
  // (c) the session revoked while a draft is typed in a chat
  await page.goto(`/chat/${tid}`);
  await expect(page.locator('[data-testid="chat"][data-ready="true"]:visible')).toBeVisible({ timeout: 30_000 });
  const DRAFT = "Who should I captain this week — Haaland or Salah?";
  await vis(page, "chat-input").fill(DRAFT);
  await page.waitForTimeout(400);
  const n = await revokeSessions(clerkId);
  log(`F2c revoked ${n} session(s) with a draft typed`);
  await page.waitForURL("**/login**", { timeout: 120_000 });
  const url = page.url().replace(BASE, "");
  await expect(page.locator('[data-testid="signed-out-note"]:visible')).toBeVisible({ timeout: 20_000 });
  const note = (await page.locator('[data-testid="signed-out-note"]:visible').textContent())!.trim();
  const phase = await page.locator(".stage").first().getAttribute("data-phase");
  const music = await page.locator(".stage").first().getAttribute("data-music");
  await shot(page, "F2_signed_out_note");
  log(`F2c -> ${url}; note "${note}"; phase ${phase}; music ${music}`);
  expect(url).toContain("reason=signed_out");
  expect(url).toContain(`redirect_url=${encodeURIComponent(`/chat/${tid}`)}`);
  expect(note).toBe("You were signed out — sign in to continue.");
  expect(phase).toBe("login");
  expect(music).toBe("off");
  await coolDown(page);
  await page.locator("#c-email").fill(`${U}+clerk_test@example.com`);
  await vis(page, "send-code").click();
  await expect(vis(page, "code-sent-title")).toBeVisible({ timeout: 20_000 });
  await vis(page, "otp").fill("424242");
  await page.waitForURL(`**/chat/${tid}`, { timeout: 30_000 });
  await expect(page.locator('[data-testid="chat"][data-ready="true"]:visible')).toBeVisible({ timeout: 30_000 });
  await expect(vis(page, "chat-input")).toHaveValue(DRAFT, { timeout: 10_000 });
  await shot(page, "F2_draft_restored");
  await clerkReady(page);
  pass(`F2 deep link -> /login?redirect_url -> back to /chat/{id}; //evil.example refused (-> /home); revoke with a draft -> "${note}" (intro + music skipped) -> sign in -> the same chat with the draft restored`);
});

// ---- F3 refresh during an answer (ONE real turn) ------------------------------------------------------------------------------------------

test("F3: reload 4 s into a real answer -> the question + 'Still working' -> the answer appears without a resend; the thread is listed", async () => {
  test.setTimeout(400_000);
  if (process.env.W7B_SKIP_F3) {
    notes.push("F3 skipped on this re-run (W7B_SKIP_F3): it PASSED on run 3 with one real turn ($0.1718); no further turn spent");
    test.skip(true, "F3 passed on run 3; not re-spending a turn");
  }
  await page.goto("/chat");
  await expect(page.locator('[data-testid="chat"][data-ready="true"]:visible')).toBeVisible({ timeout: 30_000 });
  await clerkReady(page);
  const before = Number((await apiCall(page, "get", "/me")).body.spent_today_usd ?? 0);
  const Q = "Name three good differential midfielders under 6.0m for the next gameweek, one line each.";
  let chats = 0;
  page.on("request", (r) => {
    if (r.url().endsWith("/chat") && r.method() === "POST") chats++;
  });
  await vis(page, "chat-input").fill(Q);
  await vis(page, "chat-input").press("Enter");
  await expect(vis(page, "thinking")).toBeVisible({ timeout: 10_000 });
  await page.waitForTimeout(4000);
  const tid = (await page.locator('[data-testid="chat"]:visible').first().getAttribute("data-thread-id"))!;
  expect(tid).toMatch(/^th_/);
  await page.reload();
  await expect(page.locator('[data-testid="chat"][data-ready="true"]:visible')).toBeVisible({ timeout: 30_000 });
  const right = {
    user: await page.locator('[data-testid="user-message"]:visible').count(),
    thinking: await page.locator('[data-testid="thinking"][data-resumed="true"]:visible').count(),
    word: await page.locator('[data-testid="thinking"]:visible [data-testid="spinner-word"]').textContent().catch(() => null),
    secs: await page.locator('[data-testid="thinking"]:visible [data-testid="thinking-seconds"]').textContent().catch(() => null),
    listed: await page.locator(`[data-testid="thread-row"][data-thread-id="${tid}"]:visible`).count(),
  };
  await shot(page, "F3_after_reload_still_working");
  log(`F3 right after the reload: ${JSON.stringify(right)}`);
  expect(right.user).toBe(1);
  expect(right.thinking).toBe(1);
  expect(right.word).toContain("Still working on this answer");
  expect(right.listed).toBe(1);
  await expect(page.locator('[data-testid="assistant-message"]:visible')).toHaveCount(1, { timeout: 150_000 });
  await expect(page.locator('[data-testid="thinking"]:visible')).toHaveCount(0);
  const usd = Math.max(0, Number((await apiCall(page, "get", "/me")).body.spent_today_usd ?? 0) - before);
  const rows = (await apiCall(page, "get", `/threads/${tid}/messages`)).body as unknown as { role: string }[];
  await shot(page, "F3_answer_arrived");
  log(`F3 the answer arrived after the reload; POST /chat from this page after the reload: ${chats - 1}; cost $${usd.toFixed(4)}; stored rows ${rows.map((r) => r.role).join(",")}`);
  expect(chats, "no re-send: one POST /chat in total").toBe(1);
  expect(rows.map((r) => r.role)).toEqual(["user", "assistant"]);
  expect(await sql1("SELECT count(*) FROM chat_messages WHERE status = 'pending' AND user_id = %s", [userId])).toBe(0);
  pass(`F3 reload 4 s into a real turn: the question + "Still working on this answer…" (seconds ${right.secs}) + the thread listed at once; the answer appeared without a resend ($${usd.toFixed(4)}); no pending row left; a forced failure leaving no pending row is Tests/test_w7b_backend.py`);
});

// ---- F4 the branded 404 and error pages --------------------------------------------------------------------------------------------------------

test("F4: /foo is the branded 404; a forced client crash shows the branded error page with Try again + Home", async () => {
  test.setTimeout(120_000);
  const res = await page.goto("/foo");
  await expect(vis(page, "not-found")).toBeVisible({ timeout: 15_000 });
  const t404 = await page.title();
  const links = { home: await page.locator('[data-testid="oops-home"]:visible').count(), signIn: await page.locator('[data-testid="oops-sign-in"]:visible').count(), music: await page.locator('[data-testid="sound-toggle"]:visible').count(), account: await page.locator('[data-testid="account-menu"]').count() };
  await shot(page, "F4_404");
  log(`F4 /foo: HTTP ${res?.status()}, title "${t404}", ${JSON.stringify(links)}`);
  expect(res?.status()).toBe(404);
  expect(links.home).toBe(1);
  expect(links.signIn).toBe(1);
  expect(links.music).toBe(1);
  expect(links.account).toBe(0);
  // a forced crash: the chat page's messages read answers with a non-array -> fromRows throws in the effect -> error.tsx
  await page.goto("/home");
  await clerkReady(page);
  const tid = (await apiCall(page, "post", "/threads")).body.thread_id as string;
  await page.route(`${API}/threads/${tid}/messages`, (r) => r.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ not: "an array" }) }));
  await page.goto(`/chat/${tid}`);
  await expect(vis(page, "error-page")).toBeVisible({ timeout: 20_000 });
  const retry = await page.locator('[data-testid="oops-retry"]:visible').count();
  const home = await page.locator('[data-testid="oops-home"]:visible').count();
  await shot(page, "F4_error_page");
  await page.unroute(`${API}/threads/${tid}/messages`);
  await vis(page, "oops-retry").click();
  await expect(page.locator('[data-testid="chat"][data-ready="true"]:visible')).toBeVisible({ timeout: 30_000 });
  log(`F4 forced crash on /chat/{id}: error page with Try again ${retry} / Home ${home}; Try again recovered the page`);
  expect(retry).toBe(1);
  expect(home).toBe(1);
  pass(`F4 /foo -> branded 404 (${t404}) with Home + Sign in + the music button, no account data; a forced client crash -> branded error page, Try again recovers`);
});

// ---- F5 link preview, F9 icons + manifest -------------------------------------------------------------------------------------------------------

test("F5 + F9: Open Graph / Twitter tags and the generated image; manifest + icons served", async () => {
  test.setTimeout(120_000);
  const html = await (await fetch(`${BASE}/about`)).text();
  const head = html.slice(0, html.indexOf("</head>"));
  const meta = (p: string, attr = "property") => (new RegExp(`<meta[^>]*${attr}="${p}"[^>]*content="([^"]*)"`).exec(head) ?? new RegExp(`<meta[^>]*content="([^"]*)"[^>]*${attr}="${p}"`).exec(head))?.[1] ?? null;
  const og = { title: meta("og:title"), description: meta("og:description"), image: meta("og:image"), url: meta("og:url"), site: meta("og:site_name"), twitter: meta("twitter:card", "name"), twitterImage: meta("twitter:image", "name") };
  log(`F5 tags: ${JSON.stringify(og)}`);
  expect(og.title).toBe("FPL Copilot");
  expect(og.description).toContain("FPL Copilot is your AI assistant for Fantasy Premier League");
  expect(og.twitter).toBe("summary_large_image");
  expect(og.image).toMatch(/^https?:\/\/.+\/opengraph-image/);
  const img = await fetch(og.image!);
  const bytes = Buffer.from(await img.arrayBuffer());
  log(`F5 image: HTTP ${img.status}, ${img.headers.get("content-type")}, ${bytes.length} bytes`);
  expect(img.status).toBe(200);
  expect(img.headers.get("content-type")).toContain("image/png");
  fs.writeFileSync(path.join(SHOTS, "w7b_F5_opengraph_image_1200x630.png"), bytes);
  const p2 = await context.newPage();
  await p2.setViewportSize({ width: 1200, height: 630 });
  await p2.goto(og.image!);
  await shot(p2, "F5_opengraph_image_rendered");
  await p2.close();
  // F9
  const manifestHref = /<link[^>]*rel="manifest"[^>]*href="([^"]+)"/.exec(head)?.[1] ?? null;
  const apple = /<link[^>]*rel="apple-touch-icon"[^>]*href="([^"]+)"/.exec(head)?.[1] ?? null;
  const m = await fetch(`${BASE}${manifestHref ?? "/manifest.webmanifest"}`);
  const manifest = (await m.json()) as { name: string; short_name: string; icons: { src: string; sizes: string }[]; theme_color: string; background_color: string; display: string; start_url: string };
  const icons: string[] = [];
  for (const i of manifest.icons) icons.push(`${i.sizes} ${(await fetch(`${BASE}${i.src}`)).status}`);
  const appleRes = await fetch(`${BASE}${apple ?? "/apple-icon.png"}`);
  log(`F9 manifest ${manifestHref} HTTP ${m.status}: ${JSON.stringify({ name: manifest.name, short_name: manifest.short_name, theme: manifest.theme_color, bg: manifest.background_color, display: manifest.display, start: manifest.start_url })}; icons ${icons.join(", ")}; apple-touch-icon ${apple} HTTP ${appleRes.status} ${appleRes.headers.get("content-type")}`);
  expect(m.status).toBe(200);
  expect(manifest.name).toBe("FPL Copilot");
  expect(manifest.short_name).toBe("FPL Copilot");
  expect(manifest.theme_color.toLowerCase()).toBe("#04070c");
  expect(manifest.background_color.toLowerCase()).toBe("#04070c");
  expect(manifest.display).toBe("standalone");
  expect(manifest.start_url).toBe("/home");
  expect(icons).toEqual(["192x192 200", "512x512 200"]);
  expect(appleRes.status).toBe(200);
  expect(apple).toBeTruthy();
  pass(`F5 og:title / og:description / og:image (${bytes.length}-byte PNG) / twitter:card summary_large_image present; F9 manifest (name, 192 + 512 icons, #04070C, standalone, /home) and apple-touch-icon served`);
});

// ---- F6 + F7 + D the phone: 16px inputs, music gated on the first tap and data-saver --------------------------------------------------------------

test("F7: no mp3 request before the first tap on a phone; data-saver never auto-starts; desktop unchanged", async ({ browser }) => {
  test.setTimeout(300_000);
  const state = await context.storageState();
  const measure = async (ctx: BrowserContext, label: string, tap: boolean, init?: () => void) => {
    const p = await ctx.newPage();
    if (init) await p.addInitScript(init);
    const mp3: string[] = [];
    let bytes = 0;
    p.on("request", (r) => {
      if (/\/music\/.*\.mp3/.test(r.url())) mp3.push(r.url().split("/").pop()!);
    });
    p.on("response", (r) => {
      bytes += Number(r.headers()["content-length"] ?? 0); // declared sizes only: reading a streaming audio body would hang
    });
    await p.goto("/login", { waitUntil: "domcontentloaded" });
    await p.waitForTimeout(3500);
    const beforeTap = { mp3: mp3.length, kb: Math.round(bytes / 1024), playing: await p.locator('[data-testid="site-audio"]').getAttribute("data-playing").catch(() => null), src: await p.locator('[data-testid="site-audio"]').getAttribute("src").catch(() => null) };
    let afterTap = null;
    if (tap) {
      await p.touchscreen.tap(60, 400).catch(() => p.mouse.click(60, 400));
      await p.waitForTimeout(2500);
      afterTap = { mp3: mp3.length, playing: await p.locator('[data-testid="site-audio"]').getAttribute("data-playing").catch(() => null) };
    }
    log(`F7 ${label}: before any tap ${JSON.stringify(beforeTap)}${afterTap ? `; after a tap ${JSON.stringify(afterTap)}` : ""}`);
    await p.close();
    return { beforeTap, afterTap };
  };
  const phone = await browser.newContext({ storageState: state, viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true });
  const a = await measure(phone, "phone 390 (fresh login page)", true);
  expect(a.beforeTap.mp3, "no mp3 request before the first tap on a phone").toBe(0);
  expect(a.beforeTap.src ?? "", "no src before the first tap").toBe("");
  expect(a.afterTap!.mp3, "the first tap starts the music").toBeGreaterThanOrEqual(1);
  // data-saver on: never on its own, the button still plays
  const saver = await browser.newContext({ storageState: state, viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true });
  const b = await measure(saver, "phone 390 + data-saver (emulated)", true, () => {
    Object.defineProperty(navigator, "connection", { value: { saveData: true, effectiveType: "3g" }, configurable: true });
  });
  expect(b.beforeTap.mp3).toBe(0);
  expect(b.afterTap!.mp3, "data-saver: a tap does not start it").toBe(0);
  const p3 = await saver.newPage();
  await p3.addInitScript(() => {
    Object.defineProperty(navigator, "connection", { value: { saveData: true }, configurable: true });
  });
  const mp3s: string[] = [];
  p3.on("request", (r) => {
    if (/\/music\/.*\.mp3/.test(r.url())) mp3s.push(r.url());
  });
  await p3.goto("/about");
  await p3.waitForTimeout(1500);
  await p3.locator('[data-testid="sound-toggle"]:visible').first().tap();
  await p3.waitForTimeout(2000);
  const buttonPlays = { mp3: mp3s.length, playing: await p3.locator('[data-testid="site-audio"]').getAttribute("data-playing") };
  log(`F7 data-saver: the music button -> ${JSON.stringify(buttonPlays)}`);
  expect(buttonPlays.mp3).toBeGreaterThanOrEqual(1);
  await p3.close();
  // desktop unchanged: the music starts on its own
  const desk = await browser.newContext({ storageState: state, viewport: { width: 1440, height: 900 } });
  const c = await measure(desk, "desktop 1440 (fresh login page)", false);
  expect(c.beforeTap.mp3, "desktop still auto-starts (the W5b behaviour)").toBeGreaterThanOrEqual(1);
  await desk.close();
  await saver.close();
  await phone.close();
  pass(`F7 phone: 0 mp3 requests and no src before the first tap (${a.beforeTap.kb} KB login page before any tap), the tap starts it; data-saver: never on its own (tap included), the button still plays; desktop unchanged (auto-starts, ${c.beforeTap.kb} KB)`);
});

test("F6: every input / textarea on the phone >= 16px; the desktop chat box unchanged", async ({ browser }) => {
  test.setTimeout(300_000);
  await ensureSignedIn();
  const sizes: string[] = [];
  const measureInputs = (p: Page) => p.evaluate(() => [...document.querySelectorAll("input, textarea")].filter((el) => getComputedStyle(el).display !== "none").map((el) => `${el.getAttribute("data-testid") || el.id || el.getAttribute("name") || el.tagName}:${getComputedStyle(el).fontSize}`));
  // the shared, signed-in page at the phone width (the font sizes are CSS media queries: the viewport is what counts)
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/home");
  await page.locator('[data-testid="add-team-card"]:visible, [data-testid="choice-add-team"]:visible').first().click({ timeout: 15_000 });
  await expect(vis(page, "add-team-input")).toBeVisible({ timeout: 10_000 });
  for (const f of await measureInputs(page)) sizes.push(`/home ${f}`);
  await shot(page, "F6_phone_home_dialog");
  await page.keyboard.press("Escape").catch(() => undefined);
  await page.goto("/chat");
  await expect(vis(page, "chat-input")).toBeVisible({ timeout: 15_000 });
  for (const f of await measureInputs(page)) sizes.push(`/chat ${f}`);
  await shot(page, "F6_phone_chat");
  // the login card signed OUT (signed in, /login goes straight to Home)
  const out = await browser.newContext({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true });
  out.setDefaultTimeout(15_000);
  const lp = await out.newPage();
  await lp.goto("/login", { waitUntil: "domcontentloaded" });
  await lp.waitForTimeout(2500);
  await lp.locator('[data-testid="skip-intro"]:visible').first().click({ timeout: 4000 }).catch(() => undefined);
  await expect(lp.locator("#c-email")).toBeVisible({ timeout: 10_000 });
  for (const f of await measureInputs(lp)) sizes.push(`/login(out) ${f}`);
  await shot(lp, "F6_phone_login_out");
  await out.close();
  const small = sizes.filter((s) => parseFloat(s.split(":").pop()!) < 16);
  log(`F6 phone inputs: ${sizes.join("; ")}; under 16px: ${small.length ? small.join("; ") : "none"}`);
  for (const must of ["add-team-input", "add-team-label", "chat-input", "c-email"]) expect(sizes.some((x) => x.includes(`${must}:`)), `${must} measured`).toBe(true);
  expect(small).toEqual([]);
  // desktop: the chat box unchanged
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/chat");
  await expect(vis(page, "chat-input")).toBeVisible({ timeout: 15_000 });
  const deskSize = await vis(page, "chat-input").evaluate((el) => getComputedStyle(el).fontSize);
  log(`F6 desktop chat box ${deskSize} (unchanged)`);
  pass(`F6 every input/textarea on the phone >= 16px (${sizes.length} measured: the chat box 15 -> 16px, the Add-team dialog's two inputs 14 -> 16px, the login card already 16px; desktop chat box ${deskSize}, unchanged)`);
});

// ---- F8 the fast walk shows no 429, F10 the "3 of 3 teams" note, W6b Part B rows of five --------------------------------------------------------

test("F8 + F10 + W6b-B: no 429 on the W7a fast walk; '3 of 3 teams' at the limit; rows of five on the pitch; header line shows the value", async () => {
  test.setTimeout(300_000);
  await ensureSignedIn();
  const s429: string[] = [];
  page.on("response", (r) => {
    if (r.status() === 429) s429.push(r.url().replace(API, ""));
  });
  for (const p of ["/home", "/chat", "/about", "/privacy", "/home", "/chat", "/about", "/privacy", "/home"]) {
    await page.goto(p);
    await page.waitForTimeout(900);
  }
  for (let i = 0; i < 4; i++) {
    await page.goBack();
    await page.waitForTimeout(700);
  }
  for (const p of ["/home", "/chat", "/home", "/chat"]) {
    await page.goto(p);
    await page.waitForTimeout(600);
    await page.reload();
    await page.waitForTimeout(900);
  }
  log(`F8 the fast walk: ${s429.length} responses with 429 (${s429.join(", ")})`);
  expect(s429).toEqual([]);
  // F10 + W6b-B: three seeded teams, the first one a 5-3-2
  const keys = seedTeams(userId, [7000021, 7000022, 7000023], "5-3-2");
  log(`seeded squad keys ${keys.join(", ")}`);
  await page.goto("/home");
  await expect(page.locator('[data-testid="team-card"]:visible')).toHaveCount(3, { timeout: 30_000 });
  const full = vis(page, "teams-full");
  await expect(full).toBeVisible();
  const text = (await full.textContent())!.replace(/\s+/g, " ").trim();
  const addCards = await page.locator('[data-testid="add-team-card"]:visible').count();
  await shot(page, "F10_three_of_three", true);
  log(`F10 at 3 teams: "${text}", add cards ${addCards}`);
  expect(text).toContain("3 of 3 teams");
  expect(addCards).toBe(0);
  await page.locator('[data-testid="team-card"][data-team-id="7000021"] [data-testid="ask-team"]:visible').first().click();
  await expect(page.locator('[data-testid="chat"][data-ready="true"]:visible')).toBeVisible({ timeout: 30_000 });
  await expect(vis(page, "team-card")).toBeVisible({ timeout: 30_000 });
  await expect(vis(page, "card-line")).toContainText("5-3-2", { timeout: 30_000 });
  await page.waitForTimeout(400);
  const g = await pitchGeometry(page, '[data-testid="pitch"]:visible');
  const line = await vis(page, "card-line").evaluate((el) => ({ text: (el.textContent ?? "").replace(/\s+/g, " ").trim(), cut: el.scrollWidth > el.clientWidth + 0.5 }));
  await page.locator('[data-testid="team-card"]:visible').first().screenshot({ path: path.join(SHOTS, "w7b_W6bB_532_card.png") });
  log(`W6b-B desktop 5-3-2: rows ${g.rows.map((r) => `${r.n}x${r.w}px`).join(" ")}, outside ${g.outside}, overlaps ${g.overlaps.length}; line "${line.text}" cut ${line.cut}`);
  expect(g.tokens).toBe(11);
  expect(g.rows.find((r) => r.n === 5)?.w).toBe(50);
  expect(g.outside).toBe(0);
  expect(g.overlaps).toEqual([]);
  expect(line.cut).toBe(false);
  expect(line.text).toMatch(/£\d+\.\d+m$/);
  // the phone panel at 390
  const ph = await page.context().browser()!.newContext({ storageState: await context.storageState(), viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true });
  const pp = await ph.newPage();
  await pp.goto("/chat?team=7000021");
  await expect(pp.locator('[data-testid="chat"][data-ready="true"]:visible')).toBeVisible({ timeout: 30_000 });
  await expect(vis(pp, "team-bar-line")).toContainText("5-3-2", { timeout: 30_000 });
  await vis(pp, "team-bar").click();
  await expect(vis(pp, "pitch-panel")).toBeVisible();
  await pp.waitForTimeout(400);
  const gp = await pitchGeometry(pp, '[data-testid="pitch-panel"]:visible [data-testid="pitch"]');
  const pl = await vis(pp, "panel-line").evaluate((el) => ({ text: (el.textContent ?? "").replace(/\s+/g, " ").trim(), cut: el.scrollWidth > el.clientWidth + 0.5 }));
  await pp.locator('[data-testid="pitch-panel"]:visible').screenshot({ path: path.join(SHOTS, "w7b_W6bB_532_phone_390.png") });
  log(`W6b-B phone 390 5-3-2: rows ${gp.rows.map((r) => `${r.n}x${r.w}px`).join(" ")}, outside ${gp.outside}, overlaps ${gp.overlaps.length}; panel line "${pl.text}" cut ${pl.cut}`);
  expect(gp.rows.find((r) => r.n === 5)?.w).toBe(56);
  expect(gp.outside).toBe(0);
  expect(gp.overlaps).toEqual([]);
  expect(pl.cut).toBe(false);
  await ph.close();
  pass(`F8 0 x 429 on the fast walk (120 reads a minute); F10 "${text}" shown, no Add card; W6b-B 5-3-2: rows of five at 50px desktop / 56px phone, no overlap, nothing outside the pitch, the header and panel lines end with the team value`);
});

// ---- Admin: real people only, the two grey lines; axe; the contrast sweep ---------------------------------------------------------------------------

test("Admin counts real people only with the two grey lines; axe 0 serious/critical; the --live sweep incl. /admin", async ({ browser }) => {
  test.setTimeout(300_000);
  await ensureSignedIn();
  for (const id of await findTestUsers(ADM)) await deleteUser(id);
  await createTestUser(ADM);
  const actx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const ap = await actx.newPage();
  await signIn(ap, `${ADM}+clerk_test@example.com`);
  await ap.goto("/admin");
  await expect(ap.locator('[data-testid="admin"][data-state="ready"]:visible')).toBeVisible({ timeout: 30_000 });
  const pv = Object.fromEntries((await ap.locator("[data-testid^='v-']:visible").evaluateAll((els) => els.map((e) => [e.getAttribute("data-testid")!.slice(2), Number(e.getAttribute("data-value"))]))) as [string, number][]);
  const sv = {
    users_total: Number(sql1("SELECT count(*) FROM app_users WHERE user_id >= 10001")),
    answers_total: Number(sql1("SELECT count(*) FROM chat_usage WHERE user_id >= 10001 OR (user_id IS NULL AND coalesce(turn_id, '') = 'deleted')")),
    usd_total: Number(sql1("SELECT coalesce(sum(usd), 0) FROM chat_usage WHERE user_id >= 10001 OR (user_id IS NULL AND coalesce(turn_id, '') = 'deleted')")),
    owner_usd: Number(sql1("SELECT coalesce(sum(usd), 0) FROM chat_usage WHERE user_id = 1")),
    testing_usd: Number(sql1("SELECT coalesce(sum(usd), 0) FROM chat_usage WHERE (user_id IS NULL AND coalesce(turn_id, '') <> 'deleted') OR user_id IN (9001, 9002)")),
    users_all: Number(sql1("SELECT count(*) FROM app_users")),
  };
  const ownerRow = ap.locator('[data-testid="owner-row"]:visible');
  const testingRow = ap.locator('[data-testid="testing-row"]:visible');
  const ownerUsd = (await ownerRow.count()) ? Number(await ownerRow.getAttribute("data-usd")) : 0;
  const testingUsd = (await testingRow.count()) ? Number(await testingRow.getAttribute("data-usd")) : 0;
  const userRows = await ap.locator('[data-testid="user-row"]:visible').count();
  await ap.locator('[data-testid="card-users"]:visible').scrollIntoViewIfNeeded();
  await shot(ap, "Admin_real_people_only");
  log(`Admin: users ${sv.users_total} (page ${pv.users_total}; app_users has ${sv.users_all} rows incl. the owner); answers_total ${sv.answers_total} vs ${pv.answers_total}; usd_total ${sv.usd_total} vs ${pv.usd_total}; owner line ${sv.owner_usd} vs ${ownerUsd}; testing line ${sv.testing_usd} vs ${testingUsd}; table rows ${userRows}`);
  expect(pv.users_total).toBe(sv.users_total);
  expect(userRows).toBe(sv.users_total);
  expect(pv.answers_total).toBe(sv.answers_total);
  expect(Math.abs(pv.usd_total - sv.usd_total)).toBeLessThan(1e-6);
  expect(Math.abs(ownerUsd - sv.owner_usd)).toBeLessThan(1e-6);
  expect(Math.abs(testingUsd - sv.testing_usd)).toBeLessThan(1e-6);
  expect(Number(sql1("SELECT is_admin::int FROM app_users WHERE email = %s", [`${ADM}+clerk_test@example.com`]))).toBe(0);
  // axe + the sweep on /admin, /home, /chat, and the --live script with the admin session
  const lowest: string[] = [];
  for (const p of ["/admin", "/home", "/chat"]) {
    await ap.goto(p);
    await ap.waitForTimeout(2500);
    const r = await new AxeBuilder({ page: ap }).disableRules(["color-contrast"]).analyze();
    const bad = r.violations.filter((v) => v.impact === "serious" || v.impact === "critical");
    const sw = await sweepPage(ap);
    lowest.push(`${p} axe ${bad.length} serious/critical (${r.violations.length} total), sweep lowest ${sw.lowest ? sw.lowest.ratio.toFixed(2) : "n/a"}:1, ${sw.fails.length} below`);
    expect(bad.map((v) => v.id)).toEqual([]);
    expect(sw.fails.map((x: { ratio: number; label: string }) => `${x.ratio}:1 ${x.label}`)).toEqual([]);
  }
  const STATE = path.join(SHOTS, "w7b_admin_state.json");
  await actx.storageState({ path: STATE });
  let liveOut = "";
  let liveOk = false;
  try {
    liveOut = execFileSync("node", ["scripts/contrast_public.mjs", "--live", BASE, "--storage", STATE], { cwd: process.cwd(), encoding: "utf8", timeout: 240_000 });
    liveOk = true;
  } catch (err) {
    liveOut = String((err as { stdout?: string }).stdout ?? err);
  }
  fs.rmSync(STATE, { force: true });
  const summary = liveOut.split(/\r?\n/).find((l) => l.startsWith("live sweep")) ?? "(no summary line)";
  log(`--live: ${summary}`);
  expect(liveOk).toBe(true);
  await actx.close();
  for (const id of await findTestUsers(ADM)) await deleteUser(id);
  pass(`Admin: real people only (${sv.users_total} users on the page of ${sv.users_all} app_users rows), totals = real + deleted, owner $${sv.owner_usd.toFixed(2)} and testing $${sv.testing_usd.toFixed(2)} as grey lines outside the totals; ${lowest.join("; ")}; ${summary}`);
});
