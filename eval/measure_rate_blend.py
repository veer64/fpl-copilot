"""D2 Phase 2 -- cross-season attacking-rate blend, tuning study.

    blend = w * (current season to date) + (1 - w) * (prior season)
    w     = n90 / (n90 + k),  n90 = current-season minutes-to-date / 90

PROTOCOL (binding, pre-stated):
- Walk-forward within season: at gameweek g every input uses gws < g only.
- Endpoint: realised npxG/90 and xA/90 over gws g..g+2, players with >= 90
  window minutes. Metrics: MAE and pooled Spearman per (season, stat).
- Tune k on 2023-24 and 2024-25 ONLY. 2025-26 is sealed: touched exactly once,
  with the k pre-registered in Logs/rate_blend_log.md BEFORE the run.
- Selection rule (stated before the sweep ran): k maximising the MEAN POOLED
  SPEARMAN over the four tuning cells (2 seasons x 2 stats); ties -> lower
  mean MAE. Grid: 0.5, 1, 2, 3, 5, 8, 12, 20, 40.

RATES are ratio-of-sums (sum stat / sum minutes * 90), never means of
per-match ratios -- the GK-investigation H2 lesson.

PRIOR: the player's immediately-previous season, >= 450 minutes (MIN_TIME
precedent). Fallback hierarchy for players without one (new signings,
promoted-team players, thin priors), counted and reported per tier:
  tier 1: position-average prior-season rate; position = modal current-season
          position among gws < g (point-in-time safe);
  tier 2: league-average prior-season rate (position unknowable, e.g. any
          debutant at GW1).
GK-group players are excluded -- attacking rates are an outfield concept.

CROSSWALK: this study never leaves understat-id space (prior-season joins are
understat->understat), so no crosswalk join occurs and the KNOWN_ISSUES #3
sweep is not exercised here. It remains MANDATORY at integration time --
call understat_matches.assert_crosswalk_unique() before any element join.

BASELINE: the production static rate -- attacking_rates.get_rates(season)
(pooled 3 prior seasons, k=2 FWD-npxG / k=10 otherwise), constant across the
season -- evaluated on the identical windows and rows.

Usage:
    uv run python eval/measure_rate_blend.py --tune
    uv run python eval/measure_rate_blend.py --holdout K   # sealed 2025-26, once
"""
import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "squad"))

DATA = REPO / "data" / "history"
GRID = [0.5, 1, 2, 3, 5, 8, 12, 20, 40]
MIN_PRIOR_MINUTES = 450
WINDOW = 3
MIN_WINDOW_MINUTES = 90
TUNE_SEASONS = {"2023-24": "2022-23", "2024-25": "2023-24"}
HOLDOUT = {"2025-26": "2024-25"}
STATS = ["npxG", "xA"]


def _pos_group(p):
    if p in (None, "Sub") or (isinstance(p, float) and np.isnan(p)):
        return None
    if p == "GK":
        return "GK"
    if p in ("DC", "DL", "DR"):
        return "D"
    if "M" in p:
        return "M"
    if p.startswith("FW"):
        return "F"
    return None


def load_season(season):
    """(player, gw) sums plus per-gw modal position group."""
    df = pd.read_parquet(DATA / f"understat_matches_{season.replace('-', '_')}.parquet")
    df["grp"] = df["position"].map(_pos_group)
    g = (df.groupby(["understat_player_id", "gw"])
         .agg(npxG=("npxG", "sum"), xA=("xA", "sum"), minutes=("minutes", "sum"),
              grp=("grp", lambda s: s.dropna().mode().iloc[0] if s.dropna().size else None))
         .reset_index())
    return g


def prior_tables(prior_season):
    """Player prior rates (>=450 min), position-average rates, league average."""
    g = load_season(prior_season)
    per = (g.groupby("understat_player_id")
           .agg(npxG=("npxG", "sum"), xA=("xA", "sum"), minutes=("minutes", "sum"),
                grp=("grp", lambda s: s.dropna().mode().iloc[0] if s.dropna().size else None))
           .reset_index())
    per = per[per["grp"] != "GK"]
    elig = per[per["minutes"] >= MIN_PRIOR_MINUTES].copy()
    for s in STATS:
        elig[f"{s}90"] = elig[s] / elig["minutes"] * 90
    player = elig.set_index("understat_player_id")[[f"{s}90" for s in STATS]]
    outf = per[per["grp"].notna()]
    pos = {grp: {s: sub[s].sum() / sub["minutes"].sum() * 90 for s in STATS}
           for grp, sub in outf.groupby("grp")}
    league = {s: outf[s].sum() / outf["minutes"].sum() * 90 for s in STATS}
    return player, pos, league


