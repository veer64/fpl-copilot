"""RAG answer eval, run half (2026-10-25, Prompt B1): the code checks over one runner record and the adapter that turns
eval/rag_eval/answer_questions_v1.json into a workbook eval/run_agent_evals.py can run.

Checks (eval/rag_eval/answer_eval.py), each over the turn's tool log and the RAW reply:
  C1 search_news called (an ambiguous question may skip it when the reply asks which player);
  C2 every cited id (c<digits>) is among the ids search_news returned in that turn, all calls;
  C3 FPL's flag (status / chance, with its time) appears before the first news citation -- player questions only;
  S-nonews zero citations AND says there is no recent news AND gives FPL's flag;
  S-ambig  zero citations AND asks which player AND does not answer for one of them.
The concept examples (de Ligt pass / fail, a no-news fail with an invented citation, an ambiguous fail that picks one
player) are written here; they were not in the repo."""
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
for p in (str(REPO), str(REPO / "eval"), str(REPO / "eval" / "rag_eval")):
    if p not in sys.path:
        sys.path.insert(0, p)

import answer_eval as AE                                  # noqa: E402

SEARCH_DELIGT = {"as_of": "2026-10-25T02:00:00Z", "search_mode": "hybrid", "no_news_for": [], "ambiguous_players": {},
                 "results": [{"id": "c1141", "source": "FPL official", "headline": "De Ligt (MUN, DEF)", "date": "2026-10-13", "about_requested_player": True, "text": "De Ligt (MUN, DEF): flag cleared."},
                             {"id": "c993", "source": "Man Utd official site", "headline": "De Ligt shares positive recovery update", "date": "2026-10-08", "about_requested_player": True, "text": "De Ligt is getting there."}]}
SEARCH_NONEWS = {"as_of": "2026-10-25T02:00:00Z", "search_mode": "hybrid", "no_news_for": ["Van Dijk"], "ambiguous_players": {}, "results": []}
SEARCH_AMBIG = {"as_of": "2026-10-25T02:00:00Z", "search_mode": "dense_only", "no_news_for": [], "ambiguous_players": {"Palmer": ["Cole Palmer (CHE)", "Alex Palmer (IPS)"]}, "results": []}
CARD = {"player_id": 416, "name": "Matthijs de Ligt", "team": "Man Utd", "availability": {"status": "a", "chance_of_playing_next_round": 100, "chance_gameweek": 8}}


def rec(raw, calls):
    return {"id": "rag:1", "raw_reply": raw, "rendered_reply": raw,
            "turns": [{"kind": "question", "calls": [{"tool": t, "input": i, "output": str(o)} for t, i, o in calls]}]}


def q(situation, players=("De Ligt",)):
    return {"situation": situation, "players": list(players),
            "checks": {"C1": True, "C2": True, "C3": situation in ("player_current_news", "name_variant", "conflict", "stale", "no_news"),
                       "S_nonews": situation == "no_news", "S_ambig": situation == "ambiguous"}}


CALLS_DELIGT = [("resolve_player", {"name": "De Ligt"}, {"matches": [{"player_id": 416}]}), ("get_player_card", {"player_id": 416}, CARD),
                ("search_news", {"query": "de ligt", "players": ["De Ligt"]}, SEARCH_DELIGT)]


def test_returned_and_cited_ids_come_from_the_turn():
    r = rec("FPL flag ... c993 and c1141 and again c993", CALLS_DELIGT)
    assert AE.returned_ids(r) == ["c1141", "c993"]
    assert AE.cited(r) == ["c993", "c1141"]


def test_the_de_ligt_pass_answer_passes_c1_c2_c3():
    raw = ("FPL's flag as of 23 Oct 2026: no injury flag on de Ligt, a 100% chance of playing in GW8. "
           "The Man Utd site said on 8 Oct that he shared a positive recovery update c993.")
    out = AE.check_record(rec(raw, CALLS_DELIGT), q("player_current_news"))
    assert out["C1"]["pass"] and out["C2"]["pass"] and out["C3"]["pass"], out
    assert out["S_nonews"]["applicable"] is False and out["S_ambig"]["applicable"] is False


def test_the_de_ligt_fail_answer_fails_c2_and_c3():
    raw = ("De Ligt is close to a return, the club says c999. "
           "FPL lists him as available with a 100% chance, as of 23 Oct 2026.")
    out = AE.check_record(rec(raw, CALLS_DELIGT), q("player_current_news"))
    assert out["C1"]["pass"]
    assert out["C2"]["pass"] is False and out["C2"]["violations"] == ["c999"]
    assert out["C3"]["pass"] is False and "citation" in out["C3"]["why"]


