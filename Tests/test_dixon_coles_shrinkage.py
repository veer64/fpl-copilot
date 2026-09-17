"""
Regularisation of Dixon-Coles team strengths, and the archive-canonical club name inside the
fit (prereg change B: canon_club, ARCHIVE_NAME_ALIAS, NEW_TO_ARCHIVE, check_new_clubs).

The k = 4 global prior of 2026-09-14 was FALSIFIED; the v2 form (2026-09-17, approved) is a per-club
hinge prior (tau0 5.6, N 10) plus a plausibility box (+-ln 4) applied only when the unbounded fit
leaves it -- both on CENTRED parameters (Logs/dc_shrinkage_v2_log_2026-09-17.md section 1). These
tests pin the prereg's table, the structural bit-identity, the hinge's scope, the box's scope, and
the loud detector (MODEL DEGRADED v MODEL NOTE).

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


# ------------------------------------------ the v2 form: hinge prior + plausibility box
def _newcomer_rows(n_scoreless, rng_seed=1):
    rng = np.random.default_rng(rng_seed)
    rows = _league(rng)
    opps = ["A", "B", "C", "D", "E", "F"]
    for i in range(n_scoreless):
        rows.append(_m(40 + i, "N", opps[i % 6], 0, 2) if i % 2 == 0 else _m(40 + i, opps[i % 6], "N", 1, 0))
    return rows


def _fit(rows, **kw):
    teams = sorted({r["home"] for r in rows} | {r["away"] for r in rows})
    p, idx, nt = dc._fit_dc_decay(pd.DataFrame(rows), teams, REF, 365, **kw)
    c_atk = p[:nt] - p[:nt].mean(); c_dfc = p[nt:2 * nt] - p[nt:2 * nt].mean()
    return p, idx, nt, c_atk, c_dfc


@pytest.mark.parametrize("n, lo, hi, at_box", [(3, -0.80, -0.35, False), (8, -1.3863, -1.3862, True), (12, -1.3863, -1.3862, True)])
def test_a_scoreless_newcomer_follows_the_prereg_table(n, lo, hi, at_box):
    """Zero goals in n matches, no history: the hinge pulls (n < N), then the box holds at
    exactly -ln 4 = -1.3863 of the league mean (n >= 8) -- the table in
    Logs/dc_shrinkage_threshold_prereg_2026-09-17.md section 1. At n = 3 the band is wide: the
    synthetic league's scoring rate and the newcomer's own defence shift the MAP a little."""
    p, idx, nt, c_atk, c_dfc = _fit(_newcomer_rows(n))
    a_n = c_atk[idx["N"]]
    assert lo <= a_n <= hi, f"n={n}: centred attack {a_n:.4f}"
    assert dc.LAST_FIT["converged"] is True, dc.LAST_FIT
    assert ("N" in dc.LAST_FIT["at_bound"]) is at_box
    assert dc.LAST_FIT["boxed_refit"] is at_box
    assert dc.LAST_FIT["method"] == ("SLSQP" if at_box else "L-BFGS-B")
    if n < dc.SHRINK_N:
        assert dc.LAST_FIT["clubs_below_n"]["N"]["tau"] > 0
    else:
        assert "N" not in dc.LAST_FIT["clubs_below_n"]
    # the gauge is the record's: sum(atk) == sum(dfc), L-BFGS-B from zeros never left it
    assert abs(p[:nt].sum() - p[nt:2 * nt].sum()) < 1e-3


def test_without_the_form_the_same_newcomer_runs_off(monkeypatch):
    monkeypatch.setattr(dc, "SHRINK_N", 0); monkeypatch.setattr(dc, "ATK_DFC_BOUND", None)
    p, idx, nt, c_atk, _ = _fit(_newcomer_rows(3))
    assert c_atk[idx["N"]] < -3.0 and dc.LAST_FIT["boxed_refit"] is False and dc.LAST_FIT["at_bound"] == {}


def test_a_cutoff_with_no_evidence_poor_club_is_bit_identical_to_the_plain_fit(monkeypatch):
    """The structural guarantee: no club below N and nothing outside the box -> the objective is
    the same function and the optimiser takes the same path, bit for bit."""
    rng = np.random.default_rng(2)
    rows = _league(rng, n_rounds=40)   # ~100+ matches per club, all inside the box
    p_form, _, nt, _, _ = _fit(rows)
    assert dc.LAST_FIT["clubs_below_n"] == {} and dc.LAST_FIT["at_bound"] == {} and dc.LAST_FIT["boxed_refit"] is False
    assert dc.LAST_FIT["min_margin_to_bound"] > 0.2
    monkeypatch.setattr(dc, "SHRINK_N", 0); monkeypatch.setattr(dc, "ATK_DFC_BOUND", None)
    p_plain, _, _, _, _ = _fit(rows)
    assert np.array_equal(p_form, p_plain)


def test_the_hinge_is_scoped_to_the_predict_seasons_clubs():
    """A club outside prior_teams (relegated seasons ago, its parameters unused) gets no hinge
    even below N, so the fit is bit-identical to the plain one -- the bit-identity promise
    would otherwise break at every cutoff (such a club sits at n_eff ~ 9.5)."""
    rng = np.random.default_rng(3)
    rows = _league(rng, n_rounds=40)
    for i in range(4):                      # an old club, four ordinary matches, well inside the box
        rows.append(_m(30 + i, "OLD", "ABCDEF"[i], 1, 1))
    p_scoped, _, nt, _, _ = _fit(rows, prior_teams=list("ABCDEF"))
    assert dc.LAST_FIT["clubs_below_n"] == {}
    dc.SHRINK_N, keep = 0, dc.SHRINK_N
    try:
        p_plain, _, _, _, _ = _fit(rows)
    finally:
        dc.SHRINK_N = keep
    assert np.array_equal(p_scoped, p_plain)
    p_all, _, _, _, _ = _fit(rows)          # prior_teams=None: the old club IS hinged
    assert "OLD" in dc.LAST_FIT["clubs_below_n"] and not np.array_equal(p_all, p_plain)


def test_a_phantom_club_with_no_rows_is_never_a_slack_variable():
    """A club in the team list with ZERO training rows (the archive's list spans later seasons)
    and outside prior_teams must stay at the starting point while another club is hinged: the
    league mean and the box are over the league's clubs only. Before this (first reference build)
    the optimiser moved such a phantom's defence to +26 to shift the mean, and the box then
    clamped the phantom at both bounds (Logs/dc_shrinkage_v2_log_2026-09-17.md section 1(d))."""
    rows = _newcomer_rows(3)
    teams = sorted({r["home"] for r in rows} | {r["away"] for r in rows}) + ["PHANTOM"]
    p, idx, nt = dc._fit_dc_decay(pd.DataFrame(rows), teams, REF, 365, prior_teams=[t for t in teams if t != "PHANTOM"])
    assert p[idx["PHANTOM"]] == 0.0 and p[nt + idx["PHANTOM"]] == 0.0
    assert dc.LAST_FIT["converged"] is True and dc.LAST_FIT["boxed_refit"] is False and dc.LAST_FIT["at_bound"] == {}
    assert dc.LAST_FIT["n_league"] == nt - 1 and "PHANTOM" not in dc.LAST_FIT["clubs_below_n"]
    # and the hinged newcomer's centred attack (over the league) is the table's pull, unchanged by the phantom
    league = [idx[t] for t in teams if t != "PHANTOM"]
    a_n = p[idx["N"]] - p[league].mean()
    assert -0.80 <= a_n <= -0.35, a_n


def test_the_box_binds_only_where_the_mle_runs_off():
    p, idx, nt, c_atk, c_dfc = _fit(_newcomer_rows(12))
    assert dc.LAST_FIT["at_bound"] == {"N": ["attack"]}
    others = [abs(c_atk[idx[t]]) for t in idx if t != "N"] + [abs(v) for v in c_dfc]
    assert max(others) < dc.ATK_DFC_BOUND - 0.2          # no other parameter near a bound
    assert dc.LAST_FIT["min_margin_to_bound"] > 0.2 and "N" not in dc.LAST_FIT["min_margin_club"]


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


def test_fixture_output_keeps_live_names():
    """The alias lives inside the fit; the fixtures returned carry the live names the
    FPL-named frame joins on (assembly.TEAM_MAP unchanged). Under the v2 form every live lambda
    is inside the detector bounds and the fit converges."""
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


def test_clamped_and_hinged_clubs_are_model_notes_not_degraded():
    """The box working is a MODEL NOTE (visible, never degrading); the EXTREME check keeps its
    bounds for a clamped club too -- settled 2026-09-17 before the fatal raise ships."""
    import live_deadline as ld
    frame = pd.DataFrame({"horizon_step": [1, 1, 1], "team": ["Coventry City", "Hull", "Arsenal"],
                          "team_lambda": [0.41, 1.10, 2.10]})
    lf = {"converged": True, "shrink_n": 10, "clubs_below_n": {"Hull": {"n_eff": 4.0, "tau": 3.36}},
          "at_bound": {"Coventry City": ["attack"]}}
    out = ld.degraded_findings(frame, last_fit=lf)
    assert len(out) == 2 and all(o.startswith(ld.MODEL_NOTE) for o in out)
    assert "hinge prior active" in out[0] and "Hull (n_eff 4.0, tau 3.36)" in out[0]
    assert "CLAMPED" in out[1] and "Coventry City (attack)" in out[1]
    assert not any(o.startswith(ld.MODEL_DEGRADED) for o in out)
    # a clamped club whose lambda is still below 0.15 is EXTREME regardless: the bounds do not move
    frame.loc[0, "team_lambda"] = 0.14
    out = ld.degraded_findings(frame, last_fit=lf)
    assert any(o.startswith(ld.MODEL_DEGRADED) and "Coventry City lambda=0.1400" in o for o in out)


def test_record_strengths_inside_the_bounds_once_rebuilt_with_the_prior():
    """Sanity gate (c) of prereg v2, permanent once the record is rebuilt with the form: no team
    lambda outside [0.15, 6.0] at any step of any cutoff of the three canonicals. Keyed to the
    preserved pre-change artefact (*_pre_hinge exists <=> the rebuild happened); skips before."""
    if not (REPO / "data" / "walkforward_h6_2025_26_pre_hinge.parquet").exists():
        pytest.skip("record not yet rebuilt with the v2 form (no *_pre_hinge artefact)")
    for tag in ("2023_24", "2024_25", "2025_26"):
        p = REPO / "data" / f"walkforward_h6_{tag}.parquet"
        cols = pd.read_parquet(p, columns=["cutoff", "gw", "team", "team_lambda"])
        lam = cols.groupby(["cutoff", "gw", "team"])["team_lambda"].first().dropna()
        assert lam.min() >= 0.15 and lam.max() <= 6.0, f"{p.name}: strengths {lam.min():.4f}..{lam.max():.4f}"
