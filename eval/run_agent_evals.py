"""Run the agent-eval question set and grade each answer on the tools it called.

    uv run python eval/run_agent_evals.py --core
    uv run python eval/run_agent_evals.py --sheet list_players --dry-run
    uv run python eval/run_agent_evals.py --ids "resolve_player:2,limits:1"

INPUT  eval/agent_evals/tool_questions_v2.1.xlsx -- one sheet per tool plus
       "routing" and "limits", columns: # | question | exploits | must call |
       must NOT call | setup turn | needs squad | core | bug.
OUTPUT eval/agent_evals/results/run_<UTC ts>.jsonl (one line per question) and
       a markdown report beside it. Both directories are gitignored.

WHAT IS GRADED. Only the QUESTION turn's tool calls -- a setup turn is context,
not evidence. "must call" is a chain:

    a > b       b must come after a, because b consumes a's output
    a + b       both must come after the previous step, in any order
    a|b         either satisfies that slot
    none        no tool call at all
    any         no must-call requirement (must NOT call still applies)
    tool(k=v)   that tool, called with that argument

Extra calls never fail a question; "must NOT call" lists what may never appear.
PASS / FAIL is the grade, ERROR means the RUN broke (exception, API error, cap),
and the question's known-bug id travels with the line so a FAIL on a defect we
already measured is visible without cross-referencing.

HOW IT TALKS TO THE APP. Through main.app's /chat route with a TestClient, the
same path a browser takes, so the system prompt, the history and the citation /
numeric checks are all the production ones. Three things are wrapped FOR THIS
PROCESS ONLY, never in the app: agent.call_tool (to record calls),
agent.client (to count Anthropic attempts and tokens) and embeddings.embed (to
count Voyage calls). No production file is modified.

THE SQUAD. Every question marked "needs squad" is answered against ONE recorded
squad: the active version of user FPL_USER_ID (9001) when the run starts. If a
question writes a new version -- which is a finding, not an error -- the next
question that needs the squad gets the original document back, written as a new
version through squad_store.write_version (squad_versions is append-only, so a
restore is a new row, not an UPDATE).
"""
import argparse
import json
import os
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
for p in (str(REPO), str(REPO / "squad")):
    if p not in sys.path:
        sys.path.insert(0, p)

SHEET_FILE = REPO / "eval" / "agent_evals" / "tool_questions_v2.1.xlsx"
RESULTS_DIR = REPO / "eval" / "agent_evals" / "results"
COLUMNS = ["num", "question", "exploits", "must_call", "must_not", "setup",
           "needs_squad", "core", "bug"]

# claude-sonnet-4-6, the model agent.py sends to: $3.00 / $15.00 per million tokens
# (Anthropic first-party API rates, read from the claude-api skill's model table
# 2026-10-02). Since 2026-10-10 the rates live in pricing.py, shared with the /chat
# usage log, so the two cannot drift apart. Cost lines only -- nothing here depends
# on the price being exact.
from pricing import USD_PER_MTOK as _PRICES          # noqa: E402
import pricing as _pricing                           # noqa: E402  (turn_usd: the cache rates, 2026-10-19)

USD_IN_PER_MTOK = _PRICES["claude-sonnet-4-6"]["input"]
USD_OUT_PER_MTOK = _PRICES["claude-sonnet-4-6"]["output"]


# --------------------------------------------------------------- the grammar
def split_top(spec, sep):
    return [s.strip() for s in spec.split(sep) if s.strip()]


def is_any(spec):
    """True for the "any" must-call spec, whatever its case or padding."""
    return (spec or "").strip().lower() == "any"


def parse_chain(spec):
    """"a > b|c + d" -> [[{"a"}], [{"b","c"}, {"d"}]]: steps in order, each a
    list of slots, each slot a set of acceptable tool specs."""
    spec = (spec or "").strip()
    if not spec or spec.lower() == "none":
        return []
    steps = []
    for step in split_top(spec, ">"):
        steps.append([set(split_top(slot, "|")) for slot in split_top(step, "+")])
    return steps


def parse_tool_spec(text):
    """"set_my_squad(confirm=false)" -> ("set_my_squad", ("confirm", "false"))."""
    text = text.strip()
    if "(" in text and text.endswith(")"):
        name, _, rest = text.partition("(")
        key, _, value = rest[:-1].partition("=")
        return name.strip(), (key.strip(), value.strip().lower())
    return text, None


# A tool argument the schema documents a default for: an omitted argument means
# the default, so "set_my_squad(confirm=false)" matches a preview call that left
# confirm out entirely -- which is what the agent usually does.
ARG_DEFAULTS = {("set_my_squad", "confirm"): "false"}


def call_matches(call, spec):
    name, arg = parse_tool_spec(spec)
    if call["tool"] != name:
        return False
    if arg is None:
        return True
    key, want = arg
    args = call.get("args") or {}
    if key in args:
        got = args[key]
        got = str(got).lower() if not isinstance(got, bool) else ("true" if got else "false")
    else:
        got = ARG_DEFAULTS.get((name, key))
        if got is None:
            return False
    return got == want


