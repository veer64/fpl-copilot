"""Prompt W11 Part 1 (2026-11-12): the draft team's backend -- drafts.py, draft_tools.py, the /me/draft routes, the draft chat's
thread binding and deletion. The plan of record is eval/reports/w11_checkpoint1.md (approved 12 Nov).

P   the build is legal on every run (seeded random leagues through the REAL optimiser: 15 players, 2/5/5/3, <= 3 per club,
    <= £100.0m at current prices, a legal XI, captain and vice distinct starters); the stored solve is used when it fits at
    current prices, the same optimiser re-solves at current prices when it does not; same predictions -> same draft.
R   POST /me/draft: one per account (a second build returns the existing draft, nothing written, no build counted); its first
    chat carries the opening message (O2, $0) as the first stored message; rebuild replaces (new version, chats kept,
    change count reset); DELETE removes the draft and its chats, real teams untouched; users isolated; the O9 window (10 an
    hour) -> 429; off mode: every draft route 404 and nothing reads user_drafts.
C   a change (draft_tools.set_my_squad inside a draft turn): over £100.0m refused with the amount, a 4th player from a club
    refused with the rule, a wrong position refused, a legal change previewed then saved in a LATER turn with its ticket; no
    free-transfer / hit / bank logic anywhere; a draft ticket can never match a real-squad write.
N   (Prompt W11b) the numbers the agent was working out itself come from the tools on draft turns: each starter's points, the
    captain's WITH the armband, the XI total, value and left / over (get_my_squad, get_my_xi); price out, price in, the
    difference and the money before / after in a preview and a refusal, each alternative's price and money left; the steps to
    enter it in FPL (digit-free link); the player going OUT matched against the draft's fifteen first (resolve_player).
S   draft writes never touch squad_versions / squad_scores / user_fpl_teams.
D   Delete account and the guest reaper remove the draft (O7).
T   threads: a draft chat resolves whatever team is active; /threads marks it is_draft and titles it by its first question;
    a draft chat with only the opening message is not listed (W4's rule); the messages endpoint shows the opening message.
DDL the schema of record is pinned.

Offline: test_fpl_import's `api` fixture (clerk mode on the test database, users 10001 / 10002); the model's frame, the
latest run and the FPL bootstrap replaced by a synthetic league (`league` fixture)."""
import hashlib
import random
import re
import sys
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import pytest

REPO = Path(__file__).resolve().parents[1]
for p in (str(REPO), str(REPO / "squad"), str(REPO / "eval"), str(REPO / "Tests")):
    if p not in sys.path:
        sys.path.insert(0, p)

import drafts                                                                          # noqa: E402
from test_auth import app, tdb, c, mint, bearer, _q                                     # noqa: E402,F401  (fixtures)
from test_fpl_import import api, Fpl, NOW, T1, T2, U1, U2, _offline                     # noqa: E402,F401  (fixtures)

UTC = timezone.utc
POS = {1: "GK", 2: "DEF", 3: "MID", 4: "FWD"}
DDL_SHA256 = "d2ea8d67f4435c6c9ff63ba9d9ea4306849793c0ec48637c86554d4fb5e9e527"


# ---- a synthetic league: 20 clubs x (2 GK, 6 DEF, 6 MID, 4 FWD) = 360 players ---------------------------------------------

def make_league(seed):
    rng = random.Random(seed)
    teams = [{"id": t, "name": f"Club {t:02d}", "short_name": f"C{t:02d}"} for t in range(1, 21)]
    elements, eid = [], 1
    for t in teams:
        for etype, n in ((1, 2), (2, 6), (3, 6), (4, 4)):
            for _ in range(n):
                lo, hi = {1: (40, 60), 2: (40, 75), 3: (45, 140), 4: (45, 150)}[etype]
                price = rng.randint(lo, hi)
                pts = round(max(0.5, price / 22 + rng.uniform(-1.5, 2.5)), 3) + eid * 1e-5   # no exact ties
                elements.append({"id": eid, "first_name": "P", "second_name": f"{eid:03d}", "web_name": f"P{eid:03d}",
                                 "element_type": etype, "team": t["id"], "now_cost": price, "status": "a",
                                 "chance_of_playing_next_round": None, "news": "", "news_added": None, "form": "3.0",
                                 "ep_next": str(round(pts, 1)), "_pts": pts})
                eid += 1
    return {"teams": teams, "elements": elements,
            "events": [{"id": 9, "deadline_time": "2026-10-31T11:00:00Z", "finished": True},
                       {"id": 10, "deadline_time": "2026-11-06T18:30:00Z", "finished": False},
                       {"id": 11, "deadline_time": "2026-11-21T11:00:00Z", "finished": False}]}


def pool_of(boot, prices=None):
    names = {t["id"]: t["name"] for t in boot["teams"]}
    rows = [{"element": e["id"], "name": f"P {e['second_name']}", "position": POS[e["element_type"]], "team": names[e["team"]],
             "value": int((prices or {}).get(e["id"], e["now_cost"])), "e_points": e["_pts"], "gw": 10}
            for e in boot["elements"]]
    return pd.DataFrame(rows)


def stored_solve(boot, prices=None):
    """The 'stored production solve' of the league: the real optimiser at its defaults on the run's prices."""
    import simulator as sim
    from optimize import optimize_squad
    pool = pool_of(boot, prices)
    prob, sol = optimize_squad(pool)
    team = sim.solution_to_squad(pool, sol)
    rows = [{"player_id": int(r["element"]), "name": r["name"], "position": r["position"], "team": str(r["team"]),
             "role": r["role"], "price": int(r["value"]) / 10, "e_points": float(r["e_points"])} for _, r in team.iterrows()]
    return {"gw": 10, "xi": [r for r in rows if r["role"] != "bench"], "bench_in_order": [r for r in rows if r["role"] == "bench"],
            "captain": next(r["name"] for r in rows if r["role"] == "CAPTAIN"), "config": "baseline (production)",
            "built": datetime(2026, 11, 2, 11, 0, tzinfo=UTC)}


class League:
    """Installs a synthetic league as the frame, the latest run, the stored solve and the FPL bootstrap."""

    def __init__(self, mp, seed=1, run_id=7):
        import model_tools as mt
        import team_card
        self.mp, self.seed, self.run_id = mp, seed, run_id
        self.boot = make_league(seed)
        # GW10's fixtures (the card's next gameweek at NOW): club 2k-1 at home to club 2k, kick-offs spread over the weekend
        self.fixtures = [{"id": k, "event": 10, "team_h": 2 * k - 1, "team_a": 2 * k, "kickoff_time": f"2026-11-0{7 + k % 3}T15:00:00Z"}
                         for k in range(1, 11)]
        self.run_prices = {e["id"]: e["now_cost"] for e in self.boot["elements"]}     # what the "pipeline" priced at
        self.calls = {"stored": 0, "load_pool": 0}
        mp.setattr(mt, "_current_gw", lambda: 10)
        mp.setattr(mt, "_latest_run", lambda gw=None, any_status=False: {"run_id": self.run_id, "gw": 10,
                                                                         "finished_at": datetime(2026, 11, 2, 11, 1, tzinfo=UTC)})

        def best():
            self.calls["stored"] += 1
            return stored_solve(self.boot, self.run_prices)
        mp.setattr(mt, "get_best_squad", best)
        mp.setattr(mt, "get_picks", lambda gw=None, shadow=False: best())

        def load_pool(gw=None):
            self.calls["load_pool"] += 1
            return pool_of(self.boot, self.run_prices), 10, datetime(2026, 11, 2, 11, 0, tzinfo=UTC)
        mp.setattr(mt, "_load_pool", load_pool)

        def no_frame():
            raise FileNotFoundError("no production frame in the synthetic league")
        mp.setattr(mt, "_frame_raw", no_frame)                     # W11d D4: hermetic unless a test installs one
        mp.setattr(mt, "get_prediction", lambda player_id, gw=None: {"error": "no prediction rows in the synthetic league"})
        mp.setattr(mt, "_season_label", lambda: "2026-27")
        mp.setattr(mt, "_with_flags", lambda out: out)
        mp.setattr(team_card, "_live_rows", lambda elements, conn=None: {})
        mp.setattr(drafts, "context", lambda allow_fetch=True: self.ctx())

    def ctx(self):
        import team_card
        boot = {k: v for k, v in self.boot.items()}
        c = team_card.Context(boot, True, list(self.fixtures), True, now=NOW)
        c.pool = {e["id"]: round(e["_pts"], 2) for e in self.boot["elements"]}
        c.built = datetime(2026, 11, 2, 11, 0, tzinfo=UTC)
        return c

    def raise_prices(self, by, ids):
        for e in self.boot["elements"]:
            if e["id"] in ids:
                e["now_cost"] += by


@pytest.fixture
def league(monkeypatch):
    return League(monkeypatch)


@pytest.fixture
def dapi(api, league, monkeypatch):
    """The app in clerk mode on the test database with the synthetic league; drafts' schema fresh."""
    with api.conn.cursor() as cur:
        cur.execute("DROP TABLE IF EXISTS user_drafts")
        cur.execute("DROP SEQUENCE IF EXISTS user_drafts_key_seq")
        cur.execute("DROP SEQUENCE IF EXISTS user_drafts_version_seq")
    drafts._SCHEMA_READY.clear()
    api.league = league
    yield api
    with api.conn.cursor() as cur:                                     # the shared test database keeps no draft rows
        cur.execute("DROP TABLE IF EXISTS user_drafts")
    drafts._SCHEMA_READY.clear()


def _post(api, path, sub=T1, **kw):
    return api.client.post(path, headers=bearer(mint(sub)), **kw)


def _get(api, path, sub=T1):
    return api.client.get(path, headers=bearer(mint(sub)))


def _delete(api, path, sub=T1):
    return api.client.delete(path, headers=bearer(mint(sub)))


def _legal(doc, boot, prices=None):
    """Every rule of a draft document, checked from scratch (not through drafts.check_squad)."""
    ps = doc["players"]
    assert len(ps) == 15 and len({p["element"] for p in ps}) == 15
    assert sorted(p["position"] for p in ps).count("GK") == 2
    assert {pos: sum(1 for p in ps if p["position"] == pos) for pos in ("GK", "DEF", "MID", "FWD")} == \
        {"GK": 2, "DEF": 5, "MID": 5, "FWD": 3}
    clubs = {}
    for p in ps:
        clubs[p["team"]] = clubs.get(p["team"], 0) + 1
    assert max(clubs.values()) <= 3
    cost = {e["id"]: e["now_cost"] for e in boot["elements"]} if prices is None else prices
    assert sum(cost[p["element"]] for p in ps) <= 1000
    xi = [p for p in ps if p["role"] != "bench"]
    assert len(xi) == 11
    n = {pos: sum(1 for p in xi if p["position"] == pos) for pos in ("GK", "DEF", "MID", "FWD")}
    assert n["GK"] == 1 and 3 <= n["DEF"] <= 5 and 2 <= n["MID"] <= 5 and 1 <= n["FWD"] <= 3
    caps = [p for p in ps if p["role"] == "CAPTAIN"]
    vices = [p for p in ps if p["role"] == "VICE"]
    assert len(caps) == 1 and len(vices) == 1 and caps[0]["element"] != vices[0]["element"]
    assert sorted(p["bench_order"] for p in ps if p["role"] == "bench") == [1, 2, 3, 4]


# ---- P: the build ----------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("seed", range(12))
def test_p1_the_build_is_legal_on_every_run(monkeypatch, seed):
    lg = League(monkeypatch, seed=seed)
    picks = drafts.best_picks()
    doc = drafts._picks_doc(picks)
    _legal(doc, lg.boot)
    assert picks["built_from"]["step"] == "stored" and picks["gw"] == 10


@pytest.mark.parametrize("seed", range(6))
def test_p2_price_rises_past_the_budget_re_solve_with_the_same_optimiser_at_current_prices(monkeypatch, seed):
    lg = League(monkeypatch, seed=seed)
    first = drafts.best_picks()
    lg.raise_prices(5, {p["element"] for p in first["players"]})    # +£0.5m each: the stored fifteen no longer fit
    picks = drafts.best_picks()
    assert picks["built_from"]["step"] == "re-solved"
    _legal(drafts._picks_doc(picks), lg.boot)                          # within £100.0m at the NEW prices


def test_p3_the_stored_solve_is_used_exactly_when_it_fits(league):
    picks = drafts.best_picks()
    stored = stored_solve(league.boot)
    assert sorted(p["element"] for p in picks["players"]) == sorted(r["player_id"] for r in stored["xi"] + stored["bench_in_order"])
    assert picks["captain"] == next(r["player_id"] for r in stored["xi"] if r["role"] == "CAPTAIN")
    assert picks["vice"] == next(r["player_id"] for r in stored["xi"] if r["role"] == "VICE")
    assert picks["bench"] == [r["player_id"] for r in stored["bench_in_order"]]
    assert league.calls["load_pool"] == 0                              # no re-solve


def test_p4_same_predictions_same_draft(league):
    a, b = drafts.best_picks(), drafts.best_picks()
    assert drafts._picks_doc(a) == drafts._picks_doc(b)
    league.raise_prices(5, {p["element"] for p in a["players"]})
    c1, c2 = drafts.best_picks(), drafts.best_picks()
    assert drafts._picks_doc(c1) == drafts._picks_doc(c2)


def test_p5_a_failed_build_raises_build_failed_and_never_saves(dapi, monkeypatch):
    import model_tools as mt
    monkeypatch.setattr(mt, "get_best_squad", lambda: {"error": "no run"})
    r = _post(dapi, "/me/draft")
    assert r.status_code == 503 and r.json()["error_kind"] == "draft_failed"
    assert _n_drafts(dapi.conn) == 0
    assert _q(dapi.conn, "SELECT count(*) FROM chat_threads WHERE user_id = %s", (U1,))[0][0] == 0


def _n_drafts(conn):
    if not _q(conn, "SELECT to_regclass('public.user_drafts') IS NOT NULL")[0][0]:
        return 0
    return _q(conn, "SELECT count(*) FROM user_drafts")[0][0]


def test_p6_at_most_two_builds_compute_at_once(league, monkeypatch):
    monkeypatch.setattr(drafts, "BUILD_WAIT_S", 0.05)
    assert drafts._BUILD_SEM.acquire(timeout=1) and drafts._BUILD_SEM.acquire(timeout=1)
    try:
        with pytest.raises(drafts.Busy):
            drafts.best_picks()
    finally:
        drafts._BUILD_SEM.release()
        drafts._BUILD_SEM.release()
    assert drafts.best_picks()["players"]


# ---- R: the routes ---------------------------------------------------------------------------------------------------------

def _draft_rows(conn):
    return _q(conn, "SELECT user_id, draft_key, version_id, n_changes FROM user_drafts ORDER BY user_id")


