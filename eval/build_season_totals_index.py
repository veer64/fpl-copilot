# build_season_totals_index.py
# Assemble every season total the project has produced into ONE table with
# provenance, so figures stop being scattered archaeology.
# Writes Logs/season_totals_index.md. Reporting only -- no simulations.

import datetime as dt
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parent.parent
CHIPS, SWEEP = REPO / "data" / "chips", REPO / "data" / "sweep"

# Average manager scores. CLAIMED = the figures supplied for this report;
# ONDISK = fplcache post-season snapshot, sum of events[].average_entry_score.
# 2025-26 matches exactly; 2023-24 and 2024-25 do NOT (the two statistics are
# not the same definition -- see the doc header).
AVG_CLAIMED = {"2023-24": 2038, "2024-25": 2154, "2025-26": 1895}
AVG_ONDISK = {"2023-24": 2003, "2024-25": 2008, "2025-26": 1895}

STAMPS = ["minutes_availability", "odds_horizon_gws", "dgw_handling",
          "d1_terms_active", "cs_unified", "rate_blend_active",
          "dc_rule_active", "synthetic_lambda_active"]


def stamp_str(path):
    cols = pd.read_parquet(path).columns
    have = [c for c in STAMPS if c in cols]
    row = pd.read_parquet(path, columns=have).iloc[0]
    synth = bool(row.get("synthetic_lambda_active", False))
    return ("post-#15 canonical" + ("+synth" if synth else "")), \
        dt.datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d")


def rows_from_chips():
    out = []
    for p in sorted(CHIPS.glob("chiplog_*.parquet")):
        d = pd.read_parquet(p)
        season, config = d["season"].iloc[0], d["config"].iloc[0]
        tag = season.replace("-", "_")
        decay = 0.6 if config.endswith("_d60") else 0.85
        aware = bool(d.get("bench_boost_aware", pd.Series([False])).iloc[0])
        chips = "none" if config == "baseline" else config
        wf = f"walkforward_h6_{tag}.parquet"
        fam, built = stamp_str(REPO / "data" / wf)
        out.append(dict(season=season, H=6, decay=decay, chips=chips,
                        synth="off", wf=wf, family=fam, built=built,
                        bb_aware=aware, total=int(d["final_total"].iloc[0]),
                        source=f"chips/{p.name}"))
    return out


def rows_from_sweep():
    out = []
    for p in sorted(SWEEP.glob("simlog_*.parquet")):
        d = pd.read_parquet(p, columns=["season", "variant", "horizon",
                                        "decay", "final_total"])
        season = d["season"].iloc[0]
        tag = season.replace("-", "_")
        synth = d["variant"].iloc[0] == "synth"
        wf = f"walkforward_h6_{tag}{'_synth' if synth else ''}.parquet"
        fam, built = stamp_str(REPO / "data" / wf)
        out.append(dict(season=season, H=int(d["horizon"].iloc[0]),
                        decay=float(d["decay"].iloc[0]), chips="none",
                        synth="on" if synth else "off", wf=wf, family=fam,
                        built=built, bb_aware=False,
                        total=int(d["final_total"].iloc[0]),
                        source=f"sweep/{p.name}"))
    return out


REFERENCES = [
    dict(season="2025-26", H=3, decay=0.3, chips="none", synth="off",
         wf="walkforward_h6_2526_prefix.parquet (preserved)",
         family="PRE-M3, pre-D1, pre-blend, pre-#15", built="2026-08-11",
         bb_aware=False, total=1984, source="wildcard_and_determinism.md"),
    dict(season="2025-26", H=3, decay=0.3, chips="none", synth="off",
         wf="(availability=True rebuild, same era)",
         family="pre-D1, pre-blend, pre-#15", built="2026-08-13",
         bb_aware=False, total=1938, source="eval/walkforward.py docstring"),
    dict(season="2025-26", H=6, decay=0.85, chips="none", synth="off",
         wf="(D1 Variant B, static rates)",
         family="pre-blend, pre-#15", built="2026-08-17",
         bb_aware=False, total=2028, source="d1_log.md section 9"),
    dict(season="2025-26", H=6, decay=0.85, chips="none", synth="off",
         wf="(rate blend k=8, pre-#15 DC base rates)",
         family="pre-#15", built="2026-08-18",
         bb_aware=False, total=2060, source="rate_blend_log.md section 7"),
]


