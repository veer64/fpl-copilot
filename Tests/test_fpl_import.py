"""Prompt F1a Part 5 (2026-11-02): FPL team import (fpl_import.py) and the team endpoints (/me/teams...).

The FPL responses are RECORDED (Tests/fixtures/fpl_import/): a top-50 entry of FPL's overall league (314) fetched 2 Nov 2026
20:08Z (entry, history, transfers, GW9 and GW8 picks), anonymised -- its id is 4242424, its names replaced; every number is
as recorded. bootstrap.json is the local poller snapshot of 31 Oct 2026 11:00:03Z, trimmed to the elements involved. No
network in pytest: the transport is a fake reading those files. The recorded team played a free hit in GW3 and a wildcard in
GW9 (FPL's history shows event_transfers 0 for both weeks) and took a 4-point hit in GW6.

I1 the import of the recorded team: 15 players, legal by squad_store and squad_state; roles from the picks; bank = FPL's
   entry_history.bank exactly; purchase prices = element_in_cost of the latest transfer (free-hit weeks ignored), else the
   start price (the entry started in GW1); version gw = the next deadline's (GW10); provenance names the source, the picks
   gameweek, the fetch time and every estimated value.
I2 a free hit in the latest gameweek -> the previous gameweek's picks and bank (noted).
I3 free transfers: squad_state's rule; a wildcard / free hit week spends and earns none (the recorded GW6 hit fits only
   that); FPL's hit charge corrects a disagreeing count (listed); the cap from game_settings, else 5 (noted).
I4 an entry that started after GW1: the held-since-the-start players' prices from element-summary (estimated, listed).
I5 FPL errors: 404 -> FplNotFound; 5xx / 429 / a timeout -> FplUnavailable; no deadline passed / no picks yet -> ImportRefused.
I6 requests are spaced MIN_INTERVAL_S apart.
J1-J9 the endpoints (clerk mode; 404 in off mode): import, list, activate, refresh; 409 / 422 / 404 / 503 / 429; another
   user's team -> 404 with nothing written, no FPL request and no model call; the same FPL team for two users -> two records.
Teams are made only for new test users (>= 10001) on test_threads' test database."""
import copy
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
for p in (str(REPO), str(REPO / "squad"), str(REPO / "Tests")):
    if p not in sys.path:
        sys.path.insert(0, p)

import fpl_import                                                                     # noqa: E402
import squad_store                                                                    # noqa: E402
from test_auth import app, tdb, c, mint, bearer, _q, _all_counts, _bad_tokens         # noqa: E402,F401  (fixtures)

FIX = REPO / "Tests" / "fixtures" / "fpl_import"
TID = 4242424
NOW = datetime(2026, 11, 2, 20, 0, tzinfo=timezone.utc)          # GW9's deadline passed (31 Oct), GW10's not (6 Nov)


def load():
    return {n: json.loads((FIX / f"{n}.json").read_text(encoding="utf-8"))
            for n in ("bootstrap", "entry", "history", "transfers", "picks_9", "picks_8")}


class Fpl:
    """The fake transport: FPL's paths -> (status, body) from the recorded files (any team id serves the recorded team,
    with its id); `status` forces an answer for every path; every path asked is kept in .asked."""

    def __init__(self, data=None, status=None, summaries=None):
        self.data, self.status, self.asked, self.summaries = data or load(), status, [], summaries or {}

    def __call__(self, url):
        path = url.split("/api/", 1)[1]
        self.asked.append(path)
        if self.status is not None:
            return self.status, None
        parts = path.strip("/").split("/")
        if path == "bootstrap-static/":
            return 200, self.data["bootstrap"]
        if parts[0] == "element-summary":
            s = self.summaries.get(int(parts[1]))
            return (200, s) if s is not None else (404, None)
        if parts[0] != "entry":
            return 404, None
        if len(parts) == 2:
            return 200, {**self.data["entry"], "id": int(parts[1])}
        if parts[2] in ("history", "transfers"):
            return 200, self.data[parts[2]]
        if parts[2] == "event" and parts[4] == "picks" and f"picks_{parts[3]}" in self.data:
            return 200, self.data[f"picks_{parts[3]}"]
        return 404, None


