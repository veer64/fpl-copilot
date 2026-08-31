# live_deadline.py
# The LIVE deadline path: one step-0 frame for (season, gw), produced by THE
# SAME code the backtest harness runs -- eval/walkforward_season.walk_forward
# called with cutoffs=[gw] and horizon=1. This module contains NO modelling
# logic and reimplements nothing below the seam.
#
# THE SEAM. "Assemble inputs" ends and "compute the frame" begins inside
# walk_forward's per-cutoff loop body, at these shared calls (quoted from
# eval/walkforward_season.py, all imported here through walk_forward itself):
#
#     rates, priors = rates_mod.get_rates(season, up_to_gw=k)
#     m_k = minutes_mod.get_minutes(up_to_gw=k, predict_gws=[k], per_fixture=True,
#                                   availability=AVAILABILITY, train_seasons=tr,
#                                   predict_season=season)
#     bps_model, bps_to_bonus, BPS_FEATURES, bonus_mean = \
#         bonus_mod.get_bonus_model(up_to_gw=k, train_until=tr[-1],
#                                   predict_season=season)
#     f_k = dc_mod.get_fixtures(predict_season=season, cutoff_date=cutoff_date,
#                               odds_available_until=odds_until)
#     dc_k = def_mod.get_dc_hits(season, k, targets)
#     a_k = assembly.collapse_to_gameweek(assembly.assemble_fixtures(
#         df, cw, m_k, rates, priors, f_k, dc_k, bps_model, bps_to_bonus,
#         BPS_FEATURES, bonus_mean, gws=targets, season=season,
#         dc_enabled=dc_enabled))
#
# Everything below that seam -- the five component getters and the master
# equation -- is shared bit-for-bit because the live path calls walk_forward
# itself; horizon=1 makes targets == [gw], which is exactly the step-0 slice
# (the minutes copy loop at len(targets) > 1 is a no-op, the bonus
# normalisation is per-gameweek, and every other input is target-independent;
# the parity test PROVES rather than assumes this).
#
# What this module adds, all READ-ONLY on inputs and modelling code:
#   - preflight(): input inventory checks before the expensive build;
#   - postflight(): detectors for every known SILENT fallback in the output;
#   - strict=True (LIVE ONLY; backtests keep current behaviour): every
#     detector raises LiveStrictError instead of reporting;
#   - compare_to_canonical(): the parity assertion against the canonical
#     walk-forward file -- same rows, same columns, max |delta| exactly 0.0.
#
# Usage:
#   uv run python squad/live_deadline.py --season 2025-26 --gw 5 20 33 --parity
#   uv run python squad/live_deadline.py --season 2025-26 --gw 20 --strict

import argparse
import inspect
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "squad"))
sys.path.insert(0, str(REPO / "eval"))

import walkforward_season as wfs          # noqa: E402  (the harness -- the shared path)
import attacking_rates as rates_mod       # noqa: E402
import defensive as def_mod               # noqa: E402
import minutes as minutes_mod             # noqa: E402
import assembly                           # noqa: E402

DC_RULE_FROM = "2025-26"      # the defensive-contribution rule exists from this season on
MIN_FRAME_ROWS = 300          # an empty/withered frame is the get_minutes silent-empty symptom
TOP_N = 30                    # decision partition for the crosswalk-coverage check

# COMBINED config (props ON + horizon minutes ON -- the production arm; baseline is the shadow).
# GATE PLUMBING, stated plainly: the props gate is a MODULE GLOBAL -- assembly.PROPS_HOOK is set
# to a props_feature.PropsHook and restored to None in a finally block, exactly as
# eval/walkforward_arms.py does. There is no constructor argument or config object; a crash
# between set and restore would leave the hook armed for the next caller in the same process.
# postflight verifies the global rests None. The horizon-minutes lever has NO module gate that
# any consumer reads (HORIZON_MINUTES_ACTIVE is a documentation constant): it is an input
# substitution at steps 1-5 performed by the arm builder, and at horizon=1 (targets == [gw])
# there are no steps 1-5, so it is STRUCTURALLY INERT for a step-0 frame -- nothing to set.
# Strict floor for props coverage: the pre-registered coverage gate's own line (props_prereg.md
# section 1: a partition covered below 80% cannot pass). Historical 2025-26 per-gameweek fixture
# coverage is 100% in every gameweek (min share 1.0), so any breach of 0.80 live is anomalous,
# while 0.80 still tolerates one unpriced fixture in the smallest (7-fixture) gameweeks.
PROPS_MIN_FIXTURE_COVERAGE = 0.80
ARM_STAMPS = ("arm", "props_active", "props_spec", "horizon_minutes_active", "horizon_levers")


