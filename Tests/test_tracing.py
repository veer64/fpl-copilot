"""Langfuse tracing v1 (Prompt L, 2026-10-30): tracing.py records each agent turn as one Langfuse trace -- every
Anthropic call a generation (usage incl. cache read/write, cost from pricing.py), every tool call a tool span (output
trimmed), the fact check a span + a "fact_check" score, the send-back a marked generation, the loop guard as metadata.
Pinned here (the task's T2-T11; T1, the payload, is in test_agent_payload_equivalence.py): the tree, the send-back, the
guard, the cost, the ids, the user-text switch, the trimming, failure-proofing, the kill switch, the environment.
Offline: a fake in-memory Langfuse client (no network), a fake Anthropic client, stubbed tools and logs, no database.
One real-SDK case points at a closed local port (unreachable host) -- never at Langfuse."""
import contextlib
import hashlib
import importlib
import json
import sys
import types
import uuid
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
for p in (str(REPO), str(REPO / "squad"), str(REPO / "eval")):
    if p not in sys.path:
        sys.path.insert(0, p)

import pricing  # noqa: E402

UNREACHABLE = "http://127.0.0.1:9"                 # the discard port: nothing listens, a connection is refused


# ---- the fake Langfuse backend -------------------------------------------------------------------------------------------

class FakeObs:
    def __init__(self, backend, kw, parent=None):
        self.backend, self.kw, self.parent = backend, dict(kw), parent
        self.updates, self.ended, self.scores, self.children = [], False, [], []
        self.propagated = dict(backend.active_propagation)
        self.id = uuid.uuid4().hex[:16]
        tc = kw.get("trace_context") or {}
        self.trace_id = tc.get("trace_id") if parent is None else parent.trace_id

    @property
    def as_type(self):
        return self.kw.get("as_type", "span")

    @property
    def name(self):
        return self.kw.get("name")

    def field(self, key):
        """The last value given for `key`, at start or in an update."""
        val = self.kw.get(key)
        for u in self.updates:
            if key in u and u[key] is not None:
                val = u[key]
        return val

    def metadata(self):
        out = dict(self.kw.get("metadata") or {})
        for u in self.updates:
            out.update(u.get("metadata") or {})
        return out

    def start_observation(self, **kw):
        self.backend.hit("start_observation")
        child = FakeObs(self.backend, kw, parent=self)
        self.children.append(child)
        self.backend.observations.append(child)
        return child

    def update(self, **kw):
        self.backend.hit("update")
        self.updates.append(kw)
        return self

    def end(self, **kw):
        self.backend.hit("end")
        self.ended = True
        return self

    def score_trace(self, **kw):
        self.backend.hit("score_trace")
        self.backend.scores.append(dict(kw, trace_id=self.trace_id))

    def score(self, **kw):
        self.backend.hit("score")
        self.backend.scores.append(dict(kw, trace_id=self.trace_id, observation_id=self.id))


class FakeLangfuse:
    """The slice of the Langfuse client tracing.py uses; every call is counted in `calls`."""

    def __init__(self, **kw):
        self.init_kw = kw
        self.calls, self.observations, self.scores = [], [], []
        self.active_propagation = {}
        self.flushed = self.shut = 0

    def hit(self, name):
        self.calls.append(name)

    def start_observation(self, **kw):
        self.hit("start_observation")
        obs = FakeObs(self, kw)
        self.observations.append(obs)
        return obs

    def flush(self):
        self.hit("flush")
        self.flushed += 1

    def shutdown(self):
        self.hit("shutdown")
        self.shut += 1

    @contextlib.contextmanager
    def propagate(self, **kw):
        self.hit("propagate_attributes")
        saved = dict(self.active_propagation)
        self.active_propagation.update({k: v for k, v in kw.items() if v is not None})
        try:
            yield
        finally:
            self.active_propagation = saved

    # readers for the assertions
    def roots(self):
        return [o for o in self.observations if o.parent is None]

    def of_type(self, as_type):
        return [o for o in self.observations if o.as_type == as_type]


class RaisingLangfuse(FakeLangfuse):
    """Every client call raises: tracing must swallow it and the turn must not notice."""

    def start_observation(self, **kw):
        self.hit("start_observation")
        raise RuntimeError("langfuse exploded")

    def flush(self):
        raise RuntimeError("langfuse exploded")

    def shutdown(self):
        raise RuntimeError("langfuse exploded")

    @contextlib.contextmanager
    def propagate(self, **kw):
        self.hit("propagate_attributes")
        raise RuntimeError("langfuse exploded")
        yield  # pragma: no cover