def walkforward_frame(season, prior_season):
    """One evaluation frame: a row per (player, g) with to-date inputs, prior
    inputs, fallback tier, and the realised window rates. k-independent, so the
    sweep reuses it."""
    g = load_season(season)
    player_prior, pos_prior, league_prior = prior_tables(prior_season)
    gw_max = int(g["gw"].max())

    piv = {c: g.pivot_table(index="understat_player_id", columns="gw",
                            values=c, aggfunc="sum").reindex(columns=range(1, gw_max + 1))
           for c in ("npxG", "xA", "minutes")}
    players = piv["minutes"].index
    cum = {c: piv[c].fillna(0).cumsum(axis=1) for c in piv}

    # modal position group to date: forward-filled first-seen-then-updated mode
    grp_wide = g.pivot_table(index="understat_player_id", columns="gw", values="grp",
                             aggfunc="first").reindex(columns=range(1, gw_max + 1))

    rows = []
    for gg in range(1, gw_max - WINDOW + 2):
        w_end = gg + WINDOW - 1
        win_min = piv["minutes"].loc[:, gg:w_end].sum(axis=1, min_count=1).fillna(0)
        elig = win_min >= MIN_WINDOW_MINUTES
        if gg > 1:
            td_min = cum["minutes"].loc[:, gg - 1]
            td = {s: cum[s].loc[:, gg - 1] for s in STATS}
            grp_td = grp_wide.loc[:, :gg - 1].apply(
                lambda r: r.dropna().mode().iloc[0] if r.dropna().size else None, axis=1)
        else:
            td_min = pd.Series(0.0, index=players)
            td = {s: pd.Series(0.0, index=players) for s in STATS}
            grp_td = pd.Series(None, index=players, dtype=object)

        for pid in players[elig]:
            grp = grp_td.get(pid)
            if grp == "GK":
                continue
            has_prior = pid in player_prior.index
            if has_prior:
                tier = 0
                prior = {s: player_prior.at[pid, f"{s}90"] for s in STATS}
            elif grp in pos_prior:
                tier = 1
                prior = {s: pos_prior[grp][s] for s in STATS}
            else:
                tier = 2
                prior = {s: league_prior[s] for s in STATS}
            m = float(td_min.get(pid, 0.0))
            cur = {s: (float(td[s].get(pid, 0.0)) / m * 90) if m > 0 else 0.0
                   for s in STATS}
            realised = {s: float(piv[s].loc[pid, gg:w_end].sum()) /
                        float(win_min[pid]) * 90 for s in STATS}
            rows.append({"g": gg, "pid": pid, "n90": m / 90.0, "tier": tier,
                         **{f"cur_{s}": cur[s] for s in STATS},
                         **{f"prior_{s}": prior[s] for s in STATS},
                         **{f"real_{s}": realised[s] for s in STATS}})
    return pd.DataFrame(rows)


def score_blend(frame, k):
    w = frame["n90"] / (frame["n90"] + k)
    out = {}
    for s in STATS:
        pred = w * frame[f"cur_{s}"] + (1 - w) * frame[f"prior_{s}"]
        out[f"mae_{s}"] = float((pred - frame[f"real_{s}"]).abs().mean())
        out[f"rho_{s}"] = float(spearmanr(pred, frame[f"real_{s}"]).statistic)
    return out


def score_baseline(frame, season):
    """Production static rates on the same rows. Missing players fall back to
    the module's own position priors (grp from the frame's walk-forward modal
    position; league mean of priors when unknown)."""
    import attacking_rates as ar
    rates, priors = ar.get_rates(predict_season=season)
    rates = rates.copy()
    rates["understat_id"] = rates["understat_id"].astype(str)
    # get_rates() can return the same understat_id twice when a player carried
    # different position labels across the pooled prior seasons (each position
    # pool is shrunk separately, then concatenated). Mean the duplicates for
    # this evaluation; noted in the study report.
    n_dup = int(rates.duplicated("understat_id").sum())
    r = rates.groupby("understat_id")[["npxg90", "xa90"]].mean()
    league = {s: float(np.mean([priors[p]["npxg" if s == "npxG" else "xa"]
                                for p in priors])) for s in STATS}
    key = {"npxG": "npxg90", "xA": "xa90"}
    pkey = {"npxG": "npxg", "xA": "xa"}
    out, n_fallback = {}, 0
    preds = {s: [] for s in STATS}
    grp_col = frame.get("grp") if "grp" in frame.columns else None
    for _, row in frame.iterrows():
        pid = str(row["pid"])
        for s in STATS:
            if pid in r.index and pd.notna(r.at[pid, key[s]]):
                preds[s].append(float(r.at[pid, key[s]]))
            else:
                preds[s].append(league[s])
                n_fallback += 1
    for s in STATS:
        p = pd.Series(preds[s], index=frame.index)
        out[f"mae_{s}"] = float((p - frame[f"real_{s}"]).abs().mean())
        out[f"rho_{s}"] = float(spearmanr(p, frame[f"real_{s}"]).statistic)
    out["n_fallback_lookups"] = n_fallback
    out["n_dup_ids_in_rates"] = n_dup
    return out


