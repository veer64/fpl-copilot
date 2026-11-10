"""Prompt W3 (2026-11-05): the backend the Home page needs (clerk mode only; off mode byte-identical; zero-team users unchanged).

USER DECISIONS (5 Nov): "per user you can only enter 3 teams"; general questions with no team ("not against any team"); team
scores from FPL's public history (total from GW1), refreshed weekly; squads refresh only when the user taps Refresh.

H1  at most MAX_TEAMS = 3 teams per user: the 4th import is 409 {"detail": "You can add up to 3 teams"} with nothing written and
    no FPL request.
H2  GET /me/teams returns each team's card: fpl_team_id, label, is_active, last_imported_gw (as before) + entry_name, manager_name,
    total_points, overall_rank, last_gw, last_gw_points, updated_after_gw, summary_updated_at, last_used_at, created_at,
    last_imported_at -- the summary stored at import from the responses the import already fetched (entry + history + the
    bootstrap's finished flags; no extra FPL request). /me's active_team keeps its shape.
H3  DELETE /me/active-team ("general / no team" mode): no team active (/me active_team null), a NEW default thread bound to the
    user's own id (a /chat without an id runs there, owner_key = the user id: zero-team behaviour), the user's open preview
    tickets cancelled; activating a team afterwards works as today (a new default thread bound to the team); a second DELETE
    with no team active changes nothing (the same thread, 0 cancelled); off mode 404; a bad token 401.
H4  activate sets last_used_at; activating the team that is ALREADY active keeps its default thread (no new thread, no ticket
    cancelled) and still bumps last_used_at.
H5  POST /me/teams/{id}/refresh updates the summary as well as the squad (new numbers; summary_updated_at later).
H6  the weekly score refresh (eval/refresh_team_scores.py, run(): the cron job's body): bootstrap once, then ONE history request
    per DISTINCT imported team (through fpl_import.fetch_json, so MIN_INTERVAL_S apart), every user's row of that team updated,
    never the squad (no squad_versions row); without --force a team whose summary already covers FPL's latest finished gameweek
    is skipped with no request; an FPL failure on one team is reported and the others still run.
H7  /threads rows carry fpl_team_id beside team_label (null for a thread of the user's own record).
H8  GET /deadlines: the upcoming gameweek deadlines from FPL's bootstrap (cached per process): {"events": [{gw, deadline_time,
    finished}, ...], "fetched_at"}; off mode 404; a bad token 401.
H9  the summary columns are added by a guarded, idempotent DDL (no ALTER TABLE when they exist); legacy rows NULL.
H10 zero-team users and off mode: /me for 9001 is unchanged; /me/teams of a user with no team is []; the new routes do not exist
    in off mode.

Offline: test_fpl_import's `api` fixture (clerk mode on test_threads' test database, the recorded FPL responses as the
transport, users 10001 / 10002). Teams are never made for users 1 / 9001 / 9002."""
import copy
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
for p in (str(REPO), str(REPO / "squad"), str(REPO / "eval"), str(REPO / "Tests")):
    if p not in sys.path:
        sys.path.insert(0, p)

import fpl_import                                                                     # noqa: E402
from test_auth import app, tdb, c, mint, bearer, _q, _all_counts, _bad_tokens         # noqa: E402,F401  (fixtures)
from test_fpl_import import (api, Fpl, TID, NOW, T1, T2, U1, U2, _offline,            # noqa: E402,F401  (fixtures)
                             _post, _get, _team_rows, load)
import thread_fakes as tf                                                             # noqa: E402

LIMIT = "You can add up to 3 teams"
CARD_KEYS = {"fpl_team_id", "label", "is_active", "last_imported_gw", "entry_name", "manager_name", "total_points",
             "overall_rank", "last_gw", "last_gw_points", "updated_after_gw", "summary_updated_at", "last_used_at",
             "created_at", "last_imported_at"}
SUMMARY_COLS = ("entry_name", "manager_name", "total_points", "overall_rank", "last_gw", "last_gw_points",
                "updated_after_gw", "summary_updated_at", "last_used_at")


def _h(sub=T1):
    return bearer(mint(sub))


def _teams(api, sub=T1):
    r = _get(api, "/me/teams", sub=sub)
    assert r.status_code == 200, r.text
    return r.json()


def _chat(api, message, thread_id=None, sub=T1):
    body = {"message": message}
    if thread_id is not None:
        body["thread_id"] = thread_id
    return api.client.post("/chat", json=body, headers=_h(sub))


