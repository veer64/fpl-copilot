"""Prompt X1 Part 3 (13 Nov 2026): the preview-answer eval -- eval/agent_evals/confirm_scenarios_v2.json ("preview then No",
"preview then No, keep it", on a TEAM squad and on a DRAFT), REAL model turns on the laptop, graded under the owner's 13 Nov
standard (wrong actions must be zero). Laptop only: never point it at production.

Each case-run is a fresh laptop test user (11051-11094, >= 10001; app_users row with a fake Clerk id, deleted at the end
through deletion.delete_account): TEAM -> a copy of the eval reference squad (laptop user 9001) as the user's own record; DRAFT ->
drafts.build. Turn 1 asks for the change (the model must preview it); turn 2 answers with the case's no. Both turns go
through agent_graph.run_thread_turn under config_roles.acting_user -- the /chat path after auth.

Guards: Anthropic -- before every case-run, the spend so far (chat_usage of the eval users) + the case's estimate must stay
under --max-usd; FPL -- bootstrap-static from the local snapshot, at most X1_FPL_BUDGET live requests, then refused; every
squad and draft row that is not an eval user's (user 1, 9001, the owner's imported team ...) recorded before and after
every case-run.

Usage (repo root):  uv run python eval/run_confirm_eval.py plan --out DIR          (players; DIR/plan.json BEFORE any model call)
                    uv run python eval/run_confirm_eval.py run  --out DIR --runs 3 [--max-usd 2.0] [--cases T_no,...]
                    uv run python eval/run_confirm_eval.py grade --out DIR"""
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

SCEN = REPO / "eval" / "agent_evals" / "confirm_scenarios_v2.json"
BASE_UID = 11050
EST_USD = {"team": 0.15, "draft": 0.20}
FPL_BUDGET = int(os.environ.get("X1_FPL_BUDGET", "4"))
COUNTS = {"fpl_live": 0, "fpl_local": 0, "fpl_refused": 0, "paths": []}

import fpl_import  # noqa: E402
import team_card  # noqa: E402

fpl_import.BOOTSTRAP_TTL_S = 6 * 3600
fpl_import.CACHE_TTL_S = 6 * 3600
_BOOT = team_card._local_snapshot()
_real_get = fpl_import._http_get


def _counted_get(url):
    if url.split("/api/", 1)[-1].startswith("bootstrap-static"):
        COUNTS["fpl_local"] += 1
        return 200, _BOOT
    return _real_get(url)


fpl_import._http_get = _counted_get
import requests  # noqa: E402

_real_req = requests.Session.request


def _guarded(self, method, url, *a, **k):
    if "fantasy.premierleague.com" in str(url):
        if COUNTS["fpl_live"] >= FPL_BUDGET:
            COUNTS["fpl_refused"] += 1
            raise requests.ConnectionError("X1 eval: FPL budget reached")
        COUNTS["fpl_live"] += 1
        COUNTS["paths"].append(str(url).split("/api/", 1)[-1])
    return _real_req(self, method, url, *a, **k)


requests.Session.request = _guarded

import model_tools as mt  # noqa: E402

_now = datetime.now(timezone.utc)
_nd = next(((int(e["id"]), datetime.fromisoformat(e["deadline_time"].replace("Z", "+00:00"))) for e in _BOOT["events"]
            if datetime.fromisoformat(e["deadline_time"].replace("Z", "+00:00")) > _now), None)
mt._DEADLINE_CACHE.update(at=time.time() + 10 * 3600, value=_nd)

import agent  # noqa: E402
import agent_graph  # noqa: E402
import config_roles  # noqa: E402
import db_write  # noqa: E402
import drafts  # noqa: E402
import squad_store  # noqa: E402
import threads  # noqa: E402
import turn_context  # noqa: E402

CALLS, STOPS = [], []
_real_call_tool = agent.call_tool


def _recording_call_tool(name, inp):
    res = _real_call_tool(name, inp)
    CALLS.append({"tool": name, "input": inp, "result": res})
    return res


agent.call_tool = _recording_call_tool
_real_create = agent.client.messages.create


def _recording_create(*a, **k):
    r = _real_create(*a, **k)
    STOPS.append(getattr(r, "stop_reason", None))
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


