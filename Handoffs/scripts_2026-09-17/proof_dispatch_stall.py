"""In-image proof against the REAL state: the bootstrap as FPL serves it now (GW4 unconfirmed),
the real season file (through GW3), the real dispatch state; a fake clock at Friday's three
windows. Pure policy call -- nothing saved, nothing run."""
import json
import sys
from datetime import datetime, timezone
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, "/app"); sys.path.insert(0, "/app/eval")
import requests
import dispatch_policy as dp
import deadline_dispatcher as dd

events = requests.get("https://fantasy.premierleague.com/api/bootstrap-static/", timeout=20).json()["events"]
e4 = next(e for e in events if e["id"] == 4)
print("bootstrap now: GW4 finished", e4["finished"], "data_checked", e4["data_checked"])
master = dd.master_max_gw("2026-27")
state = dd.load_state()
print("season file through GW", master, "| state slots", {k: v.get("status") for k, v in (state.get("slots") or {}).items()})
for t in ("2026-09-17T12:00:00Z", "2026-09-18T16:01:00Z", "2026-09-18T17:01:00Z", "2026-09-18T17:21:00Z"):
    now = dp.parse_iso(t)
    p = dp.plan(now, events, json.loads(json.dumps(state)), master)
    print(f"{t}: action={p['action']} slot={p['slot']} reason={p['reason'][:150]}")
    if p["action"]:
        dp.record_outcome(state, p, True, run_id=999, history_through_gw=master)
    else:
        print("   expected_next:", json.dumps(p["expected_next"])[:230])
run = {"run_id": 999, "gw": 5, "kind": "t90", "finished_at": "2026-09-18T16:01:00+00:00",
       "knowledge": {"duration_s": 50, "history_through_gw": master, "history_ingested_at": "2026-09-08T00:17:00Z",
                     "availability_asof": "2026-09-18T15:50:00Z", "odds_pulled_at": "2026-09-18T16:00:30Z"}}
print("freshness a T-90 build would carry:", dp.freshness(run, dp.expected_next(dp.parse_iso("2026-09-17T12:00:00Z"), events, dd.load_state(), master)))
