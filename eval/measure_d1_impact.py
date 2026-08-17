#!/usr/bin/env python
"""
Measure D1 impact: starter-band Spearman within positions across all three seasons.
Compare before (no D1 terms) and after (with D1 terms).

This is a minimal measurement: it rebuilds just enough to isolate D1's effect.
"""

import pandas as pd
import numpy as np
from scipy.stats import spearmanr

BASE = r"C:\Users\veers\OneDrive\Documents\FPL Agent\fpl-copilot"

def evaluate_by_position(df, title):
    """Compute starter-band Spearman and MAE by position."""
    # All rows: full picture
    all_rows = df.dropna(subset=["e_points", "actual_points"]).copy()
    all_rows["band"] = pd.cut(all_rows["e_minutes"], [0, 15, 45, 70, 90],
                               labels=["<15", "15-45", "45-70", "70+"])

    # Starter-only band (60+ minutes): what matters for decisions
    starters = all_rows[all_rows["e_minutes"] >= 60].copy()

    print(f"\n{title}")
    print("=" * 80)
    print(f"Overall metrics (all rows, n={len(all_rows)}):")
    if len(all_rows) > 0:
        print(f"  Spearman: {spearmanr(all_rows['e_points'], all_rows['actual_points']).correlation:.4f}")
        print(f"  MAE: {(all_rows['e_points'] - all_rows['actual_points']).abs().mean():.3f}")

    print(f"\nStarter band (60+ min, n={len(starters)}):")
    if len(starters) > 0:
        print(f"  Spearman: {spearmanr(starters['e_points'], starters['actual_points']).correlation:.4f}")
        print(f"  MAE: {(starters['e_points'] - starters['actual_points']).abs().mean():.3f}")

    print("\nBy position (starter band only):")
    for pos in ["GK", "DEF", "MID", "FWD"]:
        pos_data = starters[starters["position"] == pos]
        if len(pos_data) > 0:
            s = spearmanr(pos_data["e_points"], pos_data["actual_points"]).correlation
            mae = (pos_data["e_points"] - pos_data["actual_points"]).abs().mean()
            print(f"  {pos:3s} (n={len(pos_data):5d}): Spearman {s:.4f}  MAE {mae:.3f}")


if __name__ == "__main__":
    print("D1 Impact Measurement")
    print("Starter-band Spearman by position, all three seasons")

    # Load current (with D1)
    try:
        preds_2526 = pd.read_parquet(BASE + r"\data\walkforward_h6_2526.parquet")
        preds_2324 = pd.read_parquet(BASE + r"\data\walkforward_h6_2023_24.parquet")
        preds_2425 = pd.read_parquet(BASE + r"\data\walkforward_h6_2024_25.parquet")
        print("\nLoaded walkforward files (baseline from handoff)")
    except:
        print("\nNote: walkforward files don't exist yet. Using predictions_2526.parquet for 2025-26 only.")
        preds_2526 = pd.read_parquet(BASE + r"\data\predictions_2526.parquet")
        preds_2324 = None
        preds_2425 = None

    # Evaluate 2025-26
    if preds_2526 is not None and len(preds_2526) > 0:
        evaluate_by_position(preds_2526, "2025-26 (sealed test)")

    # Evaluate 2024-25 if available
    if preds_2425 is not None and len(preds_2425) > 0:
        evaluate_by_position(preds_2425, "2024-25 (validation)")

    # Evaluate 2023-24 if available
    if preds_2324 is not None and len(preds_2324) > 0:
        evaluate_by_position(preds_2324, "2023-24 (historical)")

    print("\n" + "=" * 80)
    print("Note: full historical walkforward files needed for before/after comparison.")
    print("D1 implementation is now complete. Regenerate walkforward_h6_* files to measure.")
