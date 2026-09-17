"""Second pass on the v2 implementation: the hinge and the box act on CENTRED parameters
(gauge-invariant), the box is a linear constraint on the refit (SLSQP), the hinge is restricted
to the predict season's clubs (prior_teams), LAST_FIT records the gate quantities."""
from pathlib import Path

p = Path(r"C:\dev\fpl-copilot\squad\dixon_coles.py")
s = p.read_text(encoding="utf-8", newline="")
nl = "\r\n" if "\r\n" in s else "\n"

# 1. the constants comment: add the identifiability paragraph
old_tail = '''# tau0 / N / bound is a NEW pre-registration, never a tuning of this one. SHRINK_N = 0 switches
# the hinge off and ATK_DFC_BOUND = None the box, each exactly (a revert, if the bar falsifies).'''
new_tail = '''# tau0 / N / bound is a NEW pre-registration, never a tuning of this one. SHRINK_N = 0 switches
# the hinge off and ATK_DFC_BOUND = None the box, each exactly (a revert, if the bar falsifies).
#
# IDENTIFIABILITY (found at implementation, 2026-09-17, before any endpoint number; recorded in
# the prereg log): the likelihood is invariant to atk + c / dfc - c, so "attack 0" means nothing
# on its own. The record's fits sit in the gauge sum(atk) = sum(dfc) (L-BFGS-B from zeros never
# moves along the flat direction), where the LEAGUE MEAN attack is about +0.09, not 0. A prior
# or a box written on the raw coordinates is therefore not what the prereg's words say ("the
# league rate") -- and worse, the optimiser can cheapen one club's penalty by shifting the WHOLE
# league along the flat direction, and a raw-coordinate box lets a scoreless club keep running
# off through that shift until some established club hits the opposite bound (seen on the
# synthetic test). Both parts therefore act on CENTRED parameters, atk_i - mean(atk) and
# dfc_i - mean(dfc) over the clubs in the fit: invariant to the gauge, so the fit stays in the
# record's gauge and "0.25x the league rate" means exactly that. The box becomes a linear
# constraint (SLSQP on the refit only; L-BFGS-B, the record's optimiser, everywhere else).
# The hinge applies to the clubs whose parameters are USED (the predict season's clubs,
# `prior_teams`): a club relegated two seasons earlier sits at n_eff ~ 9.5 in every fit, and a
# hinge on it would switch the penalty on at every cutoff and break the bit-identity promised.'''
assert old_tail.replace("\n", nl) in s
s = s.replace(old_tail.replace("\n", nl), new_tail.replace("\n", nl))

