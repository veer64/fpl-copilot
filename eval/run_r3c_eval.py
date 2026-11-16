"""Prompt R3c (16 Nov 2026): the final gate after the last model-written number answers moved to code -- REAL model turns on the
laptop, graded by hand under the owner's 13 Nov standard. Laptop only: never point it at production. The runner is R3b's
(eval/run_r3b_eval.py, itself R3's) with its own spec, user ids, estimates and a Set C, so the three gates are run the same way.

Set A: the same 21 saved questions as R3 and R3b (W11f's scan; R1's setA_scan.json), one run each.
Set B: eval/agent_evals/r3c_setB_v1.json, 10 cases x 3 runs -- the same ten case types with NEW wording and NEW named players.
Set C: the same file's set_c, four questions, one run each.
Each case-run is a fresh laptop test user (13201-13299; an app_users row with a fake Clerk id, deleted at the end through
deletion.delete_account): TEAM -> a copy of the eval reference squad (laptop user 9001) as the user's own record; GENERAL -> no
squad. Laptop user 9001 itself is never written. Every turn goes through agent_graph.run_thread_turn under
config_roles.acting_user -- the /chat path after auth -- in one stored thread per case-run.

Recorded per turn: the reply as delivered; EVERY model response of the turn (stop_reason, its token usage, its blocks: text
length, tool names and inputs -- R1's runner kept only the stop reasons); every tool call WITH its output (the hand check's
evidence); agent.LAST_TURN (stop_reason, truncated, direct, skipped_rounds) and LAST_FACT_CHECK; the squad state before / after.

Guards. Anthropic: before every case-run, the eval's spend so far (chat_usage of the eval users, both sets) + the case's
estimate must stay under --max-usd, else the case-run is recorded NOT RUN. FPL: ZERO live requests -- the next deadline comes
from the newest local bootstrap snapshot, and any request to FPL is refused and counted. Langfuse: off. Every squad and draft row
that is not an eval user's (users 1, 9001, 9002, ...) is fingerprinted before and after every case-run.

Usage (repo root, PYTHONUTF8=1):
  uv run python eval/run_r3c_eval.py plan --out DIR --setA PATH --rule PATH   (DIR/plan.json BEFORE any model call; never rewritten)
  uv run python eval/run_r3c_eval.py run  --out DIR --set A|B|C [--max-usd 3.0]"""
import argparse
import copy
import hashlib
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO), str(REPO / "squad"), str(REPO / "eval")]
os.chdir(REPO)
from dotenv import load_dotenv  # noqa: E402

load_dotenv(REPO / ".env")
os.environ.update(AUTH_MODE="clerk", LANGFUSE_ENABLED="0")

SPEC = REPO / "eval" / "agent_evals" / "r3c_setB_v1.json"
BASE_UID, UID_MAX = 13200, 13299
SEED_USER = 9001                                     # the agent eval's reference squad on the laptop: read, never written
# what a case-run is assumed to cost before it starts (USD); the code-built answers are one routing call
EST_USD = {"A": 0.20, "B1": 0.06, "B2": 0.08, "B3": 0.06, "B4": 0.08, "B5": 0.06, "B6": 0.12, "B7": 0.06, "B8": 0.20, "B9": 0.20,
           "B10": 0.06, "C1": 0.25, "C2": 0.15, "C3": 0.15, "C4": 0.10}
COUNTS = {"fpl_live": 0, "fpl_refused": 0, "paths": []}

import requests  # noqa: E402

_real_req = requests.Session.request


def _no_fpl(self, method, url, *a, **k):
    """FPL API cap: 0. Any request to FPL is refused (and counted); nothing else is touched."""
    if "fantasy.premierleague.com" in str(url):
        COUNTS["fpl_refused"] += 1
        COUNTS["paths"].append(str(url).split("/api/", 1)[-1])
        raise requests.ConnectionError("R3c eval: no FPL request is allowed")
    return _real_req(self, method, url, *a, **k)


requests.Session.request = _no_fpl

import fpl_import  # noqa: E402
import team_card  # noqa: E402

fpl_import.BOOTSTRAP_TTL_S = 10 * 3600
fpl_import.CACHE_TTL_S = 10 * 3600
_BOOT = team_card._local_snapshot()

import model_tools as mt  # noqa: E402

