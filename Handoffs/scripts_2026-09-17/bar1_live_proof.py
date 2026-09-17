"""Bar item 1 (prereg section 5.1), run INSIDE the deployed scheduler image, read-only:
(a) a strict baseline build of the live cutoff at horizon 6 -> distinct team_lambda per step
    (>= 18 at every step >= 1), the strict postflight passes, and injected degeneracy raises;
(b) the fit at the live cutoff instant equals the fit at midnight of the cutoff day (the
    'healthy reproduction' of 2026-09-13): fixture lambdas bit-identical, LAST_FIT identical;
(c) LAST_FIT printed (n_train, iterations, converged, max|attack|, home_adv, rho)."""
import sys
import numpy as np
import pandas as pd
sys.path.insert(0, "/app"); sys.path.insert(0, "/app/squad"); sys.path.insert(0, "/app/eval")
import dixon_coles as dc                    # noqa: E402
import live_deadline as ld                  # noqa: E402
import season_stack                          # noqa: E402
import walkforward_season as wfs             # noqa: E402

SEASON, GW = "2026-27", 5
print("image code:", open("/app/squad/dixon_coles.py").read().count("knowable_before"), "mentions of knowable_before")

frame, findings = ld.build_deadline_frame(SEASON, GW, strict=True, config="baseline", horizon=6)
print(f"strict baseline build GW{GW} H6: {len(frame)} rows; findings: {findings if findings else '(none)'}")
fit = dict(dc.LAST_FIT)
print("LAST_FIT:", {k: (round(v, 6) if isinstance(v, float) else v) for k, v in fit.items()})
for st, s in frame.groupby("horizon_step"):
    lam = s.groupby("team")["team_lambda"].first().dropna()
    print(f"  step {st} (gw {int(s['gw'].iloc[0])}): {lam.round(6).nunique()} distinct team_lambda over {len(lam)} clubs; "
          f"min {lam.min():.3f} max {lam.max():.3f}")
ok = all(s.groupby("team")["team_lambda"].first().dropna().round(6).nunique() >= 18
         for st, s in frame.groupby("horizon_step") if st >= 1)
print("BAR 1a distinct >= 18 at every step >= 1:", "MET" if ok else "NOT MET")

# the detector: passes on the real frame, raises on injected degeneracy
ld.postflight(frame, SEASON, GW, strict=True, horizon=6)
print("strict postflight on the live frame: passed")
bad = frame.copy()
m1 = bad["horizon_step"] == 1
teams = sorted(bad.loc[m1, "team"].dropna().unique())
inj = {t: (float(np.exp(0.25)) if i % 2 == 0 else 1.0) for i, t in enumerate(teams)}
bad.loc[m1, "team_lambda"] = bad.loc[m1, "team"].map(inj)
try:
    ld.postflight(bad, SEASON, GW, strict=True, horizon=6)
    print("BAR 1 detector: NOT MET -- injected degeneracy did not raise")
except ld.LiveStrictError as e:
    print("injected degeneracy raised under strict:", str(e)[:120])

# (b) healthy reproduction: live instant vs midnight of the cutoff day, same code
full = pd.concat([pd.read_parquet(season_stack.stack_path()), pd.read_parquet(season_stack.forward_path())], ignore_index=True)
v = full[full["season"] == SEASON].copy(); v["kick"] = pd.to_datetime(v["kickoff_time"])
gw_start = v.groupby("GW")["kick"].min().sort_index(); gw_end = v.groupby("GW")["kick"].max().sort_index()
all_gws = sorted(gw_start.index.astype(int))
cutoff = gw_start.loc[GW].tz_localize(None)
odds_until = gw_end.loc[min(GW + wfs.ODDS_HORIZON_GWS, max(all_gws))].tz_localize(None)
print(f"live cutoff instant {cutoff}; odds_until {odds_until}")
a = dc.get_fixtures(predict_season=SEASON, cutoff_date=str(cutoff), odds_available_until=str(odds_until)); fa = dict(dc.LAST_FIT)
b = dc.get_fixtures(predict_season=SEASON, cutoff_date=str(cutoff.normalize()), odds_available_until=str(odds_until)); fb = dict(dc.LAST_FIT)
lamcols = [c for c in a.columns if "lam" in c.lower()]
same = a.shape == b.shape and all(np.array_equal(a[c].to_numpy(), b[c].to_numpy(), equal_nan=True) for c in lamcols)
print(f"fixtures at the live instant vs midnight: {a.shape} vs {b.shape}; lambda columns {lamcols} bit-identical: {same}")
print("LAST_FIT identical:", fa == fb, "| n_train", fa.get("n_train"), "iterations", fa.get("iterations"), "converged", fa.get("converged"))
print("BAR 1b (bit-identical to the healthy reproduction):", "MET" if (same and fa == fb) else "NOT MET")
# the old-rule fit at midnight, called directly (the finding's healthy reproduction, same rows)
m = dc._load_matches(SEASON)
old_rows = m[m["date_parsed"] < cutoff.normalize()]
teams_all = sorted(set(old_rows["home"]) | set(old_rows["away"]))
print("old-rule midnight training rows:", len(old_rows), "(new rule:", int(dc.knowable_before(m, cutoff).sum()), ")")
