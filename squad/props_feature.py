# props_feature.py
# The player-prop feature at STEP 0 of the assembly, conditional-rate
# specification (Logs/props_conditional_prereg.md section 2, PRE-REGISTERED
# VALUE 2026-08-26: spec = conditional, w = 0.75, m = 1.396).
#
#   p_b,uncond = p_b(adj) * P_b(appears) / m        per book b, per fixture
#   p_mkt      = mean over books of p_b,uncond        (equal weight, merged by element)
#   lambda_mkt = -ln(1 - p_mkt)
#   e_goals    = w * lambda_mkt + (1 - w) * e_goals(model)      per FIXTURE
#
# P_b(appears) follows the book's verified void rule: p_play_any (takes part)
# for DraftKings / BetMGM / Bovada and, ASSIGNED and UNVERIFIED, FanDuel /
# 1xBet; p_start (must start) for BetRivers / MyBookie. The appearance
# probabilities are the cutoff's OWN minutes frame (the same rows the
# equation gates on), so nothing after the cutoff enters.
#
# Applied to step-0 rows only (gw == cutoff): props are a step-0 feature by
# construction (props_prereg.md section 6, arm (a)); steps 1-5 keep the
# model's rate. Goalkeepers are never touched (amendment 2). A doubling
# player with only one of two fixtures priced keeps the model on BOTH
# fixtures and is counted (amendment 3). Unpriced rows keep the model.
#
# GATE + PROVENANCE. PROPS_ACTIVE rests False and nothing in production reads
# this module; the arm builder (eval/walkforward_arms.py) installs a PropsHook
# on assembly.PROPS_HOOK in-process and stamps every emitted row with
# `props_active` and `props_spec` (the #13 lesson). The feature FAILED the
# pre-registered component test on its tuning season (condition 1, likely
# starters +0.0094 < +0.020); this module exists so the season figures can be
# produced, and those figures are not adoption evidence.

from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parent.parent

PROPS_ACTIVE = False                      # production gate; rests False
PROPS_W = 0.75                            # by prior (props_prereg.md amendment 5)
PROPS_M = 1.396                           # by calibration on the conditioned quantity
PROPS_SPEC = "conditional: w = 0.75, m = 1.396"
PARTICIPATION_BOOKS = {"draftkings", "betmgm", "bovada",      # verified: void unless the player takes part
                       "fanduel", "onexbet"}                   # ASSIGNED, unverified (P1 could not separate them)
START_BOOKS = {"betrivers", "mybookieag",                      # verified: void unless the player starts
               # 2026-08-31 panel-drift additions, void rules from the books' OWN published rules:
               # fanatics -- "a player must start for player proposition bets to be considered
               #             action" (Fanatics Soccer Betting Guide / house rules)
               # rebet    -- "if a player was not in the starting lineup, the pick will be
               #             voided" (rebet.app/sports-prediction-rules)
               "fanatics", "rebet"}
# 2026-27 books with NO established void rule -- EXCLUDED at consensus build, never
# assumed: ballybet, betparx (no published soccer player-prop rule found),
# espnbet (rules page unreachable), williamhill_us (Caesars soccer section
# truncated; a basketball-section quote is not a soccer rule). Re-admit any of
# them only with a quoted published rule.
EXCLUDED_BOOKS_NO_VOID_RULE = {"ballybet", "betparx", "espnbet", "williamhill_us"}
SUB_FLOOR = 0.30                                               # assembly: p_play_any = p_start + (1 - p_start) * 0.30
EPS = 1e-6