def _never_limited(api, monkeypatch):
    clock = {"t": 0.0}
    monkeypatch.setattr(api.users, "monotonic", lambda: clock.update(t=clock["t"] + 61) or clock["t"])


def _finished_through(boot, gw):
    """The recorded bootstrap (its events carry no flags) with FPL's finished / is_next flags as the live one has them."""
    b = copy.deepcopy(boot)
    for e in b["events"]:
        e["finished"] = int(e["id"]) <= gw
        e["is_next"] = int(e["id"]) == gw + 1
    return b


# ---- H1 ----------------------------------------------------------------------------------------------------------------

def test_h1_the_fourth_team_is_refused_with_the_homes_wording_and_nothing_written(api, monkeypatch):
    import fpl_teams
    assert fpl_teams.MAX_TEAMS == 3
    _never_limited(api, monkeypatch)
    for k in range(3):
        assert _post(api, "/me/teams", json={"fpl_team_id": TID + k}).status_code == 200
    before, asked, teams = _all_counts(api.conn), len(api.fpl.asked), _team_rows(api.conn)
    r = _post(api, "/me/teams", json={"fpl_team_id": TID + 7})
    assert r.status_code == 409 and r.json() == {"detail": LIMIT}, r.text
    assert _all_counts(api.conn) == before and _team_rows(api.conn) == teams and len(api.fpl.asked) == asked
    assert len(_teams(api)) == 3


# ---- H2 ----------------------------------------------------------------------------------------------------------------

def test_h2_the_card_is_stored_at_import_from_the_responses_already_fetched(api):
    asked0 = len(api.fpl.asked)
    r = _post(api, "/me/teams", json={"fpl_team_id": TID, "label": "Main"})
    assert r.status_code == 200, r.text
    assert api.fpl.asked[asked0:] == ["bootstrap-static/", f"entry/{TID}/", f"entry/{TID}/history/", f"entry/{TID}/transfers/",
                                      f"entry/{TID}/event/9/picks/"]                 # the import's own requests, nothing more
    [card] = _teams(api)
    assert set(card) == CARD_KEYS, sorted(card)
    assert {k: card[k] for k in ("fpl_team_id", "label", "is_active", "last_imported_gw")} == {
        "fpl_team_id": TID, "label": "Main", "is_active": True, "last_imported_gw": 10}
    # the recorded team: "Fixture XI" by "Test Manager", 735 points, overall rank 1 after GW9 (82 points in it)
    assert {k: card[k] for k in ("entry_name", "manager_name", "total_points", "overall_rank", "last_gw", "last_gw_points",
                                 "updated_after_gw", "last_used_at")} == {
        "entry_name": "Fixture XI", "manager_name": "Test Manager", "total_points": 735, "overall_rank": 1, "last_gw": 9,
        "last_gw_points": 82, "updated_after_gw": 9, "last_used_at": None}
    for k in ("summary_updated_at", "created_at", "last_imported_at"):
        assert isinstance(card[k], str) and card[k].endswith("Z"), (k, card[k])
    # /me's active_team keeps F1a's shape
    assert _get(api, "/me").json()["active_team"] == {"fpl_team_id": TID, "label": "Main", "is_active": True, "last_imported_gw": 10}


def test_h2_the_last_finished_gameweek_comes_from_the_bootstraps_flags(api):
    """FPL's live bootstrap flags finished gameweeks; a team refreshed while GW9 is still being played shows GW8."""
    api.fpl.data["bootstrap"] = _finished_through(api.fpl.data["bootstrap"], 8)
    _post(api, "/me/teams", json={"fpl_team_id": TID})
    [card] = _teams(api)
    assert (card["last_gw"], card["last_gw_points"], card["total_points"], card["overall_rank"], card["updated_after_gw"]) == (
        8, 52, 653, 10, 8)


def test_h2_team_summary_from_the_recorded_responses():
    data = load()
    s = fpl_import.team_summary({"entry": data["entry"], "history": data["history"], "bootstrap": data["bootstrap"]})
    assert s == {"entry_name": "Fixture XI", "manager_name": "Test Manager", "total_points": 735, "overall_rank": 1,
                 "last_gw": 9, "last_gw_points": 82, "updated_after_gw": 9}
    s8 = fpl_import.team_summary({"entry": data["entry"], "history": data["history"],
                                  "bootstrap": _finished_through(data["bootstrap"], 8)})
    assert (s8["last_gw"], s8["last_gw_points"], s8["total_points"], s8["overall_rank"], s8["updated_after_gw"]) == (8, 52, 653, 10, 8)
    # a team with no finished gameweek yet: the entry's own totals, no gameweek
    s0 = fpl_import.team_summary({"entry": data["entry"], "history": {"current": []}, "bootstrap": data["bootstrap"]})
    assert s0 == {"entry_name": "Fixture XI", "manager_name": "Test Manager", "total_points": 735, "overall_rank": None,
                  "last_gw": None, "last_gw_points": None, "updated_after_gw": None}


