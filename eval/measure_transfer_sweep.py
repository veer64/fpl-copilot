# measure_transfer_sweep.py
# Overnight stage 3/4 -- path-free endpoints over the transfer sweep, plus
# season totals under the standard framing.
#
# Endpoints per configuration (season x variant x H x decay):
#   E1  corr(predicted gain, realized gain) across transfers taken --
#       Pearson and Spearman. Predicted gain = the MIP's own objective grain:
#       decayed H-window sum of (e_points_in - e_points_out) at the transfer's
#       cutoff, from the SAME walkforward file the config planned on. Missing
#       rows price as 0 (matches _pool_with_owned semantics).
#   E2  realized gain per transfer over the H-window, UNDECAYED, truncated at
#       season end: mean, median, p10/p90, share > 0, n. The full per-transfer
#       table is written to data/sweep/transfer_table.parquet.
#   E3  transfers and hit points taken.
#   E4  realized gain on transfers this config declined but at least one other
#       config took at the same gameweek (same season), evaluated over a FIXED
#       3-gameweek window as the common yardstick (configs differ in H; a
#       per-config window would make the columns incomparable).
#
# Season totals are printed LAST with the standard framing: they identify the
# config, they are not evidence, and they are not comparable to any earlier
# figure (equation inputs changed: DC-wiring fix #15).
#
# Usage: uv run python eval/measure_transfer_sweep.py

import json
import sys
from itertools import product
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import pearsonr, spearmanr

REPO = Path(__file__).resolve().parent.parent
SWEEP = REPO / "data" / "sweep"
SEASONS = ["2023-24", "2024-25", "2025-26"]
DECLINE_WINDOW = 3          # fixed common yardstick for E4


def realized_actuals(tag):
    """(element, gw) -> realized points, from the canonical file's step-0 rows."""
    wf = pd.read_parquet(REPO / "data" / f"walkforward_h6_{tag}.parquet",
                         columns=["element", "gw", "horizon_step",
                                  "actual_points"])
    s0 = wf[wf["horizon_step"] == 0].copy()
    s0["actual_points"] = pd.to_numeric(s0["actual_points"],
                                        errors="coerce").fillna(0.0)
    return s0.drop_duplicates(["element", "gw"]).set_index(
        ["element", "gw"])["actual_points"]


def predictions(tag, variant):
    """(cutoff, gw, element) -> e_points from the file the config planned on."""
    name = f"walkforward_h6_{tag}.parquet" if variant == "base" \
        else f"walkforward_h6_{tag}_synth.parquet"
    wf = pd.read_parquet(REPO / "data" / name,
                         columns=["cutoff", "gw", "element", "e_points"])
    return wf.set_index(["cutoff", "gw", "element"])["e_points"]


def window_sum(series_idx, element, gws, cutoff=None, decay=None):
    total, w = 0.0, 1.0
    for g in gws:
        key = (cutoff, g, element) if cutoff is not None else (element, g)
        v = series_idx.get(key, 0.0)
        total += w * (0.0 if pd.isna(v) else float(v))
        if decay is not None:
            w *= decay
    return total


