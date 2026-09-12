# db_write.py -- the scheduler's Postgres writer, called by run_live_deadline
# AFTER a successful build+solve. Schema notes (designed from the REAL frame,
# not the sketch -- see Logs/app_wiring_log.md):
#
#   * the frame's grain is (element, TARGET gw) at ONE cutoff -- horizon_step
#     is derived (gw - cutoff), there is no separate step dimension;
#   * there is NO price column in the frame (prices join from master+skeleton
#     at solve time), so price lives on picks and players_live, never on
#     predictions;
#   * model_version is not a single field anywhere in the build -- the honest
#     version is the frame's config-stamp column set plus the git SHA, so
#     runs carry git_sha + the full stamp as JSONB and model_version is
#     "<git_sha_short>/<config>";
#   * every config the runner built lands per run, distinguished by the
#     `config` column; which one is production is config_roles.PRODUCTION_CONFIG
#     ('baseline' since 2026-09-11; no shadow) -- reads for users filter on it
#     explicitly, never on a literal.
#
# Predictions are KEPT (append per run), never overwritten: the season
# accumulates a live track record keyed by run_id.
#
# FAILURE CONTRACT: a write failure after a successful build must not be
# silent -- the caller (run_live_deadline) puts the exception in the status
# file AND exits non-zero, and /health goes stale because no run row landed.

import json
import os
from datetime import datetime, timezone
from pathlib import Path

import psycopg2

REPO = Path(__file__).resolve().parent

