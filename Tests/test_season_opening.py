"""The simulated season's OPENING free transfer -- KNOWN_ISSUES #29 (found by X2 on 2026-11-14, fixed by M1).

FPL: the gameweek-1 squad is a free pick and no free transfer is held at the gameweek-1 deadline -- the first
one is earned for gameweek 2. Until M1 every simulated season opened gameweek 1 holding one free transfer and
banked a second at the end of it, so the simulated manager stood at the gameweek-2 deadline with TWO, and at
gameweek 3 with THREE after the record's gameweek-2 Wildcard. All three reference logs of record carry that
(data/arms/armlog_*_gap0_tc2.parquet: free_transfers 2 after GW1, 3 after GW2).

Pinned here, on a small synthetic season so it runs in the unit suite:
  * the opening itself, for every season the full-system simulator is run on, with and without the
    gameweek-2 Wildcard (the simulator has ONE rule set for every season -- the 2025-26 rules by project
    convention, squad/chip_legality.py -- so the season only chooses the synthetic data);
  * the gameweek-3 count without a chip (the banking rule is untouched by the fix);
  * the gameweek-3 count after a gameweek-2 Wildcard AS THE SIMULATOR COMPUTES IT -- banked transfers kept
    and one earned = 2 -- next to what the live import's rule (fpl_import.derive_free_transfers, the rule
    checked against FPL's own hit charges) gives for the same history: kept, none earned = 1. That
    disagreement is KNOWN_ISSUES #30 (OPEN, deliberately outside M1). The test states it so it cannot be
    forgotten, and it fails the day the chip-week rule is changed -- the moment to update it;
  * the provenance stamp `opening_free_transfers` on every decision-log row, and that replaying a log
    follows the log's OWN opening (logs written before 2026-11-14 carry no stamp and opened with one);
  * the sibling season-opening sites: the opening-horizon free-pick solve and the path-control replay.
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

# Every season the full-system simulator is run on (eval/run_full_system.py holds their chip weeks).
SEASONS = ["2023-24", "2024-25", "2025-26"]
SEED = {"2023-24": 7, "2024-25": 11, "2025-26": 23}
N_GWS, HORIZON = 3, 2


def _season(seed):
    """A horizon-aware synthetic season: one row per (cutoff, gameweek, player). Predictions differ by
    gameweek so there is something to transfer for; what happened is fixed per (gameweek, player)."""
    base = make_random_pool(seed)
    rng = np.random.default_rng(seed)
    pts = {g: np.round(rng.uniform(0, 10, len(base)), 2) for g in range(1, N_GWS + 1)}
    act = {g: rng.integers(0, 12, len(base)) for g in range(1, N_GWS + 1)}
    frames = []
    for k in range(1, N_GWS + 1):
        for g in range(k, min(k + HORIZON, N_GWS + 1)):
            p = base.copy()
            p["e_points"], p["actual_points"], p["minutes"] = pts[g], act[g], 90
            p["cutoff"], p["gw"] = k, g
            frames.append(p)
    return pd.concat(frames, ignore_index=True)


def _run(season, gw2_wildcard):
    df = _season(SEED[season])
    _, log = simulator.simulate_season(df, policy="mip", horizon=HORIZON, decay=0.45, verbose=False,
                                       wildcard_gws=[2] if gw2_wildcard else None)
    return df, log.set_index("gw")


def test_the_seasons_of_record_are_the_ones_covered():
    """A fourth simulated season must be added to SEASONS above, or this fails."""
    import run_full_system as rfs
    assert sorted(rfs.WC2) == SEASONS


@pytest.mark.parametrize("season", SEASONS)
@pytest.mark.parametrize("gw2_wildcard", [False, True])
def test_one_free_transfer_at_the_gameweek_2_deadline(season, gw2_wildcard):
    """THE FIX. `free_transfers` in a log row is the count CARRIED FORWARD, so gameweek 1's row is what the
    manager holds at the gameweek-2 deadline. The record had 2 here."""
    _, log = _run(season, gw2_wildcard)
    assert int(log.loc[1, "free_transfers"]) == 1
    assert int(log.loc[1, "n_transfers"]) == 0 and int(log.loc[1, "hit"]) == 0, "the opening fifteen is a free pick"


@pytest.mark.parametrize("season", SEASONS)
def test_gameweek_3_without_a_chip_is_the_banking_rule(season):
    """One free transfer at gameweek 2: used -> one again at gameweek 3; held -> two. A second transfer at
    gameweek 2 is a 4-point hit (the record would have made it free)."""
    _, log = _run(season, gw2_wildcard=False)
    n2 = int(log.loc[2, "n_transfers"])
    assert int(log.loc[2, "hit"]) == 4 * max(0, n2 - 1)
    assert int(log.loc[2, "free_transfers"]) == max(0, 1 - n2) + 1


def test_a_second_transfer_at_gameweek_2_costs_a_hit():
    """The same rule on the state object alone, with no solver in the way."""
    frame = pd.DataFrame({"element": range(1, 16), "position": ["GK"] * 2 + ["DEF"] * 5 + ["MID"] * 5 + ["FWD"] * 3,
                          "purchase_price": [50] * 15})
    state = SquadState(frame, free_transfers=squad_state.OPENING_FREE_TRANSFERS)
    assert state.free_transfers == 0, "no free transfer exists at the gameweek-1 deadline"
    state.end_gameweek(50)
    assert state.free_transfers == 1, "the first free transfer is earned for gameweek 2"
    assert state.spend_transfers(2) == 1, "two transfers at gameweek 2 = one free + one paid"


@pytest.mark.parametrize("season", SEASONS)
def test_gameweek_3_after_a_gameweek_2_wildcard__simulator_2_live_rule_1__known_issue_30(season):
    """After the fix the simulator stands at gameweek 3 with TWO free transfers when gameweek 2 was a
    Wildcard (the record had three): the chip week keeps the banked transfer AND earns one. The live
    import's rule for the same history -- kept, none earned -- gives ONE. M1 fixes the opening only; the
    chip-week rule is KNOWN_ISSUES #30, OPEN. This test pins the simulator's present behaviour and the size
    of the disagreement, and must be updated in the commit that changes either rule."""
    import fpl_import
    _, log = _run(season, gw2_wildcard=True)
    assert bool(log.loc[2, "wildcard"]) and int(log.loc[2, "hit"]) == 0
    sim_gw3 = int(log.loc[2, "free_transfers"])
    history = {"current": [{"event": 1, "event_transfers": 0, "event_transfers_cost": 0},
                           {"event": 2, "event_transfers": int(log.loc[2, "n_transfers"]), "event_transfers_cost": 0}],
               "chips": [{"event": 2, "name": "wildcard"}]}
    live_gw3, _notes = fpl_import.derive_free_transfers(history, 1, 2, MAX_FREE_TRANSFERS)
    assert live_gw3 == 1
    assert sim_gw3 == 2
    assert sim_gw3 == live_gw3 + 1, "the simulator earns a free transfer in a chip week; the live rule does not"


@pytest.mark.parametrize("gw2_wildcard", [False, True])
def test_every_log_row_is_stamped_with_the_opening(gw2_wildcard):
    """The convention that made the decisions must be readable off the artefact (the #13 lesson). A log
    without this column was written before 2026-11-14 and opened with one free transfer."""
    _, log = _run("2025-26", gw2_wildcard)
    assert "opening_free_transfers" in log.columns
    assert (log["opening_free_transfers"] == squad_state.OPENING_FREE_TRANSFERS).all()
    assert squad_state.OPENING_FREE_TRANSFERS == 0


def test_the_opening_horizon_solve_plans_from_the_same_opening(monkeypatch):
    """The gated opening-horizon path (OPENING_HORIZON_ACTIVE, not adopted) plans gameweeks 2+ inside the
    opening solve; it must plan them from the same opening the state then carries."""
    seen = []
    real = simulator.build_and_solve

    def spy(pools, **kw):
        if not kw.get("current_squad"):
            seen.append(kw["free_transfers"])
        return real(pools, **kw)

    monkeypatch.setattr(simulator, "build_and_solve", spy)
    monkeypatch.setattr(simulator, "OPENING_HORIZON_ACTIVE", True)
    df = _season(SEED["2025-26"])
    _, log = simulator.simulate_season(df, policy="mip", horizon=HORIZON, decay=0.45, verbose=False, gws=[1, 2])
    assert seen == [squad_state.OPENING_FREE_TRANSFERS]
    assert bool(log["opening_horizon_active"].iloc[0])
    assert int(log.set_index("gw").loc[1, "free_transfers"]) == 1


def test_the_path_control_replay_opens_the_same_way():
    """squad/pathcontrol.py mirrors the simulator's loop on purpose; the two must open identically."""
    import pathcontrol as pc
    df = _season(SEED["2024-25"])
    _rows, state = pc._replay(pc.Arm("a", df, horizon=HORIZON), [1])
    assert state.free_transfers == 1


def _as_stored(log):
    """The columns eval/run_arms_full_system.replay_state reads, as a stored armlog carries them."""
    d = log.reset_index()
    d["all_transfers"] = d["all_transfers"].map(lambda t: [[int(a), int(b)] for a, b in t])
    return d


def test_replaying_a_log_follows_the_logs_own_opening(monkeypatch):
    """A log written after the fix replays from no free transfer; a log written before it (no stamp) replays
    from one, so every armlog of the old record stays reproducible gameweek by gameweek."""
    import run_arms_full_system as rafs
    df = _season(SEED["2023-24"])
    _, new = simulator.simulate_season(df, policy="mip", horizon=HORIZON, decay=0.45, verbose=False, wildcard_gws=[2])
    state = rafs.replay_state(_as_stored(new.set_index("gw")), df, N_GWS)
    assert state.free_transfers == int(new["free_transfers"].iloc[-1])

    monkeypatch.setattr(squad_state, "OPENING_FREE_TRANSFERS", 1)             # the pre-2026-11-14 convention
    _, old = simulator.simulate_season(df, policy="mip", horizon=HORIZON, decay=0.45, verbose=False, wildcard_gws=[2])
    old = old.drop(columns=["opening_free_transfers"])                         # old logs carry no stamp
    assert int(old.set_index("gw").loc[1, "free_transfers"]) == 2, "this is the opening the record was built with"
    monkeypatch.setattr(squad_state, "OPENING_FREE_TRANSFERS", 0)
    state = rafs.replay_state(_as_stored(old.set_index("gw")), df, N_GWS)
    assert state.free_transfers == int(old["free_transfers"].iloc[-1])
