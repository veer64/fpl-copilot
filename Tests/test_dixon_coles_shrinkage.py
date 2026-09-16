"""
Shrinkage on Dixon-Coles team strengths (Logs/dc_shrinkage_prereg_2026-09-13.md):
change A, a Gaussian prior at 0 on attack/defence with strength k = 4 league-average
pseudo-matches, releasing as n_eff / (n_eff + k); change B, the archive-canonical club
name inside the fit and the name guard. (The strict EXTREME-strength detector and its
tests live on branch shrink-detector-strict until a remedy exists: on main it would
fail every live build on the two runaway clubs.)

OUTCOME 2026-09-14: k = 4 was FALSIFIED on its endpoint (Logs/dc_shrinkage_log_2026-09-13.md
section 3); the module default is SHRINK_K = 0 (prior OFF, objective bit-identical to before).
These tests pin the MECHANISM under an explicit tau (monkeypatched), so the next
pre-registration is one constant away, and the guard, alias and detector regardless.

Run:
    uv run pytest Tests/test_dixon_coles_shrinkage.py -v
"""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

REPO = Path(__file__).resolve().parents[1]
for p in (str(REPO), str(REPO / "squad"), str(REPO / "eval")):
    if p not in sys.path:
        sys.path.insert(0, p)

import dixon_coles as dc                                   # noqa: E402

REF = pd.Timestamp("2026-09-18 19:00:00")


def _m(day, home, away, hg, ag, season="2026-27"):
    return dict(date_parsed=pd.Timestamp("2026-08-01") + pd.Timedelta(days=int(day)), home=home, away=away,
                home_goals=hg, away_goals=ag, season=season)


def _league(rng, n_rounds=12, teams=("A", "B", "C", "D", "E", "F")):
    """A small league with ordinary scoring, no club one-sided."""
    rows, day = [], 0
    for r in range(n_rounds):
        for i, h in enumerate(teams):
            for j, a in enumerate(teams):
                if i < j and (i + j + r) % 3 == 0:
                    rows.append(_m(day, h, a, int(rng.poisson(1.5)), int(rng.poisson(1.1))))
                    day += 1
    return rows


# ------------------------------------------------------------ change A: the prior
def test_scoreless_newcomer_is_bounded_not_minus_infinity(monkeypatch):
    monkeypatch.setattr(dc, "SHRINK_K", 4); monkeypatch.setattr(dc, "SHRINK_TAU", 5.6)
    rng = np.random.default_rng(1)
    rows = _league(rng)
    # a newcomer N with three matches, no goals scored, no history
    rows += [_m(40, "N", "A", 0, 2), _m(41, "B", "N", 1, 0), _m(42, "N", "C", 0, 1)]
    teams = sorted({r["home"] for r in rows} | {r["away"] for r in rows})
    p, idx, nt = dc._fit_dc_decay(pd.DataFrame(rows), teams, REF, 365)
    a_n = p[idx["N"]]
    assert -1.2 < a_n < -0.15, f"newcomer attack {a_n:.3f}: expected a bounded pull toward league average"
    assert dc.LAST_FIT["converged"] is True
    assert dc.LAST_FIT["shrink_k"] == 4 and abs(dc.LAST_FIT["shrink_tau"] - 5.6) < 1e-9
    assert dc.LAST_FIT["n_eff_min_club"] == "N" and dc.LAST_FIT["n_eff_min"] < 3.5


def test_without_the_prior_the_same_newcomer_runs_off(monkeypatch):
    rng = np.random.default_rng(1)
    rows = _league(rng) + [_m(40, "N", "A", 0, 2), _m(41, "B", "N", 1, 0), _m(42, "N", "C", 0, 1)]
    teams = sorted({r["home"] for r in rows} | {r["away"] for r in rows})
    monkeypatch.setattr(dc, "SHRINK_TAU", 0.0)
    p, idx, nt = dc._fit_dc_decay(pd.DataFrame(rows), teams, REF, 365)
    assert p[idx["N"]] < -3.0          # the defect the prior removes: the MLE is at -inf, the optimiser stops far out


