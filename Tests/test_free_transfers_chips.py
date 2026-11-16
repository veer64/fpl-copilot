"""Prompt R3 item 6 (16 Nov 2026): the live free-transfer count follows the live import's rule after a chip week.

squad_store.free_transfers_at rolled one free transfer per gameweek whatever happened in between; FPL -- and
fpl_import.derive_free_transfers at import time -- gives NONE for a Wildcard / Free Hit week (the bank is kept). KNOWN_ISSUES
#30 closed the same gap in the simulator (M3); this closes it for a saved team, from data ALREADY stored: the 6-hourly
team-score refresh (eval/refresh_team_scores.py) reads entry/{id}/history/ for every imported team, and that response lists the
chips played. No FPL request at chat time.

I1  the rule: a Wildcard / Free Hit gameweek between the version's gameweek and the one asked earns none; every other
    gameweek earns one; the cap holds; a record without `chip_weeks` counts exactly as before;
I2  it equals fpl_import.derive_free_transfers on the same history, gameweek by gameweek;
I3  read_active hands an imported team's chip weeks to the count (and get_my_squad shows it); a team whose chips were never
    stored, and every squad that is not an imported team's (users 1, 9001, 9002), are untouched -- with no extra read;
I4  the import stores the chips of the history it already fetched, with the gameweek they reach;
I5  the team-score refresh stores them from the request it already makes; a team whose chips do not reach the latest gameweek
    whose deadline has passed is read once, then skipped again; a summary without chips never erases stored ones;
I6  the two columns are added once, guarded; a row from before them is NULL and counts by the old rule.
Offline (recorded FPL responses; test databases); teams only for test users >= 10001."""
import copy
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
for p in (str(REPO), str(REPO / "squad"), str(REPO / "eval"), str(REPO / "Tests")):
    if p not in sys.path:
        sys.path.insert(0, p)

import fpl_import                                                                     # noqa: E402
import squad_store                                                                    # noqa: E402
from squad_state import MAX_FREE_TRANSFERS                                            # noqa: E402
from test_auth import app, tdb, c, mint, bearer, _q, _all_counts                      # noqa: E402,F401  (fixtures)
from test_fpl_import import api, TID, T1, T2, U1, U2, _offline, _post, load           # noqa: E402,F401  (fixtures; _offline: no network, a fixed clock)
from test_fpl_teams import teams, U                                                   # noqa: E402,F401  (fixture)
from test_home_backend import _finished_through                                       # noqa: E402


def _rec(gw, stored, chip_weeks=None):
    r = {"gw": gw, "squad_json": {"free_transfers": stored}}
    if chip_weeks is not None:
        r["chip_weeks"] = chip_weeks
    return r


# ---- I1 -------------------------------------------------------------------------------------------------------------------------

def test_i1_a_wildcard_or_free_hit_week_keeps_the_bank_and_earns_none():
    assert [squad_store.free_transfers_at(_rec(10, 2), g) for g in (10, 11, 12, 13, 14)] == [2, 3, 4, 5, 5]      # as before
    assert [squad_store.free_transfers_at(_rec(10, 2, []), g) for g in (10, 11, 12, 13, 14)] == [2, 3, 4, 5, 5]  # no chip played
    assert [squad_store.free_transfers_at(_rec(10, 2, [11]), g) for g in (10, 11, 12, 13, 14)] == [2, 3, 3, 4, 5]
    assert [squad_store.free_transfers_at(_rec(10, 1, [10, 11]), g) for g in (10, 11, 12, 13)] == [1, 1, 1, 2]   # two chip weeks running
    assert squad_store.free_transfers_at(_rec(10, 2, [9, 14]), 13) == 5         # a chip before the version or at / after G: not counted
    assert squad_store.free_transfers_at(_rec(10, 2, [13]), 13) == 5            # G's own chip matters to G + 1, not to G
    assert squad_store.free_transfers_at(_rec(10, 2, [13]), 14) == 5 and squad_store.free_transfers_at(_rec(10, 1, [13]), 14) == 4
    assert squad_store.free_transfers_at(_rec(10, 5, [11]), 16) == MAX_FREE_TRANSFERS == 5
    with pytest.raises(ValueError):
        squad_store.free_transfers_at(_rec(10, 2, [11]), 9)


