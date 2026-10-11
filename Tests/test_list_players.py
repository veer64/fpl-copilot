"""list_players (B1-B5, measured 2026-10-03).

Before: `position[:3]` was matched with ILIKE against a column holding GK / DEF / MID / FWD,
so "GKP" found nothing (B1) and "Goalkeeper", "keeper", "Forward" and "striker" were cut to
"Goa", "kee", "For", "str" and found nothing either (B2); `team` was an ILIKE substring, so
"Tottenham" found nothing while "Man" merged Man City and Man Utd into one list (B3); the
25-row cap carried no count, so Hull City's 43 players came back as 25 with no hint (B4);
and every empty case was a bare `[]` with no reason (B5).

The table is seeded here (fpl_news_test), so the numbers are the test's own and do not drift
with the production copy; the live counts are measured separately by direct call.
"""
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
for p in (str(REPO), str(REPO / "squad")):
    if p not in sys.path:
        sys.path.insert(0, p)

import psycopg2                                            # noqa: E402
import db_write                                            # noqa: E402
import model_tools as mt                                    # noqa: E402

TEST_DB = "fpl_news_test"

# Spurs 4, Man City 3, Man Utd 2, Everton 2 (no GK), Hull City 43 (26 MID, so the cap bites)
SEED = ([(1, "Guglielmo Vicario", "GK", "Spurs"), (2, "Micky van de Ven", "DEF", "Spurs"),
         (3, "James Maddison", "MID", "Spurs"), (4, "Dominic Solanke", "FWD", "Spurs"),
         (5, "Erling Haaland", "FWD", "Man City"), (6, "Marc Guehi", "DEF", "Man City"),
         (7, "Phil Foden", "MID", "Man City"),
         (8, "Bryan Mbeumo", "MID", "Man Utd"), (9, "Matthijs de Ligt", "DEF", "Man Utd"),
         (10, "Jordan Pickford", "DEF", "Everton"), (11, "Jack Grealish", "MID", "Everton")]
        + [(100 + i, f"Hull Player {i}", "MID" if i < 26 else "DEF", "Hull City")
           for i in range(43)])


@pytest.fixture
def live(monkeypatch):
    monkeypatch.setenv("DB_NAME", "postgres")
    try:
        admin = db_write.connect()
    except psycopg2.OperationalError as e:
        pytest.skip(f"no local Postgres: {str(e).splitlines()[0]}")
    admin.autocommit = True
    with admin.cursor() as cur:
        cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (TEST_DB,))
        if cur.fetchone() is None:
            cur.execute(f"CREATE DATABASE {TEST_DB}")
    admin.close()
    monkeypatch.setenv("DB_NAME", TEST_DB)
    c = db_write.connect()
    db_write.ensure_schema(c)
    with c.cursor() as cur:
        cur.execute("DELETE FROM players_live")
        cur.executemany(
            "INSERT INTO players_live (element, name, position, team, price_tenths, status, "
            "updated_at) VALUES (%s, %s, %s, %s, %s, 'a', now())",
            [(e, n, p, t, 100 - e) for e, n, p, t in SEED])
    c.commit()
    yield c
    c.close()


def ids(out):
    return [p["player_id"] for p in out["players"]]


# ---- B1, B2: the position word ---------------------------------------------------------
@pytest.mark.parametrize("word,code", [
    ("GK", "GK"), ("GKP", "GK"), ("gkp", "GK"), ("Goalkeeper", "GK"), ("goalkeepers", "GK"),
    ("keeper", "GK"), ("Keepers", "GK"), ("goalie", "GK"),
    ("DEF", "DEF"), ("Defender", "DEF"), ("defenders", "DEF"), ("defence", "DEF"),
    ("defense", "DEF"), ("centre-back", "DEF"), ("center-back", "DEF"),
    ("full-back", "DEF"), ("fullback", "DEF"),
    ("MID", "MID"), ("Midfielder", "MID"), ("midfielders", "MID"), ("midfield", "MID"),
    ("FWD", "FWD"), ("FW", "FWD"), ("Forward", "FWD"), ("forwards", "FWD"),
    ("striker", "FWD"), ("Strikers", "FWD"), ("attacker", "FWD"), ("attackers", "FWD"),
])
def test_every_position_word_reaches_the_stored_code(live, word, code):
    out = mt.list_players(position=word)
    assert "error" not in out, (word, out)
    got = {p["position"] for p in out["players"]}
    assert got == {code}, (word, got)
    assert out["total_matches"] == len([s for s in SEED if s[2] == code]), word


def test_an_unknown_position_is_an_error_listing_what_is_accepted(live):
    out = mt.list_players(position="nonsense")
    assert "error" in out and "nonsense" in out["error"]
    for word in ("goalkeeper", "defender", "midfielder", "forward"):
        assert word in out["error"].lower(), word
    assert "players" not in out


# ---- B3: the club ----------------------------------------------------------------------
def test_an_alias_and_the_stored_name_give_the_same_players(live):
    assert ids(mt.list_players(team="Tottenham")) == ids(mt.list_players(team="Spurs"))
    assert ids(mt.list_players(team="tottenham")) == ids(mt.list_players(team="Spurs"))
    assert len(ids(mt.list_players(team="Spurs"))) == 4


def test_an_ambiguous_club_is_refused_and_never_merged(live):
    out = mt.list_players(team="Man")
    assert "error" in out, out
    assert "Man City" in out["error"] and "Man Utd" in out["error"]
    assert "players" not in out


def test_an_unknown_club_says_no_club_matches(live):
    out = mt.list_players(team="Tottenhm")
    assert "error" in out and "no club matches" in out["error"]
    assert "Tottenhm" in out["error"]


# ---- B4: the cap -----------------------------------------------------------------------
def test_the_cap_reports_the_total_and_the_truncation(live):
    out = mt.list_players(team="Hull City")
    assert out["total_matches"] == 43
    assert out["truncated"] is True
    assert len(out["players"]) == mt.LIST_CAP
    assert "43" in (out["note"] or ""), out["note"]
    small = mt.list_players(team="Spurs")
    assert small["total_matches"] == 4 and small["truncated"] is False


def test_no_filter_counts_the_whole_table(live):
    out = mt.list_players()
    assert out["total_matches"] == len(SEED)
    assert out["truncated"] is True and len(out["players"]) == mt.LIST_CAP


# ---- B5: the empty result --------------------------------------------------------------
def test_an_empty_combination_names_the_filter(live):
    out = mt.list_players(team="Everton", position="GK")      # Everton has no keeper here
    assert out["players"] == [] and out["total_matches"] == 0
    assert out["truncated"] is False
    assert "Everton" in (out["note"] or "") and "GK" in (out["note"] or ""), out["note"]


def test_a_club_and_position_that_do_match_are_unaffected(live):
    out = mt.list_players(team="Spurs", position="keeper")
    assert [p["name"] for p in out["players"]] == ["Guglielmo Vicario"]
    assert out["total_matches"] == 1 and out["truncated"] is False and out["note"] is None


def test_the_count_not_shown_travels_with_the_answer(live):
    """Part 5a of the smoke fixes (2026-10-10): "54 more forwards" was 79 - 25 done by the model.
    The tool says how many it left out, so the reply never has to subtract."""
    out = mt.list_players(team="Hull City")
    assert out["not_shown"] == 43 - mt.LIST_CAP == out["total_matches"] - len(out["players"])
    assert str(out["not_shown"]) in (out["note"] or ""), out["note"]
    small = mt.list_players(team="Spurs")
    assert small["not_shown"] == 0
    assert mt.list_players(team="Spurs", position="GK")["not_shown"] == 0