_now = datetime.now(timezone.utc)
_nd = next(((int(e["id"]), datetime.fromisoformat(e["deadline_time"].replace("Z", "+00:00"))) for e in _BOOT["events"]
            if datetime.fromisoformat(e["deadline_time"].replace("Z", "+00:00")) > _now), None)
assert _nd is not None, "the local bootstrap snapshot has no upcoming deadline"
mt._DEADLINE_CACHE.update(at=time.time() + 20 * 3600, value=_nd)      # the next deadline from the local snapshot, never fetched

import agent  # noqa: E402
import agent_graph  # noqa: E402
import config_roles  # noqa: E402
import db_write  # noqa: E402
import drafts  # noqa: E402
import squad_store  # noqa: E402
import threads  # noqa: E402
import turn_context  # noqa: E402
import users  # noqa: E402

CALLS, RESPONSES = [], []
_real_call_tool = agent.call_tool


def _recording_call_tool(name, inp):
    res = _real_call_tool(name, inp)
    CALLS.append({"tool": name, "input": inp, "result": res})
    return res


agent.call_tool = _recording_call_tool
_real_create = agent.client.messages.create


def _block(b):
    t = getattr(b, "type", None)
    if t == "text":
        return {"type": "text", "chars": len(getattr(b, "text", "") or ""), "text": getattr(b, "text", "")}
    if t == "tool_use":
        return {"type": "tool_use", "name": getattr(b, "name", None), "input": getattr(b, "input", None)}
    return {"type": str(t)}


def _recording_create(*a, **k):
    r = _real_create(*a, **k)
    u = getattr(r, "usage", None)
    RESPONSES.append({"stop_reason": getattr(r, "stop_reason", None), "max_tokens": k.get("max_tokens"), "n_tools_offered": len(k.get("tools") or []),
                      "usage": {f: getattr(u, f, None) for f in ("input_tokens", "output_tokens", "cache_read_input_tokens",
                                                                 "cache_creation_input_tokens")} if u is not None else None,
                      "blocks": [_block(b) for b in (getattr(r, "content", None) or [])]})
    return r


agent.client.messages.create = _recording_create


def q(sql, params=()):
    conn = db_write.connect()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall() if cur.description else None
        conn.commit()
        return rows
    finally:
        conn.close()


def safety():
    """Every squad and draft row that is NOT an eval user's -- user 1, the reference user 9001 included. Must never change."""
    a = q(f"select count(*), coalesce(max(version_id),0), md5(coalesce(string_agg(user_id||':'||version_id||':'||is_active, ',' "
          f"order by version_id),'')) from squad_versions where user_id not between {BASE_UID} and {UID_MAX}")[0]
    b = q(f"select count(*), md5(coalesce(string_agg(user_id||':'||version_id, ',' order by user_id),'')) from user_drafts "
          f"where user_id not between {BASE_UID} and {UID_MAX}")[0]
    return f"squads {a[0]} / max {a[1]} / {a[2][:12]} | drafts {b[0]} / {b[1][:12]}"


def make_user(uid):
    users.ensure_schema()
    drafts.ensure_schema()
    q("INSERT INTO app_users (user_id, clerk_user_id, email, name, sign_in_method, profile_fetched_at) VALUES "
      "(%s, %s, %s, 'R3c Eval', 'email', now())", (uid, f"r3c_eval_{uid}_no_clerk_user", f"r3ceval{uid}@example.test"))


def seed_team(uid):
    src = squad_store.read_active(SEED_USER)
    conn = db_write.connect()
    try:
        squad_store.write_version(None, copy.deepcopy(src["squad_json"]), src["gw"], "R3c eval seed (copy of the eval reference squad)",
                                  True, conn=conn, user_id=uid)
    finally:
        conn.close()


def remove_user(uid):
    import deletion
    rows = q("select user_id, clerk_user_id, is_admin, is_exempt, email from app_users where user_id = %s", (uid,))
    if not rows:
        return None
    u = dict(zip(("user_id", "clerk_user_id", "is_admin", "is_exempt", "email"), rows[0]))
    return deletion.delete_account(u, clerk_delete=lambda cid: "deleted")["removed"]


def team_state(uid):
    r = q("select count(*), max(version_id) filter (where is_active) from squad_versions where user_id = %s", (uid,))[0]
    doc = None
    if r[1] is not None:
        doc = q("select squad_json from squad_versions where version_id = %s", (r[1],))[0][0]
        doc = json.loads(doc) if isinstance(doc, (str, bytes)) else doc
    return {"versions": int(r[0]), "active": r[1], "players": sorted(int(p["element"]) for p in doc["players"]) if doc else None}