@pytest.fixture(autouse=True)
def _offline(monkeypatch):
    monkeypatch.setattr(fpl_import, "MIN_INTERVAL_S", 0)
    monkeypatch.setattr(fpl_import, "clock", lambda: NOW)
    monkeypatch.setattr(fpl_import, "_http_get", lambda url: (_ for _ in ()).throw(AssertionError(f"network: {url}")))
    fpl_import._reset()
    yield
    fpl_import._reset()


def _build(fpl):
    raw = fpl_import.fetch_team(TID, get=fpl)
    return fpl_import.build(raw, {}, "2026-27")


def _by(doc):
    return {p["element"]: p for p in doc["players"]}


# ---- I1 ---------------------------------------------------------------------------------------------------------------

def test_i1_the_recorded_team_imports_legal_with_fpls_bank_and_roles():
    fpl = Fpl()
    doc, info = _build(fpl)
    data = load()
    squad_store.validate_document(doc)
    squad_store.to_state(doc)
    assert len(doc["players"]) == 15 and doc["bank"] == data["picks_9"]["entry_history"]["bank"] == 23
    assert doc["total_points"] == 735 and info["picks_gw"] == 9 and info["version_gw"] == 10
    picks = {p["element"]: p for p in data["picks_9"]["picks"]}
    by = _by(doc)
    assert set(by) == set(picks)
    assert [e for e, p in by.items() if p["role"] == "CAPTAIN"] == [411] and [e for e, p in by.items() if p["role"] == "VICE"] == [166]
    assert sorted((p["bench_order"], e) for e, p in by.items() if p["role"] == "bench") == [(1, 1), (2, 124), (3, 31), (4, 305)]
    assert all(by[e]["role"] in ("start", "CAPTAIN", "VICE") for e, p in picks.items() if p["position"] <= 11)
    assert fpl.asked == ["bootstrap-static/", f"entry/{TID}/", f"entry/{TID}/history/", f"entry/{TID}/transfers/",
                         f"entry/{TID}/event/9/picks/"]


def test_i1_purchase_prices_are_the_latest_buy_else_the_start_price():
    doc, info = _build(Fpl())
    boot = {e["id"]: e for e in load()["bootstrap"]["elements"]}
    by = _by(doc)
    bought = {79: 63, 112: 49, 53: 61, 67: 63, 166: 69, 334: 50, 31: 46, 154: 97, 40: 76}     # element_in_cost, recorded
    for e, cost in bought.items():
        assert by[e]["purchase_price"] == cost, e
    for e in (496, 115, 411, 1, 124, 305):                                       # held since GW1 (or sold only in the free hit)
        assert by[e]["purchase_price"] == boot[e]["now_cost"] - boot[e]["cost_change_start"], e
    assert not any(x.startswith("purchase_price") for x in info["estimated"])    # all exact for a GW1 entry


def test_i1_a_free_hit_weeks_transfer_never_sets_a_price():
    data = load()
    data["transfers"].append({"element_in": 411, "element_in_cost": 999, "element_out": 79, "element_out_cost": 63,
                              "entry": TID, "event": 3, "time": "2026-09-04T17:00:00Z"})   # GW3 was the free hit
    doc, _ = _build(Fpl(data))
    boot = {e["id"]: e for e in data["bootstrap"]["elements"]}
    assert _by(doc)[411]["purchase_price"] == boot[411]["now_cost"] - boot[411]["cost_change_start"]


def test_i1_provenance_names_the_source_and_every_estimate():
    doc, info = _build(Fpl())
    prov = doc["provenance"]
    assert prov["source"] == "fpl_import" and prov["fpl_team_id"] == TID and prov["picks_gw"] == 9
    assert prov["fetched_at"] == "2026-11-02T20:00:00Z" and prov["hypothetical"] is False
    assert prov["estimated"] == info["estimated"] == [
        "free_transfers: GW3 was a freehit -- its transfers were free, the saved free transfers kept and none earned that week",
        "free_transfers: GW9 was a wildcard -- its transfers were free, the saved free transfers kept and none earned that week"]
    assert prov["notes"] == ["free-transfer cap 5 = 1 + game_settings.max_extra_free_transfers (4)"]
    assert doc["free_transfers"] == 1


