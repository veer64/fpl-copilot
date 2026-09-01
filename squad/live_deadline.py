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
    from season_stack import load_stack
    h = load_stack(columns=["season", "GW", "fixture"])
    total = int(h[(h["season"] == season) & (h["GW"] == gw)]["fixture"].nunique())
    return priced, total


def preflight(season, gw, strict=False, config="baseline", horizon=1):
    """Input inventory BEFORE the build. Read-only. Returns finding strings;
    under strict every finding raises instead. horizon > 1 adds the checks a
    multi-step build needs (the horizon block at the end, plus the hmin refit
    and per-target props coverage here)."""
    findings = []
    tag = season.replace("-", "_")
    last_gw = min(int(gw) + int(horizon) - 1, 38)          # last target gameweek by the calendar
    target_gws = list(range(int(gw), last_gw + 1))

    if config == "combined":
        pb = REPO / "data" / "odds_props" / f"props_consensus_book_{season}.parquet"
        if not pb.exists():
            _finding(findings, strict, f"props per-book consensus missing: {pb.name} -- the props "
                                       f"hook cannot condition per book")
        else:
            for g in target_gws:
                priced, total = props_fixture_coverage(season, g)
                if total and priced / total < PROPS_MIN_FIXTURE_COVERAGE:
                    _finding(findings, strict,
                             f"props coverage {priced}/{total} fixtures at GW{g} is below the strict floor "
                             f"{PROPS_MIN_FIXTURE_COVERAGE:.0%} -- unpriced fixtures silently keep the model rate")
                else:
                    findings.append(f"note: props coverage {priced}/{total} fixtures at GW{g}")
        if horizon == 1:
            findings.append("note: horizon-minutes lever is structurally inert at horizon=1 "
                            "(acts at steps 1-5 only; a step-0 frame has none)")
        else:
            # the steps-1-5 substitution input: without it the lever is OFF in fact
            # while the frame is stamped horizon_minutes_active=True
            hp = REPO / "data" / "horizon" / f"hmin_{tag}_refit.parquet"
            if not hp.exists():
                _finding(findings, strict,
                         f"horizon-minutes refit file missing: {hp.name} -- steps 1-5 would silently "
                         f"keep the stale step-0 minutes copy (the lever OFF in fact, stamped ON)")
            elif not (pd.read_parquet(hp, columns=["cutoff"])["cutoff"].astype(int) == int(gw)).any():
                _finding(findings, strict,
                         f"hmin refit file has no rows for cutoff GW{gw} -- every steps-1-5 row would "
                         f"silently keep the stale step-0 copy")

    # the season stack: the skeleton, the minutes frame and prices all come from it.
    # load_stack = archive/extension PLUS the forward skeleton, exactly what the
    # build itself sees -- so gameweek-coverage checks here mirror reality.
    from season_stack import load_stack
    hk_all = load_stack(columns=["season", "GW", "kickoff_time", "fixture"])
    hs = hk_all[hk_all["season"] == season]
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

    # odds file: the fixture universe AND the market lambdas. Resolved the way
    # dixon_coles._load_matches resolves it: the frozen archive if it carries the
    # season, else the *_with_* extension (FPL-API fixture slice, prices null).
    odds_path = REPO / "data" / "history" / "odds_all_seasons.parquet"
    ext = REPO / "data" / "history" / f"odds_all_seasons_with_{tag}.parquet"
    if season not in set(pd.read_parquet(odds_path, columns=["season"])["season"].unique()) and ext.exists():
        odds_path = ext
    odds = pd.read_parquet(odds_path,
                           columns=["season", "Date", "B365H", "B365D", "B365A"])
    os_ = odds[odds["season"] == season].copy()
    if len(os_) == 0:
        _finding(findings, strict,
                 f"odds_all_seasons has NO rows for {season} -- there is no fixture universe; "
                 f"get_fixtures returns empty and the assembly fixture join fails")
    elif len(hs):
        hk = hs[hs["GW"] == gw]
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
        if len(win) and n_unpriced == len(win):
            # The fixture half of the universe exists but the PRICES do not: the
            # whole deadline gameweek would run pure-DC. Per-fixture gaps are the
            # designed, counted fallback; a fully unpriced gameweek is a live
            # quality regression vs every backtest (100% priced) and raises under
            # strict until live odds pulling (a separate job) lands.
            _finding(findings, strict,
                     f"odds PRICES missing for ALL {len(win)} GW{gw} fixtures -- the fixture "
                     f"universe is present but every lambda would be pure DC "
                     f"(lambda_source='dc'); live odds pulling is a separate pending job")
        elif n_unpriced:
            findings.append(  # graceful by design (pure-DC fallback, counted) -- never strict
                f"note: {n_unpriced} GW{gw} fixture(s) without B365 prices -> pure-DC lambdas "
                f"(lambda_source='dc'); correct behaviour, not an error")

    if horizon > 1:
        # THE HORIZON SKELETON. walk_forward and the arm pipeline both derive targets
        # from the (stack + forward skeleton) gameweeks, so a window not covered by
        # played rows OR forward rows silently SHORTENS the horizon -- no error, just
        # fewer steps. eval/build_forward_skeleton.py supplies the forward rows; this
        # finding fires when the skeleton is absent or stale for the window. (A
        # genuinely blank gameweek would also be flagged here.)
        have_gws = set(hs["GW"].astype(int)) if len(hs) else set()
        missing = [g for g in target_gws if g not in have_gws]
        if missing:
            _finding(findings, strict,
                     f"horizon-{horizon} build: no master or forward-skeleton rows for target "
                     f"gameweek(s) {missing} -- those steps would be SILENTLY DROPPED "
                     f"(the {horizon}-step frame quietly becomes {horizon - len(missing)}-step); "
                     f"build/refresh the skeleton: uv run python eval/build_forward_skeleton.py")
        elif len(os_):
            # odds fixture rows + prices across the FUTURE part of the horizon window
            # (the deadline gameweek itself is checked above)
            hk6 = hs[hs["GW"].astype(int).isin(target_gws[1:])]
            if len(hk6):
                w0 = pd.to_datetime(hk6["kickoff_time"]).min().date()
                w1 = pd.to_datetime(hk6["kickoff_time"]).max().date()
                os6 = os_.copy()
                os6["d"] = pd.to_datetime(os6["Date"], format="%d/%m/%Y", errors="coerce").dt.date
                fwin = os6[(os6["d"] >= w0) & (os6["d"] <= w1)]
                n_fx = int(hk6["fixture"].nunique())
                if len(fwin) < n_fx:
                    _finding(findings, strict,
                             f"odds rows in the steps-1+ window ({len(fwin)}) < master fixtures ({n_fx}) "
                             f"-- missing fixtures fall out of steps 1-{horizon - 1} entirely")
                n_unp6 = int(fwin[["B365H", "B365D", "B365A"]].isna().any(axis=1).sum())
                if len(fwin) and n_unp6 == len(fwin):
                    _finding(findings, strict,
                             f"odds PRICES missing for ALL {len(fwin)} fixtures in the steps-1+ window "
                             f"(GW{target_gws[1]}..GW{last_gw}) -- every steps-1-5 lambda would be pure DC; "
                             f"live odds pulling is a separate pending job")
                elif n_unp6:
                    findings.append(f"note: {n_unp6} steps-1+ fixture(s) without B365 prices -> pure-DC lambdas")

    if strict:
        # decision-time only (network): non-strict report mode stays offline
        _fixture_calendar_check(findings, strict, season, target_gws)
    return findings


