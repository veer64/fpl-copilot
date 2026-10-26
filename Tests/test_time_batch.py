"""The time batch (Prompt C, 2026-10-26): four product fixes measured in the clock gates of 25 Oct.

1. Fixtures from now (time:10): "next N / upcoming" counts only fixtures with kickoff > the clock; a gameweek-range
   listing keeps every fixture but marks each kicked-off one "played" (with the score when the actuals hold it).
2. Countdown (time:8): next to the Now line, the FIRST block of the latest user message carries one more line computed
   by code from the clock and the stored next deadline: "Next deadline: GW<n>, <Ddd DD Mon YYYY HH:MM> UTC — in <d> d
   <h> h <m> m"; never in the system block, never in the stored history; no known deadline -> no line.
3. The card names its gameweek (time:4): when FPL's chance is for a gameweek other than the next deadline's, every tool
   that shows the chance adds exactly "FPL's figure is for GW<x> (in progress); FPL has not given a GW<y> figure yet."
   ("(finished)" when that gameweek is finished); equal -> no extra text.
4. The prompt's clock pointer: the one line that said today's date is in the context block now points at the top of
   the latest message.
Offline: fake client, seeded calendar and gameweek state; the card test reads the laptop's players_live for Foden."""
import importlib
import json
import sys
import types
from datetime import datetime, timezone
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
for p in (str(REPO), str(REPO / "squad"), str(REPO / "eval")):
    if p not in sys.path:
        sys.path.insert(0, p)

import fixtures_tool as ft                                 # noqa: E402
import now_context as nc                                   # noqa: E402

UTC = timezone.utc
NOW = datetime(2026, 10, 25, 14, 30, tzinfo=UTC)           # Sunday; Arsenal's GW8 match kicked off Sat 24 Oct 14:00
DL = {8: datetime(2026, 10, 23, 17, 30, tzinfo=UTC), 9: datetime(2026, 10, 31, 11, 0, tzinfo=UTC),
      10: datetime(2026, 11, 7, 13, 30, tzinfo=UTC), 11: datetime(2026, 11, 21, 13, 30, tzinfo=UTC)}
CAL = {("Arsenal", 8): [{"opponent": "Everton", "opponent_id": 9, "home": True, "kickoff": "2026-10-24T14:00:00Z"}],
       ("Arsenal", 9): [{"opponent": "Liverpool", "opponent_id": 14, "home": False, "kickoff": "2026-11-01T16:30:00Z"}],
       ("Arsenal", 10): [{"opponent": "Hull City", "opponent_id": 12, "home": True, "kickoff": "2026-11-07T15:00:00Z"}],
       ("Arsenal", 11): [{"opponent": "Newcastle", "opponent_id": 15, "home": False, "kickoff": "2026-11-21T17:30:00Z"}],
       ("Arsenal", 12): [{"opponent": "Man City", "opponent_id": 13, "home": True, "kickoff": "2026-11-29T16:30:00Z"}],
       ("Everton", 8): [{"opponent": "Arsenal", "opponent_id": 1, "home": False, "kickoff": "2026-10-24T14:00:00Z"}],
       ("Everton", 9): [{"opponent": "Fulham", "opponent_id": 10, "home": True, "kickoff": "2026-10-31T15:00:00Z"}]}


# ---- 1. fixtures from now ------------------------------------------------------------------------------------------------

def _listing(out, team):
    """(gw, opponent, status) rows for one club, from the block shape (one club asked) or the compact rows (all clubs)."""
    if out.get("compact"):
        return [(r["gw"], r.get("opponent"), r.get("status")) for r in out["fixtures"] if r["team"] == team and not r.get("blank")]
    blocks = [b for b in out["fixtures"] if b["team"] == team]
    return [(b["gw"], f.get("opponent"), f.get("status")) for b in blocks for f in b.get("fixtures") or []]


def test_next_three_from_the_clock_skips_the_kicked_off_match_and_reaches_gw11():
    out = ft.build([], CAL, 20, team="Arsenal", gw=None, horizon=3, now=NOW)
    assert _listing(out, "Arsenal") == [(9, "Liverpool", "to come"), (10, "Hull City", "to come"), (11, "Newcastle", "to come")]
    assert out["gameweeks"] == [9, 10, 11]
    assert "Everton" not in json.dumps(out)


