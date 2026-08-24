"""Audits null-market-input rows (p_cs / opp_lambda NaN) by season, position and e_minutes band, what fills them, and whether their fixtures exist in the odds source. Result of record: Logs/gk_investigation_log.md §7 (open side-finding). Report only.

GK investigation -- null-market-input rows audit. REPORT ONLY.

Q1: how many rows have null p_cs or opp_lambda, per season, by position and
    e_minutes band (step 0)
Q2: which fixtures they belong to, and are those fixtures absent from the odds
    source (data/history/odds_all_seasons.parquet)
Q3: what those rows' e_points/pts_cs/pts_conceded/fixture_scale actually hold
    (verifying the NaN-sum-to-zero mechanism flagged in assembly.py:287-293)
"""
import numpy as np
import pandas as pd

from pathlib import Path
BASE = str(Path(__file__).resolve().parent.parent)  # repo root; rescued 2026-08-24 from a hardcoded absolute path
FILES = {
    "2025-26": r"\data\walkforward_h6_2025_26.parquet",
    "2024-25": r"\data\walkforward_h6_2024_25.parquet",
    "2023-24": r"\data\walkforward_h6_2023_24.parquet",
}

odds = pd.read_parquet(BASE + r"\data\history\odds_all_seasons.parquet")
odds["Date"] = pd.to_datetime(odds["Date"]).dt.date
print("odds file seasons:", sorted(odds["season"].unique()))
print("odds columns sample:", list(odds.columns)[:12])

for season, path in FILES.items():
    df = pd.read_parquet(BASE + path)
    d = df[df["horizon_step"] == 0].copy()
    d["actual_points"] = pd.to_numeric(d["actual_points"], errors="coerce")
    d = d.dropna(subset=["e_points", "actual_points"])
    nul = d[d["p_cs"].isna() | d["opp_lambda"].isna()]
    print(f"\n=== {season} === step-0 rows {len(d)}, null-market rows {len(nul)} "
          f"({len(nul)/len(d):.1%})")
    if not len(nul):
        continue

    d["band"] = pd.cut(d["e_minutes"], [-1, 15, 45, 60, 200],
                       labels=["<15", "15-45", "45-60", "60+"])
    nulb = d.loc[nul.index]
    print("by position x e_minutes band:")
    print(pd.crosstab(nulb["position"], nulb["band"]))

    print("\nwhat fills those rows (starter band only):")
    st = nulb[nulb["e_minutes"] >= 60]
    for c in ["e_points", "pts_cs", "pts_conceded", "fixture_scale",
              "pts_appear", "exp_bonus"]:
        if c in st.columns:
            print(f"  {c:13s} mean {st[c].mean():8.3f}  min {st[c].min():8.3f}  "
                  f"max {st[c].max():8.3f}  n_null {int(st[c].isna().sum())}")
    print(f"  actual_points mean {st['actual_points'].mean():.3f} (these are real "
          f"starters: realised minutes mean {st['minutes'].mean():.0f})")

    gwcol = [c for c in ("gw",) if c in nul.columns][0]
    keys = [k for k in ("team", "opponent", "match_date", "fixture") if k in nul.columns]
    print(f"\nfixtures involved (by {['gw'] + keys}):")
    fx = (nul.groupby([gwcol] + keys, dropna=False).size()
          .rename("n_rows").reset_index().sort_values("n_rows", ascending=False))
    print(fx.head(15).to_string(index=False))

    # check against odds source
    if "team" in nul.columns and "match_date" in nul.columns:
        seas_odds = odds[odds["season"] == season]
        fx["md"] = pd.to_datetime(fx["match_date"]).dt.date
        fx["in_odds_by_date"] = fx.apply(
            lambda r: bool(((seas_odds["Date"] == r["md"]) &
                            ((seas_odds["HomeTeam"] == r["team"]) |
                             (seas_odds["AwayTeam"] == r["team"]))).any()), axis=1)
        fx["team_any_odds_that_gw_pm3d"] = fx.apply(
            lambda r: bool((((seas_odds["HomeTeam"] == r["team"]) |
                             (seas_odds["AwayTeam"] == r["team"])) &
                            (abs(pd.to_datetime(seas_odds["Date"])
                                 - pd.Timestamp(r["md"])).dt.days <= 3)).any()), axis=1)
        print("\nodds-source check (exact team+date match, and any odds within 3 days):")
        print(fx[[gwcol, "team", "md", "n_rows", "in_odds_by_date",
                  "team_any_odds_that_gw_pm3d"]].head(15).to_string(index=False))
