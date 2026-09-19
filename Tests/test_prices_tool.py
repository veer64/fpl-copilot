"""get_price_movements -- observed moves only, and the asymmetric selling rule reused.

Two properties carry the weight.

ONE: the tool must not forecast, and the reason is not the one originally assumed. FPL does
publish a progress-to-threshold figure in this data (price_change_percent, and a set of
forward fields). The ruling of 2026-09-19 was to carry the progress figure through ATTRIBUTED
and to exclude the forward fields entirely, because a projection sitting in the payload
becomes the agent's own forecast whatever the prompt says. So the tests assert the exclusion
structurally, on the payload, rather than trusting prose.

TWO: selling price is squad_state.sell_price, not a second copy of the rule. The MIP and
propose_transfers already share that function and assert they agree; a third implementation
here is how they would silently drift.
"""
import gzip
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "squad"))

import prices_tool as pt                          # noqa: E402
from squad_state import sell_price                # noqa: E402


def _write(dirpath, when, elements):
    name = when.strftime("%Y%m%dT%H%M%SZ") + ".json.gz"
    with gzip.open(Path(dirpath) / name, "wt", encoding="utf-8") as fh:
        json.dump({"elements": elements}, fh)


def _el(eid, cost, ccs=0, fall=0, pcp=12.5, name="A B", **extra):
    e = {"id": eid, "now_cost": cost, "cost_change_start": ccs, "cost_change_start_fall": fall,
         "cost_change_event": 0, "price_change_percent": pcp,
         "first_name": name.split()[0], "second_name": name.split()[-1],
         # the forward fields FPL publishes, present in the file and excluded from the payload
         "price_change_projections": [{"offset": 0, "projected_percent": "103.6",
                                       "likelihood": 5}],
         "price_change_hourly_rate": 3846, "price_change_locked_until": None,
         "price_change_calibrating": False}
    e.update(extra)
    return e


T1 = datetime(2026, 9, 18, 17, 30, tzinfo=timezone.utc)
T0 = T1 - timedelta(days=6)
T_MID = T1 - timedelta(days=3)


@pytest.fixture()
def snaps(tmp_path):
    _write(tmp_path, T0, [_el(1, 50, name="Riser One"), _el(2, 70, name="Faller Two"),
                          _el(3, 45, name="Flat Three")])
    _write(tmp_path, T_MID, [_el(1, 51), _el(2, 69), _el(3, 45)])
    _write(tmp_path, T1, [_el(1, 52, ccs=2, pcp=91.4, name="Riser One"),
                          _el(2, 68, ccs=-2, fall=2, name="Faller Two"),
                          _el(3, 45, name="Flat Three")])
    return tmp_path


# ------------------------------------------------------------- observed, not predicted

def test_risers_and_fallers_are_net_change_between_two_observations(snaps):
    out = pt.movements(window_days=7, directory=snaps, now=T1)
    assert [r["player_id"] for r in out["risers"]] == [1]
    assert [f["player_id"] for f in out["fallers"]] == [2]
    assert out["risers"][0]["net_change"] == 0.2      # 50 -> 52 tenths
    assert out["fallers"][0]["net_change"] == -0.2
    assert out["n_moved"] == 2, "a flat player is not a mover"


def test_the_two_timestamps_and_the_gap_travel_with_the_answer(snaps):
    o = pt.movements(window_days=7, directory=snaps, now=T1)["observation"]
    assert o["observed_from"].startswith("2026-09-12")
    assert o["observed_to"].startswith("2026-09-18")
    assert o["snapshots_in_window"] == 3
    assert o["largest_gap_hours"] == 72.0
    assert o["basis"] == "observed"
    assert "BURST-SAMPLED" in o["sampling"] and "no NET change" in o["sampling"]


def test_no_change_is_not_claimed_to_mean_the_price_held(snaps):
    """A rise and a fall inside one gap cancel. The payload has to say so itself."""
    s = pt.movements(window_days=7, directory=snaps, now=T1)["observation"]["sampling"]
    assert "invisible" in s and "did not move" in s


def test_the_forward_fields_never_reach_the_payload(snaps):
    """Structural, not prose: a projection in the payload gets laundered into our voice."""
    blob = json.dumps(pt.movements(window_days=7, directory=snaps, now=T1))
    for banned in list(pt.FORWARD_FIELDS) + ["projected_percent", "likelihood", "3846"]:
        assert banned not in blob, f"a forward field leaked into the payload: {banned}"
    assert "price_change_projections" not in json.dumps(
        pt.read_snapshot(sorted(Path(snaps).glob("*.json.gz"))[-1]))


def test_fpls_progress_figure_is_carried_but_attributed(snaps):
    out = pt.movements(window_days=7, directory=snaps, now=T1)
    assert out["risers"][0]["fpl_price_change_percent"] == 91.4
    block = out["fpl_price_change_percent"]
    assert "FPL's OWN" in block["what"]
    assert "not a prediction we are making" in block["what"]
    assert block["attribute_as"] == "FPL's published figure"
    assert "laundered" in block["excluded"] or "agent's own forecast" in block["excluded"]


def test_the_payload_states_it_cannot_forecast_and_why(snaps):
    c = pt.movements(window_days=7, directory=snaps, now=T1)["cannot_forecast"]
    assert "what HAS happened" in c
    assert "NOT evidence of the next one" in c
    assert "counter reset" in c


def test_every_mover_is_marked_observed(snaps):
    out = pt.movements(window_days=7, directory=snaps, now=T1)
    for m in out["risers"] + out["fallers"]:
        assert m["basis"] == "observed"


