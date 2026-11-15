"""Crowd features in the minutes model -- M3 (model-upgrade plan step 3). GATED OFF, not adopted.

squad/crowd_block.py turns M2's builder (eval/crowd_features.py -- Probe A's five features) into a block of the
minutes model, behind minutes.CROWD_FEATURES_ACTIVE (default False). Pinned here:
  * the gate rests off, and with it off minutes.py asks for no crowd column and never imports the block --
    so every frame, payload and parity check is what it was (the parity suite, Tests/test_live_deadline.py,
    and M3's flag-off rebuild of the three frames of record prove the frames themselves);
  * the two forms' columns ("raw": the five; "rank": ownership + the four flow features as within-gameweek
    percentile ranks);
  * the SOURCE: the one snapshot the availability loader names for each gameweek, strictly before its
    deadline, and nothing the loader does not serve -- so the as-of guard, which cuts that loader to the
    cutoff, cuts this block with it;
  * the join: left, NaN for a player the snapshot does not carry, the row count guarded;
  * on this machine's data: the block equals M2's builder output row for row; the as-of world serves no
    gameweek after the cutoff; with the gate ON all five sub-models are fitted on the block's columns; and a
    cutoff rebuilt inside the as-of world equals the crowd frame on disk (the as-of guard with the gate on).
"""
import gzip
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "squad"))
sys.path.insert(0, str(REPO / "eval"))

import availability_features as avf  # noqa: E402
import minutes as mm  # noqa: E402

RAW = ["cs_own_pct", "cs_out_ratio", "cs_in_ratio", "cs_net_log", "cs_cost_change_event"]
RANK = ["cs_own_pct", "cs_out_ratio_rk", "cs_in_ratio_rk", "cs_net_log_rk", "cs_cost_change_event_rk"]
DATA = REPO / "data"
HAVE_DATA = (DATA / "availability_2526.parquet").exists() and (REPO / "fplcache" / "cache").exists()
M2_FILE = DATA / "m2" / "crowd_asof.parquet"
SEASON, CUTOFF = "2025-26", 20
CROWD_FRAME = DATA / "arms_crowd" / f"walkforward_h6_{SEASON.replace('-', '_')}_crowd.parquet"


# ---- the gate --------------------------------------------------------------------------------------------------

def test_the_gate_rests_off():
    assert mm.CROWD_FEATURES_ACTIVE is False
    assert mm.CROWD_FORM in ("rank", "raw")


def test_with_the_gate_off_no_crowd_column_is_asked_for_and_the_block_is_never_imported(monkeypatch):
    monkeypatch.setitem(sys.modules, "crowd_block", None)        # any import of it now raises ImportError
    assert mm.CROWD_FEATURES_ACTIVE is False
    assert mm._crowd_columns() == []


def test_with_the_gate_on_the_forms_columns(monkeypatch):
    monkeypatch.setattr(mm, "CROWD_FEATURES_ACTIVE", True)
    monkeypatch.setattr(mm, "CROWD_FORM", "raw")
    assert mm._crowd_columns() == RAW
    monkeypatch.setattr(mm, "CROWD_FORM", "rank")
    assert mm._crowd_columns() == RANK
    monkeypatch.setattr(mm, "CROWD_FORM", "ranks")
    with pytest.raises(ValueError, match="unknown crowd form"):
        mm._crowd_columns()


# ---- the source and the join, on synthetic snapshots -----------------------------------------------------------

def _snapshot(path, players, total_players=1000):
    payload = {"total_players": total_players,
               "elements": [{"id": i, "selected_by_percent": own, "transfers_in_event": tin, "transfers_out_event": tout,
                             "now_cost": 50, "cost_change_event": cc, "cost_change_start": 0}
                            for i, own, tin, tout, cc in players]}
    with gzip.open(path, "wt", encoding="utf-8") as f:
        json.dump(payload, f)


@pytest.fixture
def world(tmp_path, monkeypatch):
    """Two gameweeks of one season, each with its own snapshot; the availability loader names them."""
    import crowd_block as cb
    s1, s2 = tmp_path / "20260820T100000Z.json.gz", tmp_path / "20260827T100000Z.json.gz"
    _snapshot(s1, [(1, "10.0", 0, 0, 0), (2, "50.0", 0, 0, 0), (3, "0.0", 0, 0, 0)])
    _snapshot(s2, [(1, "10.0", 30, 10, 1), (2, "50.0", 5, 100, -1), (3, "0.0", 0, 0, 0), (4, "20.0", 40, 40, 0)])
    rows = []
    for gw, snap, when, deadline in ((1, s1, "2026-08-20 10:00", "2026-08-21 17:30"), (2, s2, "2026-08-27 10:00", "2026-08-28 17:30")):
        for element in (1, 2, 3):
            rows.append(dict(season="2026-27", gw=gw, element=element, snapshot_path=str(snap),
                             snapshot_time=pd.Timestamp(when, tz="UTC"), deadline_time=pd.Timestamp(deadline, tz="UTC")))
    av = pd.DataFrame(rows)
    av["hours_before_deadline"] = (av["deadline_time"] - av["snapshot_time"]).dt.total_seconds() / 3600
    served = {"av": av}
    monkeypatch.setattr(avf, "load", lambda data_dir=None: served["av"])
    monkeypatch.setattr(cb, "_SNAPSHOT_ROWS", {})
    return cb, served