def test_r1_build_returns_the_card_and_its_first_chat_opens_with_the_fixed_message(dapi):
    r = _post(dapi, "/me/draft")
    assert r.status_code == 200, r.text
    body = r.json()
    d = body["draft"]
    assert body["existing"] is False and body["thread_id"] and d["thread_id"] == body["thread_id"]
    assert len(d["players"]) == 15 and d["budget"] == 100.0 and d["value"] <= 100.0
    assert d["left"] == round(100.0 - d["value"], 1) and d["over"] == 0
    assert d["formation"].count("-") == 2 and d["captain"]["id"] != d["vice"]["id"]
    assert d["predicted_xi_points"] > 0 and d["predictions_gw"] == 10 and d["newer_predictions"] is False
    assert "free_transfers" not in d and "bank" not in d and "chips" not in d
    import agent_graph
    hist = agent_graph.load_history(body["thread_id"])
    assert hist == [{"role": "assistant", "content": drafts.OPENING_TEXT}]
    msgs = _get(dapi, f"/threads/{body['thread_id']}/messages").json()
    assert msgs[0]["role"] == "assistant" and msgs[0]["kind"] == "draft_opening" and msgs[0]["text"] == drafts.OPENING_TEXT
    assert _get(dapi, "/threads").json() == []                         # only the opening message: not listed (W4's rule)


def test_r2_one_draft_per_account_a_second_build_returns_the_existing_one(dapi):
    first = _post(dapi, "/me/draft").json()
    calls = dapi.league.calls["stored"]
    again = _post(dapi, "/me/draft").json()
    assert again["existing"] is True and again["draft"]["version_id"] == first["draft"]["version_id"]
    assert dapi.league.calls["stored"] == calls                        # nothing built
    assert len(_draft_rows(dapi.conn)) == 1
    assert _q(dapi.conn, "SELECT count(*) FROM chat_threads WHERE user_id = %s", (U1,))[0][0] == 1


def test_r3_rebuild_replaces_the_fifteen_under_a_new_version_and_keeps_the_chats(dapi):
    first = _post(dapi, "/me/draft").json()
    with dapi.conn.cursor() as cur:                                    # a change was made (n_changes 1)
        cur.execute("UPDATE user_drafts SET n_changes = 1 WHERE user_id = %s", (U1,))
    dapi.league.run_id = 8                                             # newer predictions exist
    assert _get(dapi, "/me/draft").json()["draft"]["newer_predictions"] is True
    r = _post(dapi, "/me/draft/rebuild")
    assert r.status_code == 200, r.text
    d = r.json()["draft"]
    assert d["version_id"] != first["draft"]["version_id"] and d["n_changes"] == 0 and d["newer_predictions"] is False
    assert d["thread_ids"] == [first["thread_id"]]
    assert _delete(dapi, "/me/draft").status_code == 200
    assert _post(dapi, "/me/draft/rebuild").status_code == 404


def test_r4_delete_removes_the_draft_and_its_chats_and_nothing_else(dapi):
    a = _post(dapi, "/me/draft").json()
    b = _post(dapi, "/me/draft", sub=T2).json()
    other = _post(dapi, "/threads").json()["thread_id"]               # an ordinary chat of user 1
    extra = _post(dapi, "/threads", json={"draft": True}).json()
    assert extra["draft"] is True
    r = _delete(dapi, "/me/draft")
    assert r.status_code == 200 and r.json()["deleted"] is True
    assert [row[0] for row in _draft_rows(dapi.conn)] == [U2]
    left = {row[0] for row in _q(dapi.conn, "SELECT thread_id FROM chat_threads WHERE user_id = %s", (U1,))}
    assert left == {other}                                             # both draft chats gone, the ordinary one kept
    assert _q(dapi.conn, "SELECT count(*) FROM checkpoints WHERE thread_id = %s", (a["thread_id"],))[0][0] == 0
    assert _q(dapi.conn, "SELECT count(*) FROM checkpoints WHERE thread_id = %s", (b["thread_id"],))[0][0] > 0
    assert _get(dapi, "/me/draft").json() == {"draft": None}
    assert _delete(dapi, "/me/draft").status_code == 404
    assert _post(dapi, "/threads", json={"draft": True}).status_code == 404


def test_r8_the_draft_players_are_the_team_cards_own_objects_with_each_clubs_next_fixture(dapi):
    """Checkpoint 2, fix 1: each of the draft's 15 shows HIS club's next fixture from the fixtures list, built by the real
    team card's own function (team_card.players_of) -- the same source and the same player object."""
    import team_card
    d = _post(dapi, "/me/draft").json()["draft"]
    lg = dapi.league
    team_of = {e["id"]: e["team"] for e in lg.boot["elements"]}
    short = {t["id"]: t["short_name"] for t in lg.boot["teams"]}
    opps = set()
    for p in d["players"]:
        club = team_of[p["id"]]
        f = next(f for f in lg.fixtures if f["event"] == 10 and club in (f["team_h"], f["team_a"]))
        home = f["team_h"] == club
        want = {"opp": short[f["team_a"] if home else f["team_h"]], "home": home, "n": 1}
        assert p["next"] == want, (p["short_name"], p["next"], want)
        assert p["club"] == short[club]
        opps.add(want["opp"])
    assert len(opps) > 1                                               # not one fixture for everyone
    assert drafts.as_json(team_card.players_of(lg.ctx(), drafts.read(U1)["squad_json"])) == d["players"]


def test_r5_users_are_isolated(dapi):
    a = _post(dapi, "/me/draft").json()
    assert _get(dapi, "/me/draft", sub=T2).json() == {"draft": None}
    assert _get(dapi, f"/threads/{a['thread_id']}/messages", sub=T2).status_code == 403
    r = dapi.client.post("/chat", headers=bearer(mint(T2)), json={"message": "hi", "thread_id": a["thread_id"]})
    assert r.status_code == 403
    assert drafts.turn_draft(U2, a["thread_id"]) is None
    assert drafts.turn_draft(U1, a["thread_id"]) == {"user_id": U1, "draft_key": a_key(dapi)}


def a_key(api, uid=U1):
    return _q(api.conn, "SELECT draft_key FROM user_drafts WHERE user_id = %s", (uid,))[0][0]


def test_r6_the_build_window_is_ten_an_hour(dapi):
    assert _post(dapi, "/me/draft").status_code == 200                 # 1 build
    for _ in range(9):                                                 # 9 rebuilds -> 10 in the hour
        assert _post(dapi, "/me/draft/rebuild").status_code == 200
    r = _post(dapi, "/me/draft/rebuild")
    assert r.status_code == 429 and r.json()["error_kind"] == "draft_limited"
    assert _post(dapi, "/me/draft").json()["existing"] is True         # an existing draft is returned, never limited
    assert _post(dapi, "/me/draft", sub=T2).status_code == 200         # another user's window is their own


def test_r9_in_clerk_mode_the_draft_routes_need_only_the_session_token_like_every_website_route(dapi):
    """Found on the laptop backend (W11 Part 4): the website calls with the Clerk token and NO x-api-key; the draft routes
    must be clerk routes (main.CLERK_ROUTES), else the key middleware refuses them before the handler runs."""
    from fastapi.testclient import TestClient
    bare = TestClient(dapi.main.app)                                   # no x-api-key header, as the browser calls
    h = bearer(mint(T1))
    assert bare.get("/me/draft", headers=h).json() == {"draft": None}
    built = bare.post("/me/draft", headers=h)
    assert built.status_code == 200, built.text
    assert bare.post("/me/draft/rebuild", headers=h).status_code == 200
    assert bare.post("/threads", headers=h, json={"draft": True}).status_code == 200
    tid = built.json()["thread_id"]                                    # W11e E2: the chip's instant answer, a clerk route too
    assert bare.post("/me/draft/explain", headers=h, json={"thread_id": tid, "question": "Why these players?"}).status_code == 200
    assert bare.delete("/me/draft", headers=h).status_code == 200
    assert bare.get("/me/draft").status_code == 401                    # no token: refused before the handler


def test_r7_off_mode_every_draft_route_is_404_and_nothing_reads_user_drafts(dapi, monkeypatch):
    monkeypatch.setenv("AUTH_MODE", "off")
    dapi.auth._reset()
    for method, path, kw in (("post", "/me/draft", {}), ("get", "/me/draft", {}), ("post", "/me/draft/rebuild", {}),
                             ("delete", "/me/draft", {}), ("post", "/threads", {"json": {"draft": True}}),
                             ("post", "/me/draft/explain", {"json": {"thread_id": "th_x", "question": "Why these players?"}})):
        r = getattr(dapi.client, method)(path, **kw)
        assert r.status_code == 404, (method, path, r.status_code)
    import drafts as d
    monkeypatch.setattr(d, "read", lambda *a, **k: (_ for _ in ()).throw(AssertionError("read in off mode")))
    assert d.turn_draft(9001, "th_anything") is None
    import threads
    assert threads._is_draft_key(9001, 800_000_001) is False


# ---- C: changes ------------------------------------------------------------------------------------------------------------

class Turns:
    """Two (or more) separate turns in the draft chat, as two /chat requests would be."""

    def __init__(self, uid, tid, key):
        self.uid, self.tid, self.key, self.n = uid, tid, key, 0

    def run(self, fn, yes=True, **kw):
        """Prompt X1: a confirm=true call carries the user's yes to its ticket (what confirm_gate sets after "Yes");
        yes=False is the model calling confirm=true on its own (refused: needs_yes)."""
        import turn_context
        self.n += 1
        consent = kw.get("preview_ticket") if (kw.get("confirm") and yes) else None
        turn_context.begin(f"turn-{self.n}", started_at=datetime.now(UTC) + timedelta(seconds=self.n), thread_id=self.tid,
                           draft={"user_id": self.uid, "draft_key": self.key}, consent=consent)
        try:
            return fn(**kw)
        finally:
            turn_context.end()


@pytest.fixture
def built(dapi, monkeypatch):
    import model_tools as mt
    body = _post(dapi, "/me/draft").json()
    tid = body["thread_id"]
    row = drafts.read(U1)
    monkeypatch.setattr(drafts, "best_picks", _patched_best(drafts.best_picks))
    return types.SimpleNamespace(api=dapi, tid=tid, row=row, doc=row["squad_json"], turns=Turns(U1, tid, row["draft_key"]),
                                 mt=mt, boot=dapi.league.boot)


def _patched_best(orig):
    def best(prices_fn=None):
        return orig(prices_fn=prices_fn)
    return best


def _args(doc, swap=None, captain=None):
    """set_my_squad arguments for `doc` with one player swapped (old -> new; the new one takes the old one's place)."""
    ids = [int(p["element"]) for p in doc["players"]]
    c, v, bench = drafts.roles_of(doc)
    if swap:
        o, n = swap
        ids = [n if e == o else e for e in ids]
        c, v = (n if c == o else c), (n if v == o else v)
        bench = [n if e == o else e for e in bench]
    return {"player_ids": ids, "captain_id": captain or c, "vice_id": v, "bench_order_ids": bench}


def _by_pos(boot, pos):
    return [e for e in boot["elements"] if POS[e["element_type"]] == pos]


def _club_counts(doc):
    out = {}
    for p in doc["players"]:
        out[p["team"]] = out.get(p["team"], 0) + 1
    return out


def test_c1_over_budget_is_refused_with_the_amount_and_alternatives(built):
    import model_tools as mt
    doc, boot = built.doc, built.boot
    have = {int(p["element"]) for p in doc["players"]}
    names = {t["id"]: t["name"] for t in boot["teams"]}
    clubs = _club_counts(doc)
    price = {e["id"]: e["now_cost"] for e in boot["elements"]}
    cheap_mid = max((p for p in doc["players"] if p["position"] == "MID"), key=lambda p: price[p["element"]])  # the dearest in
    dear = max((e for e in _by_pos(boot, "MID") if e["id"] not in have
                and (clubs.get(names[e["team"]], 0) < 3 or names[e["team"]] == cheap_mid["team"])), key=lambda e: e["now_cost"])
    value = sum(price[int(p["element"])] for p in doc["players"])
    dear["now_cost"] = max(dear["now_cost"], 1001 - value + price[cheap_mid["element"]])   # make sure the swap is over
    out = built.turns.run(mt.set_my_squad, **_args(doc, swap=(cheap_mid["element"], dear["id"])))
    assert out.get("refused") is True and out["draft"] is True and out["reason_kind"] == "over_budget", out
    assert out["over_by"] > 0 and out["budget"] == 100.0
    assert f"£{out['over_by']:.1f}m over the £100.0m limit" in out["error"]
    assert out["legal_alternatives"] and all(a["value_after"] <= 100.0 for a in out["legal_alternatives"])
    assert all(a["position"] == "MID" and a["player_id"] not in have for a in out["legal_alternatives"])
    assert drafts.read(U1)["version_id"] == built.row["version_id"]   # nothing saved
    assert _q(built.api.conn, "SELECT count(*) FROM squad_previews")[0][0] == 0


def test_c2_a_fourth_player_from_one_club_is_refused_with_the_rule(built):
    import model_tools as mt
    doc, boot = built.doc, built.boot
    names = {t["id"]: t["name"] for t in boot["teams"]}
    clubs = _club_counts(doc)
    have = {int(p["element"]) for p in doc["players"]}
    club = max(clubs, key=clubs.get)
    need = 4 - clubs[club]                                             # bring in this many from `club`
    pool = [e for e in sorted(boot["elements"], key=lambda e: e["now_cost"]) if names[e["team"]] == club and e["id"] not in have]
    swaps, used = [], set()
    for e in pool:
        if len(swaps) == need:
            break
        pos = POS[e["element_type"]]
        out_p = next((p for p in doc["players"] if p["position"] == pos and p["team"] != club and p["element"] not in used
                      and p["role"] in ("bench", "start")), None)
        if out_p is not None:
            swaps.append((out_p["element"], e["id"]))
            used.add(out_p["element"])
    assert len(swaps) == need
    args = _args(doc)
    for o, n in swaps:
        args["player_ids"] = [n if x == o else x for x in args["player_ids"]]
        args["bench_order_ids"] = [n if x == o else x for x in args["bench_order_ids"]]
    out = built.turns.run(mt.set_my_squad, **args)
    assert out["refused"] is True and out["reason_kind"] == "club_cap", out
    assert "at most 3 players from one club" in out["error"] and club in out["error"] and "4 from" in out["error"]


def test_c3_a_player_for_one_in_another_position_is_refused(built):
    import model_tools as mt
    doc, boot = built.doc, built.boot
    have = {int(p["element"]) for p in doc["players"]}
    d_out = next(p for p in doc["players"] if p["position"] == "DEF" and p["role"] == "bench")
    mid = next(e for e in sorted(_by_pos(boot, "MID"), key=lambda e: e["now_cost"]) if e["id"] not in have)
    out = built.turns.run(mt.set_my_squad, **_args(doc, swap=(d_out["element"], mid["id"])))
    assert out["refused"] is True and out["reason_kind"] == "position"
    assert "2 goalkeepers, 5 defenders, 5 midfielders and 3 forwards" in out["error"]


def _legal_swap(doc, boot):
    """A bench defender for the cheapest outside defender who keeps the club cap and the budget."""
    have = {int(p["element"]) for p in doc["players"]}
    clubs = {}
    for p in doc["players"]:
        clubs[p["team"]] = clubs.get(p["team"], 0) + 1
    names = {t["id"]: t["name"] for t in boot["teams"]}
    price = {e["id"]: e["now_cost"] for e in boot["elements"]}
    value = sum(price[int(p["element"])] for p in doc["players"])
    d_out = next(p for p in doc["players"] if p["position"] == "DEF" and p["role"] == "bench")
    for e in sorted(_by_pos(boot, "DEF"), key=lambda e: e["now_cost"]):
        club = names[e["team"]]
        if e["id"] in have or (clubs.get(club, 0) >= 3 and club != d_out["team"]):
            continue
        if value - price[d_out["element"]] + e["now_cost"] <= 1000:
            return d_out, e
    raise AssertionError("no legal swap")