class PropsHook:
    """Installed on assembly.PROPS_HOOK by the arm builder; called inside
    _finish_equation on the per-fixture frame AFTER the D1 goals term and
    BEFORE the bonus model, so the blended rate reaches every downstream term.
    Set `.cutoff` before each assembly call; only rows with gw == cutoff move."""

    def __init__(self, season):
        self.season = season
        pb = pd.read_parquet(REPO / "data" / "odds_props" / f"props_consensus_book_{season}.parquet")
        man = pd.read_csv(REPO / "data" / "odds_props" / "raw" / "scale" / season / "manifest.csv")
        man = man[man["event_id"].notna() & (man["books"].astype(str) != "CALL_FAILED")]
        ev = man[["gw", "fixture", "event_id"]].drop_duplicates()
        ev["fixture"] = ev["fixture"].astype(int); ev["gw"] = ev["gw"].astype(int)
        x = pb.merge(ev, on=["gw", "event_id"], how="inner")
        assert len(x) == len(pb), f"{season}: {len(pb) - len(x)} per-book rows have no vaastav fixture id"
        unknown = set(x["book"]) - PARTICIPATION_BOOKS - START_BOOKS
        assert not unknown, f"books without a conditioning rule: {sorted(unknown)}"
        self.pb = x[["gw", "fixture", "element", "book", "p_adj"]].copy()
        self.pb["element"] = self.pb["element"].astype(int)
        self.cutoff = None
        self.n_override = 0            # player-fixture rows whose e_goals moved
        self.n_partial_excluded = 0    # (gw, element) doubles priced in one fixture only -> model kept
        self.n_gk_skipped = 0
        self.by_gw = {}

    def __call__(self, a):
        assert self.cutoff is not None, "PropsHook.cutoff must be set before assembly"
        step0 = (a["gw"] == self.cutoff).to_numpy()
        if not step0.any():
            return a
        sub = a.loc[step0, ["element", "gw", "fixture", "position", "p_start", "e_goals"]].copy()
        sub["element"] = sub["element"].astype(int); sub["fixture"] = sub["fixture"].astype(int)
        sub["p_play_any"] = sub["p_start"] + (1.0 - sub["p_start"]) * SUB_FLOOR
        x = sub.merge(self.pb, on=["gw", "fixture", "element"], how="inner")
        if len(x) == 0:
            return a
        P = np.where(x["book"].isin(START_BOOKS), x["p_start"], x["p_play_any"])
        x["p_cond"] = x["p_adj"] * P
        fx = x.groupby(["element", "gw", "fixture", "position"])["p_cond"].mean().reset_index()
        # amendment 3: a double priced in one fixture keeps the model on both
        n_fix = sub.groupby(["element", "gw"])["fixture"].nunique().rename("n_fix")
        n_pr = fx.groupby(["element", "gw"])["fixture"].nunique().rename("n_priced")
        chk = pd.concat([n_fix, n_pr], axis=1).dropna()
        partial = set(chk[chk["n_priced"] < chk["n_fix"]].index)
        if partial:
            keep = ~pd.MultiIndex.from_frame(fx[["element", "gw"]]).isin(partial)
            fx = fx[keep]
        self.n_partial_excluded += len(partial)
        gk = fx["position"] == "GK"
        self.n_gk_skipped += int(gk.sum()); fx = fx[~gk]
        fx = fx[fx["p_cond"].notna()]
        lam = -np.log(1.0 - np.clip(fx["p_cond"].to_numpy() / PROPS_M, 0.0, 1.0 - EPS))
        m = pd.Series(lam, index=pd.MultiIndex.from_frame(fx[["element", "gw", "fixture"]]))
        key = pd.MultiIndex.from_arrays([a["element"].astype(int), a["gw"].astype(int), a["fixture"].astype(int)])
        mapped = m.reindex(key).to_numpy()
        mask = ~np.isnan(mapped) & step0
        a = a.copy()
        a.loc[mask, "e_goals"] = PROPS_W * mapped[mask] + (1.0 - PROPS_W) * a.loc[mask, "e_goals"].to_numpy()
        self.n_override += int(mask.sum())
        self.by_gw[int(self.cutoff)] = dict(overridden=int(mask.sum()), partial_excluded=len(partial), gk_skipped=int(gk.sum()))
        return a
