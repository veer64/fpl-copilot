"""Prompt X1 (13 Nov 2026): a squad change is saved ONLY by the user's explicit yes to THAT preview, decided by code.

The incident: the owner answered two draft previews with "No"; the model called set_my_squad(confirm=true) with the open
ticket and the draft was written both times (the lock never read the user's answer). Here, on the REAL set_my_squad
(test_confirm_lock's database and stubs; users 9001 / 9002):
- a model's confirm=true with a perfectly valid ticket writes NOTHING (needs_yes) -- the incident, closed;
- every No variant -> 0 writes and "No change made." with no model call; every Yes variant -> exactly 1 write;
- unclear answers -> 0 writes + "Shall I make this change? Yes or No" (the ticket stays open);
- a second Yes, a Yes on an older preview after a newer one, another user's or another thread's ticket -> no write;
- agent.run_agent answers a preview reply without calling the model at all.
The draft path (the same gate on a draft chat, and the buttons' endpoint) is in Tests/test_drafts.py."""
import sys
from datetime import timedelta
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
for p in (str(REPO), str(REPO / "squad"), str(REPO / "eval"), str(REPO / "Tests")):
    if p not in sys.path:
        sys.path.insert(0, p)

import confirm_gate as cg                                   # noqa: E402
import squad_previews as sp                                 # noqa: E402
import turn_context                                         # noqa: E402
from test_confirm_lock import CHANGE_A, CHANGE_B, T0, _ticket_row, _versions, db, tool   # noqa: E402,F401

NO_VARIANTS = ["No", "no", "No, keep it", "no thanks", "nope", "cancel", "don't", "Don’t", "keep my team",
               "no don't change it", "NO!", "nah", "No.", "no, leave it", "cancel that", "don't do it", "No thank you",
               "keep my squad as it is", "not now"]
YES_VARIANTS = ["Yes", "yes", "yes please", "Yes please!", "go ahead", "do it", "confirm", "save it", "Yes, do it.", "ok",
                "okay", "sure", "yep", "yeah go ahead", "yes go ahead please", "confirmed", "Go for it", "yes, save it"]
ASK_VARIANTS = ["hmm", "maybe", "what about Salah instead?", "", "keep it", "why?", "how much would that cost?",
                "is that a good idea?", "yes but what about Salah", "\U0001F44D"]
NO_MORE_VARIANTS = ["no, bring in Salah instead", "not sure, what about Palmer?", "no — make Saka captain"]


# ---- the classifier (pure) -----------------------------------------------------------------------------------------------

@pytest.mark.parametrize("text", NO_VARIANTS)
def test_every_no_variant_is_a_no(text):
    assert cg.classify(text) == "no"


@pytest.mark.parametrize("text", YES_VARIANTS)
def test_every_yes_variant_is_a_yes(text):
    assert cg.classify(text) == "yes"


@pytest.mark.parametrize("text", ASK_VARIANTS)
def test_unclear_answers_ask(text):
    assert cg.classify(text) == "ask"


@pytest.mark.parametrize("text", NO_MORE_VARIANTS)
def test_a_no_with_more_is_never_a_yes(text):
    assert cg.classify(text) == "no_more"


def test_the_model_reads_a_note_the_user_does_not():
    assert cg.model_text("No change made.", "no") == "No change made. " + cg.NO_NOTE
    assert cg.model_text("No change made.", "cancelled") == "No change made. " + cg.NO_NOTE
    assert cg.model_text("Done.", "committed") == "Done. " + cg.YES_NOTE
    assert cg.model_text(cg.ASK_REPLY, "ask") == cg.ASK_REPLY and cg.model_text(cg.GONE_REPLY, "no_open_ticket") == cg.GONE_REPLY
    assert "NEW preview" in cg.NO_NOTE and "cancelled" in cg.NO_NOTE and "spent" in cg.YES_NOTE