def grade_must_call(spec, calls):
    """(ok, reason) for the "must call" column against this turn's calls.

    "any" means the question has NO required chain -- answer it with one tool, four, or
    none. It is not "none", which forbids calling anything. The distinction matters because
    25 v2.1 rows had a correct answer failed by a chain the question never needed, and the
    fix must not become "stop grading": "must NOT call" still applies to every row.
    """
    if is_any(spec):
        return True, ""
    steps = parse_chain(spec)
    if not steps:                                   # "none": no call may be made
        if calls:
            return False, f"expected no tool call, got {', '.join(c['tool'] for c in calls)}"
        return True, ""
    pos = 0
    for n, step in enumerate(steps, start=1):
        found = []
        for slot in step:
            hit = next((i for i in range(pos, len(calls))
                        if any(call_matches(calls[i], s) for s in slot)), None)
            if hit is None:
                return False, (f"missing {'|'.join(sorted(slot))}"
                               + (f" after step {n - 1}" if n > 1 else ""))
            found.append(hit)
        pos = max(found) + 1
    return True, ""


def grade_must_not(spec, calls):
    """(ok, reason): none of the listed tools (or tool(arg=value)) was called."""
    for item in split_top(spec or "", ","):
        for c in calls:
            if call_matches(c, item):
                return False, f"called {item}, which this question forbids"
    return True, ""


def grade(q, calls, setup_calls=None):
    """PASS / FAIL for one question.

    "must call" is graded over the whole conversation -- the setup turn's calls
    followed by the question turn's -- because the chain spans turns: an agent that
    resolved a player in the setup turn and used the id in the question turn has
    done exactly the right thing, and resolving twice would be the defect.

    "must NOT call" is graded over the QUESTION turn only: a tool the setup turn
    legitimately used cannot condemn the answer that follows it.
    """
    # "none" is a statement about THIS question -- the setup turn is allowed to have
    # called tools, and usually had to -- so it is graded on the question turn alone.
    chain = list(calls) if not parse_chain(q["must_call"]) else list(setup_calls or []) + list(calls)
    ok, reason = grade_must_call(q["must_call"], chain)
    if not ok:
        return "FAIL", reason
    ok, reason = grade_must_not(q["must_not"], calls)
    if not ok:
        return "FAIL", reason
    return "PASS", ""


# ------------------------------------------------------------------- budget
# ---------------------------------------------------------------- the LLM judge on trusted metrics (Part D J8)
# TRUSTED comes from the calibration (Part C) AND the fresh set (Part D, 2026-10-12): M2 and M3b only. The judge
# runs after an answer is saved, through llm.py, on its own cap; a FAIL is re-judged twice and stands only when
# all three say FAIL (confirmed_fail); untrusted metrics are never run here.
# The judge's trust table (eval/judge/README.md, judge final 2026-10-13): --judge runs exactly the TRUSTED metrics;
# --judge-all adds the REPORT-ONLY ones, whose verdicts are report columns only and never reach the gate (judge_gate).
# M3a joined TRUSTED on 2026-10-14: calibration 38/38 (100%) and fresh 13/13 (100%), 0 judge-PASS/gold-FAIL, once the
# four calibration labels the fixes G1 / F3 / F1 / G2 proved wrong were set to FAIL on evidence.
TRUSTED_METRICS = ("M2", "M3a", "M3b")
REPORT_ONLY_METRICS = ("M1", "M4", "M5")
ALL_JUDGE_METRICS = ("M1", "M2", "M3a", "M3b", "M4", "M5")
JUDGE_MODEL = "claude-opus-5-5"
JUDGE_REJUDGES = 2


class JudgeConfig:
    def __init__(self, model=JUDGE_MODEL, max_calls=300, max_usd=8.0, metrics=TRUSTED_METRICS):
        from judge import run_judge as RJ
        self.model = model
        self.metrics = tuple(metrics)
        self.budget = RJ.Budget(max_calls, max_usd)
        self.facts = RJ.allowed_general_facts()
        self.stopped = None


# ---------------------------------------------------------------- the gate's regression rule (batch 3 F11)
# Measured 2026-10-13: three "base 3/3 vs HEAD 1/3" questions were run from a worktree WITHOUT data/, so the base saw
# "no gameweek has finished yet" and errors where HEAD saw GW5 finished -- a different question. A base run now
# counts only if its context block (clock line aside) equals HEAD's.
REGRESSION_RUNS = 3


def context_signature(block):
    """The context block without its clock line ('- Now: ...'): two runs saw the same data iff these are equal."""
    return "\n".join(l for l in (block or "").splitlines() if not l.strip().startswith("- Now:")).strip()


# ---------------------------------------------------------------- the frozen clock (eval-only, 2026-10-24)
# A gate compares two trees on the same questions; until now each answer carried the wall clock of its own minute, so
# "how long until the deadline" could never be scored against one expected value. `--now <ISO>` (default: the
# environment's FPL_EVAL_NOW, read HERE and nowhere else) replaces now_context.clock in this process only: the
# context block, the Now line and every tool that reads now_context.clock (model_tools._gw_in_progress) see the same
# instant. Production code never reads the flag or the variable (Tests/test_eval_clock.py drives /chat with it set).
FROZEN_NOW = None


