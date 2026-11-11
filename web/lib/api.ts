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

/** GET /threads: most recently active first; a thread with no message is not listed (Prompt W4). */
export type ThreadRow = {
  thread_id: string;
  created_at: string;
  last_active: string;
  is_default: boolean;
  title: string | null;
  team_label: string | null;
  fpl_team_id: number | null;
  team_name: string | null;
  updated_at: string;
};

// ---- the Chat page (Prompt W4, 2026-11-06) ---------------------------------------------------------------------------------

export type Source = { name: string; headline: string; date: string; url?: string };

/** The team card's player object (GET /me/teams/{id}/card); also the OUT / IN players of a squad-change preview. */
export type Player = {
  slot: number | null;
  id: number;
  short_name: string;
  full_name: string;
  club: string | null;
  position: "GK" | "DEF" | "MID" | "FWD" | null;
  price: number | null;
  form: number | null;
  role: "C" | "VC" | null;
  next: { opp: string | null; home: boolean; n: number } | null;
  flag: { chance: number | null; news: string | null; news_date: string | null } | null;
  pred: { points: number; source: "ours" | "fpl_est" } | null;
  in_squad: boolean;
};

export type ChangeType = "transfer" | "captain" | "vice_captain" | "bench";
export type SquadChange = { type: ChangeType; out: Player; in: Player; slot: number | null };
export type SquadPreview = {
  gw: number | null;
  expires_at: string | null;
  changes: SquadChange[];
  impact: { pts_delta: number | null; pts_horizon_gws: number | null; bank_after: number | null; ft_before: number | null; ft_after: number | null; hit_pts: number | null };
};
export type SquadApplied = { gw: number; version_id: number };

/** POST /chat */
export type ChatReply = {
  answer: string;
  thread_id: string | null;
  message_id?: string | null;
  sources?: Source[];
  squad_preview?: SquadPreview | null;
  squad_applied?: SquadApplied | null;
  capped?: boolean;
  limit?: { kind: "daily"; reset_at: string };
};

/** GET /threads/{id}/messages */
export type MessageRow =
  | { role: "user"; text: string; at: string | null }
  | { role: "pending"; text: string; started_at: string | null; message_id: string } // W7b: a turn being written
  | {
      role: "assistant";
      text: string;
      at: string | null;
      message_id: string | null;
      sources: Source[];
      squad_preview: SquadPreview | null;
      squad_applied: SquadApplied | null;
      feedback: "up" | "down" | null;
    };

export type TeamCardData = {
  team: { fpl_team_id: number; name: string; entry_name: string | null; manager_name: string | null };
  version_id: number;
  squad_as_of_gw: number;
  squad_updated_at: string;
  formation: string;
  bank: number;
  free_transfers: number | null;
  team_value: number | null;
  next_gw: number | null;
  next_deadline: string | null;
  predictions_gw: number | null;
  predictions_updated_at: string | null;
  chips: { half: { from: number; to: number }; used: number; left: number; items: { code: string; name: string; used_gw: number | null }[] } | null;
  players: Player[];
  fpl_live: boolean;
  fetched_at: string;
};

export type Feedback = "up" | "down" | null;
export type FeedbackResult = { message_id: string; feedback: Feedback; feedback_at: string; langfuse: "sent" | "skipped" | "failed" };

export type ActiveTeam = { fpl_team_id: number; label: string | null; is_active: boolean; last_imported_gw: number | null };

/** GET /me (is_owner: Prompt W5 -- user 1, the account the Delete account item is disabled for) */
export type Me = {
  user_id: number;
  is_admin: boolean;
  is_owner: boolean;
  daily_cap_usd: number;
  spent_today_usd: number;
  active_team: ActiveTeam | null;
};

// ---- Prompt W5 (2026-11-10): delete account / remove team / delete chat ------------------------------------------------------
export type DeleteAccountResult = {
  deleted: true;
  user_id: number;
  removed: Record<string, number>;
  cost_rows_anonymised: number;
  clerk: "deleted" | "already_gone";
};
export type RemoveTeamResult = {
  fpl_team_id: number;
  removed_chats: number;
  removed_squad_versions: number;
  removed_previews: number;
  removed_plans: number;
  active_team_id: number | null;
};
export type DeleteThreadResult = { thread_id: string; deleted: true; removed_messages: number; was_default: boolean };

