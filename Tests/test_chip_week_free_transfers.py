"""The free transfer a Wildcard / Free Hit week does NOT earn -- KNOWN_ISSUES #30 (found by M1 on 2026-11-14,
fixed by M3 on 2026-11-15).

FPL: in a Wildcard or Free Hit week every transfer is free, the free transfers already banked are KEPT, and
no new one is earned that week. That is the rule the live import derives from FPL's own hit charges
(fpl_import.derive_free_transfers -- "a wildcard / free hit week spends none and earns none" -- pinned on a
saved real team history by Tests/test_fpl_import.py::test_i3_the_recorded_hit_fits_only_no_earning_in_a_chip_week).
Until M3 the simulator kept the bank AND earned one: banked + 1 after every in-sim chip. The reference
configuration plays three (Wildcard 1 at gameweek 2, Free Hit 2, Wildcard 2), so every reference season held
one free transfer too many after each -- with the record's gameweek-2 Wildcard, TWO at the gameweek-3
deadline where FPL gives ONE.

Pinned here, on a small synthetic season so it runs in the unit suite:
  * the rule itself for every season the full-system simulator is run on and for each of the three in-sim
    chips, in the order that season's schedule of record plays them (the simulator has ONE rule set for every
    season -- the 2025-26 rules by project convention, squad/chip_legality.py -- so the season chooses the
    synthetic data and the order of Free Hit 2 and Wildcard 2);
  * one free transfer at the gameweek-3 deadline after the gameweek-2 Wildcard, in the state AND in what the
    planner is handed;
  * the ledger: the simulator's own free-transfer column and hit charges equal the live import's rule on the
    simulator's own transfers, every gameweek (0 extra hits);
  * the transfer MIP plans the week after a wildcard step from the same bank, not the bank plus one;
  * the path-control replay follows the same rule;
  * the provenance stamp `chip_week_free_transfers_earned` on every decision-log row, and that replaying a log
    follows the log's OWN rule: a log without the stamp was written before 2026-11-15 and earned one in a chip
    week, so the M1 record and every older armlog still replay gameweek by gameweek;
  * the old rule is one constant away (squad_state.CHIP_WEEK_FREE_TRANSFERS_EARNED = 1), nothing else moved.
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

import simulator  # noqa: E402
import squad_state  # noqa: E402
from squad_state import MAX_FREE_TRANSFERS, SquadState  # noqa: E402
from test_optimize import make_random_pool  # noqa: E402
from test_transfer_mip import a_squad  # noqa: E402
from transfer_mip import build_and_solve  # noqa: E402

# Every season the full-system simulator is run on (eval/run_full_system.py holds their chip weeks).
SEASONS = ["2023-24", "2024-25", "2025-26"]
SEED = {"2023-24": 7, "2024-25": 11, "2025-26": 23}
N_GWS, HORIZON, SECOND_HALF = 8, 2, 5
CHIPS = ["wildcard_1", "free_hit_2", "wildcard_2"]


def _season(seed, n_gws=N_GWS):
    """A horizon-aware synthetic season: one row per (cutoff, gameweek, player). Predictions differ by
    gameweek so there is something to transfer for; what happened is fixed per (gameweek, player)."""
    base = make_random_pool(seed)
    rng = np.random.default_rng(seed)
    pts = {g: np.round(rng.uniform(0, 10, len(base)), 2) for g in range(1, n_gws + 1)}
    act = {g: rng.integers(0, 12, len(base)) for g in range(1, n_gws + 1)}
    frames = []
    for k in range(1, n_gws + 1):
        for g in range(k, min(k + HORIZON, n_gws + 1)):
            p = base.copy()
            p["e_points"], p["actual_points"], p["minutes"] = pts[g], act[g], 90
            p["cutoff"], p["gw"] = k, g
            frames.append(p)
    return pd.concat(frames, ignore_index=True)


def _schedule(season):
    """The season's three in-sim chips on the short calendar, in the ORDER its schedule of record plays them:
    Wildcard 1 at gameweek 2 (as the record), then Free Hit 2 and Wildcard 2 at gameweeks 5 and 7."""
    import run_full_system as rfs
    second = sorted([("free_hit_2", rfs.FH2[season]), ("wildcard_2", rfs.WC2[season])], key=lambda x: x[1])
    weeks = {"wildcard_1": 2, second[0][0]: 5, second[1][0]: 7}
    return weeks


_RUNS = {}


def _run(season):
    """One simulated season with all three chips; cached -- several tests read the same log."""
    if season not in _RUNS:
        weeks = _schedule(season)
        df = _season(SEED[season])
        _, log = simulator.simulate_season(
            df, policy="mip", horizon=HORIZON, decay=0.45, verbose=False, second_half_start=SECOND_HALF,
            wildcard_gws=[weeks["wildcard_1"], weeks["wildcard_2"]], free_hit_gws=[weeks["free_hit_2"]])
        _RUNS[season] = (df, log.set_index("gw"), weeks)
    return _RUNS[season]


def test_the_seasons_of_record_are_the_ones_covered():
    """A fourth simulated season must be added to SEASONS above, or this fails."""
    import run_full_system as rfs
    assert sorted(rfs.WC2) == SEASONS and sorted(rfs.FH2) == SEASONS


def test_the_rule_is_none_earned():
    assert squad_state.CHIP_WEEK_FREE_TRANSFERS_EARNED == 0


# ---- (1) the rule, every season, every in-sim chip -----------------------------------------------------------------

@pytest.mark.parametrize("season", SEASONS)
@pytest.mark.parametrize("chip", CHIPS)
def test_a_chip_week_keeps_the_banked_free_transfers_and_earns_none(season, chip):
    """`free_transfers` in a log row is the count CARRIED FORWARD, so the row before the chip week is what the
    manager held at the chip week's deadline and the chip week's own row is what he holds at the next one.
    They must be equal: nothing spent, nothing earned. Until M3 the second was the first plus one."""
    _, log, weeks = _run(season)
    g = weeks[chip]
    assert bool(log.loc[g, "wildcard" if chip.startswith("wildcard") else "free_hit"]), f"GW{g} is not the {chip} week"
    assert int(log.loc[g, "hit"]) == 0, "a chip week never pays a hit"
    held_at_the_chip_deadline = int(log.loc[g - 1, "free_transfers"])
    held_at_the_next_deadline = int(log.loc[g, "free_transfers"])
    assert held_at_the_next_deadline == held_at_the_chip_deadline


@pytest.mark.parametrize("season", SEASONS)
def test_one_free_transfer_at_the_gameweek_3_deadline_after_the_gameweek_2_wildcard(season):
    """The record's own case: Wildcard 1 at gameweek 2. One free transfer is held at gameweek 2 (the opening,
    KNOWN_ISSUES #29), the Wildcard keeps it and earns none -> ONE at the gameweek-3 deadline. The M1 record
    had two there."""
    _, log, weeks = _run(season)
    assert weeks["wildcard_1"] == 2 and bool(log.loc[2, "wildcard"])
    assert int(log.loc[1, "free_transfers"]) == 1
    assert int(log.loc[2, "free_transfers"]) == 1


def test_the_planner_at_gameweek_3_is_handed_one_free_transfer(monkeypatch):
    """What the state carries is what the transfer MIP plans gameweek 3 with."""
    seen = {}
    real = simulator.build_and_solve

    def spy(pools, **kw):
        seen.setdefault(next(iter(pools)), kw["free_transfers"])
        return real(pools, **kw)

    monkeypatch.setattr(simulator, "build_and_solve", spy)
    df = _season(SEED["2025-26"], n_gws=3)
    simulator.simulate_season(df, policy="mip", horizon=HORIZON, decay=0.45, verbose=False, wildcard_gws=[2])
    assert seen[2] == 1 and seen[3] == 1


@pytest.mark.parametrize("season", SEASONS)
def test_an_ordinary_week_still_spends_and_earns_as_before(season):
    """The banking rule outside chip weeks is untouched: spend the free ones first, then earn one, cap 5."""
    _, log, weeks = _run(season)
    for g in range(2, N_GWS + 1):
        if g in weeks.values():
            continue
        held, n = int(log.loc[g - 1, "free_transfers"]), int(log.loc[g, "n_transfers"])
        assert int(log.loc[g, "hit"]) == 4 * max(0, n - held)
        assert int(log.loc[g, "free_transfers"]) == min(MAX_FREE_TRANSFERS, max(0, held - n) + 1)


# ---- (2) the ledger: the live import's rule on the simulator's own transfers ---------------------------------------

@pytest.mark.parametrize("season", SEASONS)
def test_the_simulators_ledger_is_the_live_imports_rule_every_gameweek(season):
    """Hand the simulated season to fpl_import.derive_free_transfers as an FPL team history (transfers made,
    hit cost charged, chips played). The live rule must give the simulator's own free-transfer count after
    EVERY gameweek and never disagree with a hit the simulator charged -- 0 extra hits."""
    import fpl_import
    _, log, weeks = _run(season)
    name = {"wildcard_1": "wildcard", "wildcard_2": "wildcard", "free_hit_2": "freehit"}
    history = {"current": [{"event": int(g), "event_transfers": int(log.loc[g, "n_transfers"]),
                            "event_transfers_cost": int(log.loc[g, "hit"])} for g in log.index],
               "chips": [{"event": int(g), "name": name[c]} for c, g in weeks.items()]}
    for g in log.index:
        ft, notes = fpl_import.derive_free_transfers(history, 1, int(g), MAX_FREE_TRANSFERS)
        assert ft == int(log.loc[g, "free_transfers"]), f"GW{g}: live rule {ft} != simulator {log.loc[g, 'free_transfers']}"
        assert not [x for x in notes if "charged" in x], f"GW{g}: the live rule disagrees with a simulated hit: {notes}"


# ---- the state object alone -----------------------------------------------------------------------------------------

def _state(free_transfers):
    frame = pd.DataFrame({"element": range(1, 16), "position": ["GK"] * 2 + ["DEF"] * 5 + ["MID"] * 5 + ["FWD"] * 3,
                          "purchase_price": [50] * 15})
    return SquadState(frame, free_transfers=free_transfers)


@pytest.mark.parametrize("banked", [0, 1, 2, 5])
def test_end_gameweek_after_a_chip_week_banks_the_points_and_keeps_the_count(banked):
    state = _state(banked)
    state.end_gameweek(61, earned=squad_state.CHIP_WEEK_FREE_TRANSFERS_EARNED)
    assert state.total_points == 61
    assert state.free_transfers == banked


def test_end_gameweek_by_default_still_earns_one():
    state = _state(1)
    state.end_gameweek(40)
    assert state.free_transfers == 2 and state.total_points == 40


# ---- the transfer MIP: the week after a wildcard step ---------------------------------------------------------------

def _two_week_pools():
    """Gameweek A: three forwards worth 20 each. Gameweek B: those three worth nothing and three OTHER
    forwards worth 30 each. Every other player is the same in both weeks. With a wildcard at A the plan holds
    the first three at A and swaps all three at B -- three transfers at step 1, whatever the free count."""
    pool = make_random_pool(31)
    fwd = pool.index[pool["position"] == "FWD"].tolist()
    now, later, rest = fwd[:3], fwd[3:6], fwd[6:]
    a, b = pool.copy(), pool.copy()
    for i, idx in enumerate(now + later):
        for p in (a, b):
            p.loc[idx, "value"] = 45
            p.loc[idx, "team"] = f"FwdClub{i}"
    a.loc[now, "e_points"], b.loc[now, "e_points"] = 20.0, 0.0
    a.loc[later, "e_points"], b.loc[later, "e_points"] = 0.0, 30.0
    a.loc[rest, "e_points"], b.loc[rest, "e_points"] = 0.5, 0.5
    return pool, a, b


@pytest.mark.parametrize("banked", [1, 2])
def test_the_week_after_a_wildcard_step_is_planned_from_the_same_bank(banked):
    """ft[1] <= ft[0] after a wildcard step (kept, none earned). The plan needs three transfers at step 1, so
    the free count binds: it must be the banked count, and the hits the rest. Until M3 it was banked + 1."""
    pool, a, b = _two_week_pools()
    owned = a_squad(pool)
    prices = dict(zip(pool["element"], pool["value"]))
    status, plan = build_and_solve(
        {10: a, 11: b}, current_squad=owned, purchase_prices={e: int(prices[e]) for e in owned},
        bank=1000, free_transfers=banked, mode="balanced", decay=0.9, wildcard_step=0)
    assert status == "Optimal"
    assert plan[0]["hits"] == 0, "a chip week never pays a hit"
    assert plan[1]["transfers_made"] == 3, "the scenario must force three transfers at step 1, or it tests nothing"
    assert plan[1]["free_transfers"] == banked
    assert plan[1]["hits"] == 3 - banked


def test_without_a_wildcard_the_chain_is_unchanged():
    """The same pools with no chip: step 0 spends the free transfer, step 1 has earned one back."""
    pool, a, b = _two_week_pools()
    owned = a_squad(pool)
    prices = dict(zip(pool["element"], pool["value"]))
    status, plan = build_and_solve(
        {10: a, 11: b}, current_squad=owned, purchase_prices={e: int(prices[e]) for e in owned},
        bank=1000, free_transfers=1, mode="balanced", decay=0.9, wildcard_step=None)
    assert status == "Optimal"
    used0 = plan[0]["transfers_made"]
    assert plan[0]["hits"] == max(0, used0 - 1)
    if plan[1]["transfers_made"] > 0:
        assert plan[1]["hits"] == max(0, plan[1]["transfers_made"] - 1), "one earned back after an ordinary week"


# ---- the path-control replay ---------------------------------------------------------------------------------------

def test_the_path_control_replay_follows_the_same_rule():
    """squad/pathcontrol.py mirrors the simulator's loop on purpose; a wildcard week must leave the same bank."""
    import pathcontrol as pc
    df = _season(SEED["2024-25"], n_gws=3)
    _rows, state = pc._replay(pc.Arm("a", df, wildcard_gws=[2], horizon=HORIZON), [1, 2])
    assert state.free_transfers == 1
    _, log = simulator.simulate_season(df, policy="mip", horizon=HORIZON, decay=0.45, verbose=False, wildcard_gws=[2])
    rows, state = pc._replay(pc.Arm("a", df, wildcard_gws=[2], horizon=HORIZON, decay=0.45), [1, 2, 3])
    assert [r["points"] for r in rows] == [int(p) for p in log["points"]], "replay and simulator diverged"
    assert state.free_transfers == int(log["free_transfers"].iloc[-1])