# ---- the fake Anthropic client and the agent ----------------------------------------------------------------------------

class _Block:
    def __init__(self, type_, **kw):
        self.type = type_
        for k, v in kw.items():
            setattr(self, k, v)


class _Resp:
    def __init__(self, content, stop_reason, usage=(100, 20, 0, 0), model="claude-sonnet-4-6"):
        self.content, self.stop_reason, self.model = content, stop_reason, model
        i, o, cr, cw = usage
        self.usage = types.SimpleNamespace(input_tokens=i, output_tokens=o, cache_read_input_tokens=cr,
                                           cache_creation_input_tokens=cw)


class _Fake:
    def __init__(self, responses):
        self.responses, self.calls = list(responses), []
        self.messages = self

    def create(self, **kw):
        self.calls.append(kw)
        return self.responses.pop(0)


XI = {"xi": [{"player_id": 427, "name": "Bryan Mbeumo", "position": "MID", "team": "Man Utd", "role": "start", "e_points": 4.83,
              "p_play_any": 0.98}]}
FIXTURES = {"team": "Arsenal", "fixtures": [{"gw": 9, "opponent": "Everton", "venue": "H"}]}
CHUNK_BODY = ("Arsenal manager confirmed on Friday that the midfielder trained fully this week and is in contention to start "
              "against Everton, with the club's medical staff satisfied after a scan cleared him of any structural damage. "
              "He is expected to be named in the squad for the weekend fixture at the Emirates.")
NEWS = {"as_of": "2026-10-30T12:00:00Z", "search_mode": "hybrid", "no_news_for": [], "ambiguous_players": [],
        "results": [{"id": "c901", "source": "Arsenal official site", "headline": "Midfielder fit for Everton", "url": "https://x.test/a",
                     "date": "2026-10-30", "date_words": "Friday 30 Oct", "date_basis": "published", "age": "today",
                     "about_requested_player": True, "players": ["Martin Ødegaard"], "text": CHUNK_BODY}]}
RIGHT = "From your squad:\n- **Mbeumo** — 4.8 expected points, 98% chance of playing."
WRONG = "From your squad:\n- **Mbeumo** — 4.8 expected points, 97% chance of playing."
QUESTION = "Who should I captain this week?"


def _text(s, usage=(100, 20, 0, 0), model="claude-sonnet-4-6"):
    return _Resp([_Block("text", text=s)], "end_turn", usage, model)


def _tool(*names, usage=(100, 20, 0, 0), model="claude-sonnet-4-6"):
    blocks = [_Block("tool_use", name=n, input={}, id=f"toolu_{i}_{n}") for i, n in enumerate(names)]
    return _Resp(blocks, "tool_use", usage, model)


def _two_rounds():
    """A 2-tool-round turn: one tool, then two tools asked at once, then the (clean) answer: 3 calls, 3 tool calls."""
    return [_tool("get_my_xi"), _tool("get_my_xi", "get_fixtures"), _text(RIGHT)]


