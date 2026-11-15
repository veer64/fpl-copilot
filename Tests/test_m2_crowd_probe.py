"""M2 (model-upgrade plan step 2): the crowd-signal confirmation probe -- PROBE CODE, nothing in production imports it.

eval/crowd_features.py is Probe A's feature builder (X2, PR-6) brought into the repo unchanged in substance and extended
to read the live season's snapshots: five features from the ONE bootstrap snapshot an availability file names as the
last strictly before each deadline -- raw snapshot fields, never the asof_ late-news patch, never the history table's
deadline-final counts. eval/m2_crowd_probe.py is Probe A's walk-forward and scoring with the pre-registered M2 rule.

These tests pin the pieces a wrong number could hide in: the five formulas, the strictly-before rule, the left join, the
rank transform of the secondary arm, the slices (fixed on the BASELINE arm), the bootstrap over gameweeks, the pooling,
the walk-forward's training rows and the verdict rule. The fits themselves are checked against M1's builds and X2's
rows by the run (eval/reports/m2_crowd_confirm.md), not here.
"""
import gzip
import json
import lzma
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "squad"))
sys.path.insert(0, str(ROOT / "eval"))

import crowd_features as cf  # noqa: E402
import m2_crowd_probe as probe  # noqa: E402

X2_CROWD = Path(r"C:\dev\research\x2\work\crowd_asof.parquet")


def _payload(total_players=1_000_000, elements=None):
    return {"total_players": total_players, "elements": elements or [
        {"id": 1, "selected_by_percent": "10.0", "transfers_in_event": 5_000, "transfers_out_event": 20_000,
         "now_cost": 60, "cost_change_event": -1, "cost_change_start": 2},
        {"id": 2, "selected_by_percent": "0.0", "transfers_in_event": 3, "transfers_out_event": 0,
         "now_cost": 45, "cost_change_event": 0, "cost_change_start": 0}]}


def _av(season_gws, path="snap.json.gz", snap="2026-08-28 17:10:06+00:00", deadline="2026-08-28 17:30:00+00:00"):
    return pd.DataFrame([{"gw": g, "snapshot_path": path, "snapshot_time": pd.Timestamp(snap),
                          "deadline_time": pd.Timestamp(deadline), "hours_before_deadline": 0.33} for g in season_gws])


# ------------------------------------------------------------------ the five features
def test_the_five_features_are_probe_a_formulas():
    d = cf.features(cf.rows_from_payload("2026-27", 2, _payload(), 0.33))
    a, b = d.set_index("element").loc[1], d.set_index("element").loc[2]
    assert a["cs_own_pct"] == 10.0
    assert a["cs_out_ratio"] == pytest.approx(20_000 / 100_000)          # out / owners, owners = own% x total players
    assert a["cs_in_ratio"] == pytest.approx(5_000 / 100_000)
    assert a["cs_net_log"] == pytest.approx(-np.log1p(15_000))           # sign(net) * log1p(|net|), net = in - out
    assert a["cs_cost_change_event"] == -1
    assert b["cs_in_ratio"] == pytest.approx(3.0), "owners are floored at 1, so nobody divides by zero"
    assert b["cs_net_log"] == pytest.approx(np.log1p(3))
    assert list(cf.CROWD) == ["cs_own_pct", "cs_out_ratio", "cs_in_ratio", "cs_net_log", "cs_cost_change_event"]
    assert list(cf.FLOW) == ["cs_out_ratio", "cs_in_ratio", "cs_net_log", "cs_cost_change_event"]


def test_snapshots_are_read_from_xz_and_gz(tmp_path):
    with lzma.open(tmp_path / "a.json.xz", "wt", encoding="utf-8") as f:
        json.dump(_payload(), f)
    with gzip.open(tmp_path / "b.json.gz", "wt", encoding="utf-8") as f:
        json.dump(_payload(total_players=7), f)
    assert cf.read_snapshot(tmp_path / "a.json.xz")["total_players"] == 1_000_000
    assert cf.read_snapshot(tmp_path / "b.json.gz")["total_players"] == 7
    with pytest.raises(ValueError, match="snapshot"):
        cf.read_snapshot(tmp_path / "c.json")


def test_a_snapshot_at_or_after_the_deadline_is_refused():
    ok = cf.snapshot_table(_av([1, 2]))
    assert list(ok["gw"]) == [1, 2]
    with pytest.raises(AssertionError, match="strictly before"):
        cf.snapshot_table(_av([1], snap="2026-08-28 17:30:00+00:00"))
    with pytest.raises(AssertionError, match="strictly before"):
        cf.snapshot_table(_av([1], snap="2026-08-28 18:00:00+00:00"))


