"""The "now" context block (now_context.py, 2026-10-08): built from seeded data, every line
checked; a piece that cannot be built is left out and named; the whole block stays under
MAX_CHARS; and it moves when the clock moves. Frozen clocks, seeded data, no database, no
network, no snapshot read: every loader is bypassed by passing the pieces in.

The one integration test at the end drives agent.run_agent with a scripted client and
proves the block is prepended to the system prompt on every API call of a turn, and rebuilt
between turns.
"""
import sys
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
for p in (str(REPO), str(REPO / "squad"), str(REPO / "eval")):
    if p not in sys.path:
        sys.path.insert(0, p)

import dispatch_policy as dp                               # noqa: E402
import now_context as nc                                   # noqa: E402

UTC = timezone.utc
DL = {5: datetime(2026, 9, 18, 17, 30, tzinfo=UTC), 6: datetime(2026, 10, 10, 10, 0, tzinfo=UTC),
      7: datetime(2026, 10, 17, 10, 0, tzinfo=UTC), 8: datetime(2026, 10, 23, 17, 30, tzinfo=UTC)}
CLUBS = ["Arsenal", "Aston Villa", "Bournemouth", "Brentford", "Brighton", "Chelsea", "Coventry City",
         "Crystal Palace", "Everton", "Fulham", "Hull City", "Ipswich Town", "Leeds", "Liverpool",
         "Man City", "Man Utd", "Newcastle", "Nott'm Forest", "Spurs", "Sunderland"]
NOW = datetime(2026, 10, 8, 18, 42, tzinfo=UTC)            # a Thursday between GW5 and GW6


def seeded(now=NOW, **over):
    kw = dict(deadlines=DL, finished=[1, 2, 3, 4, 5], clubs=CLUBS, dispatch_state={}, policy=dp)
    kw.update(over)
    return nc.build(now, **kw)


# ---------------------------------------------------------------- the lines
def test_the_block_states_today_with_its_weekday():
    text, omitted = seeded()
    assert text.startswith(nc.TITLE)
    assert "- Now: Thursday 2026-10-08 18:42 UTC." in text
    assert omitted == {}, omitted


def test_the_gameweek_line_between_deadlines():
    text, _ = seeded()
    assert ("- Gameweeks: GW5 is the last finished gameweek; no gameweek is in progress; "
            "next deadline GW6, Saturday 2026-10-10 10:00 UTC.") in text


def test_the_gameweek_line_while_a_gameweek_is_being_played():
    text, _ = seeded(now=datetime(2026, 10, 11, 15, 0, tzinfo=UTC))        # after GW6's deadline, GW6 not final
    assert ("GW5 is the last finished gameweek; GW6 is in progress (deadline passed, not yet final); "
            "next deadline GW7, Saturday 2026-10-17 10:00 UTC.") in text


def test_the_schedule_comes_from_the_policy_constants_not_a_copy():
    text, _ = seeded()
    assert (f"- Model updates: The model rebuilds nightly at {dp.NIGHTLY_HOUR_UTC:02d}:00 UTC once the previous "   # Part C: "updates"
            "gameweek is confirmed, and on deadline day at 90, 30 and 10 minutes before the deadline.") in text
    leads = sorted(hi for _, _, hi in dp.DEADLINE_WINDOWS)
    assert leads == [10, 30, 90]                     # the words above are built from these


def test_the_next_run_is_the_dispatchers_promise_when_the_volume_holds_one():
    state = {"expected_next": {"kind": "t90", "slot": "t90:GW6", "gw": 6, "at": "2026-10-10T08:30:00Z",
                               "condition": None, "grace_min": 35}}
    text, _ = seeded(dispatch_state=state)
    assert "Next expected update (the dispatcher's promise): the update 90 minutes before the deadline, Saturday 2026-10-10 08:30 UTC." in text   # Part C


def test_the_next_run_is_derived_from_the_policy_when_there_is_no_promise():
    # an empty state at Thursday 18:42Z: the policy says today's nightly (11:00Z) has not run, so it is due now
    text, omitted = seeded()
    assert "Next expected update (by the schedule): the nightly update, due now (Thursday 2026-10-08 18:42 UTC)." in text   # Part C
    assert "next_run" not in omitted
    # with today's nightly recorded as done, the promise is tomorrow's
    done = {"slots": {"nightly:2026-10-08": {"kind": "nightly", "status": "SUCCESS", "attempts": 1}}}
    text, _ = seeded(dispatch_state=done)
    assert "Next expected update (by the schedule): the nightly update, Friday 2026-10-09 11:00 UTC." in text   # Part C


def test_a_conditional_promise_is_said_in_words():
    state = {"expected_next": {"kind": "post_ingest", "slot": "post_ingest:GW6", "gw": 7, "at": None,
                               "condition": "GW6 confirmed by FPL and ingested (ticks 00:17/06:17/12:17/18:17Z)",
                               "grace_min": None, "certain_kind": "t90", "certain_at": "2026-10-17T08:30:00Z"}}
    text, _ = seeded(dispatch_state=state)
    assert ("Next expected update (the dispatcher's promise): once GW6 confirmed by FPL and loaded "          # Part D G3: a stored promise's old wording is said in today's words
            "(checked at 00:17/06:17/12:17/18:17Z); in any case Saturday 2026-10-17 08:30 UTC (the update 90 minutes before the deadline).") in text