def test_i1_players_live_names_win_over_bootstrap():
    raw = fpl_import.fetch_team(TID, get=Fpl())
    doc, _ = fpl_import.build(raw, {411: {"name": "Erling Haaland", "position": "FWD", "team": "Man City"}}, "2026-27")
    assert _by(doc)[411]["name"] == "Erling Haaland" and _by(doc)[411]["team"] == "Man City"


# ---- I2 ---------------------------------------------------------------------------------------------------------------

def test_i2_a_free_hit_in_the_latest_gameweek_takes_the_squad_it_reverts_to():
    data = load()
    data["picks_9"]["active_chip"] = "freehit"
    data["history"]["chips"] = [c for c in data["history"]["chips"] if c["event"] != 9] + [
        {"name": "freehit", "time": "2026-10-31T10:47:54Z", "event": 9}]
    fpl = Fpl(data)
    doc, info = _build(fpl)
    assert info["picks_gw"] == 8 and doc["provenance"]["picks_gw"] == 8 and info["version_gw"] == 10
    assert set(_by(doc)) == {p["element"] for p in data["picks_8"]["picks"]}
    assert doc["bank"] == data["picks_8"]["entry_history"]["bank"] == 5
    assert "GW9 was a free hit: the squad is GW8's, the one the free hit reverts to" in info["notes"]
    assert fpl.asked[-2:] == [f"entry/{TID}/event/9/picks/", f"entry/{TID}/event/8/picks/"]
    assert _by(doc)[334]["purchase_price"] == 50                                 # the GW8 buy, not a free-hit week's
    squad_store.to_state(doc)


def test_i2_automatic_substitutions_are_undone():
    """FPL's GW8 picks of the recorded team show its autosub applied: 334 (on) in 165's slot 5, 165 -- the vice-captain --
    in 334's bench slot 13. The team as the manager set it has 165 in the XI and 334 first outfield sub."""
    data = load()
    pos, n = fpl_import.manager_positions(data["picks_8"], 8)
    assert n == 1 and pos[165] == 5 and pos[334] == 13
    data["picks_9"]["active_chip"] = "freehit"
    data["history"]["chips"] = [c for c in data["history"]["chips"] if c["event"] != 9] + [
        {"name": "freehit", "time": "2026-10-31T10:47:54Z", "event": 9}]
    doc, info = _build(Fpl(data))
    by = _by(doc)
    assert by[165]["role"] == "VICE" and by[334]["role"] == "bench" and by[334]["bench_order"] == 2
    assert "GW8's 1 automatic substitution(s) undone: the line-up as the manager set it" in info["notes"]


# ---- I3 ---------------------------------------------------------------------------------------------------------------

def _hist(rows, chips=()):
    return {"current": [{"event": g, "event_transfers": n, "event_transfers_cost": cost} for g, n, cost in rows],
            "chips": [{"name": nm, "event": g} for nm, g in chips]}


def test_i3_the_recorded_hit_fits_only_no_earning_in_a_chip_week():
    h = load()["history"]
    ft, est = fpl_import.derive_free_transfers(h, 1, 9, 5)
    assert ft == 1 and not [x for x in est if "charged" in x]                    # the GW6 hit agrees with the derived count


