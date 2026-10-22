"""Fix batch #4 (2026-10-22), agent-side fixes, failing tests first:

  F20 a flagged player the user names is forced in at once: the player card carries `force_in` (a d / i / s player
      "can be forced into a squad build or a transfer plan ... never ask first"; a u / n player "cannot be locked ...
      ban him instead"), the two build descriptions and prompt line 7 name the ONLY refusal (FPL status u / n,
      `available: false`); u / n stay refused by the lock check.
  F21 every player card names the gameweek of its availability line inside flag_dates, the sentence the agent copies
      ("No FPL flag for GW7, last checked 17 Oct 2026" / "FPL flag set 27 Sep 2026 (for GW7), last checked ...");
      a later-gameweek plan row's status word carries the flag's gameweek ("doubtful (latest FPL flag: for GW7, ...)").
  F22 get_prediction_history leads with the LATEST move (the newest two builds) and points compare_runs at it; the
      all-time biggest move stays, second (the 19 Oct smoke compared runs 37 -> 38 because biggest_move named them).
"""
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
for p in (str(REPO), str(REPO / "squad"), str(REPO / "eval")):
    if p not in sys.path:
        sys.path.insert(0, p)

import model_tools as mt                                   # noqa: E402

UTC = timezone.utc
AS_OF = "2026-10-17 09:51:19.918536+00:00"


# ================================================================ F21: the gameweek inside flag_dates
def test_f21_flag_dates_words_carry_the_gameweek_of_the_flag():
    assert mt.flag_dates_words("2026-09-27T10:00:00Z", AS_OF, True, gw=7) == "FPL flag set 27 Sep 2026 (for GW7), last checked 17 Oct 2026"
    assert mt.flag_dates_words(None, AS_OF, True, gw=7) == "FPL flag (for GW7), last checked 17 Oct 2026"
    assert mt.flag_dates_words("2026-09-13T17:00:09Z", AS_OF, False, gw=7) == "No FPL flag for GW7, last checked 17 Oct 2026"
    # without a gameweek the F18 words are unchanged
    assert mt.flag_dates_words("2026-10-10T13:30:08Z", AS_OF, True) == "FPL flag set 10 Oct 2026, last checked 17 Oct 2026"
    assert mt.flag_dates_words("2026-09-13T17:00:09Z", AS_OF, False) == "last checked 17 Oct 2026"


def test_f21_the_card_names_the_gameweek_in_flag_dates_fit_or_flagged():
    try:
        card = mt.get_player_card(398)                                          # Foden
    except Exception as e:                                                       # noqa: BLE001
        pytest.skip(f"no local data: {type(e).__name__}: {str(e)[:80]}")
    if "error" in card or card.get("availability", {}).get("chance_gameweek") is None:
        pytest.skip("no card / no next-round gameweek on this machine's data")
    gw = card["availability"]["chance_gameweek"]
    assert f"GW{gw}" in card["flag_dates"] and card["flag_dates"] == card["availability"]["flag_dates"]
    if card["availability"]["status"] == "a":
        assert card["flag_dates"].startswith(f"No FPL flag for GW{gw}")
    else:
        assert f"(for GW{gw})" in card["flag_dates"]


# ================================================================ F22: the latest move first
def _history(monkeypatch, rows):
    monkeypatch.setattr(mt, "_q", lambda sql, params=None: rows)
    monkeypatch.setattr(mt, "_player_name", lambda pid: "Erling Haaland")
    monkeypatch.setattr(mt, "_player_meta", lambda ids: {411: {"position": "FWD", "team": "Man City"}})
    monkeypatch.setattr(mt, "_availability_for", lambda ids: {})


def _row(run_id, kind, day, e, terms=True):
    return {"run_id": run_id, "kind": kind, "slot": None, "finished_at": datetime(2026, 10, day, 11, 0, tzinfo=UTC),
            "cutoff": 6, "horizon_step": 1, "e_points": e, "p_start": 0.9, "e_minutes": 80.0, "terms_recorded": terms}


def test_f22_latest_move_is_the_newest_pair_and_comes_before_the_biggest(monkeypatch):
    _history(monkeypatch, [_row(37, "t10", 10, 6.8), _row(38, "post_ingest", 13, 6.6), _row(41, "nightly", 16, 6.6), _row(44, "t10", 17, 6.7)])
    out = mt.get_prediction_history(411, 8)
    latest, biggest = out["latest_move"], out["biggest_move"]
    assert (latest["from_run_id"], latest["to_run_id"], latest["change"]) == (41, 44, 0.1)
    assert (biggest["from_run_id"], biggest["to_run_id"], biggest["change"]) == (37, 38, -0.2)
    assert latest["explain_with"] == {"tool": "compare_runs", "player_id": 411, "gw": 8, "run_id_a": 41, "run_id_b": 44}
    keys = list(out)
    assert keys.index("latest_move") < keys.index("biggest_move")
    assert out["note"].index("latest") < out["note"].index("biggest")
    assert "latest_move" in out["note"] and "biggest_move" in out["note"]


