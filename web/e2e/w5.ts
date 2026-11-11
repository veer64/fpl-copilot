import { expect, type Page } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";
import { DB_PREFIX, py } from "./w4";

/** Shared helpers for the Prompt W5 journeys (w5-journey.spec.ts, w5-mobile.spec.ts): screenshots to the W5 folder, the
 *  per-owner row counts on the laptop database (the isolation proof of the report), the sign-out through the menu, and the
 *  control routes of the scratchpad backend (w5_backend.py). The API base and the DB helpers are w4.ts's. */

export const SHOTS5 = process.env.W5_SHOTS ?? path.join("C:", "dev", "fpl-backups", "w5_about_privacy_files");
export const API5 = process.env.W4_API_BASE ?? "http://localhost:8010";

export async function shot5(page: Page, name: string, fullPage = false) {
  fs.mkdirSync(SHOTS5, { recursive: true });
  const vp = page.viewportSize()!;
  await page.screenshot({ path: path.join(SHOTS5, `${name}_${vp.width}x${vp.height}.png`), fullPage });
}

/** Per-table row counts for a set of owners (user ids and squad keys), plus the checkpoint rows of their threads and the
 *  check rows of their turns -- the same shape the backend tests use. */
export function ownerRows(ids: number[]): Record<string, number> {
  const out = py(`${DB_PREFIX}
import json
ids = tuple(${JSON.stringify(ids)})
out = {}
for t in ("app_users", "user_fpl_teams", "squad_versions", "squad_scores", "squad_previews", "chat_threads", "chat_messages", "chat_usage", "cap_hits", "model_transfer_plans"):
    cur.execute("SELECT count(*) FROM " + t + " WHERE user_id IN %s", (ids,)); out[t] = cur.fetchone()[0]
for t in ("fact_checks", "citation_checks", "numeric_checks"):
    cur.execute("SELECT count(*) FROM " + t + " WHERE turn_id IN (SELECT turn_id FROM chat_usage WHERE user_id IN %s)", (ids,)); out[t] = cur.fetchone()[0]
cur.execute("SELECT thread_id FROM chat_threads WHERE user_id IN %s", (ids,)); tids = [r[0] for r in cur.fetchall()]
for t in ("checkpoints", "checkpoint_blobs", "checkpoint_writes"):
    if tids:
        cur.execute("SELECT count(*) FROM " + t + " WHERE thread_id = ANY(%s)", (tids,)); out[t] = cur.fetchone()[0]
    else:
        out[t] = 0
conn.rollback()
print(json.dumps(out))
`);
  return JSON.parse(out.trim().split("\n").pop()!) as Record<string, number>;
}

export function squadKeys(userId: number): number[] {
  const out = py(`${DB_PREFIX}
import json
cur.execute("SELECT squad_key FROM user_fpl_teams WHERE user_id = %s", (${userId},)); print(json.dumps([r[0] for r in cur.fetchall()])); conn.rollback()`);
  return JSON.parse(out.trim().split("\n").pop()!) as number[];
}

/** user 1's squad guard: squad_versions rows of user 1 and of its team keys, the active version and its sha256. */
export function user1Guard(): string {
  return py(`${DB_PREFIX}
import json, hashlib
cur.execute("SELECT squad_key FROM user_fpl_teams WHERE user_id = 1"); keys = [r[0] for r in cur.fetchall()]
out = {}
for k in [1] + keys:
    cur.execute("SELECT count(*) FROM squad_versions WHERE user_id = %s", (k,)); n = cur.fetchone()[0]
    cur.execute("SELECT version_id, squad_json::text FROM squad_versions WHERE user_id = %s AND is_active", (k,)); row = cur.fetchone()
    out[str(k)] = {"count": n, "active": row[0] if row else None, "sha256": hashlib.sha256(row[1].encode()).hexdigest() if row else None}
conn.rollback()
print(json.dumps(out, sort_keys=True))
`).trim().split("\n").pop()!;
}

export function usageOf(userId: number): { turn_id: string; usd: number | null }[] {
  const out = py(`${DB_PREFIX}
import json
cur.execute("SELECT turn_id, usd FROM chat_usage WHERE user_id = %s ORDER BY id", (${userId},)); rows = [[r[0], None if r[1] is None else float(r[1])] for r in cur.fetchall()]; conn.rollback()
print(json.dumps(rows))`);
  return (JSON.parse(out.trim().split("\n").pop()!) as [string, number | null][]).map(([turn_id, usd]) => ({ turn_id, usd }));
}

export function sql1(sql: string, params: unknown[] = []): unknown {
  const out = py(`${DB_PREFIX}
import json
cur.execute(${JSON.stringify(sql)}, ${JSON.stringify(params).replace(/^\[/, "(").replace(/\]$/, ",)")}); row = cur.fetchone(); conn.rollback()
print(json.dumps(row[0] if row and len(row) == 1 else row, default=str))`);
  return JSON.parse(out.trim().split("\n").pop()!);
}

export async function signOutViaMenu(page: Page) {
  await page.locator('[data-testid="account-menu"]:visible').first().click();
  await page.locator('[data-testid="sign-out"]:visible').click();
  await page.waitForURL("**/login", { timeout: 30_000 });
}

export async function control(page: Page, method: "get" | "post", p: string) {
  const r = await page.request[method](`${API5}${p}`);
  expect(r.status(), `${p}`).toBe(200);
  return (await r.json()) as Record<string, unknown>;
}

export const boxOf = async (loc: ReturnType<Page["locator"]>) => {
  const b = await loc.boundingBox();
  return b ? { x: Math.round(b.x), y: Math.round(b.y), w: Math.round(b.width), h: Math.round(b.height) } : null;
};