DDL = """
CREATE TABLE IF NOT EXISTS model_runs (
    run_id       SERIAL PRIMARY KEY,
    season       TEXT NOT NULL,
    gw           INT  NOT NULL,
    started_at   TIMESTAMPTZ,
    finished_at  TIMESTAMPTZ NOT NULL,
    status       TEXT NOT NULL,             -- SUCCESS / FAILED
    recovered    BOOLEAN NOT NULL DEFAULT FALSE,
    git_sha      TEXT,
    model_stamp  JSONB,                     -- per-config stamp columns from the frame
    strict_findings JSONB,                  -- per-config note lists
    credits_remaining INT,
    note         TEXT
);
CREATE TABLE IF NOT EXISTS model_predictions (
    run_id       INT NOT NULL REFERENCES model_runs(run_id),
    config       TEXT NOT NULL,             -- the config name; production = config_roles.PRODUCTION_CONFIG
    element      INT NOT NULL,
    gw           INT NOT NULL,              -- TARGET gameweek
    cutoff       INT NOT NULL,
    horizon_step INT NOT NULL,
    e_points     REAL, e_points_core REAL, exp_bonus REAL,
    e_minutes    REAL, p_start REAL, p_60plus REAL, p_play_any REAL,
    e_goals      REAL, e_assists REAL, p_cs REAL,
    PRIMARY KEY (run_id, config, element, gw)
);
CREATE INDEX IF NOT EXISTS ix_pred_lookup
    ON model_predictions (config, gw, element, run_id);
CREATE TABLE IF NOT EXISTS model_picks (
    run_id       INT NOT NULL REFERENCES model_runs(run_id),
    config       TEXT NOT NULL,
    element      INT NOT NULL,
    name         TEXT, position TEXT, team TEXT,
    role         TEXT NOT NULL,             -- CAPTAIN / VICE / start / bench
    bench_order  INT,                       -- 1..4 for bench rows, NULL otherwise
    price_tenths INT,
    e_points     REAL,
    PRIMARY KEY (run_id, config, element)
);
-- model_transfer_plans + model_transfers: every six-week transfer-MIP PROPOSAL,
-- append-only like model_predictions (Decision 3, 2026-09-12). These REPLACED
-- the original model_transfers(run_id, config, element_out, element_in,
-- hit_cost, gain_6gw), designed 2026-09-04 from the inspected frame for a runner
-- that would write one row per executed transfer per run. The runner never ran
-- the MIP, the table stayed empty, and when the MIP went live (2026-09-12) the
-- grain could not hold what a proposal IS: no proposal identity (two solves in
-- one run were indistinguishable), no squad_version_id (a proposal is solved
-- FROM a squad), no horizon step (the plan is six gameweeks, only step 0 is
-- executable), no prices (sold_for / bought_for are the money claim), and no
-- way to record a HOLD (zero transfers = zero rows = indistinguishable from
-- "never solved"). Empty and unreferenced, it was DROPPED on the server on
-- 2026-09-12 and recreated at this grain rather than migrated. A header row per
-- proposal; one transfers row per (step, out, in); a hold is a header with no
-- transfer rows. squad_version_id is a plain INT (squad_versions lives in
-- squad_store's DDL, which need not exist on a fresh database when this runs).
CREATE TABLE IF NOT EXISTS model_transfer_plans (
    proposal_id       SERIAL PRIMARY KEY,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    source            TEXT NOT NULL,            -- chat | deadline_run
    user_id           INT  NOT NULL DEFAULT 1,
    season            TEXT NOT NULL,
    gw                INT  NOT NULL,            -- the deadline step 0 is for
    squad_version_id  INT  NOT NULL,            -- solved FROM this squad_versions row
    run_id            INT REFERENCES model_runs(run_id),   -- the run whose frame was solved
    config            TEXT NOT NULL,
    frame_cutoff_gw   INT  NOT NULL,
    stale_by_gameweeks INT NOT NULL,            -- gw - frame_cutoff_gw (0 = fresh frame)
    horizon           INT  NOT NULL,
    effective_horizon INT  NOT NULL,
    decay             REAL NOT NULL,
    hit_bar           REAL NOT NULL,
    locked            JSONB NOT NULL,
    banned            JSONB NOT NULL,
    status            TEXT NOT NULL,            -- solver status
    objective         REAL,
    n_transfers       INT  NOT NULL,            -- step 0
    hits              INT  NOT NULL,
    hit_cost_points   INT  NOT NULL,
    free_transfers_before INT NOT NULL,
    free_transfers_after  INT NOT NULL,
    bank_before       INT  NOT NULL,            -- tenths
    bank_after        INT  NOT NULL,
    captain           INT, vice INT,
    predicted_xi_points REAL,
    hold_applied      BOOLEAN,
    solve_seconds     REAL,
    git_sha           TEXT,
    note              TEXT
);
CREATE TABLE IF NOT EXISTS model_transfers (
    transfer_id   SERIAL PRIMARY KEY,
    proposal_id   INT NOT NULL REFERENCES model_transfer_plans(proposal_id),
    horizon_step  INT NOT NULL,
    gw            INT NOT NULL,
    element_out   INT, name_out TEXT,
    element_in    INT, name_in  TEXT,
    sold_for      INT,                          -- tenths; exact at step 0, NULL later (see comment)
    bought_for    INT,
    executable    BOOLEAN NOT NULL               -- true only for step 0
);
COMMENT ON COLUMN model_transfers.sold_for IS
    'Tenths. At horizon_step 0 the exact sell price under FPL''s rule (purchase + half the rise '
    'rounded down; falls in full), computed by squad_store.plan_change from the recorded purchase '
    'price and the current price. NULL at every later step BY DESIGN, not by omission: the MIP does '
    'not track purchase prices inside the horizon (its money model values owned players at their '
    'step-0 sell value at every step and everyone else at that step''s market price), so a later-step '
    'sell price would be invented, not computed. Only step 0 is executable.';
COMMENT ON COLUMN model_transfers.bought_for IS
    'Tenths. At step 0 the current players_live price (what set_my_squad would charge). At later '
    'steps the market price the frame carried for that gameweek AS SEEN FROM the frame''s cutoff -- '
    'indicative, like everything beyond step 0.';
COMMENT ON COLUMN model_transfers.executable IS
    'TRUE only for horizon_step 0: the one move a rolling-horizon plan actually proposes. Later '
    'steps are what the solver expects to want next, re-solved from fresh data each deadline.';
COMMENT ON COLUMN model_transfer_plans.source IS
    'chat = a user request through the agent; deadline_run = the T-90 runner (option B, NOT wired '
    'as of 2026-09-12); proof = a maintainer''s build/verification run, not a user request -- '
    'exclude from any track record.';
CREATE TABLE IF NOT EXISTS players_live (
    element      INT PRIMARY KEY,
    name         TEXT, position TEXT, team TEXT,
    price_tenths INT,
    status       TEXT, chance INT, news TEXT,
    updated_at   TIMESTAMPTZ NOT NULL
);
"""