def report_frame_stats(name, frame):
    n = len(frame)
    tiers = frame["tier"].value_counts().to_dict()
    print(f"{name}: {n} evaluation rows, {frame['pid'].nunique()} players, "
          f"g {int(frame['g'].min())}-{int(frame['g'].max())}")
    print(f"  fallback tiers: player-prior {tiers.get(0, 0)}, "
          f"position-avg {tiers.get(1, 0)}, league-avg {tiers.get(2, 0)} "
          f"({(tiers.get(1, 0) + tiers.get(2, 0)) / n:.1%} without a usable prior)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tune", action="store_true")
    ap.add_argument("--holdout", type=float, default=None,
                    help="run sealed 2025-26 ONCE with this pre-registered k")
    args = ap.parse_args()

    if args.tune:
        frames = {}
        for season, prior in TUNE_SEASONS.items():
            frames[season] = walkforward_frame(season, prior)
            report_frame_stats(season, frames[season])
        print(f"\nk-sweep (grid {GRID}); selection rule: max mean pooled "
              "Spearman over the four cells, ties -> lower mean MAE")
        hdr = (f"{'k':>5s} " + " ".join(f"{se[-5:]}:{s}-rho" for se in TUNE_SEASONS
                                        for s in ("npxG", "xA"))
               + "  mean_rho  mean_mae")
        print(hdr)
        best = None
        for k in GRID:
            cells = {se: score_blend(frames[se], k) for se in TUNE_SEASONS}
            rhos = [cells[se][f"rho_{s}"] for se in TUNE_SEASONS for s in STATS]
            maes = [cells[se][f"mae_{s}"] for se in TUNE_SEASONS for s in STATS]
            mean_rho, mean_mae = float(np.mean(rhos)), float(np.mean(maes))
            print(f"{k:5.1f} " + " ".join(f"{v:9.4f}" for v in rhos)
                  + f"  {mean_rho:8.4f}  {mean_mae:8.4f}")
            if best is None or (mean_rho, -mean_mae) > (best[1], -best[2]):
                best = (k, mean_rho, mean_mae)
        print(f"\nselected k = {best[0]} (mean rho {best[1]:.4f}, "
              f"mean MAE {best[2]:.4f}) -- PRE-REGISTER IN "
              "Logs/rate_blend_log.md BEFORE running --holdout")
        print("\nProduction baseline on the same rows:")
        for se in TUNE_SEASONS:
            b = score_baseline(frames[se], se)
            print(f"  {se}: " + "  ".join(
                f"{s}: MAE {b[f'mae_{s}']:.4f} rho {b[f'rho_{s}']:.4f}" for s in STATS)
                + f"  (fallback lookups: {b['n_fallback_lookups']})")

    elif args.holdout is not None:
        log = (REPO / "Logs" / "rate_blend_log.md")
        if not log.exists() or f"k = {args.holdout:g}" not in log.read_text(encoding="utf-8"):
            sys.exit("REFUSING: pre-register the chosen k in Logs/rate_blend_log.md "
                     "first (a line containing 'k = <value>').")
        season, prior = next(iter(HOLDOUT.items()))
        frame = walkforward_frame(season, prior)
        report_frame_stats(season, frame)
        res = score_blend(frame, args.holdout)
        print(f"\nSEALED {season}, k={args.holdout:g}: " + "  ".join(
            f"{s}: MAE {res[f'mae_{s}']:.4f} rho {res[f'rho_{s}']:.4f}" for s in STATS))
        b = score_baseline(frame, season)
        print(f"baseline:            " + "  ".join(
            f"{s}: MAE {b[f'mae_{s}']:.4f} rho {b[f'rho_{s}']:.4f}" for s in STATS)
            + f"  (fallback lookups: {b['n_fallback_lookups']})")
    else:
        ap.error("--tune or --holdout K")


if __name__ == "__main__":
    main()