# ---- H3 ----------------------------------------------------------------------------------------------------------------

def _preview_possible(monkeypatch):
    """The imported squad's version is for GW10 (the recorded team), the stubbed clock says GW9: set_my_squad would refuse
    the preview as stale. The brain's preview needs the clock at the version's gameweek."""
    import model_tools as mt
    monkeypatch.setattr(mt, "_current_gw", lambda: 10)


def test_h3_general_mode_drops_the_active_team_and_starts_a_default_thread_of_the_users_own(api, monkeypatch):
    _preview_possible(monkeypatch)
    _post(api, "/me/teams", json={"fpl_team_id": TID})
    team_thread = _chat(api, "About apple").json()["thread_id"]
    assert _q(api.conn, "SELECT owner_key FROM chat_threads WHERE thread_id = %s", (team_thread,)) == [(900_000_001,)]
    assert _chat(api, tf.PREVIEW_Q).json()["answer"] == "Here is the preview. Shall I apply it?"
    r = api.client.delete("/me/active-team", headers=_h())
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["active_team"] is None and body["deactivated"] == TID and body["preview_tickets_cancelled"] == 1
    own = body["thread_id"]
    assert own != team_thread and _q(api.conn, "SELECT owner_key, is_default FROM chat_threads WHERE thread_id = %s", (own,)) == [(U1, True)]
    assert _get(api, "/me").json()["active_team"] is None
    assert [t["is_active"] for t in _teams(api)] == [False]
    import fpl_teams
    assert fpl_teams.squad_owner_id(U1) == U1                                      # zero-team behaviour: the user's own record
    r = _chat(api, "About banana")                                                # no thread id: runs in the new default
    assert r.status_code == 200 and r.json()["thread_id"] == own
    assert _chat(api, "About cherry", team_thread).status_code == 409             # the team's thread: not the active owner
    # back to the team: as today -- a fresh default thread bound to it
    a = _post(api, f"/me/teams/{TID}/activate")
    assert a.status_code == 200 and a.json()["is_active"] is True
    back = a.json()["thread_id"]
    assert back not in (own, team_thread)
    assert _q(api.conn, "SELECT owner_key, is_default FROM chat_threads WHERE thread_id = %s", (back,)) == [(900_000_001, True)]
    assert _get(api, "/me").json()["active_team"]["fpl_team_id"] == TID


def test_h3_a_second_delete_with_no_team_active_changes_nothing(api):
    _post(api, "/me/teams", json={"fpl_team_id": TID})
    first = api.client.delete("/me/active-team", headers=_h()).json()
    before = _all_counts(api.conn)
    again = api.client.delete("/me/active-team", headers=_h()).json()
    assert again == {"active_team": None, "deactivated": None, "thread_id": first["thread_id"], "preview_tickets_cancelled": 0}
    assert _all_counts(api.conn) == before


def test_h3_a_user_with_no_team_gets_their_default_thread(api):
    r = api.client.delete("/me/active-team", headers=_h(T2))
    assert r.status_code == 200 and r.json()["active_team"] is None and r.json()["deactivated"] is None
    assert _chat(api, "About apple", sub=T2).json()["thread_id"] == r.json()["thread_id"]


# ---- H4 ----------------------------------------------------------------------------------------------------------------

def test_h4_activate_sets_last_used_and_the_active_team_keeps_its_thread(api):
    _post(api, "/me/teams", json={"fpl_team_id": TID})
    _post(api, "/me/teams", json={"fpl_team_id": TID + 1})
    assert [t["last_used_at"] for t in _teams(api)] == [None, None]
    a1 = _post(api, f"/me/teams/{TID}/activate").json()                          # already active: the thread stays
    t1 = {t["fpl_team_id"]: t for t in _teams(api)}
    assert t1[TID]["last_used_at"] is not None and t1[TID + 1]["last_used_at"] is None
    before = _all_counts(api.conn)
    a2 = _post(api, f"/me/teams/{TID}/activate").json()
    assert a2["thread_id"] == a1["thread_id"] and a2["preview_tickets_cancelled"] == 0 and a2["is_active"] is True
    assert _all_counts(api.conn) == before                                       # no new thread row
    t2 = {t["fpl_team_id"]: t for t in _teams(api)}
    assert t2[TID]["last_used_at"] >= t1[TID]["last_used_at"]
    a3 = _post(api, f"/me/teams/{TID + 1}/activate").json()                      # a switch: as today, a new thread
    assert a3["thread_id"] != a1["thread_id"]
    t3 = {t["fpl_team_id"]: t for t in _teams(api)}
    assert t3[TID + 1]["last_used_at"] is not None and t3[TID + 1]["is_active"] is True and t3[TID]["is_active"] is False


