"""Tests for the second pass: centred parameters, the gauge kept, prior_teams, SLSQP at the box,
MODEL NOTE findings, the record test keyed to the *_pre_hinge artefact."""
from pathlib import Path

p = Path(r"C:\dev\fpl-copilot\Tests\test_dixon_coles_shrinkage.py")
s = p.read_text(encoding="utf-8", newline="")
nl = "\r\n" if "\r\n" in s else "\n"
start = s.index("@pytest.mark.parametrize(\"n, lo, hi, at_box\"")
end = s.index("# ------------------------------------------------------- change B: names and the guard")
new = '''def _fit(rows, **kw):
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


def test_the_box_binds_only_where_the_mle_runs_off():
    p, idx, nt, c_atk, c_dfc = _fit(_newcomer_rows(12))
    assert dc.LAST_FIT["at_bound"] == {"N": ["attack"]}
    others = [abs(c_atk[idx[t]]) for t in idx if t != "N"] + [abs(v) for v in c_dfc]
    assert max(others) < dc.ATK_DFC_BOUND - 0.2          # no other parameter near a bound
    assert dc.LAST_FIT["min_margin_to_bound"] > 0.2 and "N" not in dc.LAST_FIT["min_margin_club"]


'''
s = s[:start] + new.replace("\n", nl) + s[end:]

# the loud-detector tests: MODEL NOTE findings, EXTREME unchanged for a clamped club
old_rec = "def test_record_strengths_inside_the_bounds_once_rebuilt_with_the_prior():"
extra = '''def test_clamped_and_hinged_clubs_are_model_notes_not_degraded():
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


def test_record_strengths_inside_the_bounds_once_rebuilt_with_the_prior():'''
assert old_rec in s
s = s.replace(old_rec, extra.replace("\n", nl))
old_body = s[s.index("    \"\"\"The three canonicals, IF ever built with a prior (stamp dc_shrink_k)"):s.index("        pytest.skip(\"no canonical carries the dc_shrink_k stamp yet (pre-rebuild)\")") + len("        pytest.skip(\"no canonical carries the dc_shrink_k stamp yet (pre-rebuild)\")")]
new_body = '''    """Sanity gate (c) of prereg v2, permanent once the record is rebuilt with the form: no team
    lambda outside [0.15, 6.0] at any step of any cutoff of the three canonicals. Keyed to the
    preserved pre-change artefact (*_pre_hinge exists <=> the rebuild happened); skips before."""
    if not (REPO / "data" / "walkforward_h6_2025_26_pre_hinge.parquet").exists():
        pytest.skip("record not yet rebuilt with the v2 form (no *_pre_hinge artefact)")
    for tag in ("2023_24", "2024_25", "2025_26"):
        p = REPO / "data" / f"walkforward_h6_{tag}.parquet"
        cols = pd.read_parquet(p, columns=["cutoff", "gw", "team", "team_lambda"])
        lam = cols.groupby(["cutoff", "gw", "team"])["team_lambda"].first().dropna()
        assert lam.min() >= 0.15 and lam.max() <= 6.0, f"{p.name}: strengths {lam.min():.4f}..{lam.max():.4f}"'''
s = s.replace(old_body, new_body.replace("\n", nl))
p.write_text(s, encoding="utf-8", newline="")
print("shrinkage tests patched")

p2 = Path(r"C:\dev\fpl-copilot\Tests\test_model_degraded_health.py")
s2 = p2.read_text(encoding="utf-8", newline="")
nl2 = "\r\n" if "\r\n" in s2 else "\n"
s2 = s2.rstrip("\r\n") + nl2 + nl2 + nl2 + '''def test_model_notes_reach_health_as_information_not_reasons():
    run = {"run_id": 15, "strict_findings": {"baseline": [
        "MODEL NOTE: hinge prior active (evidence below 10 effective matches): Coventry City (n_eff 4.0, tau 3.36)",
        "MODEL NOTE: Dixon-Coles strength CLAMPED at the plausibility bound (+-ln 4 of the league rate): Hull (defence) -- served",
        "note: 269 of 656 rows have no understat_id"]}}
    notes = mt._model_notes(run)
    assert len(notes) == 2 and notes[0].startswith("run 15, baseline: hinge prior active") and "CLAMPED" in notes[1]
    assert mt._model_degraded_reasons(run) == []          # a note never degrades
    assert mt._model_notes({"run_id": 16, "strict_findings": {"baseline": ["note: x"]}}) == []
'''.replace("\n", nl2)
p2.write_text(s2, encoding="utf-8", newline="")
print("health tests patched")
