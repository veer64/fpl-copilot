"""league_table.py -- the league table AS-OF a cutoff, from results already on the volume.

WHAT IT IS. Position, points, played/won/drawn/lost, goals, per-game rates, form, home/away
splits, streaks and Bet365's odds-implied expected points for the matches already played --
per club, as of a cutoff. No new upstream, no new credential: the scores and the prices are
the odds archive the Dixon-Coles fit reads, the gameweek labels are the stack + forward
skeleton the walk-forward reads.

THE ONE RULE (FEATURE_IDEAS "league table and team form as a tool"; KNOWN_ISSUES #25). A
result may count only if the match FINISHED before the cutoff DAY began. That rule has ONE
definition, dixon_coles.knowable_before, and it is applied in model_tools.get_league_table --
NOT here. This module receives rows the rule has already admitted and carries no date
comparison of any kind; Tests/test_league_table.py asserts that against the source. Two
independently written copies of that comparison once drifted -- one leaked, one fitted a
degenerate model -- and a table that quietly counts the cutoff day's matches would be the
same bug wearing a new hat.

PURE, like explain.py, quantiles.py and fixtures_tool.py: nothing of the model stack is
imported, so the API process can answer a standings question without loading the model. The
name bridge comes from team_map.py (the literal that used to live in assembly.py, which
imports the whole stack).

GAMEWEEK LABELS come from pairing the two SIDES of the same fixture id in the calendar --
never from a date window, never from matching anything numeric. They only LABEL: the
table's arithmetic never depends on them, so an unpaired fixture degrades to gw null with a
count, not to a dropped match. Doubles are a list per (club, gameweek); drop_duplicates on
(team, gw) would hide the second leg (the get_fixtures bug, 2026-09-19).

ODDS-EXPECTED POINTS are Bet365's pre-match pricing, normalised for the overround per match
(the raw overround travels with every number so the normalisation is visible), 3*p_win +
1*p_draw, summed over the club's COUNTED matches. A match without a price is excluded and
`xpts_matches_counted` says so; `xpts_diff` compares points over the same counted matches,
because a partial expectation against a full points total is exactly the masquerade the
count exists to prevent. Descriptive of past matches only -- never a forecast, never
extrapolated, never ours.
"""
import pandas as pd

from team_map import TEAM_MAP, fpl_name   # noqa: F401  (TEAM_MAP re-exported for callers/tests)

FORM_DIRECTION = "most recent LAST -- the string reads oldest to newest, left to right"
TIEBREAK = ("points, then goal difference, then goals for, then club name; the official rule's "
            "later head-to-head steps are not applied")
MAX_FORM_N = 38
POINTS = {"W": 3, "D": 1, "L": 0}
STAT_KEYS = ("played", "won", "drawn", "lost", "gf", "ga", "gd", "points")

ODDS_METHOD = ("per match: p_i = (1/odds_i) / sum_j(1/odds_j) over home/draw/away, the divisor "
               "being the raw overround (reported unnormalised as `overround`); xpts = 3*p_win + "
               "1*p_draw; summed over the club's COUNTED matches only, never imputed for a match "
               "without a price")
BET365_ATTRIBUTION = ("Bet365's pre-match prices (football-data.co.uk's B365H/B365D/B365A "
                      "columns), normalised for the overround. The bookmaker's implied "
                      "expectation for matches ALREADY PLAYED -- Bet365's number, not this "
                      "model's and not ours.")
ODDS_NOT_A_FORECAST = ("descriptive of past matches only: this is not a forecast of any future "
                       "result, must never be extended forward, and says nothing about value -- "
                       "the same boundary as get_price_movements")
NO_MATCHES_REASON = ("no match with a result before the cutoff day: under the as-of rule a result "
                     "counts only if the match finished before the cutoff DAY began, so this club "
                     "has no knowable result yet. Null, not zero -- it is not bottom of the table.")
NULL_KEYS = STAT_KEYS + ("ppg", "gf_per_game", "ga_per_game", "form_string", "form_n",
                         "form_points", "form_gf", "form_ga", "home", "away", "unbeaten_run",
                         "winless_run", "clean_sheets", "games_failed_to_score", "one_goal_games")
ODDS_KEYS = ("odds_xpts", "xpts_matches_counted", "xpts_complete", "xpts_points_basis",
             "xpts_diff", "mean_overround", "xpts_note")