class LiveStrictError(RuntimeError):
    """A silent fallback (or missing input) that strict mode refuses to run past."""


def _finding(findings, strict, msg):
    if strict:
        raise LiveStrictError(msg)
    findings.append(msg)


def _availability_meta():
    """(seasons -> max gw) across the model-visible availability files, read-only.
    Mirrors availability_features.load()'s glob exactly (non-recursive, measurement
    files excluded) without importing its cache."""
    d = REPO / "data"
    paths = [p for p in sorted(d.glob("availability_*.parquet")) if "measurement" not in p.stem]
    meta = {}
    for p in paths:
        a = pd.read_parquet(p, columns=["season", "gw"])
        for s, g in a.groupby("season")["gw"].max().items():
            meta[s] = max(int(g), meta.get(s, 0))
    return meta


def _minutes_ladder():
    """The hardcoded prior-season ladder in minutes.py (~line 90), parsed from
    source rather than duplicated here, so this check cannot drift from the code."""
    src = inspect.getsource(minutes_mod)
    m = re.search(r"order\s*=\s*\[([^\]]*)\]", src)
    if not m:
        return None
    return re.findall(r"\"(\d{4}-\d{2})\"", m.group(1)) or re.findall(r"'(\d{4}-\d{2})'", m.group(1))


def props_fixture_coverage(season, gw):
    """(priced fixtures, total fixtures) for the gameweek, from the props consensus
    fixture file and the vaastav master. Read-only."""
    fx = pd.read_parquet(REPO / "data" / "odds_props" / f"props_consensus_fixture_{season}.parquet",
                         columns=["gw", "event_id"])
    priced = int(fx.loc[fx["gw"] == gw, "event_id"].nunique())
    from season_stack import stack_path
    h = pd.read_parquet(stack_path(), columns=["season", "GW", "fixture"])
    total = int(h[(h["season"] == season) & (h["GW"] == gw)]["fixture"].nunique())
    return priced, total


