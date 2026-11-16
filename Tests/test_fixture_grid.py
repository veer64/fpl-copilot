"""Prompt R3b item 3 (16 Nov 2026; USER DECISION): the fixture list for all clubs, or more than five, is a grid written by code.

Measured before (eval/reports/r3_answers.md): "Show me all twenty clubs' next five fixtures." was the one reply of Set A the
2,048-token cap stopped mid-table (its twin fitted in 1,980); "When's the next deadline, and who do my players face?" took a
squad read and twelve single-club calls; "Who has the easiest run of games for the next four?" was ranked by hand, with a slip.

F1   one row a club, one column a gameweek; each cell names the opponent, home or away, and the fixture's TWO ratings in words
     with their numbers -- exactly the tool's own compact rows;
F2   a blank is "no fixture", a double names both opponents and says its ratings once, a kicked-off match is "already played",
     an unrated fixture is "not rated yet" -- never an easy fixture, never "not scheduled";
F3   the words: 1-2 very hard, 3-4 hard, 5-6 middling, 7-8 easy, 9-10 very easy, and the legend says so; two ratings, never one;
F4   under the table each club's scoring ratings and clean-sheet ratings are added over the gameweeks shown (two sums), and
     the highest and lowest runs equal a count over the same rows;
F5   the next deadline (the clock helper's own line) and the update's time are in the answer; it ends with the closing question;
F6   all clubs, or a list of more than five -> the grid IS the reply; five or fewer -> the rows go to the model, as before;
     one club -> exactly what it was;
F7   "who do my players face": the clubs of the saved fifteen with the players named; no saved squad -> the no-squad result;
F8   a club name that matches nothing is refused with the known names; a draft chat's turn gets the result it always had.
Seeded clubs (Tests/r3_seed.py), the real fixture builder; no model, no network."""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
for p in (str(REPO), str(REPO / "squad"), str(Path(__file__).resolve().parent)):
    if p not in sys.path:
        sys.path.insert(0, p)

import answers                                              # noqa: E402
import fixtures_tool as ft                                  # noqa: E402
import model_tools as mt                                    # noqa: E402
import now_context as nc                                    # noqa: E402
import r3_seed as seed                                      # noqa: E402
import squad_store                                          # noqa: E402
from r3_seed import pool_db                                 # noqa: E402,F401  (the fixture)

NOW = datetime(2026, 11, 16, 9, 0, tzinfo=timezone.utc)
CLUBS = seed.CLUBS
EXTRA = ["Golf", "Hotel"]                                    # two more clubs, so that "more than five" and "all" differ
ALL = sorted(CLUBS + EXTRA)
GWS = [11, 12, 13, 14, 15]


