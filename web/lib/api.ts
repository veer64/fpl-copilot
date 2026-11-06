/** The backend as the website sees it (Prompt W3, 2026-11-05). Every value on /home comes from here, over
 *  NEXT_PUBLIC_API_BASE with the browser's Clerk session token (Authorization: Bearer); nothing is mocked. */

export const API_BASE = (process.env.NEXT_PUBLIC_API_BASE ?? "").replace(/\/$/, "");

/** GET /me/teams: one card per imported team (fpl_teams.CARD_COLS). */
export type TeamCard = {
  fpl_team_id: number;
  label: string | null;
  is_active: boolean;
  last_imported_gw: number | null;
  entry_name: string | null;
  manager_name: string | null;
  total_points: number | null;
  overall_rank: number | null;
  last_gw: number | null;
  last_gw_points: number | null;
  updated_after_gw: number | null;
  summary_updated_at: string | null;
  last_used_at: string | null;
  created_at: string;
  last_imported_at: string | null;
};

/** GET /threads: most recently active first. */
export type ThreadRow = {
  thread_id: string;
  created_at: string;
  last_active: string;
  is_default: boolean;
  title: string | null;
  team_label: string | null;
  fpl_team_id: number | null;
};

export type ActiveTeam = { fpl_team_id: number; label: string | null; is_active: boolean; last_imported_gw: number | null };

/** GET /me */
export type Me = {
  user_id: number;
  is_admin: boolean;
  daily_cap_usd: number;
  spent_today_usd: number;
  active_team: ActiveTeam | null;
};

export type DeadlineEvent = { gw: number; deadline_time: string; finished: boolean };
/** GET /deadlines */
export type Deadlines = { events: DeadlineEvent[]; fetched_at: string };

/** POST /me/teams/{id}/activate and DELETE /me/active-team both name the default thread the next chat will use. */
export type ActivateResult = ActiveTeam & { thread_id: string; preview_tickets_cancelled: number };
export type DeactivateResult = { active_team: null; deactivated: number | null; thread_id: string; preview_tickets_cancelled: number };

export class ApiError extends Error {
  status: number;
  detail: string;
  constructor(status: number, detail: string) {
    super(status ? `HTTP ${status}: ${detail}` : detail);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

export type TokenGetter = () => Promise<string | null>;

type Init = Omit<RequestInit, "body" | "headers"> & { json?: unknown };

/** One call: the token, the JSON, the error as ApiError (status 0 = no token / network). */
export async function apiFetch<T>(getToken: TokenGetter, path: string, init: Init = {}): Promise<T> {
  const token = await getToken();
  if (!token) throw new ApiError(0, "no session token");
  const headers: Record<string, string> = { Authorization: `Bearer ${token}` };
  const { json, ...rest } = init;
  let body: string | undefined;
  if (json !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(json);
  }
  let res: Response;
  try {
    res = await fetch(`${API_BASE}${path}`, { ...rest, headers, body });
  } catch (err) {
    throw new ApiError(0, err instanceof Error ? err.message : "network error");
  }
  const text = await res.text();
  let data: unknown = null;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    data = text;
  }
  if (!res.ok) {
    const detail =
      data && typeof data === "object" && "detail" in data ? String((data as { detail: unknown }).detail) : text || res.statusText;
    throw new ApiError(res.status, detail);
  }
  return data as T;
}

export const api = {
  me: (t: TokenGetter) => apiFetch<Me>(t, "/me"),
  teams: (t: TokenGetter) => apiFetch<TeamCard[]>(t, "/me/teams"),
  threads: (t: TokenGetter) => apiFetch<ThreadRow[]>(t, "/threads"),
  deadlines: (t: TokenGetter) => apiFetch<Deadlines>(t, "/deadlines"),
  addTeam: (t: TokenGetter, fplTeamId: number, label?: string) =>
    apiFetch<TeamCard>(t, "/me/teams", { method: "POST", json: label ? { fpl_team_id: fplTeamId, label } : { fpl_team_id: fplTeamId } }),
  activate: (t: TokenGetter, fplTeamId: number) => apiFetch<ActivateResult>(t, `/me/teams/${fplTeamId}/activate`, { method: "POST" }),
  refresh: (t: TokenGetter, fplTeamId: number) => apiFetch<TeamCard>(t, `/me/teams/${fplTeamId}/refresh`, { method: "POST" }),
  deactivate: (t: TokenGetter) => apiFetch<DeactivateResult>(t, "/me/active-team", { method: "DELETE" }),
};

export const FPL_TEAM_ID_MAX = 99_999_999;

/** An FPL team id typed as a number ("1234567") or pasted inside a link (the digits after /entry/), else null. */
export function parseTeamInput(raw: string): number | null {
  const s = raw.trim();
  if (!s) return null;
  let digits: string | null = null;
  if (/^\d{1,9}$/.test(s)) digits = s;
  else {
    const m = s.match(/\/entry\/(\d{1,9})(?=[/?#]|$)/i);
    if (m) digits = m[1];
  }
  if (digits === null) return null;
  const n = Number(digits);
  return n >= 1 && n <= FPL_TEAM_ID_MAX ? n : null;
}
