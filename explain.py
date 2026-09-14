"""
explain.py -- `explain_prediction` levels 1 and 2 (Logs/explain_prediction_design.md;
master plan 5.4's "demo"). PURE FUNCTIONS over one frame row (plus the row's gameweek
slice for the step-level detector): no database, no files, no model path.

Level 1 (breakdown): the nine lines the master equation sums, in descending absolute
contribution, each with the inputs it was made from, ONE of three source words
(model / constant / rule), the constant's name where a constant stands in for a model,
the fixture line, the two identities re-asserted on the row (a failure is a FINDING,
not an answer), and one summary line.

Level 2 (compare): both breakdowns on the same gameweek, the per-term difference, the
terms ranked by |difference|, the terms that account for >= 80% of the gap, and a flag
wherever a gap is a constant on one side against a model value on the other.

The vocabulary never varies:
  model    -- computed by a fitted model for this player / fixture
  constant -- a fixed value standing in for a model this project has not built (or has
              switched off); the same for every player in this situation
  rule     -- FPL's scoring rule applied to a model output
The constant labels are a fixed list (CONSTANT_LABELS); the summary line quotes them.
"""
import math

import numpy as np

# The model's constants, restated here so the API process does not import the model stack
# (assembly pulls minutes / lightgbm) to explain a row. Tests/test_explain_prediction.py
# asserts these equal squad/assembly.py's and squad/defensive.py's, so they cannot drift.
GOAL_PTS = {"FWD": 4, "MID": 5, "DEF": 6, "GK": 6}
CS_PTS = {"FWD": 0, "MID": 1, "DEF": 4, "GK": 4}
DC_BASE = {"DEF": 0.125, "MID": 0.136, "FWD": 0.058, "GK": 0.0}
LEAGUE_AVG_LAMBDA = 1.40
FWD_BASE_RATE = 0.005

TOL = 1e-6                       # float summation order only; anything larger is a defect
LAMBDA_MIN, LAMBDA_MAX = 0.15, 6.0   # the runaway-strength box (KNOWN_ISSUES #25)
X0_HOME, X0_AWAY = float(math.exp(0.25)), 1.0     # the Dixon-Coles fit's starting point
PEN_FALLBACK = 0.05
SUB_CHANCE = 0.30

# the nine lines, in the equation's order; the first eight sum to e_points_core
TERMS = [("appearance", "pts_appear"), ("goals", "pts_goals"), ("assists", "pts_assists"),
         ("clean_sheet", "pts_cs"), ("defensive_contribution", "pts_dc"), ("saves", "pts_saves"),
         ("goals_conceded", "pts_conceded"), ("cards", "pts_cards"), ("bonus", "exp_bonus")]
CORE = [c for _, c in TERMS[:8]]

CONSTANT_LABELS = {
    "dc_positional": "flat positional value",
    "dc_fwd": "flat by design",
    "position_prior": "position prior",
    "pen_fallback": "fallback 0.05",
    "neutral_fixture": "league-average fixture",
    "x0_fixture": "the fit's starting point",
    "bonus_off": "0 by decision",
    "sub_chance": "flat 0.30 sub chance",
    "card_rates": "position rates",
    "linear_scale": "linear scale",
}


def _f(row, col, default=float("nan")):
    v = row.get(col, default) if hasattr(row, "get") else getattr(row, col, default)
    try:
        return float(v)
    except (TypeError, ValueError):
        return float("nan")


def _close(a, b, tol=1e-9):
    return a == a and b == b and abs(a - b) <= tol


def _no_understat(row):
    v = row.get("understat_id") if hasattr(row, "get") else getattr(row, "understat_id", None)
    if v is None:
        return True
    try:
        return bool(np.isnan(float(v)))
    except (TypeError, ValueError):
        return str(v).strip() in ("", "nan", "None")


def reconcile(row):
    """The two identities on one row: eight terms == e_points_core, core + bonus == e_points."""
    core = sum(_f(row, c, 0.0) for c in CORE)
    r_core = core - _f(row, "e_points_core", 0.0)
    r_total = (_f(row, "e_points_core", 0.0) + _f(row, "exp_bonus", 0.0)) - _f(row, "e_points", 0.0)
    ok = abs(r_core) <= TOL and abs(r_total) <= TOL
    return {"reconciles": bool(ok), "residual_core": float(r_core), "residual_total": float(r_total),
            "tolerance": TOL}


