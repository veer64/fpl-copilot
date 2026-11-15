"""The pure pieces of M3's Part B probes (probe code -- nothing in production imports them):
  eval/m3_midweek_probe.py   B0  which form ships: the midweek snapshot choice, the feature swap, the rule
  eval/m3_component_read.py  B2  the ranking metrics of record on two frames, with a bootstrap over gameweeks
  eval/m3_crowd_frames.py    B1  the frame comparison behind "gate off reproduces the frame of record"
The fits and the full runs are in the report (eval/reports/m3_crowd_build.md); these tests pin the arithmetic
and the rules they are read by.
"""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "squad"))
sys.path.insert(0, str(REPO / "eval"))

import m3_component_read as cr  # noqa: E402
import m3_crowd_frames as fr  # noqa: E402
import m3_midweek_probe as mw  # noqa: E402

UTC = timezone.utc


# ---- B0: the midweek snapshot ------------------------------------------------------------------------------------

def _t(day, hour=0, minute=0):
    return datetime(2026, 9, day, hour, minute, tzinfo=UTC)


def test_the_midweek_snapshot_is_the_last_one_at_or_before_72_hours():
    deadlines = {2: _t(11, 17, 30), 3: _t(18, 17, 30)}
    snaps = [(_t(7, 12), "a"), (_t(8, 17, 30), "b"), (_t(8, 17, 31), "c"), (_t(15, 6), "d"), (_t(17, 6), "e")]
    t = mw.pick_midweek(deadlines, snaps).set_index("gw")
    assert t.loc[2, "snapshot_path"] == "b", "exactly 72 h before counts ('at or before'); one minute later does not"
    assert t.loc[2, "hours_before_deadline"] == 72.0
    assert t.loc[3, "snapshot_path"] == "d" and t.loc[3, "hours_before_deadline"] == pytest.approx(83.5)
    assert not t["before_previous_deadline"].any()


def test_a_gameweek_with_no_snapshot_that_early_is_left_out_and_a_stale_one_is_flagged():
    deadlines = {1: _t(4, 17, 30), 2: _t(11, 17, 30), 3: _t(14, 17, 30)}        # gameweek 3 only three days after gameweek 2
    snaps = [(_t(4, 17, 31), "just after deadline 1"), (_t(11, 12), "before deadline 2")]
    t = mw.pick_midweek(deadlines, snaps).set_index("gw")
    assert 1 not in t.index, "nothing 72 h before the first deadline"
    assert t.loc[2, "snapshot_path"] == "just after deadline 1" and not t.loc[2, "before_previous_deadline"]
    assert t.loc[3, "snapshot_path"] == "before deadline 2" and t.loc[3, "before_previous_deadline"], \
        "72 h before gameweek 3 is still gameweek 2's week: its counters belong to gameweek 2"


def test_true_midweek_gameweeks_are_within_96_hours_and_after_the_previous_deadline():
    timing = pd.DataFrame({"season": ["x"] * 4, "gw": [2, 3, 4, 5], "hours_before_deadline": [73.0, 96.0, 167.0, 80.0],
                           "before_previous_deadline": [False, False, False, True]})
    assert mw.true_midweek_gameweeks(timing) == {"x": [2, 3]}


def test_the_swap_replaces_the_crowd_columns_only_and_keeps_the_rows():
    pf = pd.DataFrame({"season": ["s"] * 3, "GW": [5] * 3, "element": [1, 2, 3], "value": [50, 60, 70],
                       "cs_own_pct": [1.0, 2.0, 3.0], "cs_net_log": [0.1, 0.2, 0.3]}, index=[10, 20, 30])
    midweek = pd.DataFrame({"season": ["s", "s", "s"], "GW": [5, 5, 4], "element": [1, 2, 3], "cs_own_pct": [9.0, 8.0, 7.0], "cs_net_log": [-1.0, -2.0, -3.0]})
    out = mw.swap_in(pf, midweek, ["cs_own_pct", "cs_net_log"])
    assert list(out.index) == [10, 20, 30] and list(out.columns) == list(pf.columns)
    assert out["value"].tolist() == [50, 60, 70]
    assert out["cs_own_pct"].tolist()[:2] == [9.0, 8.0] and out["cs_net_log"].tolist()[:2] == [-1.0, -2.0]
    assert np.isnan(out.loc[30, "cs_own_pct"]) and np.isnan(out.loc[30, "cs_net_log"]), "no midweek row for that gameweek -> missing, never the deadline value"
    assert pf["cs_own_pct"].tolist() == [1.0, 2.0, 3.0], "the deadline frame is not touched"


