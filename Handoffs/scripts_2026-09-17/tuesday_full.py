"""The Tuesday checks, precisely as asked (2026-09-15 evening). Read-only except one transfer
proposal row written with source='proof' (append-only, labelled)."""
import json
import sys
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, "/app"); sys.path.insert(0, "/app/squad")
import numpy as np
import pandas as pd
import model_tools as mt
import squad_store

def J(x): return json.dumps(x, default=str)[:400]

print("### 1. ingest / health")
tick = open("/app/data/live/INGEST_TICK.txt", encoding="utf-8").read()
print("INGEST_TICK first line:", tick.splitlines()[0], "| ACTION REQUIRED in tick:", "ACTION REQUIRED" in tick)
h = mt.health(); sch = h["data_freshness_by_source"]["schedule"]
print("health:", h["status"], h["git_sha"], "| reasons:", h["reasons"])
print("slots:", J(sch["slots_this_gameweek"]), "| last_success:", J(sch["last_success"]))

print("\n### 2. squad_scores")
rows = mt._q("SELECT score_id, gw, version_id, points_net, points_raw, hit, transfers_made, free_transfers, doubled, doubled_role, captain_bonus, subs_made, final_xi, bench_points FROM squad_scores WHERE season='2026-27' ORDER BY gw")
print("rows:", len(rows)); [print("  ", J(r)) for r in rows]
sq = mt.get_my_squad()
print("get_my_squad: version", sq.get("version_id"), "| total_points", sq.get("total_points"), "| recorded captain/vice", sq.get("recorded_captain"), "/", sq.get("recorded_vice"))
names = {r["element"]: (r["name"], r["position"], r["team"]) for r in mt._q("SELECT element, name, position, team FROM players_live")}
hist = pd.read_parquet("/app/data/history/fpl_api_2026_27.parquet")
g4 = hist[hist["GW"] == 4].set_index("element")
for r in rows:
    for out_el, in_el in (r["subs_made"] or []):
        print(f"  autosub: out {names.get(out_el)} GW4 minutes {g4.loc[out_el, 'minutes'] if out_el in g4.index else 'no row'} -> in {names.get(in_el)} minutes {g4.loc[in_el, 'minutes'] if in_el in g4.index else 'no row'}")
    cap = r["doubled"]
    print(f"  armband: {names.get(cap)} ({r['doubled_role']}), GW4 points {g4.loc[cap, 'total_points'] if cap in g4.index else '?'} minutes {g4.loc[cap, 'minutes'] if cap in g4.index else '?'}; captain_bonus {r['captain_bonus']}")
    xi_min = [(names.get(e, (e,))[0], int(g4.loc[e, "minutes"]) if e in g4.index else None) for e in (r["final_xi"] or [])]
    print("  final XI minutes:", xi_min)

print("\n### 3. Dixon-Coles fit on the new run")
runs = mt._q("SELECT run_id, kind, slot, status, finished_at, knowledge FROM model_runs WHERE run_id > 5 ORDER BY run_id")
for r in runs:
    k = r["knowledge"]; k = json.loads(k) if isinstance(k, str) else (k or {})
    dc = k.get("dc_fit") or {}
    print(f"  run {r['run_id']} {r['kind']} {r['status']} history_through_gw {k.get('history_through_gw')} | dc_fit: {J(dc)}")
df, cutoff, built = mt._frame_raw()
print(f"frame on volume: cutoff GW{cutoff}, gws {sorted(df['gw'].unique())}, built {built}")
for gw, s in df.groupby("gw"):
    lam = s.groupby("team")["team_lambda"].first().dropna()
    print(f"  GW{gw}: {lam.round(6).nunique()} distinct team_lambda over {len(lam)} clubs; min {lam.min():.4f} ({lam.idxmin()}) max {lam.max():.3f} ({lam.idxmax()})")
for club in ("Coventry City", "Hull City", "Ipswich Town"):
    s = df[df["team"] == club].groupby("gw")[["team_lambda", "opp_lambda"]].first()
    print(f"  {club}: team_lambda by gw {s['team_lambda'].round(4).to_dict()} | opp_lambda {s['opp_lambda'].round(3).to_dict()}")
low = df[(df["team_lambda"] < 0.15) | (df["opp_lambda"] < 0.15)]
print("  rows with a lambda < 0.15:", low.groupby(["gw", "team"]).size().to_dict())