def frozen_now_from(args):
    """The ISO instant to freeze at: the --now flag, else FPL_EVAL_NOW from the environment, else None."""
    return getattr(args, "now", None) or os.environ.get("FPL_EVAL_NOW") or None


def freeze_clock(iso):
    """Replace now_context.clock with a constant for the rest of this process; returns the frozen datetime (UTC)."""
    global FROZEN_NOW
    import now_context
    dt = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    now_context.clock = lambda: dt
    FROZEN_NOW = dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    return dt


def run_context(rec):
    """The context block of a runner record's question turn (its last turn); None if absent."""
    turns = rec.get("turns") or []
    return turns[-1].get("context_block") if turns else None


def classify_regression(base_runs, head_runs, n=REGRESSION_RUNS):
    """One question's verdict from runner records. CONFIRMED = at least `n` counted base runs, all PASS, AND HEAD fails
    at least 2 of its runs (at least `n` of them); FLAKY otherwise; NOT DETERMINED when fewer than `n` base runs count
    (a base run counts only if its context signature equals HEAD's) or the HEAD runs saw different data themselves.
    Returns {verdict, base_pass, base_counted, base_excluded, head_fail, head_runs, reason}."""
    head_sigs = {context_signature(run_context(r)) for r in head_runs}
    out = {"base_pass": 0, "base_counted": 0, "base_excluded": 0, "head_fail": sum(1 for r in head_runs if r.get("result") == "FAIL"),
           "head_runs": len(head_runs)}
    if len(head_sigs) != 1 or not head_runs:
        return {**out, "verdict": "NOT DETERMINED", "reason": "the HEAD runs did not all see the same data"}
    sig = head_sigs.pop()
    counted = [r for r in base_runs if context_signature(run_context(r)) == sig]
    out.update(base_counted=len(counted), base_excluded=len(base_runs) - len(counted),
               base_pass=sum(1 for r in counted if r.get("result") == "PASS"))
    if len(counted) < n:
        return {**out, "verdict": "NOT DETERMINED",
                "reason": f"only {len(counted)} base run(s) saw HEAD's data ({out['base_excluded']} excluded); {n} needed"}
    if len(head_runs) < n:
        return {**out, "verdict": "NOT DETERMINED", "reason": f"only {len(head_runs)} HEAD run(s); {n} needed"}
    if out["base_pass"] == len(counted) and out["head_fail"] >= 2:
        return {**out, "verdict": "CONFIRMED", "reason": f"base {out['base_pass']}/{len(counted)} PASS, HEAD {out['head_fail']}/{len(head_runs)} FAIL"}
    return {**out, "verdict": "FLAKY", "reason": f"base {out['base_pass']}/{len(counted)} PASS, HEAD {out['head_fail']}/{len(head_runs)} FAIL"}


def judge_metrics_for(args):
    """The metrics a run judges: every metric with --judge-all, the TRUSTED ones with --judge, none otherwise."""
    if getattr(args, "judge_all", False):
        return ALL_JUDGE_METRICS
    return TRUSTED_METRICS if getattr(args, "judge", False) else ()


def judge_gate(rec):
    """The TRUSTED metrics whose confirmed FAIL counts against the answer; report-only verdicts never do."""
    j = rec.get("judge") or {}
    return [m for m in TRUSTED_METRICS if isinstance(j.get(m), dict) and j[m].get("confirmed_fail")]


def judge_record(rec, cfg):
    """{metric: {verdict, verdicts, confirmed_fail, reason, code_reason, usd, calls[, report_only]} | {not_run} |
    {applicable: False}} for cfg.metrics (the TRUSTED ones by default); also sets rec['judge_usd']. A FAIL is
    re-judged JUDGE_REJUDGES more times. A report-only metric's row carries report_only True."""
    from judge import metrics as M
    from judge import run_judge as RJ
    out, usd_start = {}, cfg.budget.usd
    for metric in cfg.metrics:
        report_only = metric not in TRUSTED_METRICS
        if cfg.stopped:
            out[metric] = {"not_run": cfg.stopped, **({"report_only": True} if report_only else {})}
            continue
        if not M.applicable(metric, rec):
            out[metric] = {"verdict": None, "applicable": False, **({"report_only": True} if report_only else {})}
            continue
        verdicts, rows, usd0, calls0, not_run = [], [], cfg.budget.usd, cfg.budget.calls, None
        for _ in range(1 + JUDGE_REJUDGES):
            if not cfg.budget.can_call():
                not_run = f"judge cap reached (calls {cfg.budget.calls}/{cfg.budget.max_calls}, usd {cfg.budget.usd:.2f}/{cfg.budget.max_usd})"
                break
            try:
                row = RJ.judge_one(rec, metric, cfg.model, cfg.budget, facts=cfg.facts)
            except RJ.StopRun as e:
                cfg.stopped = not_run = str(e)
                break
            rows.append(row)
            verdicts.append(row.get("verdict") or ("ERROR" if row.get("error") else None))
            if verdicts[-1] != "FAIL":
                break
        if not_run and not verdicts:
            out[metric] = {"not_run": not_run, **({"report_only": True} if report_only else {})}
            continue
        confirmed = len(verdicts) == 1 + JUDGE_REJUDGES and all(v == "FAIL" for v in verdicts)
        final = "FAIL" if confirmed else ("PASS" if "PASS" in verdicts else (verdicts[-1] if verdicts else None))
        last = rows[-1] if rows else {}
        out[metric] = {"verdict": final, "verdicts": verdicts, "confirmed_fail": confirmed,
                       "reason": last.get("reason"), "code_reason": last.get("code_reason"), "error": last.get("error"),
                       "usd": round(cfg.budget.usd - usd0, 4), "calls": cfg.budget.calls - calls0,
                       **({"not_run_rejudge": not_run} if not_run else {}),
                       **({"report_only": True} if report_only else {})}
    rec["judge_usd"] = round(cfg.budget.usd - usd_start, 4)
    return out


