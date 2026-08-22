# value_teamnews_cases.py
# Team-news investigation, STEP 3 parts B+C: value the cases WITHOUT any
# simulation, by exact replay of the baseline weeks.
#
# Per-case metric -- "bench-bounded recoverable value", stated precisely:
# the points an informed manager (who knows ONLY that the player will not
# play) recovers by starting the best formation-legal bench alternative,
# MINUS what the autosub system already recovered on the realized path.
#   - autosub fired for the case player: value = max(0, best_alt - sub_pts)
#   - no sub fired (dead XI slot):        value = best_alt (0 if none legal)
#   - captaincy: FPL's armband auto-passes to the vice when the captain
#     blanks -- which is the same "next-best predicted" choice an informed
#     manager would make, so the captaincy increment is ~0 UNLESS the vice
#     also blanked (doubled_role == 'none'), in which case the increment is
#     the best legal starter's actual points (they would carry the band).
# This is a LOWER bound per case: it excludes transfer-out recovery (a free
# transfer to any market player) and better-than-vice captain picks. It is
# also OPTIMISTIC in one way, stated: "best bench alternative" uses realized
# points, i.e. perfect selection among the (usually 2-3) legal bench options.
#
# XI reconstruction = the verified replay (formation-legal argmax of
# own-cutoff e_points; production assign_bench_order, gates off); fidelity
# asserted per case week against raw_points/bench_points/n_subs.
#
# Tiers: floor = the 10 verified cases; middle = all 24 auto pre-deadline
# cases x the verified precision (10/24); ceiling = all 52 (perfect team
# news -- the oracle bound for step 4).
# Usage: uv run python eval/value_teamnews_cases.py

import json
import sys
from itertools import product
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "squad"))
from scoring import assign_bench_order, score_gameweek, _legal_after_swap  # noqa: E402

FORMATIONS = [(d, m, f) for d, m, f in product(range(3, 6), range(2, 6),
                                               range(1, 4)) if d + m + f == 10]
VERIFIED = {("2024-25", 5, "Kevin De Bruyne"),
            ("2024-25", 14, "Gabriel dos Santos Magalhães"),
            ("2024-25", 11, "Manuel Akanji"),
            ("2023-24", 16, "Erling Haaland"),
            ("2024-25", 28, "Emiliano Martínez Romero"),
            ("2023-24", 34, "Malo Gusto"),
            ("2024-25", 29, "Cole Palmer"),
            ("2024-25", 19, "Kai Havertz"),
            ("2025-26", 30, "Ibrahima Konaté"),
            ("2025-26", 28, "Erling Haaland")}


def build_squad_frame(elements, own_gw, pos, name):
    ep = own_gw.set_index("element")["e_points"].to_dict()
    sq = pd.DataFrame([{"element": e, "position": pos[e],
                        "name": name.get(e, str(e)),
                        "e_points": float(ep.get(e, 0.0)
                                          if pd.notna(ep.get(e, 0.0)) else 0.0)}
                       for e in elements])
    by = {p: sq[sq["position"] == p].sort_values("e_points", ascending=False)
          for p in ("GK", "DEF", "MID", "FWD")}
    best, bv = None, -1e18
    for d, m, f in FORMATIONS:
        if len(by["DEF"]) < d or len(by["MID"]) < m or len(by["FWD"]) < f:
            continue
        xi = pd.concat([by["GK"].head(1), by["DEF"].head(d),
                        by["MID"].head(m), by["FWD"].head(f)])
        if xi["e_points"].sum() > bv:
            best, bv = xi, xi["e_points"].sum()
    xie = set(best["element"])
    sq["role"] = sq["element"].map(lambda e: "start" if e in xie else "bench")
    st = sq[sq["role"] == "start"].sort_values("e_points", ascending=False)
    sq.loc[sq["element"] == st.iloc[0]["element"], "role"] = "CAPTAIN"
    sq.loc[sq["element"] == st.iloc[1]["element"], "role"] = "VICE"
    return assign_bench_order(sq)