@pytest.mark.parametrize("raw,rank,want", [
    ({"a": 0.10, "b": 0.10, "c": 0.10}, {"a": 0.11, "b": 0.11, "c": 0.11}, "raw"),       # raw lower in all three
    ({"a": 0.10, "b": 0.12, "c": 0.10}, {"a": 0.11, "b": 0.11, "c": 0.11}, "rank"),      # raw lower in two of three
    ({"a": 0.11, "b": 0.11, "c": 0.11}, {"a": 0.11, "b": 0.11, "c": 0.11}, "rank"),      # a tie is not "lower"
    ({"a": 0.12, "b": 0.12, "c": 0.12}, {"a": 0.11, "b": 0.11, "c": 0.11}, "rank"),
])
def test_the_shipping_form_is_rank_unless_raw_is_lower_in_every_season(raw, rank, want):
    assert mw.shipping_form(raw, rank) == want


def test_the_brier_bootstrap_resamples_whole_gameweeks():
    rng = np.random.default_rng(0)
    d = pd.DataFrame({"GW": np.repeat([2, 3, 4], [5, 7, 4]), "starts": rng.integers(0, 2, 16).astype(float),
                      "p_base": rng.uniform(0.05, 0.95, 16), "p_x": rng.uniform(0.05, 0.95, 16)})
    picks = np.array([[0, 1, 2], [0, 0, 2], [1, 1, 1]])
    got = mw.brier_delta_draws(d, "p_x", picks)
    for row, g in zip(picks, got):
        s = pd.concat([d[d.GW == [2, 3, 4][j]] for j in row])
        want = ((s.p_x - s.starts) ** 2).mean() - ((s.p_base - s.starts) ** 2).mean()
        assert g == pytest.approx(want, abs=1e-12)


class _Echo:
    """A stand-in model: 'predicts' the first crowd column it was given, scaled into (0, 1)."""
    seen = []

    def fit(self, X, y):
        _Echo.seen.append((list(X.columns), X.copy()))
        self.col = next((c for c in X.columns if c.startswith("cs_")), None)
        return self

    def predict_proba(self, X):
        p = np.full(len(X), 0.5) if self.col is None else X[self.col].fillna(-1).to_numpy(float) / 100.0
        return np.column_stack([1 - p, p])


def test_the_probe_trains_on_deadline_features_and_predicts_on_both():
    """Gameweek 3 of season 'B': the training rows carry the deadline values; the raw and rank arms are each
    predicted twice -- deadline columns, then the midweek ones -- and the baseline once."""
    import minutes as mm
    cols = sorted(set(mm.SUBF + mm.S1))
    rows = []
    for season, gw, n, lab in (("A", 1, 6, 1.0), ("B", 2, 6, 1.0), ("B", 3, 4, 0.0)):
        for e in range(1, n + 1):
            r = {c: 1.0 for c in cols}
            r.update(season=season, GW=gw, element=e, starts=lab, name=f"p{e}", av_status_code=0,
                     cs_own_pct=10.0 + e, cs_out_ratio=20.0, cs_in_ratio=30.0, cs_net_log=40.0, cs_cost_change_event=0.0,
                     cs_out_ratio_rk=0.2, cs_in_ratio_rk=0.3, cs_net_log_rk=0.4, cs_cost_change_event_rk=0.5)
            rows.append(r)
    cs = pd.DataFrame(rows)
    midweek = cs[(cs.season == "B") & (cs.GW == 3)][["season", "GW", "element"] + mw.cf.CROWD + mw.cf.RANKED].copy()
    midweek["cs_own_pct"] = 70.0
    midweek = midweek[midweek.element != 4]                       # one player has no midweek row
    _Echo.seen = []
    res = mw.walk_forward(cs, "B", ["A"], [3], ["value"], midweek, _Echo, keep=["season", "element", "GW", "starts"])
    assert [c[0][-1] for c in _Echo.seen] == ["value", "cs_cost_change_event", "cs_cost_change_event_rk"], "three fits: base, raw, rank"
    for _, X in _Echo.seen:
        assert len(X) == 12, "trained on season A and season B's gameweek 2 only"
    assert (res["p_base"] == 0.5).all()
    assert res["p_raw_dl"].tolist() == [0.11, 0.12, 0.13, 0.14] and res["p_rank_dl"].tolist() == [0.11, 0.12, 0.13, 0.14]
    assert res["p_raw_mw"].tolist() == [0.70, 0.70, 0.70, -0.01] and res["p_rank_mw"].tolist() == [0.70, 0.70, 0.70, -0.01]
    assert res["mw_present_raw"].tolist() == [True, True, True, False]


# ---- B2: the ranking metrics of record -----------------------------------------------------------------------------