STAMP_COLS = [
    "season_label", "minutes_availability", "odds_horizon_gws", "dgw_handling",
    "dc_rule_active", "d1_terms_active", "cs_unified", "penalty_fix_active",
    "topend_cal_active", "fixture_scale_gamma", "bonus_mode", "rate_blend_active",
    "rate_blend_k", "synthetic_lambda_active", "train_seasons", "arm",
    "props_active", "props_spec", "horizon_minutes_active", "horizon_levers",
]

PRED_COLS = ["e_points", "e_points_core", "exp_bonus", "e_minutes", "p_start",
             "p_60plus", "p_play_any", "e_goals", "e_assists", "p_cs"]


def connect():
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "localhost"),
        port=os.getenv("DB_PORT", "5432"),
        dbname=os.getenv("DB_NAME", "fpl"),
        user=os.getenv("DB_USER", "postgres"),
        password=os.getenv("DB_PASSWORD", ""),
    )


def git_sha():
    """Short SHA from .git without a git binary (the image has none)."""
    try:
        head = (REPO / ".git" / "HEAD").read_text().strip()
        if head.startswith("ref:"):
            ref = head.split(None, 1)[1]
            return (REPO / ".git" / ref).read_text().strip()[:9]
        return head[:9]
    except OSError:
        return None


def ensure_schema(conn):
    with conn.cursor() as cur:
        cur.execute(DDL)
    conn.commit()


PLAN_COLS = ["source", "user_id", "season", "gw", "squad_version_id", "run_id", "config",
             "frame_cutoff_gw", "stale_by_gameweeks", "horizon", "effective_horizon", "decay",
             "hit_bar", "locked", "banned", "status", "objective", "n_transfers", "hits",
             "hit_cost_points", "free_transfers_before", "free_transfers_after", "bank_before",
             "bank_after", "captain", "vice", "predicted_xi_points", "hold_applied",
             "solve_seconds", "git_sha", "note"]
TRANSFER_COLS = ["horizon_step", "gw", "element_out", "name_out", "element_in", "name_in",
                 "sold_for", "bought_for", "executable"]


def write_proposal(header, rows):
    """One MIP proposal -> one model_transfer_plans row + its model_transfers
    rows (append-only). header: dict with PLAN_COLS (locked/banned as lists);
    rows: list of dicts with TRANSFER_COLS. Returns proposal_id.

    Refuses loudly if model_transfers is still at the ORIGINAL 2026-09-04 grain
    (no proposal_id column): the server table must be dropped and recreated
    (see the DDL comment) -- an insert into the wrong grain would be a silent
    lie about what was recorded."""
    conn = connect()
    try:
        ensure_schema(conn)
        with conn.cursor() as cur:
            cur.execute("""SELECT 1 FROM information_schema.columns
                           WHERE table_name = 'model_transfers' AND column_name = 'proposal_id'""")
            if cur.fetchone() is None:
                raise RuntimeError(
                    "model_transfers is at the original (2026-09-04) grain with no proposal_id; "
                    "drop it and let ensure_schema recreate it (see the DDL comment in db_write.py)")
            vals = [header.get(c) for c in PLAN_COLS]
            for i, c in enumerate(PLAN_COLS):
                if c in ("locked", "banned"):
                    vals[i] = json.dumps(list(vals[i] or []))
            cur.execute(
                f"INSERT INTO model_transfer_plans ({', '.join(PLAN_COLS)}) VALUES "
                f"({', '.join(['%s'] * len(PLAN_COLS))}) RETURNING proposal_id", vals)
            pid = cur.fetchone()[0]
            if rows:
                cur.executemany(
                    f"INSERT INTO model_transfers (proposal_id, {', '.join(TRANSFER_COLS)}) VALUES "
                    f"({', '.join(['%s'] * (len(TRANSFER_COLS) + 1))})",
                    [(pid,) + tuple(r.get(c) for c in TRANSFER_COLS) for r in rows])
        conn.commit()
        return pid
    finally:
        conn.close()