def _usage(uid):
    r = q("select coalesce(sum(usd),0), count(*) from chat_usage where user_id = %s", (uid,))[0]
    return float(r[0]), int(r[1])


# ---- the plan (no model call) ---------------------------------------------------------------------------------------------

def _matches(name):
    """The player-lookup TOOL's matches for `name`, called exactly as the agent calls it (through its dispatcher)."""
    res = _real_call_tool("resolve_player", {"name": name})
    m = (res or {}).get("matches") or []
    return [{"id": x.get("player_id") or x.get("id"), "name": x.get("name"), "team": x.get("team"), "position": x.get("position"),
             "price": x.get("price")} for x in m], bool((res or {}).get("ambiguous"))


def _doc_args(doc, swap=None):
    ids = [int(p["element"]) for p in doc["players"]]
    roles = {int(p["element"]): str(p.get("role") or "").upper() for p in doc["players"]}
    cap = next(e for e, r in roles.items() if r in ("CAPTAIN", "C"))
    vice = next(e for e, r in roles.items() if r in ("VICE", "VC"))
    bench = [int(p["element"]) for p in sorted((p for p in doc["players"] if str(p.get("role")) == "bench"),
                                                key=lambda p: int(p.get("bench_order") or 0))]
    if swap:
        o, n = swap
        ids = [n if e == o else e for e in ids]
        bench = [n if e == o else e for e in bench]
        cap, vice = (n if cap == o else cap), (n if vice == o else vice)
    return {"player_ids": ids, "captain_id": cap, "vice_id": vice, "bench_order_ids": bench}


def _dry(uid, args):
    """The real set_my_squad preview for a swap on the probe user (nothing written; the ticket is cancelled)."""
    import squad_previews
    turn_context.begin(f"r3cdry{time.time_ns()}")
    try:
        with config_roles.acting_user(uid):
            res = mt.set_my_squad(**args)
    finally:
        turn_context.end()
    conn = db_write.connect()
    try:
        squad_previews.cancel_for_user(conn, uid)
    finally:
        conn.close()
    return isinstance(res, dict) and res.get("preview") is True, res


def _one(name):
    m, amb = _matches(name)
    return (m[0] if len(m) == 1 and not amb and m[0].get("id") is not None else None), m


def _pick(first, fallbacks, ok):
    """(the name used, the tool's matches for every name tried, why a fallback was used or None)."""
    tried = {}
    for name in [first] + list(fallbacks):
        hit, m = _one(name)
        tried[name] = m
        why = None if hit is None else ok(hit)
        if hit is not None and why is None:
            return name, hit, tried
        tried[name + " (rejected)"] = "not exactly one match" if hit is None else why
    raise RuntimeError(f"no usable name among {[first] + list(fallbacks)}: {tried}")


def git_sha():
    import subprocess
    return subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip()


