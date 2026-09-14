"""
The term columns on model_predictions (Logs/model_predictions_terms_log.md): the DDL adds every
term column idempotently and never rewrites rows; the INSERT names its columns and carries the
terms; NaN / absent -> NULL; the production frame carries every term column (so a NULL on a new
run would be a defect). No database: the row builder and the SQL text are pure.

Run:
    uv run pytest Tests/test_db_write_terms.py -v
"""

import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

import db_write                                            # noqa: E402
import explain                                             # noqa: E402

FRAME = REPO / "data" / "live" / "_tmp_frame_baseline.parquet"


def test_ddl_adds_every_term_column_idempotently_and_documents_the_null():
    for c in db_write.TERM_COLS:
        assert re.search(rf"ALTER TABLE model_predictions ADD COLUMN IF NOT EXISTS {c}\s+(REAL|TEXT|INT);", db_write.DDL), c
    assert "COMMENT ON TABLE model_predictions" in db_write.DDL and "never backfilled" in db_write.DDL
    assert "UPDATE model_predictions" not in db_write.DDL and "DEFAULT" not in db_write.DDL.split("model_predictions ADD COLUMN")[1].split(";")[0]


def test_insert_names_its_columns_and_the_placeholders_match():
    cols = db_write.PRED_INSERT_COLS
    sql = db_write.prediction_insert_sql(cols)
    assert sql.startswith("INSERT INTO model_predictions (run_id, config, element, gw, cutoff, horizon_step, e_points")
    assert sql.count("%s") == len(cols) == 6 + len(db_write.PRED_COLS) + len(db_write.TERM_COLS)
    assert cols[-2:] == ["understat_id", "n_fixtures"]


def _frame(**over):
    r = dict(element=411, gw=5, cutoff=4, e_points=5.1, e_points_core=5.1, exp_bonus=0.0, e_minutes=87.3,
             p_start=0.97, p_60plus=0.97, p_play_any=0.979, e_goals=0.7, e_assists=0.158, p_cs=0.368,
             pts_appear=1.96, pts_goals=2.8, pts_assists=0.47, pts_cs=0.0, pts_dc=0.01, pts_saves=0.0,
             pts_conceded=0.0, pts_cards=-0.15, e_pen_goals=0.0, penalty_share=0.083, team_pen_rate=0.0,
             p60=1.0, minutes_frac=0.97, p_dc_hit=0.005, team_lambda=1.284, opp_lambda=1.0,
             fixture_scale_cal=0.917, npxg90=0.79, xa90=0.18, saves_per_90=0.0, yellow_per_90=0.143,
             red_per_90=0.005, understat_id=8260.0, n_fixtures=1)
    r.update(over)
    return pd.DataFrame([r])


def test_rows_carry_the_terms_and_nan_or_absent_become_null():
    cols, rows = db_write.prediction_rows(7, "baseline", _frame())
    row = dict(zip(cols, rows[0]))
    assert row["run_id"] == 7 and row["horizon_step"] == 1 and row["pts_goals"] == pytest.approx(2.8)
    assert row["understat_id"] == "8260" and row["n_fixtures"] == 1 and row["team_lambda"] == pytest.approx(1.284)
    cols, rows = db_write.prediction_rows(7, "baseline", _frame(pts_saves=np.nan, understat_id=np.nan))
    row = dict(zip(cols, rows[0]))
    assert row["pts_saves"] is None and row["understat_id"] is None
    f = _frame().drop(columns=["pts_cards", "n_fixtures"])
    cols, rows = db_write.prediction_rows(7, "baseline", f)
    row = dict(zip(cols, rows[0]))
    assert row["pts_cards"] is None and row["n_fixtures"] is None and row["pts_goals"] == pytest.approx(2.8)


def test_term_columns_are_exactly_what_the_breakdown_reads():
    """Every column explain.breakdown reads per row is stored: the eight terms, the sub-line, the inputs."""
    needed = set(explain.CORE) | {"exp_bonus", "e_pen_goals", "penalty_share", "team_pen_rate", "p60", "minutes_frac",
                                  "p_dc_hit", "team_lambda", "opp_lambda", "fixture_scale_cal", "npxg90", "xa90",
                                  "saves_per_90", "yellow_per_90", "red_per_90", "understat_id", "n_fixtures",
                                  "p_start", "p_60plus", "p_play_any", "e_goals", "e_assists", "p_cs", "e_points", "e_points_core"}
    stored = set(db_write.PRED_COLS) | set(db_write.TERM_COLS)
    assert needed <= stored, sorted(needed - stored)


@pytest.mark.skipif(not FRAME.exists(), reason="live frame not on this machine")
def test_production_frame_carries_every_term_column_and_rows_build_without_null_terms():
    f = pd.read_parquet(FRAME)
    missing = [c for c in db_write.TERM_COLS if c not in f.columns]
    assert not missing, missing
    cols, rows = db_write.prediction_rows(99, "baseline", f.head(50))
    for r in rows:
        d = dict(zip(cols, r))
        assert all(d[c] is not None for c in explain.CORE), d