def test_the_block_reads_the_snapshot_the_availability_loader_names(world):
    cb, _ = world
    d = cb.build().set_index(["GW", "element"])
    assert sorted(d.index.get_level_values("GW").unique()) == [1, 2]
    assert len(d) == 3 + 4, "every player of each named snapshot, incl. one the availability rows do not list"
    assert d.loc[(2, 1), "cs_own_pct"] == 10.0
    assert d.loc[(2, 1), "cs_in_ratio"] == pytest.approx(30 / 100) and d.loc[(2, 1), "cs_out_ratio"] == pytest.approx(10 / 100)
    assert d.loc[(2, 1), "cs_net_log"] == pytest.approx(np.log1p(20)) and d.loc[(2, 2), "cs_net_log"] == pytest.approx(-np.log1p(95))
    assert d.loc[(2, 2), "cs_cost_change_event"] == -1
    assert (d.loc[1, ["cs_out_ratio", "cs_in_ratio", "cs_net_log"]] == 0).all().all(), "gameweek 1: no transfers yet"


def test_the_block_serves_only_what_the_loader_serves(world):
    """The as-of property, without the modelling: cut the loader to gameweek 1 and gameweek 2's snapshot is
    not read -- even though an earlier, uncut build already holds its rows in the process cache."""
    cb, served = world
    assert sorted(cb.build()["GW"].unique()) == [1, 2]
    served["av"] = served["av"][served["av"]["gw"] <= 1]
    assert sorted(cb.build()["GW"].unique()) == [1]


def test_a_snapshot_at_or_after_its_deadline_is_refused(world):
    cb, served = world
    served["av"] = served["av"].assign(snapshot_time=served["av"]["deadline_time"])
    with pytest.raises(AssertionError, match="strictly before"):
        cb.build()


def test_the_rank_form_ranks_within_the_gameweek_and_leaves_ownership_alone(world):
    cb, _ = world
    d = cb.build()
    g2 = d[d["GW"] == 2].set_index("element")
    assert g2["cs_own_pct"].tolist() == [10.0, 50.0, 0.0, 20.0]
    assert g2["cs_net_log_rk"].tolist() == [1.0, 0.25, 0.625, 0.625]          # net +20, -95, 0, 0 -> ranks 4, 1, 2.5, 2.5 of 4
    assert set(cb.columns("rank")) <= set(d.columns) and set(cb.columns("raw")) <= set(d.columns)


@pytest.mark.parametrize("form,cols", [("raw", RAW), ("rank", RANK)])
def test_attach_is_a_left_join_with_nan_for_a_player_the_snapshot_does_not_carry(world, form, cols):
    cb, _ = world
    col = pd.DataFrame({"season": ["2026-27"] * 3 + ["2025-26"], "element": [1, 4, 9, 1], "GW": [2, 2, 2, 2], "x": [1, 2, 3, 4]})
    out = cb.attach(col, form)
    assert list(out.columns) == ["season", "element", "GW", "x"] + cols
    assert len(out) == len(col) and out["x"].tolist() == [1, 2, 3, 4]
    assert out.loc[0, cols].notna().all() and out.loc[1, cols].notna().all()
    assert out.loc[2, cols].isna().all(), "element 9 is in no snapshot"
    assert out.loc[3, cols].isna().all(), "another season's row gets nothing from this one"


def test_attach_guards_the_row_count(world, monkeypatch):
    cb, _ = world
    twice = pd.concat([cb.build(), cb.build()], ignore_index=True)
    monkeypatch.setattr(cb, "build", lambda data_dir=None: twice)
    col = pd.DataFrame({"season": ["2026-27"], "element": [1], "GW": [2]})
    with pytest.raises(ValueError, match="changed the row count"):
        cb.attach(col, "rank")


# ---- on this machine's data (skipped where data/ or the snapshot archive is not present) ----------------------

