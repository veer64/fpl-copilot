"""v3 = v2 + a promoted-club centre for the hinge (Logs/dc_shrinkage_v3_prereg_2026-09-17.md section 2).
Patches squad/dixon_coles.py, squad/live_deadline.py and the tests on branch hinge-box-v2."""
from pathlib import Path

p = Path(r"C:\dev\fpl-copilot\squad\dixon_coles.py")
s = p.read_text(encoding="utf-8", newline="")
nl = "\r\n" if "\r\n" in s else "\n"


def rep(old, new, count=1):
    global s
    o, n = old.replace("\n", nl), new.replace("\n", nl)
    assert s.count(o) == count, (s.count(o), old[:70])
    s = s.replace(o, n)


rep('''ATK_DFC_BOUND = float(np.log(4.0))    # the plausibility box, +-ln 4 (0.25x .. 4x)
''', '''ATK_DFC_BOUND = float(np.log(4.0))    # the plausibility box, +-ln 4 (0.25x .. 4x)
# --- v3 (Logs/dc_shrinkage_v3_prereg_2026-09-17.md, approved 2026-09-17): the point the hinge pulls a
# PROMOTED club toward is not the league mean but what a promoted club has been. Measured on the
# archive's nine promoted cohorts (2017-18 .. 2025-26, 27 clubs; the plain end-of-season fit,
# centred over the season's twenty clubs): first-season attack -0.307 (sd 0.22, se 0.04; 0.74x the
# league rate), defence +0.203 (sd 0.20; concedes 1.22x); the same at mid-season; no cohort on the
# other side of zero; leave-one-cohort-out within 0.02; returners no better than long-absent clubs
# (one class). FIXED constants, derived once: a per-fit estimate from the current season's three
# promoted clubs would couple the centre to exactly the evidence the prior exists to supplement.
# "Promoted" is a data fact read from the archive at every cutoff (in the predict season's
# fixtures, not in the previous season's). A club below N that is NOT promoted keeps centre (0, 0)
# (v2's form) and is named in a MODEL NOTE. A different centre is a NEW pre-registration.
MU_PROMOTED_ATTACK = -0.31
MU_PROMOTED_DEFENCE = 0.20
''')
rep('''def _fit_dc_decay(train_matches, all_teams, ref_date, half_life_days, prior_teams=None):
    """Fit the DC model on `train_matches` (canonical names). `prior_teams`: the clubs the
    hinge prior may touch (the predict season's clubs); None = every club in the fit.
    Refuses (raises) a training set with unplayed matches or no rows -- see knowable_before."""''',
    '''def _fit_dc_decay(train_matches, all_teams, ref_date, half_life_days, prior_teams=None, promoted_teams=None):
    """Fit the DC model on `train_matches` (canonical names). `prior_teams`: the clubs the
    hinge prior may touch (the predict season's clubs); None = every club in the fit.
    `promoted_teams`: the clubs among them that are promoted for the predict season -- their
    hinge centre is (MU_PROMOTED_ATTACK, MU_PROMOTED_DEFENCE); every other club's is (0, 0).
    Refuses (raises) a training set with unplayed matches or no rows -- see knowable_before."""''')
rep('''    hinge_on = bool((tau_i > 0).any())
''', '''    hinge_on = bool((tau_i > 0).any())
    # v3: the hinge's centre per club -- the promoted-club constants for promoted clubs, 0 otherwise
    promoted = set(promoted_teams or ()) & {t for t, ip in zip(all_teams, in_prior) if ip}
    mu_a = np.array([MU_PROMOTED_ATTACK if t in promoted else 0.0 for t in all_teams])
    mu_d = np.array([MU_PROMOTED_DEFENCE if t in promoted else 0.0 for t in all_teams])
''')
rep('''            # (A) the hinge prior on the evidence-poor clubs' CENTRED parameters (gauge-invariant)
            c = centred(params)
            val = val + 0.5 * float(np.sum(tau_i * (c[:nt] ** 2 + c[nt:] ** 2)))''',
    '''            # (A) the hinge prior on the evidence-poor clubs' CENTRED parameters (gauge-invariant),
            # about the club's centre (v3: the promoted-club constants for a promoted club)
            c = centred(params)
            val = val + 0.5 * float(np.sum(tau_i * ((c[:nt] - mu_a) ** 2 + (c[nt:] - mu_d) ** 2)))''')
rep('''                    clubs_below_n={str(all_teams[i]): {"n_eff": round(float(n_eff[i]), 2), "tau": round(float(tau_i[i]), 3)}
                                   for i in range(nt) if tau_i[i] > 0},
                    at_bound=at_bound,''',
    '''                    clubs_below_n={str(all_teams[i]): {"n_eff": round(float(n_eff[i]), 2), "tau": round(float(tau_i[i]), 3),
                                                       "centre": ("promoted" if all_teams[i] in promoted else "league")}
                                   for i in range(nt) if tau_i[i] > 0},
                    promoted=sorted(str(t) for t in promoted),
                    mu_promoted={"attack": float(MU_PROMOTED_ATTACK), "defence": float(MU_PROMOTED_DEFENCE)},
                    hinged_not_promoted=sorted(str(all_teams[i]) for i in range(nt) if tau_i[i] > 0 and all_teams[i] not in promoted),
                    at_bound=at_bound,''')
