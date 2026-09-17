"""Bar 1b (fit at the live instant == fit at midnight of the cutoff day), robustly compared; and
WHICH club(s) the live fit prices near zero at steps >= 1, with their training rows. Read-only."""
import sys
import numpy as np
import pandas as pd
sys.path.insert(0, "/app"); sys.path.insert(0, "/app/squad"); sys.path.insert(0, "/app/eval")
import dixon_coles as dc                    # noqa: E402
import season_stack                          # noqa: E402
import walkforward_season as wfs             # noqa: E402

SEASON, GW = "2026-27", 5
full = pd.concat([pd.read_parquet(season_stack.stack_path()), pd.read_parquet(season_stack.forward_path())], ignore_index=True)
v = full[full["season"] == SEASON].copy(); v["kick"] = pd.to_datetime(v["kickoff_time"])
gw_start = v.groupby("GW")["kick"].min().sort_index(); gw_end = v.groupby("GW")["kick"].max().sort_index()
all_gws = sorted(gw_start.index.astype(int))
cutoff = gw_start.loc[GW].tz_localize(None)
odds_until = gw_end.loc[min(GW + wfs.ODDS_HORIZON_GWS, max(all_gws))].tz_localize(None)

a = dc.get_fixtures(predict_season=SEASON, cutoff_date=str(cutoff), odds_available_until=str(odds_until)); fa = dict(dc.LAST_FIT)
b = dc.get_fixtures(predict_season=SEASON, cutoff_date=str(cutoff.normalize()), odds_available_until=str(odds_until)); fb = dict(dc.LAST_FIT)
num = [c for c in a.columns if pd.api.types.is_numeric_dtype(a[c])]
same_num = a.shape == b.shape and all(np.array_equal(a[c].to_numpy(dtype=float), b[c].to_numpy(dtype=float), equal_nan=True) for c in num)
print(f"fixtures live-instant vs midnight: shapes {a.shape} / {b.shape}; all {len(num)} numeric columns bit-identical: {same_num}; "
      f"frames equal: {a.reset_index(drop=True).equals(b.reset_index(drop=True))}")
num_same = {k: fa[k] for k in fa if k != "ref_date"} == {k: fb[k] for k in fb if k != "ref_date"}
print("LAST_FIT numeric fields identical:", num_same, "(ref_date strings differ by construction:", fa["ref_date"], "vs", fb["ref_date"], ")")
print("LAST_FIT:", {k: (round(x, 6) if isinstance(x, float) else x) for k, x in fa.items()})
print("BAR 1b:", "MET" if (same_num and num_same) else "NOT MET")

# which clubs are priced near zero after the cutoff, and why
a["md"] = pd.to_datetime(a["match_date"])
fut = a[(a["md"] >= cutoff.normalize()) & (a["md"] <= gw_end.loc[min(GW + 5, max(all_gws))].tz_localize(None))]
low = fut[(fut["lam_home"] < 0.05) | (fut["lam_away"] < 0.05)][["match_date", "home", "away", "lam_home", "lam_away", "lambda_source"]]
print(f"fixtures from the cutoff day to GW{GW + 5} with a lambda < 0.05 ({len(low)}):")
print(low.to_string(index=False) if len(low) else "  none")
print("lambda_source counts on the window:", fut["lambda_source"].value_counts().to_dict())
m = dc._load_matches(SEASON)
tr = m[dc.knowable_before(m, cutoff)]
cur = tr[tr["season"] == SEASON]
teams = sorted(set(tr["home"]) | set(tr["away"]))
print(f"training rows {len(tr)}, teams {len(teams)}: {teams}")
gf = pd.concat([cur[["home", "home_goals"]].rename(columns={"home": "team", "home_goals": "g"}),
                cur[["away", "away_goals"]].rename(columns={"away": "team", "away_goals": "g"})])
rec = gf.groupby("team")["g"].agg(["count", "sum"]).rename(columns={"count": "matches_2026_27", "sum": "goals_2026_27"})
hist = m[m["season"] != SEASON]
rec["archive_rows_prior_seasons"] = [int(((hist["home"] == t) | (hist["away"] == t)).sum()) for t in rec.index]
print(rec.sort_values(["goals_2026_27", "matches_2026_27"]).head(8).to_string())
print("clubs in the 2026-27 fixtures not present in any prior season of the archive:",
      [t for t in set(cur["home"]) | set(cur["away"]) if not ((hist["home"] == t) | (hist["away"] == t)).any()])