def cmd_plan(out, set_a_path, rule_path):
    out.mkdir(parents=True, exist_ok=True)
    plan_p = out / "plan.json"
    assert not plan_p.exists(), "plan exists: a pre-registered plan is never rewritten"
    spec = json.loads(SPEC.read_text(encoding="utf-8"))
    set_a = json.loads(Path(set_a_path).read_text(encoding="utf-8"))
    set_a = [{k: a.get(k) for k in ("file", "id", "question", "setup", "needs_squad", "output_tokens", "before_chars")} for a in set_a]
    pl, fb = dict(spec["players"]), spec["fallbacks"]
    probe, checks = BASE_UID, {}
    try:
        make_user(probe)
        seed_team(probe)
        doc = squad_store.read_active(probe)["squad_json"]
        owned = {int(p["element"]) for p in doc["players"]}
        pl["p1"], h1, checks["case 6 p1"] = _pick(pl["p1"], [], lambda h: None)
        pl["p2"], h2, checks["case 6 p2"] = _pick(pl["p2"], fb["case 6"], lambda h: "the same player as p1" if h["id"] == h1["id"] else None)
        dry = {}
        for case, kin, kout, fkey in (("B8", "in8", "out8", "case 8 IN"), ("B9", "in9", "out9", "case 9 IN")):
            o_hit, o_m = _one(pl[kout])
            checks[f"{case} out"] = o_m
            assert o_hit is not None and int(o_hit["id"]) in owned, (case, "the OUT player must be one squad player", o_m)

            def legal(h, o=o_hit, case=case):
                if int(h["id"]) in owned:
                    return "already in the squad"
                ok, res = _dry(probe, _doc_args(doc, swap=(int(o["id"]), int(h["id"]))))
                dry[case] = {"in": h, "out": o, "preview": ok, "change": (res.get("change") or {}) if isinstance(res, dict) else None,
                             "error": None if ok else (res.get("error") if isinstance(res, dict) else str(res))}
                return None if ok else f"the swap does not preview as legal: {dry[case]['error']}"
            pl[kin], _hit, checks[f"{case} in"] = _pick(pl[kin], fb[fkey], legal)
        for k in ("c1", "c2"):
            hit, m = _one(pl[k])
            checks[f"C3 {k}"] = m
            assert hit is not None and int(hit["id"]) in owned, ("C3", "each named player must be one of the reference squad", m)
    finally:
        removed = remove_user(probe)
    run = mt._latest_run()
    plan = {"written_at": datetime.now(timezone.utc).isoformat(), "git": git_sha(), "spec": spec, "set_a": set_a,
            "players": pl, "player_checks": checks, "swap_dry_runs": dry, "safety_before": safety(), "probe_user_removed": removed,
            "fpl": dict(COUNTS), "reply_cap": agent._max_tokens(), "model": agent.AGENT_MODEL, "tools_offered": len(agent.tools_schema),
            "code_built_tools": sorted(agent.DIRECT_TOOLS), "next_update_words": (mt._next_run() or {}).get("words"),
            "build": {"run_id": run["run_id"], "gw": run["gw"], "finished_at": str(run["finished_at"])},
            "next_deadline": {"gw": _nd[0], "at": _nd[1].isoformat()},
            "rule_sha256": hashlib.sha256(Path(rule_path).read_bytes()).hexdigest() if rule_path else None,
            "budget_guard": {"est_usd_per_case_run": EST_USD,
                             "rule": "a case-run starts only if the eval's spend so far (both sets) + its estimate <= --max-usd"}}
    plan_p.write_text(json.dumps(plan, indent=1, default=str, ensure_ascii=False), encoding="utf-8")
    h = hashlib.sha256(plan_p.read_bytes()).hexdigest()[:16]
    print(json.dumps({"plan": str(plan_p), "sha256_16": h, "players": pl, "dry": {k: (v["preview"], v["error"]) for k, v in dry.items()},
                      "fpl": COUNTS, "build": plan["build"]}, default=str, ensure_ascii=False))


# ---- the run ---------------------------------------------------------------------------------------------------------------

def _turn(uid, tid, message, path):
    rec = {"message": message}
    c0, r0 = len(CALLS), len(RESPONSES)
    u0 = _usage(uid)
    rec["state_before"] = team_state(uid) if path == "team" else None
    t0 = time.time()
    with config_roles.acting_user(uid):
        rec["reply"] = agent_graph.run_thread_turn(uid, tid, message)
    rec["seconds"] = round(time.time() - t0, 1)
    rec["at"] = datetime.now(timezone.utc).isoformat()
    rec["calls"] = [{"tool": c["tool"], "input": c["input"], "result": c["result"]} for c in CALLS[c0:]]
    rec["responses"] = RESPONSES[r0:]
    rec["stops"] = [r["stop_reason"] for r in RESPONSES[r0:]]
    rec["last_turn"] = dict(agent.LAST_TURN) if RESPONSES[r0:] else {}      # a turn answered by code leaves the previous turn's
    rec["fact_check"] = {k: v for k, v in agent.LAST_FACT_CHECK.items() if k not in ("original",)} if RESPONSES[r0:] else {}
    rec["state_after"] = team_state(uid) if path == "team" else None
    u1 = _usage(uid)
    rec["usd"], rec["model_calls"] = round(u1[0] - u0[0], 6), u1[1] - u0[1]
    return rec


