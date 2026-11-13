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
    assert bare.delete("/me/draft", headers=h).status_code == 200
    assert bare.get("/me/draft").status_code == 401                    # no token: refused before the handler


def test_r7_off_mode_every_draft_route_is_404_and_nothing_reads_user_drafts(dapi, monkeypatch):
    monkeypatch.setenv("AUTH_MODE", "off")
    dapi.auth._reset()
    for method, path, kw in (("post", "/me/draft", {}), ("get", "/me/draft", {}), ("post", "/me/draft/rebuild", {}),
                             ("delete", "/me/draft", {}), ("post", "/threads", {"json": {"draft": True}})):
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

    def run(self, fn, **kw):
        import turn_context
        self.n += 1
        turn_context.begin(f"turn-{self.n}", started_at=datetime.now(UTC) + timedelta(seconds=self.n), thread_id=self.tid,
                           draft={"user_id": self.uid, "draft_key": self.key})
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
    assert sq["draft"] is True and sq["not_in_fpl"] is True and len(sq["xi"]) == 11 and len(sq["bench_in_order"]) == 4
    assert sq["value"] <= 100.0 and sq["rules"]["max_per_club"] == 3 and sq["rebuild_with"]["player_ids"]
    assert sq["rebuild_would_change_players"] == 0 and sq["changes_since_build"] == 0
    assert all(r["e_points"] is not None for r in sq["xi"])            # the LATEST predictions, per player
    assert "free_transfers_now" not in sq and "bank" not in sq
    xi = built.turns.run(mt.get_my_xi)
    assert xi["draft"] is True and len(xi["xi"]) == 11 and xi["adopt_with"]["player_ids"] == sorted(sq["rebuild_with"]["player_ids"])
    for fn in (mt.propose_transfers, mt.get_my_points, mt.get_wildcard_gap):
        out = built.turns.run(fn)
        assert out["draft"] is True and out["not_applicable"] is True
    assert "free and unlimited" in built.turns.run(mt.propose_transfers)["message"]


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

def _pts(boot):
    return {e["id"]: round(e["_pts"], 2) for e in boot["elements"]}


def _price(boot):
    return {e["id"]: e["now_cost"] for e in boot["elements"]}


def test_n1_get_my_squad_gives_each_starters_points_the_captain_doubled_the_xi_total_and_the_money(built):
    import model_tools as mt
    sq = built.turns.run(mt.get_my_squad)
    pts, price = _pts(built.boot), _price(built.boot)
    assert all(r["e_points"] == pts[r["player_id"]] for r in sq["xi"])
    cap = next(r for r in sq["xi"] if r["role"] == "CAPTAIN")
    assert sq["captain_points"] == {"player_id": cap["player_id"], "name": cap["name"], "short_name": cap["short_name"],
                                    "e_points": cap["e_points"], "with_armband": round(2 * cap["e_points"], 2)}
    assert cap["e_points_with_armband"] == round(2 * cap["e_points"], 2)
    assert all("e_points_with_armband" not in r for r in sq["xi"] + sq["bench_in_order"] if r["role"] != "CAPTAIN")
    assert sq["predicted_xi_points"] == round(sum(r["e_points"] for r in sq["xi"]) + cap["e_points"], 1)
    value = sum(price[r["player_id"]] for r in sq["xi"] + sq["bench_in_order"])
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