def write_failed_run(season, gw, note):
    """Best-effort FAILED marker so /health can surface a failed run even
    when the status file goes unread. Never raises -- a DB outage here must
    not mask the original failure."""
    try:
        conn = connect()
        try:
            ensure_schema(conn)
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO model_runs (season, gw, finished_at, status,
                           git_sha, note)
                       VALUES (%s,%s,%s,'FAILED',%s,%s)""",
                    (season, gw, datetime.now(timezone.utc), git_sha(),
                     (note or "")[:2000]))
            conn.commit()
        finally:
            conn.close()
        return True
    except Exception:
        return False


def write_run(season, gw, frames, teams, findings_by, started_at=None,
              recovered=False, credits_remaining=None, note=None,
              availability=None, prices=None, git=None):
    """One pipeline execution -> one model_runs row + per-config children.

    frames: {config: DataFrame}; teams: {config: solved-team DataFrame with
    role (+ bench order = frame order of bench rows)}; findings_by:
    {config: [str]}; availability: {element: (status, chance, news)};
    prices: {element: price_tenths}. Returns run_id."""
    conn = connect()
    try:
        ensure_schema(conn)
        stamp = {}
        for config, f in frames.items():
            row = f.iloc[0]
            stamp[config] = {c: (row[c].item() if hasattr(row[c], "item") else row[c])
                             for c in STAMP_COLS if c in f.columns}
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO model_runs (season, gw, started_at, finished_at,
                       status, recovered, git_sha, model_stamp, strict_findings,
                       credits_remaining, note)
                   VALUES (%s,%s,%s,%s,'SUCCESS',%s,%s,%s,%s,%s,%s)
                   RETURNING run_id""",
                (season, gw, started_at, datetime.now(timezone.utc), recovered,
                 git or git_sha(), json.dumps(stamp, default=str),
                 json.dumps(findings_by, default=str), credits_remaining, note))
            run_id = cur.fetchone()[0]

            for config, f in frames.items():
                rows = []
                for _, r in f.iterrows():
                    rows.append((run_id, config, int(r["element"]), int(r["gw"]),
                                 int(r["cutoff"]), int(r["gw"]) - int(r["cutoff"]))
                                + tuple(None if r[c] != r[c] else float(r[c])
                                        for c in PRED_COLS))
                cur.executemany(
                    """INSERT INTO model_predictions VALUES
                       (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""", rows)

            for config, team in teams.items():
                bench_order = 0
                for _, r in team.iterrows():
                    bo = None
                    if r["role"] == "bench":
                        bench_order += 1
                        bo = bench_order
                    cur.execute(
                        """INSERT INTO model_picks VALUES
                           (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                        (run_id, config, int(r["element"]), r["name"], r["position"],
                         str(r["team"]), r["role"], bo, int(r["value"]),
                         float(r["e_points"])))

            if availability is not None or prices is not None:
                from config_roles import PRODUCTION_CONFIG
                f = frames[PRODUCTION_CONFIG] if PRODUCTION_CONFIG in frames else next(iter(frames.values()))
                ident = f[f["gw"] == gw][["element", "name", "position", "team"]]
                now = datetime.now(timezone.utc)
                def _int_or_none(x):
                    # NA-proof: pd.NA/np.nan/None -> None, numerics -> int
                    try:
                        f = float(x)
                        return None if f != f else int(f)
                    except (TypeError, ValueError):
                        return None

                def _str_or_none(x):
                    try:
                        if x is None or x != x:
                            return None
                    except (TypeError, ValueError):
                        return None
                    s = str(x)
                    return s if s and s.lower() not in ("nan", "<na>") else None

                for _, r in ident.iterrows():
                    e = int(r["element"])
                    st, ch, news = (availability or {}).get(e, (None, None, None))
                    cur.execute(
                        """INSERT INTO players_live VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                           ON CONFLICT (element) DO UPDATE SET
                             name=EXCLUDED.name, position=EXCLUDED.position,
                             team=EXCLUDED.team, price_tenths=EXCLUDED.price_tenths,
                             status=EXCLUDED.status, chance=EXCLUDED.chance,
                             news=EXCLUDED.news, updated_at=EXCLUDED.updated_at""",
                        (e, r["name"], r["position"], str(r["team"]),
                         (prices or {}).get(e),
                         _str_or_none(st), _int_or_none(ch),
                         _str_or_none(news), now))
        conn.commit()
        return run_id
    finally:
        conn.close()