def _pull_fixtures():
    """One fixtures/ pull (id, event, kickoff_time). Isolated so tests monkeypatch it."""
    import json as _json
    import urllib.request as _rq
    req = _rq.Request("https://fantasy.premierleague.com/api/fixtures/",
                      headers={"User-Agent": "Mozilla/5.0 (fpl-copilot live preflight)"})
    with _rq.urlopen(req, timeout=30) as r:
        return _json.loads(r.read().decode("utf-8"))


def _fixture_calendar_check(findings, strict, season, target_gws):
    """#14-class guard (strict, decision time): a fixture moving between frame
    build and deadline shifts match_date and silently drops its Dixon-Coles
    join. Re-pull fixtures/ and compare (fixture id, event, kickoff_time)
    against the calendar snapshot the forward skeleton was built from; any
    mismatch touching the target gameweeks raises."""
    import json as _json
    from season_stack import forward_path
    fp = forward_path()
    if fp is None:
        return
    prov_p = fp.with_suffix(".provenance.json")
    if not prov_p.exists():
        _finding(findings, strict, f"forward skeleton {fp.name} has no provenance sidecar -- "
                                   f"the calendar snapshot for the re-pull check is missing")
        return
    prov = _json.loads(prov_p.read_text(encoding="utf-8"))
    if prov.get("season") != season or not set(target_gws) & set(prov.get("gws_covered", [])):
        return
    try:
        fresh = _pull_fixtures()
    except Exception as e:  # noqa: BLE001 -- offline at decision time IS the finding
        _finding(findings, strict,
                 f"could not re-pull fixtures/ to verify the calendar at decision time ({e}) -- "
                 f"a fixture moved since the skeleton build would silently drop its DC join")
        return
    cal = prov["calendar"]
    tset = set(int(g) for g in target_gws)
    moved = []
    for f in fresh:
        old = cal.get(str(f["id"]))
        if old is None:
            if f.get("event") in tset:
                moved.append((int(f["id"]), "NEW fixture not in the snapshot", [f.get("event"), f.get("kickoff_time")]))
            continue
        if [f.get("event"), f.get("kickoff_time")] != old and (old[0] in tset or f.get("event") in tset):
            moved.append((int(f["id"]), old, [f.get("event"), f.get("kickoff_time")]))
    if moved:
        _finding(findings, strict,
                 f"fixture calendar MOVED since the skeleton was built: {moved[:4]}"
                 f"{' (+more)' if len(moved) > 4 else ''} -- rebuild the skeleton "
                 f"(eval/build_forward_skeleton.py) before this deadline; a moved kickoff shifts "
                 f"match_date and silently drops the Dixon-Coles join (the #14 class)")
    else:
        findings.append("note: fixture-calendar re-pull matches the skeleton snapshot on the target gameweeks")