class BudgetExceeded(RuntimeError):
    pass


class Budget:
    def __init__(self, max_calls, max_usd, max_voyage):
        self.max_calls, self.max_usd, self.max_voyage = max_calls, max_usd, max_voyage
        self.calls = self.voyage = 0
        self.tok_in = self.tok_out = 0
        self.cache_read = self.cache_write = 0       # 2026-10-19: the agent caches its prefix; both are priced
        self.call_log = []                           # one dict per Anthropic call, in order (the turn record cuts it)
        self.usd = 0.0

    def claim_anthropic(self):
        if self.calls + 1 > self.max_calls:
            raise BudgetExceeded(f"Anthropic call cap {self.max_calls} reached")
        if self.usd >= self.max_usd:
            raise BudgetExceeded(f"USD cap {self.max_usd} reached (spent {self.usd:.2f})")
        self.calls += 1

    def claim_voyage(self):
        if self.voyage + 1 > self.max_voyage:
            raise BudgetExceeded(f"Voyage call cap {self.max_voyage} reached")
        self.voyage += 1

    def add_usage(self, usage, model="claude-sonnet-4-6"):
        i = int(getattr(usage, "input_tokens", 0) or 0)
        o = int(getattr(usage, "output_tokens", 0) or 0)
        cr = int(getattr(usage, "cache_read_input_tokens", 0) or 0)
        cw = int(getattr(usage, "cache_creation_input_tokens", 0) or 0)
        self.tok_in += i
        self.tok_out += o
        self.cache_read += cr
        self.cache_write += cw
        cost = _pricing.turn_usd(model, i, o, cache_read=cr, cache_write=cw)
        if cost is None:                             # a model with no price row: the old line, so the cap still counts
            cost = i / 1e6 * USD_IN_PER_MTOK + o / 1e6 * USD_OUT_PER_MTOK
        self.usd += cost
        self.call_log.append({"model": model, "input": i, "output": o, "cache_read": cr, "cache_write": cw,
                              "usd": round(cost, 6)})

    def snapshot(self):
        return {"anthropic_calls": self.calls, "voyage_calls": self.voyage,
                "input_tokens": self.tok_in, "output_tokens": self.tok_out,
                "cache_read_tokens": self.cache_read, "cache_write_tokens": self.cache_write,
                "api_calls_logged": len(self.call_log),
                "usd": round(self.usd, 4)}


class CountingMessages:
    def __init__(self, inner, budget):
        self.inner, self.budget = inner, budget

    def create(self, **kw):
        self.budget.claim_anthropic()
        resp = self.inner.create(**kw)
        if getattr(resp, "usage", None) is not None:
            self.budget.add_usage(resp.usage, kw.get("model", "claude-sonnet-4-6"))
        return resp


class CountingClient:
    def __init__(self, inner, budget):
        self.messages = CountingMessages(inner.messages, budget)


# ------------------------------------------------------------- the question set
# The header a question sheet must carry. v3 also holds a `changes` sheet documenting its
# own edits, whose columns are a sheet:# label and a column name -- every one of its 113
# rows loaded as a question and --non-core selected 251 of 207 (measured 2026-10-06). A
# sheet is graded only if its header row says it holds questions.
HEADER = ("#", "question")


def is_question_sheet(ws):
    """True when the sheet's first two headers are the question columns."""
    head = next(ws.iter_rows(min_row=1, max_row=1, values_only=True), ())
    got = tuple(str(h).strip().lower() if h is not None else "" for h in head[:2])
    return got == HEADER


def load_questions(path=SHEET_FILE):
    from openpyxl import load_workbook
    wb = load_workbook(path, data_only=True)
    out = []
    for sheet in wb.sheetnames:
        if not is_question_sheet(wb[sheet]):
            continue
        for row in wb[sheet].iter_rows(min_row=2, values_only=True):
            if row[1] is None:
                continue
            q = {"sheet": sheet}
            for i, name in enumerate(COLUMNS):
                v = row[i] if i < len(row) else None
                q[name] = "" if v is None else (v if name == "num" else str(v).strip())
            q["id"] = f"{sheet}:{q['num']}"
            out.append(q)
    return out