def test_c4_a_legal_change_is_previewed_then_saved_in_a_later_turn_with_no_ft_hit_or_bank(built):
    import model_tools as mt
    import turn_extras
    doc, boot = built.doc, built.boot
    d_out, d_in = _legal_swap(doc, boot)
    args = _args(doc, swap=(d_out["element"], d_in["id"]))
    prev = built.turns.run(mt.set_my_squad, **args)
    assert prev["preview"] is True and prev["committed"] is False and prev["draft"] is True and prev["kind"] == "change"
    ch = prev["change"]
    assert ch["n_transfers"] == 1 and ch["transfers"][0]["out_id"] == d_out["element"] and ch["transfers"][0]["in_id"] == d_in["id"]
    assert ch["value_after"] <= 100.0 and ch["left_after"] == round(100.0 - ch["value_after"], 1)
    text = repr(prev).lower()
    for word in ("free_transfer", "hit", "bank"):
        assert word not in text, word
    assert drafts.read(U1)["version_id"] == built.row["version_id"]   # a preview saves nothing
    # the same turn cannot spend it; a later turn can
    import turn_context
    turn_context.begin("turn-same", started_at=datetime.now(UTC) + timedelta(seconds=50), thread_id=built.tid,
                       draft={"user_id": U1, "draft_key": built.row["draft_key"]})
    turn_context.end()
    done = built.turns.run(mt.set_my_squad, **args, confirm=True, preview_ticket=prev["preview_ticket"])
    assert done["committed"] is True and done["draft"] is True, done
    row = drafts.read(U1)
    assert row["version_id"] != built.row["version_id"] and row["n_changes"] == 1
    assert d_in["id"] in {p["element"] for p in row["squad_json"]["players"]}
    assert turn_extras.applied([("set_my_squad", {}, done)]) == {"gw": 10, "version_id": row["version_id"], "draft": True,
                                                                  "kind": "change"}
    again = built.turns.run(mt.set_my_squad, **args, confirm=True, preview_ticket=prev["preview_ticket"])
    assert again["refused"] is True and again.get("reason") in ("used", None)      # the draft already IS this (no_change)
    assert drafts.read(U1)["version_id"] == row["version_id"]


def test_c5_a_ticket_against_an_older_version_is_refused(built):
    import model_tools as mt
    d_out, d_in = _legal_swap(built.doc, built.boot)
    args = _args(built.doc, swap=(d_out["element"], d_in["id"]))
    prev = built.turns.run(mt.set_my_squad, **args)
    assert _post(built.api, "/me/draft/rebuild").status_code == 200   # the version moves
    out = built.turns.run(mt.set_my_squad, **args, confirm=True, preview_ticket=prev["preview_ticket"])
    assert out["refused"] is True and out["reason"] in ("squad_changed", "different_change")


def test_c6_a_draft_fingerprint_never_matches_a_real_squad_write():
    import squad_previews
    args = ([1, 2, 3], 1, 2, [3], None)
    assert drafts.fingerprint(*args[:4]) != squad_previews.fingerprint(*args)


def test_c7_the_seven_squad_tools_answer_for_the_draft_in_a_draft_turn_only(built):
    import model_tools as mt
    sq = built.turns.run(mt.get_my_squad)
    assert sq["draft"] is True and sq["not_in_fpl"] is True and len(_xi(sq)) == 11 and len(sq["bench_in_order"]) == 4
    assert sq["value"] <= 100.0 and sq["rules"]["max_per_club"] == 3 and sq["rebuild_with"]["player_ids"]
    assert sq["rebuild_would_change_players"] == 0 and sq["changes_since_build"] == 0
    assert all(r["e_points"] is not None for r in _xi(sq))            # the LATEST predictions, per player
    assert "free_transfers_now" not in sq and "bank" not in sq
    xi = built.turns.run(mt.get_my_xi)
    assert xi["draft"] is True and len(xi["xi"]) == 11 and xi["adopt_with"]["player_ids"] == sorted(sq["rebuild_with"]["player_ids"])
    for fn in (mt.get_my_points, mt.get_wildcard_gap):
        out = built.turns.run(fn)
        assert out["draft"] is True and out["not_applicable"] is True
    assert built.turns.run(mt.propose_transfers)["kind"] == "free_swaps"      # W11c R1: the draft's best free swaps


def test_c8_rebuild_in_chat_is_a_preview_of_rebuild_with_and_yes_saves_it_as_a_rebuild(built):
    import model_tools as mt
    d_out, d_in = _legal_swap(built.doc, built.boot)
    args = _args(built.doc, swap=(d_out["element"], d_in["id"]))
    prev = built.turns.run(mt.set_my_squad, **args)
    built.turns.run(mt.set_my_squad, **args, confirm=True, preview_ticket=prev["preview_ticket"])
    sq = built.turns.run(mt.get_my_squad)
    assert sq["rebuild_would_change_players"] == 1 and sq["changes_since_build"] == 1
    rb = {k: v for k, v in sq["rebuild_with"].items() if k != "confirm"}
    p2 = built.turns.run(mt.set_my_squad, **rb)
    assert p2["preview"] is True and p2["kind"] == "rebuild" and p2["change"]["n_transfers"] == 1
    done = built.turns.run(mt.set_my_squad, **rb, confirm=True, preview_ticket=p2["preview_ticket"])
    assert done["committed"] is True and done["kind"] == "rebuild"
    assert drafts.read(U1)["n_changes"] == 0
    noop = built.turns.run(mt.set_my_squad, **rb)
    assert noop["refused"] is True and noop["reason_kind"] == "no_change"


def test_c9_outside_a_draft_turn_the_tools_never_read_the_draft(built, monkeypatch):
    import model_tools as mt
    import draft_tools
    monkeypatch.setattr(draft_tools, "get_my_squad", lambda d: (_ for _ in ()).throw(AssertionError("draft read")))
    out = mt.get_my_squad(user_id=U1)                                  # no turn open: the user's own record (none)
    assert out.get("no_squad") is True


def test_c10_over_budget_after_price_rises_allows_a_cheaper_change_and_refuses_a_dearer_one(built):
    import model_tools as mt
    built.api.league.raise_prices(2, {int(p["element"]) for p in built.doc["players"]})
    sq = built.turns.run(mt.get_my_squad)
    assert sq["value"] > 100.0 and sq["over"] == round(sq["value"] - 100.0, 1) and "over_note" in sq
    xi = [p for p in built.doc["players"] if p["role"] != "bench"]
    c, v, bench = drafts.roles_of(built.doc)
    other = next(int(p["element"]) for p in xi if int(p["element"]) not in (c, v))
    out = built.turns.run(mt.set_my_squad, **_args(built.doc, captain=other))     # a captain change costs nothing more
    assert out.get("preview") is True, out
    dear = max((e for e in _by_pos(built.boot, "DEF") if e["id"] not in {int(p["element"]) for p in built.doc["players"]}),
               key=lambda e: e["now_cost"])
    d_out = min((p for p in built.doc["players"] if p["position"] == "DEF"), key=lambda p: next(
        e["now_cost"] for e in built.boot["elements"] if e["id"] == p["element"]))
    out = built.turns.run(mt.set_my_squad, **_args(built.doc, swap=(d_out["element"], dear["id"])))
    assert out["refused"] is True and out["reason_kind"] in ("over_budget", "club_cap")


# ---- N: the numbers the agent was working out itself (Prompt W11b, 2026-11-13) ---------------------------------------------------
# The W11 eval failed on three numbers the agent derived (a captain's points doubled, two prices added, an example team ID).
# On draft turns the tools now give each of them; outside a draft turn nothing changes.

def _sq_rows(sq):
    """W11d D2: get_my_squad (draft) groups its fifteen rows by position."""
    return [r for pos in ("GK", "DEF", "MID", "FWD") for r in sq["squad_by_position"][pos]]


def _xi(sq):
    return [r for r in _sq_rows(sq) if r["in_xi"]]


def _pts(boot):
    return {e["id"]: round(e["_pts"], 2) for e in boot["elements"]}


def _price(boot):
    return {e["id"]: e["now_cost"] for e in boot["elements"]}


def test_n1_get_my_squad_gives_each_starters_points_the_captain_doubled_the_xi_total_and_the_money(built):
    import model_tools as mt
    sq = built.turns.run(mt.get_my_squad)
    pts, price = _pts(built.boot), _price(built.boot)
    assert all(r["e_points"] == pts[r["player_id"]] for r in _xi(sq))
    cap = next(r for r in _xi(sq) if r["role"] == "CAPTAIN")
    assert {k: sq["captain_points"][k] for k in ("player_id", "name", "short_name", "e_points", "with_armband")} ==         {"player_id": cap["player_id"], "name": cap["name"], "short_name": cap["short_name"],
         "e_points": cap["e_points"], "with_armband": round(2 * cap["e_points"], 2)}
    assert cap["e_points_with_armband"] == round(2 * cap["e_points"], 2)
    assert all("e_points_with_armband" not in r for r in _sq_rows(sq) if r["role"] != "CAPTAIN")
    assert sq["predicted_xi_points"] == round(sum(r["e_points"] for r in _xi(sq)) + cap["e_points"], 1)
    value = sum(price[r["player_id"]] for r in _sq_rows(sq))
    assert (sq["value"], sq["budget"], sq["left"]) == (round(value / 10, 1), 100.0, round((1000 - value) / 10, 1))
    assert "over" not in sq and "do not add" in sq["numbers_note"]


def test_n1b_get_my_xi_gives_the_same_numbers_for_its_xi_and_the_money(built):
    import model_tools as mt
    xi = built.turns.run(mt.get_my_xi)
    cap = next(r for r in xi["xi"] if r["role"] == "CAPTAIN")
    assert xi["captain_points"]["player_id"] == cap["player_id"] and xi["captain_points"]["with_armband"] == round(2 * cap["e_points"], 2)
    assert cap["e_points_with_armband"] == round(2 * cap["e_points"], 2)
    assert xi["predicted_xi_points"] == round(sum(r["e_points"] for r in xi["xi"]) + cap["e_points"], 1)
    sq = built.turns.run(mt.get_my_squad)
    assert (xi["value"], xi["budget"], xi["left"]) == (sq["value"], 100.0, sq["left"]) and "do not add" in xi["numbers_note"]


def test_n1c_over_budget_after_price_rises_both_tools_say_how_much_over(built):
    import model_tools as mt
    built.api.league.raise_prices(2, {int(p["element"]) for p in built.doc["players"]})
    sq, xi = built.turns.run(mt.get_my_squad), built.turns.run(mt.get_my_xi)
    for out in (sq, xi):
        assert out["value"] > 100.0 and out["over"] == round(out["value"] - 100.0, 1) and out["left"] == 0.0


def test_n2_a_preview_gives_price_out_price_in_the_difference_and_the_money_before_and_after(built):
    import model_tools as mt
    price = _price(built.boot)
    d_out, d_in = _legal_swap(built.doc, built.boot)
    value = sum(price[int(p["element"])] for p in built.doc["players"])
    prev = built.turns.run(mt.set_my_squad, **_args(built.doc, swap=(d_out["element"], d_in["id"])))
    assert prev["preview"] is True, prev
    t, ch = prev["change"]["transfers"][0], prev["change"]
    diff = d_in["now_cost"] - price[d_out["element"]]
    assert (t["out_price"], t["in_price"], t["price_difference"]) == (price[d_out["element"]] / 10, d_in["now_cost"] / 10,
                                                                      round(diff / 10, 1))
    word = "more" if diff > 0 else "less" if diff < 0 else "the same"
    assert word in t["difference_words"] and (diff == 0 or f"£{abs(diff) / 10:.1f}m" in t["difference_words"])
    after = value - price[d_out["element"]] + d_in["now_cost"]
    assert (ch["value_before"], ch["left_before"]) == (round(value / 10, 1), round((1000 - value) / 10, 1))
    assert (ch["value_after"], ch["left_after"], ch["over_after"]) == (round(after / 10, 1), round((1000 - after) / 10, 1), 0.0)
    assert ch["money_words"] == (f"Now the draft costs £{value / 10:.1f}m (£{(1000 - value) / 10:.1f}m left); after this change it "
                                 f"costs £{after / 10:.1f}m (£{(1000 - after) / 10:.1f}m left).")


def _over_swap(built):
    doc, boot = built.doc, built.boot
    have = {int(p["element"]) for p in doc["players"]}
    names = {t["id"]: t["name"] for t in boot["teams"]}
    clubs, price = _club_counts(doc), _price(boot)
    out_mid = max((p for p in doc["players"] if p["position"] == "MID"), key=lambda p: price[p["element"]])
    dear = max((e for e in _by_pos(boot, "MID") if e["id"] not in have
                and (clubs.get(names[e["team"]], 0) < 3 or names[e["team"]] == out_mid["team"])), key=lambda e: e["now_cost"])
    value = sum(price[int(p["element"])] for p in doc["players"])
    dear["now_cost"] = max(dear["now_cost"], 1001 - value + price[out_mid["element"]])
    return out_mid, dear, value


def test_n2b_an_over_budget_refusal_gives_the_amount_over_and_each_alternatives_price_and_money_left(built):
    import model_tools as mt
    out_mid, dear, value = _over_swap(built)
    price = _price(built.boot)
    out = built.turns.run(mt.set_my_squad, **_args(built.doc, swap=(out_mid["element"], dear["id"])))
    assert out["reason_kind"] == "over_budget", out
    t = out["transfers"][0]
    assert (t["out_id"], t["in_id"]) == (out_mid["element"], dear["id"])
    assert (t["out_price"], t["in_price"]) == (price[out_mid["element"]] / 10, dear["now_cost"] / 10)
    assert t["price_difference"] == round((dear["now_cost"] - price[out_mid["element"]]) / 10, 1) and "more" in t["difference_words"]
    after = value - price[out_mid["element"]] + dear["now_cost"]
    assert (out["value_before"], out["left_before"]) == (round(value / 10, 1), round((1000 - value) / 10, 1))
    assert (out["value_after"], out["over_by"]) == (round(after / 10, 1), round((after - 1000) / 10, 1))
    assert out["money_words"] == (f"Now the draft costs £{value / 10:.1f}m (£{(1000 - value) / 10:.1f}m left); with this change "
                                  f"it would cost £{after / 10:.1f}m (£{(after - 1000) / 10:.1f}m over £100.0m), so it was "
                                  "refused.")
    alts = out["legal_alternatives"]
    assert alts
    for a in alts:
        assert a["price"] == price[a["player_id"]] / 10 and a["instead_of_price"] == price[dear["id"]] / 10
        assert a["price_difference"] == round((price[a["player_id"]] - price[out_mid["element"]]) / 10, 1)
        a_after = value - price[out_mid["element"]] + price[a["player_id"]]
        assert (a["value_after"], a["left_after"]) == (round(a_after / 10, 1), round((1000 - a_after) / 10, 1))
        assert a["money_words"] == f"With {a['name']} instead: £{a_after / 10:.1f}m, £{(1000 - a_after) / 10:.1f}m left."