def test_i1_only_a_wildcard_or_a_free_hit_keeps_the_transfers(tdb, teams):
    with tdb.cursor() as cur:
        cur.execute("UPDATE user_fpl_teams SET chips_json = %s, chips_through_gw = 9 WHERE fpl_team_id = 111",
                    (json.dumps([{"event": 6, "name": "bboost"}, {"event": 7, "name": "freehit"}, {"event": 8, "name": "3xc"},
                                 {"event": 9, "name": "wildcard"}]),))
    rec = squad_store.read_active(teams[111], conn=tdb)
    assert rec["chip_weeks"] == [7, 9]                                           # bench boost and triple captain still earn one
    assert squad_store.CHIP_KEEPS_TRANSFERS == fpl_import.CHIP_KEEPS_TRANSFERS


# ---- I2 -------------------------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("chips", [{}, {4: "wildcard"}, {3: "freehit", 7: "wildcard"}, {2: "bboost", 5: "3xc"}, {2: "wildcard", 3: "freehit"}])
def test_i2_it_equals_the_live_imports_rule_gameweek_by_gameweek(chips):
    history = {"current": [{"event": g, "event_transfers": 0, "event_transfers_cost": 0} for g in range(1, 13)],
               "chips": [{"event": g, "name": n} for g, n in chips.items()]}
    keeps = [g for g, n in chips.items() if n in fpl_import.CHIP_KEEPS_TRANSFERS]
    for g in range(2, 13):                       # the count FOR gameweek g: the import's (history through g - 1) vs the lazy one
        want, _ = fpl_import.derive_free_transfers(history, 1, g - 1, 5)
        got = squad_store.free_transfers_at(_rec(2, 1, keeps), g)             # an entry that started in GW1 holds 1 for GW2
        assert got == want, (g, chips)


# ---- I3 -------------------------------------------------------------------------------------------------------------------------

def test_i3_read_active_hands_an_imported_teams_chip_weeks_to_the_count(tdb, teams, monkeypatch):
    import model_tools as mt
    monkeypatch.setattr(mt, "_current_gw", lambda: 9)
    doc_ft = squad_store.read_active(teams[111], conn=tdb)["squad_json"]["free_transfers"]      # the seed: gw 6
    plain = squad_store.read_active(teams[111], conn=tdb)
    assert "chip_weeks" not in plain                                             # nothing stored yet: the old rule
    assert squad_store.free_transfers_at(plain, 9) == min(5, doc_ft + 3)
    with tdb.cursor() as cur:
        cur.execute("UPDATE user_fpl_teams SET chips_json = %s, chips_through_gw = 8 WHERE fpl_team_id = 111",
                    (json.dumps([{"event": 7, "name": "wildcard"}]),))
        cur.execute("UPDATE user_fpl_teams SET chips_json = '[]'::jsonb, chips_through_gw = 8 WHERE fpl_team_id = 222")
    rec = squad_store.read_active(teams[111], conn=tdb)
    assert rec["chip_weeks"] == [7] and squad_store.free_transfers_at(rec, 9) == min(5, doc_ft + 2)   # GW7 earned none
    assert squad_store.read_active(teams[222], conn=tdb)["chip_weeks"] == []      # known to have played none
    summary = squad_store.summary(rec, {}, current_gw=9)
    assert summary["free_transfers_now"] == min(5, doc_ft + 2) and summary["free_transfers_recorded"] == doc_ft