def test_the_fixed_texts():
    assert cg.NO_CHANGE_REPLY == "No change made."
    assert cg.ASK_REPLY == "Shall I make this change? Yes or No"
    assert sp.refusal("needs_yes") == sp.NEEDS_YES_REFUSAL and "never call confirm=true" in sp.NEEDS_YES_REFUSAL
    assert sp.REASONS[-1] == "needs_yes"


def test_the_saved_reply_is_built_from_the_write_result():
    draft = {"draft": True, "committed": True, "change": {"transfers": [{"out": "Doku", "in": "Enzo Fernández"}],
                                                         "value_after": 99.3, "left_after": 0.7, "captain_changed": True}}
    assert cg.saved_reply(draft) == ("Done — saved to your draft. Doku out, Enzo Fernández in. The captain is as previewed. "
                                     "The draft now costs £99.3m (£0.7m left).")
    team = {"committed": True, "change": {"transfers": [{"out": "P16", "in": "P17"}], "bank_after": 0.5, "hit_cost_points": 4}}
    assert cg.saved_reply(team) == "Done — saved to your squad. P16 out, P17 in. Bank after: £0.5m. It costs a 4-point hit."


# ---- the lock: the model alone can never write -----------------------------------------------------------------------------

def _preview(tool, n=1, change=CHANGE_A, thread_id=None):
    turn_context.begin(turn_id=f"turn{n:02d}", started_at=T0 + timedelta(minutes=n), thread_id=thread_id)
    pv = tool(**change, confirm=False)
    turn_context.end()
    assert pv["preview"] and pv["preview_ticket"], pv
    return pv


def test_the_incident_a_model_confirm_with_a_valid_ticket_writes_nothing(tool, db):
    """13 Nov: preview -> the user says No -> the model calls confirm=true with the open ticket. Now: needs_yes, 0 writes."""
    n0 = _versions(db)
    pv = _preview(tool)
    turn_context.begin(turn_id="turn02", started_at=T0 + timedelta(minutes=2))      # the "No" turn, model-driven
    out = tool(**CHANGE_A, confirm=True, preview_ticket=pv["preview_ticket"])
    turn_context.end()
    assert out["refused"] and out["reason"] == "needs_yes" and out["error"] == sp.NEEDS_YES_REFUSAL
    assert _versions(db) == n0 and _ticket_row(db, pv["preview_ticket"])["used_at"] is None


def test_consent_for_another_ticket_is_not_consent(tool, db):
    pv = _preview(tool)
    turn_context.begin(turn_id="turn02", started_at=T0 + timedelta(minutes=2), consent="some-other-ticket")
    out = tool(**CHANGE_A, confirm=True, preview_ticket=pv["preview_ticket"])
    turn_context.end()
    assert out["reason"] == "needs_yes"


def test_the_preview_stores_the_change_a_yes_commits(tool, db):
    pv = _preview(tool)
    args = _ticket_row(db, pv["preview_ticket"])["change_args"]
    assert args == {**CHANGE_A, "gw": 9, "note": None, "proposal_id": None}


# ---- the typed answers (agent.run_agent's first step) ---------------------------------------------------------------------

@pytest.mark.parametrize("text", NO_VARIANTS)
def test_a_typed_no_writes_nothing_and_cancels_the_ticket(tool, db, text):
    n0 = _versions(db)
    pv = _preview(tool)
    out = cg.answer_turn(text, [], None)
    turn_context.end()
    assert out is not None and out[0] == "No change made."                      # what the user sees
    assert out[1] == [{"role": "user", "content": text},                          # what the model's history keeps
                      {"role": "assistant", "content": "No change made. " + cg.NO_NOTE}]
    assert _versions(db) == n0 and _ticket_row(db, pv["preview_ticket"])["cancelled_at"] is not None