def main():
    rows = rows_from_chips() + rows_from_sweep() + REFERENCES
    df = pd.DataFrame(rows)
    df["margin_claimed"] = df.apply(
        lambda r: r["total"] - AVG_CLAIMED[r["season"]], axis=1)
    df["margin_ondisk"] = df.apply(
        lambda r: r["total"] - AVG_ONDISK[r["season"]], axis=1)
    df = df.sort_values(["family", "season", "H", "decay", "synth", "chips"])

    lines = ["# Season totals index -- every simulated season total, one place",
             "",
             f"Generated {dt.date.today()} by eval/build_season_totals_index.py.",
             "",
             "**Framing (mandatory):** a season total is ONE draw from a",
             "distribution with path sd ~60 (M1 failed). This index exists so",
             "figures can be LOCATED and grouped by provenance -- comparisons",
             "are valid ONLY within a family AND only between rows differing",
             "by exactly the variable under test. Season totals never decide",
             "adoptions; component and windowed metrics do.",
             "",
             "**Average-manager verification:** claimed averages 2038 / 2154 /",
             "1895 vs fplcache sum of events[].average_entry_score 2003 / 2008",
             "/ 1895. 2025-26 MATCHES; 2023-24 is 35 off; 2024-25 is 146 off.",
             "The statistics differ by definition (sum of per-GW averages !=",
             "average of season totals; late entries and chips break the",
             "equivalence), so BOTH margins are shown.",
             "",
             "**Provenance notes:** (1) the 2023-24 sweep sims ran against the",
             "pre-#15-rebuild canonical, proven BIT-IDENTICAL to the rebuilt",
             "file (dc_enabled=False season), so they belong to the post-#15",
             "family. (2) The 2023-24/2024-25 _synth files predate the #15",
             "rebuild but are DC-irrelevant seasons -- same family. (3) All",
             "four REFERENCE rows predate the DC-wiring fix (#15); 1984/1938",
             "also predate D1 and the rate blend; 2028 predates the blend.",
             "They are comparable to NOTHING in this index.",
             "(4) bb_aware=True rows flip transfer_mip.BENCH_BOOST_AWARE --",
             "their baseline (gate off) differs by chips+gate JOINTLY: that",
             "package is the declared variable (p4 log section 8).",
             "",
             "| season | H | decay | chips | synth λ | bb-aware | walkforward file | family | built | total | vs avg (claimed) | vs avg (fplcache) | source |",
             "|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for _, r in df.iterrows():
        lines.append(
            f"| {r.season} | {r.H} | {r.decay} | {r.chips} | {r.synth} | "
            f"{'Y' if r.bb_aware else '-'} | {r.wf} | {r.family} | {r.built} | "
            f"**{r.total}** | {r.margin_claimed:+d} | {r.margin_ondisk:+d} | "
            f"{r.source} |")

    lines += ["",
              "## Valid comparisons (exhaustive)",
              "",
              "1. **Chip effects**: any chips/bb-aware row vs the SAME season's",
              "   `baseline` chips row at H=6 decay=0.85 (family post-#15,",
              "   synth off). Variable = the chip package.",
              "2. **combined_d60** vs the same season's sweep `base H6 d60` row.",
              "3. **D4 base-vs-synth**: sweep rows within the same (season, H,",
              "   decay) -- the 27 matched pairs of the sign test.",
              "4. Nothing else. Cross-H, cross-decay, cross-season and every",
              "   REFERENCE row: NOT comparable.",
              "",
              "## Explicit flags",
              "",
              "- No baseline is missing: every post-#15 config has a same-family",
              "  baseline on disk.",
              "- One historical cross-provenance comparison was ATTEMPTED and",
              "  caught before measurement: D4 Phase 2's first 2025-26 synth",
              "  build used the wrong writer (stamps differed); rebuilt before",
              "  any number was read (overnight log, stage 2).",
              "- The four reference figures are retained for lineage only."]

    out = REPO / "Logs" / "season_totals_index.md"
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"{len(df)} rows -> {out}")
    print(df.groupby(["family", "season"]).size().to_string())


if __name__ == "__main__":
    main()