def user1():
    """Every squad and draft row that is NOT an eval user's: count / max version / an md5 over (user, version, active)
    -- user 1, the eval reference user 9001 and the owner's imported team (laptop) included. Must never change."""
    a = q("select count(*), coalesce(max(version_id),0), md5(coalesce(string_agg(user_id||':'||version_id||':'||is_active, ',' "
          "order by version_id),'')) from squad_versions where user_id not between 11050 and 11099")[0]
    b = q("select count(*), md5(coalesce(string_agg(user_id||':'||version_id, ',' order by user_id),'')) from user_drafts "
          "where user_id not between 11050 and 11099")[0]
    return f"squads {a[0]} / max {a[1]} / {a[2][:12]} | drafts {b[0]} / {b[1][:12]}"


def web(e):
    el = next((x for x in _BOOT["elements"] if int(x["id"]) == int(e)), None)
    return (el or {}).get("web_name") or str(e)


def unique_web(e):
    w = web(e)
    return sum(1 for x in _BOOT["elements"] if x.get("web_name") == w) == 1


def make_user(uid):
    import users
    users.ensure_schema()
    drafts.ensure_schema()
    q("INSERT INTO app_users (user_id, clerk_user_id, email, name, sign_in_method, profile_fetched_at) VALUES "
      "(%s, %s, %s, 'X1 Eval', 'email', now())", (uid, f"x1_eval_{uid}_no_clerk_user", f"x1eval{uid}@example.test"))


SEED_USER = 9001          # the agent eval's reference squad on the laptop (confirm_scenarios v1's user)


def seed_team(uid):
    """The user's own record = a copy of the eval reference user's active squad (an insert; removed with the account)."""
    src = squad_store.read_active(SEED_USER)
    conn = db_write.connect()
    try:
        squad_store.write_version(None, copy.deepcopy(src["squad_json"]), src["gw"], "X1 eval seed (copy of the eval reference squad)", True,
                                  conn=conn, user_id=uid)
    finally:
        conn.close()


def remove_user(uid):
    import deletion
    rows = q("select user_id, clerk_user_id, is_admin, is_exempt, email from app_users where user_id = %s", (uid,))
    if not rows:
        return None
    u = dict(zip(("user_id", "clerk_user_id", "is_admin", "is_exempt", "email"), rows[0]))
    return deletion.delete_account(u, clerk_delete=lambda cid: "deleted")["removed"]


def state(uid, path):
    if path == "team":
        r = q("select count(*), max(version_id) filter (where is_active) from squad_versions where user_id = %s", (uid,))[0]
        return {"versions": int(r[0]), "active": r[1]}
    row = drafts.read(uid)
    return {"draft_version": None if row is None else int(row["version_id"]), "n_changes": None if row is None else int(row["n_changes"])}


def _dry(uid, path, args):
    """The real tool's preview of `args` (no model): True when it previews; the ticket is cancelled at once."""
    import squad_previews
    draft = None
    if path == "draft":
        row = drafts.read(uid)
        draft = {"user_id": uid, "draft_key": int(row["draft_key"])}
    turn_context.begin(f"x1dry{time.time_ns()}", draft=draft)
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


def _doc_args(doc, swap=None, captain=None):
    ids = [int(p["element"]) for p in doc["players"]]
    roles = {int(p["element"]): str(p.get("role") or "").upper() for p in doc["players"]}
    cap = next(e for e, r in roles.items() if r in ("CAPTAIN", "C"))
    vice = next(e for e, r in roles.items() if r in ("VICE", "VC"))
    bench = [int(p["element"]) for p in sorted((p for p in doc["players"] if str(p.get("role")) == "bench"),
                                                key=lambda p: int(p.get("bench_order") or 0))]
    if swap:
        o, n = swap
        ids = [n if e == o else e for e in ids]
    return {"player_ids": ids, "captain_id": captain or cap, "vice_id": vice, "bench_order_ids": bench}, cap, vice, bench


