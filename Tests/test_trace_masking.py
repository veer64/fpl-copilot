"""Prompt P7 Part 4 (2026-11-01): no email address or phone number leaves for Langfuse. With LANGFUSE_LOG_USER_TEXT=1 the
user's message is logged, so every string a trace carries -- the turn's input and output, each call's response text, each
tool's arguments and output, the fact check's output -- has emails replaced by [email] and phone numbers by [phone]
(tracing.mask). The Langfuse user is the integer user id, never an email. The request Anthropic receives is untouched
(payload v5). docs/privacy.md says, in plain words, what is stored, where, and how to ask for deletion."""
import json
import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
for p in (str(REPO), str(REPO / "Tests")):
    if p not in sys.path:
        sys.path.insert(0, p)

from test_tracing import ag, _tracing_on, _Fake, _Resp, _Block, _text, XI   # noqa: E402,F401  (ag: the fixture)

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
PHONES = ["+44 7700 900123", "07700 900123", "(020) 7946 0958", "555-123-4567", "+1 (555) 123-4567", "+33 1 23 45 67 89",
          "07700900123"]
NOT_PHONES = ["2026-10-30 21:04:00+00:00", "Fri 30 Oct 2026 21:04 UTC", "£7.9m", "0.125355751", "e_points 4.83", "GW10",
              "98% chance", "player 411", "turn 2fa2e003e1cb4c7faeefe78595c7cd8b", "17:30 UTC", "version 13ebb8e94",
              "id 7156-7204", "£100.0m budget", "3-1 win", "1,234,567 managers"]


@pytest.mark.parametrize("phone", PHONES)
def test_m1_phone_numbers_are_masked(phone):
    import tracing
    assert tracing.mask(f"call me on {phone} please") == "call me on [phone] please"


@pytest.mark.parametrize("text", NOT_PHONES)
def test_m1_numbers_that_are_not_phones_are_left_alone(text):
    import tracing
    assert tracing.mask(text) == text


def test_m1_emails_are_masked_and_structures_are_walked():
    import tracing
    assert tracing.mask("mail Jane.Doe+fpl@Example.co.uk now") == "mail [email] now"
    v = {"q": ["a@b.io", {"deep": "x +44 7700 900123"}], "n": 411, "ok": True, "none": None}
    assert tracing.mask(v) == {"q": ["[email]", {"deep": "x [phone]"}], "n": 411, "ok": True, "none": None}


SECRET_MSG = "I'm jane.doe@example.com, text me on +44 7700 900123 -- who should I captain?"


def test_m2_a_turn_exports_no_email_and_no_phone(ag, monkeypatch):
    tracing, made = _tracing_on(monkeypatch, log_user_text="1")
    monkeypatch.setitem(ag.available_functions, "search_news", lambda **kw: {"results": [], "echo": kw})
    reply = "Captain Mbeumo. I'll email jane.doe@example.com or ring 07700 900123."
    fake = _Fake([_Resp([_Block("tool_use", name="search_news", input={"query": "jane.doe@example.com 07700 900123"},
                                id="toolu_1")], "tool_use"),
                  _text(reply)])
    monkeypatch.setattr(ag, "client", fake)
    answer, _ = ag.run_agent(SECRET_MSG, [])
    assert answer == reply                                               # the user still gets the reply as written
    sent = json.dumps([c["messages"] for c in fake.calls], default=str)
    assert "jane.doe@example.com" in sent                                # the model still gets the message as written
    lf = made[-1]
    exported = json.dumps([{"kw": o.kw, "updates": o.updates} for o in lf.observations] + lf.scores, default=str)
    assert not EMAIL_RE.search(exported), EMAIL_RE.findall(exported)
    assert "7700 900123" not in exported and "07700" not in exported
    assert "[email]" in exported and "[phone]" in exported
    root = lf.roots()[0]
    assert "[email]" in root.field("input") and "[email]" in root.field("output")


def test_m3_the_langfuse_user_is_the_integer_user_id(monkeypatch):
    """The turn's user as Langfuse sees it: the stored thread's integer user (clerk mode passes it), or -- with no thread --
    config_roles.DEFAULT_USER_ID(), which is the signed-in user inside a signed-in request. Never an email."""
    import config_roles
    tracing, made = _tracing_on(monkeypatch)
    turn = tracing.start_turn("turn-m3-a", "hi", session_id="th_x", user_id=10007)
    turn.end("ok")
    with config_roles.acting_user(10008):
        turn = tracing.start_turn("turn-m3-b", "hi")
        turn.end("ok")
    users_seen = [o.propagated.get("user_id") for o in made[-1].observations]
    assert users_seen == ["10007", "10008"]
    assert not EMAIL_RE.search(json.dumps([o.propagated for o in made[-1].observations], default=str))


def test_m4_the_privacy_text_says_what_where_and_how_to_delete():
    doc = (REPO / "docs" / "privacy.md").read_text(encoding="utf-8")
    low = doc.lower()
    for needle in ("messages", "squad", "usage", "our server", "anthropic", "voyage", "langfuse", "30 days", "delet",
                   "google", "email"):
        assert needle in low, needle
    assert not EMAIL_RE.search(doc)                                      # no personal address in a public repo


def test_m1_a_phone_at_the_end_of_a_sentence_is_masked_a_decimal_is_not():
    import tracing
    assert tracing.mask("ring 07700 900123.") == "ring [phone]."
    assert tracing.mask("worth 123456789.5 points") == "worth 123456789.5 points"