def test_c3_needs_the_flag_with_its_time_before_the_first_citation():
    # the flag without a time does not count
    raw = "FPL shows no flag on him. The club said he is getting there c993."
    out = AE.check_record(rec(raw, CALLS_DELIGT), q("player_current_news"))
    assert out["C3"]["pass"] is False
    # no citation at all: the flag with its time still has to be there
    raw2 = "FPL shows no flag on him, 100% chance of playing, as of 23 Oct 2026. Nothing else to add."
    assert AE.check_record(rec(raw2, CALLS_DELIGT), q("player_current_news"))["C3"]["pass"] is True
    # not a player question
    assert AE.check_record(rec(raw2, CALLS_DELIGT), q("club_news", players=()))["C3"]["applicable"] is False


def test_the_no_news_fail_cites_an_invented_id():
    calls = [("resolve_player", {"name": "Van Dijk"}, {"matches": [{"player_id": 356}]}),
             ("search_news", {"query": "van dijk", "players": ["Van Dijk"]}, SEARCH_NONEWS)]
    raw = "There is no recent news on Van Dijk c777. FPL shows no flag on him as of 23 Oct 2026."
    out = AE.check_record(rec(raw, calls), q("no_news", players=("Van Dijk",)))
    assert out["C2"]["pass"] is False and out["S_nonews"]["pass"] is False and "citation" in out["S_nonews"]["why"]
    good = "I found no recent news on Van Dijk. FPL shows no flag on him, 100% chance of playing, as of 23 Oct 2026."
    assert AE.check_record(rec(good, calls), q("no_news", players=("Van Dijk",)))["S_nonews"]["pass"] is True


def test_the_ambiguous_fail_answers_for_one_player():
    calls = [("search_news", {"query": "palmer", "players": ["Palmer"]}, SEARCH_AMBIG)]
    raw = "Cole Palmer is fit: FPL shows no flag on him, 100% chance of playing, as of 23 Oct 2026."
    out = AE.check_record(rec(raw, calls), q("ambiguous", players=("Palmer",)))
    assert out["S_ambig"]["pass"] is False
    good = "Two players answer to Palmer: Cole Palmer (Chelsea) and Alex Palmer (Ipswich Town). Which one do you mean?"
    out2 = AE.check_record(rec(good, [("resolve_player", {"name": "Palmer"}, {"matches": [{"player_id": 1}, {"player_id": 2}]})]), q("ambiguous", players=("Palmer",)))
    assert out2["S_ambig"]["pass"] is True
    assert out2["C1"]["pass"] is True                     # ambiguous may skip search_news when it asks which player


def test_summary_counts_a_question_as_passing_only_when_both_runs_pass():
    good = rec("FPL flag, 100% chance, as of 23 Oct 2026. The club says c993.", CALLS_DELIGT)
    bad = rec("The club says c999. FPL flag 100% as of 23 Oct 2026.", CALLS_DELIGT)
    qs = {"rag:1": q("player_current_news")}
    table = AE.summarise([dict(good, run=1), dict(bad, run=2)], qs)
    assert table["C2"] == {"passing": 0, "applicable": 1}
    assert table["C1"] == {"passing": 1, "applicable": 1}
    assert table["S_nonews"] == {"passing": 0, "applicable": 0}


def test_the_adapter_writes_a_workbook_the_runner_loads(tmp_path):
    import run_agent_evals as rae
    src = REPO / "eval" / "rag_eval" / "answer_questions_v1.json"
    out = tmp_path / "answer_questions_v1.xlsx"
    rows = AE.to_workbook(src, out)
    loaded = rae.load_questions(out)
    doc = json.loads(src.read_text(encoding="utf-8"))
    assert [q["id"] for q in loaded] == [q["id"] for q in doc["questions"]] == [r["id"] for r in rows]
    assert len(loaded) == 15
    by = {q["id"]: q for q in loaded}
    assert by["rag:27"]["must_call"] == "any"                       # ambiguous may skip search_news
    assert by["rag:6"]["must_call"] == "search_news" and by["rag:29"]["must_call"] == "search_news"
    assert all(q["needs_squad"] == "N" and q["core"] == "Y" for q in loaded)