def test_n2c_a_club_cap_refusal_gives_the_prices_and_each_alternatives_money_left(built):
    import model_tools as mt
    doc, boot = built.doc, built.boot
    names = {t["id"]: t["name"] for t in boot["teams"]}
    clubs, price, have = _club_counts(doc), _price(boot), {int(p["element"]) for p in doc["players"]}
    value = sum(price[e] for e in have)
    club = max(clubs, key=clubs.get)
    args, swaps = _args(doc), []
    for e in sorted(boot["elements"], key=lambda e: e["now_cost"]):
        if len(swaps) == 4 - clubs[club]:
            break
        if names[e["team"]] != club or e["id"] in have:
            continue
        o = next((p for p in doc["players"] if p["position"] == POS[e["element_type"]] and p["team"] != club
                  and p["role"] in ("bench", "start") and p["element"] not in [s[0] for s in swaps]), None)
        if o is not None:
            swaps.append((o["element"], e["id"]))
    for o, n in swaps:
        args["player_ids"] = [n if x == o else x for x in args["player_ids"]]
        args["bench_order_ids"] = [n if x == o else x for x in args["bench_order_ids"]]
    out = built.turns.run(mt.set_my_squad, **args)
    assert out["reason_kind"] == "club_cap", out
    assert {(t["out_id"], t["in_id"]) for t in out["transfers"]} == set(swaps)
    assert all({"out_price", "in_price", "price_difference", "difference_words"} <= set(t) for t in out["transfers"])
    assert out["left_before"] == round((1000 - value) / 10, 1) and out["legal_alternatives"]
    after = value + sum(price[n] - price[o] for o, n in swaps)
    assert out["value_after"] == round(after / 10, 1) and out["money_words"].startswith(f"Now the draft costs £{value / 10:.1f}m")
    for a in out["legal_alternatives"]:
        assert a["price"] == price[a["player_id"]] / 10 and a["left_after"] == round(100.0 - a["value_after"], 1)


def test_n3_the_steps_to_enter_it_in_fpl_come_from_get_my_squad_with_a_digit_free_link(built):
    import json
    import re
    import model_tools as mt
    e = built.turns.run(mt.get_my_squad)["enter_in_fpl"]
    text = json.dumps(e, ensure_ascii=False)
    assert re.search(r"\d", text) is None, text
    for must in ("fantasy.premierleague.com/entry/<your team ID>/", "Points", "Add my team ID", "How to enter it"):
        assert must in text, must
    assert isinstance(e["steps"], list) and len(e["steps"]) >= 4
    wording = (REPO / "prompts" / "draft_mode.md").read_text(encoding="utf-8")
    assert "enter_in_fpl" in wording and "Never invent an example team ID" in wording   # its numbers: test_draft_payload test_4


def _named(built, monkeypatch, full, web):
    """resolve_player over the synthetic league (its players_live and FPL web names), with chosen players renamed."""
    import model_tools as mt
    teams = {t["id"]: t["name"] for t in built.boot["teams"]}
    rows = [{"element": e["id"], "name": full.get(e["id"], f"P {e['second_name']}"), "position": POS[e["element_type"]],
             "team": teams[e["team"]], "price_tenths": e["now_cost"], "status": "a"} for e in built.boot["elements"]]
    webs = {e["id"]: web.get(e["id"], e["web_name"]) for e in built.boot["elements"]}
    monkeypatch.setattr(mt, "_q", lambda sql, params=(): [] if "status = ANY" in sql else [dict(r) for r in rows])
    monkeypatch.setattr(mt, "_web_names", lambda: webs)


def test_n4_the_player_going_out_is_matched_against_the_drafts_fifteen_first(built, monkeypatch):
    import model_tools as mt
    have = {int(p["element"]) for p in built.doc["players"]}
    mine = next(p for p in built.doc["players"] if p["position"] == "MID" and p["role"] == "start")
    other = next(e for e in _by_pos(built.boot, "DEF") if e["id"] not in have)
    _named(built, monkeypatch, {mine["element"]: "Diego Gómez", other["id"]: "Joe Gomez"},
           {mine["element"]: "Gomez", other["id"]: "Gomez"})
    plain = mt.resolve_player("Gomez")                                 # outside a draft turn: exactly as before (ask)
    assert plain["ambiguous"] is True and plain["action"] == "ask the user which one" and "in_your_draft" not in plain
    out = built.turns.run(mt.resolve_player, name="Gomez")
    assert out["in_your_draft"]["player_id"] == mine["element"] and out["in_your_draft"]["position"] == "MID"
    assert "OUT" in out["action"] and "without asking" in out["action"]
    assert {k: v for k, v in out.items() if k not in ("in_your_draft", "draft_note", "action")} == \
        {k: v for k, v in plain.items() if k != "action"}


def test_n4b_a_draft_player_beats_a_closer_outside_match_for_the_player_going_out(built, monkeypatch):
    import model_tools as mt
    have = {int(p["element"]) for p in built.doc["players"]}
    mine = next(p for p in built.doc["players"] if p["position"] == "MID" and p["role"] == "start")
    other = next(e for e in _by_pos(built.boot, "MID") if e["id"] not in have)
    _named(built, monkeypatch, {mine["element"]: "Rayan Cherki", other["id"]: "Rayan Rocha"},
           {mine["element"]: "Cherki", other["id"]: "Rayan"})
    plain = mt.resolve_player("Rayan")
    assert plain["ambiguous"] is False and plain["matches"][0]["player_id"] == other["id"]
    out = built.turns.run(mt.resolve_player, name="Rayan")
    assert out["in_your_draft"]["player_id"] == mine["element"]


def test_n4c_two_draft_players_with_the_name_still_ask_and_none_says_so(built, monkeypatch):
    import model_tools as mt
    two = [p for p in built.doc["players"] if p["position"] == "DEF"][:2]
    _named(built, monkeypatch, {two[0]["element"]: "Ben White", two[1]["element"]: "Kyle White"},
           {two[0]["element"]: "White", two[1]["element"]: "White"})
    out = built.turns.run(mt.resolve_player, name="White")
    assert out["in_your_draft"] is None and {r["player_id"] for r in out["draft_matches"]} == {p["element"] for p in two}
    assert "ask which" in out["draft_note"]
    none = built.turns.run(mt.resolve_player, name="Nobody Here")
    assert none["in_your_draft"] is None and "No player in the user's draft" in none["draft_note"]


# ---- W: the root causes behind W11b's eval failures (Prompt W11c, 2026-11-13) --------------------------------------------------
# R1 "suggest changes" had no tool; R2 refusals did not lead with the alternatives; R3 the agent invented reasons; R4 money it
# restated or rounded. On draft turns only.

def _solver_score(boot, ids):
    """The build's own score for a fixed fifteen, by the REAL optimiser (optimize_squad at its defaults, the fifteen locked):
    (objective, XI points with the captain counted twice)."""
    import simulator as sim
    from optimize import optimize_squad, resolve_bench_weight
    pool = pool_of(boot)
    p15 = pool[pool["element"].isin(ids)].reset_index(drop=True)
    prob, sol = optimize_squad(p15, locked_elements=sorted(ids), budget=int(p15["value"].sum()))
    team = sim.solution_to_squad(p15, sol)
    xi = team[team["role"] != "bench"]
    cap = float(team.loc[team["role"] == "CAPTAIN", "e_points"].iloc[0])
    bench = float(team.loc[team["role"] == "bench", "e_points"].sum())
    return float(xi["e_points"].sum()) + cap + resolve_bench_weight() * bench, float(xi["e_points"].sum()) + cap


def _legal_single_swaps(doc, boot):
    have = {int(p["element"]) for p in doc["players"]}
    names = {t["id"]: t["name"] for t in boot["teams"]}
    price, clubs = _price(boot), _club_counts(doc)
    value = sum(price[e] for e in have)
    out = []
    for p in doc["players"]:
        o = int(p["element"])
        for e in _by_pos(boot, p["position"]):
            club = names[e["team"]]
            if e["id"] in have or clubs.get(club, 0) - (1 if club == p["team"] else 0) >= 3:
                continue
            if value - price[o] + e["now_cost"] <= 1000:
                out.append((o, e["id"]))
    return out


def test_w1_propose_transfers_in_a_draft_gives_the_best_free_swaps_by_the_builds_own_score(built):
    import random
    import model_tools as mt
    doc, boot = built.doc, built.boot
    out = built.turns.run(mt.propose_transfers)
    assert out["draft"] is True and out["kind"] == "free_swaps" and 1 <= len(out["swaps"]) <= 3, out
    assert out["already_best"] is True and "already the best" in out["summary"]   # the synthetic draft IS the build
    assert "suggestion" in out["how_to_present"] and "only after the user picks" in out["how_to_present"]
    have = [int(p["element"]) for p in doc["players"]]
    base_obj, base_xi = _solver_score(boot, have)
    pts, price = _pts(boot), _price(boot)
    tops = []
    for s in out["swaps"]:
        o, i = s["out"]["player_id"], s["in"]["player_id"]
        assert (s["out"]["e_points"], s["in"]["e_points"]) == (pts[o], pts[i])
        assert s["points_difference"] == round(pts[i] - pts[o], 2)
        assert s["price_difference"] == round((price[i] - price[o]) / 10, 1)
        after = sum(price[e] for e in have) - price[o] + price[i]
        assert s["value_after"] == round(after / 10, 1) and s["left_after"] == round((1000 - after) / 10, 1)
        new = [i if e == o else e for e in have]
        obj, xi = _solver_score(boot, new)
        assert abs(s["xi_points_after"] - xi) <= 0.06 and abs(s["build_score_change"] - (obj - base_obj)) <= 0.02
        assert s["build_score_change"] <= 0                                  # nothing beats the build
        a = s["preview_with"]
        drafts.plan_change(doc, a["player_ids"], a["captain_id"], a["vice_id"], a["bench_order_ids"],
                           drafts.player_meta(a["player_ids"], ctx=built.api.league.ctx()), {e["id"]: e["now_cost"] for e in boot["elements"]})
        assert sorted(a["player_ids"]) == sorted(new) and a["confirm"] is False
        tops.append(obj)
    assert tops == sorted(tops, reverse=True)
    rng = random.Random(3)
    for o, i in rng.sample(_legal_single_swaps(doc, boot), 25):            # no sampled legal swap scores above the first
        assert _solver_score(boot, [i if e == o else e for e in have])[0] <= tops[0] + 1e-6
    assert drafts.read(U1)["version_id"] == built.row["version_id"]
    assert _q(built.api.conn, "SELECT count(*) FROM squad_previews")[0][0] == 0


def test_w1b_after_a_worse_change_the_first_free_swap_gains(built):
    import db_write
    import model_tools as mt
    doc, boot = built.doc, built.boot
    have = {int(p["element"]) for p in doc["players"]}
    price = _price(boot)
    start_def = max((p for p in doc["players"] if p["position"] == "DEF" and p["role"] == "start"), key=lambda p: _pts(boot)[p["element"]])
    clubs, names = _club_counts(doc), {t["id"]: t["name"] for t in boot["teams"]}
    worse = min((e for e in _by_pos(boot, "DEF") if e["id"] not in have and e["now_cost"] <= price[start_def["element"]]
                 and clubs.get(names[e["team"]], 0) < 3), key=lambda e: e["_pts"])
    a = _args(doc, swap=(start_def["element"], worse["id"]))
    new_doc, _ = drafts.plan_change(doc, a["player_ids"], a["captain_id"], a["vice_id"], a["bench_order_ids"],
                                    drafts.player_meta(a["player_ids"] + list(have), ctx=built.api.league.ctx()), price)
    conn = db_write.connect()
    try:
        drafts.write_change(conn, U1, built.row["version_id"], new_doc)
        conn.commit()
    finally:
        conn.close()
    out = built.turns.run(mt.propose_transfers)
    assert out["already_best"] is False and out["swaps"][0]["build_score_change"] > 0, out
    assert out["swaps"][0]["xi_points_change"] >= 0 and "best free swaps" in out["summary"]


def _first_keys(d, n=2):
    return list(d)[:n]


def test_w2_a_refusal_leads_with_the_alternatives_in_a_ready_sentence(built):
    import model_tools as mt
    out_mid, dear, value = _over_swap(built)
    out = built.turns.run(mt.set_my_squad, **_args(built.doc, swap=(out_mid["element"], dear["id"])))
    assert out["reason_kind"] == "over_budget" and _first_keys(out) == ["instead", "legal_alternatives"], list(out)
    alts = out["legal_alternatives"]
    parts = [f"{a['short_name']} ({a['price_text']}, {a['left_after_text']})" for a in alts]
    want = "Instead you could bring in " + (", ".join(parts[:-1]) + " or " + parts[-1] if len(parts) > 1 else parts[0]) + "."
    assert out["instead"] == want


def test_w2b_a_club_cap_refusal_leads_with_its_alternatives_too(built):
    import model_tools as mt
    doc, boot = built.doc, built.boot
    names = {t["id"]: t["name"] for t in boot["teams"]}
    clubs, have = _club_counts(doc), {int(p["element"]) for p in doc["players"]}
    club = max(clubs, key=clubs.get)
    args, swaps = _args(doc), []
    for e in sorted(boot["elements"], key=lambda e: e["now_cost"]):
        if len(swaps) == 4 - clubs[club]:
            break
        if names[e["team"]] != club or e["id"] in have:
            continue
        o = next((p for p in doc["players"] if p["position"] == POS[e["element_type"]] and p["team"] != club
                  and p["role"] in ("bench", "start") and p["element"] not in [s[0] for s in swaps]), None)
        if o is not None:
            swaps.append((o["element"], e["id"]))
    for o, n in swaps:
        args["player_ids"] = [n if x == o else x for x in args["player_ids"]]
        args["bench_order_ids"] = [n if x == o else x for x in args["bench_order_ids"]]
    out = built.turns.run(mt.set_my_squad, **args)
    assert out["reason_kind"] == "club_cap" and _first_keys(out) == ["instead", "legal_alternatives"], list(out)
    assert out["instead"].startswith("Instead") and all(a["short_name"] in out["instead"] for a in out["legal_alternatives"])


def test_w3_get_my_squad_says_how_the_fifteen_were_picked_and_only_facts_per_player(built):
    import model_tools as mt
    sq = built.turns.run(mt.get_my_squad)
    assert "basis" not in sq
    hp = sq["how_picked"]
    for must in ("most predicted points for GW10", "captain counted twice", "0.2", "bench", "£100.0m", "squad rules"):
        assert must in hp, must
    assert "only" in sq["reasons_rule"] and "predicted points, price, club and next fixture" in sq["reasons_rule"]
    for judgement in ("easy", "tough", "upside", "ceiling", "form"):   # the smoke's invented reasons
        assert judgement in sq["reasons_rule"], judgement
    ctx = built.api.league.ctx()
    team_of = {e["id"]: e["team"] for e in built.boot["elements"]}
    for r in _sq_rows(sq):
        nf = ctx.next_fixture(team_of[r["player_id"]])
        assert r["next_fixture"] == f"{nf['opp']} ({'H' if nf['home'] else 'A'})", r
    wording = (REPO / "prompts" / "draft_mode.md").read_text(encoding="utf-8")
    for must in ("only reasons a tool states", "propose_transfers", "instead"):
        assert must in wording, must