@pytest.mark.parametrize("text", YES_VARIANTS)
def test_a_typed_yes_writes_exactly_once(tool, db, text):
    n0 = _versions(db)
    pv = _preview(tool)
    out = cg.answer_turn(text, [], None)
    rec_turn = turn_context.current()
    turn_context.end()
    assert out is not None and out[0].startswith("Done — saved to your squad."), out
    n1 = _versions(db)
    assert n1[0] == n0[0] + 1 and n1[1] != n0[1]
    assert _ticket_row(db, pv["preview_ticket"])["used_at"] is not None
    assert rec_turn["consent"] == pv["preview_ticket"]
    assert turn_context.last()["squad_applied"] == {"gw": 9, "version_id": n1[1]}
    assert cg.answer_turn("Yes", [], None) is None                  # a second Yes: no open ticket, nothing for the gate
    turn_context.end()
    turn_context.begin(turn_id="turn09", started_at=T0 + timedelta(minutes=9))    # and the model cannot write it again
    again = tool(**CHANGE_A, confirm=True, preview_ticket=pv["preview_ticket"])
    turn_context.end()
    assert again["refused"] and _versions(db) == n1


@pytest.mark.parametrize("text", ASK_VARIANTS)
def test_an_unclear_answer_writes_nothing_and_asks(tool, db, text):
    n0 = _versions(db)
    pv = _preview(tool)
    out = cg.answer_turn(text, [], None)
    turn_context.end()
    assert out is not None and out[0] == "Shall I make this change? Yes or No"
    row = _ticket_row(db, pv["preview_ticket"])
    assert _versions(db) == n0 and row["used_at"] is None and row["cancelled_at"] is None   # still open: a Yes can follow
    yes = cg.answer_turn("yes", [], None)
    turn_context.end()
    assert yes[0].startswith("Done") and _versions(db)[0] == n0[0] + 1


@pytest.mark.parametrize("text", NO_MORE_VARIANTS)
def test_a_no_with_more_cancels_and_leaves_the_rest_to_the_model(tool, db, text):
    n0 = _versions(db)
    pv = _preview(tool)
    assert cg.answer_turn(text, [], None) is None                   # the model answers the rest ...
    assert _ticket_row(db, pv["preview_ticket"])["cancelled_at"] is not None     # ... with nothing left to commit
    assert _versions(db) == n0


def test_no_open_ticket_means_the_gate_does_nothing(tool, db):
    assert cg.answer_turn("yes", [], None) is None
    pv = _preview(tool)
    with db.cursor() as cur:                                         # expired
        cur.execute("UPDATE squad_previews SET expires_at = created_at WHERE id = %s", (pv["preview_ticket"],))
    db.commit()
    assert cg.answer_turn("yes", [], None) is None


def test_another_threads_ticket_is_not_this_threads(tool, db):
    n0 = _versions(db)
    pv = _preview(tool, thread_id="thA")
    assert cg.answer_turn("yes", [], {"thread_id": "thB", "user_id": 9001}) is None          # thread B: no gating
    turn_context.begin(turn_id="turnB", started_at=T0 + timedelta(minutes=5), thread_id="thB",
                       consent=pv["preview_ticket"])                                       # even with consent forged
    out = tool(**CHANGE_A, confirm=True, preview_ticket=pv["preview_ticket"])
    turn_context.end()
    assert out["refused"] and out["reason"] == "missing" and _versions(db) == n0
    yes = cg.answer_turn("yes", [], {"thread_id": "thA", "user_id": 9001})                  # its own thread: written
    turn_context.end()
    assert yes[0].startswith("Done") and _versions(db)[0] == n0[0] + 1


def test_another_users_ticket_is_not_theirs(tool, db, monkeypatch):
    n0 = _versions(db)
    pv = _preview(tool)                                              # user 9001's
    monkeypatch.setenv("FPL_USER_ID", "9002")
    assert cg.answer_turn("yes", [], None) is None
    said, reply, applied, outcome = cg.answer_button(9002, None, "turn01", "yes", None)
    assert (said, reply, applied, outcome) == ("Yes", cg.GONE_REPLY, None, "no_open_ticket")
    assert _versions(db) == n0 and _versions(db, 9002)[0] == 1 and _ticket_row(db, pv["preview_ticket"])["used_at"] is None