@pytest.mark.parametrize("rows,chips,want,flagged", [
    ([(2, 0, 0), (3, 0, 0), (4, 0, 0)], (), 4, False),                          # +1 a week
    ([(g, 0, 0) for g in range(2, 12)], (), 5, False),                          # capped at 5
    ([(2, 0, 0), (3, 3, 4)], (), 1, False),                                      # 2 free + 1 paid, then +1
    ([(2, 2, 0)], (), 1, True),                                                  # 2 free with 1 derived: FPL's charge wins
    ([(2, 0, 0), (3, 1, 4)], (), 1, True),                                       # a hit with 2 derived: FPL's charge wins
    ([(2, 0, 0), (3, 5, 0)], (("wildcard", 3),), 2, False),                      # a wildcard spends and earns none
])
def test_i3_free_transfers_follow_squad_states_rule(rows, chips, want, flagged):
    ft, est = fpl_import.derive_free_transfers(_hist(rows, chips), 1, rows[-1][0], 5)
    assert ft == want
    assert bool([x for x in est if "charged" in x]) is flagged


def test_i3_the_cap_comes_from_game_settings_else_five():
    assert fpl_import.ft_cap({"game_settings": {"max_extra_free_transfers": 2}})[0] == 3
    cap, note = fpl_import.ft_cap({"game_settings": {}})
    assert cap == 5 and "assumed" in note


# ---- I4 ---------------------------------------------------------------------------------------------------------------

def test_i4_a_late_starter_prices_its_first_squad_from_element_summary():
    data = load()
    data["entry"]["started_event"] = 4
    data["transfers"] = [t for t in data["transfers"] if t["event"] >= 4]
    data["history"]["chips"] = [c for c in data["history"]["chips"] if c["event"] >= 4]
    held = [p["element"] for p in data["picks_9"]["picks"]]
    bought = {t["element_in"] for t in data["transfers"] if t["event"] <= 9 and t["event"] != 3}
    first = [e for e in held if e not in bought]
    summaries = {e: {"history": [{"round": 3, "value": 10, "kickoff_time": "a"}, {"round": 4, "value": 40 + i, "kickoff_time": "b"}]}
                 for i, e in enumerate(first)}
    fpl = Fpl(data, summaries=summaries)
    doc, info = _build(fpl)
    for i, e in enumerate(first):
        assert _by(doc)[e]["purchase_price"] == 40 + i
    assert sorted(x for x in fpl.asked if x.startswith("element-summary")) == sorted(f"element-summary/{e}/" for e in first)
    priced = [x for x in info["estimated"] if x.startswith("purchase_price")]
    assert len(priced) == len(first) and all("GW4" in x for x in priced)


# ---- I5 ---------------------------------------------------------------------------------------------------------------

def test_i5_fpl_errors_are_named():
    with pytest.raises(fpl_import.FplNotFound):
        fpl_import.fetch_team(TID, get=lambda url: (404, None) if "/entry/" in url else (200, load()["bootstrap"]))
    for status in (500, 502, 503, 429, 403):
        fpl_import._reset()
        with pytest.raises(fpl_import.FplUnavailable):
            fpl_import.fetch_team(TID, get=Fpl(status=status))

    def timeout(url):
        raise fpl_import.FplUnavailable("FPL could not be reached: ReadTimeout")
    fpl_import._reset()
    with pytest.raises(fpl_import.FplUnavailable):
        fpl_import.fetch_team(TID, get=timeout)


def test_i5_nothing_to_import_yet_is_refused():
    with pytest.raises(fpl_import.ImportRefused):
        fpl_import.fetch_team(TID, now=datetime(2026, 8, 1, tzinfo=timezone.utc), get=Fpl())
    data = load()
    data["entry"]["started_event"] = 10
    fpl_import._reset()
    with pytest.raises(fpl_import.ImportRefused, match="GW10"):
        fpl_import.fetch_team(TID, get=Fpl(data))


# ---- I6 ---------------------------------------------------------------------------------------------------------------

def test_i6_requests_are_spaced(monkeypatch):
    t = {"now": 100.0}
    slept = []
    monkeypatch.setattr(fpl_import, "MIN_INTERVAL_S", 1.0)
    monkeypatch.setattr(fpl_import.time, "monotonic", lambda: t["now"])
    monkeypatch.setattr(fpl_import.time, "sleep", lambda s: (slept.append(round(s, 3)), t.update(now=t["now"] + s)))
    fpl_import._reset()
    fpl = Fpl()
    fpl_import.fetch_json("bootstrap-static/", get=fpl)
    t["now"] += 0.25
    fpl_import.fetch_json(f"entry/{TID}/", get=fpl)
    assert slept == [0.75]