rep('''    cur = mc[mc["season"] == predict_season]
    prior_teams = sorted(set(cur["home"]) | set(cur["away"]))      # the clubs whose parameters are USED
    params, idx, nt = _fit_dc_decay(train_m, teams, ref, HALF_LIFE_DAYS, prior_teams=prior_teams)''',
    '''    cur = mc[mc["season"] == predict_season]
    prior_teams = sorted(set(cur["home"]) | set(cur["away"]))      # the clubs whose parameters are USED
    # v3: promoted = in the predict season's fixtures and not in the previous archive season's (a data
    # fact under canonical names; the archive's first season has no previous season -> nobody promoted)
    earlier = sorted(s for s in mc["season"].unique() if s < predict_season)
    if earlier:
        prev = mc[mc["season"] == earlier[-1]]
        promoted_teams = sorted(t for t in prior_teams if t not in (set(prev["home"]) | set(prev["away"])))
    else:
        promoted_teams = []
    params, idx, nt = _fit_dc_decay(train_m, teams, ref, HALF_LIFE_DAYS, prior_teams=prior_teams,
                                    promoted_teams=promoted_teams)''')
p.write_text(s, encoding="utf-8", newline="")
print("dixon_coles patched")

p2 = Path(r"C:\dev\fpl-copilot\squad\live_deadline.py")
s2 = p2.read_text(encoding="utf-8", newline="")
nl2 = "\r\n" if "\r\n" in s2 else "\n"
old = '''        out.append(f"{MODEL_NOTE} hinge prior active (evidence below {(lf or {}).get('shrink_n')} effective matches): "
                   + ", ".join(f"{t} (n_eff {v.get('n_eff')}, tau {v.get('tau')})" for t, v in sorted(below.items())))'''
new = '''        mu = (lf or {}).get("mu_promoted") or {}
        out.append(f"{MODEL_NOTE} hinge prior active (evidence below {(lf or {}).get('shrink_n')} effective matches; "
                   f"promoted-club centre attack {mu.get('attack')} / defence {mu.get('defence')}): "
                   + ", ".join(f"{t} (n_eff {v.get('n_eff')}, tau {v.get('tau')}, centre {v.get('centre', 'league')})"
                               for t, v in sorted(below.items())))
        hnp = (lf or {}).get("hinged_not_promoted") or []
        if hnp:
            out.append(f"{MODEL_NOTE} a club below {(lf or {}).get('shrink_n')} effective matches that is NOT promoted "
                       f"(centre = the league mean, v2's form): {', '.join(hnp)} -- the evidence table said this never "
                       "happens; understand the club")'''
assert old.replace("\n", nl2) in s2
s2 = s2.replace(old.replace("\n", nl2), new.replace("\n", nl2))
p2.write_text(s2, encoding="utf-8", newline="")
print("live_deadline patched")

