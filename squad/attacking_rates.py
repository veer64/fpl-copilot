# attacking_rates.py
# Empirical-Bayes shrinkage of attacking rates (npxG/90, xA/90).
# Module form for assembly: get_rates_2526() returns (rates, priors) in the exact
# shape assembly.py consumes.
#
# Full investigation (noise measurement, k-gridsearch, robustness tests, finishing
# & price-tier negatives) is in Shrinkage_log — stripped here.
#
# Final rule (verified against the log):
#   shrunk = w*raw + (1-w)*prior, w = n90/(n90+k), n90 = time/90
#   prior  = per-position, per-season average rate
#   k      = 2 for FWD npxG (most reliable), 10 for everything else
#   source = understat_season_aggregates.parquet, keyed on stable Understat id
#            (Bug #2: numeric cols are strings -> pd.to_numeric on load)
#
# NOTE: assembly uses the plain SHRUNK rate (npxg90 / xa90) — the validated 0.716
# result. The defender shot-volume adjustment (+0.081 for DEF) is a documented
# future improvement, not wired into the validated assembly.

import pandas as pd

BASE = r"C:\Users\veers\OneDrive\Documents\FPL Agent\fpl-copilot"
MIN_TIME = 450        # ~5 full matches for a usable season rate

_NUM_COLS = ["games", "time", "goals", "xG", "assists", "xA", "shots", "key_passes",
             "yellow_cards", "red_cards", "npg", "npxG", "xGChain", "xGBuildup"]


def _k_for(stat, pos_label):
    return 2 if (stat == "npxG" and pos_label == "F") else 10


def _load_understat():
    us = pd.read_parquet(BASE + r"\data\history\understat_season_aggregates.parquet")
    for c in _NUM_COLS:
        us[c] = pd.to_numeric(us[c])      # Bug #2
    return us


def _shrunk_rate(us, season, pos_label, stat):
    """Per-position, per-season shrinkage of `stat`/90. Returns (frame[id, shrunk], prior)."""
    pool = us[(us["understat_season"] == season)
              & (us["position"].str.contains(pos_label, na=False))
              & (us["time"] >= MIN_TIME)].copy()
    if len(pool) < 10:
        return None, None
    prior = pool[stat].sum() / pool["time"].sum() * 90        # per-position season average
    raw = pool[stat] / pool["time"] * 90
    n90 = pool["time"] / 90
    w = n90 / (n90 + _k_for(stat, pos_label))
    pool["shrunk"] = w * raw + (1 - w) * prior
    return pool[["id", "shrunk"]], prior


def get_rates_2526(season="2025"):
    """Produce the assembly inputs for the given Understat season (default '2025' =
    the 2025-26 season). Returns:
      rates  : DataFrame[understat_id, npxg90, xa90]  (plain shrunk rates)
      priors : {pos_label: {'npxg': float, 'xa': float}}  position-average fallbacks
    """
    us = _load_understat()
    npxg_rows, xa_rows, priors = [], [], {}
    for pos in ["F", "M", "D"]:
        npxg, npxg_prior = _shrunk_rate(us, season, pos, "npxG")
        xa, xa_prior = _shrunk_rate(us, season, pos, "xA")
        if npxg is None:
            continue
        npxg_rows.append(npxg.rename(columns={"shrunk": "npxg90"}))
        xa_rows.append(xa.rename(columns={"shrunk": "xa90"}))
        priors[pos] = {"npxg": npxg_prior, "xa": xa_prior}

    npxg_tbl = pd.concat(npxg_rows)
    xa_tbl = pd.concat(xa_rows)
    rates = npxg_tbl.merge(xa_tbl, on="id", how="outer").rename(columns={"id": "understat_id"})
    return rates, priors


if __name__ == "__main__":
    rates, priors = get_rates_2526("2025")
    print(f"Attacking rates for 2025-26: {len(rates)} players")
    print("Priors:", {p: {k: round(v, 3) for k, v in d.items()} for p, d in priors.items()})
    # sanity: top npxG should be elite forwards
    us = _load_understat()
    names = us[us["understat_season"] == "2025"][["id", "player_name"]].drop_duplicates("id")
    chk = rates.merge(names, left_on="understat_id", right_on="id", how="left")
    print("\nTop npxG/90 (should be elite forwards):")
    print(chk.sort_values("npxg90", ascending=False).head(8)[
        ["player_name", "npxg90", "xa90"]].to_string(index=False))