def test_i3_a_squad_that_is_not_an_imported_teams_is_read_exactly_as_before(tdb, teams):
    class NoExtraRead:
        def cursor(self, *a, **k):
            raise AssertionError("a non-imported squad owner must cost no extra read")
    for owner in (1, 9001, 9002, 800_000_001, None, "x"):
        assert squad_store._chip_weeks(NoExtraRead(), owner) is None
    assert squad_store.FIRST_IMPORTED_SQUAD_KEY == 900_000_001
    import fpl_teams
    assert squad_store.FIRST_IMPORTED_SQUAD_KEY == fpl_teams.FIRST_SQUAD_KEY


def test_i3_a_database_without_the_column_counts_by_the_old_rule(tdb, teams):
    with tdb.cursor() as cur:
        cur.execute("ALTER TABLE user_fpl_teams DROP COLUMN chips_json")
    squad_store._CHIPS_COLUMN.clear()
    try:
        rec = squad_store.read_active(teams[111], conn=tdb)
        assert "chip_weeks" not in rec
    finally:
        squad_store._CHIPS_COLUMN.clear()


# ---- I4 -------------------------------------------------------------------------------------------------------------------------

def test_i4_the_import_stores_the_chips_of_the_history_it_already_fetched(api):
    asked0 = len(api.fpl.asked)
    _post(api, "/me/teams", json={"fpl_team_id": TID})
    assert sum(1 for a in api.fpl.asked[asked0:] if "/history/" in a) == 1       # no extra request for them
    [(chips, through, key)] = _q(api.conn, "SELECT chips_json, chips_through_gw, squad_key FROM user_fpl_teams WHERE fpl_team_id = %s", (TID,))
    want = fpl_import.chips_played(load()["history"])
    assert chips == want and {c_["name"] for c_ in want} >= {"wildcard", "freehit"}
    assert through == 9                                                          # the recorded team: picks of GW9, imported for GW10
    rec = squad_store.read_active(key, conn=api.conn)
    assert rec["chip_weeks"] == sorted(c_["event"] for c_ in want if c_["name"] in ("wildcard", "freehit"))
    assert all(g < rec["gw"] for g in rec["chip_weeks"])                         # all before the version: the import already counted them
    assert squad_store.free_transfers_at(rec, rec["gw"]) == rec["squad_json"]["free_transfers"]


# ---- I5 -------------------------------------------------------------------------------------------------------------------------

def test_i5_the_refresh_job_stores_the_chips_from_the_request_it_already_makes(api):
    import refresh_team_scores as job
    api.fpl.data["bootstrap"] = _finished_through(api.fpl.data["bootstrap"], 9)
    _post(api, "/me/teams", json={"fpl_team_id": TID})
    with api.conn.cursor() as cur:                                               # a row from before the columns: scores current, no chips
        cur.execute("UPDATE user_fpl_teams SET chips_json = NULL, chips_through_gw = NULL WHERE fpl_team_id = %s", (TID,))
    fpl_import._reset()
    asked0 = len(api.fpl.asked)
    out = job.run(get=api.fpl)
    assert api.fpl.asked[asked0:] == ["bootstrap-static/", f"entry/{TID}/history/"]   # read once, though its scores were current
    assert [r[0] for r in out["refreshed"]] == [TID] and out["skipped"] == []
    [(chips, through)] = _q(api.conn, "SELECT chips_json, chips_through_gw FROM user_fpl_teams WHERE fpl_team_id = %s", (TID,))
    assert chips == fpl_import.chips_played(load()["history"]) and through == 9
    fpl_import._reset()
    asked1 = len(api.fpl.asked)
    again = job.run(get=api.fpl)
    assert api.fpl.asked[asked1:] == ["bootstrap-static/"] and again["skipped"] == [TID]   # nothing to do: skipped as before