def step_is_degenerate(step_rows):
    """Detector 7: every club's team_lambda at this step is the fit's starting point
    (home e^0.25 / away 1.0). Needs >= 10 clubs to say anything."""
    if step_rows is None or len(step_rows) == 0 or "team" not in step_rows.columns:
        return False
    lam = step_rows.groupby("team")["team_lambda"].first().dropna()
    if len(lam) < 10:
        return False
    at_x0 = np.isclose(lam, X0_HOME, atol=1e-6) | np.isclose(lam, X0_AWAY, atol=1e-6)
    return bool(at_x0.all())


def _stamp(row, col, default=None):
    v = row.get(col, default) if hasattr(row, "get") else getattr(row, col, default)
    return default if v is None or (isinstance(v, float) and np.isnan(v)) else v


def breakdown(row, step_rows=None):
    """Level 1 on one (element, gw) row of the frame. Returns a dict; `lines` are the
    nine terms in descending |points|; `fixture` is the tenth line; `summary` is the
    one sentence the agent quotes; `reconciles` False makes it a FINDING."""
    pos = str(row["position"])
    mf = _f(row, "minutes_frac")
    p60p, ppa, pst, p60 = _f(row, "p_60plus"), _f(row, "p_play_any"), _f(row, "p_start"), _f(row, "p60")
    fs = _f(row, "fixture_scale_cal")
    tl, ol = _f(row, "team_lambda"), _f(row, "opp_lambda")
    bonus_mode = str(_stamp(row, "bonus_mode", "unknown"))
    pen_fix = bool(_stamp(row, "penalty_fix_active", False))
    gamma = _f(row, "fixture_scale_gamma", 1.0)
    topend = bool(_stamp(row, "topend_cal_active", False))
    step = int(_f(row, "horizon_step", 0)) if _f(row, "horizon_step", 0) == _f(row, "horizon_step", 0) else 0
    n_fix = int(_f(row, "n_fixtures", 1)) if _f(row, "n_fixtures", 1) == _f(row, "n_fixtures", 1) else 1
    prior = _no_understat(row)
    degenerate = step_is_degenerate(step_rows)
    neutral = _close(tl, LEAGUE_AVG_LAMBDA, 1e-9) and _close(ol, LEAGUE_AVG_LAMBDA, 1e-9)
    runaway = (tl == tl and (tl < LAMBDA_MIN or tl > LAMBDA_MAX)) or (ol == ol and (ol < LAMBDA_MIN or ol > LAMBDA_MAX))

    lines = []

    def add(term, col, formula, inputs, source, constant=None, notes=()):
        lines.append({"term": term, "points": round(_f(row, col, 0.0), 4), "formula": formula,
                      "inputs": {k: (round(v, 4) if isinstance(v, float) and v == v else v) for k, v in inputs.items()},
                      "source": source, "constant": constant, "notes": list(notes)})

    # appearance
    add("appearance", "pts_appear",
        f"P(60+) {p60p:.2f} x 2 + P(play <60) {max(ppa - p60p, 0):.2f} x 1",
        {"p_start": pst, "p60": p60, "p_60plus": p60p, "p_play_any": ppa},
        "model", None, [f"P(play <60) uses a flat {SUB_CHANCE:.2f} for the sub chance ({CONSTANT_LABELS['sub_chance']})"])
    # goals (+ penalties sub-line)
    e_goals, npxg, pen = _f(row, "e_goals"), _f(row, "npxg90"), _f(row, "e_pen_goals", 0.0)
    gpts = GOAL_PTS.get(pos, 0)
    g_src, g_const = ("constant", CONSTANT_LABELS["position_prior"]) if prior else ("model", None)
    g_notes = [f"x {gpts} pts ({pos})"]
    if prior:
        g_notes.append("no Understat record: the rate is the position prior" + (" (goalkeepers receive the DEF prior)" if pos == "GK" else ""))
    if not topend or _close(gamma, 1.0):
        g_notes.append(f"fixture scale is {CONSTANT_LABELS['linear_scale']} in team strength (gamma {gamma:g})")
    add("goals", "pts_goals",
        f"e_goals {e_goals:.3f} (npxG/90 {npxg:.2f} x {mf:.2f} of 90 min x fixture {fs:.2f} + pens {pen:.3f}) x {gpts} pts",
        {"e_goals": e_goals, "npxg90": npxg, "minutes_frac": mf, "fixture_scale_cal": fs, "e_pen_goals": pen},
        g_src, g_const, g_notes)
    pen_share, tpr = _f(row, "penalty_share"), _f(row, "team_pen_rate")
    pen_pts = pen * gpts if pen == pen else 0.0
    pen_notes = []
    if not pen_fix:
        pen_notes.append("the penalty term is ~50x undersized (team_pen_rate is built from penalties MISSED; KNOWN_ISSUES #19)")
    lines[-1]["penalties"] = {"points": round(pen_pts, 4),
                              "formula": (f"penalty_share {pen_share:.3f} x team_pen_rate {tpr:.3f} x {mf:.2f} min x {gpts} pts" if not pen_fix
                                          else f"penalty_share {pen_share:.3f} x {mf:.2f} min x {gpts} pts"),
                              "inputs": {"penalty_share": round(pen_share, 4), "team_pen_rate": round(tpr, 4)},
                              "source": "constant" if _close(pen_share, PEN_FALLBACK, 1e-9) else "model",
                              "constant": CONSTANT_LABELS["pen_fallback"] if _close(pen_share, PEN_FALLBACK, 1e-9) else None,
                              "notes": pen_notes}
    # assists
    e_ast, xa = _f(row, "e_assists"), _f(row, "xa90")
    add("assists", "pts_assists", f"e_assists {e_ast:.3f} (xA/90 {xa:.2f} x {mf:.2f} of 90 min x fixture {fs:.2f}) x 3 pts",
        {"e_assists": e_ast, "xa90": xa, "minutes_frac": mf, "fixture_scale_cal": fs},
        g_src, g_const, (["no Understat record: the rate is the position prior"] if prior else []))
    # clean sheet
    pcs, cspts = _f(row, "p_cs"), CS_PTS.get(pos, 0)
    if cspts == 0:
        add("clean_sheet", "pts_cs", f"{pos}: 0 pts", {"p_cs": pcs}, "rule")
    else:
        add("clean_sheet", "pts_cs", f"p_cs {pcs:.3f} x {cspts} pts x P(60+) {p60p:.2f}",
            {"p_cs": pcs, "p_60plus": p60p}, "model", None, [])
    # defensive contribution
    pdc = _f(row, "p_dc_hit")
    if pos == "GK":
        add("defensive_contribution", "pts_dc", "GK: excluded", {"p_dc_hit": pdc}, "rule")
    elif pos == "FWD" and _close(pdc, FWD_BASE_RATE, 1e-9):
        add("defensive_contribution", "pts_dc", f"p_dc_hit {pdc:.3f} x 2 x {mf:.2f} min", {"p_dc_hit": pdc, "minutes_frac": mf},
            "constant", CONSTANT_LABELS["dc_fwd"], ["no forward model; 0.4% hit rate"])
    elif pos in DC_BASE and _close(pdc, DC_BASE[pos], 1e-9):
        add("defensive_contribution", "pts_dc", f"p_dc_hit {pdc:.3f} x 2 x {mf:.2f} min", {"p_dc_hit": pdc, "minutes_frac": mf},
            "constant", CONSTANT_LABELS["dc_positional"], ["no model row for this player"])
    else:
        add("defensive_contribution", "pts_dc", f"p_dc_hit {pdc:.3f} x 2 x {mf:.2f} min", {"p_dc_hit": pdc, "minutes_frac": mf}, "model")
    # saves
    s90 = _f(row, "saves_per_90")
    if pos != "GK":
        add("saves", "pts_saves", "not a GK", {}, "rule")
    else:
        add("saves", "pts_saves", f"E[floor(S/3)], S ~ Poisson(saves/90 {s90:.2f} x {mf:.2f} min)", {"saves_per_90": s90, "minutes_frac": mf},
            "model", None, ["may be the 0.3 x position-mean fallback where the keeper has no rolling history (not marked per row)"])
    # goals conceded
    if pos not in ("GK", "DEF"):
        add("goals_conceded", "pts_conceded", "not GK/DEF", {}, "rule")
    else:
        add("goals_conceded", "pts_conceded", f"-E[floor(C/2)], C ~ Poisson(opp lambda {ol:.3f} x {mf:.2f} min)",
            {"opp_lambda": ol, "minutes_frac": mf}, "model")
    # cards
    y90, r90 = _f(row, "yellow_per_90"), _f(row, "red_per_90")
    add("cards", "pts_cards", f"-(yellow {y90:.3f}/90 x 1 + red {r90:.3f}/90 x 3) x {mf:.2f} min",
        {"yellow_per_90": y90, "red_per_90": r90, "minutes_frac": mf}, "constant", CONSTANT_LABELS["card_rates"],
        ["no player card model"])
    # bonus
    if bonus_mode == "delete":
        add("bonus", "exp_bonus", "bonus_mode = delete", {"bonus_mode": bonus_mode}, "constant", CONSTANT_LABELS["bonus_off"],
            ["the bonus model is switched off; ~0.3 pts/week understated on average"])
    else:
        add("bonus", "exp_bonus", f"exp_bonus (bonus_mode = {bonus_mode})", {"bonus_mode": bonus_mode}, "model")

    # the fixture line
    fx_notes = []
    if degenerate:
        fx_src, fx_const = "constant", CONSTANT_LABELS["x0_fixture"]
        fx_notes.append("every club at this step sits at the fit's starting point (home e^0.25 / away 1.0): home/away only, no team strength (Logs/dc_degenerate_fit_finding_2026-09-13.md)")
    elif neutral:
        fx_src, fx_const = "constant", CONSTANT_LABELS["neutral_fixture"]
        fx_notes.append("no fixture match in the Dixon-Coles join: both lambdas at the neutral fill 1.40")
    else:
        fx_src, fx_const = "model", None
    if runaway:
        fx_notes.append(f"a strength parameter ran off (lambda outside [{LAMBDA_MIN}, {LAMBDA_MAX}]): a club with no history and a one-sided record -- KNOWN_ISSUES #25")
    if step >= 1 and int(_f(row, "odds_horizon_gws", 0) or 0) == 0 and not degenerate:
        fx_notes.append("beyond the deadline gameweek the fixture uses the fitted Dixon-Coles strengths, not the market")
    if n_fix > 1:
        fx_notes.append(f"double gameweek: {n_fix} fixtures -- additive terms are summed, the rates shown are fixture averages")
    fixture = {"team_lambda": round(tl, 4) if tl == tl else None, "opp_lambda": round(ol, 4) if ol == ol else None,
               "fixture_scale_cal": round(fs, 4) if fs == fs else None, "n_fixtures": n_fix,
               "source": fx_src, "constant": fx_const, "notes": fx_notes}

    lines.sort(key=lambda l: -abs(l["points"]))
    rec = reconcile(row)
    consts = [(l["term"], l["constant"]) for l in lines if l["source"] == "constant"]
    known = ["appearance carries a flat 0.30 sub chance"]
    if lines and any(l["term"] == "goals" and l.get("penalties", {}).get("source") == "constant" for l in lines):
        consts.append(("penalties", CONSTANT_LABELS["pen_fallback"]))
    summary = (f"{len(consts)} of 9 lines are constants standing in for models ("
               + "; ".join(f"{t.replace('_', ' ')}: {c}" for t, c in consts) + ") -- the rest are model outputs under FPL's rules; "
               + " and ".join(known)
               + (f"; the fixture strength at this step is {fx_const}" if fx_const else "")
               + (" -- and a strength parameter ran off (KNOWN_ISSUES #25)" if runaway else "") + ".")
    name = str(row.get("name", row.get("element")) if hasattr(row, "get") else getattr(row, "name", ""))
    out = {"player_id": int(_f(row, "element")), "name": name, "position": pos, "team": str(row["team"]),
           "gw": int(_f(row, "gw")), "horizon_step": step, "total_e_points": round(_f(row, "e_points"), 4),
           "lines": lines, "fixture": fixture, "summary": summary, **rec}
    if not rec["reconciles"]:
        out["finding"] = (f"the row does NOT reconcile: eight terms - e_points_core = {rec['residual_core']:.6f}, "
                          f"core + bonus - e_points = {rec['residual_total']:.6f} (tolerance {TOL}); this is a defect in the "
                          "frame, not rounding -- report it, do not answer the breakdown as if it were sound")
    out["rendered"] = render(out)
    return out