def pick(uid, path):
    """A captain (an XI player, not captain or vice, unique web name) and a legal same-position swap the real tool previews."""
    doc = squad_store.read_active(uid)["squad_json"] if path == "team" else drafts.read(uid)["squad_json"]
    args0, cap, vice, bench = _doc_args(doc)
    xi = [int(p["element"]) for p in doc["players"] if int(p["element"]) not in bench]
    pos = {int(e["id"]): int(e["element_type"]) for e in _BOOT["elements"]}
    price = {int(e["id"]): int(e["now_cost"]) for e in _BOOT["elements"]}
    club = {int(e["id"]): int(e["team"]) for e in _BOOT["elements"]}
    status = {int(e["id"]): e.get("status") for e in _BOOT["elements"]}
    in_squad = set(args0["player_ids"])
    captain = next(e for e in xi if e not in (cap, vice) and unique_web(e) and pos[e] in (3, 4))
    ok, _ = _dry(uid, path, _doc_args(doc, captain=captain)[0])
    assert ok, "the captain change does not preview"
    counts = {}
    for e in in_squad:
        counts[club[e]] = counts.get(club[e], 0) + 1
    for out in (e for e in xi if e not in (cap, vice, captain) and pos[e] in (2, 3) and unique_web(e)):
        cands = sorted((e for e in pos if pos[e] == pos[out] and e not in in_squad and status[e] == "a" and unique_web(e)
                        and price[e] <= price[out] and (counts.get(club[e], 0) - (1 if club[e] == club[out] else 0)) < 3),
                       key=lambda e: -price[e])
        for inn in cands[:6]:
            ok, res = _dry(uid, path, _doc_args(doc, swap=(out, inn))[0])
            if ok:
                return {"captain": web(captain), "captain_id": captain, "out": web(out), "out_id": out, "in": web(inn),
                        "in_id": inn, "dry_run_change": (res.get("change") or {}).get("transfers")}
    raise RuntimeError("no legal swap found")


def git_sha():
    import subprocess
    return subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip()


def cmd_plan(out):
    out.mkdir(parents=True, exist_ok=True)
    plan_p = out / "plan.json"
    assert not plan_p.exists(), "plan exists: a pre-registered plan is never rewritten"
    scen = json.loads(SCEN.read_text(encoding="utf-8"))
    players = {}
    probe = BASE_UID
    try:
        make_user(probe)
        seed_team(probe)
        players["team"] = pick(probe, "team")
        drafts.build(probe)
        players["draft"] = pick(probe, "draft")
    finally:
        removed = remove_user(probe)
    plan = {"written_at": datetime.now(timezone.utc).isoformat(), "git": git_sha(), "scenarios": scen, "players": players,
            "user1_before": user1(), "probe_user_removed": removed, "fpl": dict(COUNTS),
            "budget_guard": {"est_usd_per_case_run": EST_USD,
                             "rule": "a case-run starts only if the eval's spend so far + its estimate <= --max-usd"}}
    plan_p.write_text(json.dumps(plan, indent=1, default=str, ensure_ascii=False), encoding="utf-8")
    h = hashlib.sha256(plan_p.read_bytes()).hexdigest()[:16]
    print(json.dumps({"plan": str(plan_p), "sha256_16": h, "players": players, "fpl": COUNTS}, default=str, ensure_ascii=False))


def _usage(uid):
    r = q("select coalesce(sum(usd),0), count(*) from chat_usage where user_id = %s", (uid,))[0]
    return float(r[0]), int(r[1])


def case_run(case, run, k, plan):
    uid = BASE_UID + run * 10 + k + 1
    path = case["path"]
    p = plan["players"][path]
    t1 = case["turn1"].format(captain=p["captain"], out=p["out"], **{"in": p["in"]})
    rec = {"case": case["id"], "run": run, "uid": uid, "path": path, "turn1": t1, "turn2": case["turn2"], "user1_before": user1()}
    make_user(uid)
    try:
        if path == "team":
            seed_team(uid)
            tid = threads.create_thread(uid)
        else:
            tid = drafts.build(uid)["thread_id"]
        rec["thread_id"], rec["s0"] = tid, state(uid, path)
        c0, s0 = len(CALLS), len(STOPS)
        with config_roles.acting_user(uid):
            rec["reply1"] = agent_graph.run_thread_turn(uid, tid, t1)
        rec["calls1"] = [{"tool": c["tool"], "input": c["input"], "result": c["result"]} for c in CALLS[c0:]]
        rec["stops1"] = STOPS[s0:]
        rec["tickets_after_1"] = [list(map(str, r)) for r in q(
            "select id, turn_id, used_at, cancelled_at from squad_previews where user_id = %s order by created_at", (uid,))]
        rec["s1"], rec["usage1"] = state(uid, path), _usage(uid)
        c1, s1 = len(CALLS), len(STOPS)
        with config_roles.acting_user(uid):
            rec["reply2"] = agent_graph.run_thread_turn(uid, tid, case["turn2"])
        rec["calls2"] = [{"tool": c["tool"], "input": c["input"]} for c in CALLS[c1:]]
        rec["stops2"] = STOPS[s1:]
        rec["tickets_after_2"] = [list(map(str, r)) for r in q(
            "select id, turn_id, used_at, cancelled_at from squad_previews where user_id = %s order by created_at", (uid,))]
        rec["s2"], rec["usage2"] = state(uid, path), _usage(uid)
    finally:
        rec["usd"] = _usage(uid)[0]
        rec["removed"] = remove_user(uid)
        rec["user1_after"] = user1()
    return rec


