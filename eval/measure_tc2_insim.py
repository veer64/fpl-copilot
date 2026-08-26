#!/usr/bin/env python
"""In-sim Triple Captain 2 on the bonus-delete arm (p4 log section 12c (ii) rule: earliest second-half double
holding no other chip). Compares armlog_{season}_bonusdel_tc2 against armlog_{season}_bonusdel gameweek by
gameweek: squads, transfers and captains must be identical (the MIP has no chip variable, so a scheduled TC
cannot change a decision) and the only difference is the extra captain multiple at the TC2 week.

    uv run python eval/measure_tc2_insim.py
"""
import json
import sys
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "squad")); sys.path.insert(0, str(REPO / "eval"))
from chip_legality import check_chip_schedule  # noqa: E402
import measure_arms_full_system as m  # noqa: E402

SEASONS = [("2023-24", "2023_24"), ("2024-25", "2024_25"), ("2025-26", "2025_26")]
REF_CHIP = {"2023-24": 2296, "2024-25": 2294, "2025-26": 2206}   # OLD-convention reference (fslog base_wc2); the bonusdel_tc2 rows ARE the reference of record since 2026-08-26
DEL_CHIP = {"2023-24": 2241, "2024-25": 2277, "2025-26": 2261}


def els(e):
    return sorted(int(x) for x in (json.loads(e) if isinstance(e, str) else e))


def main():
    for season, tag in SEASONS:
        base = m.mfs.load(REPO / "data" / "arms" / f"armlog_{tag}_bonusdel.parquet")
        tc = m.mfs.load(REPO / "data" / "arms" / f"armlog_{tag}_bonusdel_tc2.parquet")
        tc2 = int(tc["tc2_gw"].iloc[0]); assert tc2 > 0
        ref = m.mfs.load(REPO / "data" / "p1" / f"fslog_{tag}_base_wc2.parquet")
        wc1, wc2, fh2, bb1, bb2 = 2, int(ref.wc2.iloc[0]), int(ref.fh2.iloc[0]), int(ref.bb1.iloc[0]), int(ref.bb2.iloc[0])
        # path identity check
        same_sq = all(els(base.loc[g, "elements"]) == els(tc.loc[g, "elements"]) for g in base.index)
        same_tr = all(base.loc[g, "all_transfers"] == tc.loc[g, "all_transfers"] for g in base.index)
        same_cap = all(str(base.loc[g, "captain"]) == str(tc.loc[g, "captain"]) for g in base.index)
        diff_pts = {int(g): int(tc.loc[g, "points"] - base.loc[g, "points"]) for g in base.index if tc.loc[g, "points"] != base.loc[g, "points"]}
        # reads
        cap = m.cap_pred_arm(season, "bonusdel")
        b1, b2, tc1_gw, tc1, _ = m.chip_reads(tc, tc, cap, wc1, wc2, fh2, bb1, bb2, 1)
        bb1_, bb2_, tc1gw_, tc1_, _ = m.chip_reads(base, base, cap, wc1, wc2, fh2, bb1, bb2, 1)
        path_tc, path_base = int(tc.final_total.iloc[0]), int(base.final_total.iloc[0])
        tc2_read = int(tc.loc[tc2, "captain_bonus"] - base.loc[tc2, "captain_bonus"])
        chip_tc = path_tc + b1 + b2 + tc1
        # captain at the deadline: the MIP's cap variable = argmax step-0 e_points in the XI at cutoff tc2
        wf = pd.read_parquet(REPO / "data" / f"walkforward_h6_{tag}_bonusdel.parquet", columns=["cutoff", "gw", "element", "name", "e_points", "n_fixtures"])
        own = wf[(wf.cutoff == tc2) & (wf.gw == tc2)].set_index("element")
        squad = els(tc.loc[tc2, "elements"])
        capname = str(tc.loc[tc2, "captain"]); caprow = own[own.name == capname]
        top = own.loc[[e for e in squad if e in own.index]].sort_values("e_points", ascending=False).head(3)
        check_chip_schedule({"wildcard": [wc1, wc2], "free_hit": [fh2], "bench_boost": [bb1, bb2], "triple_captain": [tc2, tc1_gw]},
                            played_gws=set(int(g) for g in tc.index), source=f"bonusdel_tc2 {season}")
        print(f"\n== {season}: TC2 in-sim at GW{tc2} (eligible-doubles rule; chip weeks WC {wc1},{wc2} FH {fh2} BB {bb1},{bb2} TC1 GW{tc1_gw}) -- legality PASS")
        print(f"   path identical to the delete arm? squads {same_sq}, transfers {same_tr}, captains {same_cap}; per-gw point differences: {diff_pts}")
        print(f"   captain at GW{tc2} deadline: {capname} (own-cutoff e_points {float(caprow.e_points.iloc[0]) if len(caprow) else float('nan'):.2f}, "
              f"doubling {int(caprow.n_fixtures.iloc[0]) if len(caprow) else '?'} fixtures); top-3 in squad by step-0 e_points: "
              + ", ".join(f"{r.name} {r.e_points:.2f} (x{int(r.n_fixtures)})" for r in top.itertuples()))
        print(f"   doubled role at GW{tc2}: {tc.loc[tc2, 'doubled_role']}; TC2 read (extra captain multiple) = {tc2_read}; delete-arm captain_bonus that week {int(base.loc[tc2, 'captain_bonus'])}")
        print(f"   path: delete {path_base} -> delete+TC2 {path_tc} ({path_tc - path_base:+d}, of which TC2 read {tc2_read}, path movement {path_tc - path_base - tc2_read:+d})")
        print(f"   chip reads (own): BB1@{bb1} +{b1} (delete arm +{bb1_}), BB2@{bb2} +{b2} (+{bb2_}), TC1@GW{tc1_gw} +{tc1} (+{tc1_}); TC2 now IN the path")
        print(f"   chip-inclusive: delete+TC2 **{chip_tc}** vs delete {DEL_CHIP[season]} ({chip_tc - DEL_CHIP[season]:+d}) vs reference {REF_CHIP[season]} ({chip_tc - REF_CHIP[season]:+d})")


if __name__ == "__main__":
    main()