# ------------------------------------------------------------------ odds

def implied_probabilities(h, d, a):
    """Overround-normalised win/draw/loss probabilities from three decimal prices, or None.

    None whenever any price is missing, non-numeric, NaN or not above 1.0 -- a decimal price
    at or below 1.0 is corrupt (it would imply a probability of one or more). Never imputed:
    the caller excludes the match and counts the exclusion.
    """
    vals = []
    for x in (h, d, a):
        try:
            v = float(x)
        except (TypeError, ValueError):
            return None
        if v != v or v <= 1.0:
            return None
        vals.append(v)
    raw = [1.0 / v for v in vals]
    s = sum(raw)
    return {"p_home": raw[0] / s, "p_draw": raw[1] / s, "p_away": raw[2] / s, "overround": s}


def match_xpts(p_win, p_draw):
    return 3.0 * p_win + 1.0 * p_draw


def odds_attribution(provenance):
    """WHO priced the matches -- read from the odds pull's provenance sidecar, never assumed
    from the column name.

    The archive's price columns are named B365H/B365D/B365A for every season. For the
    football-data seasons they are Bet365's prices (overround about 1.05). For a LIVE season
    the odds pull writes a de-margined multi-book consensus into the same columns
    (odds_live_pull_<season>.provenance.json: `construction`, `panel`, `source_note` -- for
    2026-27 a twelve-book panel that does not include Bet365, overround 1.0000). Calling that
    "Bet365" would be a false attribution, so the label comes from the sidecar when one
    exists. Measured 2026-09-19, and the reported overround shows the reader which it is.
    """
    if provenance:
        construction = str(provenance.get("construction") or "a multi-book consensus")
        panel = provenance.get("panel") or []
        note = str(provenance.get("source_note") or "")
        pulled = provenance.get("pulled_at")
        who = construction + (f" of {len(panel)} books" if panel else "") + (f" ({note})" if note else "")
        return {
            "source_kind": "consensus",
            "attribution": (f"the market's pre-match prices as this project's odds pull stored "
                            f"them: {who}. The archive's columns are named B365H/D/A for every "
                            f"season, but for this season they hold that consensus and NOT "
                            f"Bet365's prices" + (f"; pulled {pulled}" if pulled else "")
                            + ". The market's number, not this model's and not ours."),
            "method": ODDS_METHOD + (" For a de-margined source the normalisation changes "
                                     "nothing, and the reported overround of about 1.0 shows that."),
            "not_a_forecast": ODDS_NOT_A_FORECAST,
        }
    return {"source_kind": "bet365", "attribution": BET365_ATTRIBUTION, "method": ODDS_METHOD,
            "not_a_forecast": ODDS_NOT_A_FORECAST}


# ------------------------------------------------------------------ the cutoff and the calendar

def parse_as_of(as_of):
    """(naive UTC Timestamp, None) or (None, reason). A tz-aware input is converted to UTC and
    stripped, so it compares with the archive's naive dates the way the walk-forward's cutoff
    does (tz_localize(None))."""
    try:
        ts = pd.Timestamp(as_of)
    except (ValueError, TypeError) as e:
        return None, f"as_of {as_of!r} is not a timestamp I can read ({type(e).__name__}: {e})"
    if pd.isna(ts):
        return None, f"as_of {as_of!r} is not a timestamp I can read"
    if ts.tzinfo is not None:
        ts = ts.tz_convert("UTC").tz_localize(None)
    return ts, None


def first_kickoff_by_gw(cal):
    """{gw: first kickoff, tz-naive} -- the walk-forward's derivation of cutoff_date, verbatim:
    eval/walkforward_season.py does v.groupby("GW")["kick"].min() and .tz_localize(None).
    Tests/test_league_table.py pins the two equal on the real 2026-27 calendar."""
    if cal is None or len(cal) == 0:
        return {}
    kick = pd.to_datetime(cal["kickoff_time"])
    starts = kick.groupby(cal["GW"]).min().sort_index()
    out = {}
    for g, t in starts.items():
        if pd.isna(t):
            continue
        out[int(g)] = t.tz_localize(None) if t.tzinfo is not None else t
    return out