def _frame(seed, n_gw=4, n=40, noise=1.0):
    rng = np.random.default_rng(seed)
    rows = []
    for gw in range(1, n_gw + 1):
        pts = rng.integers(0, 15, n).astype(float)
        e = pts + noise * rng.normal(0, 3, n)
        for i in range(n):
            rows.append(dict(element=i + 1, gw=gw, horizon_step=0, e_points=e[i], pts=pts[i], p_start=rng.uniform(0, 1),
                             n_fixtures=1 if i else 2, starts=float(rng.uniform() < 0.6)))
    return pd.DataFrame(rows)


def test_the_metrics_of_record_on_one_frame():
    from scipy.stats import spearmanr
    d = _frame(1)
    d["_key"] = d["element"] * 100 + d["gw"]
    parts = cr.by_gameweek(d, set(d.loc[d["p_start"] >= 0.75, "_key"]))
    m = cr.metrics(parts, sorted(parts))
    ls = d[d.p_start >= 0.75]
    assert m["n_ls"] == len(ls) and m["ls_rho"] == pytest.approx(spearmanr(ls.e_points, ls.pts).statistic)
    assert m["ls_rho_fixed_rows"] == pytest.approx(m["ls_rho"]), "fixed on its own likely starters = its own figure"
    top = d[d.groupby("gw")["e_points"].rank(ascending=False, method="first") <= 10]
    assert m["top10_yield"] == pytest.approx(top.groupby("gw")["pts"].mean().mean())
    t30 = d[d.groupby("gw")["e_points"].rank(ascending=False, method="first") <= 30]
    assert m["top30_rho"] == pytest.approx(spearmanr(t30.e_points, t30.pts).statistic)
    assert m["n_single"] == int((d.n_fixtures == 1).sum()), "P(start) is scored on single-fixture rows only"
    assert 0 <= m["pstart_brier"] <= 1 and 0 <= m["pstart_auc"] <= 1


def test_identical_frames_have_zero_deltas_and_zero_width_intervals():
    a, b = _frame(2), _frame(2)
    r = cr.read(a, b, nb=50)
    for k in cr.METRICS:
        assert r[k]["delta"] == 0 and r[k]["lo"] == 0 and r[k]["hi"] == 0


def test_a_sharper_frame_reads_better_and_each_frame_picks_its_own_rows():
    base, sharp = _frame(3, n_gw=6, noise=3.0), _frame(3, n_gw=6, noise=0.2)        # same truth, better e_points
    sharp["p_start"] = 1.0 - base["p_start"]                                          # a different likely-starter set
    r = cr.read(base, sharp, nb=200)
    assert r["top30_rho"]["delta"] > 0 and r["top10_yield"]["delta"] > 0
    assert r["top10_yield"]["lo"] > 0, "a clear gain clears zero"
    own = sharp[sharp["p_start"] >= 0.75]
    from scipy.stats import spearmanr
    assert r["ls_rho"]["crowd"] == pytest.approx(spearmanr(own.e_points, own.pts).statistic), "the crowd frame's OWN likely starters"
    fixed = sharp[(base["p_start"] >= 0.75).to_numpy()]
    assert r["ls_rho_fixed_rows"]["crowd"] == pytest.approx(spearmanr(fixed.e_points, fixed.pts).statistic), "the side read uses the baseline's rows"


# ---- B1: the frame comparison --------------------------------------------------------------------------------------

def test_the_frame_comparison_sees_a_value_a_nan_and_a_label():
    a = pd.DataFrame({"x": [1.0, 2.0, np.nan], "s": ["a", "b", "c"], "flag": [True, False, True]})
    assert fr.frame_diff(a, a.copy()) == (0.0, [], [], 0)
    b = a.copy(); b.loc[1, "x"] = 2.5
    assert fr.frame_diff(a, b)[:2] == (0.5, ["x"])
    c = a.copy(); c.loc[2, "x"] = 0.0
    assert fr.frame_diff(a, c)[3] == 1 and fr.frame_diff(a, c)[1] == ["x"], "a value on one side, NaN on the other"
    d = a.copy(); d.loc[0, "s"] = "z"; d.loc[0, "flag"] = False
    assert fr.frame_diff(a, d)[2] == ["s", "flag"]


def test_the_new_frames_have_their_own_names_and_nothing_is_written_over(tmp_path, monkeypatch):
    assert fr.out_path("2025-26", "crowd").name == "walkforward_h6_2025_26_crowd.parquet"
    assert fr.out_path("2025-26", "flagoff").parent.name == "arms_crowd" != fr.record_path("2025-26").parent.name
    monkeypatch.setattr(fr, "OUT", tmp_path)
    fr.out_path("2025-26", "crowd").write_bytes(b"x")
    with pytest.raises(FileExistsError):
        fr.cmd_build(type("A", (), {"season": "2025-26", "mode": "crowd", "form": "rank"})())
