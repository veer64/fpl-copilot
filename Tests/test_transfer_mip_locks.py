"""
Locks and bans in the six-week transfer MIP, the simulator's `cutoff` vantage
point, and the property that a proposal APPLIES through squad_store.plan_change
with the same accounting the MIP claimed (part 3 of the squad-state build,
2026-09-12).

Synthetic pools (test_optimize.make_random_pool), real solves (HiGHS in
process, a few seconds). No database, no network, no model-path code.

Run:
    uv run pytest Tests/test_transfer_mip_locks.py -v
"""

import sys
from pathlib import Path

import pandas as pd
import pytest

REPO = Path(__file__).resolve().parents[1]
for p in (str(REPO), str(REPO / "squad"), str(REPO / "Tests")):
    if p not in sys.path:
        sys.path.insert(0, p)

import squad_store                                         # noqa: E402
from simulator import decide_gameweek_mip                  # noqa: E402
from squad_state import SquadState                         # noqa: E402
from transfer_mip import build_and_solve                   # noqa: E402
from test_optimize import make_random_pool                 # noqa: E402
from test_transfer_mip import a_squad, squad_frame         # noqa: E402


def _pool(seed=0):
    pool = make_random_pool(seed)
    for c, v in (("p_play_any", 0.9), ("p_60plus", 0.8)):
        if c not in pool.columns:
            pool[c] = v
    return pool


def _setup(seed=0, T=2):
    pool = _pool(seed)
    squad = a_squad(pool)
    pools = {5 + t: pool for t in range(T)}
    purchase = {e: int(pool.loc[pool["element"] == e, "value"].iloc[0]) for e in squad}
    return pool, squad, pools, purchase


def _solve(pools, squad, purchase, **kw):
    status, plan = build_and_solve(pools, current_squad=squad, purchase_prices=purchase,
                                   bank=5, free_transfers=1, **kw)
    assert status == "Optimal", status
    return plan


# ------------------------------------------------------------ locks / bans
def test_defaults_are_inert():
    pool, squad, pools, purchase = _setup()
    a = _solve(pools, squad, purchase)
    b = _solve(pools, squad, purchase, locked_elements=[], banned_elements=None)
    assert a[0]["objective"] == pytest.approx(b[0]["objective"])
    assert a[0]["squad"] == b[0]["squad"] and a[0]["buys"] == b[0]["buys"]


def test_lock_a_non_owned_player_forces_the_buy():
    pool, squad, pools, purchase = _setup()
    pos = dict(zip(pool["element"], pool["position"]))
    cheap = pool[(~pool["element"].isin(squad)) & (pool["position"] == "MID")].sort_values("value")
    target = int(cheap["element"].iloc[0])
    plan = _solve(pools, squad, purchase, locked_elements=[target])
    assert target in plan[0]["buys"]
    for st in plan:
        assert target in st["squad"]
    assert pos[target] == "MID"
    # a MID went out for him (the 15 stays 2/5/5/3)
    assert any(pos[s] == "MID" for s in plan[0]["sells"])


def test_ban_an_owned_player_forces_the_sale():
    pool, squad, pools, purchase = _setup()
    victim = squad[3]                                        # a DEF from the owned fifteen
    plan = _solve(pools, squad, purchase, banned_elements=[victim])
    assert victim in plan[0]["sells"]
    for st in plan:
        assert victim not in st["squad"]


def test_lock_and_ban_clash_or_unknown_are_refused():
    pool, squad, pools, purchase = _setup()
    with pytest.raises(ValueError):
        build_and_solve(pools, squad, purchase, 5, 1, locked_elements=[squad[0]], banned_elements=[squad[0]])
    with pytest.raises(ValueError):
        build_and_solve(pools, squad, purchase, 5, 1, locked_elements=[99999])


# ------------------------------------------------------- simulator cutoff
def _season_df(pool, gws=(4, 5, 6), cutoff=4):
    return pd.concat([pool.assign(gw=g, cutoff=cutoff) for g in gws], ignore_index=True)


def _state(pool, squad):
    return SquadState(squad_frame(pool, squad), bank=5, free_transfers=1)


def test_decide_gameweek_mip_reads_a_later_gameweek_from_the_frames_cutoff():
    pool, squad, _, _ = _setup()
    df = _season_df(pool)
    prices = dict(zip(pool["element"], pool["value"]))
    state = _state(pool, squad)
    # the default (cutoff == gw) cannot see GW5 from a cutoff-4 frame
    with pytest.raises(ValueError):
        decide_gameweek_mip(df, 5, _state(pool, squad), pool, prices, [4, 5, 6], horizon=2)
    team, transfers, step, eff_h, plan = decide_gameweek_mip(
        df, 5, state, pool, prices, [4, 5, 6], horizon=2, cutoff=4, return_plan=True)
    assert [st["gw"] for st in plan] == [5, 6] and eff_h == 2
    assert len(team) == 15 and set(team["role"]) <= {"CAPTAIN", "VICE", "start", "bench"}