def test_h4_the_active_teams_preview_ticket_survives_a_re_activation(api, monkeypatch):
    _preview_possible(monkeypatch)
    _post(api, "/me/teams", json={"fpl_team_id": TID})
    tid = _chat(api, tf.PREVIEW_Q).json()["thread_id"]
    a = _post(api, f"/me/teams/{TID}/activate").json()
    assert a["preview_tickets_cancelled"] == 0 and a["thread_id"] == tid
    assert _chat(api, tf.YES_Q, tid).json()["answer"] == "Written."


# ---- H5 ----------------------------------------------------------------------------------------------------------------

def test_h5_refresh_updates_the_summary_too(api, monkeypatch):
    _post(api, "/me/teams", json={"fpl_team_id": TID})
    [c0] = _teams(api)
    h = copy.deepcopy(api.fpl.data["history"])
    h["current"][-1].update(points=90, total_points=743, overall_rank=3)
    api.fpl.data["history"] = h
    api.fpl.data["entry"] = {**api.fpl.data["entry"], "name": "Fixture XI v2", "player_last_name": "Boss"}
    r = _post(api, f"/me/teams/{TID}/refresh")
    assert r.status_code == 200, r.text
    [c1] = _teams(api)
    assert (c1["total_points"], c1["overall_rank"], c1["last_gw_points"], c1["entry_name"], c1["manager_name"]) == (
        743, 3, 90, "Fixture XI v2", "Test Boss")
    assert c1["summary_updated_at"] >= c0["summary_updated_at"] and c1["last_imported_at"] >= c0["last_imported_at"]
    assert c1["label"] == c0["label"]                                            # the user's label is theirs


# ---- H6 ----------------------------------------------------------------------------------------------------------------

def test_h6_the_weekly_job_refreshes_every_imported_team_once_and_never_the_squad(api, monkeypatch):
    import refresh_team_scores as job
    _post(api, "/me/teams", json={"fpl_team_id": TID})
    _post(api, "/me/teams", json={"fpl_team_id": TID + 1})
    _post(api, "/me/teams", json={"fpl_team_id": TID}, sub=T2)                   # the same team for a second user
    versions = _q(api.conn, "SELECT count(*) FROM squad_versions")[0][0]
    h = copy.deepcopy(api.fpl.data["history"])
    h["current"][-1].update(points=91, total_points=744, overall_rank=2)
    api.fpl.data["history"] = h
    fpl_import._reset()                                                          # a fresh process: no cached bootstrap
    asked0 = len(api.fpl.asked)
    out = job.run(force=True, get=api.fpl)
    assert api.fpl.asked[asked0:] == ["bootstrap-static/", f"entry/{TID}/history/", f"entry/{TID + 1}/history/"]
    assert out["teams"] == 2 and sorted(out["refreshed"]) == [(TID, 2), (TID + 1, 1)] and out["failed"] == [] and out["skipped"] == []
    assert out["requests"] == 3
    rows = _q(api.conn, "SELECT user_id, fpl_team_id, total_points, overall_rank, last_gw_points, entry_name FROM user_fpl_teams ORDER BY id")
    assert rows == [(U1, TID, 744, 2, 91, "Fixture XI"), (U1, TID + 1, 744, 2, 91, "Fixture XI"), (U2, TID, 744, 2, 91, "Fixture XI")]
    assert _q(api.conn, "SELECT count(*) FROM squad_versions")[0][0] == versions   # the squad is never touched