def test_the_twenty_clubs_are_listed_from_the_snapshot():
    text, _ = seeded()
    assert "- Premier League clubs this season (20): Arsenal, Aston Villa, " in text
    assert "Coventry City" in text and text.rstrip().endswith("Sunderland.")


# ---------------------------------------------------------------- omissions, size, the clock
def test_a_piece_that_cannot_be_built_is_left_out_and_named():
    def boom():
        raise OSError("snapshot unreadable")
    text, omitted = seeded(deadlines={}, clubs=[])
    assert "next deadline" not in text and "Premier League clubs" not in text
    assert "GW5 is the last finished gameweek" in text            # the pieces that could be built stay
    assert set(omitted) >= {"deadlines", "clubs"}, omitted
    assert "- Now:" in text


def test_no_finished_gameweek_yet_is_said_not_guessed():
    text, omitted = seeded(finished=[])
    assert "no gameweek has finished yet" in text
    assert "finished_gameweeks" not in omitted


def test_the_block_never_exceeds_the_cap_even_with_absurd_club_names():
    clubs = [f"Club {i} " + "X" * 80 for i in range(20)]
    text, omitted = seeded(clubs=clubs)
    assert len(text) <= nc.MAX_CHARS
    assert omitted.get("clubs_truncated")
    text2, omitted2 = seeded()
    assert len(text2) <= nc.MAX_CHARS and "clubs_truncated" not in omitted2
    assert len(text2) < 900, len(text2)              # the real block has room to spare


def test_the_block_changes_when_the_clock_changes():
    a, _ = seeded(now=NOW)
    b, _ = seeded(now=NOW + timedelta(days=2))         # Saturday after GW6's deadline, GW6 in progress
    c, _ = seeded(now=NOW + timedelta(minutes=1))
    assert a != b and "GW6 is in progress" in b and "GW6 is in progress" not in a
    assert a != c and "18:43 UTC" in c


def test_the_loaders_are_the_shared_readers_not_second_copies():
    """The deadline table, the finished list and the clubs come through the readers the tools already
    use, so the block can never disagree with a tool answer about a date or a club."""
    import model_tools as mt
    import fixtures_tool as ft
    assert nc._load_deadlines.__code__.co_names and "_gw_deadline_times" in nc._load_deadlines.__code__.co_names
    assert "_actuals_master" in nc._load_finished.__code__.co_names
    assert "_team_names" in nc._load_clubs.__code__.co_names
    assert "_dispatch_state" in nc._load_dispatch_state.__code__.co_names
    assert hasattr(mt, "_gw_deadline_times") and hasattr(ft, "_team_names")


# ---------------------------------------------------------------- the agent
class _Block:
    def __init__(self, type_, **kw):
        self.type = type_
        for k, v in kw.items():
            setattr(self, k, v)


class _Resp:
    def __init__(self, content, stop_reason):
        self.content, self.stop_reason = content, stop_reason


class _Fake:
    """Turn 1 calls a tool, turn 2 replies; records every create() keyword set."""

    def __init__(self):
        self.calls, self.turn = [], 0

    def create(self, **kw):
        self.calls.append(kw)
        self.turn += 1
        if self.turn % 2 == 1:
            return _Resp([_Block("tool_use", name="get_picks", input={}, id=f"t{self.turn}")], "tool_use")
        return _Resp([_Block("text", text="done")], "end_turn")


def test_the_agent_prepends_a_fresh_block_to_the_system_prompt_every_turn(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-used")
    import importlib
    import agent as ag
    importlib.reload(ag)
    clock = {"now": NOW}
    monkeypatch.setattr(ag, "context_block", lambda: nc.build(clock["now"], deadlines=DL, finished=[1, 2, 3, 4, 5],
                                                                 clubs=CLUBS, dispatch_state={}, policy=dp)[0])
    fake = _Fake()
    monkeypatch.setattr(ag, "client", types.SimpleNamespace(messages=fake))
    monkeypatch.setitem(ag.available_functions, "get_picks", lambda **kw: {"captain": "X"})
    _, messages = ag.run_agent("q1")
    assert len(fake.calls) == 2
    for c in fake.calls:                                                   # both API calls of the turn
        s = ag.system_text(c["system"])                                   # one text block since 2026-10-19
        assert s.startswith(nc.TITLE) and s.endswith(ag.SYSTEM_PROMPT)
        assert "Thursday 2026-10-08 18:42 UTC" in s
    clock["now"] = NOW + timedelta(days=2)
    ag.run_agent("q2", messages)
    assert "GW6 is in progress" in ag.system_text(fake.calls[-1]["system"])     # rebuilt for the second turn
    assert "GW6 is in progress" not in ag.system_text(fake.calls[0]["system"])


def test_a_block_that_fails_to_build_does_not_take_the_turn_down(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-used")
    import importlib
    import agent as ag
    importlib.reload(ag)

    def boom():
        raise RuntimeError("volume gone")
    monkeypatch.setattr(ag, "context_block", boom)
    fake = _Fake()
    monkeypatch.setattr(ag, "client", types.SimpleNamespace(messages=fake))
    monkeypatch.setitem(ag.available_functions, "get_picks", lambda **kw: {"captain": "X"})
    answer, _ = ag.run_agent("q")
    assert answer == "done"
    assert ag.system_text(fake.calls[0]["system"]) == ag.SYSTEM_PROMPT   # the prompt alone, never a half block