def select(questions, args):
    if args.ids:
        want = {s.strip() for s in args.ids.split(",") if s.strip()}
        return [q for q in questions if q["id"] in want]
    out = questions
    if args.sheet:
        out = [q for q in out if q["sheet"] in set(args.sheet)]
    if args.core:
        out = [q for q in out if q["core"].upper() == "Y"]
    if args.non_core:
        out = [q for q in out if q["core"].upper() != "Y"]
    return out


# ------------------------------------------------------------------- the squad
class SquadKeeper:
    """Holds the run's reference squad document and puts it back when a question
    has changed it. Append-only: a restore is a new version."""

    def __init__(self, user_id, conn):
        import squad_store
        self.ss, self.user_id, self.conn = squad_store, user_id, conn
        rec = squad_store.read_active(user_id, conn=conn)
        self.doc = rec["squad_json"]
        self.gw = rec["gw"]
        self.version = rec["version_id"]
        self.restores = []

    def fingerprint(self, doc):
        return json.dumps([[p["element"], p["role"], p["bench_order"]]
                           for p in sorted(doc["players"], key=lambda x: x["element"])],
                          sort_keys=True)

    def active(self):
        return self.ss.read_active(self.user_id, conn=self.conn)

    def max_version(self):
        with self.conn.cursor() as cur:
            cur.execute("SELECT COALESCE(MAX(version_id), 0) FROM squad_versions "
                        "WHERE user_id = %s", (self.user_id,))
            return cur.fetchone()[0]

    def ensure(self, qid):
        """Reference document active before the question. Returns (ok, note)."""
        try:
            rec = self.active()
        except Exception as e:                       # noqa: BLE001 -- reported, never fatal
            return False, f"could not read the squad: {type(e).__name__}: {e}"
        if self.fingerprint(rec["squad_json"]) == self.fingerprint(self.doc):
            return True, ""
        row = self.ss.write_version(rec, self.doc, self.gw,
                                    f"agent eval restore before {qid}", True,
                                    conn=self.conn, user_id=self.user_id)
        self.restores.append({"before": qid, "new_version": row["version_id"]})
        return True, f"restored as version {row['version_id']}"


# -------------------------------------------------------------------- the run
def new_ids(conn, table, after):
    with conn.cursor() as cur:
        cur.execute(f"SELECT id FROM {table} WHERE id > %s ORDER BY id", (after,))
        return [r[0] for r in cur.fetchall()]


def max_id(conn, table):
    with conn.cursor() as cur:
        try:
            cur.execute(f"SELECT COALESCE(MAX(id), 0) FROM {table}")
            return cur.fetchone()[0]
        except Exception:                           # noqa: BLE001 -- table may not exist
            conn.rollback()
            return None