# ---- (3) the stamp, and replaying a log by its own rule -------------------------------------------------------------

@pytest.mark.parametrize("season", SEASONS)
def test_every_log_row_is_stamped_with_the_chip_week_rule(season):
    """The convention that made the decisions must be readable off the artefact (the #13 lesson). A log
    without this column was written before 2026-11-15 and earned a free transfer in a chip week."""
    _, log, _ = _run(season)
    assert "chip_week_free_transfers_earned" in log.columns
    assert (log["chip_week_free_transfers_earned"] == 0).all()


def _as_stored(log):
    """The columns eval/run_arms_full_system.replay_state reads, as a stored armlog carries them."""
    d = log.reset_index() if log.index.name == "gw" else log.copy()
    d["all_transfers"] = d["all_transfers"].map(lambda t: [[int(a), int(b)] for a, b in t])
    return d


def test_the_rule_a_log_was_written_under_is_read_off_the_log():
    import run_arms_full_system as rafs
    assert rafs.log_chip_week_earned(pd.DataFrame({"gw": [1], "chip_week_free_transfers_earned": [0]})) == 0
    assert rafs.log_chip_week_earned(pd.DataFrame({"gw": [1], "chip_week_free_transfers_earned": [1]})) == 1
    assert rafs.log_chip_week_earned(pd.DataFrame({"gw": [1]})) == 1, "no stamp = written before 2026-11-15 = one earned"