@pytest.mark.skipif(not (HAVE_DATA and M2_FILE.exists()), reason="needs the snapshot archive and data/m2/crowd_asof.parquet")
def test_the_block_equals_m2s_builder_output_row_for_row():
    """'Exactly M2's builder': the block built through the availability loader equals the file M2 built."""
    import crowd_block as cb
    key = ["season", "GW", "element"]
    mine = cb.build().sort_values(key).reset_index(drop=True)
    m2 = pd.read_parquet(M2_FILE).sort_values(key).reset_index(drop=True)
    assert len(mine) == len(m2) and (mine[key].to_numpy() == m2[key].to_numpy()).all()
    for c in RAW + RANK[1:]:
        a, b = mine[c].to_numpy(float), m2[c].to_numpy(float)
        assert (np.isnan(a) == np.isnan(b)).all(), c
        assert np.nanmax(np.abs(a - b)) == 0.0, c


@pytest.mark.skipif(not HAVE_DATA, reason="needs the snapshot archive")
def test_the_as_of_world_serves_no_gameweek_after_the_cutoff(tmp_path):
    """Inside the as-of guard's world for (season, k) the block holds gameweeks <= k of that season only;
    other seasons are whole. This is what lets the guard see the block at all."""
    import asof_reconstruction as ar
    import crowd_block as cb
    full = cb.build()
    with ar.asof_world(SEASON, CUTOFF, tmp_path):
        cut = cb.build()
    this = cut[cut["season"] == SEASON]
    assert int(this["GW"].max()) == CUTOFF and int(full[full["season"] == SEASON]["GW"].max()) == 38
    other = lambda d: d[d["season"] != SEASON]
    assert len(other(cut)) == len(other(full))
    assert sorted(cb.build()["GW"].unique())[-1] == 38, "the world is restored on exit"


@pytest.mark.skipif(not HAVE_DATA, reason="needs the history stack and the snapshot archive")
def test_with_the_gate_on_all_five_sub_models_are_fitted_on_the_block(monkeypatch):
    """Spy on every LightGBM fit of one get_minutes call (three trees each: this test reads the feature
    lists, not the predictions). Five sub-models, each fitted with the form's columns at the end of its list."""
    seen = []

    def spying(base):
        class Spy(base):
            def __init__(self, **kw):
                kw["n_estimators"] = 3
                super().__init__(**kw)

            def fit(self, X, y, **kw):
                seen.append(list(X.columns))
                return super().fit(X, y, **kw)
        return Spy

    monkeypatch.setattr(mm.lgb, "LGBMClassifier", spying(mm.lgb.LGBMClassifier))
    monkeypatch.setattr(mm.lgb, "LGBMRegressor", spying(mm.lgb.LGBMRegressor))
    monkeypatch.setattr(mm, "CROWD_FEATURES_ACTIVE", True)
    monkeypatch.setattr(mm, "CROWD_FORM", "rank")
    out = mm.get_minutes(up_to_gw=5, predict_gws=[5], per_fixture=True, availability=True,
                         train_seasons=["2022-23", "2023-24", "2024-25"], predict_season=SEASON)
    assert len(out) > 300 and out["p_start"].between(0, 1).all()
    assert len(seen) == 5, "P(start), P(60+ | start), P(came on | benched), E[min | start], E[min | sub]"
    for cols in seen:
        assert cols[-len(RANK):] == RANK
        assert cols[-len(RANK) - len(avf.FEATURES):-len(RANK)] == avf.FEATURES
    assert [len(c) for c in seen] == [16 + 9 + 5, 14 + 9 + 5, 11 + 9 + 5, 11 + 9 + 5, 8 + 9 + 5]
    frame = mm.get_minutes.last_frame
    assert frame[RANK].notna().any().all(), "the predicted rows carry the block"


@pytest.mark.skipif(not (HAVE_DATA and CROWD_FRAME.exists()), reason="needs the M3 crowd frame of 2025-26")
def test_the_as_of_guard_passes_with_the_gate_on(monkeypatch):
    """THE AS-OF GUARD ON THE BLOCK. A cutoff rebuilt from inputs cut to that deadline's information set,
    with the gate on, equals the crowd frame on disk in every non-outcome column -- the block reads nothing
    from after the cutoff. The frame is stamped; the frames of record (gate off) carry no such column."""
    import asof_reconstruction as ar
    canon = pd.read_parquet(CROWD_FRAME)
    assert bool(canon["crowd_features_active"].all()) and canon["crowd_form"].nunique() == 1
    monkeypatch.setattr(mm, "CROWD_FEATURES_ACTIVE", True)
    monkeypatch.setattr(mm, "CROWD_FORM", str(canon["crowd_form"].iloc[0]))
    frame, _ = ar.build_asof(SEASON, CUTOFF, config="baseline", horizon=6)
    table, row_ok, only_canon, only_live = ar.compare(frame, canon, CUTOFF)
    assert row_ok and not only_canon and not only_live
    assert len(table) == 0, "these columns read post-cutoff information:\n" + table.to_string(index=False)
    record = pd.read_parquet(DATA / f"walkforward_h6_{SEASON.replace('-', '_')}.parquet", columns=None).columns
    assert "crowd_features_active" not in record and "crowd_form" not in record