def test_one_snapshot_per_gameweek_and_only_the_naming_columns_are_read():
    """The builder takes WHICH snapshot from the availability file and nothing else of it: an availability frame
    with no asof_ column at all is enough, and two snapshots named for one gameweek is refused."""
    av = _av([1, 1, 2])                                                   # two rows of gameweek 1, same snapshot: fine
    assert len(cf.snapshot_table(av)) == 2
    bad = pd.concat([_av([1]), _av([1], path="other.json.gz")], ignore_index=True)
    with pytest.raises(AssertionError, match="one snapshot"):
        cf.snapshot_table(bad)
    assert not [c for c in cf.NAMING_COLUMNS if c.startswith("asof_")]


def test_build_reads_the_named_snapshot_of_each_gameweek(tmp_path):
    (tmp_path / "data").mkdir()
    for name, tp in (("g1.json.gz", 1_000_000), ("g2.json.gz", 2_000_000)):
        with gzip.open(tmp_path / name, "wt", encoding="utf-8") as f:
            json.dump(_payload(total_players=tp), f)
    av = pd.concat([_av([1], path="g1.json.gz"), _av([2], path="g2.json.gz")], ignore_index=True)
    av["season"] = "2026-27"
    av["asof_status"] = "i"                                               # present in the real file, never read here
    av.to_parquet(tmp_path / "data" / "availability_2627.parquet", index=False)
    d = cf.build(["2026-27"], data_dir=tmp_path / "data", repo=tmp_path)
    assert len(d) == 4 and not d.duplicated(["season", "GW", "element"]).any()
    one = d[(d.GW == 1) & (d.element == 1)].iloc[0]
    two = d[(d.GW == 2) & (d.element == 1)].iloc[0]
    assert one["cs_out_ratio"] == pytest.approx(0.2) and two["cs_out_ratio"] == pytest.approx(0.1)
    assert set(d["snapshot_path"]) == {"g1.json.gz", "g2.json.gz"}


def test_attach_is_a_left_join_and_a_player_missing_from_the_snapshot_is_nan():
    crowd = cf.features(cf.rows_from_payload("2026-27", 2, _payload(), 0.33))
    col = pd.DataFrame({"season": ["2026-27"] * 3, "element": [1, 2, 99], "GW": [2, 2, 2],
                        "selected": [1, 2, 3], "transfers_in": [9, 9, 9]})   # the history table's deadline-final counts
    out = cf.attach(col, crowd)
    assert len(out) == 3 and list(out["element"]) == [1, 2, 99]
    assert out.loc[2, list(cf.CROWD)].isna().all(), "no snapshot row -> NaN, never a zero"
    assert out.loc[0, "cs_own_pct"] == 10.0, "the feature is the SNAPSHOT's ownership, not the history table's `selected`"
    with pytest.raises(ValueError, match="row count"):
        cf.attach(col, pd.concat([crowd, crowd], ignore_index=True))


def test_the_rank_arm_ranks_the_four_flow_features_within_a_gameweek_and_leaves_ownership():
    d = pd.DataFrame({"season": ["A"] * 4 + ["A"] * 2, "GW": [1] * 4 + [2] * 2, "element": [1, 2, 3, 4, 1, 2],
                      "cs_own_pct": [5.0, 1.0, 9.0, 0.0, 5.0, 1.0],
                      "cs_out_ratio": [0.1, 0.4, 0.2, np.nan, 100.0, 200.0],
                      "cs_in_ratio": [0.0, 0.0, 0.0, 0.0, 1.0, 2.0],
                      "cs_net_log": [-3.0, 2.0, 0.0, 1.0, 5.0, -5.0],
                      "cs_cost_change_event": [0, 0, 1, -1, 0, 0]})
    r = cf.to_ranks(d)
    assert list(r["cs_own_pct"]) == list(d["cs_own_pct"]), "ownership is not ranked"
    assert list(cf.RANKED) == [c + "_rk" for c in cf.FLOW]
    g1 = r[r.GW == 1]
    assert list(g1["cs_out_ratio_rk"].iloc[:3].round(4)) == [round(1 / 3, 4), 1.0, round(2 / 3, 4)], "rank over the values present"
    assert np.isnan(g1["cs_out_ratio_rk"].iloc[3]), "a missing value stays missing"
    assert set(g1["cs_in_ratio_rk"]) == {0.625}, "ties share the average rank: (1+2+3+4)/4 / 4"
    assert list(r[r.GW == 2]["cs_out_ratio_rk"]) == [0.5, 1.0], "a gameweek is ranked on its own, whatever its scale"
    assert list(r[r.GW == 2]["cs_net_log_rk"]) == [1.0, 0.5]