def gameweek_index(cal):
    """{(home, away): [(gw, kickoff), ...]} by pairing the two SIDES of each fixture id.

    The stack carries each fixture twice, once per club, with `team` (the club's own FPL name),
    `was_home` and `fixture`. Joining home side to away side on the id names both clubs with
    no opponent-id resolution and no date arithmetic. A fixture id with anything but exactly
    one home and one away side is left unpaired. {} when there is no calendar.
    """
    need = {"fixture", "team", "was_home", "GW", "kickoff_time"}
    if cal is None or len(cal) == 0 or not need <= set(cal.columns):
        return {}
    sides = (cal.dropna(subset=["fixture", "team"])
                .drop_duplicates(["fixture", "team", "was_home"])
                [["fixture", "team", "was_home", "GW", "kickoff_time"]])
    is_home = sides["was_home"].astype(bool)
    j = sides[is_home].merge(sides[~is_home], on="fixture", suffixes=("_h", "_a"))
    per_fixture = j.groupby("fixture").size()
    j = j[j["fixture"].map(per_fixture) == 1]
    idx = {}
    for r in j.itertuples(index=False):
        idx.setdefault((str(r.team_h), str(r.team_a)), []).append(
            (int(r.GW_h), str(r.kickoff_time_h)))
    return idx


def label_matches(matches, index):
    """(matches with an FPL-spelled `home`/`away` and a `gw` column, n_unmapped). A pair the
    calendar cannot name exactly once gets gw None and is counted, never dropped."""
    m = matches.copy()
    m["home"] = m["home"].map(fpl_name)
    m["away"] = m["away"].map(fpl_name)
    gws, unmapped = [], 0
    for h, a in zip(m["home"], m["away"]):
        hits = index.get((h, a), [])
        if len(hits) == 1:
            gws.append(int(hits[0][0]))
        else:
            gws.append(None)
            unmapped += 1
    m["gw"] = pd.Series(gws, index=m.index, dtype="object")
    return m, unmapped


# ------------------------------------------------------------------ the arithmetic

LONG_COLS = ["club", "opponent", "venue", "date", "gw", "home", "away", "gf", "ga", "result",
             "points", "odds_present", "p_win", "p_draw", "p_loss", "overround", "xpts"]


def long_form(known):
    """One row per (club, match) from the admitted matches -- both clubs' views of each."""
    rows = []
    for r in known.itertuples(index=False):
        hg, ag = int(r.home_goals), int(r.away_goals)
        p = implied_probabilities(r.b365h, r.b365d, r.b365a)
        gw = None if r.gw is None or r.gw != r.gw else int(r.gw)
        for club, opp, venue, gf, ga, pw, pl in (
                (r.home, r.away, "H", hg, ag, p and p["p_home"], p and p["p_away"]),
                (r.away, r.home, "A", ag, hg, p and p["p_away"], p and p["p_home"])):
            res = "W" if gf > ga else ("L" if gf < ga else "D")
            rows.append({
                "club": club, "opponent": opp, "venue": venue, "date": r.date_parsed, "gw": gw,
                "home": r.home, "away": r.away, "gf": gf, "ga": ga, "result": res,
                "points": POINTS[res], "odds_present": p is not None,
                "p_win": pw if p else None, "p_draw": p["p_draw"] if p else None,
                "p_loss": pl if p else None, "overround": p["overround"] if p else None,
                "xpts": match_xpts(pw, p["p_draw"]) if p else None,
            })
    return pd.DataFrame(rows, columns=LONG_COLS)


def _split(g):
    won, drawn, lost = (int((g["result"] == k).sum()) for k in ("W", "D", "L"))
    gf, ga = int(g["gf"].sum()), int(g["ga"].sum())
    return {"played": int(len(g)), "won": won, "drawn": drawn, "lost": lost,
            "gf": gf, "ga": ga, "gd": gf - ga, "points": int(g["points"].sum())}


def _run(results, ends_on):
    """Consecutive results from the most recent backwards that are not `ends_on`."""
    n = 0
    for r in reversed(results):
        if r == ends_on:
            break
        n += 1
    return n


