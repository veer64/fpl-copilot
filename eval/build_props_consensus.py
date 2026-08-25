"""De-vig and consensus for the player-prop pull under props_prereg.md sections 1, 4 and ADDENDUM 1 (amendments 1 and 3), no tuning, no endpoint: per book per fixture, decimal prices -> raw implied probabilities; thin boards (below 50% of the fixture's largest) DROPPED; each retained book scaled by mean_total / book_total computed on the SHARED element set (elements priced by every retained book) so board size cannot masquerade as margin; equal-weight consensus across the retained books pricing the player, MERGED BY ELEMENT never by name string (asserted: no element twice within a fixture); per-fixture rate lambda = -ln(1 - p); attached to (element, gameweek) by summing lambda over the player's fixtures, with rows priced in fewer fixtures than the walkforward's n_fixtures flagged `partial_double` (excluded from every endpoint). Keeps the v1 whole-board files as *_v1_wholeboard.parquet and reports what moved. Writes data/odds_props/props_consensus[_fixture]_{season}.parquet and appends the rebuild section to Logs/props_devig_log.md. No 2025-26 outcome is read.

Usage: uv run python eval/build_props_consensus.py
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "eval"))
from build_crosswalk import _norm  # noqa: E402

SCALE = REPO / "data" / "odds_props" / "raw" / "scale"
OUT = REPO / "data" / "odds_props"
SEASONS = ["2024-25", "2025-26"]
MARKET = "player_goal_scorer_anytime"
P_CLIP = 0.99
TOP = 30
SAMPLE_GW = ("2024-25", 20)
MIN_BOARD_SHARE = 0.50      # amendment 1(a): drop boards below half the fixture's largest
MIN_SHARED = 5              # amendment 1(b): shared set smaller than this -> whole-board fallback, counted
METHOD = "addendum1_shared_set"


def main():
    md = ["\n---\n\n## Rebuild under ADDENDUM 1 — amendments 1 and 3 (2026-08-24; before any 2025-26 outcome was read)\n",
          f"Method as amended: boards below {MIN_BOARD_SHARE:.0%} of the fixture's largest board are dropped; each retained "
          f"book's scale factor is mean_total / book_total over the SHARED element set (elements priced by every retained "
          f"book; fixtures with fewer than {MIN_SHARED} shared elements fall back to whole-board totals and are counted); "
          "equal-weight consensus merged by element (asserted); λ = −ln(1 − p) per fixture, summed over the player's "
          "fixtures; rows priced in fewer fixtures than the walkforward's `n_fixtures` are flagged `partial_double` and "
          "excluded from every endpoint. v1 (whole-board) files kept as `*_v1_wholeboard.parquet`; deltas reported.\n"]
    for season in SEASONS:
        tag = season.replace("-", "_")
        cw = pd.read_csv(OUT / f"props_crosswalk_{season}.csv")
        cw_map = {(r.event_id, r.key): int(r.element) for r in cw[cw["element"].notna()].itertuples()}
        man = pd.read_csv(SCALE / season / "manifest.csv")
        man = man[man["event_id"].notna() & (man["books"].astype(str) != "CALL_FAILED")]
        rows, totals, clips, dropped, fallback = [], [], 0, [], 0
        for r in man.itertuples():
            f = SCALE / season / f"gw{int(r.gw):02d}_{r.event_id}_euus.json"
            if not f.exists():
                continue
            d = json.loads(f.read_text(encoding="utf-8"))["data"]
            per_book, size, whole_total = {}, {}, {}
            for bk in d["bookmakers"]:
                for mk in bk["markets"]:
                    if mk["key"] != MARKET:
                        continue
                    by_el, n, tot = {}, 0, 0.0
                    for o in mk["outcomes"]:
                        nm = o.get("description") or o["name"]
                        if nm.lower() in ("no scorer", "no goalscorer"):
                            continue
                        p = 1.0 / float(o["price"]); n += 1; tot += p
                        el = cw_map.get((r.event_id, _norm(nm)))
                        if el is not None:
                            by_el.setdefault(el, []).append(p)
                    per_book[bk["key"]] = {el: float(np.mean(v)) for el, v in by_el.items()}
                    size[bk["key"]] = n; whole_total[bk["key"]] = tot
            if not per_book:
                continue
            largest = max(size.values())
            keep = [b for b in per_book if size[b] >= MIN_BOARD_SHARE * largest]
            for b in per_book:
                if b not in keep:
                    dropped.append(dict(season=season, gw=int(r.gw), book=b, n=size[b], largest=largest))
            # shared element set across retained books
            shared = set.intersection(*[set(per_book[b]) for b in keep]) if len(keep) > 1 else set(per_book[keep[0]])
            if len(shared) < MIN_SHARED:
                fallback += 1
                basis = {b: whole_total[b] for b in keep}
            else:
                basis = {b: sum(per_book[b][el] for el in shared) for b in keep}
            mean_basis = float(np.mean(list(basis.values())))
            scale = {b: mean_basis / basis[b] for b in keep}
            for b in keep:
                totals.append(dict(season=season, gw=int(r.gw), event_id=r.event_id, book=b, whole_raw=whole_total[b],
                                   shared_raw=basis[b], scale=scale[b], shared_adj=basis[b] * scale[b],
                                   n_shared=len(shared), n_board=size[b]))
            acc = {}
            for b in keep:
                for el, p in per_book[b].items():
                    pa = min(p * scale[b], P_CLIP); clips += int(p * scale[b] > P_CLIP)
                    acc.setdefault(el, []).append((b, pa, p))
            for el, lst in acc.items():
                p_cons = float(np.mean([pa for _, pa, _ in lst]))
                rows.append(dict(season=season, gw=int(r.gw), event_id=r.event_id, element=el, p_consensus=p_cons,
                                 p_raw_mean=float(np.mean([p for _, _, p in lst])),
                                 lambda_fixture=float(-np.log(1.0 - p_cons)), n_books=len(lst),
                                 onexbet=int(any(b == "onexbet" for b, _, _ in lst)),
                                 books="|".join(sorted(b for b, _, _ in lst)), method=METHOD))
        fx = pd.DataFrame(rows)
        dup = fx[fx.duplicated(["event_id", "element"], keep=False)]
        assert len(dup) == 0, f"{season}: element appears twice within a fixture after the merge:\n{dup.head(10)}"
        # ---- what moved vs v1 (whole-board)
        v1p = OUT / f"props_consensus_fixture_{season}.parquet"
        v1keep = OUT / f"props_consensus_fixture_{season}_v1_wholeboard.parquet"
        moved = None
        if v1p.exists():
            v1 = pd.read_parquet(v1p)
            if "method" not in v1.columns:          # a genuine v1 file
                v1.to_parquet(v1keep, index=False)
                pd.read_parquet(OUT / f"props_consensus_{season}.parquet").to_parquet(OUT / f"props_consensus_{season}_v1_wholeboard.parquet", index=False)
        if v1keep.exists():
            v1 = pd.read_parquet(v1keep)
            j = fx.merge(v1[["event_id", "element", "p_consensus"]], on=["event_id", "element"], how="inner", suffixes=("", "_v1"))
            dlt = (j["p_consensus"] - j["p_consensus_v1"])
            moved = dict(n=len(j), gt02=int((dlt.abs() > 0.02).sum()), gt05=int((dlt.abs() > 0.05).sum()),
                         max=float(dlt.abs().max()), mean=float(dlt.mean()), lost=len(v1) - len(j), gained=len(fx) - len(j))
        # ---- attach to (element, gw) + amendment 3 flag
        gwf = (fx.groupby(["season", "gw", "element"])
               .agg(lambda_mkt=("lambda_fixture", "sum"), n_fixtures_priced=("event_id", "nunique"),
                    n_books_min=("n_books", "min"), n_books_mean=("n_books", "mean"), onexbet_any=("onexbet", "max")).reset_index())
        gwf["p_mkt_gw"] = 1.0 - np.exp(-gwf["lambda_mkt"])
        wf = pd.read_parquet(REPO / "data" / f"walkforward_h6_{tag}.parquet",
                             columns=["cutoff", "gw", "element", "name", "position", "team", "e_points", "p_start", "e_minutes", "n_fixtures"])
        own = wf[wf["cutoff"] == wf["gw"]].copy()
        gwf = gwf.merge(own[["gw", "element", "n_fixtures"]], on=["gw", "element"], how="left")
        gwf["partial_double"] = (gwf["n_fixtures"].notna()) & (gwf["n_fixtures_priced"] < gwf["n_fixtures"])
        gwf["method"] = METHOD
        fx.to_parquet(OUT / f"props_consensus_fixture_{season}.parquet", index=False)
        gwf.to_parquet(OUT / f"props_consensus_{season}.parquet", index=False)
        tot = pd.DataFrame(totals); drp = pd.DataFrame(dropped)
        # ---- coverage (outfield, amendment 2) and sanity
        m = own.merge(gwf, on=["gw", "element", "n_fixtures"], how="left")
        m = m[m["gw"].isin(gwf["gw"].unique())]
        m["covered"] = m["p_mkt_gw"].notna() & ~m["partial_double"].eq(True)
        m["rk"] = m.groupby("gw")["e_points"].rank(ascending=False, method="first")
        parts = {"likely starters (p_start >= .75)": m["p_start"] >= 0.75,
                 "uncertain (.25-.75)": (m["p_start"] >= 0.25) & (m["p_start"] < 0.75),
                 "written off (p_start < .25)": m["p_start"] < 0.25,
                 f"squad-relevant (top {TOP} e_points in gw)": m["rk"] <= TOP}
        hist = pd.read_parquet(REPO / "data/history/all_seasons_fixed.parquet", columns=["season", "element", "minutes"])
        hist["minutes"] = pd.to_numeric(hist["minutes"], errors="coerce").fillna(0)
        smin = hist[hist["season"] == season].groupby("element")["minutes"].sum()
        m["season_minutes"] = m["element"].map(smin).fillna(0)
        print(f"\n================ {season} ================  ({METHOD})")
        print(f"  fixtures {fx['event_id'].nunique()}; (fixture, element) rows {len(fx):,}; (gw, element) rows {len(gwf):,}; clips {clips}; "
              f"merge-by-element assert PASSED; boards dropped {len(drp)} ({drp['book'].value_counts().to_dict() if len(drp) else {}}); "
              f"whole-board fallbacks {fallback}")
        if moved:
            print(f"  moved vs v1 (whole-board): {moved['n']:,} shared (fixture, element) rows; |dp| > 0.02: {moved['gt02']:,} ({moved['gt02'] / moved['n']:.1%}); "
                  f"> 0.05: {moved['gt05']:,}; max {moved['max']:.3f}; mean signed {moved['mean']:+.4f}; rows only in v1 {moved['lost']}, only in v2 {moved['gained']}")
        bt = tot.groupby("book").agg(fixtures=("event_id", "nunique"), whole_raw=("whole_raw", "mean"), shared_raw=("shared_raw", "mean"),
                                     scale_mean=("scale", "mean"), scale_min=("scale", "min"), scale_max=("scale", "max"),
                                     shared_adj=("shared_adj", "mean"), n_shared=("n_shared", "mean"), n_board=("n_board", "mean"))
        print("  board totals per retained book: whole-board raw | shared-set raw -> scale mean [min,max] -> shared-set adjusted | board size / shared size:")
        for b, r in bt.sort_values("shared_raw").iterrows():
            print(f"     {b:12s} fx {int(r.fixtures):3d}  whole {r.whole_raw:5.2f} | shared {r.shared_raw:5.2f} -> {r.scale_mean:.3f} [{r.scale_min:.2f},{r.scale_max:.2f}] -> {r.shared_adj:5.2f} | {r.n_board:4.1f} / {r.n_shared:4.1f}")
        pdbl = gwf[gwf["partial_double"]]
        print(f"  amendment 3: partial doubles flagged and excluded: {len(pdbl)} (gw, element) rows")
        print("  COVERAGE, OUTFIELD players only (amendment 2), excluding partial doubles; gate 80%:")
        cov = []
        for name, mask in parts.items():
            g = m[mask & (m["position"] != "GK")]
            c = g["covered"].mean(); cov.append((name, c, len(g)))
            print(f"     {name:38s} {c:6.1%} of {len(g):6,d} outfield rows {'OK' if c >= .8 else '<-- BELOW GATE'}")
        sg = SAMPLE_GW[1] if season == SAMPLE_GW[0] else None
        md.append(f"### {season}\n")
        md.append(f"- Fixtures {fx['event_id'].nunique()}; (fixture, element) rows {len(fx):,}; (gameweek, element) rows {len(gwf):,}; clipped {clips}; "
                  f"merge-by-element assert passed; boards dropped under amendment 1(a): {len(drp)} "
                  f"({drp['book'].value_counts().to_dict() if len(drp) else 'none'}); whole-board fallbacks (shared set < {MIN_SHARED}): {fallback}.")
        if moved:
            md.append(f"- **What moved vs v1:** of {moved['n']:,} shared (fixture, element) rows, {moved['gt02']:,} ({moved['gt02'] / moved['n']:.1%}) "
                      f"shifted by more than 0.02 and {moved['gt05']:,} by more than 0.05 (max {moved['max']:.3f}, mean signed {moved['mean']:+.4f}); "
                      f"{moved['lost']} rows existed only in v1 (dropped boards' exclusive players), {moved['gained']} only in v2.")
        md.append("\n**Board totals per retained book** (pooled): whole-board raw | shared-set raw → scale factor → shared-set adjusted | mean board size / shared-set size\n")
        md.append("| book | fixtures | whole-board raw | shared-set raw | scale mean [min, max] | shared-set adjusted | board / shared |\n|---|---|---|---|---|---|---|")
        for b, r in bt.sort_values("shared_raw").iterrows():
            md.append(f"| {b} | {int(r.fixtures)} | {r.whole_raw:.2f} | {r.shared_raw:.2f} | {r.scale_mean:.3f} [{r.scale_min:.2f}, {r.scale_max:.2f}] | {r.shared_adj:.2f} | {r.n_board:.1f} / {r.n_shared:.1f} |")
        md.append(f"\n- **Amendment 3:** {len(pdbl)} partial-double (gameweek, element) rows flagged and excluded from every endpoint.")
        md.append("\n**Coverage gate on OUTFIELD players (amendment 2), partial doubles excluded:**\n\n| partition | covered / outfield rows | gate |\n|---|---|---|")
        for name, c, n in cov:
            md.append(f"| {name} | {c:.1%} of {n:,} | {'clears 80%' if c >= .8 else '**BELOW 80%**'} |")
        if sg is not None:
            t = m[(m["gw"] == sg) & m["p_mkt_gw"].notna() & (m["position"] != "GK")].sort_values("p_mkt_gw", ascending=False).head(20)
            print(f"  SANITY top 20, {season} GW{sg}: " + "; ".join(f"{r._asdict()['name']} ({r.team}, {r.position}) {r.p_mkt_gw:.2f}{'*' if r.season_minutes < 90 else ''}" for r in t.itertuples()))
            md.append(f"\n**Sanity — top 20 by consensus p_gw, {season} GW{sg}, outfield** (\\* = < 90 season minutes, a placeholder price):\n\n| # | player | team | pos | p_gw | v1 p_gw | books | e_points (model) |\n|---|---|---|---|---|---|---|---|")
            v1g = pd.read_parquet(OUT / f"props_consensus_{season}_v1_wholeboard.parquet")[["gw", "element", "p_mkt_gw"]].rename(columns={"p_mkt_gw": "v1"}) if (OUT / f"props_consensus_{season}_v1_wholeboard.parquet").exists() else None
            for i, r in enumerate(t.itertuples(), 1):
                v1v = float(v1g[(v1g.gw == sg) & (v1g.element == r.element)]["v1"].iloc[0]) if v1g is not None and ((v1g.gw == sg) & (v1g.element == r.element)).any() else float("nan")
                md.append(f"| {i} | {r._asdict()['name']}{'*' if r.season_minutes < 90 else ''} | {r.team} | {r.position} | {r.p_mkt_gw:.3f} | {v1v:.3f} | {r.n_books_mean:.0f} | {r.e_points:.2f} |")
        md.append("")
    log = REPO / "Logs" / "props_devig_log.md"
    cur = log.read_text(encoding="utf-8")
    if "## Rebuild under ADDENDUM 1" in cur:
        print("\nlog already has the rebuild section -- not appended twice")
    else:
        log.write_text(cur.rstrip("\n") + "\n" + "\n".join(md) + "\n", encoding="utf-8")
        print(f"\nappended the rebuild section to {log}")


if __name__ == "__main__":
    main()