def main():
    logs = sorted(SWEEP.glob("simlog_*.parquet"))
    if not logs:
        raise SystemExit("no sweep logs found under data/sweep/")
    print(f"{len(logs)} sweep logs found")

    acts = {}
    preds = {}
    transfer_rows = []
    config_rows = []

    for p in logs:
        log = pd.read_parquet(p)
        season = log["season"].iloc[0]
        variant = log["variant"].iloc[0]
        H = int(log["horizon"].iloc[0])
        decay = float(log["decay"].iloc[0])
        tag = season.replace("-", "_")
        max_gw = int(log["gw"].max())
        if tag not in acts:
            acts[tag] = realized_actuals(tag)
        if (tag, variant) not in preds:
            preds[(tag, variant)] = predictions(tag, variant)

        for _, row in log.iterrows():
            g = int(row["gw"])
            for out_e, in_e in json.loads(row["all_transfers"]):
                h_gws = [x for x in range(g, g + H) if x <= max_gw]
                pred = (window_sum(preds[(tag, variant)], in_e, h_gws,
                                   cutoff=g, decay=decay)
                        - window_sum(preds[(tag, variant)], out_e, h_gws,
                                     cutoff=g, decay=decay))
                real = (window_sum(acts[tag], in_e, h_gws)
                        - window_sum(acts[tag], out_e, h_gws))
                w3 = [x for x in range(g, g + DECLINE_WINDOW) if x <= max_gw]
                real3 = (window_sum(acts[tag], in_e, w3)
                         - window_sum(acts[tag], out_e, w3))
                transfer_rows.append({
                    "season": season, "variant": variant, "H": H,
                    "decay": decay, "gw": g, "out": out_e, "in": in_e,
                    "pred_gain": pred, "real_gain": real, "real_gain_3": real3,
                    "truncated": len(h_gws) < H})
        config_rows.append({
            "season": season, "variant": variant, "H": H, "decay": decay,
            "total": int(log["final_total"].iloc[0]),
            "transfers": int(log["n_transfers"].sum()),
            "hit_pts": int(log["hit"].sum())})

    tr = pd.DataFrame(transfer_rows)
    cfg = pd.DataFrame(config_rows).sort_values(
        ["season", "variant", "H", "decay"])
    tr.to_parquet(SWEEP / "transfer_table.parquet", index=False)
    print(f"transfer table: {len(tr)} transfers -> data/sweep/transfer_table.parquet")

    # --- E1 + E2 ---------------------------------------------------------
    print("\n=== E1/E2: per config -- corr(pred, real) and realized-gain "
          "distribution (H-window, undecayed) ===")
    print(f"{'season':<9}{'var':<7}{'H':>2}{'dec':>5} {'n':>4} {'pear':>7} "
          f"{'spear':>7} {'mean':>7} {'med':>6} {'p10':>7} {'p90':>6} "
          f"{'%>0':>5} {'trunc':>6}")
    for (season, variant, H, decay), g in tr.groupby(
            ["season", "variant", "H", "decay"]):
        pear = pearsonr(g["pred_gain"], g["real_gain"])[0] if len(g) > 2 else np.nan
        spear = spearmanr(g["pred_gain"], g["real_gain"])[0] if len(g) > 2 else np.nan
        print(f"{season:<9}{variant:<7}{H:>2}{decay:>5.2f} {len(g):>4} "
              f"{pear:>7.3f} {spear:>7.3f} {g['real_gain'].mean():>7.2f} "
              f"{g['real_gain'].median():>6.2f} "
              f"{g['real_gain'].quantile(0.1):>7.2f} "
              f"{g['real_gain'].quantile(0.9):>6.2f} "
              f"{(g['real_gain'] > 0).mean():>5.0%} "
              f"{g['truncated'].mean():>6.0%}")

    # --- E3 --------------------------------------------------------------
    print("\n=== E3: transfers and hit points taken ===")
    print(cfg.to_string(index=False))

    # --- E4 --------------------------------------------------------------
    print(f"\n=== E4: declined transfers -- taken by another config at the "
          f"same gw, not by this one (realized over fixed {DECLINE_WINDOW}-gw "
          f"window) ===")
    print(f"{'season':<9}{'var':<7}{'H':>2}{'dec':>5} {'n_declined':>10} "
          f"{'mean':>7} {'med':>6} {'%>0':>5}")
    for season in SEASONS:
        ts = tr[tr["season"] == season]
        if len(ts) == 0:
            continue
        all_tuples = ts[["variant", "H", "decay", "gw", "out", "in",
                         "real_gain_3"]].copy()
        for (variant, H, decay), g in ts.groupby(["variant", "H", "decay"]):
            mine = set(zip(g["gw"], g["out"], g["in"]))
            others = all_tuples[~all_tuples.apply(
                lambda r: (r["gw"], r["out"], r["in"]) in mine, axis=1)]
            others = others.drop_duplicates(["gw", "out", "in"])
            if len(others) == 0:
                continue
            print(f"{season:<9}{variant:<7}{H:>2}{decay:>5.2f} "
                  f"{len(others):>10} {others['real_gain_3'].mean():>7.2f} "
                  f"{others['real_gain_3'].median():>6.2f} "
                  f"{(others['real_gain_3'] > 0).mean():>5.0%}")

    # --- stage 4: totals, framing mandatory ------------------------------
    print("\n=== STAGE 4: season totals -- SANITY FRAMING ONLY ===")
    print("These identify each configuration's run. They are NOT evidence")
    print("(M1 failed; path noise sd ~ 60), NOT comparable to 2060/2028/1984")
    print("or any earlier figure (equation inputs changed: KNOWN_ISSUES #15),")
    print("and no winner may be picked on them. An earlier decay sweep's")
    print("monotone pattern evaporated after two unrelated bugfixes.")
    piv = cfg.pivot_table(index=["season", "H", "decay"], columns="variant",
                          values="total", aggfunc="first")
    print(piv.to_string())


if __name__ == "__main__":
    main()