def test_h6_without_force_a_summary_already_after_the_latest_finished_gameweek_is_skipped(api):
    import refresh_team_scores as job
    api.fpl.data["bootstrap"] = _finished_through(api.fpl.data["bootstrap"], 9)
    _post(api, "/me/teams", json={"fpl_team_id": TID})                            # stored after GW9
    with api.conn.cursor() as cur:
        cur.execute("INSERT INTO user_fpl_teams (user_id, fpl_team_id, label, updated_after_gw) VALUES (%s, %s, 'Old', 8)", (U2, TID + 5))
    fpl_import._reset()
    asked0 = len(api.fpl.asked)
    out = job.run(get=api.fpl)
    assert api.fpl.asked[asked0:] == ["bootstrap-static/", f"entry/{TID + 5}/history/"]
    assert out["latest_finished_gw"] == 9 and out["skipped"] == [TID] and [r[0] for r in out["refreshed"]] == [TID + 5]
    assert _q(api.conn, "SELECT updated_after_gw, total_points FROM user_fpl_teams WHERE fpl_team_id = %s", (TID + 5,)) == [(9, 735)]
    fpl_import._reset()
    asked1 = len(api.fpl.asked)
    assert job.run(get=api.fpl)["refreshed"] == [] and api.fpl.asked[asked1:] == ["bootstrap-static/"]   # nothing to do


def test_h6_one_teams_fpl_failure_does_not_stop_the_others(api, monkeypatch):
    import refresh_team_scores as job
    _post(api, "/me/teams", json={"fpl_team_id": TID})
    _post(api, "/me/teams", json={"fpl_team_id": TID + 1})
    real = api.fpl.__call__

    def flaky(url):
        if f"entry/{TID}/history/" in url:
            return 503, None
        return real(url)
    fpl_import._reset()
    out = job.run(force=True, get=flaky)
    assert [f[0] for f in out["failed"]] == [TID] and [r[0] for r in out["refreshed"]] == [TID + 1]
    assert job.exit_code(out) == 1 and job.exit_code({"failed": []}) == 0


def test_h6_the_job_goes_through_fetch_json_so_requests_are_spaced(api, monkeypatch):
    import refresh_team_scores as job
    _post(api, "/me/teams", json={"fpl_team_id": TID})
    _post(api, "/me/teams", json={"fpl_team_id": TID + 1})
    t = {"now": 100.0}
    slept = []
    monkeypatch.setattr(fpl_import, "MIN_INTERVAL_S", 1.0)
    monkeypatch.setattr(fpl_import.time, "monotonic", lambda: t["now"])
    monkeypatch.setattr(fpl_import.time, "sleep", lambda s: (slept.append(round(s, 3)), t.update(now=t["now"] + s)))
    fpl_import._reset()
    job.run(force=True, get=api.fpl)
    assert slept == [1.0, 1.0]                                                   # bootstrap -> history -> history, a second apart


def test_h6_the_cron_line_and_the_argparse_are_documented():
    src = (REPO / "eval" / "refresh_team_scores.py").read_text(encoding="utf-8")
    assert "docker compose run --rm fpl-scheduler uv run python eval/refresh_team_scores.py" in src
    assert "--force" in src


# ---- H7 ----------------------------------------------------------------------------------------------------------------

def test_h7_threads_carry_the_teams_fpl_id(api):
    _post(api, "/me/teams", json={"fpl_team_id": TID, "label": "Main"})
    team_thread = _chat(api, "About apple").json()["thread_id"]
    own = api.client.delete("/me/active-team", headers=_h()).json()["thread_id"]
    _chat(api, "About banana", own)                                          # W4: an empty thread is not listed
    rows = {x["thread_id"]: x for x in _get(api, "/threads").json()}
    assert set(rows[team_thread]) == {"thread_id", "created_at", "last_active", "is_default", "title", "team_label", "fpl_team_id",
                                      "team_name", "updated_at"}
    assert (rows[team_thread]["fpl_team_id"], rows[team_thread]["team_label"], rows[team_thread]["team_name"]) == (TID, "Main", "Main")
    assert (rows[own]["fpl_team_id"], rows[own]["team_label"], rows[own]["team_name"]) == (None, None, None)


# ---- H8 ----------------------------------------------------------------------------------------------------------------

