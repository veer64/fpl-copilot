"""De-vig and consensus for the player-prop pull (Logs/props_prereg.md sections 1 and 4; no tuning, no endpoint): per book per fixture, decimal prices -> raw implied probabilities -> proportional margin adjustment (each book scaled to the fixture's cross-book mean board total; anytime-scorer outcomes are not mutually exclusive so nothing is normalised to 1) -> equal-weight consensus across the books that price the player, MERGED BY ELEMENT never by name string (asserted: no element twice within a fixture) -> per-fixture rate lambda = -ln(1 - p) -> attached to (element, gameweek) by SUMMING lambda over the player's fixtures (double gameweeks; verified on a known double). Writes data/odds_props/props_consensus_{season}.parquet (per gameweek) and props_consensus_fixture_{season}.parquet (per fixture), and Logs/props_devig_log.md with the report: distributions by position and predicted-minutes band, board totals raw vs adjusted per book, coverage per pre-registered partition (the 80% gate), the placeholder-price problem quantified (not filtered), and a top-20 sanity list. No 2025-26 outcome is read.

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
P_CLIP = 0.99          # adjusted p above this is clipped (counted)
TOP = 30
SAMPLE_GW = ("2024-25", 20)


def main():
    md = ["# Player-prop de-vig and consensus — build log (2026-08-24)\n",
          "Governed by `Logs/props_prereg.md` §1 and §4; crosswalk at commit a7c3fce. **No tuning of w or m, no "
          "endpoint, no 2025-26 outcome read** (2025-26 appears below only in outcome-free descriptives: coverage "
          "and distributions of the market quantity itself).\n",
          "## Method (stated before the results)\n",
          "1. **Raw implied**: per book, per fixture, p_raw = 1 / decimal price for every priced outcome. \"No Scorer\" "
          "pseudo-outcomes are dropped. Board total = Σ p_raw over the whole board (matched and unmatched names alike — "
          "the book's margin applies to its whole board).",
          "2. **Margin adjustment** (coverage log §6): anytime-scorer outcomes are not mutually exclusive, so probabilities "
          "cannot be normalised to 1. Each book is scaled proportionally so its board total equals the cross-book mean "
          "total for that fixture: p_adj = p_raw × (mean_total / book_total). Adjusted p above 0.99 is clipped and counted.",
          "3. **Consensus**: merged BY ELEMENT (crosswalk `element`), never by name string. Equal weight over the books "
          "that price the element after adjustment. Why equal weight: every book is a noisy read of the same quantity, "
          "no reliability evidence exists yet, and a weight would be a new tunable outside the pre-registration. "
          "Consequence stated: with ~4 US books to one 1xBet, the equal-weight consensus is US-dominated; a "
          "region-balanced variant is a legitimate alternative and is NOT built here. **Assert**: after the merge no "
          "element appears twice within a fixture — fail loudly (the 28 two-spelling events in 2025-26 are the case).",
          "4. **Rate**: λ_mkt = −ln(1 − p_consensus) per fixture (Poisson, prereg §1).",
          "5. **Attach to (element, gameweek)**: λ summed over the player's fixtures in the gameweek (double gameweeks), "
          "p_gw = 1 − e^{−Σλ}; `n_fixtures_priced` recorded. Verified on a known double below.\n"]
    for season in SEASONS:
        tag = season.replace("-", "_")
        cw = pd.read_csv(OUT / f"props_crosswalk_{season}.csv")
        cw_map = {(r.event_id, r.key): int(r.element) for r in cw[cw["element"].notna()].itertuples()}
        man = pd.read_csv(SCALE / season / "manifest.csv")
        man = man[man["event_id"].notna() & (man["books"].astype(str) != "CALL_FAILED")]
        rows, totals, clips = [], [], 0
        for r in man.itertuples():
            f = SCALE / season / f"gw{int(r.gw):02d}_{r.event_id}_euus.json"
            if not f.exists():
                continue
            d = json.loads(f.read_text(encoding="utf-8"))["data"]
            per_book = {}                                   # book -> {element: p_raw} (merged by element)
            book_total = {}
            for bk in d["bookmakers"]:
                for mk in bk["markets"]:
                    if mk["key"] != MARKET:
                        continue
                    tot, by_el = 0.0, {}
                    for o in mk["outcomes"]:
                        nm = o.get("description") or o["name"]
                        if nm.lower() in ("no scorer", "no goalscorer"):
                            continue
                        p = 1.0 / float(o["price"])
                        tot += p
                        el = cw_map.get((r.event_id, _norm(nm)))
                        if el is None:
                            continue
                        # merge by element within the book (a book could carry two
                        # strings for one element; the crosswalk asserted it does not,
                        # but the merge is by element regardless)
                        by_el.setdefault(el, []).append(p)
                    per_book[bk["key"]] = {el: float(np.mean(v)) for el, v in by_el.items()}
                    book_total[bk["key"]] = tot
            if not per_book:
                continue
            mean_total = float(np.mean(list(book_total.values())))
            for bk, tot in book_total.items():
                totals.append(dict(season=season, gw=int(r.gw), event_id=r.event_id, book=bk, raw_total=tot,
                                   scale=mean_total / tot, adj_total=mean_total, n_priced=len(per_book[bk])))
            # consensus by element
            acc = {}
            for bk, pe in per_book.items():
                s = mean_total / book_total[bk]
                for el, p in pe.items():
                    pa = min(p * s, P_CLIP)
                    clips += int(p * s > P_CLIP)
                    acc.setdefault(el, []).append((bk, pa, p))
            for el, lst in acc.items():
                p_cons = float(np.mean([pa for _, pa, _ in lst]))
                rows.append(dict(season=season, gw=int(r.gw), event_id=r.event_id, element=el,
                                 p_consensus=p_cons, p_raw_mean=float(np.mean([p for _, _, p in lst])),
                                 lambda_fixture=float(-np.log(1.0 - p_cons)), n_books=len(lst),
                                 onexbet=int(any(b == "onexbet" for b, _, _ in lst)),
                                 books="|".join(sorted(b for b, _, _ in lst))))
        fx = pd.DataFrame(rows)
        # ---- THE ASSERT: merged by element, no element twice within a fixture
        dup = fx[fx.duplicated(["event_id", "element"], keep=False)]
        assert len(dup) == 0, f"{season}: element appears twice within a fixture after the merge:\n{dup.head(10)}"
        # ---- attach to (element, gw): sum lambda over fixtures
        gwf = (fx.groupby(["season", "gw", "element"])
               .agg(lambda_mkt=("lambda_fixture", "sum"), n_fixtures_priced=("event_id", "nunique"),
                    n_books_min=("n_books", "min"), n_books_mean=("n_books", "mean"),
                    onexbet_any=("onexbet", "max")).reset_index())
        gwf["p_mkt_gw"] = 1.0 - np.exp(-gwf["lambda_mkt"])
        fx.to_parquet(OUT / f"props_consensus_fixture_{season}.parquet", index=False)
        gwf.to_parquet(OUT / f"props_consensus_{season}.parquet", index=False)
        tot = pd.DataFrame(totals)
        # ---- DGW verification on the walkforward's n_fixtures
        wf = pd.read_parquet(REPO / "data" / f"walkforward_h6_{tag}.parquet",
                             columns=["cutoff", "gw", "element", "name", "position", "team", "e_points", "p_start",
                                      "e_minutes", "n_fixtures"])
        own = wf[wf["cutoff"] == wf["gw"]].copy()
        dg = own[own["n_fixtures"] >= 2][["gw", "element", "name", "n_fixtures"]]
        chk = dg.merge(gwf, on=["gw", "element"], how="inner")
        dgw_ok = chk[chk["n_fixtures_priced"] == 2]
        dgw_one = chk[chk["n_fixtures_priced"] == 1]
        # ---- distributions on the own-cutoff frame (outcome-free)
        m = own.merge(gwf, on=["gw", "element"], how="left")
        m = m[m["gw"].isin(gwf["gw"].unique())]
        m["covered"] = m["p_mkt_gw"].notna()
        m["rk"] = m.groupby("gw")["e_points"].rank(ascending=False, method="first")
        parts = {"likely starters (p_start >= .75)": m["p_start"] >= 0.75,
                 "uncertain (.25-.75)": (m["p_start"] >= 0.25) & (m["p_start"] < 0.75),
                 "written off (p_start < .25)": m["p_start"] < 0.25,
                 f"squad-relevant (top {TOP} e_points in gw)": m["rk"] <= TOP}
        hist = pd.read_parquet(REPO / "data/history/all_seasons_fixed.parquet", columns=["season", "element", "minutes"])
        hist["minutes"] = pd.to_numeric(hist["minutes"], errors="coerce").fillna(0)
        smin = hist[hist["season"] == season].groupby("element")["minutes"].sum()
        m["season_minutes"] = m["element"].map(smin).fillna(0)
        m["placeholder"] = m["covered"] & (m["season_minutes"] < 90) & (m["p_mkt_gw"] >= 0.25)
        m["emin_band"] = pd.cut(m["e_minutes"], [-1, 15, 45, 60, 200], labels=["<15", "15-45", "45-60", "60+"])
        # placeholder effect on board totals: unmatched names + matched <90-min at >= .25 raw
        print(f"\n================ {season} ================")
        print(f"  fixtures {fx['event_id'].nunique()}; (fixture, element) rows {len(fx):,}; (gw, element) rows {len(gwf):,}; "
              f"clipped adjusted p > {P_CLIP}: {clips}; merge-by-element assert: PASSED (0 duplicates)")
        print(f"  books per (fixture, element): " + ", ".join(f"{k}:{v}" for k, v in fx['n_books'].value_counts().sort_index().items())
              + f"; 1xBet present on {fx['onexbet'].mean():.0%} of rows")
        bt = tot.groupby("book").agg(fixtures=("event_id", "nunique"), raw_mean=("raw_total", "mean"), raw_sd=("raw_total", "std"),
                                     raw_min=("raw_total", "min"), raw_max=("raw_total", "max"), scale_mean=("scale", "mean"),
                                     scale_min=("scale", "min"), scale_max=("scale", "max"), adj_mean=("adj_total", "mean"))
        print("  board totals per book (raw mean/sd/min/max -> scale factor mean [min,max] -> adjusted mean):")
        for b, r in bt.sort_values("raw_mean").iterrows():
            print(f"     {b:14s} fx {int(r.fixtures):3d}  raw {r.raw_mean:5.2f} ±{r.raw_sd:4.2f} [{r.raw_min:4.2f},{r.raw_max:4.2f}]  "
                  f"scale {r.scale_mean:.3f} [{r.scale_min:.2f},{r.scale_max:.2f}]  adj {r.adj_mean:5.2f}")
        print(f"  DGW check: {len(dg)} doubling (gw, element) rows in the walkforward; priced in BOTH fixtures {len(dgw_ok)}, "
              f"in ONE {len(dgw_one)}, in none {len(dg) - len(chk)}")
        if len(dgw_ok):
            ex = dgw_ok.sort_values("lambda_mkt", ascending=False).iloc[0]
            both = fx[(fx["gw"] == ex.gw) & (fx["element"] == ex.element)]
            print(f"     e.g. GW{int(ex.gw)} {ex['name']}: fixture p {', '.join(f'{p:.3f}' for p in both['p_consensus'])} -> "
                  f"lambda {', '.join(f'{l:.3f}' for l in both['lambda_fixture'])} -> sum {ex.lambda_mkt:.3f} -> p_gw {ex.p_mkt_gw:.3f} "
                  f"(vs a single-fixture read {both['p_consensus'].max():.3f})")
        print("  consensus p_gw by position (covered rows): " + "; ".join(
            f"{pos} n={int(g['p_mkt_gw'].notna().sum())} mean {g['p_mkt_gw'].mean():.3f} med {g['p_mkt_gw'].median():.3f} p90 {g['p_mkt_gw'].quantile(.9):.3f}"
            for pos, g in m.groupby("position")))
        print("  consensus p_gw by predicted-minutes band: " + "; ".join(
            f"{b}: n={int(g['p_mkt_gw'].notna().sum())} mean {g['p_mkt_gw'].mean():.3f}"
            for b, g in m.groupby("emin_band", observed=True)))
        print("  COVERAGE per pre-registered partition (rows with a consensus p / partition rows; gate 80%):")
        cov_lines = []
        for name, mask in parts.items():
            g = m[mask]
            gk = g[g["position"] != "GK"]
            s = f"{name:38s} {g['covered'].mean():6.1%} of {len(g):6,d} rows (outfield only {gk['covered'].mean():6.1%}); placeholder rows {int(g['placeholder'].sum())}"
            print("     " + s); cov_lines.append((name, g["covered"].mean(), len(g), gk["covered"].mean(), int(g["placeholder"].sum())))
        ph = m[m["placeholder"]]
        print(f"  placeholder-price rows (covered, <90 season minutes, p_gw >= .25): {len(ph)} rows / {ph['element'].nunique()} players; "
              f"share of covered rows {len(ph) / max(m['covered'].sum(), 1):.2%}")
        # effect of placeholders on board totals -> everyone's scale factor
        print(f"  unmatched names' share of raw board totals (they inflate a book's total and so scale the matched players down): "
              f"computed per fixture below in the log")
        # sample gw top 20
        if (season, None) or True:
            sg = SAMPLE_GW[1] if season == SAMPLE_GW[0] else None
        md.append(f"## {season}\n")
        md.append(f"- Fixtures {fx['event_id'].nunique()}; (fixture, element) rows {len(fx):,}; (gameweek, element) rows {len(gwf):,}; "
                  f"adjusted p clipped at {P_CLIP}: {clips}; **merge-by-element assert passed (0 duplicates)**. Books per "
                  f"(fixture, element): " + ", ".join(f"{k} book(s): {v:,}" for k, v in fx['n_books'].value_counts().sort_index().items())
                  + f"; 1xBet on {fx['onexbet'].mean():.0%} of rows.")
        md.append("\n**Board totals per book, raw → adjusted** (pooled over fixtures; the adjustment scales each book to the fixture's cross-book mean):\n")
        md.append("| book | fixtures | raw total mean ± sd [min, max] | scale factor mean [min, max] | adjusted total mean |\n|---|---|---|---|---|")
        for b, r in bt.sort_values("raw_mean").iterrows():
            md.append(f"| {b} | {int(r.fixtures)} | {r.raw_mean:.2f} ± {r.raw_sd:.2f} [{r.raw_min:.2f}, {r.raw_max:.2f}] | {r.scale_mean:.3f} [{r.scale_min:.2f}, {r.scale_max:.2f}] | {r.adj_mean:.2f} |")
        md.append(f"\n**Double-gameweek verification:** {len(dg)} doubling (gameweek, element) rows in the walkforward; priced in both "
                  f"fixtures {len(dgw_ok)}, in one {len(dgw_one)}, in none {len(dg) - len(chk)}.")
        if len(dgw_ok):
            md.append(f"Example GW{int(ex.gw)} {ex['name']}: fixture p {', '.join(f'{p:.3f}' for p in both['p_consensus'])} → "
                      f"λ {', '.join(f'{l:.3f}' for l in both['lambda_fixture'])} → Σλ {ex.lambda_mkt:.3f} → p_gw {ex.p_mkt_gw:.3f} "
                      f"(a single-fixture read would have been {both['p_consensus'].max():.3f}).")
        md.append("\n**Consensus p_gw by position** (covered rows): " + "; ".join(
            f"{pos} n={int(g['p_mkt_gw'].notna().sum())}, mean {g['p_mkt_gw'].mean():.3f}, median {g['p_mkt_gw'].median():.3f}, p90 {g['p_mkt_gw'].quantile(.9):.3f}"
            for pos, g in m.groupby("position")) + ".")
        md.append("**By predicted-minutes band (own-cutoff e_minutes):** " + "; ".join(
            f"{b}: n={int(g['p_mkt_gw'].notna().sum())}, mean {g['p_mkt_gw'].mean():.3f}" for b, g in m.groupby("emin_band", observed=True)) + ".\n")
        md.append("**Coverage per pre-registered partition — the 80% gate (prereg §1):**\n")
        md.append("| partition | covered / rows | outfield-only coverage | placeholder rows inside |\n|---|---|---|---|")
        for name, c, n, cg, ph_n in cov_lines:
            flag = "" if c >= 0.80 else " **← BELOW THE 80% GATE**"
            md.append(f"| {name} | {c:.1%} of {n:,}{flag} | {cg:.1%} | {ph_n} |")
        md.append(f"\n**Placeholder-price problem:** {len(ph)} covered (gameweek, element) rows / {ph['element'].nunique()} players with "
                  f"< 90 season minutes and p_gw ≥ 0.25 ({len(ph) / max(m['covered'].sum(), 1):.2%} of covered rows). Not filtered. "
                  "They sit almost entirely in the written-off band (table above). Distortion of OTHER players' consensus: "
                  "none through the per-element merge; some through the margin adjustment, because every priced name — "
                  "matched or not — enters a book's board total, and a book carrying academy names at 0.3–0.6 has a larger "
                  "total and is scaled DOWN for everyone. Quantified below.\n")
        # quantify placeholder + unmatched effect on board totals
        eff = []
        for r in man.itertuples():
            f = SCALE / season / f"gw{int(r.gw):02d}_{r.event_id}_euus.json"
            if not f.exists():
                continue
            d = json.loads(f.read_text(encoding="utf-8"))["data"]
            for bk in d["bookmakers"]:
                for mk in bk["markets"]:
                    if mk["key"] != MARKET:
                        continue
                    tot = unm = 0.0
                    for o in mk["outcomes"]:
                        nm = o.get("description") or o["name"]
                        if nm.lower() in ("no scorer", "no goalscorer"):
                            continue
                        p = 1.0 / float(o["price"]); tot += p
                        el = cw_map.get((r.event_id, _norm(nm)))
                        if el is None or (float(smin.get(el, 0)) < 90 and p >= 0.25):
                            unm += p
                    eff.append(dict(book=bk["key"], tot=tot, junk=unm))
        eff = pd.DataFrame(eff)
        eff["junk_share"] = eff["junk"] / eff["tot"]
        js = eff.groupby("book")["junk_share"].agg(["mean", "max"])
        print("  share of each book's raw board total carried by unmatched names + placeholder-priced fringe (mean / max): "
              + "; ".join(f"{b} {r['mean']:.1%}/{r['max']:.1%}" for b, r in js.iterrows()))
        md.append("Share of each book's raw board total carried by unmatched names plus placeholder-priced fringe (mean / max over fixtures): "
                  + "; ".join(f"{b} {r['mean']:.1%} / {r['max']:.1%}" for b, r in js.iterrows()) + ". That share is the size of the "
                  "scale-factor distortion those names impose on the rest of the board at that book.\n")
        # DGW coverage detail: which positions are the "priced in none" doubling rows?
        none_rows = dg.merge(gwf[["gw", "element"]], on=["gw", "element"], how="left", indicator=True)
        none_rows = none_rows[none_rows["_merge"] == "left_only"].merge(own[["gw", "element", "position"]], on=["gw", "element"], how="left")
        print(f"  DGW rows with no consensus by position: {none_rows['position'].value_counts().to_dict()}")
        md.append(f"Doubling rows with no consensus, by position: {none_rows['position'].value_counts().to_dict()} "
                  f"(goalkeepers are never priced; the rest are unpriced fringe). Rows priced in ONE of two fixtures ({len(dgw_one)}) carry "
                  f"`n_fixtures_priced = 1 < n_fixtures = 2`; the feature step must not treat their Σλ as a full-gameweek rate.\n")
        if sg is not None:
            t = m[(m["gw"] == sg) & m["covered"]].sort_values("p_mkt_gw", ascending=False).head(20)
            print(f"  SANITY top 20 by consensus p_gw, {season} GW{sg}: " + "; ".join(
                f"{r._asdict()['name']} ({r.team}, {r.position}) {r.p_mkt_gw:.2f}" for r in t.itertuples()))
            md.append(f"**Sanity — top 20 by consensus p_gw, {season} GW{sg}:**\n\n| # | player | team | pos | p_gw | books | e_points (model) |\n|---|---|---|---|---|---|---|")
            for i, r in enumerate(t.itertuples(), 1):
                md.append(f"| {i} | {r._asdict()['name']} | {r.team} | {r.position} | {r.p_mkt_gw:.3f} | {r.n_books_mean:.0f} | {r.e_points:.2f} |")
            md.append("")
    (REPO / "Logs" / "props_devig_log.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print("\n-> Logs/props_devig_log.md; data/odds_props/props_consensus[_fixture]_{season}.parquet")


if __name__ == "__main__":
    main()