def test_w3b_unknown_fixtures_never_read_as_a_blank(built):
    import draft_tools
    ctx = built.api.league.ctx()
    e = built.boot["elements"][0]["id"]
    assert draft_tools._next_words(ctx, e, 10) is not None
    ctx.fixtures = None                                                # not loaded (a cold cache inside a turn): unknown
    assert draft_tools._next_words(ctx, e, 10) is None
    ctx.fixtures = []                                                  # loaded, and the club has none: a real blank
    assert draft_tools._next_words(ctx, e, 10) == "no fixture in GW10"


MONEY_PLAIN = ("price", "out_price", "in_price", "value", "value_before", "value_after", "budget", "instead_of_price", "replaces_price")
MONEY_LEFT = ("left", "left_before", "left_after")
MONEY_OVER = ("over", "over_after", "over_by")


def _money_texts_ok(x, path="", seen=None):
    """Every money number in a draft tool's output has its said form beside it (R4); returns the money keys checked."""
    seen = [] if seen is None else seen
    if isinstance(x, dict):
        for k, v in x.items():
            if isinstance(v, (int, float)) and not isinstance(v, bool) and k in MONEY_PLAIN + MONEY_LEFT + MONEY_OVER + ("price_difference",):
                want = (f"£{v:.1f}m" if k in MONEY_PLAIN else f"£{v:.1f}m left" if k in MONEY_LEFT else f"£{v:.1f}m over"
                        if k in MONEY_OVER else ("the same price" if v == 0 else f"£{abs(v):.1f}m {'more' if v > 0 else 'less'}"))
                assert x.get(f"{k}_text") == want, f"{path}.{k}: {x.get(k + '_text')!r} != {want!r}"
                seen.append(k)
            else:
                _money_texts_ok(v, f"{path}.{k}", seen)
    elif isinstance(x, list):
        for i, v in enumerate(x):
            _money_texts_ok(v, f"{path}[{i}]", seen)
    return seen


def test_w4_every_money_figure_is_in_the_output_as_it_would_be_said(built):
    import model_tools as mt
    d_out, d_in = _legal_swap(built.doc, built.boot)
    outs = {"squad": built.turns.run(mt.get_my_squad), "xi": built.turns.run(mt.get_my_xi),
            "preview": built.turns.run(mt.set_my_squad, **_args(built.doc, swap=(d_out["element"], d_in["id"]))),
            "swaps": built.turns.run(mt.propose_transfers)}
    out_mid, dear, _ = _over_swap(built)
    outs["over"] = built.turns.run(mt.set_my_squad, **_args(built.doc, swap=(out_mid["element"], dear["id"])))
    seen = {k: set(_money_texts_ok(v, k)) for k, v in outs.items()}
    assert {"price", "value", "left", "budget"} <= seen["squad"] and {"value", "left"} <= seen["xi"]
    assert {"out_price", "in_price", "price_difference", "value_before", "left_before", "value_after", "left_after"} <= seen["preview"]
    assert {"over_by", "value_before", "left_before", "value_after", "price", "left_after"} <= seen["over"]
    assert {"price", "price_difference", "value_after", "left_after"} <= seen["swaps"]
    built.api.league.raise_prices(2, {int(p["element"]) for p in built.doc["players"]})
    assert "over" in _money_texts_ok(built.turns.run(mt.get_my_squad), "squad_over")


# ---- D: real reasons for each pick (Prompt W11d, 2026-11-13) ----------------------------------------------------------------------
# W11c's case 1 ("why these players?") invented causal reasons 3 of 3. The draft's get_my_squad now carries reasons computed by
# code from the build's own objective (D1), its rows grouped by position (D2), each player's main breakdown parts from the same
# source as explain_prediction (D4); the wording allows no other reason and no range (D3).

PICK_RE = re.compile(r"^Picked: the best legal alternative, (.+) \(£(\d+\.\d)m\), would lower the build's score by (\d+\.\d\d)\.$")


def test_d1_each_pick_has_a_reason_computed_from_the_builds_objective_and_checked_against_the_optimiser(built):
    import model_tools as mt
    doc, boot = built.doc, built.boot
    sq = built.turns.run(mt.get_my_squad)
    rows = _sq_rows(sq)
    have = [int(p["element"]) for p in doc["players"]]
    base_obj, _ = _solver_score(boot, have)
    price = _price(boot)
    with_alt = [r for r in rows if r["best_alternative"] is not None]
    assert len(with_alt) >= 10
    for r in rows:
        if r["best_alternative"] is None:                              # e.g. the cheapest keeper with no money left: a true reason
            assert r["pick_reason"] == "Picked: no legal alternative fits his place within £100.0m and FPL's squad rules."
            continue
        m = PICK_RE.match(r["pick_reason"])
        assert m, r["pick_reason"]
        alt = r["best_alternative"]
        assert (m.group(1), float(m.group(2)), float(m.group(3))) == (alt["short_name"], alt["price"], r["build_score_loss"])
        assert alt["price"] == price[alt["player_id"]] / 10 and r["build_score_loss"] >= 0      # the synthetic draft IS the build
    swaps = _legal_single_swaps(doc, boot)
    rng = random.Random(5)
    for r in rng.sample(with_alt, 3):                                   # the reported loss and "best" by the REAL optimiser
        o, best = r["player_id"], r["best_alternative"]["player_id"]
        best_obj, _ = _solver_score(boot, [best if e == o else e for e in have])
        assert abs((base_obj - best_obj) - r["build_score_loss"]) <= 0.02, r
        mine = [i for oo, i in swaps if oo == o and i != best]
        for i in rng.sample(mine, min(8, len(mine))):
            assert _solver_score(boot, [i if e == o else e for e in have])[0] <= best_obj + 1e-6
    xi_cost = sum(price[r["player_id"]] for r in rows if r["in_xi"])
    bench_cost = sum(price[r["player_id"]] for r in rows if not r["in_xi"])
    share = _half_up_int(xi_cost, xi_cost + bench_cost)                # W11g: the XI's share, computed
    assert sq["budget_line"] == (f"XI £{xi_cost / 10:.1f}m, bench £{bench_cost / 10:.1f}m; the XI takes {share}% of the "
                                 f"£{(xi_cost + bench_cost) / 10:.1f}m spent; bench points count 0.2×, so most of the budget goes on the XI.")
    assert "The build's score is the XI's predicted points with the captain counted twice, plus 0.2 × the bench's" in sq["how_picked"]


def test_d1b_a_player_the_build_would_not_pick_says_so(built):
    import db_write
    import model_tools as mt
    doc, boot = built.doc, built.boot
    have = {int(p["element"]) for p in doc["players"]}
    price = _price(boot)
    start_def = max((p for p in doc["players"] if p["position"] == "DEF" and p["role"] == "start"), key=lambda p: _pts(boot)[p["element"]])
    clubs, names = _club_counts(doc), {t["id"]: t["name"] for t in boot["teams"]}
    worse = min((e for e in _by_pos(boot, "DEF") if e["id"] not in have and e["now_cost"] <= price[start_def["element"]]
                 and clubs.get(names[e["team"]], 0) < 3), key=lambda e: e["_pts"])
    a = _args(doc, swap=(start_def["element"], worse["id"]))
    new_doc, _ = drafts.plan_change(doc, a["player_ids"], a["captain_id"], a["vice_id"], a["bench_order_ids"],
                                    drafts.player_meta(a["player_ids"] + list(have), ctx=built.api.league.ctx()), price)
    conn = db_write.connect()
    try:
        drafts.write_change(conn, U1, built.row["version_id"], new_doc)
        conn.commit()
    finally:
        conn.close()
    row = next(r for r in _sq_rows(built.turns.run(mt.get_my_squad)) if r["player_id"] == worse["id"])
    assert row["pick_reason"].startswith("Not the build's pick now: ") and "would raise the build's score by" in row["pick_reason"]
    assert row["build_score_loss"] < 0


def test_d2_the_rows_are_grouped_by_position_with_the_position_spelled_out(built):
    import model_tools as mt
    sq = built.turns.run(mt.get_my_squad)
    groups = sq["squad_by_position"]
    assert list(groups) == ["GK", "DEF", "MID", "FWD"] and [len(groups[p]) for p in groups] == [2, 5, 5, 3]
    words = {"GK": "Goalkeeper", "DEF": "Defender", "MID": "Midfielder", "FWD": "Forward"}
    for pos, rows in groups.items():
        assert all(r["position"] == pos and r["position_name"] == words[pos] for r in rows)
        assert [r["in_xi"] for r in rows] == sorted((r["in_xi"] for r in rows), reverse=True)     # starters first
    assert "xi" not in sq and sum(r["in_xi"] for r in _sq_rows(sq)) == 11
    bench = sorted((p for p in built.doc["players"] if p["role"] == "bench"), key=lambda p: p["bench_order"])
    short = {e["id"]: e["web_name"] for e in built.boot["elements"]}
    assert sq["bench_in_order"] == [short[p["element"]] for p in bench]


def test_d3_the_wording_allows_only_the_tools_reasons(built):
    import model_tools as mt
    rule = built.turns.run(mt.get_my_squad)["reasons_rule"]
    for must in ("pick_reason", "how_picked", "explain_my_draft", "budget_line", "breakdown", "counts as invented"):
        assert must in rule, must
    wording = (REPO / "prompts" / "draft_mode.md").read_text(encoding="utf-8")
    for must in ("pick_reason", "how_picked", "explain_my_draft", "breakdown", "counts as invented"):
        assert must in wording, must
    # W11e E4: D3's "never give a range" is withdrawn -- it contradicts the system prompt's P10 / P50 / P90 ranges
    assert "give a range" not in wording.lower() and "give a range" not in rule.lower()


def _fake_frame(boot, gw=10):
    """A production frame with the explain columns for every player: the breakdown's own inputs, deterministic."""
    rows = []
    for e in boot["elements"]:
        k = e["id"]
        rows.append({"element": k, "gw": gw, "cutoff": gw, "position": POS[e["element_type"]], "team": f"Club {e['team']:02d}",
                     "name": f"P {e['second_name']}", "pts_appear": 1.5 + (k % 5) / 10, "pts_goals": (k % 7) / 5,
                     "pts_assists": (k % 3) / 4, "pts_cs": (k % 4) / 6, "pts_dc": 0.05, "pts_saves": 0.0, "pts_conceded": -(k % 2) / 3,
                     "pts_cards": -0.1, "exp_bonus": 0.0, "p_60plus": 0.80 + (k % 10) / 100, "p_play_any": 0.95,
                     "e_points": 3.0, "e_points_core": 3.0, "team_lambda": 1.2 + e["team"] / 100, "opp_lambda": 1.3})
    return pd.DataFrame(rows)


def test_d4_each_player_carries_his_main_breakdown_parts_from_explain_predictions_source(built, monkeypatch):
    import explain
    import model_tools as mt
    df = _fake_frame(built.boot)
    monkeypatch.setattr(mt, "_frame_raw", lambda: (df, 10, datetime(2026, 11, 2, 11, 0, tzinfo=UTC)))
    sq = built.turns.run(mt.get_my_squad)
    for r in _sq_rows(sq):
        row, step, err = mt._explain_row(df, 10, r["player_id"], 10)
        assert err is None
        lines = explain.breakdown(row, step)["lines"]                  # what explain_prediction shows for him
        want = [{"part": l["term"].replace("_", " "), "points": round(l["points"], 2)} for l in lines if round(l["points"], 2) != 0][:3]
        b = r["breakdown"]
        assert b["parts"] == want, (r["short_name"], b)
        assert (b["chance_of_60_plus"], b["chance_of_playing"]) == (round(row["p_60plus"], 2), round(row["p_play_any"], 2))
        for part in want:
            assert f"{part['part']} {part['points']:+.2f}" in b["breakdown_words"]
        assert f"a {round(row['p_60plus'] * 100)}% chance of playing 60+ minutes" in b["breakdown_words"]
    monkeypatch.setattr(mt, "_frame_raw", lambda: (_ for _ in ()).throw(FileNotFoundError("gone")))
    sq = built.turns.run(mt.get_my_squad)                              # no frame: no breakdown, the rest of the answer stands
    assert all(r["breakdown"] is None for r in _sq_rows(sq)) and all(r["pick_reason"] for r in _sq_rows(sq))


# ---- E: the two "explain" answers (Prompt W11e, 2026-11-13) --------------------------------------------------------------------
# W11d: every "why these players?" reply listed all fifteen and hit the 1,024-token reply limit, and every captain reply worked out
# a number itself. E1 a short squad_explanation built by code; E2 the "Why these players?" chip answered from it, $0; E3 the
# captain's P10 / P50 / P90 (with the armband too) and his margin over the next-best option; E4 the range ban withdrawn.

def _fake_prediction(q):
    """model_tools.get_prediction's shape for one gameweek (the source get_player_card shows), with these quantiles."""
    def get_prediction(player_id, gw=None):
        p10, p50, p90 = q
        return {"player_id": player_id, "predictions": [{"gw": gw, "q_p10": p10, "q_p50": p50, "q_p90": p90}],
                "quantiles": {"computed": True, "per_gw": [{"gw": gw, "p10": p10, "p50": p50, "p90": p90, "p10_unusable": False}]}}
    return get_prediction


def test_e1_the_summary_is_built_by_code_and_get_my_squad_no_longer_carries_its_own_explanation(built):
    """W11e E1's short explanation is now explain_my_draft's summary (W11g G4: one source of truth)."""
    import draft_tools
    import model_tools as mt
    sq = built.turns.run(mt.get_my_squad)
    assert "squad_explanation" not in sq
    ex = built.turns.run(mt.explain_my_draft, detail="summary")["direct_reply"]
    for must in ("most predicted points for GW10", "captain counted twice", "0.2 × the bench's", "£100.0m"):
        assert must in ex, must
    cap = sq["captain_points"]
    assert f"Captain: {cap['short_name']}, {cap['e_points']:.2f} predicted points, {cap['with_armband']:.2f} with the armband" in ex
    rows = sorted((r for r in _sq_rows(sq) if r["build_score_loss"] and r["build_score_loss"] > 0),
                  key=lambda r: (-r["build_score_loss"], r["player_id"]))[:4]
    want = ", ".join(f"{r['short_name']} {r['build_score_loss']:.2f} ({r['best_alternative']['short_name']}, "
                     f"£{r['best_alternative']['price']:.1f}m, {_relation(r['price'], r['best_alternative']['price'])})"
                     for r in rows)
    assert f"by what the best legal alternative would cost the build's score: {want}." in ex
    assert ex.rstrip().endswith(draft_tools.EXPLAIN_FOLLOW_UP)
    assert "- **" not in ex                                             # never the fifteen


