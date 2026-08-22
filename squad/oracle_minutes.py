"""
ORACLE MINUTES — a MEASURING INSTRUMENT, never a model.

========================  WARNING — DELIBERATE LEAKAGE  ========================
This module injects REALIZED minutes into the prediction frame. It exists for
exactly one purpose: the team-news step-4 upper bound — what would perfect
lineup knowledge be worth? It must NEVER be adopted, defaulted on, or allowed
anywhere near a production or backtest-of-record run. The gate rests False;
every decision-log row is stamped `oracle_minutes_active` so any artefact
built under it is permanently marked. If you are reading this because the
flag showed up True somewhere unexpected: that run is invalid, discard it.
==============================================================================

The transform (per prediction row, everything else stays PREDICTED):
  e_minutes   -> realized minutes
  p_play_any  -> 1{minutes > 0};  p_60plus -> 1{minutes >= 60}
  pts_appear  -> 2/1/0 by the same indicators (exact)
  pts_cs      -> p_cs * CS_PTS[pos] * 1{minutes >= 60}   (exact recompute)
  pts_dc      -> 2 * p_dc_hit * 1{minutes >= 60}          (exact recompute)
  attacking / saves / conceded / cards / bonus terms -> scaled by
      clip(minutes / max(e_minutes, 30), 0, 2.5)          (stated APPROXIMATION
      of re-running the assembly at oracle minutes; rates stay predicted)
  e_points    -> the sum of the above
Realized minutes are per (cutoff, gw, element) row, i.e. the oracle knows
minutes across the WHOLE planning horizon — deliberately stronger than any
lineup service (which sells next-deadline knowledge only). Upper bound.
"""

import numpy as np
import pandas as pd

# The gate. False on disk, flipped in-process only by the step-4/5 drivers.
ORACLE_MINUTES_ACTIVE = False
# Step-5 restrictions (set by the driver alongside the gate):
#   "full"         -- every row (the step-4 horizon-wide oracle)
#   "step0"        -- realized minutes at horizon_step 0 only (arm A: the
#                     slice a lineup service sells)
#   "masked_step0" -- step 0 AND (gw, element) in ORACLE_MASK (arm B:
#                     structurally knowable; arm C: Guardian-reported)
ORACLE_MODE = "full"
ORACLE_MASK = None          # set of (gw, element) for masked_step0

CS_PTS = {"GK": 4.0, "DEF": 4.0, "MID": 1.0, "FWD": 0.0}


def apply_oracle_minutes(df):
    """Return a copy of the walk-forward frame with minutes-derived terms
    replaced by their realized-minutes versions. Requires the component
    columns; raises loudly if any is missing (no silent partial oracle)."""
    need = ["minutes", "e_minutes", "pts_appear", "pts_goals", "pts_assists",
            "pts_cs", "pts_dc", "pts_saves", "pts_conceded", "pts_cards",
            "exp_bonus", "p_cs", "p_dc_hit", "position", "e_points"]
    missing = [c for c in need if c not in df.columns]
    if missing:
        raise ValueError(f"oracle transform needs columns {missing} -- "
                         "refusing a partial oracle")
    d = df.copy()
    if ORACLE_MODE == "full":
        sel = pd.Series(True, index=d.index)
    elif ORACLE_MODE == "step0":
        sel = d["cutoff"] == d["gw"]
    elif ORACLE_MODE == "masked_step0":
        if not ORACLE_MASK:
            raise ValueError("masked_step0 needs a non-empty ORACLE_MASK")
        keys = pd.MultiIndex.from_arrays([d["gw"], d["element"]])
        sel = (d["cutoff"] == d["gw"]) \
            & keys.isin(pd.MultiIndex.from_tuples(sorted(ORACLE_MASK)))
    else:
        raise ValueError(f"unknown ORACLE_MODE {ORACLE_MODE!r}")
    untouched = d[~sel]
    d = d[sel].copy()
    m = pd.to_numeric(d["minutes"], errors="coerce").fillna(0.0).astype(float)
    played = (m > 0).astype(float)
    sixty = (m >= 60).astype(float)
    e_min = pd.to_numeric(d["e_minutes"], errors="coerce").fillna(0.0)
    factor = np.clip(m / np.maximum(e_min, 30.0), 0.0, 2.5)

    appear = 2.0 * sixty + 1.0 * (played - sixty)
    cs_val = d["position"].map(CS_PTS).astype(float)
    pts_cs = d["p_cs"].astype(float) * cs_val * sixty
    pts_dc = 2.0 * d["p_dc_hit"].astype(float) * sixty
    scaled = (d[["pts_goals", "pts_assists", "pts_saves", "pts_conceded",
                 "pts_cards", "exp_bonus"]].astype(float)
              .mul(factor, axis=0))

    d["e_points"] = (appear + pts_cs + pts_dc + scaled.sum(axis=1))
    d["pts_appear"], d["pts_cs"], d["pts_dc"] = appear, pts_cs, pts_dc
    for c in ("pts_goals", "pts_assists", "pts_saves", "pts_conceded",
              "pts_cards", "exp_bonus"):
        d[c] = scaled[c]
    d["e_minutes"] = m
    if "p_play_any" in d.columns:
        d["p_play_any"] = played
    if "p_60plus" in d.columns:
        d["p_60plus"] = sixty
    out = pd.concat([d, untouched]).sort_index()
    print(f"[oracle] mode={ORACLE_MODE}: {len(d):,} of {len(out):,} rows "
          "transformed", flush=True)
    return out