def test_replaying_a_log_follows_the_logs_own_chip_week_rule(monkeypatch):
    """A log written after the fix replays with none earned in its Wildcard week; a log written before it (no
    stamp) replays with one earned, so the M1 record and every older armlog stay reproducible gameweek by
    gameweek -- replay_state asserts the free-transfer count against the log at every gameweek."""
    import run_arms_full_system as rafs
    df = _season(SEED["2023-24"], n_gws=4)
    kw = dict(policy="mip", horizon=HORIZON, decay=0.45, verbose=False, wildcard_gws=[2])
    _, new = simulator.simulate_season(df, **kw)
    assert int(new.set_index("gw").loc[2, "free_transfers"]) == 1
    state = rafs.replay_state(_as_stored(new), df, 4)
    assert state.free_transfers == int(new["free_transfers"].iloc[-1])

    monkeypatch.setattr(squad_state, "CHIP_WEEK_FREE_TRANSFERS_EARNED", 1)      # the rule until 2026-11-15
    _, old = simulator.simulate_season(df, **kw)
    assert (old["chip_week_free_transfers_earned"] == 1).all(), "the stamp records the rule in force"
    assert int(old.set_index("gw").loc[2, "free_transfers"]) == 2, "this is the chip-week rule the M1 record was built with"
    monkeypatch.setattr(squad_state, "CHIP_WEEK_FREE_TRANSFERS_EARNED", 0)
    stamped = rafs.replay_state(_as_stored(old), df, 4)                         # stamped 1: replays by its stamp
    unstamped = rafs.replay_state(_as_stored(old.drop(columns=["chip_week_free_transfers_earned"])), df, 4)   # as M1's logs
    assert stamped.free_transfers == unstamped.free_transfers == int(old["free_transfers"].iloc[-1])

    wrong = _as_stored(old.drop(columns=["chip_week_free_transfers_earned"]))
    wrong["chip_week_free_transfers_earned"] = 0                                # the wrong rule for this log
    with pytest.raises(AssertionError, match="replayed FT"):
        rafs.replay_state(wrong, df, 4)