// ---- Prompt W6 (2026-11-11): the admin page (GET /admin/summary; the owner only -- 403 for anyone else) ----------------------
export type AdminUser = {
  user_id: number;
  name: string | null;
  email: string | null;
  sign_in_method: string | null;
  joined: string | null;
  last_active: string | null;
  answers: number;
  usd: number;
  answers_today: number;
  usd_today: number;
  answers_7_days: number;
  usd_7_days: number;
  cap_hits: number;
  is_admin: boolean;
};
export type AdminCapHit = { user_id: number; name: string | null; email: string | null; at: string; spent_usd: number; cap_usd: number };
export type AdminDown = {
  message_id: string;
  thread_id: string;
  at: string | null;
  user_id: number;
  name: string | null;
  question: string | null;
  answer: string | null;
  answer_chars: number;
  answer_truncated: boolean;
  trace_id: string;
  trace_url: string | null;
};
export type AdminSummary = {
  at: string;
  users_total: number;
  sign_ups_today: number;
  sign_ups_7_days: number;
  active_today: number;
  active_7_days: number;
  answers_today: number;
  answers_total: number;
  usd_today: number;
  usd_month: number;
  usd_total: number;
  sign_ups_per_day: { day: string; n: number }[];
  users: AdminUser[];
  deleted_accounts: { answers: number; usd: number };
  owner_use: { answers: number; usd: number }; // W7b: not in the totals
  testing_use: { answers: number; usd: number }; // W7b: not in the totals
  cap_hits: AdminCapHit[];
  cap_hits_today: number;
  cap_hits_total: number;
  sign_in_methods: Record<string, number>;
  feedback: { up_total: number; down_total: number; up_7_days: number; down_7_days: number; recent_down: AdminDown[] };
  langfuse: { host: string | null; project_id: string | null };
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
  retryAfter?: number;
  threadId?: string;
  constructor(status: number, detail: string) {
    super(status ? `HTTP ${status}: ${detail}` : detail);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

export type TokenGetter = () => Promise<string | null>;

type Init = Omit<RequestInit, "body" | "headers"> & { json?: unknown; timeoutMs?: number };

/** The GET reads in flight, by path: a second concurrent read of the same path shares the first one's promise (Prompt W4:
 *  the Chat page's reads stay well under the server's 60 a minute; Next 16 re-runs a shown-again page's effects). */
const inflight = new Map<string, Promise<unknown>>();

/** One call: the token, the JSON, the error as ApiError (status 0 = no token / network, 408 = the client timeout).
 *  Retry-After (seconds) rides on a 429's error as `retryAfter`. */
export async function apiFetch<T>(getToken: TokenGetter, path: string, init: Init = {}): Promise<T> {
  const method = (init.method ?? "GET").toUpperCase();
  if (method === "GET") {
    const running = inflight.get(path);
    if (running) return running as Promise<T>;
    const p = doFetch<T>(getToken, path, init).finally(() => inflight.delete(path));
    inflight.set(path, p);
    return p;
  }
  return doFetch<T>(getToken, path, init);
}

async function doFetch<T>(getToken: TokenGetter, path: string, init: Init): Promise<T> {
  const token = await getToken();
  if (!token) throw new ApiError(401, "no session token"); // signed out meanwhile: the page sends the user to /login
  const headers: Record<string, string> = { Authorization: `Bearer ${token}` };
  const { json, timeoutMs, ...rest } = init;
  let body: string | undefined;
  if (json !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(json);
  }
  const ctl = timeoutMs ? new AbortController() : null;
  const timer = ctl ? window.setTimeout(() => ctl.abort(), timeoutMs) : null;
  let res: Response;
  try {
    res = await fetch(`${API_BASE}${path}`, { ...rest, headers, body, cache: "no-store", signal: ctl?.signal ?? rest.signal }); // every read is live, never the browser cache
  } catch (err) {
    if (ctl?.signal.aborted) throw new ApiError(408, "the answer took too long");
    throw new ApiError(0, err instanceof Error ? err.message : "network error");
  } finally {
    if (timer !== null) window.clearTimeout(timer);
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
    const err = new ApiError(res.status, detail);
    const ra = res.headers.get("Retry-After");
    if (ra && /^\d+$/.test(ra)) err.retryAfter = Number(ra);
    if (data && typeof data === "object" && "thread_id" in data) err.threadId = String((data as { thread_id: unknown }).thread_id);
    throw err;
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
  // the Chat page (Prompt W4)
  teamCard: (t: TokenGetter, fplTeamId: number) => apiFetch<TeamCardData>(t, `/me/teams/${fplTeamId}/card`),
  messages: (t: TokenGetter, threadId: string) => apiFetch<MessageRow[]>(t, `/threads/${encodeURIComponent(threadId)}/messages`),
  newThread: (t: TokenGetter) => apiFetch<{ thread_id: string }>(t, "/threads", { method: "POST" }),
  chat: (t: TokenGetter, message: string, threadId: string | null, timeoutMs = CHAT_TIMEOUT_MS) =>
    apiFetch<ChatReply>(t, "/chat", { method: "POST", json: threadId ? { message, thread_id: threadId } : { message }, timeoutMs }),
  feedback: (t: TokenGetter, messageId: string, score: Feedback) =>
    apiFetch<FeedbackResult>(t, `/messages/${encodeURIComponent(messageId)}/feedback`, { method: "POST", json: { score } }),
  // Prompt W5: the three deletes (each one transaction on the server, scoped to the signed-in user)
  deleteAccount: (t: TokenGetter) => apiFetch<DeleteAccountResult>(t, "/me", { method: "DELETE", timeoutMs: 60_000 }),
  removeTeam: (t: TokenGetter, fplTeamId: number) => apiFetch<RemoveTeamResult>(t, `/me/teams/${fplTeamId}`, { method: "DELETE", timeoutMs: 60_000 }),
  deleteThread: (t: TokenGetter, threadId: string) =>
    apiFetch<DeleteThreadResult>(t, `/threads/${encodeURIComponent(threadId)}`, { method: "DELETE", timeoutMs: 60_000 }),
  // Prompt W6: the admin page; the CSV is the P7 file (text/csv, formula-prefixed cells) read with the token and saved by the page
  adminSummary: (t: TokenGetter) => apiFetch<AdminSummary>(t, "/admin/summary"),
  adminUsersCsv: (t: TokenGetter) => apiFetch<string>(t, "/admin/users.csv"),
};

/** GET /deadlines without a token (Prompt W5: open in clerk mode -- public FPL data, cached a minute), for the About page's
 *  chips whoever is looking; the same shape as api.deadlines. */
export async function deadlinesPublic(): Promise<Deadlines> {
  const res = await fetch(`${API_BASE}/deadlines`, { cache: "no-store" });
  if (!res.ok) throw new ApiError(res.status, res.statusText);
  return (await res.json()) as Deadlines;
}

/** The brief: answers take 10-20 s and are not streamed; anything past this is system message d. */
export const CHAT_TIMEOUT_MS = 90_000;
export const MESSAGE_MAX = 2000;

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