def test_f22_an_unchanged_latest_pair_is_still_the_latest_move(monkeypatch):
    _history(monkeypatch, [_row(37, "t10", 10, 6.8), _row(38, "post_ingest", 13, 6.6), _row(41, "nightly", 16, 6.6)])
    out = mt.get_prediction_history(411, 8)
    assert (out["latest_move"]["from_run_id"], out["latest_move"]["to_run_id"], out["latest_move"]["change"]) == (38, 41, 0.0)
    assert out["biggest_move"]["from_run_id"] == 37


def test_f22_the_no_breakdown_lead_describes_the_latest_move(monkeypatch):
    _history(monkeypatch, [_row(3, "deadline", 4, 4.12, terms=False), _row(9, "nightly", 15, 3.71), _row(12, "nightly", 16, 3.95, terms=False)])
    out = mt.get_prediction_history(411, 8)
    assert out["latest_move"]["explainable"] is False
    assert out["summary_plain"].startswith(mt.NO_WHY) and "3.7" in out["summary_plain"] and "4.0" in out["summary_plain"]
    assert "4.1" not in out["summary_plain"]                                     # the older, bigger move is not the lead



# ================================================================ F20: a named force-in builds at once
def test_f20_the_card_says_a_flagged_player_can_be_forced_in_and_a_departed_one_cannot():
    try:
        semenyo, watkins, fit = mt.get_player_card(397), mt.get_player_card(55), mt.get_player_card(398)
    except Exception as e:                                                       # noqa: BLE001
        pytest.skip(f"no local data: {type(e).__name__}: {str(e)[:80]}")
    if semenyo.get("status") not in ("i", "d", "s") or watkins.get("status") not in ("u", "n"):
        pytest.skip("this machine's data no longer has Semenyo flagged / Watkins departed")
    assert "forced_availability_warning" in semenyo["force_in"] and "at once" in semenyo["force_in"] and "ask" in semenyo["force_in"]
    assert semenyo["availability"]["force_in"] == semenyo["force_in"]
    assert "ban" in watkins["force_in"] and "cannot be locked" in watkins["force_in"]
    assert "force_in" not in fit and "force_in" not in fit["availability"]


def test_f20_the_descriptions_and_the_prompt_name_the_only_refusal_precisely():
    import agent
    desc = {t["name"]: t["description"] for t in agent.tools_schema}
    for name in ("build_squad_from_scratch", "propose_transfers"):
        assert "a player who cannot play for his club cannot be locked" not in desc[name]
        assert "status u or n" in desc[name] and "`available: false`" in desc[name] and "forced_availability_warning" in desc[name]
    prompt = (REPO / "prompts" / "system_prompt.md").read_text(encoding="utf-8")
    assert "the tool refuses only a player who cannot play for his club" not in prompt
    assert "never an injury flag" in prompt and "the user's named force-in wins over the flag" in prompt


def test_f20_u_and_n_stay_refused_by_the_lock_check():
    try:
        out = mt.optimise(lock_player_ids=[55])                                    # Watkins: status u
    except Exception as e:                                                       # noqa: BLE001
        pytest.skip(f"no local data: {type(e).__name__}: {str(e)[:80]}")
    assert out.get("error_kind") == "locked_player_unavailable", out.get("error")


# ================================================================ F21 (later rows): the gameweek in the copied word
def test_f21_a_later_gameweek_row_carries_the_flags_gameweek_in_its_status_word(monkeypatch):
    monkeypatch.setattr(mt, "_flags_for", lambda ids: {367: {"name": "Cody Gakpo", "status": "d", "status_word": "doubtful", "chance": 25,
                                                             "news": "Thigh injury", "as_of": "2026-10-17 09:51:19+00:00", "gw": 7,
                                                             "chance_words": "chance of playing in GW7: 25%, FPL as of 17 Oct 2026"}})
    out = {"gw": 7, "this_deadline": {"transfers": [{"out": "Cody Gakpo", "out_id": 367, "in": "X", "in_id": 1}]},
           "later_steps_indicative": [{"gw": 11, "transfers": [{"out": "Cody Gakpo", "out_id": 367, "in": "Sávio", "in_id": 403}]}]}
    out = mt._with_flags(out)
    now_row = out["this_deadline"]["transfers"][0]
    later_row = out["later_steps_indicative"][0]["transfers"][0]
    assert now_row["status_word_out"] == "doubtful" and now_row["chance_words_out"].startswith("chance of playing in GW7")
    assert later_row["status_word_out"] == "doubtful (latest FPL flag: for GW7, as of 17 Oct 2026)"
    assert later_row["chance_words_out"].startswith("latest FPL flag (for GW7")


