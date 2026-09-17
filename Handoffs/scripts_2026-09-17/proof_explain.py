"""In-image proof of explain_prediction / compare_predictions against the real volume and
database (the scheduler image has the env). Read-only."""
import sys
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, "/app")
import model_tools as mt

for pid, gw in [(411, 5), (82, 5), (411, 4)]:
    r = mt.explain_prediction(pid, gw=gw)
    if "error" in r:
        print(f"explain_prediction({pid}, gw={gw}) -> error: {r['error']}"); continue
    print(f"--- explain_prediction({pid}, gw={gw}) run_id {r.get('run_id')} stale_by {r.get('stale_by_gameweeks')}")
    print("built:", (r.get("built") or "")[:160])
    print(r["rendered"])
    if r.get("note_stale"): print("note_stale:", r["note_stale"][:140])
    if r.get("finding"): print("FINDING:", r["finding"])
    print()
c = mt.compare_predictions(411, 379, gw=5)
print("--- compare_predictions(411, 379, gw=5)")
print(c.get("error") or c["rendered"])
print()
print("GW12 ->", mt.explain_prediction(411, gw=12).get("error"))
print("unknown player ->", mt.explain_prediction(999999, gw=5).get("error"))