def _kick(g, i=0, days=0):
    """Saturday 15:00 UTC of that gameweek (GW11 = 21 Nov 2026), an hour later for a double's second match."""
    return (datetime(2026, 11, 21, 15 + i, 0, tzinfo=timezone.utc) + timedelta(days=7 * (g - 11) + days)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _calendar():
    """{(club, gw): [{"opponent", "opponent_id", "home", "kickoff"}]} for eight clubs, GW11-16: Alpha doubles in GW12, Bravo
    blanks in GW13 (the seed's shape), every kickoff after NOW."""
    cal = {}
    for (club, g), fx in seed.calendar().items():
        cal[(club, g)] = [{"opponent": f["opponent"], "opponent_id": 0, "home": f["home"], "kickoff": _kick(g, i)} for i, f in enumerate(fx)]
    for g in seed.GWS:
        cal[("Golf", g)] = [{"opponent": "Hotel", "opponent_id": 0, "home": g % 2 == 0, "kickoff": _kick(g, days=2)}]     # the Monday match
        cal[("Hotel", g)] = [{"opponent": "Golf", "opponent_id": 0, "home": g % 2 == 1, "kickoff": _kick(g, days=2)}]
    return cal


def _model_rows(gws=seed.GWS):
    """One model row a (club, gameweek) with a fixture: distinct expected goals and clean-sheet chances, so every score is
    decided by rank."""
    rows = []
    for k, ((club, g), _fx) in enumerate(sorted(_calendar().items())):
        if g not in gws:
            continue
        rows.append({"element": 1, "gw": g, "team": club, "team_lambda": 0.6 + 0.037 * ((k * 7) % 41),
                     "opp_lambda": 1.9 - 0.031 * ((k * 5) % 37), "p_cs": 0.08 + 0.012 * ((k * 11) % 43), "horizon_step": g - 11,
                     "n_fixtures": len(_fx)})
    return rows


@pytest.fixture
def fx(pool_db, monkeypatch):
    """get_fixtures on the seeded clubs: the calendar and the per-club model rows are the test's, the fixture builder is the
    real one, the clock is fixed before every kickoff."""
    cal = _calendar()
    monkeypatch.setattr(ft, "calendar", lambda path=None, df=None: (cal, len(ALL)))
    monkeypatch.setattr(mt, "_team_gw_rows", lambda run_id, skel: (_model_rows(), {}))
    monkeypatch.setattr(mt, "_fixture_results", lambda: {})
    monkeypatch.setattr(mt, "_gw_in_progress", lambda: None)
    monkeypatch.setattr(nc, "clock", lambda: NOW)
    monkeypatch.setattr(nc, "_load_deadlines", lambda: {11: datetime(2026, 11, 21, 11, 0, tzinfo=timezone.utc),
                                                        12: datetime(2026, 11, 28, 11, 0, tzinfo=timezone.utc)})
    shorts = {**seed.SHORTS, "Golf": "GOL", "Hotel": "HOT"}
    monkeypatch.setattr(mt, "_club_short_names", lambda: dict(shorts))
    return {"cal": cal, "shorts": shorts}


def _compact(fx_env, **kw):
    """The tool's own compact rows for the same request -- what the model used to get -- through the real builder."""
    return ft.build(_model_rows(), fx_env["cal"], len(ALL), now=NOW, results={}, **kw)


def _cell_for(rows, shorts, with_day=False):
    opps = " + ".join(f"{shorts[r['opponent']]} ({'H' if r['home'] else 'A'})" + (f", {r['kickoff_day']}" if with_day else "") for r in rows)
    a, d = rows[0]["attack_score"], rows[0]["defence_score"]
    words = answers.DIFFICULTY_WORDS
    return f"{opps}: scoring {words[a]} ({a}), clean sheet {words[d]} ({d})" + (" (the two fixtures together)" if len(rows) > 1 else "")


def test_f1_one_row_a_club_one_column_a_gameweek_from_the_tools_own_rows(fx):
    out = mt.get_fixtures()
    assert "direct_reply_error" not in out and set(out) >= {"direct_reply", "clubs", "gameweeks"}
    text = out["direct_reply"]
    assert text.split("\n")[0] == "**Fixtures for all 8 clubs, GW11–16 (6 gameweeks).**" or text.split("\n")[0] == "**Fixtures for all 8 clubs, GW11–15 (5 gameweeks).**"
    compact = _compact(fx, horizon=5)
    gws = sorted({r["gw"] for r in compact["fixtures"]})
    head, body = seed.tables(text)[0]
    assert head == ["Club"] + [f"GW{g}" for g in gws] and [r[0] for r in body] == ALL
    by = {}
    for r in compact["fixtures"]:
        by.setdefault((r["team"], r["gw"]), []).append(r)
    checked = 0
    for r in body:
        for g, cell in zip(gws, r[1:]):
            rows = by.get((r[0], g))
            if rows:
                assert cell == _cell_for(rows, fx["shorts"]), (r[0], g)
                checked += 1
    assert checked == len(by) >= 39                                          # every listed fixture is in the grid, as the tool rated it
    assert out["gameweeks"] == gws and out["clubs"] == ALL


def test_f2_blank_double_played_and_unrated_cells(fx, monkeypatch):
    text = mt.get_fixtures(gw=13)["direct_reply"]                            # one gameweek, every club: Bravo has no fixture
    head, body = seed.tables(text)[0]
    cells = {r[0]: r[1] for r in body}
    assert head == ["Club", "GW13"] and cells["Bravo"] == "no fixture"
    text = mt.get_fixtures(gw=12)["direct_reply"]
    alpha = {r[0]: r[1] for r in seed.tables(text)[0][1]}["Alpha"]
    assert " + " in alpha and alpha.endswith("(the two fixtures together)") and alpha.count("scoring") == 1
    # an unrated gameweek: the model's rows stop at GW14, the calendar goes on
    monkeypatch.setattr(mt, "_team_gw_rows", lambda run_id, skel: (_model_rows(gws=[11, 12, 13, 14]), {}))
    text = mt.get_fixtures(horizon=6)["direct_reply"]
    head, body = seed.tables(text)[0]
    col = head.index("GW16")
    assert all(r[col].endswith(": not rated yet") for r in body if r[0] != "Alpha")
    assert {r[0]: r[col] for r in body}["Alpha"] == "—"                      # Alpha's double: its six fixtures end at GW15
    assert "A dash: the club has a fixture that gameweek, beyond the number of fixtures asked for." in text
    assert "GW15, GW16: scheduled but not rated yet; this update rates GW11–14 only. That is a missing rating, not an easy fixture." in text
    assert "not scheduled" not in text
    # a kicked-off match is not among the fixtures to come: its cell says so
    monkeypatch.setattr(nc, "clock", lambda: datetime(2026, 11, 22, 9, 0, tzinfo=timezone.utc))      # Sunday: only the Monday match is to come
    text = mt.get_fixtures(horizon=2)["direct_reply"]
    head, body = seed.tables(text)[0]
    col = head.index("GW11")
    assert {r[0]: r[col] for r in body if r[0] not in ("Golf", "Hotel")} == {c: "already played" for c in CLUBS}
    assert all(r[col].startswith(("HOT (", "GOL (")) and "scoring" in r[col] for r in body if r[0] in ("Golf", "Hotel"))


def test_f3_the_words_and_the_legend():
    w = answers.DIFFICULTY_WORDS
    assert [w[k] for k in range(1, 11)] == ["very hard", "very hard", "hard", "hard", "middling", "middling", "easy", "easy", "very easy", "very easy"]
    assert answers.difficulty_words(8, 5) == "scoring easy (8), clean sheet middling (5)"
    assert answers.difficulty_words(1, 10) == "scoring very hard (1), clean sheet very easy (10)"
    cells = {("Alpha", 11): [{"opponent": "Bravo", "home": True, "attack": 9, "defence": 3}]}
    text = answers.fixture_grid(["Alpha"], [11], cells, shorts={"Bravo": "BRA"})
    assert "| Alpha | BRA (H): scoring very easy (9), clean sheet hard (3) |" in text
    assert "1 (hardest) to 10 (easiest): 1–2 very hard, 3–4 hard, 5–6 middling, 7–8 easy, 9–10 very easy." in text
    assert "The two often disagree and are never merged into one." in text


def test_f4_the_runs_are_two_sums_over_the_same_rows(fx):
    out = mt.get_fixtures(horizon=4)
    text = out["direct_reply"]
    compact = _compact(fx, horizon=4)
    att, dfn = {c: 0 for c in ALL}, {c: 0 for c in ALL}
    seen = set()
    for r in compact["fixtures"]:
        if (r["team"], r["gw"]) in seen or r["attack_score"] is None:
            continue
        seen.add((r["team"], r["gw"]))                                       # a double's ratings are the gameweek's: counted once
        att[r["team"]] += r["attack_score"]
        dfn[r["team"]] += r["defence_score"]

    def run(sums):
        ranked = sorted(sums.items(), key=lambda kv: (-kv[1], kv[0]))
        top = [kv for kv in ranked if kv[1] >= ranked[2][1]]
        low = sorted((kv for kv in ranked if kv[1] <= ranked[-3][1]), key=lambda kv: (kv[1], kv[0]))
        return f"highest {', '.join(f'{c} {v}' for c, v in top)}; lowest {', '.join(f'{c} {v}' for c, v in low)}"

    gws = sorted({r["gw"] for r in compact["fixtures"]})
    label = f"GW{gws[0]}–{gws[-1]}"
    assert (f"**Runs over {label}** (each club's ratings added up over those gameweeks; a gameweek with no fixture adds nothing):") in text
    assert f"- Scoring ratings: {run(att)}." in text and f"- Clean-sheet ratings: {run(dfn)}." in text


def test_f5_the_deadline_the_update_and_the_closing_question(fx):
    text = mt.get_fixtures()["direct_reply"]
    lines = text.split("\n")
    assert lines[1] == nc.countdown_line(NOW) + "." == "Next deadline: GW11, Sat 21 Nov 2026 11:00 UTC — in 5 d 2 h 0 m."
    assert lines[2] == f"Ratings from the update of Wed 11 Nov 2026, 11:01 UTC. Next update: {seed.NEXT_UPDATE}."
    assert lines[-1] == "Want me to rank the best players from any of these clubs?" and lines[-3] == "Any Premier League side can beat anyone."
    assert ("GW11 is priced off the betting market. GW12–15 are longer-range estimates from team strengths, with no odds, lineups or "
            "team news yet, so these ratings will move before then.") in text or "GW12–16 are longer-range estimates" in text


def test_f6_all_clubs_or_more_than_five_is_the_reply_and_fewer_is_not(fx):
    six = mt.get_fixtures(teams=["Alpha", "bravo", "CHA", "Delta", "Echo", "Foxtrot"])
    assert six["direct_reply"].split("\n")[0].startswith("**Fixtures for 6 clubs, GW11–")
    assert [r[0] for r in seed.tables(six["direct_reply"])[0][1]] == sorted(CLUBS)
    five = mt.get_fixtures(teams=["Alpha", "Bravo", "Charlie", "Delta", "Echo"])
    assert "direct_reply" not in five and five["compact"] is True and five["teams_requested"] == sorted(CLUBS)[:5]
    assert {r["team"] for r in five["fixtures"]} == set(sorted(CLUBS)[:5]) and all("in_words" in r for r in five["fixtures"] if r.get("opponent"))
    one = mt.get_fixtures(team="Alpha")
    assert "direct_reply" not in one and one["compact"] is False and one["season_summary"]["team"] == "Alpha"
    # the grid's facts are the same tool rows: nothing in the six-club grid that the all-clubs answer does not hold
    all_rows = {r[0]: r for r in seed.tables(mt.get_fixtures()["direct_reply"])[0][1]}
    for r in seed.tables(six["direct_reply"])[0][1]:
        assert r[1:6] == all_rows[r[0]][1:6]


def test_f7_who_do_my_players_face(fx, monkeypatch):
    ids = [101, 109, 102, 103, 110, 118, 126, 105, 113, 121, 129, 137, 107, 115, 123]
    record = {"squad_json": {"players": [{"element": e, "name": seed.PLAYERS[e - 101][1], "position": seed.PLAYERS[e - 101][2],
                                           "team": seed.PLAYERS[e - 101][3]} for e in ids]}}
    monkeypatch.setattr(mt, "_read_active", lambda user_id: record)
    monkeypatch.setattr(mt, "_squad_owner", lambda user_id: user_id)
    out = mt.get_fixtures(my_players=True, gw=11)
    text = out["direct_reply"]
    assert text.split("\n")[0] == "**Your players' fixtures, GW11 (1 gameweek): the 5 clubs in your squad.**"
    head, body = seed.tables(text)[0]
    assert head == ["Club", "Your players", "GW11"] and [r[0] for r in body] == ["Alpha", "Bravo", "Charlie", "Delta", "Echo"]
    alpha = next(r for r in body if r[0] == "Alpha")
    assert alpha[1] == "Alp GK1 (GK), Alp DEF1 (DEF), Alp DEF2 (DEF), Alp MID1 (MID), Alp FWD1 (FWD)"
    compact = _compact(fx, gw=11)
    row = next(r for r in compact["fixtures"] if r["team"] == "Alpha")
    assert alpha[2] == _cell_for([row], fx["shorts"], with_day=True) and row["kickoff_day"] in alpha[2]   # one gameweek: the kickoff is in the cell
    assert text.split("\n")[-1] == "Want me to review your squad over these gameweeks?"
    assert text.split("\n")[1].startswith("Next deadline: GW11, Sat 21 Nov 2026 11:00 UTC")
    # no span asked for: the players' NEXT fixture, not five gameweeks; a span that is asked for is honoured
    nxt = mt.get_fixtures(my_players=True)
    assert seed.tables(nxt["direct_reply"])[0][0] == ["Club", "Your players", "GW11"] and nxt["gameweeks"] == [11]
    three = mt.get_fixtures(my_players=True, horizon=3)
    assert three["direct_reply"].split("\n")[0].startswith("**Your players' fixtures, GW11–1") and len(three["gameweeks"]) >= 3
    assert mt.get_fixtures()["gameweeks"][:5] == [11, 12, 13, 14, 15]         # every club, no span asked for: five fixtures, as always

    def no_squad(user_id):
        raise squad_store.NoSquadError("no active squad")

    monkeypatch.setattr(mt, "_read_active", no_squad)
    none = mt.get_fixtures(my_players=True)
    assert none.get("no_squad") is True and "direct_reply" not in none


def test_f8_an_unknown_club_is_refused_and_a_draft_turn_is_untouched(fx, monkeypatch):
    bad = mt.get_fixtures(teams=["Alpha", "Bravo", "Charlie", "Delta", "Echo", "Zulu"])
    assert "error" in bad and "known_teams" in bad and "direct_reply" not in bad
    normal_one = mt.get_fixtures(team="Alpha")
    monkeypatch.setattr(mt, "_draft_turn", lambda: {"user_id": 10001, "draft_key": 800_000_001})
    draft_all = mt.get_fixtures()
    assert "direct_reply" not in draft_all and draft_all["compact"] is True and len({r["team"] for r in draft_all["fixtures"]}) == 8
    assert all("in_words" not in r for r in draft_all["fixtures"])           # R3's ready words are a normal turn's, as before
    draft_one = mt.get_fixtures(team="Alpha")
    assert set(draft_one) == set(normal_one) and "direct_reply" not in draft_one
    assert "direct_reply" not in mt.get_fixtures(teams=sorted(CLUBS), my_players=True)   # arguments a draft chat's schema does not have: ignored
