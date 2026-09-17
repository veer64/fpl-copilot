"""The Tuesday checks (fix log section 12), run inside the image once post_ingest:GW4 has fired.
Read-only."""
import json
import sys
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, "/app")
import model_tools as mt

runs = mt._q("SELECT run_id, gw, kind, slot, status, finished_at, knowledge FROM model_runs WHERE run_id > 5 ORDER BY run_id")
print("runs after run 5:")
for r in runs:
    k = r.get("knowledge")
    if isinstance(k, str):
        try: k = json.loads(k)
        except ValueError: k = None
    dc = (k or {}).get("dc_fit") or {}
    print(f"  run {r['run_id']} GW{r['gw']} {r['kind']} {r['slot']} {r['status']} {r['finished_at']} | history_through_gw {(k or {}).get('history_through_gw')} "
          f"| dc_fit n_train {dc.get('n_train')} converged {dc.get('converged')} max|atk| {dc.get('max_abs_attack')} max|def| {dc.get('max_abs_defence')}")
ok = [r for r in runs if r["status"] == "SUCCESS"]
if ok:
    rid = ok[-1]["run_id"]
    n = mt._q("SELECT COUNT(*) AS n, COUNT(pts_goals) AS t FROM model_predictions WHERE run_id = %s", (rid,))[0]
    print(f"run {rid}: predictions rows {n['n']}, with recorded terms {n['t']}")
sc = mt._q("SELECT gw, points, hits, created_at FROM squad_scores WHERE season = '2026-27' ORDER BY gw")
print("squad_scores:", sc if sc else "none yet")
r = mt.explain_prediction(411, gw=5)
if "error" in r:
    print("explain_prediction(411, gw=5):", r["error"])
else:
    print(f"explain_prediction(411, gw=5): run {r.get('run_id')} stale_by {r.get('stale_by_gameweeks')} | fixture source {r['fixture']['source']} | {r['fixture']['notes']}")
    print("  summary:", r["summary"][:220])
for pid, label in [(0, None)]:
    pass
step = mt._frame_raw()[0]
g5 = step[step["gw"] == 5]
low = g5[(g5["team_lambda"] < 0.15) | (g5["opp_lambda"] < 0.15)].groupby("team").size()
print("GW5 rows with a lambda < 0.15 by club:", low.to_dict() if len(low) else "none")
h = mt.health()
print("health:", h["status"], h["git_sha"], "| reasons:", h["reasons"])