# 2. the fit
fstart = s.index("def _fit_dc_decay(train_matches, all_teams, ref_date, half_life_days):")
fend = s.index("    return x, idx, nt") + len("    return x, idx, nt")
func = '''def _fit_dc_decay(train_matches, all_teams, ref_date, half_life_days, prior_teams=None):
    """Fit the DC model on `train_matches` (canonical names). `prior_teams`: the clubs the
    hinge prior may touch (the predict season's clubs); None = every club in the fit.
    Refuses (raises) a training set with unplayed matches or no rows -- see knowable_before."""
    n_nan = int(train_matches[["home_goals", "away_goals"]].isna().any(axis=1).sum())
    if n_nan:
        raise ValueError(f"Dixon-Coles training set has {n_nan} match(es) with NaN goals -- "
                         "unplayed fixtures leaked past the cutoff (knowable_before); refusing to fit")
    if len(train_matches) == 0:
        raise ValueError("Dixon-Coles training set is empty -- refusing to fit")
    idx = {t: i for i, t in enumerate(all_teams)}
    nt = len(all_teams)
    h = train_matches["home"].map(idx).values
    a = train_matches["away"].map(idx).values
    hg = train_matches["home_goals"].values.astype(float)
    ag = train_matches["away_goals"].values.astype(float)
    age = (ref_date - train_matches["date_parsed"]).dt.days.values
    w = np.ones(len(age)) if half_life_days is None else np.exp(-(np.log(2) / half_life_days) * age)

    # (A) evidence per club (decay-weighted match count) and the hinge precision it earns
    n_eff = np.zeros(nt)
    np.add.at(n_eff, h, w); np.add.at(n_eff, a, w)
    in_prior = np.ones(nt, dtype=bool) if prior_teams is None else np.array([t in set(prior_teams) for t in all_teams])
    tau_i = np.zeros(nt)
    if SHRINK_N:
        tau_i[in_prior] = SHRINK_TAU0 * np.clip(1.0 - n_eff[in_prior] / SHRINK_N, 0.0, None)
    hinge_on = bool((tau_i > 0).any())

    def centred(p):
        atk, dfc = p[:nt], p[nt:2 * nt]
        return np.concatenate([atk - atk.mean(), dfc - dfc.mean()])

    def nll(params):
        atk, dfc = params[:nt], params[nt:2 * nt]
        hadv, rho = params[-2], params[-1]
        lam_h = np.exp(atk[h] + dfc[a] + hadv)
        lam_a = np.exp(atk[a] + dfc[h])
        log_p = poisson.logpmf(hg, lam_h) + poisson.logpmf(ag, lam_a)
        tau = np.ones(len(hg))
        tau[(hg == 0) & (ag == 0)] = (1 - lam_h * lam_a * rho)[(hg == 0) & (ag == 0)]
        tau[(hg == 0) & (ag == 1)] = (1 + lam_h * rho)[(hg == 0) & (ag == 1)]
        tau[(hg == 1) & (ag == 0)] = (1 + lam_a * rho)[(hg == 1) & (ag == 0)]
        tau[(hg == 1) & (ag == 1)] = (1 - rho)
        log_p = log_p + np.log(np.clip(tau, 1e-10, None))
        val = -(w * log_p).sum()
        if hinge_on:
            # (A) the hinge prior on the evidence-poor clubs' CENTRED parameters (gauge-invariant)
            c = centred(params)
            val = val + 0.5 * float(np.sum(tau_i * (c[:nt] ** 2 + c[nt:] ** 2)))
        return val

    x0 = np.zeros(2 * nt + 2); x0[-2] = 0.25
    res = minimize(nll, x0, method="L-BFGS-B")                     # the unbounded fit, the record's optimiser
    method, boxed_refit = "L-BFGS-B", False
    B = ATK_DFC_BOUND
    if B is not None and float(np.abs(centred(res.x)).max()) > B:
        # (B) the box, ONLY because the unbounded fit left it: |atk_i - mean(atk)| <= B and the
        # same for defence, as linear inequality constraints A p + B >= 0 (rows: +-(e_i - 1/nt))
        C = np.zeros((2 * nt, 2 * nt + 2))
        C[:nt, :nt] = -1.0 / nt
        C[nt:, nt:2 * nt] = -1.0 / nt
        C[np.arange(2 * nt), np.arange(2 * nt)] += 1.0
        A = np.vstack([C, -C])
        cons = [{"type": "ineq", "fun": lambda p, A=A, B=B: A @ p + B, "jac": lambda p, A=A: A}]
        res = minimize(nll, x0, method="SLSQP", constraints=cons, options={"maxiter": 1000})
        method, boxed_refit = "SLSQP", True
    x = res.x
    c = centred(x)
    at_bound = {}
    if B is not None:
        for i, t in enumerate(all_teams):
            hit = [nm for nm, v in (("attack", c[i]), ("defence", c[nt + i])) if abs(abs(v) - B) < 1e-5]
            if hit:
                at_bound[str(t)] = hit
    # gate (e) of the prereg: how close the nearest ESTABLISHED club (n_eff >= N, not at a bound)
    # sits to the box; and the evidence of the predict season's poorest club
    est = [i for i in range(nt) if n_eff[i] >= (SHRINK_N or 0) and str(all_teams[i]) not in at_bound]
    margins = [(B - abs(c[i]), str(all_teams[i]), "attack") for i in est] + \\
              [(B - abs(c[nt + i]), str(all_teams[i]), "defence") for i in est] if B is not None else []
    m_min = min(margins) if margins else (None, None, None)
    pri = [i for i in range(nt) if in_prior[i]] or list(range(nt))
    i_min = int(min(pri, key=lambda i: n_eff[i]))
    LAST_FIT.clear()
    LAST_FIT.update(n_train=int(len(train_matches)), n_teams=int(nt), iterations=int(res.nit),
                    converged=bool(res.success), method=method, boxed_refit=boxed_refit,
                    max_abs_attack=float(np.abs(x[:nt]).max()), max_abs_defence=float(np.abs(x[nt:2 * nt]).max()),
                    max_abs_centred_attack=float(np.abs(c[:nt]).max()), max_abs_centred_defence=float(np.abs(c[nt:]).max()),
                    league_mean_attack=float(x[:nt].mean()), league_mean_defence=float(x[nt:2 * nt].mean()),
                    home_adv=float(x[-2]), rho=float(x[-1]),
                    ref_date=str(pd.Timestamp(ref_date)),
                    shrink_tau0=float(SHRINK_TAU0), shrink_n=int(SHRINK_N or 0),
                    bound=(None if B is None else float(B)),
                    n_eff_min=float(n_eff[i_min]), n_eff_min_club=str(all_teams[i_min]),
                    clubs_below_n={str(all_teams[i]): {"n_eff": round(float(n_eff[i]), 2), "tau": round(float(tau_i[i]), 3)}
                                   for i in range(nt) if tau_i[i] > 0},
                    at_bound=at_bound,
                    min_margin_to_bound=(None if m_min[0] is None else round(float(m_min[0]), 4)),
                    min_margin_club=(None if m_min[0] is None else f"{m_min[1]} {m_min[2]}"))
    return x, idx, nt'''
s = s[:fstart] + func.replace("\n", nl) + s[fend:]

# 3. the call site: the predict season's clubs are the hinge's scope
old_call = "    params, idx, nt = _fit_dc_decay(train_m, teams, ref, HALF_LIFE_DAYS)"
new_call = '''    cur = mc[mc["season"] == predict_season]
    prior_teams = sorted(set(cur["home"]) | set(cur["away"]))      # the clubs whose parameters are USED
    params, idx, nt = _fit_dc_decay(train_m, teams, ref, HALF_LIFE_DAYS, prior_teams=prior_teams)'''