@pytest.fixture
def ag(monkeypatch):
    """The agent with its logs captured (the DB writes a turn makes) and two stubbed tools."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-used")
    monkeypatch.setenv("FPL_USER_ID", "9001")
    import agent
    importlib.reload(agent)
    writes = []
    monkeypatch.setattr(agent, "context_block", lambda now=None: "CONTEXT BLOCK")
    monkeypatch.setattr(agent, "record_chat_usage", lambda *a, **k: writes.append(("chat_usage", a, k)))
    monkeypatch.setattr(agent, "_citation_check", lambda *a, **k: writes.append(("citation", a[1:], k)))
    monkeypatch.setattr(agent, "_numeric_check", lambda *a, **k: writes.append(("numeric", a[1:2], k)))
    monkeypatch.setattr(agent, "_fact_check_log", lambda turn_id, info: writes.append(("fact_check", dict(info), {})))
    monkeypatch.setitem(agent.available_functions, "get_my_xi", lambda **kw: XI)
    monkeypatch.setitem(agent.available_functions, "get_fixtures", lambda **kw: FIXTURES)
    monkeypatch.setitem(agent.available_functions, "search_news", lambda **kw: NEWS)
    agent._test_writes = writes
    return agent


def _tracing_on(monkeypatch, backend_cls=FakeLangfuse, log_user_text="1"):
    """LANGFUSE_ENABLED=1 with keys present, the client built by a factory that returns the fake."""
    import tracing
    monkeypatch.setenv("LANGFUSE_ENABLED", "1")
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-lf-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-lf-test")
    monkeypatch.setenv("LANGFUSE_BASE_URL", UNREACHABLE)
    if log_user_text is None:
        monkeypatch.delenv("LANGFUSE_LOG_USER_TEXT", raising=False)
    else:
        monkeypatch.setenv("LANGFUSE_LOG_USER_TEXT", log_user_text)
    made = []

    def factory():
        fake = backend_cls()
        made.append(fake)
        return fake, fake.propagate

    monkeypatch.setattr(tracing, "_make_backend", factory)
    tracing._reset()
    return tracing, made


def _run(ag, monkeypatch, responses, question=QUESTION):
    fake = _Fake(responses)
    monkeypatch.setattr(ag, "client", fake)
    answer, history = ag.run_agent(question, [])
    return answer, fake


def _usage_row(ag):
    rows = [w for w in ag._test_writes if w[0] == "chat_usage"]
    assert len(rows) == 1
    turn_id, model, api_calls, i, o, cr, cw, usd, n = rows[0][1]
    return {"turn_id": turn_id, "model": model, "api_calls": api_calls, "usd": usd}


# ---- T2 the tree ---------------------------------------------------------------------------------------------------------

def test_t2_a_two_tool_round_turn_is_one_trace_with_a_generation_per_call_and_a_span_per_tool(ag, monkeypatch):
    tracing, made = _tracing_on(monkeypatch)
    answer, fake = _run(ag, monkeypatch, _two_rounds())
    assert answer == RIGHT and len(fake.calls) == 3
    lf = made[-1]
    roots = lf.roots()
    assert len(roots) == 1 and roots[0].ended
    gens = lf.of_type("generation")
    tools = lf.of_type("tool")
    assert len(gens) == len(fake.calls) == 3
    assert [t.name for t in tools] == ["get_my_xi", "get_my_xi", "get_fixtures"]      # 2 tools asked at once = 2 spans
    fcs = [o for o in lf.observations if o.name == "fact_check"]
    assert len(fcs) == 1 and fcs[0].ended
    assert [s["name"] for s in lf.scores] == ["fact_check"] and lf.scores[0]["value"] == "pass"
    assert all(o.ended for o in lf.observations)
    assert all(o.trace_id == roots[0].trace_id for o in lf.observations)
    assert [g.metadata().get("send_back") for g in gens] == [False, False, False]
    assert gens[0].field("model") == "claude-sonnet-4-6" and gens[0].metadata().get("stop_reason") == "tool_use"
    assert tracing.LAST_TURN["generations"] == 3 and tracing.LAST_TURN["tools"] == 3 and tracing.LAST_TURN["fact_check"]


def test_t2_a_tool_error_is_recorded_on_its_span(ag, monkeypatch):
    tracing, made = _tracing_on(monkeypatch)
    monkeypatch.setitem(ag.available_functions, "get_my_xi", lambda **kw: {"error": "no squad recorded"})
    _run(ag, monkeypatch, [_tool("get_my_xi"), _text("You have no squad recorded yet.")])
    span = made[-1].of_type("tool")[0]
    assert span.field("level") == "ERROR" and "no squad recorded" in span.field("status_message")


# ---- T3 the send-back ----------------------------------------------------------------------------------------------------

def test_t3_a_fact_check_mismatch_adds_exactly_one_generation_marked_send_back(ag, monkeypatch):
    tracing, made = _tracing_on(monkeypatch)
    answer, fake = _run(ag, monkeypatch, [_tool("get_my_xi"), _text(WRONG), _text(RIGHT)])
    assert answer == RIGHT and len(fake.calls) == 3
    lf = made[-1]
    gens = lf.of_type("generation")
    assert len(gens) == 3
    marked = [g for g in gens if g.metadata().get("send_back")]
    assert len(marked) == 1 and marked[0] is gens[-1]
    assert marked[0].parent is not None and marked[0].parent.name == "fact_check"
    assert [s["value"] for s in lf.scores] == ["sent_back_fixed"]


def test_t3_a_rewrite_still_wrong_scores_sent_back_flagged(ag, monkeypatch):
    tracing, made = _tracing_on(monkeypatch)
    still = "From your squad:\n- **Mbeumo** — 4.8 expected points, 96% chance of playing."
    _run(ag, monkeypatch, [_tool("get_my_xi"), _text(WRONG), _text(still)])
    lf = made[-1]
    assert [s["value"] for s in lf.scores] == ["sent_back_flagged"]
    assert len([g for g in lf.of_type("generation") if g.metadata().get("send_back")]) == 1


def test_t3_a_failed_send_back_call_is_closed_as_an_error_and_scored_flagged(ag, monkeypatch):
    tracing, made = _tracing_on(monkeypatch)

    class Boom(_Fake):
        def create(self, **kw):
            if len(self.calls) == 2:
                self.calls.append(kw)
                raise ConnectionError("network down")
            return super().create(**kw)
    fake = Boom([_tool("get_my_xi"), _text(WRONG)])
    monkeypatch.setattr(ag, "client", fake)
    answer, _ = ag.run_agent(QUESTION, [])
    assert answer == WRONG
    lf = made[-1]
    sb = [g for g in lf.of_type("generation") if g.metadata().get("send_back")]
    assert len(sb) == 1 and sb[0].ended and sb[0].field("level") == "ERROR"
    assert [s["value"] for s in lf.scores] == ["sent_back_flagged"]


# ---- T4 the loop guard ---------------------------------------------------------------------------------------------------

def test_t4_the_loop_guard_reply_is_recorded_as_metadata_with_no_fact_check(ag, monkeypatch):
    tracing, made = _tracing_on(monkeypatch)
    answer, fake = _run(ag, monkeypatch, [_Resp([_Block("thinking", thinking="", signature="s")], "max_tokens")])
    assert answer == ag.GUARD_REPLY
    lf = made[-1]
    root = lf.roots()[0]
    assert root.metadata().get("loop_guard") is True and root.field("output") == ag.GUARD_REPLY and root.ended
    assert [o for o in lf.observations if o.name == "fact_check"] == [] and lf.scores == []
    assert len(lf.of_type("generation")) == 1


# ---- T5 cost -------------------------------------------------------------------------------------------------------------

def test_t5_each_generation_costs_what_pricing_says_and_the_trace_sums_to_the_turns_usd(ag, monkeypatch):
    tracing, made = _tracing_on(monkeypatch)
    usages = [(12, 85, 11873, 1406), (431, 120, 13279, 977), (77, 333, 14256, 0), (5, 410, 14256, 593)]
    responses = [_tool("get_my_xi", usage=usages[0]), _tool("get_my_xi", "get_fixtures", usage=usages[1]),
                 _text(WRONG, usage=usages[2]), _text(RIGHT, usage=usages[3])]
    _run(ag, monkeypatch, responses)
    gens = made[-1].of_type("generation")
    assert len(gens) == 4
    total = 0.0
    for g, (i, o, cr, cw) in zip(gens, usages):
        assert g.field("usage_details") == {"input": i, "output": o, "cache_read_input_tokens": cr,
                                            "cache_creation_input_tokens": cw}
        cost = g.field("cost_details")
        assert round(cost["total"], 6) == pricing.turn_usd("claude-sonnet-4-6", i, o, cache_read=cr, cache_write=cw)
        assert cost["total"] == cost["input"] + cost["cache_creation_input_tokens"] + cost["cache_read_input_tokens"] + cost["output"]
        total += cost["total"]
    row = _usage_row(ag)
    assert row["api_calls"] == 4 and row["usd"] is not None
    assert round(total, 6) == row["usd"] and abs(total - row["usd"]) <= 5e-7


def test_t5_cost_details_are_pricing_py_on_any_usage():
    for i, o, cr, cw in [(0, 0, 0, 0), (1, 1, 1, 1), (999, 1023, 123457, 4321), (3, 7, 11, 13), (12500, 1024, 0, 12500)]:
        for model in ("claude-sonnet-4-6", "claude-opus-5-5", "claude-sonnet-5"):
            d = pricing.cost_details(model, i, o, cache_read=cr, cache_write=cw)
            assert round(d["total"], 6) == pricing.turn_usd(model, i, o, cache_read=cr, cache_write=cw)
    assert pricing.cost_details("claude-unknown-9", 10, 10) is None


def test_t5_an_unknown_model_has_its_cost_omitted_never_zero(ag, monkeypatch):
    tracing, made = _tracing_on(monkeypatch)
    _run(ag, monkeypatch, [_text("Hello!", model="claude-unknown-9")])
    g = made[-1].of_type("generation")[0]
    assert g.field("cost_details") is None
    assert all("cost_details" not in u or u["cost_details"] is None for u in g.updates)
    assert g.field("usage_details")["input"] == 100


# ---- T6 ids --------------------------------------------------------------------------------------------------------------

def test_t6_the_trace_id_is_deterministic_from_the_turn_id_and_carries_turn_and_user(ag, monkeypatch):
    tracing, made = _tracing_on(monkeypatch)
    _run(ag, monkeypatch, [_text("Hello!")])
    turn_id = ag.LAST_TURN["turn_id"]
    root = made[-1].roots()[0]
    want = hashlib.sha256(turn_id.encode("utf-8")).hexdigest()[:32]
    assert root.kw["trace_context"] == {"trace_id": want} and tracing.trace_id_for(turn_id) == want
    assert tracing.LAST_TURN["trace_id"] == want
    assert root.propagated["user_id"] == "9001" and root.propagated["metadata"]["turn_id"] == turn_id
    assert root.propagated["metadata"]["user_id"] == "9001" and root.metadata()["turn_id"] == turn_id
    for obs in made[-1].observations:                       # every observation carries the user and the turn
        assert obs.propagated.get("user_id") == "9001" and obs.propagated["metadata"]["turn_id"] == turn_id


def test_t6_the_sdk_seed_helper_agrees_with_the_fallback():
    import tracing
    from langfuse import Langfuse
    tid = uuid.uuid4().hex
    assert Langfuse.create_trace_id(seed=tid) == hashlib.sha256(tid.encode("utf-8")).hexdigest()[:32] == tracing.trace_id_for(tid)


# ---- T7 the user-text switch -----------------------------------------------------------------------------------------------

def test_t7_log_user_text_0_redacts_the_trace_input(ag, monkeypatch):
    tracing, made = _tracing_on(monkeypatch, log_user_text="0")
    _run(ag, monkeypatch, [_text("Hello!")])
    root = made[-1].roots()[0]
    assert root.field("input") == f"[redacted, {len(QUESTION)} chars]"
    assert QUESTION not in json.dumps([o.kw for o in made[-1].observations] + [u for o in made[-1].observations for u in o.updates],
                                      default=str, ensure_ascii=False)


def test_t7_log_user_text_1_logs_the_message_and_unset_redacts(ag, monkeypatch):
    tracing, made = _tracing_on(monkeypatch, log_user_text="1")
    _run(ag, monkeypatch, [_text("Hello!")])
    assert made[-1].roots()[0].field("input") == QUESTION
    tracing, made = _tracing_on(monkeypatch, log_user_text=None)
    _run(ag, monkeypatch, [_text("Hello!")])
    assert made[-1].roots()[0].field("input") == f"[redacted, {len(QUESTION)} chars]"


# ---- T8 trimming ---------------------------------------------------------------------------------------------------------

def test_t8_search_news_span_keeps_ids_titles_dates_source_and_no_body(ag, monkeypatch):
    tracing, made = _tracing_on(monkeypatch)
    _run(ag, monkeypatch, [_tool("search_news"), _text("Ødegaard trained fully this week [c901].")])
    span = made[-1].of_type("tool")[0]
    out = span.field("output")
    dumped = json.dumps(out, ensure_ascii=False)
    r = out["results"][0]
    assert r["id"] == "c901" and r["headline"] == "Midfielder fit for Everton" and r["date"] == "2026-10-30"
    assert r["source"] == "Arsenal official site" and "text" not in r
    assert CHUNK_BODY[:60] not in dumped and "trained fully" not in dumped
    everything = json.dumps([o.kw for o in made[-1].observations] + [u for o in made[-1].observations for u in o.updates],
                            default=str, ensure_ascii=False)
    assert CHUNK_BODY[:200] not in everything


def test_t8_other_outputs_over_8000_chars_are_truncated_with_the_count():
    import tracing
    big = {"rows": ["x" * 100 for _ in range(120)]}
    s = json.dumps(big, ensure_ascii=False)
    out = tracing.trim_output("list_players", big)
    assert isinstance(out, str) and len(s) > 8000
    assert out == s[:8000] + f"[truncated {len(s) - 8000} chars]"
    small = {"rows": ["x"] * 10}
    assert tracing.trim_output("list_players", small) == small
    assert tracing.trim_output("get_player_card", "plain text") == "plain text"


# ---- T9 failure-proof ----------------------------------------------------------------------------------------------------

def _strip_turn(writes):
    """The DB writes of a turn with its random turn id taken out (two runs of one turn differ only there)."""
    out = []
    for kind, args, kw in writes:
        args = list(args)
        if kind == "chat_usage":
            args = args[1:]
        out.append((kind, json.dumps(args, default=str, sort_keys=True), json.dumps(kw, default=str, sort_keys=True)))
    return out


def _turn_writes(ag, monkeypatch, responses):
    ag._test_writes.clear()
    answer, fake = _run(ag, monkeypatch, responses)
    return answer, _strip_turn(ag._test_writes), [json.dumps(c, default=lambda o: vars(o), sort_keys=True) for c in fake.calls]


def _off(monkeypatch):
    import tracing
    monkeypatch.setenv("LANGFUSE_ENABLED", "0")
    tracing._reset()


def test_t9_a_client_raising_on_every_call_changes_nothing_and_is_logged_once(ag, monkeypatch, capsys):
    _off(monkeypatch)
    off = _turn_writes(ag, monkeypatch, [_tool("get_my_xi"), _text(WRONG), _text(RIGHT)])
    tracing, made = _tracing_on(monkeypatch, backend_cls=RaisingLangfuse)
    capsys.readouterr()
    on1 = _turn_writes(ag, monkeypatch, [_tool("get_my_xi"), _text(WRONG), _text(RIGHT)])
    on2 = _turn_writes(ag, monkeypatch, [_tool("get_my_xi"), _text(WRONG), _text(RIGHT)])
    assert on1 == off and on2 == off
    logged = [l for l in capsys.readouterr().out.splitlines() if "[tracing" in l]
    assert len(logged) == 1, logged
    assert made and made[-1].calls                           # the client was called, and raised, and nothing broke


def test_t9_keys_missing_changes_nothing_makes_no_client_and_is_logged_once(ag, monkeypatch, capsys):
    _off(monkeypatch)
    off = _turn_writes(ag, monkeypatch, [_tool("get_my_xi"), _text(RIGHT)])
    tracing, made = _tracing_on(monkeypatch)
    monkeypatch.delenv("LANGFUSE_SECRET_KEY")
    capsys.readouterr()
    on1 = _turn_writes(ag, monkeypatch, [_tool("get_my_xi"), _text(RIGHT)])
    on2 = _turn_writes(ag, monkeypatch, [_tool("get_my_xi"), _text(RIGHT)])
    assert on1 == off and on2 == off and made == []
    assert len([l for l in capsys.readouterr().out.splitlines() if "[tracing" in l]) == 1


def test_t9_the_package_failing_to_import_changes_nothing_and_is_logged_once(ag, monkeypatch, capsys):
    import tracing
    _off(monkeypatch)
    off = _turn_writes(ag, monkeypatch, [_tool("get_my_xi"), _text(RIGHT)])
    monkeypatch.setenv("LANGFUSE_ENABLED", "1")
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-lf-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-lf-test")
    monkeypatch.setenv("LANGFUSE_BASE_URL", UNREACHABLE)
    monkeypatch.setitem(sys.modules, "langfuse", None)       # `import langfuse` now raises ImportError
    tracing._reset()
    capsys.readouterr()
    on1 = _turn_writes(ag, monkeypatch, [_tool("get_my_xi"), _text(RIGHT)])
    on2 = _turn_writes(ag, monkeypatch, [_tool("get_my_xi"), _text(RIGHT)])
    assert on1 == off and on2 == off
    assert len([l for l in capsys.readouterr().out.splitlines() if "[tracing" in l]) == 1


def test_t9_an_unreachable_host_changes_nothing(ag, monkeypatch):
    """The real SDK, pointed at a closed local port: sending happens in the SDK's background threads only."""
    import tracing
    _off(monkeypatch)
    off = _turn_writes(ag, monkeypatch, [_tool("get_my_xi", "get_fixtures"), _text(WRONG), _text(RIGHT)])
    monkeypatch.setenv("LANGFUSE_ENABLED", "1")
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", f"pk-lf-test-{uuid.uuid4().hex[:8]}")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-lf-test")
    monkeypatch.setenv("LANGFUSE_BASE_URL", UNREACHABLE)
    monkeypatch.setenv("LANGFUSE_LOG_USER_TEXT", "1")
    tracing._reset()
    try:
        on = _turn_writes(ag, monkeypatch, [_tool("get_my_xi", "get_fixtures"), _text(WRONG), _text(RIGHT)])
        assert tracing.LAST_TURN.get("enabled") is True and tracing.LAST_TURN.get("errors") == 0
        assert tracing.LAST_TURN["generations"] == 3 and tracing.LAST_TURN["tools"] == 2
    finally:
        tracing.shutdown(timeout_s=1.0)
        tracing._reset()
    assert on == off


