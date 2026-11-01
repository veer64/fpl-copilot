"""Prompt P7 Part 1 (2026-11-01): a user with NO squad (every new sign-in) gets a clear "no squad saved yet" RESULT from every
squad tool -- never an {"error": ...}, which the agent reports as a failure. Measured on 1 Nov for a fresh id: get_my_squad,
get_my_xi, propose_transfers, set_my_squad (preview) and get_wildcard_gap returned {"error": "no active squad version for
user N: ... Seed one (eval/seed_squad_gw4.py) ..."}, get_my_points an error with error_kind no_squad_for_gw; only
get_price_movements answered (my_squad_unavailable). Other squad-state failures (two active versions, an illegal stored
document, a squad that did not exist at a played gameweek's deadline) stay errors. Read-only: the id below owns nothing."""
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
for p in (str(REPO), str(REPO / "squad"), str(REPO / "Tests")):
    if p not in sys.path:
        sys.path.insert(0, p)

import model_tools as mt                                   # noqa: E402
import squad_store                                         # noqa: E402

NOBODY = 99_999_901                                         # no row anywhere


def _assert_no_squad(out, user_id=NOBODY):
    assert isinstance(out, dict) and "error" not in out, out
    assert out["no_squad"] is True and out["user_id"] == user_id
    assert out["status"] == "no squad saved yet" and "not an error" in out["note"]
    assert "eval/" not in str(out) and "seed" not in str(out).lower()          # no developer instructions to a user


def test_a_missing_active_version_is_its_own_error_class_with_the_same_message():
    with pytest.raises(squad_store.NoSquadError) as ei:
        squad_store.active_from_rows([], user_id=NOBODY)
    assert isinstance(ei.value, squad_store.SquadStateError)
    assert f"no active squad version for user {NOBODY}" in str(ei.value)


@pytest.mark.parametrize("call", [
    lambda: mt.get_my_squad(NOBODY),
    lambda: mt.get_my_xi(NOBODY),
    lambda: mt.propose_transfers(horizon=1, user_id=NOBODY),
    lambda: mt.set_my_squad([1] * 15, 1, 2, [3, 4, 5, 6], confirm=False, user_id=NOBODY),
    lambda: mt.get_wildcard_gap(NOBODY),
    lambda: mt.get_my_points(user_id=NOBODY),
], ids=["get_my_squad", "get_my_xi", "propose_transfers", "set_my_squad", "get_wildcard_gap", "get_my_points"])
def test_every_squad_tool_answers_no_squad_saved_yet(call, monkeypatch):
    # get_my_points answers "nothing played yet" before it looks for a squad: pin one played gameweek (test_actual_points'
    # master), so the answer does not depend on what the actuals cache holds when this test runs
    from test_actual_points import master
    monkeypatch.setattr(mt, "_actuals_master", lambda: (master([(1, 3, 29, 90, 2)]), {}))
    _assert_no_squad(call())


def test_the_price_movements_still_answer_the_market_part():
    out = mt.get_price_movements(user_id=NOBODY)
    assert "error" not in out and "my_squad_unavailable" in out


def test_the_default_user_resolves_through_the_same_path(monkeypatch):
    monkeypatch.setenv("FPL_USER_ID", str(NOBODY))
    _assert_no_squad(mt.get_my_squad())


def test_two_active_versions_stay_an_error():
    rows = [{"version_id": 1}, {"version_id": 2}]
    with pytest.raises(squad_store.SquadStateError) as ei:
        squad_store.active_from_rows(rows, user_id=NOBODY)
    assert not isinstance(ei.value, squad_store.NoSquadError)


def test_other_squad_state_failures_stay_errors(monkeypatch):
    def boom(user_id=None, conn=None):
        raise squad_store.SquadStateError("2 active squad versions for user 1")
    monkeypatch.setattr(squad_store, "read_active", boom)
    assert mt.get_my_squad(1) == {"error": "2 active squad versions for user 1"}