def preflight(season, gw, strict=False, config="baseline"):
    """Input inventory BEFORE the build. Read-only. Returns finding strings;
    under strict every finding raises instead."""
    findings = []
    tag = season.replace("-", "_")

    if config == "combined":
        pb = REPO / "data" / "odds_props" / f"props_consensus_book_{season}.parquet"
        if not pb.exists():
            _finding(findings, strict, f"props per-book consensus missing: {pb.name} -- the props "
                                       f"hook cannot condition per book")
        else:
            priced, total = props_fixture_coverage(season, gw)
            if total and priced / total < PROPS_MIN_FIXTURE_COVERAGE:
                _finding(findings, strict,
                         f"props coverage {priced}/{total} fixtures at GW{gw} is below the strict floor "
                         f"{PROPS_MIN_FIXTURE_COVERAGE:.0%} -- unpriced fixtures silently keep the model rate")
            else:
                findings.append(f"note: props coverage {priced}/{total} fixtures at GW{gw}")
        findings.append("note: horizon-minutes lever is structurally inert at horizon=1 "
                        "(acts at steps 1-5 only; a step-0 frame has none)")

    # the season stack: the skeleton, the minutes frame and prices all come from it
    # (season_stack.stack_path resolves the archive or the *_with_* extension)
    from season_stack import stack_path
    hist = stack_path()
    h = pd.read_parquet(hist, columns=["season", "GW"])
    hs = h[h["season"] == season]
    if len(hs) == 0:
        _finding(findings, strict, f"vaastav master has NO rows for {season} ({hist.name})")
    elif gw not in set(hs["GW"].astype(int)):
        _finding(findings, strict, f"vaastav master has no GW{gw} rows for {season}")

    # crosswalk file (walk_forward would raise later; catch it before the expense)
    cwp = REPO / "data" / "history" / f"crosswalk_{tag}.csv"
    if not cwp.exists():
        _finding(findings, strict, f"crosswalk missing: {cwp.name}")

    # rate blend: the season must be mapped and BOTH per-match Understat files exist
    if rates_mod.RATE_BLEND_ACTIVE:
        prior = rates_mod.BLEND_PRIOR.get(season)
        if prior is None:
            _finding(findings, strict, f"attacking_rates.BLEND_PRIOR has no entry for {season}")
        else:
            for s, role in ((prior, "prior"), (season, "current")):
                p = REPO / "data" / "history" / f"understat_matches_{s.replace('-', '_')}.parquet"
                if not p.exists():
                    _finding(findings, strict, f"Understat per-match file missing ({role} season): {p.name}")

    # penalty join: prior-year Understat aggregates (silent position/0.05 fallback without them)
    aggp = REPO / "data" / "history" / "understat_season_aggregates.parquet"
    agg = pd.read_parquet(aggp, columns=["understat_season"])
    prior_year = str(int(season[:4]) - 1)
    if not (agg["understat_season"].astype(str) == prior_year).any():
        _finding(findings, strict,
                 f"Understat season aggregates have no rows for {prior_year} -- penalty_share "
                 f"would silently fall back to position means / 0.05")

    # availability: the glob availability_features.load() sees (data/live/ is INVISIBLE to it)
    meta = _availability_meta()
    if season not in meta:
        _finding(findings, strict,
                 f"no data/availability_*.parquet covers {season} -- the whole availability "
                 f"block would silently fill UNKNOWN(-1)/0/NaN (data/live/ files are not seen)")
    elif meta[season] < gw:
        _finding(findings, strict,
                 f"availability for {season} ends at GW{meta[season]} < GW{gw} -- rows at the "
                 f"deadline gameweek would silently fill UNKNOWN")

    # minutes.py hardcoded prior-season ladder (silent all-cold-start if absent)
    ladder = _minutes_ladder()
    if ladder is None:
        _finding(findings, strict, "could not locate minutes.py's `order = [...]` ladder to check it")
    elif season not in ladder:
        _finding(findings, strict,
                 f"{season} is absent from minutes.py's hardcoded season ladder {ladder} -- every "
                 f"player would silently get prev_* = 0 and transfer_status = 2 (league-wide cold start)")

    # DC rule sets (silent zeroing of a live scoring rule if absent)
    if season >= DC_RULE_FROM:
        if season not in wfs.DC_SEASONS:
            _finding(findings, strict,
                     f"{season} is absent from walkforward_season.DC_SEASONS -- the defensive-"
                     f"contribution term (a rule IN FORCE from {DC_RULE_FROM}) would be silently zeroed")
        if season not in def_mod.DC_RULE_SEASONS:
            _finding(findings, strict,
                     f"{season} is absent from defensive.DC_RULE_SEASONS -- get_dc_hits would return empty")

    # odds file: the fixture universe AND the market lambdas
    odds = pd.read_parquet(REPO / "data" / "history" / "odds_all_seasons.parquet",
                           columns=["season", "Date", "B365H", "B365D", "B365A"])
    os_ = odds[odds["season"] == season].copy()
    if len(os_) == 0:
        _finding(findings, strict,
                 f"odds_all_seasons has NO rows for {season} -- there is no fixture universe; "
                 f"get_fixtures returns empty and the assembly fixture join fails")
    elif len(hs):
        hk = pd.read_parquet(hist, columns=["season", "GW", "kickoff_time", "fixture"])
        hk = hk[(hk["season"] == season) & (hk["GW"] == gw)]
        n_fixtures = hk["fixture"].nunique()
        k0 = pd.to_datetime(hk["kickoff_time"]).min().date()
        k1 = pd.to_datetime(hk["kickoff_time"]).max().date()
        os_["d"] = pd.to_datetime(os_["Date"], format="%d/%m/%Y", errors="coerce").dt.date
        win = os_[(os_["d"] >= k0) & (os_["d"] <= k1)]
        if len(win) < n_fixtures:
            _finding(findings, strict,
                     f"odds rows in the GW{gw} kickoff window ({len(win)}) < vaastav fixtures "
                     f"({n_fixtures}) -- missing fixtures fall out of the frame entirely")
        n_unpriced = int(win[["B365H", "B365D", "B365A"]].isna().any(axis=1).sum())
        if n_unpriced:
            findings.append(  # graceful by design (pure-DC fallback, counted) -- never strict
                f"note: {n_unpriced} GW{gw} fixture(s) without B365 prices -> pure-DC lambdas "
                f"(lambda_source='dc'); correct behaviour, not an error")
    return findings