# ---- the buttons ---------------------------------------------------------------------------------------------------------

def test_the_no_button_cancels_that_preview_and_writes_nothing(tool, db):
    n0 = _versions(db)
    pv = _preview(tool)
    said, reply, applied, outcome = cg.answer_button(9001, None, "turn01", "no", None)
    assert (said, reply, applied, outcome) == ("No", "No change made.", None, "cancelled")
    assert _versions(db) == n0 and _ticket_row(db, pv["preview_ticket"])["cancelled_at"] is not None
    said, reply, applied, outcome = cg.answer_button(9001, None, "turn01", "yes", None)     # a Yes after the No
    assert reply == cg.GONE_REPLY and _versions(db) == n0


def test_the_yes_button_writes_that_preview_once(tool, db):
    n0 = _versions(db)
    pv = _preview(tool)
    said, reply, applied, outcome = cg.answer_button(9001, None, "turn01", "yes", None)
    n1 = _versions(db)
    assert said == "Yes" and outcome == "committed" and reply.startswith("Done — saved to your squad.")
    assert applied == {"gw": 9, "version_id": n1[1]} and n1[0] == n0[0] + 1
    said, reply, applied, outcome = cg.answer_button(9001, None, "turn01", "yes", None)     # a second Yes
    assert (reply, applied, outcome) == (cg.ALREADY_REPLY, None, "already_used") and _versions(db) == n1
    assert _ticket_row(db, pv["preview_ticket"])["used_at"] is not None


def test_yes_on_an_older_preview_after_a_newer_one_writes_nothing(tool, db):
    n0 = _versions(db)
    _preview(tool, 1, CHANGE_A)
    pv_b = _preview(tool, 2, CHANGE_B)                               # the newer preview cancels the older ticket
    said, reply, applied, outcome = cg.answer_button(9001, None, "turn01", "yes", None)
    assert reply == cg.GONE_REPLY and _versions(db) == n0
    assert cg.answer_button(9001, None, "turn02", "yes", None)[3] == "committed"           # the newer one: written
    assert _versions(db)[0] == n0[0] + 1 and _ticket_row(db, pv_b["preview_ticket"])["used_at"] is not None


# ---- the loop: a preview answer never reaches the model --------------------------------------------------------------------

class _NoModel:
    def __init__(self):
        self.messages = self
        self.calls = 0

    def create(self, **kw):
        self.calls += 1
        raise AssertionError("the model must not be called for a preview answer")


@pytest.mark.parametrize("text,reply", [("No", "No change made."), ("hmm", "Shall I make this change? Yes or No")])
def test_run_agent_answers_a_preview_reply_without_the_model(tool, db, monkeypatch, text, reply):
    import agent
    fake = _NoModel()
    monkeypatch.setattr(agent, "client", fake)
    n0 = _versions(db)
    _preview(tool)
    answer, history = agent.run_agent(text, [])
    assert answer == reply and fake.calls == 0 and _versions(db) == n0
    assert history[-1] == {"role": "assistant", "content": cg.model_text(reply, "no" if text == "No" else "ask")}
    assert turn_context.current() is None and turn_context.last()["scripted"] is True


def test_run_agent_yes_writes_without_the_model(tool, db, monkeypatch):
    import agent
    fake = _NoModel()
    monkeypatch.setattr(agent, "client", fake)
    n0 = _versions(db)
    _preview(tool)
    answer, _ = agent.run_agent("Yes", [])
    assert answer.startswith("Done — saved to your squad.") and fake.calls == 0 and _versions(db)[0] == n0[0] + 1