def postflight(frame, season, gw, strict=False, horizon=1):
    """Detectors on the produced frame for the fallbacks preflight cannot see.
    The step-0 detectors run on the deadline gameweek's rows; horizon > 1 adds
    the truncation check (the failure preflight infers, this one OBSERVES)."""
    findings = []
    if horizon > 1:
        steps = sorted(int(s) for s in frame["horizon_step"].unique())
        want = list(range(0, min(int(horizon), 38 - int(gw) + 1)))
        if steps != want:
            _finding(findings, strict,
                     f"horizon-{horizon} frame carries steps {steps}, expected {want} -- the horizon "
                     f"was silently truncated (missing master/fixture rows for the dropped gameweeks)")
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


def build_deadline_frame(season, gw, strict=False, verbose=False, config="baseline", horizon=1):
    """ONE deadline frame via the SHARED implementations, at any horizon.
    baseline  -> walkforward_season.walk_forward (the canonical builder) with
                 cutoffs=[gw] -- the code that built every canonical file.
    combined  -> the arm builder's EXTRACTED per-cutoff pipeline
                 (walkforward_arms.cutoff_components / minutes_frames /
                 assemble_cutoff / stamp_arm_frame) -- the code that built the
                 arm record files, with the props hook through the existing
                 module gate and the steps-1-5 horizon-minutes substitution
                 through minutes_frames. No second implementation of either
                 path exists. Returns (frame, findings)."""
    assert config in ("baseline", "combined"), config
    horizon = int(horizon)
    findings = preflight(season, gw, strict=strict, config=config, horizon=horizon)
    if config == "baseline":
        frame = wfs.walk_forward(season, cutoffs=[int(gw)], horizon=horizon, verbose=verbose)
    else:
        import props_feature
        import walkforward_arms as arms_mod
        from season_stack import load_stack
        k = int(gw)
        df = load_stack()          # stack + forward skeleton (matches walk_forward's read)
        cw = wfs.crosswalk_for(season)
        tr = wfs.train_seasons_for(season)
        dc_enabled = season in wfs.DC_SEASONS
        v = df[df["season"] == season].copy()
        v["kick"] = pd.to_datetime(v["kickoff_time"])
        gw_start = v.groupby("GW")["kick"].min().sort_index()
        gw_end = v.groupby("GW")["kick"].max().sort_index()
        all_gws = sorted(gw_start.index.astype(int))
        targets = [g for g in all_gws if k <= g < k + horizon]
        hmin = None
        if horizon > 1:
            hp = REPO / "data" / "horizon" / f"hmin_{season.replace('-', '_')}_refit.parquet"
            hmin = pd.read_parquet(hp) if hp.exists() else None  # absence already reported/raised by preflight
        hook = props_feature.PropsHook(season)
        comp = arms_mod.cutoff_components(season, k, targets, tr, gw_start, gw_end, all_gws)
        mins, n_refit, n_stale = arms_mod.minutes_frames(comp["m_k"], k, targets, hmin)
        frame = arms_mod.assemble_cutoff(comp, df, cw, mins, k, targets, season, dc_enabled, hook)
        frame = arms_mod.stamp_arm_frame(frame, season, tr, "both", dc_enabled)
        if assembly.PROPS_HOOK is not None:      # the module-global gate must rest None
            raise LiveStrictError("assembly.PROPS_HOOK did not rest None after the build")
        if hook.n_override == 0:
            _finding(findings, strict, "props ON but ZERO player-fixtures overridden -- the hook "
                                       "silently produced a model-only frame")
        else:
            findings.append(f"note: props overrode {hook.n_override} player-fixtures; partial doubles "
                            f"excluded {hook.n_partial_excluded}; GK skipped {hook.n_gk_skipped}")
        if horizon > 1:
            if hmin is not None and n_refit == 0:
                _finding(findings, strict, "hmin refit file loaded but ZERO rows substituted at steps "
                                           "1-5 -- the lever silently produced an all-stale frame")
            findings.append(f"note: horizon minutes steps 1-5: {n_refit} refit rows substituted, "
                            f"{n_stale} stale-copy fallback rows")
    findings += postflight(frame, season, gw, strict=strict, horizon=horizon)
    return frame, findings