def test_a_gameweek_range_listing_keeps_the_kicked_off_match_marked_played_with_its_score():
    out = ft.build([], CAL, 20, team="Arsenal", gw=8, horizon=1, now=NOW, results={("Arsenal", 8, "2026-10-24T14:00:00Z"): "Arsenal 2-1 Everton"})
    rows = _listing(out, "Arsenal")
    assert rows == [(8, "Everton", "played")]
    f = out["fixtures"][0]["fixtures"][0]
    assert f["score"] == "Arsenal 2-1 Everton"


def test_without_a_clock_the_listing_starts_at_the_first_loaded_gameweek_as_before():
    out = ft.build([], CAL, 20, team="Arsenal", gw=None, horizon=3, now=None)
    assert out["gameweeks"] == [8, 9, 10]


def test_all_clubs_listing_counts_only_fixtures_still_to_come_per_club():
    out = ft.build([], CAL, 20, team=None, gw=None, horizon=1, now=NOW)
    assert _listing(out, "Arsenal") == [(9, "Liverpool", "to come")]
    assert _listing(out, "Everton") == [(9, "Fulham", "to come")]


def test_get_fixtures_reads_the_shared_clock_not_the_wall_clock():
    import inspect
    import model_tools as mt
    src = inspect.getsource(mt.get_fixtures)
    assert "datetime.now(" not in src and "nc.clock()" in src or "now_context.clock()" in src


