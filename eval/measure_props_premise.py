"""P1 of Logs/props_conditional_prereg.md section 4 -- the premise test, independent of the minutes model. On 2024-25 (GW8-38) written-off rows (own-cutoff p_start < 0.25; outfield; single fixture; priced; partial doubles excluded) where the player DID take part (realised minutes > 0), the market's as-quoted p / m (m = 1.517, the pre-registered scalar) is compared with the realised P(>= 1 goal): a price conditional on appearing predicts a ratio near 1 or above; an already-unconditional price predicts ~ P(appears) on that band (0.13-0.20). Thresholds fixed in advance: >= 0.7 supported; < 0.5 premise wrong (abandon); 0.5-0.7 stop and report. Also reported: the split by book-rule group (participation: DraftKings / BetMGM / Bovada; start: BetRivers; unverified: FanDuel / 1xBet), started vs substitute appearances, the realised appearance rate on the band (for P2), and the likely-starter control. Per-book probabilities are recomputed from the raw boards with the consensus builder's exact scaling and ASSERTED to average to the stored consensus. No 2025-26 file is read. No build, no tuning.

Usage: uv run python eval/measure_props_premise.py [--append-log]
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "eval"))
from build_crosswalk import _norm  # noqa: E402
import build_props_consensus as B  # noqa: E402  (MARKET, P_CLIP, MIN_BOARD_SHARE, MIN_SHARED, SCALE, OUT)

SEASON, GW_LO, GW_HI = "2024-25", 8, 38
M = 1.517
GROUPS = {"participation (DK/BetMGM/Bovada)": ["draftkings", "betmgm", "bovada"],
          "start (BetRivers)": ["betrivers"],
          "unverified (FanDuel)": ["fanduel"], "unverified (1xBet)": ["onexbet"]}
T_SUPPORT, T_WRONG = 0.7, 0.5


def per_book_probabilities(season):
    """Replicates eval/build_props_consensus.py per fixture: thin boards dropped, shared-set scaling, clip. Returns (event_id, element, book, p_adj)."""
    cw = pd.read_csv(B.OUT / f"props_crosswalk_{season}.csv")
    cw_map = {(r.event_id, r.key): int(r.element) for r in cw[cw["element"].notna()].itertuples()}
    man = pd.read_csv(B.SCALE / season / "manifest.csv")
    man = man[man["event_id"].notna() & (man["books"].astype(str) != "CALL_FAILED")]
    rows = []
    for r in man.itertuples():
        f = B.SCALE / season / f"gw{int(r.gw):02d}_{r.event_id}_euus.json"
        if not f.exists():
            continue
        d = json.loads(f.read_text(encoding="utf-8"))["data"]
        per_book, size, whole_total = {}, {}, {}
        for bk in d["bookmakers"]:
            for mk in bk["markets"]:
                if mk["key"] != B.MARKET:
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
        keep = [b for b in per_book if size[b] >= B.MIN_BOARD_SHARE * largest]
        shared = set.intersection(*[set(per_book[b]) for b in keep]) if len(keep) > 1 else set(per_book[keep[0]])
        basis = {b: whole_total[b] for b in keep} if len(shared) < B.MIN_SHARED else {b: sum(per_book[b][el] for el in shared) for b in keep}
        mean_basis = float(np.mean(list(basis.values())))
        for b in keep:
            sc = mean_basis / basis[b]
            for el, p in per_book[b].items():
                rows.append(dict(gw=int(r.gw), event_id=r.event_id, element=el, book=b, p_adj=min(p * sc, B.P_CLIP)))
    return pd.DataFrame(rows)


def ratio_line(g, label):
    if len(g) == 0:
        return f"    {label:52s} n     0  --"
    pred = (g["p"] / M).mean(); real = (g["goals"] >= 1).mean()
    return (f"    {label:52s} n {len(g):5d}  mean p/m {pred:.4f}  realised P(>=1) {real:.4f}  "
            f"ratio {pred / real:.2f}" if real > 0 else f"    {label:52s} n {len(g):5d}  mean p/m {pred:.4f}  realised 0 -- ratio undefined")


def main():
    append = "--append-log" in sys.argv
    tag = SEASON.replace("-", "_")
    wf = pd.read_parquet(REPO / "data" / f"walkforward_h6_{tag}.parquet",
                         columns=["cutoff", "gw", "element", "name", "position", "p_start", "e_minutes", "n_fixtures", "p_play_any"])
    own = wf[wf["cutoff"] == wf["gw"]].copy()
    cons = pd.read_parquet(B.OUT / f"props_consensus_{SEASON}.parquet")
    assert (cons["method"] == "addendum1_shared_set").all()
    fx = pd.read_parquet(B.OUT / f"props_consensus_fixture_{SEASON}.parquet")
    hist = pd.read_parquet(REPO / "data/history/all_seasons_fixed.parquet", columns=["season", "element", "GW", "minutes", "goals_scored", "starts"])
    hist = hist[hist["season"] == SEASON]
    hist = hist.groupby(["element", "GW"]).agg(minutes=("minutes", "sum"), goals=("goals_scored", "sum"), starts=("starts", "max")).reset_index().rename(columns={"GW": "gw"})
    pb = per_book_probabilities(SEASON)
    # ---- assert the recomputed per-book probabilities reproduce the stored consensus exactly
    chk = pb.groupby(["event_id", "element"])["p_adj"].mean().rename("p_recomputed").reset_index().merge(fx[["event_id", "element", "p_consensus"]], on=["event_id", "element"])
    assert len(chk) == len(fx) and np.allclose(chk["p_recomputed"], chk["p_consensus"], atol=1e-9), "per-book recomputation does not reproduce the consensus"
    # ---- population: written-off, outfield, singles, priced, GW window, partial doubles excluded
    m = own.merge(cons[["gw", "element", "p_mkt_gw", "partial_double"]], on=["gw", "element"], how="left").merge(hist, on=["element", "gw"], how="left")
    m["minutes"] = m["minutes"].fillna(0); m["goals"] = m["goals"].fillna(0).astype(int); m["starts"] = m["starts"].fillna(0).astype(int)
    base = m[(m["gw"] >= GW_LO) & (m["gw"] <= GW_HI) & (m["n_fixtures"] == 1) & (m["position"] != "GK") & m["p_mkt_gw"].notna() & ~m["partial_double"].eq(True)].copy()
    base["p"] = base["p_mkt_gw"]
    wo = base[base["p_start"] < 0.25].copy(); ls = base[base["p_start"] >= 0.75].copy()
    wo["played"] = wo["minutes"] > 0; wo["started"] = wo["starts"] == 1; wo["sub"] = wo["played"] & ~wo["started"]
    out = []
    P = out.append
    P(f"P1 -- premise test on {SEASON} GW{GW_LO}-{GW_HI}, m = {M} (pre-registered scalar). No 2025-26 file read. Per-book recomputation reproduces the stored consensus: ASSERTED.")
    P(f"  written-off band (p_start < .25), outfield singles the market prices, partial doubles excluded: n {len(wo):,}")
    P(f"  realised appearance rate on the band: took part {wo['played'].mean():.3f} (n {int(wo['played'].sum())}); started {wo['started'].mean():.3f} (n {int(wo['started'].sum())}); "
      f"substitute {wo['sub'].mean():.3f} (n {int(wo['sub'].sum())}).  Minutes-model means on the band: p_start {wo['p_start'].mean():.3f}, p_play_any {wo['p_play_any'].mean():.3f}  [for P2]")
    P(f"  as-quoted calibration on ALL band rows (the 7.33 signature): mean p/m {(wo['p'] / M).mean():.4f} vs realised {(wo['goals'] >= 1).mean():.4f} -> ratio {(wo['p'] / M).mean() / (wo['goals'] >= 1).mean():.2f}")
    P("\n  HEADLINE (consensus price):")
    P(ratio_line(wo[wo["played"]], "written-off, TOOK PART (minutes > 0)"))
    P(ratio_line(wo[wo["started"]], "  of which STARTED"))
    P(ratio_line(wo[wo["sub"]], "  of which SUBSTITUTE appearance"))
    P(ratio_line(ls, "control: likely starters, all rows (~1.00 by construction)"))
    played = wo[wo["played"]]
    pred = (played["p"] / M).mean(); real = (played["goals"] >= 1).mean(); ratio = pred / real
    verdict = ("PREMISE SUPPORTED (>= 0.7)" if ratio >= T_SUPPORT else "PREMISE WRONG (< 0.5) -- ABANDON the conditional line" if ratio < T_WRONG else "INDETERMINATE (0.5-0.7) -- stop and report")
    P(f"\n  P1 RATIO = {ratio:.2f} (n = {len(played)})  ->  {verdict}")
    # ---- per book / per group: the book's own price on the rows it priced, same m
    single_ev = fx.groupby(["gw", "element"])["event_id"].first().rename("event_id").reset_index()   # singles: one event per (gw, element)
    wb = wo.merge(single_ev, on=["gw", "element"]).merge(pb[["event_id", "element", "book", "p_adj"]], on=["event_id", "element"])
    lb = ls.merge(single_ev, on=["gw", "element"]).merge(pb[["event_id", "element", "book", "p_adj"]], on=["event_id", "element"])
    P("\n  BY BOOK (each book's own scaled price on the rows IT priced; same m). Written-off took-part ratio, then started / substitute, then the likely-starter control:")
    P(f"    {'book':14s} {'n played':>8s} {'ratio':>6s} | {'n start':>7s} {'ratio':>6s} | {'n sub':>5s} {'ratio':>6s} | {'LS n':>5s} {'LS ratio':>8s} | mean p (band, played) ")
    def r_(g):
        if len(g) == 0:
            return float("nan")
        real = (g["goals"] >= 1).mean()
        return (g["p_adj"] / M).mean() / real if real > 0 else float("nan")
    book_rows = {}
    for gname, books in GROUPS.items():
        for b in books:
            g = wb[wb["book"] == b]; gl = lb[lb["book"] == b]
            gp, gs, gu = g[g["played"]], g[g["started"]], g[g["sub"]]
            book_rows[b] = dict(group=gname, n_played=len(gp), r_played=r_(gp), n_start=len(gs), r_start=r_(gs), n_sub=len(gu), r_sub=r_(gu), n_ls=len(gl), r_ls=r_(gl), p_played=gp["p_adj"].mean() if len(gp) else float("nan"))
            x = book_rows[b]
            P(f"    {b:14s} {x['n_played']:8d} {x['r_played']:6.2f} | {x['n_start']:7d} {x['r_start']:6.2f} | {x['n_sub']:5d} {x['r_sub']:6.2f} | {x['n_ls']:5d} {x['r_ls']:8.2f} | {x['p_played']:.4f}   [{gname}]")
    P("\n  BY GROUP (rows pooled across the group's books):")
    for gname, books in GROUPS.items():
        g = wb[wb["book"].isin(books)]
        P(f"    {gname:34s} played n {int(g['played'].sum()):5d} ratio {r_(g[g['played']]):5.2f} | started n {int(g['started'].sum()):4d} ratio {r_(g[g['started']]):5.2f} | sub n {int(g['sub'].sum()):4d} ratio {r_(g[g['sub']]):5.2f}")
    # ---- the second, independent check: price LEVEL of start books vs participation books on the same written-off rows
    part = wb[wb["book"].isin(GROUPS["participation (DK/BetMGM/Bovada)"])].groupby(["gw", "element"])["p_adj"].mean().rename("p_part")
    P("\n  PRICE LEVEL on the same written-off rows (book / participation-group mean, same (gw, element)); a start-conditioned price should sit ABOVE a participation-conditioned one on fringe players:")
    for b in ["betrivers", "fanduel", "onexbet", "draftkings", "betmgm", "bovada"]:
        g = wb[wb["book"] == b].merge(part, on=["gw", "element"])
        if len(g) == 0:
            continue
        lr = np.log(g["p_adj"] / g["p_part"])
        gs = g[g["sub"]]; gst = g[g["started"]]
        P(f"    {b:14s} n {len(g):5d}  geometric mean ratio {np.exp(lr.mean()):.3f}  (median {np.exp(lr.median()):.3f}; on sub rows n {len(gs)} {np.exp(np.log(gs['p_adj'] / gs['p_part']).mean()) if len(gs) else float('nan'):.3f}; on started rows n {len(gst)} {np.exp(np.log(gst['p_adj'] / gst['p_part']).mean()) if len(gst) else float('nan'):.3f})   [{book_rows[b]['group']}]")
    text = "\n".join(out)
    print(text)
    if append:
        log = REPO / "Logs" / "props_conditional_prereg.md"
        cur = log.read_text(encoding="utf-8")
        if "## RESULTS — P1" in cur:
            print("\nlog already has the P1 results section -- not appended twice")
        else:
            sec = ("\n\n---\n\n## RESULTS — P1, the premise test (2026-08-26). Method as §4 P1; thresholds as fixed there. No 2025-26 file read.\n\n"
                   "Script: `eval/measure_props_premise.py`. Per-book probabilities recomputed from the raw boards with the builder's exact "
                   "scaling and asserted to reproduce the stored consensus. Output of record (verbatim):\n\n```\n" + text + "\n```\n")
            log.write_text(cur.rstrip("\n") + sec, encoding="utf-8")
            print(f"\nappended the P1 results section to {log}")


if __name__ == "__main__":
    main()