def compare_to_canonical(frame, season, gw, canonical_path=None, allow_only_live=frozenset(), step=0):
    """The parity assertion: identical rows, identical columns, max |delta|
    exactly 0.0 on every numeric column, for ONE horizon step (default 0 -- the
    historical behaviour; pass step=1..5 to check a horizon build's later steps
    against the canonical rows at cutoff==gw, horizon_step==step).
    `allow_only_live` names stamp columns the record file predates (never data
    columns). Returns (ok, report_lines)."""
    tag = season.replace("-", "_")
    path = Path(canonical_path) if canonical_path else REPO / "data" / f"walkforward_h6_{tag}.parquet"
    canon = pd.read_parquet(path)
    c = canon[(canon["cutoff"] == gw) & (canon["horizon_step"] == step)].sort_values("element").reset_index(drop=True)
    l = frame[frame["horizon_step"] == step].sort_values("element").reset_index(drop=True)
    lines = [f"GW{gw} step {step} (gw {gw + step}): live {len(l)} rows vs canonical {len(c)} rows ({path.name})"]
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
    ap.add_argument("--horizon", type=int, default=1, help="1 = step-0 frame; 6 = the full planning horizon")
    a = ap.parse_args()
    all_ok = True
    for gw in a.gw:
        frame, findings = build_deadline_frame(a.season, gw, strict=a.strict, verbose=False,
                                               config=a.config, horizon=a.horizon)
        n_steps = frame["horizon_step"].nunique()
        print(f"\n=== {a.season} GW{gw} [{a.config}, horizon={a.horizon}]: {len(frame)} rows, "
              f"{n_steps} step(s), built through the shared implementations")
        for fn in findings:
            print(f"  finding: {fn}")
        if a.parity:
            tag = a.season.replace("-", "_")
            canonical = (REPO / "data" / "arms_gap0" / f"walkforward_h6_{tag}_both.parquet"
                         if a.config == "combined" else None)
            allow = {"penalty_join_prior_season"} if a.config == "combined" else frozenset()
            for step in sorted(int(s) for s in frame["horizon_step"].unique()):
                ok, lines = compare_to_canonical(frame, a.season, gw, canonical_path=canonical,
                                                 allow_only_live=allow, step=step)
                for ln in lines:
                    print(ln)
                all_ok = all_ok and ok
    if a.parity:
        print(f"\nPARITY: {'PASS -- live path is bit-identical to the canonical harness' if all_ok else 'FAIL'}")
        sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