def test_i5_a_chip_played_after_the_import_is_known_before_the_next_count(api):
    import refresh_team_scores as job
    api.fpl.data["bootstrap"] = _finished_through(api.fpl.data["bootstrap"], 9)
    _post(api, "/me/teams", json={"fpl_team_id": TID})
    [(key, gw)] = _q(api.conn, "SELECT squad_key, last_imported_gw FROM user_fpl_teams WHERE fpl_team_id = %s", (TID,))
    with api.conn.cursor() as cur:                                               # as if stored one deadline ago
        cur.execute("UPDATE user_fpl_teams SET chips_through_gw = 8 WHERE fpl_team_id = %s", (TID,))
    h = copy.deepcopy(api.fpl.data["history"])
    h["chips"] = [c_ for c_ in h["chips"] if c_["event"] != gw] + [{"event": gw, "name": "freehit", "time": "2026-10-31T10:00:00Z"}]
    api.fpl.data["history"] = h
    fpl_import._reset()
    out = job.run(get=api.fpl)
    assert [r[0] for r in out["refreshed"]] == [TID]                             # its chips did not reach GW9: read once more
    rec = squad_store.read_active(key, conn=api.conn)
    assert gw in rec["chip_weeks"]
    stored = rec["squad_json"]["free_transfers"]
    assert squad_store.free_transfers_at(rec, gw + 1) == stored                  # the Free Hit week kept the bank and earned none
    assert squad_store.free_transfers_at({**rec, "chip_weeks": []}, gw + 1) == min(5, stored + 1)   # the old count, for contrast


def test_i5_a_summary_without_chips_never_erases_stored_ones(api):
    import fpl_teams
    _post(api, "/me/teams", json={"fpl_team_id": TID})
    before = _q(api.conn, "SELECT chips_json, chips_through_gw FROM user_fpl_teams WHERE fpl_team_id = %s", (TID,))
    n = fpl_teams.write_summary(TID, {"total_points": 800, "overall_rank": 5, "last_gw": 9, "last_gw_points": 60, "updated_after_gw": 9},
                                conn=api.conn)
    assert n == 1 and _q(api.conn, "SELECT chips_json, chips_through_gw FROM user_fpl_teams WHERE fpl_team_id = %s", (TID,)) == before
    half = fpl_teams._summary_params({"chips": [{"event": 2, "name": "wildcard"}], "chips_through_gw": None})
    assert half["chips_json"] is None and half["chips_through_gw"] is None       # chips with no gameweek they reach: not stored
    assert fpl_teams.chip_marks(conn=api.conn) == {TID: before[0][1]}


# ---- I6 -------------------------------------------------------------------------------------------------------------------------

def test_i6_the_columns_are_added_once_guarded_and_legacy_rows_are_null(tdb):
    import fpl_teams
    fpl_teams._SCHEMA_READY.clear()
    with tdb.cursor() as cur:
        cur.execute("DROP TABLE IF EXISTS user_fpl_teams")
        cur.execute("DROP SEQUENCE IF EXISTS user_fpl_teams_squad_key_seq")
        cur.execute(fpl_teams.DDL)
        cur.execute(fpl_teams.SUMMARY_DDL)                                       # the table as production has it today
        cur.execute("INSERT INTO user_fpl_teams (user_id, fpl_team_id, label, updated_after_gw) VALUES (10001, 111, 'Legacy', 9)")
    fpl_teams.ensure_schema(tdb)
    fpl_teams.ensure_schema(tdb)                                                 # idempotent
    cols = {r[0]: (r[1], r[2]) for r in _q(tdb, "SELECT column_name, data_type, is_nullable FROM information_schema.columns "
                                              "WHERE table_name = 'user_fpl_teams'")}
    assert cols["chips_json"] == ("jsonb", "YES") and cols["chips_through_gw"] == ("integer", "YES")
    assert _q(tdb, "SELECT chips_json, chips_through_gw, updated_after_gw FROM user_fpl_teams") == [(None, None, 9)]
    assert fpl_teams.chip_marks(conn=tdb) == {111: None}
    assert "chips_json" not in fpl_teams.CARD_COLS and "chips_json" not in fpl_teams.PUBLIC_COLS   # never on the website's card
    src = (REPO / "fpl_teams.py").read_text(encoding="utf-8")
    assert src.count("IF NOT EXISTS (SELECT 1 FROM information_schema.columns") == 2               # both additions guarded
    fpl_teams._SCHEMA_READY.clear()