# ---- J: the endpoints ---------------------------------------------------------------------------------------------------

T1, T2 = "user_t1", "user_t2"
U1, U2 = 10_001, 10_002


@pytest.fixture
def api(c, monkeypatch):
    """Clerk mode on the test database: user_fpl_teams fresh, users 10001 / 10002 signed up, FPL faked, the season and the
    players_live names stubbed (the test database has no model run and no players_live)."""
    import fpl_teams
    import model_tools
    with c.conn.cursor() as cur:
        cur.execute("DROP TABLE IF EXISTS user_fpl_teams")
        cur.execute("DROP SEQUENCE IF EXISTS user_fpl_teams_squad_key_seq")
        cur.execute("INSERT INTO app_users (user_id, clerk_user_id, email, name, sign_in_method, profile_fetched_at) VALUES "
                    "(%s, %s, 't1@example.test', 'T One', 'email', now()), (%s, %s, 't2@example.test', 'T Two', 'email', now())",
                    (U1, T1, U2, T2))
    fpl_teams._SCHEMA_READY.clear()
    fpl = Fpl()
    monkeypatch.setattr(fpl_import, "_http_get", fpl)
    monkeypatch.setattr(model_tools, "_season_label", lambda: "2026-27")
    monkeypatch.setattr(fpl_import, "players_live_meta", lambda elements, conn=None: {})
    c.fpl = fpl
    yield c
    fpl_teams._SCHEMA_READY.clear()


def _post(api, path, sub=T1, **kw):
    return api.client.post(path, headers=bearer(mint(sub)), **kw)


def _get(api, path, sub=T1):
    return api.client.get(path, headers=bearer(mint(sub)))


def _team_rows(conn):
    if not _q(conn, "SELECT to_regclass('public.user_fpl_teams') IS NOT NULL")[0][0]:
        return []                                                                  # refused before the table was ever needed
    return _q(conn, "SELECT user_id, fpl_team_id, label, is_active, squad_key, last_imported_gw FROM user_fpl_teams ORDER BY id")