def postflight(frame, season, gw, strict=False):
    """Detectors on the produced frame for the fallbacks preflight cannot see."""
    findings = []
    f = frame[frame["gw"] == gw]

    if len(f) < MIN_FRAME_ROWS:
        _finding(findings, strict,
                 f"frame has {len(f)} rows at GW{gw} (< {MIN_FRAME_ROWS}) -- the get_minutes "
                 f"silent-empty symptom (minutes.py returns an empty frame rather than raising)")
        return findings

    # fixture-join completeness at the deadline gameweek (assembly's own guards
    # allow up to 10% global / 50% per-team leakage; live demands 100%)
    n_null = int(f["team_lambda"].isna().sum())
    if n_null:
        _finding(findings, strict,
                 f"{n_null} GW{gw} rows have no fixture join (team_lambda null) -- below the "
                 f"live bar of 100% even if above assembly's 90%/50% guards")

    # crosswalk coverage where decisions are made (the Cherki class, ~+1.3 e_points/row)
    top = f.nlargest(TOP_N, "e_points")
    miss_top = top[top["understat_id"].isna() | (top["understat_id"].astype(str) == "") |
                   (top["understat_id"].astype(str) == "nan")]
    if len(miss_top):
        _finding(findings, strict,
                 f"{len(miss_top)} of the top {TOP_N} by e_points have no understat_id "
                 f"(silent positional-prior rates): {sorted(miss_top['name'])}")
    n_missing_all = int(f["understat_id"].isna().sum())
    if n_missing_all:
        findings.append(f"note: {n_missing_all} of {len(f)} rows have no understat_id -> "
                        f"positional-prior rates (silent; GKs receive the DEF prior)")

    # team_pen_rate fallback (exact detection: teams absent from the season's
    # vaastav penalty aggregate received the hard-coded 0.08)
    from season_stack import stack_path
    hist = pd.read_parquet(stack_path(),
                           columns=["season", "team", "penalties_missed"])
    have = set(hist.loc[hist["season"] == season].groupby("team").size().index)
    fb_teams = sorted(set(f["team"]) - have)
    if fb_teams:
        _finding(findings, strict,
                 f"team_pen_rate fell back to the 0.08 default for team(s) {fb_teams} "
                 f"(absent from the season's vaastav penalty aggregate)")

    # DC-hit base-rate fallback (graceful cold-start inside an enabled season; report only)
    if season in wfs.DC_SEASONS:
        base = f["position"].map(assembly.DC_BASE)
        n_base = int(np.isclose(f["p_dc_hit"], base).sum())
        if n_base > 0.9 * len(f):
            findings.append(f"note: p_dc_hit sits at the DC_BASE position rates on {n_base}/{len(f)} "
                            f"rows -- the defensive model's cold-start prior, correct early-season behaviour")

    # penalty_share conservative fill (gate-off path fills 0.05; report only)
    n_ps = int((f["penalty_share"] == 0.05).sum())
    if n_ps:
        findings.append(f"note: penalty_share == 0.05 (the conservative fill) on {n_ps}/{len(f)} rows")
    return findings


def build_deadline_frame(season, gw, strict=False, verbose=False, config="baseline"):
    """ONE step-0 frame via the SHARED harness. config='combined' arms the props
    hook through the EXISTING module gate (assembly.PROPS_HOOK) with a finally
    restore; no branch below the seam. Returns (frame, findings)."""
    assert config in ("baseline", "combined"), config
    findings = preflight(season, gw, strict=strict, config=config)
    hook = None
    if config == "combined":
        import props_feature
        hook = props_feature.PropsHook(season)
        hook.cutoff = int(gw)
        assembly.PROPS_HOOK = hook
    try:
        frame = wfs.walk_forward(season, cutoffs=[int(gw)], horizon=1, verbose=verbose)
    finally:
        assembly.PROPS_HOOK = None
    if config == "combined":
        if assembly.PROPS_HOOK is not None:      # the module-global gate must rest None
            raise LiveStrictError("assembly.PROPS_HOOK did not rest None after the build")
        if hook.n_override == 0:
            _finding(findings, strict, "props ON but ZERO player-fixtures overridden -- the hook "
                                       "silently produced a model-only frame")
        else:
            findings.append(f"note: props overrode {hook.n_override} player-fixtures; partial doubles "
                            f"excluded {hook.n_partial_excluded}; GK skipped {hook.n_gk_skipped}")
        # stamp the frame the way the arm builder stamps its record files
        import props_feature
        frame["arm"] = "both"
        frame["props_active"] = True
        frame["props_spec"] = props_feature.PROPS_SPEC
        frame["horizon_minutes_active"] = True
        frame["horizon_levers"] = "refit"
    findings += postflight(frame, season, gw, strict=strict)
    return frame, findings


