"""The same-squad head-to-head from a reference record -- the measuring instrument of M3 B3
(squad/pathcontrol.window_run / summarise_head_to_head, eval/m3_head_to_head.py).

Two arms are restarted from the SAME squad state at an anchor gameweek -- the reference record's own state,
rebuilt by replaying its log -- and played for a few gameweeks with the simulator of record itself. Three things
make that a fair instrument, and each is pinned here on a small synthetic season:
  * the state can be rebuilt at EVERY anchor, including after a Free Hit week (replay_state used to stop there);
  * a window plans each of its gameweeks against the WHOLE season's calendar, so its last weeks are not planned
    like a season's last weeks (simulate_season's `plan_gws`; the default is unchanged behaviour);
  * an arm restarted from a state on its OWN record reproduces that record exactly -- the determinism the
    comparison rests on, checked rather than assumed (the full run checks it on every anchor of the real seasons).
Plus the summary: per-season mean and block-bootstrap interval over anchors, and the pooled line.
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "squad"))
sys.path.insert(0, str(REPO / "eval"))
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import pathcontrol as pc  # noqa: E402
import simulator  # noqa: E402
import squad_state  # noqa: E402
from test_optimize import make_random_pool  # noqa: E402

N_GWS, HORIZON, SECOND_HALF = 8, 2, 5
SCHEDULE = dict(wildcard_gws=[2, 7], free_hit_gws=[5], triple_captain_gw=6, second_half_start=SECOND_HALF)


def _season(seed, shift=0.0):
    """A horizon-aware synthetic season (see Tests/test_chip_week_free_transfers.py). `shift` perturbs the
    predictions only -- a second ARM over the same realised outcomes."""
    base = make_random_pool(seed)
    rng = np.random.default_rng(seed)
    pts = {g: np.round(rng.uniform(0, 10, len(base)), 2) for g in range(1, N_GWS + 1)}
    act = {g: rng.integers(0, 12, len(base)) for g in range(1, N_GWS + 1)}
    noise = np.random.default_rng(seed + 1000)
    frames = []
    for k in range(1, N_GWS + 1):
        for g in range(k, min(k + HORIZON, N_GWS + 1)):
            p = base.copy()
            p["e_points"] = np.round(pts[g] + shift * noise.uniform(-3, 3, len(base)), 2).clip(0)
            p["actual_points"], p["minutes"] = act[g], 90
            p["cutoff"], p["gw"] = k, g
            frames.append(p)
    return pd.concat(frames, ignore_index=True)


def _stored(log):
    """A decision log as an armlog stores it (the columns replay_state reads)."""
    d = log.copy()
    d["all_transfers"] = d["all_transfers"].map(lambda t: [[int(a), int(b)] for a, b in t])
    return d


@pytest.fixture(scope="module")
def record():
    df = _season(7)
    _, log = simulator.simulate_season(df, policy="mip", horizon=HORIZON, decay=0.45, verbose=False, **SCHEDULE)
    return df, log


# ---- plan_gws ------------------------------------------------------------------------------------------------------

def test_plan_gws_defaults_to_the_gameweeks_played(record):
    """Unchanged behaviour: naming the played gameweeks as the calendar gives the same season."""
    df, log = record
    _, again = simulator.simulate_season(df, policy="mip", horizon=HORIZON, decay=0.45, verbose=False,
                                         plan_gws=list(range(1, N_GWS + 1)), **SCHEDULE)
    for c in ("points", "hit", "n_transfers", "captain", "free_transfers", "bank"):
        assert again[c].tolist() == log[c].tolist(), c
    assert [sorted(map(tuple, t)) for t in again["all_transfers"]] == [sorted(map(tuple, t)) for t in log["all_transfers"]]


def test_a_window_plans_against_the_whole_season(record, monkeypatch):
    """Playing gameweeks 3-4 only: with the season's calendar the planner at gameweek 4 still sees gameweek 5;
    without it the window's last week is planned like the season's last week (one gameweek)."""
    import run_arms_full_system as rafs
    df, log = record
    seen = {}
    real = simulator.build_and_solve

    def spy(pools, **kw):
        seen[next(iter(pools))] = len(pools)
        return real(pools, **kw)

    monkeypatch.setattr(simulator, "build_and_solve", spy)
    pc.window_run(df, [3, 4], rafs.replay_state(_stored(log), df, 2), schedule=SCHEDULE, horizon=HORIZON)
    assert seen == {3: HORIZON, 4: HORIZON}
    seen.clear()
    simulator.simulate_season(df, policy="mip", horizon=HORIZON, decay=0.45, verbose=False, gws=[3, 4],
                              initial_state=rafs.replay_state(_stored(log), df, 2), **SCHEDULE)
    assert seen == {3: HORIZON, 4: 1}


# ---- the record's state at every anchor, incl. after a Free Hit ------------------------------------------------------

def test_replaying_a_log_goes_through_a_free_hit_week(record):
    """The Free Hit squad is handed back: after gameweek 5 the state holds the squad of gameweek 4, the bank
    and free transfers the log carries forward, and the season's points. Asserted against the log at every
    gameweek inside replay_state."""
    import run_arms_full_system as rafs
    df, log = record
    by = log.set_index("gw")
    assert bool(by.loc[5, "free_hit"]) and int(by.loc[5, "n_transfers"]) > 0, "the scenario needs a Free Hit that changes the squad"
    state = rafs.replay_state(_stored(log), df, 5)
    assert set(state.elements) == set(int(e) for e in by.loc[4, "elements"]), "the pre-chip squad is back"
    assert set(state.elements) != set(int(e) for e in by.loc[5, "elements"])
    assert state.bank == int(by.loc[5, "bank"]) and state.free_transfers == int(by.loc[5, "free_transfers"])
    end = rafs.replay_state(_stored(log), df, N_GWS)
    assert end.total_points == int(by.loc[N_GWS, "total_points"]) and end.free_transfers == int(by.loc[N_GWS, "free_transfers"])


def test_a_log_written_under_the_old_chip_week_rule_replays_through_its_free_hit(monkeypatch):
    """A log without the stamp earned a free transfer in its Free Hit week too (KNOWN_ISSUES #30)."""
    import run_arms_full_system as rafs
    df = _season(7)
    monkeypatch.setattr(squad_state, "CHIP_WEEK_FREE_TRANSFERS_EARNED", 1)
    _, old = simulator.simulate_season(df, policy="mip", horizon=HORIZON, decay=0.45, verbose=False, **SCHEDULE)
    monkeypatch.setattr(squad_state, "CHIP_WEEK_FREE_TRANSFERS_EARNED", 0)
    by = old.set_index("gw")
    assert int(by.loc[5, "free_transfers"]) == int(by.loc[4, "free_transfers"]) + 1
    end = rafs.replay_state(_stored(old.drop(columns=["chip_week_free_transfers_earned"])), df, N_GWS)
    assert end.free_transfers == int(by.loc[N_GWS, "free_transfers"])


@pytest.mark.parametrize("W", [1, 3])
def test_an_arm_restarted_from_its_own_record_reproduces_it_at_every_anchor(record, W):
    """THE DETERMINISM THE COMPARISON RESTS ON. From the record's state at anchor k (none at k = 1: the opening
    pick), the same frame under the same chip schedule plays the record's own gameweeks k..k+W-1 -- every
    anchor, before, on and after each chip week."""
    import run_arms_full_system as rafs
    df, log = record
    by = log.set_index("gw")
    for k in range(1, N_GWS - W + 2):
        state = rafs.replay_state(_stored(log), df, k - 1) if k > 1 else None
        win = pc.window_run(df, list(range(k, k + W)), state, schedule=SCHEDULE, horizon=HORIZON).set_index("gw")
        for g in range(k, k + W):
            assert int(win.loc[g, "points"]) == int(by.loc[g, "points"]), f"anchor {k}, GW{g}"
            assert sorted(map(tuple, win.loc[g, "all_transfers"])) == sorted(map(tuple, by.loc[g, "all_transfers"])), f"anchor {k}, GW{g}"
            assert win.loc[g, "captain"] == by.loc[g, "captain"] and int(win.loc[g, "free_transfers"]) == int(by.loc[g, "free_transfers"])
            assert bool(win.loc[g, "wildcard"]) == bool(by.loc[g, "wildcard"]) and bool(win.loc[g, "free_hit"]) == bool(by.loc[g, "free_hit"])
            assert bool(win.loc[g, "triple_captain"]) == bool(by.loc[g, "triple_captain"])


def test_two_arms_start_a_window_from_the_same_squad(record):
    """A second arm (other predictions, same outcomes) restarted at anchor 4: both arms hold the record's squad
    at that deadline; what they do from there is their own."""
    import run_arms_full_system as rafs
    df, log = record
    other = _season(7, shift=1.0)
    held = set(int(e) for e in log.set_index("gw").loc[3, "elements"])
    for frame in (df, other):
        state = rafs.replay_state(_stored(log), df, 3)
        assert set(state.elements) == held
        win = pc.window_run(frame, [4, 5, 6], state, schedule=SCHEDULE, horizon=HORIZON)
        assert win["gw"].tolist() == [4, 5, 6] and len(win.loc[win["gw"] == 4, "elements"].iloc[0]) == 15


# ---- the logs of record on disk (skipped where data/ is not present) ------------------------------------------------

_FRAMES = {}


def _frame(season):
    if season not in _FRAMES:
        wf = REPO / "data" / f"walkforward_h6_{season.replace('-', '_')}.parquet"
        _FRAMES[season] = simulator.load_season(walkforward_path=str(wf), horizon_aware=True, season=season)
    return _FRAMES[season]


@pytest.mark.parametrize("season", ["2023-24", "2024-25", "2025-26"])
@pytest.mark.parametrize("suffix", ["", "_m1", "_m3a"])
def test_the_logs_of_record_replay_through_the_whole_season(season, suffix):
    """All 38 gameweeks of every reference log -- through Wildcard 1, Free Hit 2 and Wildcard 2, each under the
    rule ITS log was written with -- so the record's state exists at every anchor of the head-to-head."""
    import run_arms_full_system as rafs
    tag = season.replace("-", "_")
    log_path = REPO / "data" / "arms" / f"armlog_{tag}_gap0_tc2{suffix}.parquet"
    if not (log_path.exists() and (REPO / "data" / f"walkforward_h6_{tag}.parquet").exists()):
        pytest.skip(f"{log_path.name} or its frame is not on this machine")
    log = pd.read_parquet(log_path)
    state = rafs.replay_state(log, _frame(season), 38)
    last = log.set_index("gw").loc[38]
    assert state.total_points == int(last["total_points"]) == int(log["final_total"].iloc[0])
    assert state.free_transfers == int(last["free_transfers"]) and state.bank == int(last["bank"])


# ---- the summary ----------------------------------------------------------------------------------------------------

def test_the_summary_is_a_mean_per_season_and_over_every_anchor():
    d = {"2023-24": pd.Series([2.0] * 33, index=range(1, 34)), "2024-25": pd.Series([-1.0] * 33, index=range(1, 34)),
         "2025-26": pd.Series([5.0] * 30, index=range(1, 31))}
    s = pc.summarise_head_to_head(d).set_index("season")
    assert s.loc["2023-24", "mean_delta"] == 2.0 and s.loc["2024-25", "mean_delta"] == -1.0 and s.loc["2025-26", "mean_delta"] == 5.0
    assert s.loc["pooled", "n_anchors"] == 96
    assert s.loc["pooled", "mean_delta"] == pytest.approx((2 * 33 - 33 + 5 * 30) / 96, abs=1e-3)
    assert s.loc["2023-24", "ci_low"] == s.loc["2023-24", "ci_high"] == 2.0, "no spread, no interval width"
    assert s.loc["pooled", "seasons_positive"] == 2
    assert (s.loc["2023-24", "treated_better"], s.loc["2024-25", "reference_better"], s.loc["2023-24", "tied"]) == (33, 33, 0)


def test_identical_arms_summarise_to_zero():
    d = {s: pd.Series(np.zeros(33), index=range(1, 34)) for s in ("a", "b", "c")}
    s = pc.summarise_head_to_head(d).set_index("season")
    assert (s["mean_delta"] == 0).all() and (s["ci_low"] == 0).all() and (s["ci_high"] == 0).all() and (s["tied"].iloc[:3] == 33).all()


def test_the_interval_resamples_blocks_of_anchors_and_brackets_the_mean():
    rng = np.random.default_rng(3)
    d = {s: pd.Series(rng.normal(3.0, 8.0, 33), index=range(1, 34)) for s in ("a", "b", "c")}
    s = pc.summarise_head_to_head(d, block=4, n_boot=500).set_index("season")
    for name in ("a", "b", "c", "pooled"):
        assert s.loc[name, "ci_low"] < s.loc[name, "mean_delta"] < s.loc[name, "ci_high"]
    assert (s.loc["pooled", "ci_high"] - s.loc["pooled", "ci_low"]) < min(s.loc[n, "ci_high"] - s.loc[n, "ci_low"] for n in ("a", "b", "c")), \
        "three seasons pooled are tighter than any one"
    again = pc.summarise_head_to_head(d, block=4, n_boot=500).set_index("season")
    assert again.equals(s), "seeded: the same draws every time"


# ---- the driver's pieces --------------------------------------------------------------------------------------------

def test_the_anchors_are_every_gameweek_whose_window_fits():
    import m3_head_to_head as h
    t = h.tasks_for("2025-26")
    assert [k for k, n in t if n == 6] == list(range(1, 34)) and [k for k, n in t if n == 3] == [34, 35, 36]


def test_a_three_gameweek_window_is_the_first_three_weeks_of_the_six_week_run():
    import json
    import m3_head_to_head as h
    rows = []
    for arm, pts in (("base", [10, 20, 30, 40, 50, 60]), ("crowd", [11, 20, 33, 40, 50, 54])):
        for i, p in enumerate(pts):
            rows.append(dict(anchor=5, arm=arm, gw=5 + i, points=p, hit=4 if (arm == "crowd" and i == 2) else 0, bench_points=7,
                             all_transfers=json.dumps([[1, 2]] if (arm == "crowd" and i == 0) else []), captain="A" if i else arm))
    d = pd.DataFrame(rows)
    six, three = h.window_deltas(d, 6, bb_weeks={7}), h.window_deltas(d, 3, bb_weeks={7})
    assert six["delta"].tolist() == [-2] and three["delta"].tolist() == [4]
    assert three["first_week_transfers_differ"].tolist() == [True] and three["first_week_captain_differs"].tolist() == [True]
    assert six["weeks_transfers_differ"].tolist() == [1] and six["hits_crowd"].tolist() == [4]
    assert six["delta_with_bb_bench"].tolist() == [-2], "both arms' bench counts in the Bench Boost week"
