"""TC2 valuation sweep: for every legal second-half gameweek on the frozen base_wc2 path, the Triple Captain 2 read that would have resulted (captain_bonus = the doubled player's raw points, i.e. the third multiple), reported as a DISTRIBUTION with the rule-of-record week (largest double excluding BB2) and the old rule's week (largest double = BB2) ranked against it and against the random-week mean. Every read is hindsight on a single path; nothing here is adopted into any headline. Result of record: Logs/tc2_valuation_log.md. Read-only; no simulations.

Method (stated before the results, and written into the log):

  * Path: data/p1/fslog_{season}_base_wc2.parquet -- the system-as-configured
    full-system cell. The captain is READ from the frozen path (`captain`,
    `doubled_role`, `captain_bonus` per gw), never re-chosen.
  * Read formula: TC2_read(gw) = captain_bonus[gw]. In the decision log
    captain_bonus = points(doubled player) x 1, where the doubled player is
    the captain, or the vice when the captain played 0 minutes
    (scoring.resolve_captain). A Triple Captain adds exactly one more
    multiple of that player's points, so the read is captain_bonus itself --
    the same quantity every TC1/TC2 read in the project uses.
  * Legal weeks: GW20-38 minus the weeks already holding a chip on that
    path (WC2, FH2, BB2; one chip per gameweek). TC1 sits in the first half.
  * Doubles inventory: walkforward n_fixtures >= 2 at own cutoff, teams
    doubling per gw (eval/quantify_collision.py convention).
  * Rule of record: TC2 = largest double gameweek EXCLUDING the BB2 week
    (p4 log section 12c). Where two doubles tie on team count the rule does
    not pick; every tied week is reported.
  * Old rule: largest double gameweek overall = the BB2 week. Its read is
    illegal (collision) and is shown only for comparison, ranked as if it
    had been counted among the legal weeks.
  * Random-week baseline: the mean read over the legal weeks -- what a
    manager who picked blind would expect.
  * Rank: 1 = best legal week. Percentile = share of legal weeks whose read
    is <= the week's read (ties count in favour).
"""
import datetime as dt
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "squad"))
from chip_legality import check_chip_schedule  # noqa: E402

P1 = REPO / "data" / "p1"
SEASONS = ["2023-24", "2024-25", "2025-26"]
H2_START = 20


def doubles_inventory(tag):
    wf = pd.read_parquet(REPO / "data" / f"walkforward_h6_{tag}.parquet",
                         columns=["cutoff", "gw", "team", "n_fixtures"])
    own = wf[wf["cutoff"] == wf["gw"]]
    return own[own["n_fixtures"] >= 2].groupby("gw")["team"].nunique()


def pct_le(series, value):
    return float((series <= value).mean())


def rank_of(series, value):
    """1 = best. Rank by strict 'more than', so ties share the better rank."""
    return int((series > value).sum()) + 1


def sweep(season):
    tag = season.replace("-", "_")
    d = pd.read_parquet(P1 / f"fslog_{tag}_base_wc2.parquet").set_index("gw")
    wc1, wc2, fh2, bb1, bb2 = (int(d[c].iloc[0]) for c in
                               ("wc1", "wc2", "fh2", "bb1", "bb2"))
    taken = {wc2, fh2, bb2}
    inv = doubles_inventory(tag)
    legal = [g for g in range(H2_START, 39) if g in d.index and g not in taken]
    reads = d.loc[legal, "captain_bonus"].astype(int)
    # each candidate is a legal play by construction -- assert it anyway
    for g in legal:
        check_chip_schedule({"wildcard": [wc1, wc2], "free_hit": [fh2],
                             "bench_boost": [bb1, bb2], "triple_captain": [g]},
                            played_gws=set(int(x) for x in d.index),
                            source=f"{season} TC2@GW{g}")
    # rule of record: largest double excluding chip weeks (report ties)
    cand = inv[(inv.index >= H2_START) & ~inv.index.isin(taken)]
    rule_weeks = sorted(int(g) for g in cand[cand == cand.max()].index) \
        if len(cand) else []
    old_week = int(inv.idxmax())            # largest double overall
    assert old_week == bb2, f"{season}: old-rule week {old_week} != BB2 {bb2}"
    old_read = int(d.loc[old_week, "captain_bonus"])
    dbl_weeks = [g for g in legal if g in inv.index]
    sgl_weeks = [g for g in legal if g not in inv.index]
    return dict(season=season, d=d, wc2=wc2, fh2=fh2, bb1=bb1, bb2=bb2,
                inv=inv, legal=legal, reads=reads, rule_weeks=rule_weeks,
                cand=cand, old_week=old_week, old_read=old_read,
                dbl_weeks=dbl_weeks, sgl_weeks=sgl_weeks)


