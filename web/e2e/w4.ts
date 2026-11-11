import { expect, type Page } from "@playwright/test";
import { execFileSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";

/** Shared helpers for the Prompt W4 browser journeys (chat-journey.spec.ts, chat-mobile.spec.ts): the laptop backend in
 *  clerk mode on http://localhost:8000 (scratchpad w4_backend.py), FPL read from the test only to pick team ids and to
 *  cross-check the card (>= 1 s apart, counted), the Clerk session token from the page, API calls with it, screenshots to
 *  the backups folder, and a small Python runner for the laptop-DB steps (test users >= 10001 only). */

export const API = process.env.W4_API_BASE ?? "http://localhost:8000";
export const SHOTS = process.env.W4_SHOTS ?? path.join("C:", "dev", "fpl-backups", "w4_chat_files");
export const REPO = path.resolve(process.cwd(), "..");
const FPL = "https://fantasy.premierleague.com/api";

export const mask = (id: number | string) => `***${String(id).slice(-3)}`;
export const fplCounter = { n: 0, last: 0 };

export async function fplGet<T>(p: string): Promise<T> {
  const wait = 1100 - (Date.now() - fplCounter.last);
  if (wait > 0) await new Promise((r) => setTimeout(r, wait));
  fplCounter.last = Date.now();
  fplCounter.n++;
  const r = await fetch(`${FPL}/${p}`, { headers: { "User-Agent": "Mozilla/5.0 (fpl-copilot W4 browser check; contact: repo owner)" } });
  if (!r.ok) throw new Error(`FPL ${p}: HTTP ${r.status}`);
  return (await r.json()) as T;
}

export type Standing = { entry: number; entry_name: string; player_name: string; rank: number; total: number };

export function shotName(page: Page, name: string) {
  const vp = page.viewportSize()!;
  return path.join(SHOTS, `${name}_${vp.width}x${vp.height}.png`);
}
export async function shot(page: Page, name: string, fullPage = false) {
  fs.mkdirSync(SHOTS, { recursive: true });
  await page.screenshot({ path: shotName(page, name), fullPage });
}

export async function token(page: Page): Promise<string> {
  const t = await page.evaluate(() => (window as unknown as { Clerk?: { session?: { getToken: () => Promise<string | null> } } }).Clerk?.session?.getToken());
  if (!t) throw new Error("no Clerk session token in the page");
  return t;
}

export async function apiCall(page: Page, method: "get" | "post" | "delete", p: string, json?: unknown, timeout = 120_000) {
  const t = await token(page);
  const r = await page.request[method](`${API}${p}`, { headers: { Authorization: `Bearer ${t}` }, data: json, timeout });
  let body: unknown = null;
  try {
    body = await r.json();
  } catch {
    body = null;
  }
  return { status: r.status(), body: body as Record<string, unknown> & { detail?: string } };
}

export async function signIn(page: Page, email: string) {
  await page.goto("/login");
  // W5b: while the login page streams in, two intro overlays can exist for a moment (the W3 lesson): the visible first one
  await page.locator('[data-testid="skip-intro"]:visible').first().click();
  await expect(page.locator(".stage").first()).toHaveAttribute("data-phase", "login");
  await page.locator("#c-email").fill(email);
  await page.getByTestId("send-code").click();
  await expect(page.getByTestId("code-sent-title")).toHaveText("Check your email");
  await page.getByTestId("otp").fill("424242");
  await page.waitForURL("**/home", { timeout: 30_000 });
}

/** the visible element with this test id: Next 16 keeps a left page mounted but hidden, so a test id can exist twice */
export const vis = (page: Page, testId: string) => page.locator(`[data-testid="${testId}"]:visible`);

/** Add a team on Home through the real dialog (the import's own FPL requests happen in the backend). */
export async function addTeamOnHome(page: Page, teamId: number, via: "choice" | "card") {
  await page.getByTestId(via === "choice" ? "choice-add-team" : "add-team-card").click();
  await expect(page.getByTestId("add-team-input")).toBeVisible();
  await page.getByTestId("add-team-input").fill(String(teamId));
  await page.getByTestId("add-team-submit").click();
  await expect(page.locator(`[data-testid="team-card"][data-team-id="${teamId}"]`)).toBeVisible({ timeout: 60_000 });
}

/** DB_* for the laptop steps, from the repo's .env, never printed. */
export function dbEnv(): NodeJS.ProcessEnv {
  const env: NodeJS.ProcessEnv = { ...process.env };
  const text = fs.readFileSync(path.join(REPO, ".env"), "utf8");
  for (const line of text.split(/\r?\n/)) {
    const m = /^([A-Z_]+)=(.*)$/.exec(line.trim());
    if (m && (m[1].startsWith("DB_") || m[1].startsWith("LANGFUSE_"))) env[m[1]] = m[2].replace(/^"|"$/g, "");
  }
  env.PYTHONIOENCODING = "utf-8";
  return env;
}

/** Run a small Python program against the laptop (repo on sys.path); its stdout is returned. */
export function py(code: string): string {
  const python = path.join(REPO, ".venv", "Scripts", "python.exe");
  return execFileSync(python, ["-X", "utf8", "-c", code], { cwd: REPO, env: dbEnv(), encoding: "utf8", timeout: 120_000 });
}

export const DB_PREFIX = `
import os, sys
sys.path[:0] = [r"${REPO.replace(/\\/g, "\\\\")}", r"${REPO.replace(/\\/g, "\\\\")}\\\\squad"]
import db_write
conn = db_write.connect()
cur = conn.cursor()
`;

/** The GET reads to the API made by the page since the counter was last reset (per chat open / per message). */
export function countApiGets(page: Page) {
  const state = { gets: 0, posts: 0, s429: 0, paths: [] as string[] };
  page.on("request", (req) => {
    if (!req.url().startsWith(API)) return;
    if (req.method() === "GET") {
      state.gets++;
      state.paths.push(new URL(req.url()).pathname);
    } else if (req.method() === "POST" || req.method() === "DELETE") state.posts++;
  });
  page.on("response", (res) => {
    if (res.url().startsWith(API) && res.status() === 429) state.s429++;
  });
  return state;
}