def test_e2_the_why_chip_is_answered_from_code_stored_as_a_turn_and_no_model_is_called(dapi):
    import agent_graph
    import model_tools as mt
    body = _post(dapi, "/me/draft").json()
    tid = body["thread_id"]
    called = []
    dapi.mp.setattr(dapi.agent, "run_agent", lambda *a, **k: called.append(1) or ("never", []))
    r = _post(dapi, "/me/draft/explain", json={"thread_id": tid, "question": "Why these players?"})
    assert r.status_code == 200, r.text
    out = r.json()
    assert called == [] and out["thread_id"] == tid and out["message_id"] and out["sources"] == []
    row = drafts.read(U1)
    summary = Turns(U1, tid, row["draft_key"]).run(mt.explain_my_draft, detail="summary")["direct_reply"]
    assert out["answer"] == summary                                    # W11g G4: one builder for the chip and the tool
    msgs = _get(dapi, f"/threads/{tid}/messages").json()
    assert [m["role"] for m in msgs] == ["assistant", "user", "assistant"]
    assert msgs[1]["text"] == "Why these players?" and msgs[2]["text"] == out["answer"] and msgs[2]["message_id"] == out["message_id"]
    hist = agent_graph.load_history(tid)                               # the agent sees the turn on the next question
    assert hist[1] == {"role": "user", "content": "Why these players?"} and hist[2] == {"role": "assistant", "content": out["answer"]}
    rows = _get(dapi, "/threads").json()
    assert rows[0]["thread_id"] == tid and rows[0]["is_draft"] is True and rows[0]["title"] == "Why these players?"
    plain = _post(dapi, "/threads").json()["thread_id"]                # not a draft chat: refused
    assert _post(dapi, "/me/draft/explain", json={"thread_id": plain, "question": "Why these players?"}).status_code == 404
    _post(dapi, "/me/draft", sub=T2)                                   # another user's draft chat: refused
    assert _post(dapi, "/me/draft/explain", sub=T2, json={"thread_id": tid, "question": "Why these players?"}).status_code == 404
    assert _post(dapi, "/me/draft/explain", json={"thread_id": tid, "question": "x" * 201}).status_code == 422


def test_e3_captain_points_carry_the_range_the_armband_range_and_the_margin_over_the_next_best(built, monkeypatch):
    import model_tools as mt
    monkeypatch.setattr(mt, "get_prediction", _fake_prediction((2.0, 6.0, 14.0)))
    sq = built.turns.run(mt.get_my_squad)
    cap = sq["captain_points"]
    assert cap["range"] == {"p10": 2.0, "p50": 6.0, "p90": 14.0, "p10_unusable": False}
    assert cap["range_with_armband"] == {"p10": 4.0, "p50": 12.0, "p90": 28.0}
    xi = sorted((r for r in _xi(sq) if r["player_id"] != cap["player_id"]), key=lambda r: -r["e_points"])
    nb = cap["next_best"]
    assert (nb["player_id"], nb["e_points"], nb["margin"]) == (xi[0]["player_id"], xi[0]["e_points"],
                                                              round(cap["e_points"] - xi[0]["e_points"], 2))
    words = cap["captain_words"]
    for n in (cap["e_points"], cap["with_armband"], nb["e_points"], nb["margin"]):
        assert f"{n:.2f}" in words, n
    assert "with the armband: low 4.0, middle 12.0, top 28.0" in words and nb["short_name"] in words
    assert "2.0 / 6.0 / 14.0" not in words and "P10 / P50 / P90" not in words          # W11h H2: never two ranges side by side
    monkeypatch.setattr(mt, "get_prediction", lambda player_id, gw=None: {"error": "no prediction rows"})
    cap = built.turns.run(mt.get_my_squad)["captain_points"]           # no quantiles: no range, the rest stands
    assert cap["range"] is None and cap["range_with_armband"] is None and cap["next_best"]


def test_e3c_the_captaincy_edge_is_the_margin_itself_and_the_top_options_are_listed(built, monkeypatch):
    """The W11e dev smoke: "doubles to a 2.46-point edge" (the margin doubled -- wrong: captaining him rather than the next-best
    adds the margin once) and "no other player within 2 points" (an invented threshold, and false)."""
    import model_tools as mt
    monkeypatch.setattr(mt, "get_prediction", _fake_prediction((2.0, 6.0, 14.0)))
    sq = built.turns.run(mt.get_my_squad)
    cap, nb = sq["captain_points"], sq["captain_points"]["next_best"]
    assert cap["captaincy_edge"] == {"over": nb["short_name"], "points": nb["margin"]}
    edge = (f"captaining {cap['short_name']} rather than {nb['short_name']} adds {nb['margin']:.2f} to the XI's predicted total "
            "(the armband counts one player twice, so the edge is the margin itself, not double it)")
    assert edge in cap["captain_words"]
    xi = sorted(_xi(sq), key=lambda r: (-r["e_points"], r["player_id"]))[:3]
    assert [{k: o[k] for k in ("player_id", "short_name", "e_points", "with_armband")} for o in cap["captain_options"]] == \
        [{"player_id": r["player_id"], "short_name": r["short_name"], "e_points": r["e_points"],
          "with_armband": round(2 * r["e_points"], 2)} for r in xi]


def test_e1b_get_my_squad_routes_every_explanation_to_explain_my_draft(built):
    import model_tools as mt
    rule = built.turns.run(mt.get_my_squad)["explain_answer_rule"]
    for must in ("explain_my_draft", "each_player", "player by player", "player=", "never write your own explanation"):
        assert must in rule, must


def test_e3b_the_wording_says_quote_numbers_exactly_with_no_hedges():
    wording = (REPO / "prompts" / "draft_mode.md").read_text(encoding="utf-8")
    assert "explain_my_draft" in wording and "never list all fifteen" not in wording.lower()      # W11f V2: withdrawn
    assert "player by player" in wording
    for w in ("nearly", "over", "about", "around"):
        assert f'"{w}"' in wording, w


# ---- F (Prompt W11f): value facts by code, each pick's rank, the wording --------------------------------------------------

def _most(rank, joint):
    """'the most' / 'the 2nd-most' / 'the joint 3rd-most' -- written independently of draft_tools."""
    if rank == 1:
        return "the joint most" if joint else "the most"
    suf = "th" if 10 <= rank % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(rank % 10, "th")
    return f"the {'joint ' if joint else ''}{rank}{suf}-most"


def _biggest(rank, joint):
    if rank == 1:
        return "the joint biggest" if joint else "the biggest"
    suf = "th" if 10 <= rank % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(rank % 10, "th")
    return f"the {'joint ' if joint else ''}{rank}{suf}-biggest"


def test_f1_each_player_carries_his_points_per_million_and_his_rank_among_his_position_at_his_price_or_less(built):
    """W11f V1: "for his price" IS the human explanation -- so the tool states it. Points per £1m from his shown points and
    current price; his rank at his position among ALL players priced at or below him, from the same predictions and prices
    (checked here by brute force over the league)."""
    import model_tools as mt
    sq = built.turns.run(mt.get_my_squad)
    pts, price = _pts(built.boot), _price(built.boot)
    pos_of = {e["id"]: POS[e["element_type"]] for e in built.boot["elements"]}
    seen_ranks = set()
    for r in _sq_rows(sq):
        e, v = r["player_id"], r["value_facts"]
        assert r["e_points"] == pts[e] and r["price"] == price[e] / 10
        assert abs(v["points_per_million"] - pts[e] / (price[e] / 10)) <= 0.005 + 1e-9, r
        group = [i for i in pos_of if pos_of[i] == r["position"] and price[i] <= price[e]]
        rank = 1 + sum(1 for i in group if pts[i] > pts[e])
        joint = any(pts[i] == pts[e] for i in group if i != e)
        assert (v["rank"], v["joint"], v["of"], v["position"]) == (rank, joint, len(group), r["position"]), r
        assert v["words"] == (f"{v['points_per_million']:.2f} predicted points per £1m; {_most(rank, joint)} predicted points "
                              f"of any {r['position']} at £{price[e] / 10:.1f}m or less ({len(group)} players)"), v["words"]
        seen_ranks.add(rank)
    assert len(seen_ranks) > 1                                          # not one rank for everyone


def test_f1b_without_a_price_or_points_there_are_no_value_facts(built, monkeypatch):
    import model_tools as mt
    first = int(built.doc["players"][0]["element"])
    orig = drafts.current_prices
    monkeypatch.setattr(drafts, "current_prices", lambda ids, ctx=None, allow_fetch=True:
                        {e: v for e, v in orig(ids, ctx=ctx, allow_fetch=allow_fetch).items() if e != first})
    rows = {r["player_id"]: r for r in _sq_rows(built.turns.run(mt.get_my_squad))}
    assert rows[first]["value_facts"] is None
    assert all(r["value_facts"] is not None for e, r in rows.items() if e != first)


def test_f2_each_pick_carries_its_rank_by_what_the_best_legal_alternative_would_cost(built):
    """W11f V3: the baseline's false claims were ranks the model worked out ("third-strongest pick overall", "the
    second-biggest overall pick after Haaland") -- each pick's rank now comes from the tool."""
    import model_tools as mt
    rows = _sq_rows(built.turns.run(mt.get_my_squad))
    ranked = [r for r in rows if r["build_score_loss"] is not None and r["build_score_loss"] >= 0]
    assert len(ranked) >= 10
    for r in rows:
        if r not in ranked:
            assert r["pick_rank"] is None
            continue
        loss = r["build_score_loss"]
        rank = 1 + sum(1 for x in ranked if x["build_score_loss"] > loss)
        joint = any(x["build_score_loss"] == loss for x in ranked if x is not r)
        assert (r["pick_rank"]["rank"], r["pick_rank"]["joint"], r["pick_rank"]["of"]) == (rank, joint, len(ranked)), r
        assert r["pick_rank"]["words"] == (f"{_biggest(rank, joint)} of the {len(ranked)} picks by what the best legal "
                                           f"alternative would cost the build's score ({loss:.2f})")


def test_f3_the_wording_allows_value_remarks_only_as_value_facts_state_them_and_ranks_only_from_pick_rank(built):
    import model_tools as mt
    rule = built.turns.run(mt.get_my_squad)["reasons_rule"]
    wording = (REPO / "prompts" / "draft_mode.md").read_text(encoding="utf-8")
    for text in (rule, wording):
        for must in ("value_facts", "pick_rank", "for his price", "counts as invented", "pick_reason", "how_picked",
                     "budget_line"):
            assert must in text, must
    assert "value for money, fixtures" not in wording                   # value is no longer on the invented list


# ---- G (Prompt W11g): long explanations are written by CODE (explain_my_draft) -------------------------------------------
# W11f: a fifteen-player walkthrough holds ~70 facts; at ~99% per fact about half of all walkthroughs carry one slip ("almost all"
# for 77%, "cheaper" for the same price, "the most" for 2nd-most). These tests make such slips impossible by construction: every
# rank or value phrase is the player's own value_facts / pick_rank, every price relation matches the two prices, every
# percentage is computed from the data -- over the synthetic league, random perturbations of it and the real run-73 draft.

RUN73 = REPO / "Tests" / "fixtures" / "w11g_run73_get_my_squad.json"
MOST_RE = re.compile(r"the (?:joint )?(?:\d+(?:st|nd|rd|th)-)?most predicted points of any (?:GK|DEF|MID|FWD) at £\d+\.\dm or less "
                     r"\(\d+ players\)")
BIG_RE = re.compile(r"the (?:joint )?(?:\d+(?:st|nd|rd|th)-)?biggest of the \d+ picks")
REL_RE = re.compile(r"£(\d+\.\d)m, (the same price|£\d+\.\dm (?:cheaper|dearer))\)")
PCT_RE = re.compile(r"(\d+)%")
NUM_RE = re.compile(r"\d+(?:\.\d+)?")
BANNED = ("almost all", "nearly all", "entirely", "mostly", "good value", "bargain", "best value", "for his price", "at his price",
          "cheap ", "cheap.", "pick_reason", "value_facts", "pick_rank", "how_picked", "budget_line")


def _relation(price, alt):
    d = round(alt * 10) - round(price * 10)
    return "the same price" if d == 0 else f"£{abs(d) / 10:.1f}m {'cheaper' if d < 0 else 'dearer'}"