def main():
    cases = pd.read_parquet(REPO / "data/teamnews/case_list.parquet")
    guard = pd.read_parquet(REPO / "data/teamnews/guardian_passages.parquet")
    cls = guard.set_index(["season", "gw", "element"])["classification"]
    rows = []
    for season in ["2023-24", "2024-25", "2025-26"]:
        tag = season.replace("-", "_")
        log = pd.read_parquet(REPO / "data/p1" / f"p1log_{tag}_base.parquet")
        log["elements"] = log["elements"].map(json.loads)
        log = log.set_index("gw")
        wf = pd.read_parquet(REPO / "data" / f"walkforward_h6_{tag}.parquet",
                             columns=["cutoff", "gw", "element", "name",
                                      "position", "e_points",
                                      "actual_points", "minutes"])
        own = wf[wf["cutoff"] == wf["gw"]]
        act = wf.drop_duplicates(subset=["gw", "element"]).copy()
        for c in ("actual_points", "minutes"):
            act[c] = pd.to_numeric(act[c], errors="coerce").fillna(0)
        pos = wf.drop_duplicates("element").set_index("element")["position"].to_dict()
        name = wf.drop_duplicates("element").set_index("element")["name"].to_dict()

        for _, cse in cases[cases["season"] == season].iterrows():
            gw, e = int(cse["gw"]), int(cse["element"])
            lrow = log.loc[gw]
            sq = build_squad_frame(list(lrow["elements"]),
                                   own[own["gw"] == gw], pos, name)
            a = act[act["gw"] == gw][["element", "minutes", "actual_points"]] \
                .rename(columns={"actual_points": "total_points"})
            res = score_gameweek(sq, a, transfers_made=0, free_transfers=15)
            ok = (res["raw_points"] == lrow["raw_points"]
                  and res["bench_points"] == lrow["bench_points"]
                  and len(res["subs_made"]) == lrow["n_subs"])
            mins = dict(zip(a["element"], a["minutes"]))
            pts = dict(zip(a["element"], a["total_points"]))
            case_pos = pos[e]
            sub_in = next((i for o, i in res["subs_made"] if o == e), None)
            hole = e in res["final_xi"]
            # legal bench alternatives for the case slot (played only),
            # excluding subs consumed by OTHER holes
            used_elsewhere = {i for o, i in res["subs_made"] if o != e}
            bench_e = [b for b in sq.loc[sq["role"] == "bench", "element"]
                       if b not in used_elsewhere and mins.get(b, 0) > 0]
            xi_pos = [pos[x] for x in res["final_xi"]]
            legal = []
            for b in bench_e:
                if (pos[b] == "GK") != (case_pos == "GK"):
                    continue
                base_pos = xi_pos if hole else xi_pos + [case_pos]
                if _legal_after_swap(base_pos, case_pos, pos[b]) \
                        or pos[b] == case_pos:
                    legal.append(b)
            best_alt = max((pts.get(b, 0) for b in legal), default=0)
            if sub_in is not None:
                value = max(0.0, best_alt - pts.get(sub_in, 0))
                mode = f"autosub ({name.get(sub_in)} scored {pts.get(sub_in, 0):.0f})"
            elif hole:
                value = float(best_alt)
                mode = "dead XI slot"
            else:
                value, mode = 0.0, "was on bench (no XI cost)"
            cap_inc = 0.0
            if cse["captained"]:
                if lrow["doubled_role"] == "none":
                    alive = [x for x in res["final_xi"] if mins.get(x, 0) > 0]
                    cap_inc = max((pts.get(x, 0) for x in alive), default=0)
                mode += f" | captained, armband->{lrow['doubled_role']}"
            c = cls.get((season, gw, e), "no_coverage")
            rows.append({"season": season, "gw": gw, "player": cse["player"],
                         "group": cse["group"], "classification": c,
                         "verified": (season, gw, cse["player"]) in VERIFIED,
                         "value": round(value + cap_inc, 1),
                         "cap_increment": round(cap_inc, 1),
                         "mode": mode, "fidelity_ok": bool(ok)})

    df = pd.DataFrame(rows)
    df.to_parquet(REPO / "data/teamnews/case_values.parquet", index=False)
    print(f"fidelity: {int(df['fidelity_ok'].sum())}/{len(df)} case-weeks "
          "replayed exactly")
    print("\nPer verified case:")
    v = df[df["verified"]]
    print(v[["season", "gw", "player", "value", "mode"]]
          .to_string(index=False))
    print("\nBench-bounded value by tier (per season / pooled):")
    pre = df[df["classification"] == "pre_deadline_signal"]
    prec = len(v) / len(pre)
    for label, sub, scale in [
            ("floor (10 verified)", v, 1.0),
            (f"middle (24 auto-pre x {prec:.2f} precision)", pre, prec),
            ("ceiling (all 52, perfect news)", df, 1.0)]:
        per = sub.groupby("season")["value"].sum() * scale
        print(f"  {label:42s} "
              + "  ".join(f"{s}: {per.get(s, 0):5.1f}" for s in
                          ["2023-24", "2024-25", "2025-26"])
              + f"   pooled {sub['value'].sum() * scale:.1f}"
              f"  (~{sub['value'].sum() * scale / 3:.1f}/season)")


if __name__ == "__main__":
    main()