def run_one(q, client, agent, recorder, budget, keeper, conn, judge_cfg=None):
    """One question (with its setup turn, if any). Returns the result record; with `judge_cfg` the trusted
    metrics are judged after grading (judge_record)."""
    rec = {"id": q["id"], "sheet": q["sheet"], "num": q["num"], "question": q["question"],
           "must_call": q["must_call"], "must_not": q["must_not"], "setup": q["setup"],
           "needs_squad": q["needs_squad"], "core": q["core"], "bug": q["bug"],
           "started_at": datetime.now(timezone.utc).isoformat()}
    if FROZEN_NOW:
        rec["frozen_now"] = FROZEN_NOW                    # the instant the context block's clock was held at

    if q["needs_squad"].upper() == "Y":
        ok, note = keeper.ensure(q["id"])
        rec["squad_ready"] = ok
        rec["squad_restored"] = note
        if not ok:
            rec.update(result="ERROR", reason=note)
            return rec
    version_before = keeper.max_version() if keeper else None
    cit_before, num_before = max_id(conn, "citation_checks"), max_id(conn, "numeric_checks")

    reset_rate_limit()
    client.post("/reset")
    turns = []
    try:
        for kind, text in ([("setup", q["setup"])] if q["setup"] else []) + \
                          [("question", q["question"])]:
            recorder.clear()
            getattr(agent, "LAST_CONTEXT", {}).clear()
            t0 = time.time()
            before = budget.snapshot()
            r = client.post("/chat", json={"message": text})
            after = budget.snapshot()
            if r.status_code != 200:
                raise RuntimeError(f"/chat returned {r.status_code}: {r.text[:200]}")
            turns.append({"kind": kind, "message": text,
                          "reply": r.json().get("answer", ""),
                          "calls": recorder.dump(),
                          "context_block": getattr(agent, "LAST_CONTEXT", {}).get("text"),
                          "latency_s": round(time.time() - t0, 2),
                          "anthropic_calls": after["anthropic_calls"] - before["anthropic_calls"],
                          "input_tokens": after["input_tokens"] - before["input_tokens"],
                          "output_tokens": after["output_tokens"] - before["output_tokens"],
                          "cache_read_tokens": after["cache_read_tokens"] - before["cache_read_tokens"],
                          "cache_write_tokens": after["cache_write_tokens"] - before["cache_write_tokens"],
                          "api_usage": budget.call_log[before["api_calls_logged"]:after["api_calls_logged"]],
                          "usd": round(after["usd"] - before["usd"], 4)})
    except BudgetExceeded as e:
        rec.update(result="NOT RUN", reason=str(e), turns=turns)
        raise BudgetExceeded(str(e)) from e
    except Exception as e:                          # noqa: BLE001 -- an ERROR, by definition
        rec.update(result="ERROR", reason=f"{type(e).__name__}: {str(e)[:300]}", turns=turns)
        return rec

    qturn = turns[-1]
    rec["turns"] = turns
    rec["calls"] = qturn["calls"]
    rec["raw_reply"] = agent.LAST_RAW.get("text", "")
    rec["rendered_reply"] = qturn["reply"]
    rec["latency_s"] = qturn["latency_s"]
    rec["anthropic_calls"] = sum(t["anthropic_calls"] for t in turns)
    rec["input_tokens"] = sum(t["input_tokens"] for t in turns)
    rec["output_tokens"] = sum(t["output_tokens"] for t in turns)
    rec["cache_read_tokens"] = sum(t["cache_read_tokens"] for t in turns)
    rec["cache_write_tokens"] = sum(t["cache_write_tokens"] for t in turns)
    rec["usd"] = round(sum(t["usd"] for t in turns), 4)
    rec["citation_check_ids"] = new_ids(conn, "citation_checks", cit_before) if cit_before is not None else []
    rec["numeric_check_ids"] = new_ids(conn, "numeric_checks", num_before) if num_before is not None else []
    rec["tool_errors"] = [{"tool": c["tool"], "error": c["error"]}
                          for c in qturn["calls"] if c.get("error")]
    if keeper:
        after_v = keeper.max_version()
        rec["wrote_squad_version"] = bool(version_before is not None and after_v > version_before)
        rec["squad_versions_after"] = after_v
    earlier = [c for t in turns[:-1] for c in t["calls"]]
    res, reason = grade(q, qturn["calls"], setup_calls=earlier)
    rec["result"], rec["reason"] = res, reason
    rec["actual_calls"] = " > ".join(c["tool"] for c in qturn["calls"]) or "(none)"
    if turns[:-1]:
        rec["setup_calls"] = " > ".join(c["tool"] for c in earlier) or "(none)"
    if judge_cfg is not None:
        rec["judge"] = judge_record(rec, judge_cfg)
    return rec


_ID_NOISE = ("req_", "request_id")
# A provider error that will not clear by retrying: no amount of waiting buys credit,
# and bad credentials do not fix themselves. Measured 2026-10-03: a credit outage
# carried a fresh request_id on every attempt, so comparing raw strings never saw a
# repeat and the run kept calling a dead API for 85 questions.
FATAL_MARKS = ("credit balance is too low", "401", "403", "authentication_error",
               "permission_error", "invalid x-api-key")


def error_shape(reason):
    """The error with its per-attempt noise removed, for "same error again" tests."""
    import re
    s = re.sub(r"req_[A-Za-z0-9]+", "req_X", reason or "")
    s = re.sub(r"\d+", "N", s)
    return s[:200]


def fatal_error(reason):
    low = (reason or "").lower()
    return any(m.lower() in low for m in FATAL_MARKS)


def reset_rate_limit():
    """Clear the app's PROCESS-LOCAL /chat rate-limit counters (main.py allows 30
    calls per client and 60 in total per hour). That ceiling exists to bound what
    an outside caller can spend; this run's spend is bounded by --max-calls and
    --max-usd instead, and a 179-question eval cannot fit in 60 calls an hour.
    Runner-local: the limiter itself is untouched, so the deployed app keeps it."""
    try:
        import main as app_main
        app_main._hits_global.clear()
        app_main._hits_by_ip.clear()
    except Exception as e:                           # noqa: BLE001 -- never fatal
        print(f"  [rate-limit reset skipped: {type(e).__name__}: {e}]")


class Recorder:
    def __init__(self):
        self.calls = []

    def clear(self):
        self.calls = []

    def dump(self):
        return list(self.calls)


def wrap_dispatcher(agent, recorder):
    """Record every tool call the agent makes, in order. Runner-local: the
    production dispatcher is called unchanged and its result passed straight
    back, so nothing the agent sees differs from production. Since 2026-10-11
    each record also carries `output`: str(result), the exact tool_result
    content agent.py hands the model (the answer-quality judge reads it)."""
    original = agent.call_tool

    def recording_call_tool(tool_name, tool_input):
        out = original(tool_name, tool_input)
        err = out.get("error") if isinstance(out, dict) else None
        recorder.calls.append({"tool": tool_name, "args": tool_input or {},
                               "error": (str(err)[:300] if err else None),
                               "output": str(out)})
        return out

    agent.call_tool = recording_call_tool
    return original