def test_established_clubs_barely_move_and_the_prior_releases(monkeypatch):
    rng = np.random.default_rng(2)
    rows = _league(rng, n_rounds=40)   # ~ 100+ matches per club
    teams = sorted({r["home"] for r in rows} | {r["away"] for r in rows})
    monkeypatch.setattr(dc, "SHRINK_K", 4); monkeypatch.setattr(dc, "SHRINK_TAU", 5.6)
    p_prior, idx, nt = dc._fit_dc_decay(pd.DataFrame(rows), teams, REF, 365)
    n_eff_min = dc.LAST_FIT["n_eff_min"]
    monkeypatch.setattr(dc, "SHRINK_TAU", 0.0)
    p_mle, _, _ = dc._fit_dc_decay(pd.DataFrame(rows), teams, REF, 365)
    d = np.abs(p_prior[:2 * nt] - p_mle[:2 * nt]).max()
    assert n_eff_min > 20
    assert d < 0.08, f"established clubs moved by {d:.3f} under the prior (n_eff_min {n_eff_min:.1f})"
    # release: the shrunk estimate keeps most of the MLE, in the direction of the MLE
    mle, sh = p_mle[:nt], p_prior[:nt]
    big = np.abs(mle) > 0.2
    if big.any():
        ratio = (sh[big] / mle[big])
        assert (ratio > 0.75).all() and (ratio < 1.05).all()


# ------------------------------------------------------- change B: names and the guard
def test_canonical_names_and_the_guard():
    assert dc.canon_club("Hull City") == "Hull" and dc.canon_club("Ipswich Town") == "Ipswich"
    assert dc.canon_club("Arsenal") == "Arsenal"
    hist = [dict(season="2024-25", home="Ipswich", away="Arsenal"), dict(season="2016-17", home="Hull", away="Everton")]
    cur = [dict(season="2026-27", home="Hull", away="Arsenal"), dict(season="2026-27", home="Ipswich", away="Coventry City")]
    mc = pd.DataFrame(hist + cur)
    # Coventry City is declared new for 2026-27; Hull / Ipswich have history under their canonical names
    assert dc.check_new_clubs(mc, "2026-27") == {"Coventry City"}
    # an undeclared club with no history refuses (the unmapped-alias case)
    bad = pd.concat([mc, pd.DataFrame([dict(season="2026-27", home="Nowhere Town", away="Arsenal")])])
    with pytest.raises(ValueError) as ei:
        dc.check_new_clubs(bad, "2026-27")
    assert "Nowhere Town" in str(ei.value) and "unmapped alias" in str(ei.value)
    # a stale declaration (declared new, but history exists) refuses too
    stale = mc.copy()
    stale.loc[stale["home"] == "Coventry City", "home"] = "Arsenal"
    stale = pd.concat([stale, pd.DataFrame([dict(season="2020-21", home="Coventry City", away="Everton"),
                                            dict(season="2026-27", home="Coventry City", away="Everton")])])
    with pytest.raises(ValueError) as ei:
        dc.check_new_clubs(stale, "2026-27")
    assert "declared new but they DO have history" in str(ei.value)


def test_declared_new_clubs_match_the_archive_exactly():
    """NEW_TO_ARCHIVE must be exactly the set of clubs with zero prior-season rows under
    canonical names, for every season the loader can serve on this machine."""
    for ps in ("2023-24", "2024-25", "2025-26", "2026-27"):
        try:
            m = dc._load_matches(ps)
        except FileNotFoundError:
            continue
        mc = m.assign(home=m["home"].map(dc.canon_club), away=m["away"].map(dc.canon_club))
        assert dc.check_new_clubs(mc, ps) == set(dc.NEW_TO_ARCHIVE.get(ps, set())), ps


def test_fixture_output_keeps_live_names(monkeypatch):
    """The alias lives inside the fit; the fixtures returned carry the live names the
    FPL-named frame joins on (assembly.TEAM_MAP unchanged). Under the prior (explicit tau)
    every live lambda is inside the detector bounds and the fit converges; under the module
    default (prior OFF) the runaway defect is still there, which the record-bounds assertion
    below would show -- KNOWN_ISSUES #25 stays open."""
    monkeypatch.setattr(dc, "SHRINK_K", 4); monkeypatch.setattr(dc, "SHRINK_TAU", 5.6)
    try:
        out = dc.get_fixtures(predict_season="2026-27", cutoff_date="2026-09-18 19:00:00",
                              odds_available_until="2026-09-20 15:30:00")
    except FileNotFoundError:
        pytest.skip("2026-27 odds extension not on this machine")
    names = set(out["home"]) | set(out["away"])
    assert {"Hull City", "Ipswich Town", "Coventry City"} <= names and "Hull" not in names and "Ipswich" not in names
    assert dc.LAST_FIT["converged"] is True
    lam = pd.concat([out["lam_home"], out["lam_away"]])
    assert lam.min() > 0.15 and lam.max() < 6.0, f"live fixtures outside the strength bounds: {lam.min():.4f}..{lam.max():.4f}"


