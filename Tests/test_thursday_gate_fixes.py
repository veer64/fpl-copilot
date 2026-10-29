"""Thursday gate fixes (2026-10-15).

F13 -- a flag applies only to the gameweek it names. FPL's chance of playing is for its next round, so a row in a plan
for a LATER gameweek must not repeat it as if it were that gameweek's figure: the batch 3 gate's one CONFIRMED new M3a
FAIL (propose_transfers:1) had the agent calling Collins and Foden "unavailable" for GW7 while their label said GW6.
The prompt says it in one sentence, and _with_flags labels such rows "latest FPL flag (for GW<n>, as of <date>)" at the
source; rows for the flag's own gameweek, or with no gameweek, keep the flag's words exactly.

F14 -- get_prediction names the player whose prediction it returns. After an ambiguous "Palmer" (the 2026-10-09 lock
gives no ids), the agent called get_prediction(328) with an id no tool had given it; the output named only the club,
so Pascal Struijk's numbers went out as "Cole Palmer at Brighton" (2026-10-14, resolve_player:10). On 2026-10-09 the
same invented-id slip was caught because get_player_card names the player."""
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for p in (str(ROOT), str(ROOT / "squad"), str(ROOT / "eval")):
    if p not in sys.path:
        sys.path.insert(0, p)

import model_tools as mt  # noqa: E402

F13_SENTENCE = ("A flag applies only to the gameweek it names; for later gameweeks call it the latest flag, "
                "not a forecast.")
NOW = datetime(2026, 10, 15, 11, 1, 55, tzinfo=timezone.utc)
OLD = datetime(2026, 9, 29, 11, 1, 51, tzinfo=timezone.utc)


def _flag(gw, as_of=NOW, chance=75):
    return {532: {"name": "Daniel Ballard", "status": "d", "status_word": "doubtful", "chance": chance,
                  "news": "Knock - 75% chance of playing", "as_of": as_of, "gw": gw,
                  "chance_words": mt.chance_words(chance, as_of, gw)}}


def _plan():
    """propose_transfers' shape: the plan's own gameweek at the top, this deadline's rows, then later steps."""
    return {"gw": 7,
            "this_deadline": {"transfers": [{"out": "Victor Lindelöf", "out_id": 37, "in": "Daniel Ballard", "in_id": 532}],
                              "xi": [{"player_id": 532, "name": "Daniel Ballard"}]},
            "later_steps_indicative": [{"horizon_step": 1, "gw": 8, "transfers": [
                {"out": "Daniel Ballard", "out_id": 532, "in": "Jarrad Branthwaite", "in_id": 2}]}]}


def test_f13_the_prompt_says_a_flag_applies_only_to_the_gameweek_it_names():
    text = (ROOT / "prompts" / "system_prompt.md").read_text(encoding="utf-8")
    assert F13_SENTENCE in text


def test_f13_latest_flag_words():
    assert mt.latest_flag_words(75, NOW, 7) == "latest FPL flag (for GW7, as of Thu 15 Oct 2026): chance of playing 75%"
    assert mt.latest_flag_words(0, OLD, 6) == "latest FPL flag (for GW6, as of Tue 29 Sep 2026): chance of playing 0%"
    assert mt.latest_flag_words(None, NOW, 7) is None


def test_f13_plan_rows_for_later_gameweeks_carry_the_latest_flag_label(monkeypatch):
    monkeypatch.setattr(mt, "_flags_for", lambda ids: _flag(7))
    out = mt._with_flags(_plan())
    now_row = out["this_deadline"]["transfers"][0]
    assert now_row["chance_words_in"] == "chance of playing in GW7: 75%, FPL as of Thu 15 Oct 2026"
    assert out["this_deadline"]["xi"][0]["chance_words"] == "chance of playing in GW7: 75%, FPL as of Thu 15 Oct 2026"
    later = out["later_steps_indicative"][0]["transfers"][0]
    assert later["chance_words_out"] == "latest FPL flag (for GW7, as of Thu 15 Oct 2026): chance of playing 75%"
    assert later["status_word_out"].startswith("doubtful (latest FPL flag: for GW") and later["chance_out"] == 75   # the flag itself is kept; F21 (2026-10-22): the later row's word carries the flag's gameweek


def test_f13_a_flag_for_an_earlier_gameweek_is_the_latest_flag_on_every_plan_row(monkeypatch):
    monkeypatch.setattr(mt, "_flags_for", lambda ids: _flag(6, OLD, 0))
    out = mt._with_flags(_plan())
    assert out["this_deadline"]["transfers"][0]["chance_words_in"] == \
        "latest FPL flag (for GW6, as of Tue 29 Sep 2026): chance of playing 0%"
    assert out["later_steps_indicative"][0]["transfers"][0]["chance_words_out"] == \
        "latest FPL flag (for GW6, as of Tue 29 Sep 2026): chance of playing 0%"


def test_f13_rows_with_no_gameweek_keep_the_flag_words(monkeypatch):
    monkeypatch.setattr(mt, "_flags_for", lambda ids: _flag(7))
    out = mt._with_flags({"players": [{"player_id": 532, "name": "Daniel Ballard"}]})
    assert out["players"][0]["chance_words"] == "chance of playing in GW7: 75%, FPL as of Thu 15 Oct 2026"


def _prediction_fakes(monkeypatch, lookup_row):
    run = {"run_id": 40, "gw": 7, "season": "2026-27", "status": "SUCCESS"}
    monkeypatch.setattr(mt, "_latest_run", lambda gw=None, any_status=False: dict(run))
    monkeypatch.setattr(mt, "_run_meta", lambda r, config=None: {"run_id": 40, "gw": 7})
    monkeypatch.setattr(mt, "_table_columns", lambda t, ttl=None: set())
    monkeypatch.setattr(mt, "_run_horizon", lambda r: (7, 12))
    monkeypatch.setattr(mt, "_availability_for", lambda els: {})
    monkeypatch.setattr(mt, "_quantile_block", lambda rows: {"computed": False})

    def fake_q(sql, params=None):
        if "model_predictions" in sql:
            return [{"gw": 7, "e_points": 2.4, "horizon_step": 0}]
        return [lookup_row]
    monkeypatch.setattr(mt, "_q", fake_q)


def test_f14_get_prediction_names_the_player_it_answers_for(monkeypatch):
    _prediction_fakes(monkeypatch, {"name": "Pascal Struijk", "team": "Brighton"})
    out = mt.get_prediction(328, gw=7)
    assert out["player_id"] == 328 and out["name"] == "Pascal Struijk" and out["team"] == "Brighton"
    keys = list(out)
    assert keys.index("name") == keys.index("player_id") + 1, keys     # whose numbers these are, next to the id


def test_f14_a_failed_name_lookup_never_breaks_the_prediction(monkeypatch):
    _prediction_fakes(monkeypatch, {"team": "Brighton"})              # the old lookup's row shape
    out = mt.get_prediction(328, gw=7)
    assert "name" not in out and out["team"] == "Brighton" and out["predictions"]