def wrap_context(agent):
    """Keep the context block the agent prepended to the turn's system prompt
    (agent._system_for_turn calls agent.context_block once per user turn), so a
    judge sees the same dates, gameweek state and club list the model saw. A
    block that fails to build is recorded as None and the error re-raised, as
    the agent expects (it then sends the prompt alone)."""
    agent.LAST_CONTEXT = {}
    original = agent.context_block

    def with_now_line(text, now):
        """The block as the model saw it (2026-10-24): the clock line travels in the user message now, so it is put back
        after the title here, in the pre-move shape, for the judge and context_signature (which strips it)."""
        if now is None or not text or any(l.startswith("- Now:") for l in text.splitlines()):
            return text
        import now_context
        lines = text.splitlines()
        return "\n".join(lines[:1] + [now_context.now_line(now)] + lines[1:])

    def capture(now=None):
        try:
            text = original(now) if now is not None else original()
        except Exception:
            agent.LAST_CONTEXT["text"] = None
            raise
        agent.LAST_CONTEXT["text"] = with_now_line(text, now)
        return text

    agent.context_block = capture
    return original


def wrap_raw_reply(agent):
    """The rendered reply comes back from /chat; the RAW model text does not, so
    keep the last one the citation check saw (it is handed the raw text)."""
    agent.LAST_RAW = {}
    original = agent._citation_check

    def capture(turn_id, text, returned_ids):
        agent.LAST_RAW["text"] = text
        return original(turn_id, text, returned_ids)

    agent._citation_check = capture
    return original


def wrap_voyage(budget):
    import embeddings
    original = embeddings.embed

    def counting_embed(*a, **kw):
        budget.claim_voyage()
        return original(*a, **kw)

    embeddings.embed = counting_embed
    return original


# ------------------------------------------------------------------ reporting
def write_report(path, records, args, budget, keeper, started, finished):
    by_sheet = {}
    for r in records:
        s = by_sheet.setdefault(r["sheet"], {"PASS": 0, "FAIL": 0, "ERROR": 0, "NOT RUN": 0})
        s[r.get("result", "ERROR")] = s.get(r.get("result", "ERROR"), 0) + 1
    tot = {k: sum(s.get(k, 0) for s in by_sheet.values())
           for k in ("PASS", "FAIL", "ERROR", "NOT RUN")}
    lines = [f"# Agent eval run {started}", "",
             f"- questions: {len(records)}  |  PASS {tot['PASS']}  FAIL {tot['FAIL']}  "
             f"ERROR {tot['ERROR']}  NOT RUN {tot['NOT RUN']}",
             f"- selection: {' '.join(sys.argv[1:]) or '(all)'}",
             f"- started {started}, finished {finished}",
             f"- Anthropic calls {budget.calls}, Voyage calls {budget.voyage}, "
             f"tokens {budget.tok_in} in / {budget.tok_out} out, ${budget.usd:.2f}",
             f"- squad restores: {len(keeper.restores) if keeper else 0}", "",
             "## Per sheet", "", "| sheet | PASS | FAIL | ERROR | NOT RUN |", "|---|---|---|---|---|"]
    for s in sorted(by_sheet):
        c = by_sheet[s]
        lines.append(f"| {s} | {c.get('PASS',0)} | {c.get('FAIL',0)} | "
                     f"{c.get('ERROR',0)} | {c.get('NOT RUN',0)} |")
    lines += ["", "## FAIL and ERROR", "",
              "| id | question | expected | actual calls | bug | reason |", "|---|---|---|---|---|---|"]
    for r in records:
        if r.get("result") in ("FAIL", "ERROR", "NOT RUN"):
            lines.append(f"| {r['id']} | {r['question'][:70]} | {r.get('must_call','')} | "
                         f"{r.get('actual_calls','(n/a)')} | {r.get('bug','')} | "
                         f"{r.get('reason','')[:120]} |")
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_parser():
    """The CLI, as its own function so the options are testable without a run."""
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    # The workbook was a module constant bound into load_questions' default, so every run
    # graded v2.1 whatever had superseded it. --file names the question set; omitted, the
    # constant stands, so nothing that worked before changes.
    ap.add_argument("--file", help="question workbook (default: %s)" % SHEET_FILE.name)
    ap.add_argument("--core", action="store_true")
    ap.add_argument("--non-core", action="store_true", dest="non_core")
    ap.add_argument("--sheet", action="append")
    ap.add_argument("--ids")
    ap.add_argument("--max-calls", type=int, default=900)
    ap.add_argument("--max-usd", type=float, default=40.0)
    ap.add_argument("--max-voyage", type=int, default=200)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--user-id", type=int, default=9001)
    ap.add_argument("--now", help="freeze the context block's clock at this UTC instant (ISO 8601) for the whole run; "
                                  "default: the environment's FPL_EVAL_NOW; eval-only, production never reads it")
    ap.add_argument("--out")
    ap.add_argument("--judge", action="store_true", help="judge the TRUSTED metrics (TRUSTED_METRICS) after each answer, through llm.py")
    ap.add_argument("--judge-all", action="store_true", dest="judge_all",
                    help="judge every metric; the report-only ones (REPORT_ONLY_METRICS) are report columns, never the gate")
    ap.add_argument("--judge-max-usd", type=float, default=8.0, dest="judge_max_usd")
    ap.add_argument("--judge-max-calls", type=int, default=300, dest="judge_max_calls")
    return ap