# ------------------------------------------------ the LOUD extreme-strength detector
import live_deadline as ld                                 # noqa: E402


def _frame(lams_by_step):
    rows = []
    for step, lams in lams_by_step.items():
        for i, lam in enumerate(lams):
            rows.append(dict(horizon_step=step, gw=4 + step, team=f"T{i}", element=100 * step + i,
                             team_lambda=lam, opp_lambda=1.0, e_points=1.0, understat_id=1.0, position="MID",
                             p_dc_hit=0.1, penalty_share=0.0))
    return pd.DataFrame(rows)


def test_extreme_strength_is_a_loud_finding_that_is_appended_never_raised():
    """User decision 2026-09-16: served, not refused -- visible through /health and the push."""
    good = list(np.linspace(0.45, 3.5, 20))
    f = _frame({0: good, 1: good[:-1] + [0.0006]})
    hits = ld.degraded_findings(f, last_fit={})
    assert len(hits) == 1 and hits[0].startswith(ld.MODEL_DEGRADED)
    assert "EXTREME at horizon step 1" in hits[0] and "T19 lambda=0.0006" in hits[0] and "served, not refused" in hits[0]
    assert any("T19 lambda=6.5000" in x for x in ld.degraded_findings(_frame({0: good, 1: good[:-1] + [6.5]}), last_fit={}))
    assert ld.degraded_findings(_frame({0: good, 1: good[:-1] + [0.2]}), last_fit={}) == []
    # source level: postflight EXTENDS with these findings and never routes them through _finding
    import inspect
    src = inspect.getsource(ld.postflight)
    assert "findings.extend(degraded_findings(frame))" in src
    import re
    dsrc = inspect.getsource(ld.degraded_findings)
    assert "_finding(" not in dsrc and re.search(r"^\s*raise", dsrc, re.M) is None


def test_a_non_converged_fit_is_a_loud_finding_too():
    good = list(np.linspace(0.45, 3.5, 20))
    hits = ld.degraded_findings(_frame({0: good, 1: good}),
                                last_fit={"converged": False, "iterations": 189, "max_abs_attack": 7.39, "max_abs_defence": 0.88})
    assert len(hits) == 1 and hits[0].startswith(ld.MODEL_DEGRADED) and "did NOT converge" in hits[0] and "7.39" in hits[0]
    assert ld.degraded_findings(_frame({0: good, 1: good}), last_fit={"converged": True}) == []


# ------------------------------------------------------------ the record


def test_record_strengths_inside_the_bounds_once_rebuilt_with_the_prior():
    """The three canonicals, IF ever built with a prior (stamp dc_shrink_k), carry no team
    lambda outside [0.15, 6.0] at any step of any cutoff. Skips on the current record (no
    stamp: k = 4 was falsified and the prior is off)."""
    checked = 0
    for tag in ("2023_24", "2024_25", "2025_26"):
        p = REPO / "data" / f"walkforward_h6_{tag}.parquet"
        if not p.exists():
            continue
        import pyarrow.parquet as pq
        if "dc_shrink_k" not in pq.read_schema(p).names:
            continue
        cols = pd.read_parquet(p, columns=["cutoff", "gw", "team", "team_lambda", "dc_shrink_k"])
        assert int(cols["dc_shrink_k"].iloc[0]) > 0
        lam = cols.groupby(["cutoff", "gw", "team"])["team_lambda"].first().dropna()
        assert lam.min() >= 0.15 and lam.max() <= 6.0, f"{p.name}: strengths {lam.min():.4f}..{lam.max():.4f}"
        checked += 1
    if checked == 0:
        pytest.skip("no canonical carries the dc_shrink_k stamp yet (pre-rebuild)")