def fmt_week(r, g):
    d = r["d"]
    role = d.loc[g, "doubled_role"]
    cap = d.loc[g, "captain"]
    n = int(r["inv"].get(g, 0))
    tag = f"DGW x{n}" if n else "single"
    return f"GW{g} ({tag}; captain {cap}, doubled={role})"


def main():
    out = []
    out.append("# TC2 valuation sweep -- every legal second-half week on the frozen base_wc2 paths\n")
    out.append(f"Generated {dt.date.today()} by eval/tc2_valuation_sweep.py. "
               "Read-only; no simulations.\n")
    out.append("**Framing (binding):** every number below is a HINDSIGHT read "
               "of what one captain scored on one frozen path. Nothing here "
               "is adopted into any headline; the chip-inclusive figures of "
               "record remain 2296 / 2294 / 2206 with TC2 scored as zero "
               "(p4 log section 12c). This is a valuation study of the "
               "TC2 RULE, not a figure.\n")
    out.append("## Method (stated before the results)\n")
    out.append(__doc__.split("Method (stated before the results, and written into the log):", 1)[1].strip() + "\n")

    res = [sweep(s) for s in SEASONS]
    pooled_rule_pct, pooled_rule_gap = [], []

    out.append("## Results\n")
    for r in res:
        s, reads, legal = r["season"], r["reads"], r["legal"]
        mean, med, sd = reads.mean(), reads.median(), reads.std(ddof=1)
        q25, q75 = np.percentile(reads, [25, 75])
        out.append(f"### {s}\n")
        out.append(f"Path chips: WC2 GW{r['wc2']}, FH2 GW{r['fh2']}, BB1 GW{r['bb1']}, "
                   f"BB2 GW{r['bb2']}. Legal TC2 weeks: {len(legal)} "
                   f"(GW{H2_START}-38 minus those three). Doubles in H2: "
                   + (", ".join(f"GW{g}:{int(v)}" for g, v in r["inv"].items()
                                if g >= H2_START) or "none") + ".\n")
        out.append("**Distribution of the TC2 read over legal weeks** "
                   "(captain_bonus, points):\n")
        out.append(f"- min {int(reads.min())}, q25 {q25:.1f}, median {med:.1f}, "
                   f"mean {mean:.2f}, q75 {q75:.1f}, max {int(reads.max())}; "
                   f"sd {sd:.2f}, n={len(reads)}")
        out.append(f"- **random-week baseline (mean over legal weeks): {mean:.2f}**")
        top = reads.sort_values(ascending=False)
        out.append("- best five weeks: " + ", ".join(
            f"GW{g} {int(v)}" for g, v in top.head(5).items()))
        out.append("- worst five weeks: " + ", ".join(
            f"GW{g} {int(v)}" for g, v in top.tail(5).items()))
        vice = [g for g in legal if r["d"].loc[g, "doubled_role"] != "captain"]
        out.append(f"- weeks where the armband fell to the vice/none: "
                   + (", ".join(f"GW{g}" for g in vice) if vice else "none") + "\n")
        out.append("**Per-week reads** (legal weeks; * = double gameweek):\n")
        out.append("| gw | teams doubling | captain | doubled | TC2 read | rank/" + str(len(legal)) + " | pctile |")
        out.append("|---|---|---|---|---|---|---|")
        for g in legal:
            v = int(reads.loc[g]); n = int(r["inv"].get(g, 0))
            out.append(f"| GW{g}{'*' if n else ''} | {n or '-'} | "
                       f"{r['d'].loc[g, 'captain']} | {r['d'].loc[g, 'doubled_role']} | "
                       f"{v} | {rank_of(reads, v)} | {100 * pct_le(reads, v):.0f}% |")
        out.append("")
        # rule of record
        out.append("**Rule of record -- largest double EXCLUDING the BB2 week:**\n")
        if not r["rule_weeks"]:
            out.append("- no other second-half double exists: the rule does not "
                       "select a week (falls to a discretionary pick).\n")
        else:
            if len(r["rule_weeks"]) > 1:
                out.append(f"- TIE: {len(r['rule_weeks'])} doubles share the largest "
                           f"team count ({int(r['cand'].max())}); the rule does not "
                           f"pick between them. All tied weeks reported.")
            for g in r["rule_weeks"]:
                v = int(reads.loc[g]); rk = rank_of(reads, v); pc = pct_le(reads, v)
                out.append(f"- {fmt_week(r, g)}: read **{v}**, rank {rk}/{len(legal)}, "
                           f"percentile {100 * pc:.0f}%, vs random-week mean "
                           f"{v - mean:+.2f} ({(v - mean) / sd:+.2f} sd)")
                pooled_rule_pct.append(pc); pooled_rule_gap.append(v - mean)
            out.append("")
        # old rule
        v = r["old_read"]
        out.append("**Old rule -- largest double overall = the BB2 week "
                   "(ILLEGAL read, comparison only):**\n")
        out.append(f"- {fmt_week(r, r['old_week'])}: read {v}; had it been legal it "
                   f"would rank {rank_of(reads, v)}/{len(legal) + 1} "
                   f"(percentile {100 * pct_le(reads, v):.0f}% of the legal weeks), "
                   f"vs random-week mean {v - mean:+.2f}.\n")
        # secondary: doubles vs singles
        if r["dbl_weeks"]:
            md = reads.loc[r["dbl_weeks"]].mean(); ms = reads.loc[r["sgl_weeks"]].mean()
            out.append(f"**Secondary -- does 'double' carry signal at all?** mean read "
                       f"on legal double weeks {md:.2f} (n={len(r['dbl_weeks'])}) vs "
                       f"single weeks {ms:.2f} (n={len(r['sgl_weeks'])}): "
                       f"{md - ms:+.2f}.\n")
        else:
            out.append("**Secondary:** no legal double weeks this season.\n")

    # pooled view
    out.append("## Pooled view (three seasons, thin sample)\n")
    if pooled_rule_pct:
        out.append(f"- rule-of-record weeks evaluated: {len(pooled_rule_pct)} "
                   f"(ties counted separately); mean percentile "
                   f"{100 * np.mean(pooled_rule_pct):.0f}%, percentiles "
                   + ", ".join(f"{100 * p:.0f}%" for p in pooled_rule_pct)
                   + f"; mean gap vs random-week baseline {np.mean(pooled_rule_gap):+.2f} "
                   f"points (gaps " + ", ".join(f"{g:+.1f}" for g in pooled_rule_gap) + ").")
        out.append("- A rule indistinguishable from random sits at the 50th "
                   "percentile with a zero mean gap. Three seasons cannot "
                   f"separate anything but a large effect: 3 seasons "
                   f"({len(pooled_rule_pct)} candidate weeks once ties are "
                   "listed; tied weeks within a season are NOT independent "
                   "draws) of ~16 legal weeks each.")
    out.append("")

    # ---------------------------------------------------------------- reading
    out.append("## Reading (data-driven; the caveats above are binding)\n")
    worst_per_season = []
    for r in res:
        if r["rule_weeks"]:
            worst_per_season.append(min(pct_le(r["reads"], int(r["reads"].loc[g]))
                                        for g in r["rule_weeks"]))
    # The first reading (2026-08-24, morning) is kept struck through with its
    # supersession marker, per house convention.
    out.append("- ~~**Not a null on this evidence.** Every rule-of-record "
               "candidate in every season sits in the top quarter of its "
               "season's legal weeks (worst candidate per season: "
               + ", ".join(f"{100 * p:.0f}%" for p in worst_per_season)
               + f"); mean gap vs the random-week baseline "
               f"{np.mean(pooled_rule_gap):+.1f} points. If the rule were "
               "picking blind, the chance that the worst candidate of all three "
               "seasons still lands in the top quarter is roughly 0.25^3 = "
               "1.6%.~~ -- **SUPERSEDED 2026-08-24 (user review): wrong null.** "
               "That test asks \"picked blind among 16 legal weeks\", but the "
               "rule picks a DOUBLE, and doubles outscore singles by "
               "construction (two matches). Conditional on landing on a double, "
               "top-quartile is far likelier than 25%, so the 1.6% measures the "
               "existence of doubles, not the rule.")
    # what IS established: play TC2 on a double
    out.append("- **Established: play TC2 on a double.** Mean read on legal "
               "double weeks vs single weeks supports it in all three seasons: "
               + "; ".join(f"{r['season']} {r['reads'].loc[r['dbl_weeks']].mean():+.1f} "
                           f"vs {r['reads'].loc[r['sgl_weeks']].mean():+.1f}"
                           for r in res if r["dbl_weeks"]) + ".")
    # what is NOT established: the largest double among doubles
    fired = []
    for r in res:
        others = [g for g in r["dbl_weeks"] if g not in r["rule_weeks"]]
        if len(r["rule_weeks"]) == 1 and others:
            g = r["rule_weeks"][0]
            fired.append(f"{r['season']}: GW{g} read {int(r['reads'].loc[g])} vs the "
                         f"other eligible doubles "
                         + "/".join(str(int(r['reads'].loc[o])) for o in others))
        elif len(r["rule_weeks"]) > 1:
            fired.append(f"{r['season']}: TIE, rule selected nothing")
    out.append("- **NOT established: that the LARGEST double is the right choice "
               "among doubles.** The correct null is \"largest double vs any "
               "double\". On that comparison the rule fired in one of three "
               "seasons and tied in the other two (" + "; ".join(fired) + "). "
               "One season is not evidence.")
    out.append("- **Weight caveat:** the largest single read in the sweep (GW24 "
               "2024-25, 29, Salah) comes from the season whose baseline is a "
               "97th-percentile draw with a 13.8% Salah concentration "
               "(Logs/why_2024_25_log.md). It should not carry weight.")
    out.append("- **The mechanism is the ordinary one, not a subtle edge:** a "
               "double gives the captain two matches. Mean read on legal "
               "double weeks vs single weeks: "
               + "; ".join(f"{r['season']} {r['reads'].loc[r['dbl_weeks']].mean():+.1f} "
                           f"vs {r['reads'].loc[r['sgl_weeks']].mean():+.1f}"
                           for r in res if r["dbl_weeks"])
               + ". Three seasons of realised captain points on one path each.")
    out.append("- **The old rule's week (BB2) is a poor TC week on these paths "
               "even ignoring legality:** its read ranks "
               + "; ".join(f"{r['season']} {rank_of(r['reads'], r['old_read'])}/"
                           f"{len(r['legal']) + 1} (captain {r['d'].loc[r['old_week'], 'captain']}, "
                           f"read {r['old_read']})" for r in res)
               + ". The bench-aware Bench Boost objective (bench weight 1.0 "
               "that week) reshapes the squad for the bench and degrades the "
               "captain choice -- the biggest-DGW week is exactly where the "
               "two chips fight over the same squad.")
    out.append("- **The rule of record needs a tie-break clause.** In two of "
               "three seasons the largest remaining double is a tie among "
               "2-team doubles, and the rule as written does not select. The "
               "candidate proposed on 2026-08-24 -- among eligible doubles, the "
               "week where the intended captain's own-cutoff predicted points "
               "are highest -- was checked for computability BEFORE adoption "
               "(next section) and is NOT computable at decision time; not "
               "adopted.")
    out.append("- **What would change the reading:** a fourth and fifth "
               "season (2021-22/2022-23 are not portable, KNOWN_ISSUES #11), "
               "or a policy-level test where TC2 is scheduled in-sim on the "
               "rule's week with the captain chosen at the deadline -- i.e. "
               "a simulation, deliberately not run here.")
    out.append("")
    # tie-break computability check (rendered by its own module; checked
    # BEFORE any adoption, per the 2026-08-24 instruction)
    import tc2_tiebreak_computability as tiebreak
    out += tiebreak.render(tiebreak.analyse_all())
    out.append("## What this is not\n")
    out.append("- Not a figure: no read here enters the chip-inclusive "
               "headline. The headline scores TC2 as zero by decision.")
    out.append("- Not a predictive test: the reads are realised captain "
               "points on one path, seen after the fact. A rule that ranks "
               "well here on three draws has demonstrated compatibility with "
               "the data, not skill.")
    out.append("- The doubles inventory is thinner than the season count: "
               "two of three seasons have no second-largest double above "
               "two teams, so the rule ties and does not pick.")

    log = REPO / "Logs" / "tc2_valuation_log.md"
    log.write_text("\n".join(out) + "\n", encoding="utf-8")
    print("\n".join(out))
    print(f"\n-> {log}")


if __name__ == "__main__":
    main()