assert old_call in s
s = s.replace(old_call, new_call.replace("\n", nl))
p.write_text(s, encoding="utf-8", newline="")
print("dixon_coles patched")

# 4. live_deadline: CLAMPED is a MODEL NOTE (visible, not degraded); the EXTREME check is unchanged
p2 = Path(r"C:\dev\fpl-copilot\squad\live_deadline.py")
s2 = p2.read_text(encoding="utf-8", newline="")
old_block_start = s2.index("    out = []\r\n    lf = dc_mod.LAST_FIT if last_fit is None else last_fit" if "\r\n" in s2 else "    out = []\n    lf = dc_mod.LAST_FIT if last_fit is None else last_fit")
old_block_end = s2.index("    if lf and lf.get(\"converged\") is False:")
new_block = '''    out = []
    lf = dc_mod.LAST_FIT if last_fit is None else last_fit
    for step, s in frame.groupby("horizon_step" if "horizon_step" in frame.columns else "gw"):
        lam = s.groupby("team")["team_lambda"].first().dropna()
        bad = lam[(lam < LAMBDA_MIN) | (lam > LAMBDA_MAX)]
        if len(bad):
            out.append(f"{MODEL_DEGRADED} Dixon-Coles strength EXTREME at horizon step {step}: "
                       + ", ".join(f"{t} lambda={v:.4f}" for t, v in bad.items())
                       + f" (outside [{LAMBDA_MIN}, {LAMBDA_MAX}]) -- a parameter ran off: no history and a "
                       "one-sided record (KNOWN_ISSUES #25); served, not refused")
    # THE BOX AND THE DETECTOR, settled 2026-09-17 before the fatal raise ships (prereg v2,
    # Logs/dc_shrinkage_threshold_prereg_2026-09-17.md): a club CLAMPED at the plausibility
    # bound (LAST_FIT["at_bound"]) is the box working, not a parameter running off. It is a
    # MODEL NOTE -- visible in the run's findings and on /health, never a degraded reason, never
    # pushed, never raised. The EXTREME check above is UNCHANGED and still applies to a clamped
    # club: its bounds are the bounds, and a lambda below 0.15 is a finding whoever produces
    # it. The fatal raise, when it ships, raises on EXTREME and on a non-converged fit only.
    below = (lf or {}).get("clubs_below_n") or {}
    if below:
        out.append(f"{MODEL_NOTE} hinge prior active (evidence below {(lf or {}).get('shrink_n')} effective matches): "
                   + ", ".join(f"{t} (n_eff {v.get('n_eff')}, tau {v.get('tau')})" for t, v in sorted(below.items())))
    clamped = (lf or {}).get("at_bound") or {}
    if clamped:
        out.append(f"{MODEL_NOTE} Dixon-Coles strength CLAMPED at the plausibility bound (+-ln 4 of the league rate): "
                   + ", ".join(f"{t} ({'/'.join(v)})" for t, v in sorted(clamped.items()))
                   + " -- a one-sided record with the hinge released; the box is holding (prereg v2 section 1); served")
'''
nl2 = "\r\n" if "\r\n" in s2 else "\n"
s2 = s2[:old_block_start] + new_block.replace("\n", nl2) + s2[old_block_end:]
old_msg = '''        out.append(f"{MODEL_DEGRADED} Dixon-Coles fit did NOT converge (L-BFGS-B success False after "'''
new_msg = '''        out.append(f"{MODEL_DEGRADED} Dixon-Coles fit did NOT converge ({lf.get('method') or 'L-BFGS-B'} success False after "'''
assert old_msg in s2
s2 = s2.replace(old_msg, new_msg)
old_const = 'MODEL_DEGRADED = "MODEL DEGRADED:"'
assert old_const in s2
s2 = s2.replace(old_const, old_const + nl2 + 'MODEL_NOTE = "MODEL NOTE:"        # visible on the run and /health; never degrades, never pushes, never raises')
old_doc = '''    """The two LOUD, NON-FATAL model-degradation findings (MODEL_DEGRADED prefix): a club
    whose team_lambda sits outside [LAMBDA_MIN, LAMBDA_MAX] at any step, and a fit that
    did not converge. Pure over the frame (+ dixon_coles.LAST_FIT unless given); returns
    strings and never raises, so a degraded model is served AND visible."""'''
new_doc = '''    """The two LOUD, NON-FATAL model-degradation findings (MODEL_DEGRADED prefix): a club
    whose team_lambda sits outside [LAMBDA_MIN, LAMBDA_MAX] at any step, and a fit that
    did not converge -- plus the MODEL NOTE findings (the hinge prior's clubs; a club clamped
    at the plausibility bound), which inform and never degrade. Pure over the frame
    (+ dixon_coles.LAST_FIT unless given); returns strings and never raises."""'''
assert old_doc.replace("\n", nl2) in s2
s2 = s2.replace(old_doc.replace("\n", nl2), new_doc.replace("\n", nl2))
p2.write_text(s2, encoding="utf-8", newline="")
print("live_deadline patched")