def case_run(set_name, case_id, run, idx, path, messages):
    uid = BASE_UID + idx
    assert BASE_UID < uid <= UID_MAX
    rec = {"set": set_name, "case": case_id, "run": run, "uid": uid, "path": path, "safety_before": safety(),
           "started_at": datetime.now(timezone.utc).isoformat()}
    make_user(uid)
    try:
        if path == "team":
            seed_team(uid)
        tid = threads.create_thread(uid)
        rec["thread_id"] = tid
        rec["turns"] = []
        for m in messages:
            rec["turns"].append(_turn(uid, tid, m, path))
    except Exception as e:  # noqa: BLE001 -- recorded, the run goes on
        rec["error"] = f"{type(e).__name__}: {str(e)[:500]}"
    finally:
        rec["usd"] = _usage(uid)[0]
        rec["removed"] = remove_user(uid)
        rec["safety_after"] = safety()
    return rec


def _all_results(out):
    res = []
    for name in ("results_A.json", "results_B.json", "results_C.json"):
        p = out / name
        if p.exists():
            res += json.loads(p.read_text(encoding="utf-8"))
    return res


def cmd_run(out, set_name, max_usd):
    plan = json.loads((out / "plan.json").read_text(encoding="utf-8"))
    assert plan["git"] == git_sha(), f"the plan was written on {plan['git']}, this is {git_sha()}"
    res_p = out / f"results_{set_name}.json"
    results = json.loads(res_p.read_text(encoding="utf-8")) if res_p.exists() else []
    spent = sum(float(r.get("usd") or 0) for r in _all_results(out))
    jobs = []
    if set_name == "C":
        pl = plan["players"]
        for k, case in enumerate(plan["spec"]["set_c"]):
            msgs = [t.format(**pl) for t in case["turns"]]
            jobs.append((case["id"], 1, 70 + k + 1, case["path"], msgs, EST_USD[case["id"]]))
    elif set_name == "B":
        pl = plan["players"]
        for run in range(1, plan["spec"]["runs_per_case"] + 1):
            for k, case in enumerate(plan["spec"]["cases"]):
                msgs = [t.format(**pl) for t in case["turns"]]
                jobs.append((case["id"], run, 30 + (run - 1) * 10 + k + 1, case["path"], msgs, EST_USD[case["id"]]))
    else:
        for i, a in enumerate(plan["set_a"]):
            msgs = ([a["setup"]] if a.get("setup") else []) + [a["question"]]
            path = "team" if str(a.get("needs_squad") or "").upper().startswith("Y") else "general"
            jobs.append((f"A{i + 1:02d}:{a['id']}", 1, 1 + i, path, msgs, EST_USD["A"] * len(msgs)))
    for case_id, run, idx, path, msgs, est in jobs:
        if any(r["case"] == case_id and r["run"] == run for r in results):
            continue                                      # one run each: a recorded case-run is never run again
        if spent + est > max_usd:
            print(f"{case_id} run {run}: NOT RUN (spent ${spent:.4f} + est ${est:.2f} > ${max_usd})", flush=True)
            results.append({"set": set_name, "case": case_id, "run": run, "not_run": True})
            res_p.write_text(json.dumps(results, indent=1, default=str, ensure_ascii=False), encoding="utf-8")
            continue
        r = case_run(set_name, case_id, run, idx, path, msgs)
        spent += float(r.get("usd") or 0)
        results.append(r)
        res_p.write_text(json.dumps(results, indent=1, default=str, ensure_ascii=False), encoding="utf-8")
        last = (r.get("turns") or [{}])[-1]
        stops = [s for t in r.get("turns") or [] for s in t.get("stops") or []]
        print(f"{case_id} run {run}: ${r['usd']:.4f} (total ${spent:.4f}) stops={stops} err={r.get('error')} "
              f"safety_same={r['safety_before'] == r['safety_after']} fpl_refused={COUNTS['fpl_refused']} | {str(last.get('reply'))[:90]!r}",
              flush=True)
    print(json.dumps({"spent_usd": round(spent, 4), "fpl": COUNTS}, default=str))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=("plan", "run"))
    ap.add_argument("--out", required=True)
    ap.add_argument("--set", default="B", choices=("A", "B", "C"))
    ap.add_argument("--setA", default="")
    ap.add_argument("--rule", default="", help="the pre-registered rule as copied into the report (its sha256 goes in the plan)")
    ap.add_argument("--max-usd", type=float, default=3.0, dest="max_usd")
    a = ap.parse_args()
    if a.cmd == "plan":
        cmd_plan(Path(a.out), a.setA, a.rule)
    else:
        cmd_run(Path(a.out), a.set, a.max_usd)
