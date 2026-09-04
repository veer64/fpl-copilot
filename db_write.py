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
#   * both configs land per run, distinguished by the `config` column
#     ('combined' = production, 'baseline' = shadow) -- reads for users
#     filter config='combined' explicitly.
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
    config       TEXT NOT NULL,             -- 'combined' (production) / 'baseline' (shadow)
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
CREATE TABLE IF NOT EXISTS model_transfers (
    run_id       INT NOT NULL REFERENCES model_runs(run_id),
    config       TEXT NOT NULL,
    element_out  INT, element_in INT,
    hit_cost     INT, gain_6gw REAL
);
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
                f = frames.get("combined") or next(iter(frames.values()))
                ident = f[f["gw"] == gw][["element", "name", "position", "team"]]
                now = datetime.now(timezone.utc)
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
                         st, None if ch != ch else (int(ch) if ch is not None else None),
                         news, now))
        conn.commit()
        return run_id
    finally:
        conn.close()