def test_timing_skew_over_two_hours_calls_for_the_rank_arm():
    assert probe.needs_rank_arm(train_median_hours=4.4, test_median_hours=0.16)
    assert probe.needs_rank_arm(train_median_hours=1.0, test_median_hours=3.5)
    assert not probe.needs_rank_arm(train_median_hours=4.4, test_median_hours=2.5)
    assert not probe.needs_rank_arm(train_median_hours=4.4, test_median_hours=6.4), "more than 2 h, not 2 h or more"


@pytest.mark.skipif(not (X2_CROWD.exists() and (ROOT / "fplcache" / "cache").exists()
                         and (ROOT / "data" / "availability_2425.parquet").exists()),
                    reason="X2's Probe A feature file or the fplcache archive is not on this machine")
def test_the_builder_reproduces_x2s_probe_a_features_on_a_real_season():
    """Reuse, not reinvention: 2024-25 rebuilt here equals the file Probe A was run on, value for value."""
    mine = cf.build(["2024-25"]).sort_values(["GW", "element"]).reset_index(drop=True)
    x2 = pd.read_parquet(X2_CROWD)
    x2 = x2[x2["season"] == "2024-25"].sort_values(["GW", "element"]).reset_index(drop=True)
    assert len(mine) == len(x2) == 27_479
    for c in cf.CROWD + ["hours_before_deadline"]:
        a, b = mine[c].to_numpy(float), x2[c].to_numpy(float)
        assert ((a == b) | (np.isnan(a) & np.isnan(b))).all(), c


# ------------------------------------------------------------------ slices, metrics, bootstrap, pooling
def _scored():
    return pd.DataFrame({"GW": [1, 1, 1, 2, 2, 2], "starts": [1, 0, 1, 1, 0, 0],
                         "p_base": [0.80, 0.80, 0.50, 0.75, 0.24, 0.90],
                         "p_crowd": [0.90, 0.10, 0.99, 0.70, 0.80, 0.60],
                         "av_status_code": [0, 2, 0, 0, 0, 0]})


def test_slices_are_fixed_on_the_baseline_arm():
    s = probe.slices(_scored())
    assert list(s) == ["ALL", "LS", "UNCERTAIN", "LS-UNFLAGGED"]
    assert len(s["ALL"]) == 6
    assert list(s["LS"].index) == [0, 1, 3, 5], "p_base >= 0.75 -- 0.75 itself is in; the treated arm's value plays no part"
    assert list(s["UNCERTAIN"].index) == [2], "0.25 <= p_base < 0.75"
    assert list(s["LS-UNFLAGGED"].index) == [0, 3, 5], "likely starter AND FPL status 'a' (code 0)"


def test_metrics_by_hand():
    d = pd.DataFrame({"starts": [1, 0, 1, 0], "p": [0.9, 0.2, 0.6, 0.4]})
    m = probe.metrics(d, "p")
    assert m["brier"] == pytest.approx((0.01 + 0.04 + 0.16 + 0.16) / 4)
    assert m["logloss"] == pytest.approx(-(np.log(0.9) + np.log(0.8) + np.log(0.6) + np.log(0.6)) / 4)
    assert m["auc"] == 1.0
    assert np.isnan(probe.metrics(d[d.starts == 1], "p")["auc"]), "one class only -> no AUC, not a crash"


class _FirstGroupRng:
    """Always draws gameweek index 0, so a draw is that gameweek repeated."""
    def integers(self, lo, hi, n):
        return np.zeros(n, dtype=int)


def test_the_bootstrap_resamples_whole_gameweeks():
    d = _scored()
    draws = probe.bootstrap_deltas(d, "p_base", "p_crowd", _FirstGroupRng(), nb=3)
    gw1 = d[d.GW == 1]
    want = probe.metrics(gw1, "p_crowd")["brier"] - probe.metrics(gw1, "p_base")["brier"]
    assert draws["brier"].shape == (3,) and np.allclose(draws["brier"], want)
    assert set(draws) == {"brier", "logloss", "auc"}


def test_pooled_is_the_mean_across_seasons_draw_by_draw():
    a, b, c = np.array([-0.002, 0.000, -0.004]), np.array([-0.001, -0.003, 0.002]), np.array([0.0, 0.0, -0.001])
    p = probe.pooled([a, b, c])
    assert np.allclose(p, [-0.001, -0.001, -0.001])
    lo, hi = probe.interval(np.linspace(-1, 1, 2001))
    assert lo == pytest.approx(-0.95) and hi == pytest.approx(0.95)