def test_the_horizon_description_says_fixtures_still_to_come(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-used")
    import agent as ag
    ag = importlib.reload(ag)
    tool = next(t for t in ag.tools_schema if t["name"] == "get_fixtures")
    desc = tool["input_schema"]["properties"]["horizon"]["description"]
    assert "still to come" in desc and "from the current one" not in desc


# ---- 2. the countdown line ------------------------------------------------------------------------------------------------

def test_the_countdown_line_is_computed_from_the_clock_and_the_stored_next_deadline():
    assert nc.countdown_line(NOW, deadlines=DL) == "Next deadline: GW9, Sat 31 Oct 2026 11:00 UTC — in 5 d 20 h 30 m"
    assert nc.countdown_line(datetime(2026, 10, 31, 10, 59, tzinfo=UTC), deadlines=DL) == "Next deadline: GW9, Sat 31 Oct 2026 11:00 UTC — in 0 d 0 h 1 m"
    assert nc.countdown_line(datetime(2027, 6, 1, tzinfo=UTC), deadlines=DL) is None        # no deadline left
    assert nc.countdown_line(NOW, deadlines={}) is None                                     # none known


class _Block:
    def __init__(self, type_, **kw):
        self.type = type_
        for k, v in kw.items():
            setattr(self, k, v)


class _Raw:
    def __init__(self, script):
        self.script, self.calls = list(script), []
        self.messages = self

    def create(self, **kw):
        self.calls.append(json.loads(json.dumps(kw, default=lambda b: dict(vars(b)))))
        return self.script.pop(0)


def _resp(text):
    return types.SimpleNamespace(content=[_Block("text", text=text)], stop_reason="end_turn", model="claude-sonnet-4-6",
                                 usage=types.SimpleNamespace(input_tokens=1, output_tokens=1, cache_read_input_tokens=0, cache_creation_input_tokens=0))


def _agent(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-used")
    monkeypatch.setattr(nc, "clock", lambda: NOW)
    monkeypatch.setattr(nc, "_load_deadlines", lambda: dict(DL))
    import agent as ag
    ag = importlib.reload(ag)
    monkeypatch.setattr(ag, "context_block", lambda now=None: "CONTEXT BLOCK (test)\n- Gameweeks: GW8 is in progress; next deadline GW9, Saturday 2026-10-31 11:00 UTC.")
    monkeypatch.setattr(ag, "record_chat_usage", lambda *a, **k: None)
    monkeypatch.setattr(ag, "_citation_check", lambda *a, **k: None)
    monkeypatch.setattr(ag, "_numeric_check", lambda *a, **k: None)
    return ag


def test_the_countdown_rides_with_the_now_line_in_the_first_block_and_nowhere_else(monkeypatch):
    ag = _agent(monkeypatch)
    fake = _Raw([_resp("ok")])
    monkeypatch.setattr(ag, "client", fake)
    _, history = ag.run_agent("how long until the deadline?")
    first = fake.calls[0]["messages"][0]["content"][0]["text"]
    assert first == "- Now: Sunday 2026-10-25 14:30 UTC.\nNext deadline: GW9, Sat 31 Oct 2026 11:00 UTC — in 5 d 20 h 30 m"
    assert "Next deadline:" not in ag.system_text(fake.calls[0]["system"])
    assert "Next deadline:" not in json.dumps(history, default=str) and history[0] == {"role": "user", "content": "how long until the deadline?"}


def test_no_known_deadline_means_the_now_line_alone(monkeypatch):
    ag = _agent(monkeypatch)
    monkeypatch.setattr(nc, "_load_deadlines", lambda: {})
    fake = _Raw([_resp("ok")])
    monkeypatch.setattr(ag, "client", fake)
    ag.run_agent("hi")
    assert fake.calls[0]["messages"][0]["content"][0]["text"] == "- Now: Sunday 2026-10-25 14:30 UTC."


# ---- 3. the card names its gameweek ------------------------------------------------------------------------------------------

def test_fpl_figure_note_only_when_the_chance_gameweek_differs_from_the_next_deadline_gameweek():
    import model_tools as mt
    note = mt.fpl_figure_note(8, now=NOW, deadlines=DL, finished=[1, 2, 3, 4, 5, 6, 7])
    assert note == "FPL's figure is for GW8 (in progress); FPL has not given a GW9 figure yet."
    assert mt.fpl_figure_note(9, now=NOW, deadlines=DL, finished=[1, 2, 3, 4, 5, 6, 7]) is None
    assert mt.fpl_figure_note(7, now=NOW, deadlines=DL, finished=[1, 2, 3, 4, 5, 6, 7]) == "FPL's figure is for GW7 (finished); FPL has not given a GW9 figure yet."
    assert mt.fpl_figure_note(None, now=NOW, deadlines=DL, finished=[]) is None


def test_foden_card_and_the_compare_and_flag_helpers_carry_the_note_at_the_frozen_clock(monkeypatch):
    import model_tools as mt
    try:
        import db_write
        db_write.connect().close()
    except Exception as e:                               # noqa: BLE001
        pytest.skip(f"no local Postgres: {str(e).splitlines()[0]}")
    monkeypatch.setattr(nc, "clock", lambda: NOW)
    monkeypatch.setattr(nc, "_load_deadlines", lambda: dict(DL))
    monkeypatch.setattr(nc, "_load_finished", lambda: [1, 2, 3, 4, 5, 6, 7])
    card = mt.get_player_card(398)                      # Phil Foden: FPL chance 100 for GW8 in the 23 Oct data
    if card.get("availability", {}).get("chance_gameweek") != 8:
        pytest.skip("the laptop data is not the 23 Oct dump (chance gameweek is not 8)")
    want = "FPL's figure is for GW8 (in progress); FPL has not given a GW9 figure yet."
    assert card["availability"]["fpl_figure_note"] == want and card["fpl_figure_note"] == want
    st = mt._player_status([398])
    assert st[398]["fpl_figure_note"] == want
    fl = mt._flags_for([9])                             # Hincapié, doubtful 75% in the 23 Oct data
    if 9 in fl:
        assert fl[9]["fpl_figure_note"] == want


# ---- 4. the prompt pointer ---------------------------------------------------------------------------------------------------

def test_the_prompt_points_at_the_top_of_the_latest_message_for_the_date():
    text = (REPO / "prompts" / "system_prompt.md").read_text(encoding="utf-8")
    assert "the clock line at the top of your latest message (today's date and weekday" in text
    assert "context block at the top of this prompt (today's date" not in text