def main(argv=None):
    a = build_parser().parse_args(argv)

    questions = select(load_questions(a.file or SHEET_FILE), a)
    if a.dry_run:
        print(f"{len(questions)} question(s) would run:")
        for q in questions:
            print(f"  {q['id']:28s} needs_squad={q['needs_squad']} core={q['core']} "
                  f"setup={'Y' if q['setup'] else 'N'} must_call={q['must_call']}")
        return 0

    os.environ["FPL_USER_ID"] = str(a.user_id)
    os.environ.setdefault("APP_API_KEY", uuid.uuid4().hex)
    import db_write
    import agent
    import main as app_main
    from fastapi.testclient import TestClient

    frozen = frozen_now_from(a)
    if frozen:
        dt = freeze_clock(frozen)
        print(f"clock frozen at {dt:%A %Y-%m-%d %H:%M} UTC (eval-only: now_context.clock in this process)")

    budget = Budget(a.max_calls, a.max_usd, a.max_voyage)
    recorder = Recorder()
    wrap_dispatcher(agent, recorder)
    wrap_raw_reply(agent)
    wrap_context(agent)
    wrap_voyage(budget)
    agent.client = CountingClient(agent.client, budget)

    conn = db_write.connect()
    conn.autocommit = True
    keeper = SquadKeeper(a.user_id, conn)
    print(f"reference squad: user {a.user_id}, version {keeper.version}, gw {keeper.gw}")

    client = TestClient(app_main.app, headers={"x-api-key": os.environ["APP_API_KEY"]})
    judge_metrics = judge_metrics_for(a)
    judge_cfg = JudgeConfig(JUDGE_MODEL, a.judge_max_calls, a.judge_max_usd, judge_metrics) if judge_metrics else None
    if judge_cfg:
        print(f"judge: {JUDGE_MODEL} on {', '.join(judge_metrics)} (gate: {', '.join(TRUSTED_METRICS)}), cap {a.judge_max_calls} calls / ${a.judge_max_usd}")
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    started = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%M%SZ")
    out = Path(a.out) if a.out else RESULTS_DIR / f"run_{started}.jsonl"
    records, stopped = [], None
    # Stop the run on a provider that is not going to recover: a 401/403 at once,
    # or the same error three times in a row. Everything after is NOT RUN.
    streak = {"reason": None, "n": 0}
    with out.open("w", encoding="utf-8") as fh:
        for i, q in enumerate(questions, start=1):
            if stopped:
                rec = {"id": q["id"], "sheet": q["sheet"], "num": q["num"],
                       "question": q["question"], "bug": q["bug"], "core": q["core"],
                       "must_call": q["must_call"], "result": "NOT RUN", "reason": stopped}
            else:
                try:
                    rec = run_one(q, client, agent, recorder, budget, keeper, conn, judge_cfg)
                except BudgetExceeded as e:
                    stopped = str(e)
                    rec = {"id": q["id"], "sheet": q["sheet"], "num": q["num"],
                           "question": q["question"], "bug": q["bug"], "core": q["core"],
                           "must_call": q["must_call"], "result": "NOT RUN", "reason": stopped}
            if rec.get("result") == "ERROR":
                r = rec.get("reason", "")
                shape = error_shape(r)
                streak["n"] = streak["n"] + 1 if shape == streak["reason"] else 1
                streak["reason"] = shape
                if fatal_error(r):
                    stopped = f"the provider cannot serve this run: {r[:140]}"
                elif streak["n"] >= 3:
                    stopped = f"the same error three times in a row: {r[:120]}"
            else:
                streak["reason"], streak["n"] = None, 0
            records.append(rec)
            fh.write(json.dumps(rec, default=str) + "\n")
            fh.flush()
            print(f"[{i}/{len(questions)}] {rec['id']:28s} {rec.get('result'):8s} "
                  f"{rec.get('reason','')[:70]}", flush=True)
    finished = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%M%SZ")
    report = out.with_suffix(".md")
    write_report(report, records, a, budget, keeper, started, finished)
    print(f"\njsonl:  {out}\nreport: {report}")
    print(f"Anthropic {budget.calls} calls, Voyage {budget.voyage}, "
          f"tokens {budget.tok_in}/{budget.tok_out}, ${budget.usd:.2f}")
    if judge_cfg:
        jb = judge_cfg.budget
        print(f"judge ({JUDGE_MODEL}, {', '.join(judge_cfg.metrics)}): {jb.calls} calls, tokens {jb.tok_in}/{jb.tok_out}, ${jb.usd:.2f}"
              + (f" -- stopped: {judge_cfg.stopped}" if judge_cfg.stopped else ""))
        gated = [(r["id"], m) for r in records for m in judge_gate(r)]
        print(f"judge gate ({', '.join(TRUSTED_METRICS)}): {len(gated)} confirmed FAIL(s)" + (f": {gated}" if gated else ""))
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