def test_h8_deadlines_are_the_upcoming_gameweeks_from_the_cached_bootstrap(api):
    api.fpl.data["bootstrap"] = _finished_through(api.fpl.data["bootstrap"], 9)
    fpl_import._reset()
    asked0 = len(api.fpl.asked)
    r = _get(api, "/deadlines")
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body) == {"events", "fetched_at"} and body["fetched_at"].endswith("Z")
    assert body["events"][0] == {"gw": 10, "deadline_time": "2026-11-06T18:30:00Z", "finished": False}
    assert [e["gw"] for e in body["events"]] == [10, 11, 12, 13] and all(e["deadline_time"] > NOW.strftime("%Y-%m-%dT%H:%M:%SZ") for e in body["events"])
    assert _get(api, "/deadlines").status_code == 200
    assert api.fpl.asked[asked0:] == ["bootstrap-static/"]                       # cached: one request for two calls
    # Prompt W5 (checkpoint Q1 A): /deadlines is open in clerk mode -- public FPL data, no token needed, a bad token ignored
    assert api.client.get("/deadlines").status_code == 200
    assert api.client.get("/deadlines", headers=bearer(_bad_tokens()["wrong azp"])).status_code == 200


def test_h8_deadlines_when_fpl_is_down(api):
    fpl_import._reset()
    api.fpl.status = 503
    r = _get(api, "/deadlines")
    assert r.status_code == 503 and "FPL" in r.json()["detail"]


# ---- H9 ----------------------------------------------------------------------------------------------------------------

def test_h9_the_summary_columns_are_added_once_guarded_and_legacy_rows_are_null(tdb):
    import fpl_teams
    fpl_teams._SCHEMA_READY.clear()
    with tdb.cursor() as cur:
        cur.execute("DROP TABLE IF EXISTS user_fpl_teams")
        cur.execute("DROP SEQUENCE IF EXISTS user_fpl_teams_squad_key_seq")
        cur.execute(fpl_teams.DDL)                                               # F1a's table, without the columns
        cur.execute("INSERT INTO user_fpl_teams (user_id, fpl_team_id, label) VALUES (10001, 111, 'Legacy')")
    fpl_teams.ensure_schema(tdb)
    fpl_teams.ensure_schema(tdb)                                                 # idempotent
    cols = {r[0]: (r[1], r[2]) for r in _q(tdb, "SELECT column_name, data_type, is_nullable FROM information_schema.columns "
                                              "WHERE table_name = 'user_fpl_teams'")}
    for c_ in SUMMARY_COLS:
        assert c_ in cols and cols[c_][1] == "YES", c_
    assert cols["last_used_at"][0] == "timestamp with time zone" and cols["total_points"][0] == "integer"
    assert _q(tdb, "SELECT " + ", ".join(SUMMARY_COLS) + " FROM user_fpl_teams WHERE fpl_team_id = 111") == [(None,) * len(SUMMARY_COLS)]
    src = (REPO / "fpl_teams.py").read_text(encoding="utf-8")
    assert "IF NOT EXISTS (SELECT 1 FROM information_schema.columns" in src       # guarded: no ACCESS EXCLUSIVE lock each run
    [card] = fpl_teams.team_cards(10001, conn=tdb)
    assert card["entry_name"] is None and card["last_used_at"] is None and card["label"] == "Legacy"
    fpl_teams._SCHEMA_READY.clear()


# ---- H10 ---------------------------------------------------------------------------------------------------------------

def test_h10_zero_team_users_are_unchanged(api):
    assert api.client.get("/me", headers=bearer(mint("user_a9001"))).json() == {
        "user_id": 9001, "is_admin": False, "is_owner": False, "daily_cap_usd": 1.0, "spent_today_usd": 0.0, "active_team": None}
    assert _get(api, "/me/teams", sub=T2).json() == []


@pytest.mark.parametrize("method,path", [("delete", "/me/active-team"), ("get", "/deadlines"), ("get", "/me/teams")])
def test_h10_off_mode_has_none_of_the_routes(app, monkeypatch, method, path):
    from fastapi.testclient import TestClient
    monkeypatch.delenv("AUTH_MODE", raising=False)
    r = getattr(app.client, method)(path)
    assert r.status_code == 404 and r.json() == {"detail": "Not Found"}
    assert getattr(TestClient(app.main.app), method)(path).status_code == 401


@pytest.mark.parametrize("case", ["missing", "expired", "no azp", "wrong azp"])
def test_h10_a_bad_token_is_401_on_the_new_routes(api, case):
    """/deadlines left this list with Prompt W5 (checkpoint Q1 A): it is open in clerk mode -- test_deletion_backend D."""
    token = _bad_tokens()[case]
    before = _all_counts(api.conn)
    for method, path in (("delete", "/me/active-team"), ("get", "/me/teams")):
        r = getattr(api.client, method)(path, headers=bearer(token) if token else {})
        assert r.status_code == 401, (case, path, r.status_code)
    assert _all_counts(api.conn) == before and api.fpl.asked == []