def compare_to_canonical(frame, season, gw, canonical_path=None, allow_only_live=frozenset()):
    """The parity assertion: identical rows, identical columns, max |delta|
    exactly 0.0 on every numeric column. `allow_only_live` names stamp columns
    the record file predates (never data columns). Returns (ok, report_lines)."""
    tag = season.replace("-", "_")
    path = Path(canonical_path) if canonical_path else REPO / "data" / f"walkforward_h6_{tag}.parquet"
    canon = pd.read_parquet(path)
    c = canon[(canon["cutoff"] == gw) & (canon["horizon_step"] == 0)].sort_values("element").reset_index(drop=True)
    l = frame[frame["gw"] == gw].sort_values("element").reset_index(drop=True)
    lines = [f"GW{gw}: live {len(l)} rows vs canonical {len(c)} rows ({path.name})"]
    ok = True
    only_live = set(l.columns) - set(c.columns) - set(allow_only_live)
    only_canon = set(c.columns) - set(l.columns)
    tolerated = (set(l.columns) - set(c.columns)) & set(allow_only_live)
    if tolerated:
        lines.append(f"  tolerated only-live stamp column(s) the record file predates: {sorted(tolerated)}")
    if only_live or only_canon:
        ok = False
        lines.append(f"  COLUMN SET DIFFERS: only-live {sorted(only_live)}, "
                     f"only-canonical {sorted(only_canon)}")
    common = [col for col in c.columns if col in set(l.columns)]
    if len(l) != len(c) or not (l["element"].values == c["element"].values).all():
        ok = False
        lines.append(f"  ROW SET DIFFERS: only-live {sorted(set(l['element']) - set(c['element']))[:10]}, "
                     f"only-canonical {sorted(set(c['element']) - set(l['element']))[:10]}")
        keep = sorted(set(l["element"]) & set(c["element"]))
        l = l[l["element"].isin(keep)].reset_index(drop=True)
        c = c[c["element"].isin(keep)].reset_index(drop=True)
    n_num = n_obj = 0
    for col in common:
        a, b = l[col], c[col]
        if pd.api.types.is_numeric_dtype(b) and not pd.api.types.is_bool_dtype(b):
            av, bv = a.astype(float).values, b.astype(float).values
            both_nan = np.isnan(av) & np.isnan(bv)
            delta = np.abs(np.where(both_nan, 0.0, av - bv))
            mx = float(np.nanmax(delta)) if len(delta) else 0.0
            nan_mismatch = int((np.isnan(av) != np.isnan(bv)).sum())
            if mx != 0.0 or nan_mismatch:
                ok = False
                lines.append(f"  DIFFERS {col}: max |delta| {mx:.3e}, nan mismatches {nan_mismatch}, "
                             f"n differing {int((delta > 0).sum() + nan_mismatch)}")
            n_num += 1
        else:
            eq = (a.astype(str).fillna("<na>") == b.astype(str).fillna("<na>"))
            if not eq.all():
                ok = False
                lines.append(f"  DIFFERS {col}: {int((~eq).sum())} rows (non-numeric)")
            n_obj += 1
    lines.append(f"  {'BIT-IDENTICAL' if ok else 'NOT identical'}: {n_num} numeric + {n_obj} "
                 f"non-numeric columns compared, max |delta| exactly 0.0 required")
    return ok, lines


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", required=True)
    ap.add_argument("--gw", type=int, nargs="+", required=True)
    ap.add_argument("--strict", action="store_true", help="LIVE ONLY: every silent fallback raises")
    ap.add_argument("--parity", action="store_true", help="assert bit-identity vs the canonical frame")
    ap.add_argument("--config", choices=["baseline", "combined"], default="baseline")
    a = ap.parse_args()
    all_ok = True
    for gw in a.gw:
        frame, findings = build_deadline_frame(a.season, gw, strict=a.strict, verbose=False, config=a.config)
        print(f"\n=== {a.season} GW{gw} [{a.config}]: {len(frame)} step-0 rows built through the shared harness")
        for fn in findings:
            print(f"  finding: {fn}")
        if a.parity:
            tag = a.season.replace("-", "_")
            if a.config == "combined":
                canonical = REPO / "data" / "arms_gap0" / f"walkforward_h6_{tag}_both.parquet"
                ok, lines = compare_to_canonical(frame, a.season, gw, canonical_path=canonical,
                                                 allow_only_live={"penalty_join_prior_season"})
            else:
                ok, lines = compare_to_canonical(frame, a.season, gw)
            for ln in lines:
                print(ln)
            all_ok = all_ok and ok
    if a.parity:
        print(f"\nPARITY: {'PASS -- live path is bit-identical to the canonical harness' if all_ok else 'FAIL'}")
        sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
