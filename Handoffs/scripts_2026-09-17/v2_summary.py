"""Compact table over the endpoint JSONs: the primary form (ref_v2) and the sensitivity rows."""
import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
HERE = Path(__file__).resolve().parent
rows = []
for label in sys.argv[1:] or ["ref_v2", "ref_n6", "ref_n15", "ref_tau28", "ref_box3", "ref_box6"]:
    p = HERE / f"v2_endpoint_{label}.json"
    if not p.exists():
        print(f"{label}: (no endpoint yet)"); continue
    r = json.loads(p.read_text(encoding="utf-8"))
    P = r["pooled"]
    conv = all(S["all_converged"] for S in r["seasons"].values())
    lam_min = min(S["lambda_min"]["value"] for S in r["seasons"].values())
    margin = min(S["min_margin_to_bound"]["margin"] for S in r["seasons"].values() if S["min_margin_to_bound"]["margin"] is not None)
    boxed = {s: list(S["boxed_cutoffs"].keys()) for s, S in r["seasons"].items() if S["boxed_cutoffs"]}
    unaff = all(S["unaffected_bit_identical"] for S in r["seasons"].values())
    pcs_max = max(S["step0_pcs"]["max_abs_delta"] for S in r["seasons"].values())
    pcs_clean = max(S["step0_pcs"]["max_delta_no_affected_club"] for S in r["seasons"].values())
    per = {s: (S["season_means"]["starters"]["delta"], S["season_means"]["top30"]["delta"]) for s, S in r["seasons"].items()}
    print(f"{label:9s} cells {P['cells']:3d} | starters d {P['starters']['delta']:+.4f} SE {P['starters']['se']:.4f} ({P['starters']['delta_over_se']:+.1f} SE)"
          f" | top30 d {P['top30']['delta']:+.4f} SE {P['top30']['se']:.4f} ({P['top30']['delta_over_se']:+.1f} SE)"
          f" | conv {conv} lam_min {lam_min:.3f} margin {margin:.2f} unaff_bitid {unaff} pcs_max {pcs_max:.3f} pcs_clean_max {pcs_clean:.4f} boxed {boxed}")
    print("          per season (starters, top30):", {s: (f"{a:+.4f}", f"{b:+.4f}") for s, (a, b) in per.items()},
          "| verdict:", r["verdict"], "| stops:", r["stops"], "| tells:", r["tells"])