print("\n### 4. stored-terms path")
print("compare_runs(411, 5, 5, 9):", mt.compare_runs(411, 5, 5, 9).get("error"))
c = mt.compare_runs(411, 5, 6, 9); print("compare_runs(411, 5, 6, 9):", c.get("error") or c["sentence"])
r9 = mt.explain_prediction(411, gw=5, run_id=9)
print("RUN9_HAALAND_GW5_JSON=" + json.dumps({k: r9[k] for k in ("player_id", "name", "position", "team", "gw", "horizon_step", "total_e_points", "lines", "fixture", "summary", "reconciles", "residual_core", "residual_total")}, default=float))

print("\n### 5. term columns")
for r in runs:
    n = mt._q("SELECT COUNT(*) AS n, COUNT(pts_goals) AS t FROM model_predictions WHERE run_id = %s", (r["run_id"],))[0]
    print(f"  run {r['run_id']}: rows {n['n']}, with terms {n['t']}")

print("\n### 6. advice: GW5 XI now vs run 5")
xi = mt.get_my_xi()
if "error" in xi:
    print("get_my_xi error:", xi["error"])
else:
    print(f"  run {xi['run_id']} GW{xi['gw']} (as of cutoff {xi['predictions_as_of_cutoff_gw']}): captain {xi['captain']}, vice {xi['vice']}, XI pts {xi['predicted_xi_points']}")
    print("  XI:", [(r['name'], r['e_points']) for r in xi['xi']])
    print("  bench:", [(r['name'], r['e_points']) for r in xi['bench_in_order']])
# run 5's XI over the same fifteen from its stored totals
rec = squad_store.read_active(1); doc = rec["squad_json"]; state = squad_store.to_state(doc)
els = [p["element"] for p in doc["players"]]
p5 = pd.DataFrame(mt._q("SELECT element, e_points, p_play_any, p_start FROM model_predictions WHERE run_id = 5 AND config = 'baseline' AND gw = 5 AND element = ANY(%s)", (els,)))
p5["name"] = p5["element"].map(lambda e: names.get(e, ("?",))[0]); p5["position"] = p5["element"].map(lambda e: names.get(e, (None, "?"))[1]); p5["team"] = p5["element"].map(lambda e: names.get(e, (None, None, "?"))[2])
prices = {r["element"]: r["price_tenths"] for r in mt._q("SELECT element, price_tenths FROM players_live WHERE element = ANY(%s)", (els,))}
try:
    team5, missing5 = squad_store.xi_over_fifteen(p5, state, prices)
    roles5 = squad_store.roles_from_team(team5)
    cap5 = next(int(r.element) for r in team5.itertuples() if roles5[int(r.element)][0] == "CAPTAIN")
    xi5 = [(r.name, round(float(r.e_points), 2)) for r in team5.itertuples() if roles5[int(r.element)][0] != "bench"]
    b5 = [(r.name, round(float(r.e_points), 2)) for r in team5.itertuples() if roles5[int(r.element)][0] == "bench"]
    print(f"  run 5 GW5 XI: captain {names.get(cap5)[0]}; XI {xi5}; bench {b5}; XI pts {round(float(sum(p for _, p in xi5)), 2)}")
except Exception as e:
    print("  run 5 XI solve failed:", type(e).__name__, str(e)[:200])
    print("  run 5 GW5 e_points for the fifteen:", p5.sort_values("e_points", ascending=False)[["name", "e_points"]].round(2).values.tolist())

print("\n### 7. transfer proposal now vs run 5")
old = mt._q("SELECT plan_id, run_id, source, created_at, hits, bank_after, summary FROM model_transfer_plans WHERE run_id = 5 ORDER BY plan_id DESC LIMIT 1") if mt._q("SELECT 1 FROM information_schema.columns WHERE table_name='model_transfer_plans' AND column_name='summary'") else mt._q("SELECT * FROM model_transfer_plans WHERE run_id = 5 ORDER BY plan_id DESC LIMIT 1")
print("  latest stored proposal on run 5:", J(old[0]) if old else "none")
if old:
    print("  its transfers:", [J(t) for t in mt._q("SELECT * FROM model_transfers WHERE plan_id = %s ORDER BY step, transfer_out", (old[0]["plan_id"],))][:8])
prop = mt.propose_transfers(source="proof")
if "error" in prop:
    print("  propose_transfers error:", prop["error"])
else:
    print("  NEW proposal (run", prop.get("run_id"), "): keys", list(prop.keys())[:20])
    print("  ", J({k: prop.get(k) for k in ("proposal_id", "run_id", "predictions_as_of_cutoff_gw", "hits", "bank_after", "expected_gain", "summary", "next_deadline_transfers", "plan") if k in prop}))