# ---- T10 the kill switch -------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("value", [None, "0", "", "false", "yes"])
def test_t10_langfuse_enabled_unset_or_not_1_makes_zero_client_calls(ag, monkeypatch, value):
    tracing, made = _tracing_on(monkeypatch)
    if value is None:
        monkeypatch.delenv("LANGFUSE_ENABLED")
    else:
        monkeypatch.setenv("LANGFUSE_ENABLED", value)
    tracing._reset()
    importlib.reload(ag)                                     # the import-time init too
    monkeypatch.setattr(ag, "context_block", lambda now=None: "CONTEXT BLOCK")
    monkeypatch.setattr(ag, "record_chat_usage", lambda *a, **k: None)
    monkeypatch.setattr(ag, "_citation_check", lambda *a, **k: None)
    monkeypatch.setattr(ag, "_numeric_check", lambda *a, **k: None)
    monkeypatch.setattr(ag, "_fact_check_log", lambda *a, **k: None)
    monkeypatch.setitem(ag.available_functions, "get_my_xi", lambda **kw: XI)
    _run(ag, monkeypatch, [_tool("get_my_xi"), _text(WRONG), _text(RIGHT)])
    tracing.shutdown(timeout_s=0.1)
    assert made == []                                        # no client was ever built, so no call was ever made
    assert tracing.LAST_TURN.get("enabled") is False