def test_decide_gameweek_mip_default_return_is_unchanged():
    pool, squad, _, _ = _setup()
    df = _season_df(pool, gws=(4, 5), cutoff=4)
    prices = dict(zip(pool["element"], pool["value"]))
    out = decide_gameweek_mip(df, 4, _state(pool, squad), pool, prices, [4, 5], horizon=2)
    assert len(out) == 4


# ------------------------------------------ a proposal applies, same path
def _roles_for(pool, squad):
    """A legal recorded-roles document for the owned fifteen: 4-4-2, bench GK
    first, captain the first forward, vice the first midfielder."""
    rows = pool[pool["element"].isin(squad)].copy()
    by_pos = {pos: list(rows[rows["position"] == pos]["element"]) for pos in ("GK", "DEF", "MID", "FWD")}
    role, bo = {}, {}
    role[by_pos["GK"][0]] = "start"; role[by_pos["GK"][1]] = "bench"; bo[by_pos["GK"][1]] = 1
    for e in by_pos["DEF"][:4]: role[e] = "start"
    role[by_pos["DEF"][4]] = "bench"; bo[by_pos["DEF"][4]] = 2
    for e in by_pos["MID"][:4]: role[e] = "start"
    role[by_pos["MID"][4]] = "bench"; bo[by_pos["MID"][4]] = 3
    for e in by_pos["FWD"][:2]: role[e] = "start"
    role[by_pos["FWD"][2]] = "bench"; bo[by_pos["FWD"][2]] = 4
    role[by_pos["FWD"][0]] = "CAPTAIN"; role[by_pos["MID"][0]] = "VICE"
    players = [{"element": int(r.element), "name": r.name, "position": r.position, "team": r.team,
                "purchase_price": int(r.value), "role": role[r.element], "bench_order": bo.get(r.element)}
               for r in rows.itertuples()]
    return squad_store.document(players, 5, 1, 0, "2026-27", {"kind": "seed", "hypothetical": True})


def test_a_proposal_applies_through_plan_change_with_the_mips_accounting():
    """The property the tool relies on: proposal_to_request + plan_change
    accept what decide_gameweek_mip proposed, and count the same transfers and
    hits. A proposal that could not be applied would be a bug."""
    pool, squad, _, _ = _setup(seed=3)
    df = _season_df(pool, gws=(5, 6, 7), cutoff=5)
    prices = {int(e): int(v) for e, v in zip(pool["element"], pool["value"])}
    doc = _roles_for(pool, squad)
    record = {"version_id": 1, "user_id": 1, "season": "2026-27", "gw": 5,
              "created_at": "2026-09-12 05:24:53+00", "is_active": True, "supersedes": None,
              "note": None, "squad_json": doc}
    state = squad_store.to_state(doc)
    team, transfers, step, eff_h, plan = decide_gameweek_mip(
        df, 5, state, pool, prices, [5, 6, 7], horizon=3, cutoff=5, return_plan=True)
    req = squad_store.proposal_to_request(team)
    assert len(req["player_ids"]) == 15 and len(req["bench_order_ids"]) == 4
    live = {int(r.element): {"name": r.name, "position": r.position, "team": r.team, "price_tenths": int(r.value)}
            for r in pool.itertuples()}
    new_doc, change = squad_store.plan_change(record, req["player_ids"], req["captain_id"], req["vice_id"],
                                              req["bench_order_ids"], 5, live, next_deadline_gw=5)
    assert change["n_transfers"] == int(step["transfers_made"]) == len(transfers)
    assert change["hits"] == int(step["hits"])
    assert set(new_doc["players"][i]["element"] for i in range(15)) == set(req["player_ids"])
    assert change["bank_after"] >= 0


# ----------------------------------------------------------- persistence
def test_proposal_tables_are_in_the_model_ddl_with_their_rationale():
    import db_write
    ddl = db_write.DDL
    for must in ("CREATE TABLE IF NOT EXISTS model_transfer_plans", "proposal_id",
                 "squad_version_id", "horizon_step", "executable", "These REPLACED",
                 "original model_transfers(run_id, config, element_out, element_in",
                 "way to record a HOLD"):
        assert must in ddl, must
    for c in db_write.PLAN_COLS:
        assert c in ddl, c
    for c in db_write.TRANSFER_COLS:
        assert c in ddl, c
    # a NULL that could be mistaken for a bug carries its reason on the column
    for must in ("COMMENT ON COLUMN model_transfers.sold_for", "NULL at every later step BY DESIGN",
                 "COMMENT ON COLUMN model_transfers.bought_for", "COMMENT ON COLUMN model_transfers.executable",
                 "COMMENT ON COLUMN model_transfer_plans.source", "proof = a maintainer"):
        assert must in ddl, must
