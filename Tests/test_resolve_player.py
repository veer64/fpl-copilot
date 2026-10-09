"""Name resolution for the agent's resolve_player (2026-10-03).

The candidates below are the REAL rows of the 2026-27 data (element id, web_name and
full name as players_live and the bootstrap snapshot hold them), so these tests pin
what the live squad actually looks like:

  - FPL's display name is not the stored full name ("B.Fernandes" / "Bruno Borges
    Fernandes"), so a user typing "Bruno Fernandes" matched nothing.
  - Accents are stored and users do not type them ("Ødegaard", "Gyökeres", "Guéhi",
    "João Pedro").
  - Two players share a web_name ("Palmer" x2, "James" x2), so a single name can be
    genuinely ambiguous.
  - A substring match put Alisson and Robertson under "Son".

No database and no network: the ranker is pure, and the two resolve_player tests
monkeypatch its two reads.
"""
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
for p in (str(REPO), str(REPO / "squad")):
    if p not in sys.path:
        sys.path.insert(0, p)

import model_tools as mt                                   # noqa: E402
import player_names as pn                                  # noqa: E402


def cand(i, web, first, second, team):
    return {"id": i, "web_name": web, "first_name": first, "second_name": second,
            "team": team, "short": team[:3].upper()}


SQUAD = [
    cand(426, "B.Fernandes", "Bruno Borges", "Fernandes", "Man Utd"),
    cand(525, "Fernandes", "Mateus", "Fernandes", "Spurs"),
    cand(15, "Ødegaard", "Martin", "Ødegaard", "Arsenal"),
    cand(25, "Gyökeres", "Viktor", "Gyökeres", "Arsenal"),
    cand(388, "Guéhi", "Marc", "Guéhi", "Man City"),
    cand(165, "João Pedro", "João Pedro", "Junqueira de Jesus", "Chelsea"),
    cand(119, "Costinha", "João Pedro", "Loureiro da Costa", "Brighton"),
    cand(397, "Semenyo", "Antoine", "Semenyo", "Man City"),
    cand(154, "Palmer", "Cole", "Palmer", "Chelsea"),
    cand(301, "Palmer", "Alex", "Palmer", "Ipswich Town"),
    cand(142, "James", "Reece", "James", "Chelsea"),
    cand(343, "James", "Daniel", "James", "Leeds"),
    cand(60, "Hill", "James", "Hill", "Bournemouth"),
    cand(480, "Gibbs-White", "Morgan", "Gibbs-White", "Nott'm Forest"),
    cand(350, "A.Becker", "Alisson", "Becker", "Liverpool"),
    cand(362, "Robertson", "Andrew", "Robertson", "Spurs"),
]
IDS = {c["id"]: c for c in SQUAD}


def ranked_ids(name, rank=None):
    out = pn.rank_matches(name, SQUAD)
    return [c["id"] for r, c in out if rank is None or r == rank]


def test_the_display_name_resolves_even_though_the_stored_name_is_longer():
    assert ranked_ids("Bruno Fernandes") == [426]


def test_accents_fold_both_ways():
    for typed, want in [("Odegaard", 15), ("Ødegaard", 15), ("Gyokeres", 25),
                        ("Gyökeres", 25), ("Guehi", 388), ("Guéhi", 388)]:
        assert ranked_ids(typed)[0] == want, typed


def test_joao_pedro_prefers_the_player_fpl_calls_joao_pedro():
    assert ranked_ids("Joao Pedro", rank=0) == [165]
    assert 119 in ranked_ids("Joao Pedro")          # the other one still matches, lower


def test_a_hyphen_is_a_space():
    assert ranked_ids("Gibbs White") == [480]
    assert ranked_ids("Gibbs-White") == [480]


def test_a_short_word_does_not_match_inside_another_name():
    got = ranked_ids("Son")
    assert 350 not in got and 362 not in got, got      # not Alisson, not Robertson


def test_a_prefix_needs_four_letters_and_a_single_word():
    assert 480 in ranked_ids("Gibb")                   # prefix of Gibbs-White
    assert ranked_ids("Gib") == []                      # three letters is not enough


def test_two_players_share_a_display_name():
    assert sorted(ranked_ids("Palmer", rank=0)) == [154, 301]
    assert sorted(ranked_ids("James", rank=0)) == [142, 343]
    assert 60 in ranked_ids("James")                    # James Hill matches, lower


def test_an_unknown_name_matches_nothing():
    assert ranked_ids("Mbappe") == []


# ---- resolve_player, with its two reads replaced ---------------------------------
def _patch(monkeypatch, rows=None):
    """players_live rows and the web_name map, from the fixture squad."""
    live = rows if rows is not None else [
        {"element": c["id"], "name": f"{c['first_name']} {c['second_name']}".strip(),
         "position": "MID", "team": c["team"], "price_tenths": 50, "status": "a"}
        for c in SQUAD]
    monkeypatch.setattr(mt, "_q", lambda sql, params=None: live)
    monkeypatch.setattr(mt, "_web_names", lambda: {c["id"]: c["web_name"] for c in SQUAD})
    return live


def test_resolve_player_returns_the_new_shape(monkeypatch):
    _patch(monkeypatch)
    out = mt.resolve_player("Bruno Fernandes")
    assert set(out) >= {"matches", "total_matches", "truncated", "ambiguous", "note"}
    assert [m["player_id"] for m in out["matches"]] == [426]
    assert out["total_matches"] == 1 and out["truncated"] is False
    assert out["ambiguous"] is False


def test_several_players_in_the_top_rank_are_reported_ambiguous(monkeypatch):
    _patch(monkeypatch)
    for name, n_top in [("Palmer", 2), ("James", 2)]:
        out = mt.resolve_player(name)
        assert out["ambiguous"] is True, name
        assert out["total_matches"] >= n_top, (name, out["total_matches"])
        assert all("player_id" not in m for m in out["matches"]) and out["action"] == "ask the user which one"   # the lock


def test_a_club_is_a_preference_and_a_mismatch_is_explained(monkeypatch):
    _patch(monkeypatch)
    out = mt.resolve_player("Semenyo", club="Bournemouth")
    assert [m["player_id"] for m in out["matches"]] == [397]
    assert "Man City" in (out["note"] or ""), out["note"]
    out = mt.resolve_player("Palmer", club="Chelsea")
    assert [m["player_id"] for m in out["matches"]] == [154]


def test_no_match_carries_suggestions_not_an_exception(monkeypatch):
    _patch(monkeypatch)
    out = mt.resolve_player("Mbappe")
    assert out["matches"] == [] and out["total_matches"] == 0
    assert out["note"] and isinstance(out["suggestions"], list)


def test_truncation_is_flagged(monkeypatch):
    many = [{"element": 1000 + i, "name": f"Jamie Test{i}", "position": "MID",
             "team": "Arsenal", "price_tenths": 40, "status": "a"} for i in range(9)]
    monkeypatch.setattr(mt, "_q", lambda sql, params=None: many)
    monkeypatch.setattr(mt, "_web_names", lambda: {1000 + i: "Jamie" for i in range(9)})
    out = mt.resolve_player("Jamie")
    assert out["total_matches"] == 9
    assert out["truncated"] is True and len(out["matches"]) == mt.RESOLVE_CAP