def test_j1_import_list_and_me(api):
    r = _post(api, "/me/teams", json={"fpl_team_id": TID, "label": "Main"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert {k: body[k] for k in ("fpl_team_id", "label", "is_active", "last_imported_gw", "picks_gw")} == {
        "fpl_team_id": TID, "label": "Main", "is_active": True, "last_imported_gw": 10, "picks_gw": 9}
    assert len(body["estimated"]) == 2 and body["version_id"]
    [(uid, fid, label, active, key, gw)] = _team_rows(api.conn)
    assert (uid, fid, label, active, gw) == (U1, TID, "Main", True, 10) and key == 900_000_001
    row = _q(api.conn, "SELECT user_id, gw, is_active, supersedes, squad_json->'provenance'->>'source', "
                       "(squad_json->>'bank')::int FROM squad_versions WHERE version_id = %s", (body["version_id"],))
    assert row == [(key, 10, True, None, "fpl_import", 23)]
    assert _get(api, "/me/teams").json() == [{"fpl_team_id": TID, "label": "Main", "is_active": True, "last_imported_gw": 10}]
    assert _get(api, "/me").json()["active_team"] == {"fpl_team_id": TID, "label": "Main", "is_active": True, "last_imported_gw": 10}
    import fpl_teams
    assert fpl_teams.squad_owner_id(U1) == key


def test_j1_the_label_defaults_to_the_fpl_teams_name(api):
    assert _post(api, "/me/teams", json={"fpl_team_id": TID}).json()["label"] == "Fixture XI"


def test_j2_a_second_team_is_not_active_until_activated(api):
    _post(api, "/me/teams", json={"fpl_team_id": TID})
    r = _post(api, "/me/teams", json={"fpl_team_id": TID + 1, "label": "Second"})
    assert r.status_code == 200 and r.json()["is_active"] is False
    r = _post(api, f"/me/teams/{TID + 1}/activate")
    body = r.json()
    thread_id = body.pop("thread_id", None)                                 # F1b: activation starts a new default thread
    assert r.status_code == 200 and body == {"fpl_team_id": TID + 1, "label": "Second", "is_active": True,
                                             "last_imported_gw": 10, "preview_tickets_cancelled": 0}
    assert isinstance(thread_id, str) and thread_id.startswith("th_")
    assert _q(api.conn, "SELECT owner_key, is_default FROM chat_threads WHERE thread_id = %s", (thread_id,)) == [(900_000_002, True)]
    assert [(t["fpl_team_id"], t["is_active"]) for t in _get(api, "/me/teams").json()] == [(TID, False), (TID + 1, True)]
    import fpl_teams
    assert fpl_teams.squad_owner_id(U1) == 900_000_002


def test_j3_refresh_writes_a_new_version_append_only(api):
    first = _post(api, "/me/teams", json={"fpl_team_id": TID}).json()
    r = _post(api, f"/me/teams/{TID}/refresh")
    assert r.status_code == 200, r.text
    assert r.json()["supersedes"] == first["version_id"] and r.json()["version_id"] != first["version_id"]
    rows = _q(api.conn, "SELECT version_id, is_active, supersedes FROM squad_versions WHERE user_id = 900000001 ORDER BY version_id")
    assert rows == [(first["version_id"], False, None), (r.json()["version_id"], True, first["version_id"])]


def test_j4_a_duplicate_or_a_sixth_team_is_409_with_nothing_written(api, monkeypatch):
    clock = {"t": 0.0}
    monkeypatch.setattr(api.users, "monotonic", lambda: clock.update(t=clock["t"] + 61) or clock["t"])   # never rate-limited
    for k in range(5):
        assert _post(api, "/me/teams", json={"fpl_team_id": TID + k}).status_code == 200
    before, asked = _all_counts(api.conn), len(api.fpl.asked)
    teams = _team_rows(api.conn)
    r = _post(api, "/me/teams", json={"fpl_team_id": TID})
    assert r.status_code == 409 and "already added" in r.json()["detail"]
    r = _post(api, "/me/teams", json={"fpl_team_id": TID + 9})
    assert r.status_code == 409 and r.json() == {"detail": "at most 5 FPL teams per user"}
    assert _all_counts(api.conn) == before and _team_rows(api.conn) == teams and len(api.fpl.asked) == asked   # no FPL request


@pytest.mark.parametrize("body", [{"fpl_team_id": 0}, {"fpl_team_id": 100_000_000}, {"fpl_team_id": "4242424"},
                                  {"fpl_team_id": 1.5}, {"fpl_team_id": True}, {}, None,
                                  {"fpl_team_id": TID, "label": "x" * 41}, {"fpl_team_id": TID, "label": 7}])
def test_j5_an_invalid_id_or_label_is_422(api, body):
    r = _post(api, "/me/teams", json=body)
    assert r.status_code == 422, (body, r.status_code, r.text)
    assert _team_rows(api.conn) == [] and api.fpl.asked == []


@pytest.mark.parametrize("tid", ["0", "abc", "123456789", "-5", "1e3", "١"])
@pytest.mark.parametrize("verb", ["activate", "refresh"])
def test_j5_an_invalid_path_id_is_422(api, tid, verb):
    r = _post(api, f"/me/teams/{tid}/{verb}")
    assert r.status_code == 422, (tid, verb, r.status_code, r.text)


@pytest.mark.parametrize("status,code", [(404, 404), (500, 503), (503, 503), (429, 503)])
def test_j6_fpl_failures_write_nothing(api, status, code):
    api.fpl.status = status
    before = _all_counts(api.conn)
    r = _post(api, "/me/teams", json={"fpl_team_id": TID})
    assert r.status_code == code, r.text
    if code == 404:
        assert r.json() == {"detail": "FPL team not found"}
    assert _team_rows(api.conn) == [] and _all_counts(api.conn) == before


def test_j6_a_refresh_that_fails_at_fpl_writes_nothing(api):
    _post(api, "/me/teams", json={"fpl_team_id": TID})
    before, teams = _all_counts(api.conn), _team_rows(api.conn)
    api.fpl.status = 502
    assert _post(api, f"/me/teams/{TID}/refresh").status_code == 503
    assert _all_counts(api.conn) == before and _team_rows(api.conn) == teams


def test_j7_another_users_team_is_404_with_nothing_written_and_no_fpl_request(api):
    _post(api, "/me/teams", json={"fpl_team_id": TID})
    before, asked, calls, teams = _all_counts(api.conn), len(api.fpl.asked), api.brain.calls, _team_rows(api.conn)
    for verb in ("activate", "refresh"):
        r = _post(api, f"/me/teams/{TID}/{verb}", sub=T2)
        assert r.status_code == 404 and r.json() == {"detail": "team not found for this user"}, (verb, r.text)
    assert _get(api, "/me/teams", sub=T2).json() == []
    assert (_all_counts(api.conn), len(api.fpl.asked), api.brain.calls, _team_rows(api.conn)) == (before, asked, calls, teams)


def test_j7_the_same_fpl_team_for_two_users_is_two_records(api):
    a = _post(api, "/me/teams", json={"fpl_team_id": TID}).json()
    b = _post(api, "/me/teams", json={"fpl_team_id": TID}, sub=T2).json()
    rows = _team_rows(api.conn)
    assert [(r[0], r[1], r[4]) for r in rows] == [(U1, TID, 900_000_001), (U2, TID, 900_000_002)]
    assert a["version_id"] != b["version_id"]


def test_j8_the_sixth_import_or_refresh_in_a_minute_is_429(api, monkeypatch):
    monkeypatch.setattr(api.users, "monotonic", lambda: 5000.0)
    assert _post(api, "/me/teams", json={"fpl_team_id": TID}).status_code == 200
    codes = [_post(api, f"/me/teams/{TID}/refresh").status_code for _ in range(5)]
    assert codes == [200, 200, 200, 200, 429]
    assert _post(api, f"/me/teams/{TID}/activate").status_code == 200           # activation is not an import
    with api.conn.cursor() as cur:
        cur.execute("UPDATE app_users SET is_admin = TRUE, is_exempt = TRUE WHERE user_id = %s", (U2,))
    assert [_post(api, "/me/teams", json={"fpl_team_id": TID + k}, sub=T2).status_code for k in range(6)][-1] == 429


ROUTES = [("get", "/me/teams", None), ("post", "/me/teams", {"fpl_team_id": TID}),
          ("post", f"/me/teams/{TID}/activate", None), ("post", f"/me/teams/{TID}/refresh", None)]


@pytest.mark.parametrize("case", ["missing", "expired", "no azp", "wrong azp"])
@pytest.mark.parametrize("method,path,body", ROUTES)
def test_j9_a_bad_token_is_401_before_anything(api, case, method, path, body):
    token = _bad_tokens()[case]
    before = _all_counts(api.conn)
    kw = {"headers": bearer(token) if token else {}}
    if body is not None:
        kw["json"] = body
    r = getattr(api.client, method)(path, **kw)
    assert r.status_code == 401, (case, path, r.status_code)
    assert _all_counts(api.conn) == before and api.fpl.asked == []


@pytest.mark.parametrize("method,path,body", ROUTES + [("post", "/me/teams", {"fpl_team_id": "bad"}),
                                                       ("post", "/me/teams/abc/activate", None)])
def test_j9_off_mode_has_none_of_them(app, monkeypatch, method, path, body):
    from fastapi.testclient import TestClient
    monkeypatch.delenv("AUTH_MODE", raising=False)
    kw = {} if body is None else {"json": body}
    r = getattr(app.client, method)(path, **kw)
    assert r.status_code == 404 and r.json() == {"detail": "Not Found"}, (path, r.status_code, r.text)
    assert getattr(TestClient(app.main.app), method)(path, **kw).status_code == 401