def render(bd):
    hdr = (f"{bd['name']} ({bd['position']}, {bd['team']}) -- GW{bd['gw']}: {bd['total_e_points']:.2f} expected points"
           f"   [reconciles: {'yes' if bd['reconciles'] else 'NO'}, residual {bd['residual_core']:+.4f}]")
    rows = [hdr]
    for l in bd["lines"]:
        tag = l["source"] + (f": {l['constant']}" if l["constant"] else "")
        rows.append(f"  {l['term'].replace('_', ' '):<22s} {l['points']:+6.2f}   {l['formula']:<70s} {tag}")
        if l["term"] == "goals" and "penalties" in l:
            p = l["penalties"]
            ptag = p["source"] + (f": {p['constant']}" if p["constant"] else "")
            rows.append(f"    of which penalties {p['points']:+6.2f}   {p['formula']:<66s} {ptag}")
    fx = bd["fixture"]
    ftag = fx["source"] + (f": {fx['constant']}" if fx["constant"] else "")
    rows.append(f"  fixture: team lambda {fx['team_lambda']} / opp lambda {fx['opp_lambda']} (scale {fx['fixture_scale_cal']}) -- {ftag}")
    rows.append(bd["summary"])
    return "\n".join(rows)


def compare(a, b, label_a=None, label_b=None):
    """Level 2: two breakdowns on the same gameweek. Per-term difference a - b, ranked by
    |difference|; the terms accounting for >= 80% of the absolute gap; a flag where a
    term is a constant on one side and a model value on the other. label_a / label_b
    name the sides in the rendering (default: the players' names; a run-to-run comparison
    of ONE player passes "run 7" / "run 9")."""
    if a["gw"] != b["gw"]:
        raise ValueError(f"compare needs the same gameweek: GW{a['gw']} vs GW{b['gw']}")
    name_a, name_b = label_a or a["name"], label_b or b["name"]
    a = dict(a, name=name_a); b = dict(b, name=name_b)
    la = {l["term"]: l for l in a["lines"]}; lb = {l["term"]: l for l in b["lines"]}
    terms = []
    for t, _ in TERMS:
        x, y = la[t], lb[t]
        d = x["points"] - y["points"]
        flag = None
        if x["source"] != y["source"] and "constant" in (x["source"], y["source"]) and abs(d) > 1e-9:
            side = a["name"] if x["source"] == "constant" else b["name"]
            const = x["constant"] if x["source"] == "constant" else y["constant"]
            flag = f"the whole {t.replace('_', ' ')} gap is a {const} ({side}) vs a model value"
        terms.append({"term": t, "a": x["points"], "b": y["points"], "diff": round(d, 4),
                      "source_a": x["source"], "source_b": y["source"], "flag": flag})
    gap = round(a["total_e_points"] - b["total_e_points"], 4)
    ranked = sorted(terms, key=lambda r: -abs(r["diff"]))
    tot = sum(abs(r["diff"]) for r in ranked) or 1.0
    acc, lead = 0.0, []
    for r in ranked:
        if abs(r["diff"]) <= 1e-9:
            break
        lead.append(r); acc += abs(r["diff"])
        if acc / tot >= 0.80:
            break
    shares = [f"{r['term'].replace('_', ' ')} {100 * abs(r['diff']) / tot:.0f}%" for r in lead]
    sentence = (f"{a['name']} {a['total_e_points']:.2f} vs {b['name']} {b['total_e_points']:.2f} (gap {gap:+.2f}): "
                + (", ".join(shares) + " of the absolute gap." if lead else "no term differs."))
    flags = [r["flag"] for r in terms if r["flag"]]
    fa, fb = a["fixture"], b["fixture"]
    if fa["source"] == "constant" and fb["source"] == "constant":
        flags.append(f"both fixtures are {fa['constant']}: the goals/assists gap is minutes and rates plus home/away, not opponent quality")
    elif "constant" in (fa["source"], fb["source"]):
        flags.append(f"one fixture is a constant ({fa['constant'] or fb['constant']}) and the other a model value")
    out = {"gw": a["gw"], "a": {"player_id": a["player_id"], "name": a["name"], "total_e_points": a["total_e_points"]},
           "b": {"player_id": b["player_id"], "name": b["name"], "total_e_points": b["total_e_points"]},
           "gap": gap, "terms": ranked, "sentence": sentence, "flags": flags,
           "reconciles": bool(a["reconciles"] and b["reconciles"])}
    rows = [f"{'term':<22s} {a['name'][:14]:>14s} {b['name'][:14]:>14s} {'diff':>7s}"]
    for r in ranked:
        rows.append(f"{r['term'].replace('_', ' '):<22s} {r['a']:>+14.2f} {r['b']:>+14.2f} {r['diff']:>+7.2f}" + (f"   {r['flag']}" if r["flag"] else ""))
    rows.append(sentence)
    rows.extend(flags)
    out["rendered"] = "\n".join(rows)
    return out
