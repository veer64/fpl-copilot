"""Prompt R3c item 3 (16 Nov 2026; USER DECISION): the league table is written by code.

Measured before (eval/reports/r3b_answers.md, Set A): the model-written table answers added commentary their own table
contradicted -- "Brighton and Brentford finish level on all three counting measures" beside goal differences of +6 and +3, and
"an unbeaten run of 18 at the end of the season", which no tool gave.

L1  every cell -- position, played, won, drawn, lost, goals for / against, goal difference, points -- equals a hand count of the
    synthetic season's results admitted by the as-of rule; the order is the builder's;
L2  the as-of line: the cutoff, where it came from, how many results were counted and the latest one; a postponed fixture dated
    before the cutoff is listed as not counted; an unranked club is said as such;
L3  no commentary: every line is the header, the as-of line, the table, the not-counted / tiebreak lines or the closing question;
L4  after_gw=N is every result before GW N+1's first kickoff (the same cutoff the default derives for the run's gameweek);
    after_gw with as_of, or a gameweek the calendar cannot place, is refused for the model;
L5  one club's answer, an empty table and a draft chat's turn carry no code-built text.
The synthetic season of Tests/test_league_table.py, through model_tools.get_league_table; no model, no network."""
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
for p in (str(REPO), str(REPO / "squad"), str(REPO / "eval"), str(Path(__file__).resolve().parent)):
    if p not in sys.path:
        sys.path.insert(0, p)

import answers                                              # noqa: E402
import r3_seed as seed                                      # noqa: E402
from test_league_table import mt                            # noqa: E402,F401  (the fixture: the synthetic season)


def _hand_table(through_day):
    """Played / won / drawn / lost / goals per club from the synthetic archive, counting a result when its date is before
    `through_day` (the as-of rule: finished before the cutoff DAY began)."""
    import pandas as pd
    from test_league_table import ARCHIVE
    t = {}
    for d, h, a, hg, ag, *_ in ARCHIVE:
        if hg != hg or pd.to_datetime(d, dayfirst=True) >= pd.Timestamp(through_day):
            continue
        h, a = {"Tottenham": "Spurs"}.get(h, h), {"Tottenham": "Spurs"}.get(a, a)
        for club, gf, ga in ((h, hg, ag), (a, ag, hg)):
            r = t.setdefault(club, {"p": 0, "w": 0, "d": 0, "l": 0, "gf": 0, "ga": 0})
            r["p"] += 1
            r["gf"] += int(gf)
            r["ga"] += int(ga)
            r["w" if gf > ga else "d" if gf == ga else "l"] += 1
    for r in t.values():
        r["pts"] = 3 * r["w"] + r["d"]
        r["gd"] = r["gf"] - r["ga"]
    return t


def _gd(v):
    return f"+{v}" if v > 0 else (f"−{abs(v)}" if v < 0 else "0")


def test_l1_every_cell_equals_a_hand_count(mt):
    out = mt.get_league_table(as_of="2026-09-05")                            # GW1-2 plus the 31 Aug double; the 2 Sep postponement listed
    text = out["direct_reply"]
    want = _hand_table("2026-09-05")
    head, rows = seed.tables(text)[0]
    assert head == ["Pos", "Club", "P", "W", "D", "L", "GF", "GA", "GD", "Pts"]
    ranked = sorted(want, key=lambda c: (-want[c]["pts"], -want[c]["gd"], -want[c]["gf"], c))
    assert [r[1] for r in rows] == ranked
    for k, r in enumerate(rows, 1):
        w = want[r[1]]
        assert r == [str(k), r[1], str(w["p"]), str(w["w"]), str(w["d"]), str(w["l"]), str(w["gf"]), str(w["ga"]), _gd(w["gd"]), str(w["pts"])]
    assert [r[1] for r in rows] == [x["team"] for x in out["table"]]           # the builder's own order


def test_l2_the_as_of_line_and_the_not_counted_fixture(mt):
    out = mt.get_league_table(as_of="2026-09-05")
    lines = out["direct_reply"].split("\n")
    n = out["n_matches_in_table"]
    assert lines[0].startswith(f"**Premier League table 2026-27: {n} results counted, the latest from ") and lines[0].endswith(".**")
    assert lines[1].startswith(f"As of {out['as_of']['cutoff_words']} (the date asked, read as UTC). ")
    assert ("Not counted: 1 fixture dated before the as-of day with no result in the archive (Everton v Spurs, 2026-09-02"
            in out["direct_reply"]) and "The table is incomplete as of that date." in out["direct_reply"]
    early = mt.get_league_table(as_of="2026-08-23")                          # one gameweek in: every club has played once
    assert early["n_matches_in_table"] == 2 and "2 results counted" in early["direct_reply"].split("\n")[0]


def test_l3_no_commentary(mt):
    text = mt.get_league_table(as_of="2026-09-07")["direct_reply"]
    allowed = ("**Premier League table", "As of ", "| ", "|---", "Not counted:", "No result counted yet", "Level clubs are ordered by")
    for ln in text.split("\n"):
        assert ln == "" or ln.startswith(allowed) or ln == answers.TABLE_FOLLOW_UP, ln
    assert text.split("\n")[-1] == "Want me to look at any of these clubs' fixtures?"


def test_l4_after_gw_is_the_next_gameweeks_first_kickoff(mt):
    a = mt.get_league_table(after_gw=2)
    b = mt.get_league_table(as_of="2026-09-05T14:00:00")                     # GW3's first kickoff
    assert a["as_of"]["cutoff"] == b["as_of"]["cutoff"] and [r["team"] for r in a["table"]] == [r["team"] for r in b["table"]]
    assert a["as_of"]["source"] == "after GW2: every result before GW3's first kickoff, from the fixture calendar"
    assert a["direct_reply"].split("\n")[0].startswith("**Premier League table 2026-27 after GW2: ")
    assert "(after GW2: every result before GW3's first kickoff, from the fixture calendar)" in a["direct_reply"].split("\n")[1]
    assert a["as_of"]["cutoff"] == mt.get_league_table()["as_of"]["cutoff"]       # the run's GW3: its default is "after GW2"
    assert "error" in mt.get_league_table(after_gw=2, as_of="2026-09-05")
    assert "error" in mt.get_league_table(after_gw=4)                        # no GW5 in the calendar
    assert "error" in mt.get_league_table(after_gw="two")
    assert mt.get_league_table()["as_of"]["source"].startswith("the latest build's as-of time")   # no gameweek named: as before


def test_l5_one_club_an_empty_table_and_a_draft_turn(mt, monkeypatch):
    one = mt.get_league_table(team="Arsenal")
    assert "direct_reply" not in one and one["form_detail"] is not None
    assert "direct_reply" not in mt.get_league_table(as_of="2010-01-01")
    monkeypatch.setattr(mt, "_draft_turn", lambda: {"user_id": 10001, "draft_key": 800_000_001})
    assert "direct_reply" not in mt.get_league_table(as_of="2026-09-05")
