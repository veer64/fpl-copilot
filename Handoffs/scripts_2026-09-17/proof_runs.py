"""In-image proof of the stored-terms path against the real database: run 5 predates the term
columns, so the honest answer is the error naming that; compare_runs likewise; the frame path
still answers. Read-only."""
import sys
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, "/app")
import model_tools as mt

r = mt.explain_prediction(411, gw=5, run_id=5)
print("explain_prediction(411, gw=5, run_id=5) ->", r.get("error") or "(breakdown!)")
c = mt.compare_runs(411, 5, 5, 5)
print("compare_runs(411, 5, 5, 5) ->", c.get("error") or "(comparison!)")
print("explain_prediction(411, gw=5, run_id=999) ->", mt.explain_prediction(411, gw=5, run_id=999).get("error"))
f = mt.explain_prediction(411, gw=5)
print("frame path still answers:", "error" not in f, "| total", f.get("total_e_points"), "| run_id", f.get("run_id"))