def test_the_old_rule_is_one_constant_away(monkeypatch):
    """Nothing else moved: with the constant at 1 the simulator earns in a chip week exactly as before."""
    df = _season(SEED["2024-25"], n_gws=3)
    monkeypatch.setattr(squad_state, "CHIP_WEEK_FREE_TRANSFERS_EARNED", 1)
    _, log = simulator.simulate_season(df, policy="mip", horizon=HORIZON, decay=0.45, verbose=False, wildcard_gws=[2])
    log = log.set_index("gw")
    assert int(log.loc[2, "free_transfers"]) == int(log.loc[1, "free_transfers"]) + 1 == 2


# ---- the logs of record on disk (skipped where data/ is not present) ------------------------------------------------

_ARMS = REPO / "data" / "arms"
_RECORD_LOGS = [(s, suffix) for s in SEASONS for suffix in ("", "_m1", "_m3a")]


@pytest.mark.parametrize("season,suffix", _RECORD_LOGS)
def test_the_logs_of_record_replay_gameweek_by_gameweek(season, suffix):
    """Every reference log -- the 2026-09-13 record (no stamps), the M1 restatement (opening stamped, chip-week
    rule not) and the M3 restatement (both stamped) -- replays against its own free-transfer column through
    gameweek 7, the state eval/run_arms_full_system.py resumes an arm from. Gameweek 2 is the Wildcard."""
    import run_arms_full_system as rafs
    tag = season.replace("-", "_")
    log_path = _ARMS / f"armlog_{tag}_gap0_tc2{suffix}.parquet"
    wf = REPO / "data" / f"walkforward_h6_{tag}.parquet"
    if not (log_path.exists() and wf.exists()):
        pytest.skip(f"{log_path.name} or its frame is not on this machine")
    log = pd.read_parquet(log_path)
    df = simulator.load_season(walkforward_path=str(wf), horizon_aware=True, season=season)
    state = rafs.replay_state(log, df, 7)
    by = log.set_index("gw")
    assert state.free_transfers == int(by.loc[7, "free_transfers"])
    want_gw3 = {"": 3, "_m1": 2, "_m3a": 1}[suffix]
    assert int(by.loc[2, "free_transfers"]) == want_gw3, "free transfers held at the gameweek-3 deadline"