# ------------------------------------------------------------------ the pre-registered verdict
@pytest.mark.parametrize("ls_auc,all_brier,pooled_ci,want", [
    (+0.010, -0.0010, (-0.0020, -0.0001), "PASS"),
    (+0.010, -0.0010, (-0.0020, +0.0001), "INCONCLUSIVE"),      # (a) holds, the pooled interval touches zero
    (+0.010, -0.0010, (-0.0020, 0.0), "INCONCLUSIVE"),          # entirely below 0 means the upper end is < 0
    (-0.001, -0.0010, (-0.0020, -0.0001), "FAIL"),              # (a) fails on the likely-starter AUC
    (+0.010, +0.0002, (-0.0020, -0.0001), "FAIL"),              # (a) fails on the all-rows Brier
    (0.0, -0.0010, (-0.0020, -0.0001), "FAIL"),                 # "delta > 0" is strict
    (+0.010, 0.0, (-0.0020, -0.0001), "FAIL"),                  # "delta < 0" is strict
])
def test_the_verdict_is_the_pre_registered_rule(ls_auc, all_brier, pooled_ci, want):
    assert probe.verdict(ls_auc_delta_2026=ls_auc, all_brier_delta_2026=all_brier, pooled_all_brier_ci=pooled_ci) == want


# ------------------------------------------------------------------ the walk-forward
class _Spy:
    """Stands in for LightGBM: remembers what it was trained on and predicts a constant."""
    calls = []

    def fit(self, X, y):
        _Spy.calls.append(dict(columns=list(X.columns), n=len(X), y=list(y), index=list(X.index)))
        return self

    def predict_proba(self, X):
        assert (X["is_double_gw"] == 0).all(), "prediction asks for one ordinary fixture"
        return np.column_stack([np.full(len(X), 0.7), np.full(len(X), 0.3)])


def _frame():
    import minutes as mm
    rows = []
    for season, gws in (("2025-26", [1, 2]), ("2026-27", [1, 2, 3])):
        for gw in gws:
            for el in (1, 2):
                rows.append({"season": season, "element": el, "GW": gw,
                             "starts": np.nan if (season, gw) == ("2026-27", 3) else float(el == 1),
                             "name": f"p{el}", "av_status_code": 0})
    cs = pd.DataFrame(rows)
    for c in sorted(set(mm.S1 + mm.SUBF)):
        cs[c] = 1.0
    cs["is_double_gw"] = [1 if i == 4 else 0 for i in range(len(cs))]
    cs["f_base"], cs["f_extra"] = 0.5, 0.25
    return cs


def test_the_walk_forward_trains_on_earlier_labelled_rows_only_and_scores_both_arms_on_the_same_rows():
    _Spy.calls = []
    cs = _frame()
    arms = {"base": ["is_double_gw", "f_base"], "crowd": ["is_double_gw", "f_base", "f_extra"]}
    out = probe.walk_forward_arms(cs, "2026-27", ["2025-26"], gws=[1, 2, 3], arms=arms, make_model=_Spy,
                                  arms_for_gw=lambda k: ["base"] if k == 3 else ["base", "crowd"])
    by = {(c["n"], tuple(c["columns"])) for c in _Spy.calls}
    # gameweek 1: the prior season only (4 rows); gameweek 2: + this season's gameweek 1 (6); gameweek 3: + gameweek 2 (8)
    assert [c["n"] for c in _Spy.calls] == [4, 4, 6, 6, 8], [c["n"] for c in _Spy.calls]
    assert (8, ("is_double_gw", "f_base")) in by and (8, ("is_double_gw", "f_base", "f_extra")) not in by, \
        "the unlabelled gameweek is predicted by the baseline arm only (it is there for the exactness check)"
    assert all(not np.isnan(v) for c in _Spy.calls for v in c["y"]), "an unlabelled row is never trained on"
    assert len(out) == 6 and list(out["GW"]) == [1, 1, 2, 2, 3, 3]
    assert out["p_base"].notna().all() and out.loc[out.GW < 3, "p_crowd"].notna().all() and out.loc[out.GW == 3, "p_crowd"].isna().all()
    assert "is_double_gw_orig" in out.columns and int(out["is_double_gw_orig"].sum()) == 1, "the real flag is kept for the record"
    assert int(cs["is_double_gw"].sum()) == 1, "the caller's frame is not modified"


def test_outputs_are_never_written_over_an_existing_file(tmp_path):
    p = tmp_path / "rows.parquet"
    probe.write_new(pd.DataFrame({"a": [1]}), p)
    assert p.exists()
    with pytest.raises(FileExistsError):
        probe.write_new(pd.DataFrame({"a": [2]}), p)
    assert pd.read_parquet(p)["a"].tolist() == [1]
