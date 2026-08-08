# attacking_rates.py
# Empirical-Bayes shrinkage of attacking rates (npxG/90, xA/90).
# Module form for assembly: get_rates() returns (rates, priors) in the exact
# shape assembly.py consumes.
#
# Full investigation (noise measurement, k-gridsearch, robustness tests, finishing
# & price-tier negatives) is in Shrinkage_log — stripped here.
#
# Final rule (verified against the log):
#   shrunk = w*raw + (1-w)*prior, w = n90/(n90+k), n90 = time/90
#   prior  = per-position average rate (over the pooled prior seasons)
#   k      = 2 for FWD npxG (most reliable), 10 for everything else
#   source = understat_season_aggregates.parquet, keyed on stable Understat id
#            (Bug #2: numeric cols are strings -> pd.to_numeric on load)
#
# LEAKAGE FIX (2026-08): rates for a predicted season are now built from PRIOR
# seasons only (pooled), never the season being predicted. The old
# get_rates_2526("2025") used 2025-26's OWN full-season totals to predict 2025-26
# gameweeks — future information leaking backward. The shrinkage method was always
# validated cross-season (Shrinkage_log §4.1: last season's rate predicts next
# season's), so prior-season rates are the design-correct, leak-free input.
# Counts are POOLED across prior seasons (more minutes -> steadier prior, log §8.1).
#
# NOTE: assembly uses the plain SHRUNK rate (npxg90 / xa90). The defender
# shot-volume adjustment (+0.081 for DEF) is a documented future improvement,
# not wired in. Time-decay across the pooled seasons is also future work.

import pandas as pd

BASE = r"C:\Users\veers\OneDrive\Documents\FPL Agent\fpl-copilot"
MIN_TIME = 450        # ~5 full matches of pooled time for a usable rate

# Map a predicted FPL season -> the Understat prior seasons that feed its rates.
# Understat labels by start-year: "2024" == 2024-25. Predicting 2025-26 uses
# 2022,2023,2024 (the three seasons before it).
PRIOR_SEASONS = {
    "2025-26": ["2022", "2023", "2024"],
}

_NUM_COLS = ["games", "time", "goals", "xG", "assists", "xA", "shots", "key_passes",
             "yellow_cards", "red_cards", "npg", "npxG", "xGChain", "xGBuildup"]


def _k_for(stat, pos_label):
    return 2 if (stat == "npxG" and pos_label == "F") else 10


def _load_understat():
    us = pd.read_parquet(BASE + r"\data\history\understat_season_aggregates.parquet")
    for c in _NUM_COLS:
        us[c] = pd.to_numeric(us[c])      # Bug #2
    return us


def _pool_prior_seasons(us, prior_seasons, pos_label):
    """Pool a player's counts across the prior seasons (one row per player).
    Summing counts (npxG, xA, time, ...) weights naturally by minutes played:
    a 3-season regular gets a stable rate, a one-season player a noisier one."""
    pool = us[(us["understat_season"].isin(prior_seasons))
              & (us["position"].str.contains(pos_label, na=False))].copy()
    if pool.empty:
        return pool
    # sum the count-like columns per player across the prior seasons
    agg = pool.groupby("id", as_index=False).agg(
        time=("time", "sum"),
        npxG=("npxG", "sum"),
        xA=("xA", "sum"),
    )
    return agg


def _shrunk_rate(pooled, pos_label, stat):
    """Per-position shrinkage of `stat`/90 on POOLED prior-season counts.
    Returns (frame[id, shrunk], prior)."""
    pool = pooled[pooled["time"] >= MIN_TIME].copy()
    if len(pool) < 10:
        return None, None
    prior = pool[stat].sum() / pool["time"].sum() * 90        # per-position pooled average
    raw = pool[stat] / pool["time"] * 90
    n90 = pool["time"] / 90
    w = n90 / (n90 + _k_for(stat, pos_label))
    pool["shrunk"] = w * raw + (1 - w) * prior
    return pool[["id", "shrunk"]], prior


def get_rates(predict_season="2025-26", prior_seasons=None):
    """Produce the assembly inputs for the predicted season, built from PRIOR
    seasons only (leak-free). Returns:
      rates  : DataFrame[understat_id, npxg90, xa90]  (plain shrunk rates)
      priors : {pos_label: {'npxg': float, 'xa': float}}  position-average fallbacks
    """
    if prior_seasons is None:
        prior_seasons = PRIOR_SEASONS[predict_season]

    us = _load_understat()
    npxg_rows, xa_rows, priors = [], [], {}
    for pos in ["F", "M", "D"]:
        pooled = _pool_prior_seasons(us, prior_seasons, pos)
        if pooled.empty:
            continue
        npxg, npxg_prior = _shrunk_rate(pooled, pos, "npxG")
        xa, xa_prior = _shrunk_rate(pooled, pos, "xA")
        if npxg is None:
            continue
        npxg_rows.append(npxg.rename(columns={"shrunk": "npxg90"}))
        xa_rows.append(xa.rename(columns={"shrunk": "xa90"}))
        priors[pos] = {"npxg": npxg_prior, "xa": xa_prior}

    npxg_tbl = pd.concat(npxg_rows)
    xa_tbl = pd.concat(xa_rows)
    rates = npxg_tbl.merge(xa_tbl, on="id", how="outer").rename(columns={"id": "understat_id"})
    return rates, priors


# Backward-compat shim: old callers used get_rates_2526("2025").
# Now leak-free — ignores the passed season and builds 2025-26 from prior seasons.
def get_rates_2526(season="2025"):
    return get_rates("2025-26")


if __name__ == "__main__":
    rates, priors = get_rates("2025-26")
    print(f"Attacking rates for 2025-26 (from prior seasons 2022-24): {len(rates)} players")
    print("Priors:", {p: {k: round(v, 3) for k, v in d.items()} for p, d in priors.items()})
    # sanity: top npxG should be elite forwards (rated on their PRIOR-season output)
    us = _load_understat()
    names = us[us["understat_season"].isin(["2022", "2023", "2024"])][["id", "player_name"]].drop_duplicates("id")
    chk = rates.merge(names, left_on="understat_id", right_on="id", how="left")
    print("\nTop npxG/90 (should be elite forwards):")
    print(chk.sort_values("npxg90", ascending=False).head(8)[
        ["player_name", "npxg90", "xa90"]].to_string(index=False))