p3 = Path(r"C:\dev\fpl-copilot\Tests\test_dixon_coles_shrinkage.py")
s3 = p3.read_text(encoding="utf-8", newline="")
nl3 = "\r\n" if "\r\n" in s3 else "\n"
anchor = "def test_the_box_binds_only_where_the_mle_runs_off():"
new_tests = '''# ------------------------------------------------ v3: the promoted-club centre (prereg 2026-09-17 evening)
def test_a_promoted_club_with_no_rows_sits_exactly_at_the_promoted_centre():
    """A promoted club with zero training rows has nothing but the hinge: its centred parameters
    settle at (MU_PROMOTED_ATTACK, MU_PROMOTED_DEFENCE) -- the implementation check the prereg
    names (section 3's first tell). A non-promoted club in the same position sits at (0, 0)."""
    rng = np.random.default_rng(4)
    rows = _league(rng, n_rounds=40)
    league = list("ABCDEF") + ["P", "Q"]
    teams = sorted(league)
    p, idx, nt = dc._fit_dc_decay(pd.DataFrame(rows), teams, REF, 365, prior_teams=league, promoted_teams=["P"])
    pri = [idx[t] for t in league]
    c_a = p[:nt] - p[pri].mean(); c_d = p[nt:2 * nt] - p[nt + np.array(pri)].mean()
    assert abs(c_a[idx["P"]] - dc.MU_PROMOTED_ATTACK) < 1e-3 and abs(c_d[idx["P"]] - dc.MU_PROMOTED_DEFENCE) < 1e-3
    assert abs(c_a[idx["Q"]]) < 1e-3 and abs(c_d[idx["Q"]]) < 1e-3
    assert dc.LAST_FIT["promoted"] == ["P"] and dc.LAST_FIT["hinged_not_promoted"] == ["Q"]
    assert dc.LAST_FIT["clubs_below_n"]["P"]["centre"] == "promoted" and dc.LAST_FIT["clubs_below_n"]["Q"]["centre"] == "league"
    assert dc.LAST_FIT["mu_promoted"] == {"attack": -0.31, "defence": 0.20}
    assert dc.LAST_FIT["converged"] is True and dc.LAST_FIT["boxed_refit"] is False


def test_the_promoted_centre_lowers_a_scoreless_newcomer_and_the_box_still_holds():
    """The prereg's table: at n = 3 the promoted centre sits below the league centre by 0.1-0.35
    (0.20 at the real league rate); at n = 8 both are at the box, -ln 4 exactly, SLSQP."""
    rows = _newcomer_rows(3)
    teams = sorted({r["home"] for r in rows} | {r["away"] for r in rows})
    p2_, idx, nt = dc._fit_dc_decay(pd.DataFrame(rows), teams, REF, 365, prior_teams=teams)
    a_v2 = p2_[idx["N"]] - p2_[:nt].mean()
    p3_, idx, nt = dc._fit_dc_decay(pd.DataFrame(rows), teams, REF, 365, prior_teams=teams, promoted_teams=["N"])
    a_v3 = p3_[idx["N"]] - p3_[:nt].mean()
    assert 0.10 <= a_v2 - a_v3 <= 0.35, (a_v2, a_v3)
    assert dc.LAST_FIT["converged"] is True and dc.LAST_FIT["at_bound"] == {}
    rows = _newcomer_rows(8)
    teams = sorted({r["home"] for r in rows} | {r["away"] for r in rows})
    p8, idx, nt = dc._fit_dc_decay(pd.DataFrame(rows), teams, REF, 365, prior_teams=teams, promoted_teams=["N"])
    a8 = p8[idx["N"]] - p8[:nt].mean()
    assert abs(a8 + dc.ATK_DFC_BOUND) < 1e-5 and dc.LAST_FIT["at_bound"] == {"N": ["attack"]} and dc.LAST_FIT["method"] == "SLSQP"


def test_v2_form_is_unchanged_when_nobody_is_promoted():
    """v3 = v2 + the centre: with promoted_teams empty (or None) the objective is v2's, bit for bit."""
    rows = _newcomer_rows(3)
    teams = sorted({r["home"] for r in rows} | {r["away"] for r in rows})
    p_a, _, _ = dc._fit_dc_decay(pd.DataFrame(rows), teams, REF, 365, prior_teams=teams)
    p_b, _, _ = dc._fit_dc_decay(pd.DataFrame(rows), teams, REF, 365, prior_teams=teams, promoted_teams=[])
    assert np.array_equal(p_a, p_b) and dc.LAST_FIT["promoted"] == [] and dc.LAST_FIT["hinged_not_promoted"] == ["N"]


'''
assert anchor in s3
s3 = s3.replace(anchor, new_tests.replace("\n", nl3) + anchor)
# the live-fixture test: the promoted three are detected from the archive
old = '''    assert dc.LAST_FIT["converged"] is True'''
new = '''    assert dc.LAST_FIT["converged"] is True
    assert dc.LAST_FIT["promoted"] == ["Coventry City", "Hull City", "Ipswich Town"], dc.LAST_FIT["promoted"]
    assert dc.LAST_FIT["hinged_not_promoted"] == []'''
assert s3.count(old.replace("\n", nl3)) == 1
s3 = s3.replace(old.replace("\n", nl3), new.replace("\n", nl3))
# the notes test: the hinge note now carries the centre
old = '''    lf = {"converged": True, "shrink_n": 10, "clubs_below_n": {"Hull": {"n_eff": 4.0, "tau": 3.36}},
          "at_bound": {"Coventry City": ["attack"]}}'''
new = '''    lf = {"converged": True, "shrink_n": 10, "clubs_below_n": {"Hull": {"n_eff": 4.0, "tau": 3.36, "centre": "promoted"}},
          "mu_promoted": {"attack": -0.31, "defence": 0.2}, "hinged_not_promoted": [],
          "at_bound": {"Coventry City": ["attack"]}}'''
assert s3.count(old.replace("\n", nl3)) == 1
s3 = s3.replace(old.replace("\n", nl3), new.replace("\n", nl3))
old = '''    assert "hinge prior active" in out[0] and "Hull (n_eff 4.0, tau 3.36)" in out[0]'''
new = '''    assert "hinge prior active" in out[0] and "Hull (n_eff 4.0, tau 3.36, centre promoted)" in out[0] and "attack -0.31 / defence 0.2" in out[0]'''
assert s3.count(old.replace("\n", nl3)) == 1
s3 = s3.replace(old.replace("\n", nl3), new.replace("\n", nl3))
p3.write_text(s3, encoding="utf-8", newline="")
print("tests patched")