def _odds_block(g, played):
    c = g[g["odds_present"]]
    n = int(len(c))
    out = {"xpts_matches_counted": n, "xpts_complete": n == played}
    if n:
        xpts = float(c["xpts"].sum())
        basis = int(c["points"].sum())
        out.update({"odds_xpts": round(xpts, 4), "xpts_points_basis": basis,
                    "xpts_diff": round(basis - xpts, 4),
                    "mean_overround": round(float(c["overround"].mean()), 4)})
    else:
        out.update({"odds_xpts": None, "xpts_points_basis": None, "xpts_diff": None,
                    "mean_overround": None})
    out["xpts_note"] = (f"{n} of {played} matches counted"
                        + ("" if n == played else " (the rest carry no price in the archive)")
                        + "; xpts_diff = points in the counted matches (xpts_points_basis) minus "
                          "odds_xpts, never points over all matches minus a partial sum")
    return out


def club_row(club, g, form_last_n, include_odds):
    g = g.sort_values("date", kind="stable")
    row = {"position": None, "team": club, "no_matches": False, **_split(g)}
    played = row["played"]
    row["ppg"] = round(row["points"] / played, 3)
    row["gf_per_game"] = round(row["gf"] / played, 3)
    row["ga_per_game"] = round(row["ga"] / played, 3)
    last = g.tail(form_last_n)
    row["form_string"] = "".join(last["result"])
    row["form_n"] = int(len(last))
    row["form_points"] = int(last["points"].sum())
    row["form_gf"] = int(last["gf"].sum())
    row["form_ga"] = int(last["ga"].sum())
    row["home"] = _split(g[g["venue"] == "H"])
    row["away"] = _split(g[g["venue"] == "A"])
    results = list(g["result"])
    row["unbeaten_run"] = _run(results, "L")
    row["winless_run"] = _run(results, "W")
    row["clean_sheets"] = int((g["ga"] == 0).sum())
    row["games_failed_to_score"] = int((g["gf"] == 0).sum())
    row["one_goal_games"] = int(((g["gf"] - g["ga"]).abs() == 1).sum())
    if include_odds:
        row.update(_odds_block(g, played))
    return row


def null_row(club, include_odds):
    row = {"position": None, "team": club, "no_matches": True, "reason": NO_MATCHES_REASON}
    row.update({k: None for k in NULL_KEYS})
    if include_odds:
        row.update({k: None for k in ODDS_KEYS})
    return row


def table(long, clubs, form_last_n, include_odds):
    """Ranked rows for every club in `clubs`; a club with no admitted match is a null row with a
    reason, listed after the ranked ones with position None -- never a fabricated 0-0-0."""
    rows = []
    for club in clubs:
        g = long[long["club"] == club]
        rows.append(club_row(club, g, form_last_n, include_odds) if len(g)
                    else null_row(club, include_odds))
    ranked = sorted((r for r in rows if not r["no_matches"]),
                    key=lambda r: (-r["points"], -r["gd"], -r["gf"], r["team"]))
    for i, r in enumerate(ranked, 1):
        r["position"] = i
    return ranked + [r for r in rows if r["no_matches"]]


def form_detail(long, club, position, include_odds, attribution=None):
    """That club's admitted matches, oldest first, grouped by gameweek label -- a LIST per
    gameweek so a double shows both legs. Unlabelled matches group under gw None."""
    g = long[long["club"] == club].sort_values("date", kind="stable")
    groups = {}
    for r in g.itertuples(index=False):
        m = {"gw": r.gw, "date": f"{r.date:%Y-%m-%d}", "opponent": r.opponent,
             "venue": r.venue, "score": f"{r.gf}-{r.ga}", "gf": r.gf, "ga": r.ga,
             "result": r.result, "points": r.points}
        if include_odds:
            m["odds"] = None if not r.odds_present else {
                "p_win": round(float(r.p_win), 4), "p_draw": round(float(r.p_draw), 4),
                "p_loss": round(float(r.p_loss), 4), "overround": round(float(r.overround), 4),
                "xpts": round(float(r.xpts), 4)}
        groups.setdefault(r.gw, []).append(m)
    out = {"team": club, "position": position,
           "results_by_gw": [{"gw": gw, "n_matches": len(ms), "double_gameweek": len(ms) > 1,
                              "matches": ms} for gw, ms in groups.items()],
           "form_direction": FORM_DIRECTION}
    if include_odds:
        out["odds_attribution"] = (attribution or odds_attribution(None))["attribution"]
    return out


def missing_list(missing):
    return [{"date": f"{r.date_parsed:%Y-%m-%d}", "home": r.home, "away": r.away,
             "gw": (None if r.gw is None or r.gw != r.gw else int(r.gw))}
            for r in missing.itertuples(index=False)]