def test_the_cumulative_counters_survive_sparse_sampling(snaps):
    """Net since season start is exact however sparsely we sampled; falls are separate."""
    out = pt.movements(window_days=7, directory=snaps, now=T1)
    assert out["risers"][0]["season_net_change"] == 0.2
    assert out["fallers"][0]["season_net_change"] == -0.2
    assert out["fallers"][0]["season_total_falls"] == 0.2


def test_only_the_bracketing_snapshots_are_parsed(snaps, monkeypatch):
    """O(1), not O(archive): 53 files today, ~250 by May, 41 ms each."""
    read = []
    real = pt.read_snapshot
    monkeypatch.setattr(pt, "read_snapshot", lambda p: (read.append(p), real(p))[1])
    pt.movements(window_days=7, directory=snaps, now=T1)
    assert len(read) == 2, f"parsed {len(read)} snapshots, should be the two brackets"


def test_an_empty_archive_is_an_error_not_an_empty_market(tmp_path):
    out = pt.movements(window_days=7, directory=tmp_path)
    assert "error" in out and "no price snapshots" in out["error"]


# ------------------------------------------------------------- the selling rule

SQUAD = {"bank": 9, "players": [
    {"element": 1, "name": "Riser One", "position": "MID", "purchase_price": 50},
    {"element": 2, "name": "Faller Two", "position": "DEF", "purchase_price": 70},
    {"element": 3, "name": "Flat Three", "position": "GK", "purchase_price": 45},
]}


def test_selling_price_uses_squad_states_function_not_a_second_copy(snaps):
    out = pt.movements(window_days=7, directory=snaps, now=T1, squad=SQUAD)
    by = {p["player_id"]: p for p in out["my_squad"]["players"]}
    assert by[1]["sells_for"] == round(sell_price(50, 52) / 10, 1)
    assert by[2]["sells_for"] == round(sell_price(70, 68) / 10, 1)
    src = (REPO / "prices_tool.py").read_text(encoding="utf-8")
    assert "from squad_state import sell_price" in src
    assert "// 2" not in src, "the asymmetric rule is reimplemented here"


def test_the_asymmetry_is_visible_in_the_numbers(snaps):
    """A 0.2 rise returns 0.1; a 0.2 fall costs the full 0.2."""
    out = pt.movements(window_days=7, directory=snaps, now=T1, squad=SQUAD)
    by = {p["player_id"]: p for p in out["my_squad"]["players"]}
    assert by[1]["price_now"] == 5.2 and by[1]["sells_for"] == 5.1      # half the rise
    assert by[2]["price_now"] == 6.8 and by[2]["sells_for"] == 6.8      # fall in full
    assert by[1]["profit_if_sold"] == 0.1
    assert by[2]["profit_if_sold"] == -0.2


def test_sells_for_is_not_price_now_and_the_payload_says_why(snaps):
    b = pt.movements(window_days=7, directory=snaps, now=T1, squad=SQUAD)["my_squad"]
    assert "half the rise, rounded down" in b["selling_rule"]
    assert "overstates the budget" in b["asymmetry_matters"]


def test_an_unpriced_player_is_valued_at_what_you_paid_never_at_a_guess(snaps):
    squad = {"bank": 0, "players": [
        {"element": 99, "name": "Ghost", "position": "MID", "purchase_price": 55}]}
    b = pt.movements(window_days=7, directory=snaps, now=T1, squad=squad)["my_squad"]
    p = b["players"][0]
    assert p["price_unknown"] is True
    assert p["sells_for"] == 5.5, "assuming a rise would invent money"
    assert b["unpriced_elements"] == [99]


def test_the_squad_totals_add_up(snaps):
    b = pt.movements(window_days=7, directory=snaps, now=T1, squad=SQUAD)["my_squad"]
    assert b["total_paid"] == 16.5
    assert b["total_sell_value"] == round((51 + 68 + 45) / 10, 1)
    assert b["bank"] == 0.9


# ------------------------------------------------------------- the agent's entry

def test_the_agent_entry_point_is_registered_and_dispatches(monkeypatch):
    monkeypatch.setenv("APP_API_KEY", "x" * 48)
    import agent
    # Identity would be the obvious assertion and it is WRONG here: other test modules call
    # importlib.reload on `agent` and on `model_tools`, so by the time this runs the dispatch
    # map can hold a function object from an earlier incarnation of the module. Same function,
    # different object. The property worth pinning is that the map points at the REAL tool in
    # model_tools rather than a stub or a lambda, and module+qualname says that across reloads.
    fn = agent.available_functions["get_price_movements"]
    assert (fn.__module__, fn.__qualname__) == ("model_tools", "get_price_movements")
    monkeypatch.setitem(agent.available_functions, "get_price_movements",
                        lambda **k: {"ok": True, "got": k})
    assert agent.call_tool("get_price_movements", {"window_days": 14}) == {
        "ok": True, "got": {"window_days": 14}}


def test_movers_still_answer_when_there_is_no_squad(monkeypatch, snaps):
    monkeypatch.setenv("APP_API_KEY", "x" * 48)
    import model_tools as mt
    import squad_store

    def boom(user_id):
        raise RuntimeError("no active version")
    monkeypatch.setattr(squad_store, "read_active", boom)
    monkeypatch.setattr(pt, "BOOTSTRAP_DIR", snaps)
    monkeypatch.setattr(pt, "movements",
                        lambda **k: {"risers": [], "fallers": [], "squad_was": k.get("squad")})
    out = mt.get_price_movements()
    assert out["squad_was"] is None
    assert "my_squad_unavailable" in out