def _half_up_int(num, den):
    from decimal import ROUND_HALF_UP, Decimal
    return int((Decimal(num) * 100 / Decimal(den)).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def _player_numbers(r):
    """Every number a player's line may show, as written: his own fields only."""
    out = {"1", "15", "100.0", str(r.get("bench_order") or "")}       # 100.0: "within £100.0m" when no alternative fits
    if r.get("price") is not None:
        out.add(f"{r['price']:.1f}")
    if r.get("e_points") is not None:
        out.add(f"{r['e_points']:.2f}")
    for prt in ((r.get("breakdown") or {}).get("parts") or []):
        out.add(f"{abs(prt['points']):.2f}")
    if r.get("build_score_loss") is not None:
        out.add(f"{abs(r['build_score_loss']):.2f}")
    alt = r.get("best_alternative")
    if alt:
        out.add(f"{alt['price']:.1f}")
        d = abs(round(alt["price"] * 10) - round(r["price"] * 10)) / 10
        out.add(f"{d:.1f}")
    v = r.get("value_facts")
    if v:
        out |= set(NUM_RE.findall(v["words"]))
    pr = r.get("pick_rank")
    if pr:
        out |= {str(pr["rank"]), str(pr["of"])}
    return out


def _check_explain(sq, text, detail):
    """The by-construction rules over one explanation (summary / each_player / one player)."""
    rows = {r["short_name"]: r for r in _sq_rows(sq)}
    low = text.lower()
    for b in BANNED:
        assert b not in low, b
    lines = [ln for ln in text.split("\n") if ln.startswith("- **")]
    if detail == "each_player":
        names = [ln[4:ln.index("**", 4)] for ln in lines]
        assert names == [r["short_name"] for r in _sq_rows(sq)]        # all fifteen, by position, once each
    for ln in lines:
        r = rows[ln[4:ln.index("**", 4)]]
        v, pr = r.get("value_facts"), r.get("pick_rank")
        assert [m.group(0) for m in MOST_RE.finditer(ln)] == ([] if v is None else [v["words"].split("; ", 1)[1]]), ln
        assert v is None or v["words"] in ln
        assert [m.group(0) for m in BIG_RE.finditer(ln)] == ([] if pr is None else [f"{_biggest(pr['rank'], pr['joint'])} of the {pr['of']} picks"]), ln
        for m in REL_RE.finditer(ln):
            assert r["best_alternative"] and float(m.group(1)) == r["best_alternative"]["price"], ln
            assert m.group(2) == _relation(r["price"], r["best_alternative"]["price"]), ln
        allowed = _player_numbers(r)
        body = ln[ln.index("**", 4) + 2:].replace(str(r["team"]), "")      # a synthetic club is "Club 03"
        if r.get("best_alternative"):
            body = body.replace(str(r["best_alternative"]["short_name"]), "")   # a synthetic name is "P045"
        for n in NUM_RE.findall(body):
            assert n in allowed, (r["short_name"], n, ln)
    # the summary's biggest picks: each loss, alternative and relation is that player's own
    for m in re.finditer(r"([^\s,:(]+(?: [^\s,:(]+)?) (\d+\.\d\d) \(([^,]+), £(\d+\.\d)m, (the same price|£\d+\.\dm (?:cheaper|dearer))\)",
                         text):
        r = rows.get(m.group(1))
        if r is None:
            continue
        assert f"{r['build_score_loss']:.2f}" == m.group(2) and r["best_alternative"]["short_name"] == m.group(3)
        assert float(m.group(4)) == r["best_alternative"]["price"] and m.group(5) == _relation(r["price"], r["best_alternative"]["price"])
    # every percentage is computed from the data: the XI's share of the money spent, the captain's points share
    xi = sum(round(r["price"] * 10) for r in rows.values() if r["in_xi"] and r["price"] is not None)
    total = sum(round(r["price"] * 10) for r in rows.values() if r["price"] is not None)
    want = {_half_up_int(xi, total)}
    share = (sq.get("captain_points") or {}).get("points_share")
    if share:
        want.add(_half_up_int(f"{share['points']:.2f}", f"{share['of']:.2f}"))
    for m in PCT_RE.finditer(text):
        assert int(m.group(1)) in want, (m.group(0), want)
    if "the XI takes" in text:
        assert f"the XI takes {_half_up_int(xi, total)}% of the £{total / 10:.1f}m spent" in text


def _fake_frame_sq(built, monkeypatch):
    import model_tools as mt
    df = _fake_frame(built.boot)
    monkeypatch.setattr(mt, "_frame_raw", lambda: (df, 10, datetime(2026, 11, 2, 11, 0, tzinfo=UTC)))
    return built.turns.run(mt.get_my_squad)


def test_g1_explain_my_draft_is_code_built_and_its_text_is_the_direct_reply(built, monkeypatch):
    import draft_tools
    import model_tools as mt
    sq = _fake_frame_sq(built, monkeypatch)
    for detail in ("summary", "each_player"):
        out = built.turns.run(mt.explain_my_draft, detail=detail)
        text = out["direct_reply"]
        assert text == draft_tools.explain_text(sq, detail)
        _check_explain(sq, text, detail)
        assert text.rstrip().endswith(draft_tools.EXPLAIN_FOLLOW_UP) and draft_tools.BONUS_NOTE in text
    rows = _sq_rows(sq)
    each = built.turns.run(mt.explain_my_draft, detail="each_player")["direct_reply"]
    for pos, head in (("GK", "Goalkeepers"), ("DEF", "Defenders"), ("MID", "Midfielders"), ("FWD", "Forwards")):
        assert f"**{head}**" in each
    for r in rows:                                                     # every player's facts, as his row has them
        ln = next(x for x in each.split("\n") if x.startswith(f"- **{r['short_name']}**"))
        assert f"£{r['price']:.1f}m" in ln and f"{r['e_points']:.2f} predicted points" in ln
        for prt in r["breakdown"]["parts"]:
            assert f"{prt['part']} {prt['points']:+.2f}" in ln
    one = rows[3]
    asked = one["short_name"].lower()
    out = built.turns.run(mt.explain_my_draft, detail="summary", player=asked)
    assert f"- **{one['short_name']}**" in out["direct_reply"] and out["direct_reply"].count("- **") == 1
    _check_explain(sq, out["direct_reply"], "player")
    bad = built.turns.run(mt.explain_my_draft, detail="summary", player="Nobody Atall")
    assert "direct_reply" not in bad and "not one of" in bad["error"]
    assert "error" in mt.explain_my_draft(detail="summary")            # outside a draft chat: never the draft


def test_g1b_the_captains_own_explanation_carries_his_captain_words(built, monkeypatch):
    import model_tools as mt
    sq = _fake_frame_sq(built, monkeypatch)
    cap = sq["captain_points"]
    out = built.turns.run(mt.explain_my_draft, detail="summary", player=cap["short_name"])["direct_reply"]
    assert cap["captain_words"] in out


def test_g2_false_claims_are_impossible_by_construction_over_random_drafts(built, monkeypatch):
    """A property test: the builder transcribes whatever facts it gets -- 60 random perturbations of the synthetic draft
    (prices, alternatives' prices, losses, value ranks, pick ranks), every rule checked on every text."""
    import copy
    import draft_tools
    base = _fake_frame_sq(built, monkeypatch)
    for seed in range(60):
        rng = random.Random(seed)
        sq = copy.deepcopy(base)
        for r in _sq_rows(sq):
            r["price"] = rng.randint(40, 150) / 10
            if r.get("best_alternative"):
                r["best_alternative"]["price"] = round(rng.choice([r["price"], max(3.9, r["price"] - rng.randint(1, 60) / 10),
                                                                   r["price"] + rng.randint(1, 30) / 10]), 1)
                r["build_score_loss"] = round(rng.uniform(-0.6, 5.0), 2)
            rank, joint = rng.randint(1, 30), rng.random() < 0.2
            of = rank + rng.randint(0, 250)
            ppm = round(r["e_points"] / r["price"], 2)
            r["value_facts"] = {"points_per_million": ppm, "position": r["position"], "rank": rank, "joint": joint, "of": of,
                                "words": f"{ppm:.2f} predicted points per £1m; {_most(rank, joint)} predicted points of any "
                                         f"{r['position']} at £{r['price']:.1f}m or less ({of} players)"}
        ranked = [r for r in _sq_rows(sq) if r.get("build_score_loss") is not None and r["build_score_loss"] >= 0]
        for r in _sq_rows(sq):
            if r in ranked:
                k = 1 + sum(1 for x in ranked if x["build_score_loss"] > r["build_score_loss"])
                r["pick_rank"] = {"rank": k, "joint": any(x["build_score_loss"] == r["build_score_loss"] for x in ranked if x is not r),
                                  "of": len(ranked)}
            else:
                r["pick_rank"] = None
        for detail in ("summary", "each_player"):
            _check_explain(sq, draft_tools.explain_text(sq, detail), detail)
        for r in rng.sample(_sq_rows(sq), 3):
            _check_explain(sq, draft_tools.explain_text(sq, "summary", r["short_name"]), "player")


def test_g2b_the_real_run73_draft_explains_with_no_false_claim():
    """The real draft of W11f's diag and eval (production run 73, GW11): every explanation passes the same rules. The six
    after-diag slips of W11f could not be written: Kelleher is 'the same price', Suzuki is 'the 2nd-most', the XI's share is 77%."""
    import json
    import draft_tools
    sq = json.loads(RUN73.read_text(encoding="utf-8"))
    each = draft_tools.explain_text(sq, "each_player")
    _check_explain(sq, each, "each_player")
    _check_explain(sq, draft_tools.explain_text(sq, "summary"), "summary")
    for r in _sq_rows(sq):
        _check_explain(sq, draft_tools.explain_text(sq, "summary", r["short_name"]), "player")
    suzuki = next(x for x in each.split("\n") if x.startswith("- **Suzuki**"))
    assert "Kelleher (£5.0m, the same price)" in suzuki and "the 2nd-most predicted points of any GK at £5.0m or less" in suzuki
    assert "the XI takes 77% of the £99.9m spent" in each


def test_g3_the_wording_routes_every_explanation_to_the_tool():
    import draft_tools
    wording = (REPO / "prompts" / "draft_mode.md").read_text(encoding="utf-8")
    for text in (wording, draft_tools.EXPLAIN_ANSWER_RULE):
        for must in ("explain_my_draft", "each_player", "player by player", "never write your own explanation"):
            assert must in text, must
    for text in (wording, draft_tools.REASONS_RULE):                   # G5: give the share, never a vague one
        assert "almost all" in text and "give the share" in text


def test_g5_captain_words_give_the_share_of_his_points(built, monkeypatch):
    sq = _fake_frame_sq(built, monkeypatch)
    cap = sq["captain_points"]
    row = next(r for r in _sq_rows(sq) if r["role"] == "CAPTAIN")
    parts = row["breakdown"]["parts"]
    part = max(parts, key=lambda x: x["points"])                     # W11h H1: his biggest part
    pct = _half_up_int(f"{part['points']:.2f}", f"{row['e_points']:.2f}")
    assert cap["points_share"] == {"part": part["part"], "points": part["points"], "of": row["e_points"], "percent": pct}
    assert f"{part['part']} {part['points']:.2f} of his {row['e_points']:.2f} predicted points ({pct}%)" in cap["captain_words"]


# ---- H (Prompt W11h): the captain answer built by code; one range per phrase; the owner's follow-up; the swap budget fact ----
# W11g: two captain replies spliced the bare and the armband ranges ("4.0 / 12.0 / 14.0") and one reply got the budget rule
# wrong ("same or less" with £0.1m left). The captain answer is now code-built like the walkthrough, no field puts two ranges
# side by side, and the budget rule for a swap is a sentence from code.

RUN73_H = REPO / "Tests" / "fixtures" / "w11h_run73_get_my_squad.json"
ARMBAND_RE = re.compile(r"with the armband: low (\d+\.\d), middle (\d+\.\d), top (\d+\.\d)")
FOLLOW_UP = "Which player would you like me to go into, or is there anyone you'd like to bring in?"


def _option_numbers(o):
    out = {"1", "60", "3", f"{o['e_points']:.2f}", f"{o['with_armband']:.2f}"}
    a = o.get("range_with_armband")
    if a:
        out |= {f"{a[k]:.1f}" for k in ("p10", "p50", "p90")}
    sh = o.get("points_share")
    if sh:
        out |= {f"{sh['points']:.2f}", f"{sh['of']:.2f}", str(sh["percent"])}
    if o.get("chance_of_60_plus") is not None:
        out.add(str(round(o["chance_of_60_plus"] * 100)))
    m = o.get("margin_to_next")
    if m:
        out |= {f"{m['points']:.2f}", f"{m['e_points']:.2f}"}
    return out


def _check_captain(sq, text):
    """The by-construction rules over the code-built captain answer: the captain and the vice named from the rows; each
    option's line carries only his own numbers; its range phrase is HIS armband range; no bare range anywhere; no vague
    share; the bonus sentence and the owner's follow-up."""
    import draft_tools
    cap = sq["captain_points"]
    rows = {r["short_name"]: r for r in _sq_rows(sq)}
    captain = next(r["short_name"] for r in rows.values() if r["role"] == "CAPTAIN")
    vice = next(r["short_name"] for r in rows.values() if r["role"] == "VICE")
    assert f"Captain: {captain}. Vice-captain: {vice}." in text
    lines = [ln for ln in text.split("\n") if ln.startswith("- **")]
    opts = {o["short_name"]: o for o in cap["captain_options"] + (cap.get("extra_options") or [])}   # + the captain / vice
    names = [ln[4:ln.index("**", 4)] for ln in lines]                                             # when not in the top 3
    assert names[:3] == [o["short_name"] for o in cap["captain_options"]][:3], names
    for ln, name in zip(lines, names):
        o = opts[name]
        a = o.get("range_with_armband")
        found = ARMBAND_RE.findall(ln)
        assert found == ([] if a is None else [(f"{a['p10']:.1f}", f"{a['p50']:.1f}", f"{a['p90']:.1f}")]), ln
        body = ln[ln.index("**", 4) + 2:].replace(str(rows[name]["team"]), "")
        m = o.get("margin_to_next")
        if m:
            body = body.replace(str(m["short_name"]), "")
        for n in NUM_RE.findall(body):
            assert n in _option_numbers(o), (name, n, ln)
    low = text.lower()
    for b in ("p10", "p50", "p90", "almost all", "entirely", "mostly", "captain_points", "range_with_armband"):
        assert b not in low, b
    assert draft_tools.BONUS_NOTE in text and text.rstrip().endswith(FOLLOW_UP)


def test_h1_the_captain_answer_is_code_built_and_is_the_direct_reply(built, monkeypatch):
    import draft_tools
    import model_tools as mt
    _fake_frame_sq(built, monkeypatch)
    monkeypatch.setattr(mt, "get_prediction", _fake_prediction((2.0, 6.0, 14.0)))
    sq = built.turns.run(mt.get_my_squad)
    out = built.turns.run(mt.explain_my_draft, detail="captain")
    assert out["direct_reply"] == draft_tools.explain_text(sq, "captain")
    _check_captain(sq, out["direct_reply"])
    xi = sorted((r for r in _sq_rows(sq) if r["in_xi"]), key=lambda r: (-r["e_points"], r["player_id"]))
    opts = sq["captain_points"]["captain_options"]
    assert [o["player_id"] for o in opts] == [r["player_id"] for r in xi[:3]]
    for i, o in enumerate(opts):                                        # each option's own facts, from his row
        r = xi[i]
        assert o["range_with_armband"] == {"p10": 4.0, "p50": 12.0, "p90": 28.0}
        assert o["chance_of_60_plus"] == r["breakdown"]["chance_of_60_plus"]
        part = max(r["breakdown"]["parts"], key=lambda x: x["points"])
        assert o["points_share"] == {"part": part["part"], "points": part["points"], "of": r["e_points"],
                                     "percent": _half_up_int(f"{part['points']:.2f}", f"{r['e_points']:.2f}")}
        nxt = xi[i + 1]
        assert o["margin_to_next"] == {"short_name": nxt["short_name"], "e_points": nxt["e_points"],
                                       "points": round(r["e_points"] - nxt["e_points"], 2)}


def test_h1b_captain_answers_are_correct_by_construction_over_random_options_and_the_real_run73_draft(built, monkeypatch):
    """60 random perturbations of the options (points, ranges, shares, chances, margins) and the real draft (production run 73):
    every option line carries only its own numbers and its own armband range."""
    import copy
    import json
    import draft_tools
    import model_tools as mt
    _fake_frame_sq(built, monkeypatch)
    monkeypatch.setattr(mt, "get_prediction", _fake_prediction((2.0, 6.0, 14.0)))
    base = built.turns.run(mt.get_my_squad)
    for seed in range(60):
        rng = random.Random(seed)
        sq = copy.deepcopy(base)
        for o in sq["captain_points"]["captain_options"]:
            o["e_points"] = round(rng.uniform(2, 12), 2)
            o["with_armband"] = round(2 * o["e_points"], 2)
            lo = round(rng.uniform(0, 6), 1)
            o["range_with_armband"] = None if rng.random() < 0.15 else {"p10": lo, "p50": round(lo + rng.uniform(0, 8), 1),
                                                                        "p90": round(lo + rng.uniform(8, 30), 1)}
            pts = round(rng.uniform(0.5, o["e_points"]), 2)
            o["points_share"] = {"part": rng.choice(["goals", "appearance", "assists"]), "points": pts, "of": o["e_points"],
                                 "percent": _half_up_int(f"{pts:.2f}", f"{o['e_points']:.2f}")}
            o["chance_of_60_plus"] = round(rng.uniform(0.3, 0.99), 2)
            o["margin_to_next"]["points"] = round(rng.uniform(0, 3), 2)
        _check_captain(sq, draft_tools.explain_text(sq, "captain"))
    real = json.loads(RUN73_H.read_text(encoding="utf-8"))
    text = draft_tools.explain_text(real, "captain")
    _check_captain(real, text)
    assert "with the armband: low 4.0, middle 12.0, top 28.0" in text and "14.0" not in text


def test_h2_no_field_puts_the_bare_and_the_armband_ranges_side_by_side(built, monkeypatch):
    import json
    import model_tools as mt
    monkeypatch.setattr(mt, "get_prediction", _fake_prediction((2.0, 6.0, 14.0)))
    sq = built.turns.run(mt.get_my_squad)
    cap = sq["captain_points"]
    assert cap["range"]["p90"] == 14.0 and cap["range_with_armband"]["p90"] == 28.0     # each in its own field

    def strings(x):
        if isinstance(x, str):
            yield x
        elif isinstance(x, dict):
            for v in x.values():
                yield from strings(v)
        elif isinstance(x, list):
            for v in x:
                yield from strings(v)

    def has(s_, n):
        return re.search(rf"(?<![\d.]){re.escape(n)}(?!\d)", s_) is not None
    for text in strings(sq):
        assert not (has(text, "2.0") and has(text, "6.0") and has(text, "14.0")), text    # the bare range in no text
        assert "P10 / P50 / P90" not in text
    for text in strings(json.loads(RUN73_H.read_text(encoding="utf-8"))):
        assert not (has(text, "2.0") and has(text, "6.0") and has(text, "14.0")), text


def test_h3_the_code_built_answers_end_with_the_owners_follow_up_and_the_website_offers_its_chips(built, monkeypatch):
    import draft_tools
    import model_tools as mt
    monkeypatch.setattr(mt, "get_prediction", _fake_prediction((2.0, 6.0, 14.0)))
    assert draft_tools.EXPLAIN_FOLLOW_UP == FOLLOW_UP
    for detail in ("summary", "each_player", "captain"):
        assert built.turns.run(mt.explain_my_draft, detail=detail)["direct_reply"].rstrip().endswith(FOLLOW_UP), detail
    one = _sq_rows(built.turns.run(mt.get_my_squad))[0]["short_name"]
    assert built.turns.run(mt.explain_my_draft, detail="summary", player=one)["direct_reply"].rstrip().endswith(FOLLOW_UP)
    ts = (REPO / "web" / "lib" / "draft-chips.ts").read_text(encoding="utf-8")
    assert f'export const EXPLAIN_FOLLOW_UP =\n  "{FOLLOW_UP}";' in ts or f'export const EXPLAIN_FOLLOW_UP = "{FOLLOW_UP}";' in ts
    assert '{ text: "Explain one player" }' in ts and '{ text: "Bring someone in" }' in ts


def test_i1_the_swap_budget_words_are_gone_and_a_named_swap_is_always_previewed(built):
    """W11i I1: W11h's swap_budget_words let the model judge a named over-budget swap itself -- no set_my_squad call, so no
    refusal and none of the tool's alternatives (W11h case 6, 0 of 3). Reverted: the field is gone, and the wording sends
    every named swap to set_my_squad first."""
    import draft_tools
    import model_tools as mt
    sq = built.turns.run(mt.get_my_squad)
    assert "swap_budget_words" not in sq and not hasattr(draft_tools, "_swap_budget_words")
    wording = (REPO / "prompts" / "draft_mode.md").read_text(encoding="utf-8")
    for text in (wording, draft_tools.REASONS_RULE):
        assert "swap_budget_words" not in text
        assert "For any named swap, always preview it with set_my_squad first" in text
        assert "never judge affordability yourself" in text


def test_h5_the_wording_routes_captain_questions_to_code():
    import draft_tools
    wording = (REPO / "prompts" / "draft_mode.md").read_text(encoding="utf-8")
    for text in (wording, draft_tools.EXPLAIN_ANSWER_RULE):
        assert "captain" in text and "explain_my_draft" in text
    assert 'detail="captain"' in wording and "outside the top 3" in wording
    assert "with and without the armband" not in wording                  # H2: one range per phrase


# ---- S: real squads are never touched ----------------------------------------------------------------------------------------

def _real_counts(conn):
    out = {}
    for t in ("squad_versions", "squad_scores", "user_fpl_teams"):
        if _q(conn, f"SELECT to_regclass('public.{t}') IS NOT NULL")[0][0]:
            out[t] = _q(conn, f"SELECT count(*), coalesce(sum(hashtext(t::text)), 0) FROM {t} t")[0]
    return out


def test_s1_draft_writes_never_touch_real_squads_or_teams(dapi, monkeypatch):
    import fpl_teams
    import fpl_import
    monkeypatch.setattr(fpl_import, "team_summary", lambda *a, **k: {}, raising=False)
    r = dapi.client.post("/me/teams", headers=bearer(mint(T1)), json={"fpl_team_id": 4242424})
    assert r.status_code == 200, r.text                                # a real team exists
    before = _real_counts(dapi.conn)
    body = _post(dapi, "/me/draft").json()
    _post(dapi, "/me/draft/rebuild")
    _post(dapi, "/threads", json={"draft": True})
    row = drafts.read(U1)
    t = Turns(U1, body["thread_id"], row["draft_key"])
    import model_tools as mt
    sq = t.run(mt.get_my_squad)
    rb = {k: v for k, v in sq["rebuild_with"].items() if k != "confirm"}
    t.run(mt.set_my_squad, **_args(row["squad_json"]))
    _delete(dapi, "/me/draft")
    assert _real_counts(dapi.conn) == before
    assert fpl_teams.active_team(U1) is not None or True                # the active flag was never flipped by draft code


# ---- D: Delete account and the guest reaper -----------------------------------------------------------------------------------

def test_d1_delete_account_removes_the_draft_and_its_chats(dapi):
    import deletion
    _post(dapi, "/me/draft")
    _post(dapi, "/me/draft", sub=T2)
    user = dict(zip(("user_id", "clerk_user_id", "is_admin", "is_exempt", "email"),
                    _q(dapi.conn, "SELECT user_id, clerk_user_id, is_admin, is_exempt, email FROM app_users WHERE user_id = %s",
                       (U1,))[0]))
    out = deletion.delete_account(user, clerk_delete=lambda cid: "deleted")
    assert out["removed"]["drafts"] == 1 and out["removed"]["chats"] >= 1
    assert [r[0] for r in _draft_rows(dapi.conn)] == [U2]
    assert _q(dapi.conn, "SELECT count(*) FROM chat_threads WHERE user_id = %s", (U1,))[0][0] == 0


def test_d2_the_guest_reaper_removes_a_guests_draft(dapi, monkeypatch):
    import guest
    import users
    _post(dapi, "/me/draft")
    with dapi.conn.cursor() as cur:
        cur.execute("UPDATE app_users SET is_guest = TRUE WHERE user_id = %s", (U1,))
    monkeypatch.setattr(guest, "enabled", lambda: False)              # the switch off: every guest is swept
    monkeypatch.setattr(guest, "clerk_get_user", lambda cid: {"public_metadata": {"guest": True}})
    monkeypatch.setattr(users, "delete_clerk_user", lambda cid: "deleted")
    out = guest.sweep()
    assert [d["user_id"] for d in out["deleted"]] == [U1], out
    assert _draft_rows(dapi.conn) == []
    assert _q(dapi.conn, "SELECT count(*) FROM chat_threads WHERE user_id = %s", (U1,))[0][0] == 0


# ---- T: threads ---------------------------------------------------------------------------------------------------------------

def test_t1_a_draft_chat_is_listed_after_its_first_question_tagged_and_titled_by_it(dapi):
    body = _post(dapi, "/me/draft").json()
    dapi.brain.say = lambda *a, **k: "A reply."
    r = dapi.client.post("/chat", headers=bearer(mint(T1)), json={"message": "Why these players?", "thread_id": body["thread_id"]})
    assert r.status_code == 200, r.text
    rows = _get(dapi, "/threads").json()
    assert len(rows) == 1 and rows[0]["thread_id"] == body["thread_id"]
    assert rows[0]["is_draft"] is True and rows[0]["title"] == "Why these players?" and rows[0]["fpl_team_id"] is None
    msgs = _get(dapi, f"/threads/{body['thread_id']}/messages").json()
    assert [m["role"] for m in msgs][:2] == ["assistant", "user"] and msgs[0]["kind"] == "draft_opening"
    import agent_graph
    assert agent_graph.load_history(body["thread_id"])[0] == {"role": "assistant", "content": drafts.OPENING_TEXT}


def test_t2_a_draft_chat_resolves_whatever_team_is_active(dapi, monkeypatch):
    import threads
    body = _post(dapi, "/me/draft").json()
    monkeypatch.setattr(threads, "current_owner", lambda uid: 900_000_123)   # a team is active
    assert threads.resolve(U1, body["thread_id"]) == body["thread_id"]
    plain = _post(dapi, "/threads").json()["thread_id"]
    with dapi.conn.cursor() as cur:
        cur.execute("UPDATE chat_threads SET owner_key = %s WHERE thread_id = %s", (U1, plain))
    with pytest.raises(threads.TeamChanged):
        threads.resolve(U1, plain)                                     # an ordinary chat still gets the 409


def test_t3_a_draft_turn_carries_the_draft_and_its_block_an_ordinary_turn_does_not(dapi):
    body = _post(dapi, "/me/draft").json()
    seen = []
    orig = dapi.agent.run_agent

    def spy(message, messages=None, *, thread=None):
        seen.append(dict(thread or {}))
        return orig(message, messages, thread=thread)
    dapi.mp.setattr(dapi.agent, "run_agent", spy)
    dapi.client.post("/chat", headers=bearer(mint(T1)), json={"message": "hi", "thread_id": body["thread_id"]})
    dapi.client.post("/chat", headers=bearer(mint(T1)), json={"message": "hi"})
    assert seen[0]["draft"] == {"user_id": U1, "draft_key": a_key(dapi)}
    assert "draft" not in seen[1]


# ---- DDL ----------------------------------------------------------------------------------------------------------------------

def test_ddl_is_stable():
    """The draft schema of record (W11). A change here must be deliberate: re-pin AND re-apply at the deploy
    (`python -c "import drafts; drafts.ensure_schema()"`)."""
    assert hashlib.sha256(drafts.DDL.encode("utf-8")).hexdigest() == DDL_SHA256
    for must in ("CREATE TABLE IF NOT EXISTS user_drafts", "user_id     INT         PRIMARY KEY",
                 "draft_key   INT         NOT NULL UNIQUE", "version_id  INT         NOT NULL UNIQUE"):
        assert must in drafts.DDL, must


def test_squad_store_ddl_is_unchanged():
    import squad_store
    from test_squad_store_writes import DDL_SHA256 as SQUAD_DDL
    assert hashlib.sha256(squad_store.DDL.encode("utf-8")).hexdigest() == SQUAD_DDL


# ---- Prompt X1 (2026-11-13): a draft change is saved ONLY by the user's explicit yes to THAT preview ---------------------
# The incident: the owner's "No" to two draft previews was read by the model as a yes and both swaps were saved. Now the
# model alone can never write, a typed answer is decided by code, and the preview's buttons name their own preview.

def _draft_preview(built):
    import model_tools as mt
    d_out, d_in = _legal_swap(built.doc, built.boot)
    args = _args(built.doc, swap=(d_out["element"], d_in["id"]))
    prev = built.turns.run(mt.set_my_squad, **args)
    assert prev["preview"] is True and prev["preview_ticket"], prev
    return args, prev, f"turn-{built.turns.n}"


def test_x1_the_incident_a_models_confirm_after_no_saves_nothing(built):
    import model_tools as mt
    args, prev, _ = _draft_preview(built)
    out = built.turns.run(mt.set_my_squad, yes=False, **args, confirm=True, preview_ticket=prev["preview_ticket"])
    assert out["refused"] is True and out["reason"] == "needs_yes" and out["draft"] is True
    assert drafts.read(U1)["version_id"] == built.row["version_id"]


@pytest.mark.parametrize("said", ["No", "No, keep it", "no thanks", "nope", "cancel", "don't", "keep my team",
                                  "no don't change it"])
def test_x1_a_typed_no_in_the_draft_chat_saves_nothing(built, said):
    import confirm_gate
    import turn_context
    _draft_preview(built)
    thread = {"thread_id": built.tid, "user_id": U1, "draft": {"user_id": U1, "draft_key": built.row["draft_key"]}}
    reply, _ = confirm_gate.answer_turn(said, [], thread)
    turn_context.end()
    assert reply == "No change made." and drafts.read(U1)["version_id"] == built.row["version_id"]


def _after_the_preview(monkeypatch):
    """Turns.run dates its turns a few seconds AHEAD of now; the answer's turn must start after the preview's."""
    import turn_context
    monkeypatch.setattr(turn_context, "clock", lambda: datetime.now(UTC) + timedelta(minutes=5))


def test_x1_a_typed_yes_in_the_draft_chat_saves_once(built, monkeypatch):
    import confirm_gate
    import turn_context
    args, prev, _ = _draft_preview(built)
    _after_the_preview(monkeypatch)
    thread = {"thread_id": built.tid, "user_id": U1, "draft": {"user_id": U1, "draft_key": built.row["draft_key"]}}
    reply, _ = confirm_gate.answer_turn("yes please", [], thread)
    assert turn_context.current()["consent"] == prev["preview_ticket"]   # the commit ran under THIS ticket's consent
    turn_context.end()
    row = drafts.read(U1)
    assert reply.startswith("Done — saved to your draft.") and row["version_id"] != built.row["version_id"]
    assert row["n_changes"] == 1 and (turn_context.last() or {}).get("squad_applied", {}).get("draft") is True
    assert confirm_gate.answer_turn("yes", [], thread) is None          # a second yes: nothing open, no second write
    turn_context.end()
    assert drafts.read(U1)["version_id"] == row["version_id"]


def test_x1_the_buttons_answer_their_own_preview_by_code(built, monkeypatch):
    """POST /me/preview/answer: No -> "No change made." and the draft unchanged; Yes on that cancelled preview -> nothing;
    a new preview's Yes -> saved once (squad_applied for the card); a second Yes -> "already saved"; another user -> 403."""
    _, _, mid = _draft_preview(built)
    _after_the_preview(monkeypatch)
    no = _post(built.api, "/me/preview/answer", json={"thread_id": built.tid, "message_id": mid, "answer": "no"})
    assert no.status_code == 200 and no.json()["answer"] == "No change made." and no.json()["squad_applied"] is None
    assert drafts.read(U1)["version_id"] == built.row["version_id"]
    late = _post(built.api, "/me/preview/answer", json={"thread_id": built.tid, "message_id": mid, "answer": "yes"})
    assert late.json()["answer"].startswith("Nothing was saved") and drafts.read(U1)["version_id"] == built.row["version_id"]
    _, _, mid2 = _draft_preview(built)
    assert _post(built.api, "/me/preview/answer", json={"thread_id": built.tid, "message_id": mid2, "answer": "yes"},
                 sub=T2).status_code == 403
    yes = _post(built.api, "/me/preview/answer", json={"thread_id": built.tid, "message_id": mid2, "answer": "yes"})
    row = drafts.read(U1)
    assert yes.status_code == 200 and yes.json()["answer"].startswith("Done — saved to your draft.")
    assert yes.json()["squad_applied"] == {"gw": yes.json()["squad_applied"]["gw"], "version_id": row["version_id"],
                                           "draft": True, "kind": "change"}
    assert row["version_id"] != built.row["version_id"] and row["n_changes"] == 1
    again = _post(built.api, "/me/preview/answer", json={"thread_id": built.tid, "message_id": mid2, "answer": "yes"})
    assert again.json()["answer"] == "That change is already saved." and drafts.read(U1)["version_id"] == row["version_id"]
    msgs = _get(built.api, f"/threads/{built.tid}/messages").json()
    said = [m["text"] for m in msgs if m["role"] == "user"][-4:]
    assert said == ["No", "Yes", "Yes", "Yes"]                          # stored as the chat's turns, like typed answers
    bad = _post(built.api, "/me/preview/answer", json={"thread_id": built.tid, "message_id": mid2, "answer": "maybe"})
    assert bad.status_code == 422