def test_t10_the_test_suite_runs_with_tracing_off():
    import os
    assert os.environ.get("LANGFUSE_ENABLED") == "0"


# ---- T11 environment -----------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("env", ["dev", "eval", "production"])
def test_t11_the_tracing_environment_is_passed_to_the_client(monkeypatch, env):
    import langfuse
    import tracing
    seen = []

    class Capture(FakeLangfuse):
        def __init__(self, **kw):
            super().__init__(**kw)
            seen.append(kw)
    monkeypatch.setattr(langfuse, "Langfuse", Capture)
    monkeypatch.setenv("LANGFUSE_ENABLED", "1")
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-lf-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-lf-test")
    monkeypatch.setenv("LANGFUSE_BASE_URL", UNREACHABLE)
    monkeypatch.setenv("LANGFUSE_TRACING_ENVIRONMENT", env)
    tracing._reset()
    tracing.init()
    assert len(seen) == 1 and seen[0]["environment"] == env and seen[0]["base_url"] == UNREACHABLE
    assert seen[0]["tracer_provider"] is not None              # a private provider: never the global OpenTelemetry one
    tracing._reset()


def test_t11_the_eval_runner_sets_the_eval_environment(monkeypatch):
    import run_agent_evals as rae
    monkeypatch.setenv("LANGFUSE_TRACING_ENVIRONMENT", "production")
    rae.main(["--dry-run", "--ids", "resolve_player:2"])
    import os
    assert os.environ["LANGFUSE_TRACING_ENVIRONMENT"] == "eval"


def test_the_app_shuts_tracing_down_on_shutdown(monkeypatch):
    monkeypatch.setenv("APP_API_KEY", "k")
    import main as app_main
    import tracing
    calls = []
    monkeypatch.setattr(tracing, "shutdown", lambda timeout_s=None: calls.append(timeout_s))
    from fastapi.testclient import TestClient
    with TestClient(app_main.app, headers={"x-api-key": "k"}):
        pass
    assert len(calls) == 1