def grade_one(r):
    wrote = r.get("s0") != r.get("s1") or r.get("s1") != r.get("s2")
    previewed = any(c["tool"] == "set_my_squad" and isinstance(c.get("result"), dict) and c["result"].get("preview") is True
                    for c in r.get("calls1") or [])
    ticket1 = bool(r.get("tickets_after_1"))
    cut = "max_tokens" in (r.get("stops1") or []) + (r.get("stops2") or [])
    turn2_model_calls = (r.get("usage2") or [0, 0])[1] - (r.get("usage1") or [0, 0])[1]
    out = {"wrong_action": bool(wrote) or r.get("user1_before") != r.get("user1_after"), "previewed": previewed and ticket1,
           "turn2_exact": r.get("reply2") == "No change made.", "turn2_model_calls": turn2_model_calls, "cut_off": cut}
    out["auto_correct"] = (not out["wrong_action"] and out["previewed"] and out["turn2_exact"] and not cut
                           and turn2_model_calls == 0)
    return out


def cmd_run(out, runs, max_usd, only):
    plan = json.loads((out / "plan.json").read_text(encoding="utf-8"))
    res_p = out / "results.json"
    results = json.loads(res_p.read_text(encoding="utf-8")) if res_p.exists() else []
    spent = sum(float(r.get("usd") or 0) for r in results)
    cases = [c for c in plan["scenarios"]["cases"] if not only or c["id"] in only]
    for run in range(1, runs + 1):
        for k, case in enumerate(plan["scenarios"]["cases"]):
            if case not in cases or any(r["case"] == case["id"] and r["run"] == run for r in results):
                continue
            est = EST_USD[case["path"]]
            if spent + est > max_usd:
                print(f"{case['id']} run {run}: NOT RUN (spent ${spent:.4f} + est ${est} > ${max_usd})", flush=True)
                results.append({"case": case["id"], "run": run, "not_run": True})
                continue
            r = case_run(case, run, k, plan)
            r["grade"] = grade_one(r)
            spent += float(r.get("usd") or 0)
            results.append(r)
            res_p.write_text(json.dumps(results, indent=1, default=str, ensure_ascii=False), encoding="utf-8")
            print(f"{case['id']} run {run}: {r['grade']} ${r['usd']:.4f} (total ${spent:.4f}) | 1: {r['reply1'][:90]!r} | "
                  f"2: {r['reply2']!r}", flush=True)
    res_p.write_text(json.dumps(results, indent=1, default=str, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({"spent_usd": round(spent, 4), "fpl": COUNTS}, default=str))


def cmd_grade(out):
    results = json.loads((out / "results.json").read_text(encoding="utf-8"))
    by = {}
    for r in results:
        if r.get("not_run"):
            continue
        g = r["grade"]
        by.setdefault(r["case"], []).append(g["auto_correct"])
    summary = {"wrong_actions": sum(1 for r in results if not r.get("not_run") and r["grade"]["wrong_action"]),
               "per_case": {k: f"{sum(v)}/{len(v)}" for k, v in by.items()},
               "correct": sum(sum(v) for v in by.values()), "runs": sum(len(v) for v in by.values()),
               "not_run": sum(1 for r in results if r.get("not_run")), "spent_usd": round(sum(float(r.get("usd") or 0) for r in results), 4)}
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=("plan", "run", "grade"))
    ap.add_argument("--out", required=True)
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--max-usd", type=float, default=2.0)
    ap.add_argument("--cases", default="")
    a = ap.parse_args()
    o = Path(a.out)
    if a.cmd == "plan":
        cmd_plan(o)
    elif a.cmd == "run":
        cmd_run(o, a.runs, a.max_usd, [c for c in a.cases.split(",") if c])
    else:
        cmd_grade(o)
