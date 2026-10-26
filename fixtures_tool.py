"""fixtures_tool.py -- the fixture calendar and its difficulty, from OUR model.

WHY NOT FDR. FPL's fixture-difficulty rating is ONE number per fixture. Our model has two
and they routinely disagree: a fixture can be a good place to attack and a bad place to keep
a clean sheet, and the single number cannot say so. Collapsing them would throw away the one
thing this model has that theirs does not (master plan 5.4).

PURE, like explain.py and quantiles.py: no part of the model stack is imported, so the API
process can answer a fixture question without loading the model. In particular it does NOT
call dixon_coles.get_fixtures, which REFITS Dixon-Coles -- that is the model path and it is
not something a chat turn may trigger.

WHERE THE DATA IS (verified on the server 2026-09-19, not assumed):
  * the calendar   data/history/forward_skeleton_2026_27.parquet -- GW5..38, 659 elements per
                   gameweek, with opponent_team (an FPL team id), was_home and kickoff_time
                   non-null for every FUTURE gameweek. Written by the WEEKLY INGEST, so it is
                   up to a week old; its age is stamped on every answer.
  * the team names bootstrap_raw's teams block: 20 ids, and the map was checked end to end --
                   zero unmapped opponents, name sets identical to the skeleton's, and every
                   fixture self-pairs. No TEAM_MAP bridging is needed; that is only for the
                   football-data archive, whose spellings differ (Man United / Tottenham).
  * the lambdas    model_predictions, constant within (team, gameweek). Read from the SAME
                   run the prediction tools read, so a fixture and a prediction quoted in one
                   answer can never come from different builds.

THE LAMBDAS ARE PRODUCTS, AND SAYING OTHERWISE WOULD BE A SUBTLER FDR ERROR. team_lambda is
attack_ours x defence_theirs x home_advantage -- the expected goals in THIS fixture, not the
opponent's defensive rating. The factors exist only inside the fit. So comparing one team's
fixtures across gameweeks is valid, and comparing "how good is that defence" across different
teams' fixtures conflates the attacker. Every answer says so.

NEVER INFER THE OPPONENT FROM MATCHING LAMBDAS. Measured: 0 collisions across gw5-10 today, so
it would appear to work. It fails exactly when the fit is degenerate and every club sits at the
starting point -- which is when a reader most needs the fixture list. The opponent comes from
the calendar or it is not named.
"""
import gzip
import json
from pathlib import Path

import pandas as pd

from explain import LEAGUE_AVG_LAMBDA, fixture_provenance, market_priced, runaway_side

REPO = Path(__file__).resolve().parent
SKELETON = REPO / "data" / "history" / "forward_skeleton_2026_27.parquet"
BOOTSTRAP_DIR = REPO / "data" / "live" / "bootstrap_raw" / "2026-27"

SKELETON_COLS = ["element", "GW", "team", "opponent_team", "was_home", "kickoff_time"]
MAX_HORIZON = 10


def _team_names():
    """FPL team id -> name, from the most recent bootstrap snapshot. Returns {} if it cannot
    tell, and the caller then declines to name opponents rather than guessing at them."""
    try:
        snaps = sorted(BOOTSTRAP_DIR.glob("*.json.gz"))
        if not snaps:
            return {}
        with gzip.open(snaps[-1], "rt", encoding="utf-8") as fh:
            teams = json.load(fh).get("teams") or []
        return {int(t["id"]): str(t["name"]) for t in teams if "id" in t and "name" in t}
    except Exception:                                   # noqa: BLE001 -- a read must not die here
        return {}


def calendar(path=None, df=None):
    """(team, gw) -> the fixtures that team plays that gameweek, as a list.

    A LIST, not a row. drop_duplicates(["team","GW"]) would silently drop the second leg of a
    double gameweek, and a fixture tool that hides half a double is worse than no fixture tool.
    A team with no fixture that gameweek is simply absent, and the caller reports a blank.
    """
    if df is None:
        df = pd.read_parquet(Path(path) if path else SKELETON, columns=SKELETON_COLS)
    names = _team_names()
    # One row per (team, gw, fixture) -- the 659 elements per gameweek are the same fixtures
    # repeated, so dedupe on the fixture identity (kickoff), never on (team, gw).
    fx = (df.drop_duplicates(["team", "GW", "kickoff_time", "opponent_team"])
            [["team", "GW", "opponent_team", "was_home", "kickoff_time"]]
            .sort_values(["GW", "team", "kickoff_time"]))
    fx["opponent"] = fx["opponent_team"].map(names) if names else None
    out = {}
    for r in fx.to_dict("records"):
        out.setdefault((str(r["team"]), int(r["GW"])), []).append({
            "opponent": r["opponent"],
            "opponent_id": int(r["opponent_team"]),
            "home": bool(r["was_home"]),
            "kickoff": str(r["kickoff_time"]),
        })
    return out, len(names)


SCORE_MEANING = ("1 (hardest) to 10 (easiest), by rank among every fixture the build has priced: a score of "
                 "k means the figure sits in the k-th tenth of all loaded fixtures. Two scores, never one.")


def _num(v):
    return None if v is None or v != v else float(v)


def rank_scores(values):
    """{key: score} -- each value's decile rank, 1 (lowest tenth) to 10 (highest tenth), among ALL the values
    given. Pure, and the one place the derivation lives (3d, 2026-10-08):

        pct   = (number of values strictly below v + half the number equal to v) / N
        score = 1 + floor(10 * pct)

    so the smallest value scores 1, the largest 10, equal values share a score, and the scale is
    RELATIVE to the loaded fixtures rather than fixed thresholds -- which is what replaced the old
    easy / average / hard bands (hard-coded cut points, B24). A None or NaN value gets None, and does
    not count towards N. With one value the score is 5: nothing to rank against."""
    nums = {k: _num(v) for k, v in values.items()}
    pool = sorted(v for v in nums.values() if v is not None)
    n = len(pool)
    out = {}
    for k, v in nums.items():
        if v is None:
            out[k] = None
            continue
        if n < 2:
            out[k] = 5
            continue
        below = sum(1 for x in pool if x < v)
        equal = sum(1 for x in pool if x == v)
        pct = (below + 0.5 * equal) / n
        out[k] = max(1, min(10, 1 + int(10 * pct)))
    return out


def fixture_scores(rows):
    """{(team, gw): {"attack": s, "defence": s}} for every per-(team, gameweek) model row: the attack score
    ranks team_lambda (higher is easier to score in), the defence score ranks p_cs (higher is easier to
    keep a clean sheet), each across ALL the rows given. Never combined."""
    keys = [(str(r["team"]), int(r["gw"])) for r in rows]
    att = rank_scores({k: r.get("team_lambda") for k, r in zip(keys, rows)})
    dfn = rank_scores({k: r.get("p_cs") for k, r in zip(keys, rows)})
    return {k: {"attack": att[k], "defence": dfn[k]} for k in keys}


def _difficulty(tl, ol, pcs, scores=None):
    """The two quantities, never one composite.

    attacking  -- how easy is it to SCORE here: our expected goals in this fixture.
    defensive  -- how easy is a CLEAN SHEET here: p_cs primarily, opp_lambda alongside.

    p_cs is the 0.2*DC + 0.8*market blend (CS_BLEND_W) and is what the model actually uses for
    the clean-sheet term, so it is the honest defensive number. It is NOT exp(-opp_lambda): at
    step 0 the two differ (sd 0.0211, max 0.0782), which is the coupling error the quantile
    work found. Both are reported so neither is hidden behind the other.

    `scores` is this fixture's {"attack", "defence"} from fixture_scores -- the 1-10 rank among all
    loaded fixtures that replaced the fixed easy / average / hard bands (3d, 2026-10-08).
    """
    scores = scores or {}
    return {
        "attacking": {
            "measure": "expected goals FOR this team in this fixture (team_lambda)",
            "value": None if tl is None or tl != tl else round(float(tl), 4),
            "score": scores.get("attack"),
            "score_meaning": SCORE_MEANING,
            "reading": "higher is EASIER to score in",
        },
        "defensive": {
            "measure": "clean-sheet probability (p_cs, the 0.2 DC / 0.8 market blend)",
            "value": None if pcs is None or pcs != pcs else round(float(pcs), 4),
            "opp_lambda": None if ol is None or ol != ol else round(float(ol), 4),
            "score": scores.get("defence"),
            "score_meaning": SCORE_MEANING,
            "reading": "higher is EASIER to keep a clean sheet",
            # Friday targeted fix F17 (2026-10-16): a team's clean-sheet chance was read as lifting a forward's floor
            "clean_sheet_points": ("FPL scoring: 4 points for goalkeepers and defenders, 1 point for midfielders, "
                                   "no clean-sheet points for forwards"),
            "note": ("the clean-sheet chance is not simply derived from the opponent's expected goals: at the "
                     "deadline gameweek the two differ (sd 0.0211, max 0.0782) because the chance blends the "
                     "team-strength estimate with the market, and the opponent's expected goals are pure market"),
        },
        "why_two_numbers": ("FPL's FDR is one number per fixture. These two disagree often -- a "
                            "fixture can be a good place to attack and a bad place to keep a "
                            "clean sheet -- and the disagreement is the information."),
        "these_are_products": ("team_lambda is attack_ours x defence_theirs x home_advantage, "
                               "the expected goals in THIS fixture -- NOT the opponent's "
                               "defensive rating. Comparing one team's fixtures across "
                               "gameweeks is valid; comparing defences across different teams' "
                               "fixtures conflates the attacker."),
    }


SCORE_PLAIN = ("a score of k means the fixture sits in the k-th tenth of every fixture the build priced: a score of 10 "
               "is not 'the easiest fixture' and 1 is not 'the hardest', each is one tenth of all fixtures; attack and "
               "defence are scored separately and never combined")
MATCH_LENGTH_H = 2


def fixture_status(kickoff, now):
    """'played' / 'in progress' / 'to come' for a kickoff ISO string against the clock (Part D G4: the agent
    called a match played the day before 'already underway'); None when either is missing."""
    if not kickoff or now is None:
        return None
    try:
        from datetime import datetime, timedelta, timezone
        k = datetime.fromisoformat(str(kickoff).replace("Z", "+00:00"))
        if k.tzinfo is None:
            k = k.replace(tzinfo=timezone.utc)
    except ValueError:
        return None
    if now < k:
        return "to come"
    if now < k + timedelta(hours=MATCH_LENGTH_H):
        return "in progress"
    return "played"


def kickoff_day(kickoff):
    """'Sunday 11 Oct 2026, 15:30 UTC' for a kickoff ISO string (Part D G4: the agent called 2026-10-11 'Saturday')."""
    if not kickoff:
        return None
    try:
        from datetime import datetime, timezone
        k = datetime.fromisoformat(str(kickoff).replace("Z", "+00:00"))
        if k.tzinfo is None:
            k = k.replace(tzinfo=timezone.utc)
        return k.astimezone(timezone.utc).strftime("%A %d %b %Y, %H:%M UTC")
    except ValueError:
        return None


def build(rows, cal, n_team_names, team=None, gw=None, horizon=5,
          step_rows_by_gw=None, skeleton_age_hours=None, now=None, results=None):
    """PURE. `rows` are the per-(team, gw) model rows; `cal` is calendar()'s mapping; `now` (optional)
    gives every fixture a status against the clock. With `now` and no `gw`, the listing is "the next
    `horizon` fixtures still to come" per club (kickoff after the clock; time batch, 2026-10-26); with a
    `gw` every fixture of that gameweek is kept and a kicked-off one is marked played, with its score when
    `results` ({(team, gw, kickoff): "Home 2-1 Away"}) holds it.

    A fixture beyond the model's horizon is RETURNED WITH difficulty None and a reason, never
    omitted and never given a fabricated number -- the same rule the quantile block uses for a
    run that did not compute them: a missing calculation must not read as an absence of risk.
    """
    by_key = {(str(r["team"]), int(r["gw"])): r for r in rows}
    scores = fixture_scores(rows)                   # ranked across EVERY loaded fixture, before any filter
    model_gws = sorted({int(r["gw"]) for r in rows})
    horizon = max(1, min(int(horizon), MAX_HORIZON))

    cal_gws = sorted({k[1] for k in cal})
    if gw is not None:
        # A gameweek the FILE does not cover is not a blank gameweek. Before 2026-10-04 every
        # one of them answered "no fixture for this team in this gameweek (a blank)", which
        # reads as "they are not playing" when the truth is that the calendar stops there --
        # the forward skeleton starts at the ingest's gameweek and ends at 38 (B21).
        if cal_gws and not (cal_gws[0] <= int(gw) <= cal_gws[-1]):
            covers = f"fixtures loaded cover GW{cal_gws[0]}-{cal_gws[-1]}"
            if 1 <= int(gw) < cal_gws[0]:
                # the same words get_prediction uses for a gameweek behind the run's horizon,
                # so one question asked of two tools does not get two different explanations
                err = (f"GW{int(gw)} has already been played; {covers}. For what happened, "
                       "ask for the player's actual points, or the team's score.")
                kind = "already_played"
            else:
                err = (f"GW{int(gw)} is not in the fixture calendar: {covers}. A gameweek "
                       "outside that is missing from the file, which is not the same as a "
                       "blank gameweek.")
                kind = "out_of_range"
            return {"error": err, "error_kind": kind,
                    "fixtures": [], "gameweeks": [int(gw)],
                    "calendar_covers": {"first_gw": cal_gws[0], "last_gw": cal_gws[-1]}}
        want_gws = [int(gw)]
    elif now is not None:
        # "next N / upcoming" (time batch, 2026-10-26): only fixtures with kickoff after the clock count, club by
        # club -- the listing holds each club's next `horizon` fixtures still to come, grouped by gameweek; a
        # kicked-off match is not among them (the 25 Oct gate listed Arsenal's played GW8 match under "next three").
        want_gws = None
    else:
        start = model_gws[0] if model_gws else min((k[1] for k in cal), default=1)
        want_gws = list(range(start, start + horizon))

    teams = sorted({k[0] for k in cal}) if team is None else [str(team)]
    unknown = [t for t in teams if not any(k[0] == t for k in cal)]

    out = []
    for t in teams:
        if want_gws is None:
            coming = sorted(((g, f) for (tt, g), fl in cal.items() if tt == t for f in fl
                             if fixture_status(f.get("kickoff"), now) == "to come"),
                            key=lambda gf: (str(gf[1].get("kickoff")), gf[0]))[:horizon]
            t_gws = sorted({g for g, _ in coming})
            keep = {(g, str(f.get("kickoff"))) for g, f in coming}
        else:
            t_gws, keep = want_gws, None
        for g in t_gws:
            fixtures = cal.get((t, g), [])
            if keep is not None:
                fixtures = [f for f in fixtures if (g, str(f.get("kickoff"))) in keep]
            if not fixtures:
                out.append({"team": t, "gw": g, "fixtures": [], "blank_gameweek": True,
                            "note": "no fixture for this team in this gameweek (a blank)"})
                continue
            mrow = by_key.get((t, g))
            entries = []
            for f in fixtures:
                e = dict(f)
                status = fixture_status(e.get("kickoff"), now)
                if status:
                    e["status"] = status
                    if results and status != "to come":
                        sc = results.get((t, g, str(e.get("kickoff"))))
                        if sc:
                            e["score"] = sc                      # the stored result of a kicked-off match (time batch, 2026-10-26)
                day = kickoff_day(e.get("kickoff"))
                if day:
                    e["kickoff_day"] = day
                if mrow is None:
                    e["difficulty"] = None
                    # batch 3 F9 (2026-10-14): the agent said a fixture beyond the plan was "not scheduled"; it is
                    # scheduled, the model has simply not rated it yet -- said in those words, with its gameweek and date
                    e["rating"] = f"scheduled but not rated yet: GW{g}" + (f", {day}" if day else "")
                    e["difficulty_unavailable"] = (
                        f"the latest build covers gameweeks "
                        f"{model_gws[0]}-{model_gws[-1]} and this is GW{g}; the fixture is real "
                        f"but the model has not priced it. This is a missing CALCULATION, not "
                        f"an easy fixture." if model_gws else
                        "no model run is available to price this fixture")
                else:
                    tl, ol = mrow.get("team_lambda"), mrow.get("opp_lambda")
                    src, const, notes = fixture_provenance(mrow, (step_rows_by_gw or {}).get(g))
                    e["difficulty"] = _difficulty(tl, ol, mrow.get("p_cs"), scores.get((t, g)))
                    e["lambdas"] = {
                        "team_lambda": None if tl is None or tl != tl else round(float(tl), 6),
                        "opp_lambda": None if ol is None or ol != ol else round(float(ol), 6),
                        "league_average_lambda": LEAGUE_AVG_LAMBDA,
                    }
                    e["provenance"] = {
                        "source": src,
                        "constant": const,
                        "priced_off": ("market odds (the deadline gameweek)" if market_priced(mrow)
                                       else "a planning estimate based on team strength alone -- no odds "
                                            "are published this far out, and this is a LOWER "
                                            "QUALITY number than a market-priced one"),
                        "market_priced": market_priced(mrow),
                        "how_known": ("from horizon_step: the deadline gameweek carries odds, "
                                      "beyond it none are published. model_predictions does "
                                      "not store odds_horizon_gws, so this is derived, not "
                                      "read"),
                        "horizon_step": (int(mrow["horizon_step"])
                                         if mrow.get("horizon_step") is not None else None),
                        "notes": notes,
                    }
                    sides = runaway_side(mrow)
                    e["runaway"] = bool(sides)
                    e["runaway_sides"] = sides
                    if sides:
                        e["runaway_warning"] = (
                            "This fixture's difficulty rests on a strength that ran off "
                            "(KNOWN_ISSUES #25). Where the OPPONENT's attack ran off the "
                            "clean sheet is priced as near certain and the defensive "
                            "difficulty here is NOT trustworthy -- it is the same defect that "
                            "manufactures a floor in the quantiles.")
                entries.append(e)
            out.append({"team": t, "gw": g, "fixtures": entries,
                        "n_fixtures": len(entries),
                        "double_gameweek": len(entries) > 1})

    # 4d (2026-10-08): for one club, its doubles and blanks across EVERY gameweek the calendar holds --
    # the calendar already carried them; a triple-captain or bench-boost question needs them in one place.
    season_summary = None
    if team is not None and cal_gws:
        t = str(team)
        covered = list(range(cal_gws[0], cal_gws[-1] + 1))
        season_summary = {
            "team": t, "calendar_covers": [cal_gws[0], cal_gws[-1]],
            "double_gameweeks": [g for g in covered if len(cal.get((t, g), [])) >= 2],
            "blank_gameweeks": [g for g in covered if not cal.get((t, g))],
            "note": ("from the loaded fixture calendar only. Doubles and blanks are usually confirmed later in "
                     "the season as cup ties and postponements settle, so an empty list means none are known "
                     "yet, not that none will happen."),
        }

    compact = team is None
    if compact:
        # 20 clubs x 5 gameweeks was 100 entries and 190,162 characters, because every entry
        # repeated the same four paragraphs about the two difficulty numbers (B25). The rule is
        # said once, below, and each row carries the six facts a reader is actually scanning.
        rows = []
        for e in out:
            if e.get("blank_gameweek"):
                rows.append({"team": e["team"], "gw": e["gw"], "opponent": None,
                             "home": None, "attacking": None, "defensive": None,
                             "attack_score": None, "defence_score": None, "blank": True})
                continue
            for f in e["fixtures"]:
                d = f.get("difficulty") or {}
                rows.append({"team": e["team"], "gw": e["gw"], "opponent": f.get("opponent"),
                             "home": f.get("home"), "status": f.get("status"), "kickoff_day": f.get("kickoff_day"),
                             "attacking": (d.get("attacking") or {}).get("value"),
                             "defensive": (d.get("defensive") or {}).get("value"),
                             "attack_score": (d.get("attacking") or {}).get("score"),
                             "defence_score": (d.get("defensive") or {}).get("score"),
                             **({"rating": f["rating"]} if f.get("rating") else {})})
        out = rows

    listed = want_gws if want_gws is not None else sorted({int(b["gw"]) for b in out if isinstance(b, dict) and b.get("gw") is not None})
    return {
        "compact": compact,
        "fixtures": out,
        "season_summary": season_summary,
        "teams_requested": teams,
        "unknown_teams": unknown,
        "gameweeks": listed,
        "listed_gameweeks": listed,
        "model_horizon": {"gws": model_gws,
                          "gameweeks_covered": [model_gws[0], model_gws[-1]] if model_gws else [],
                          "note": ("fixtures outside this range are scheduled but not rated yet: they are listed "
                                   "with difficulty null, a rating line and a reason, never omitted and never 'not "
                                   "scheduled'; the build covers "
                                   + (f"GW{model_gws[0]}-GW{model_gws[-1]}" if model_gws else "no gameweek")
                                   + (f" while this answer lists GW{listed[0]}-GW{listed[-1]}" if listed else " while this answer lists no gameweek")
                                   + (" -- a club with no fixture listed here may still have one in a covered gameweek this answer does not list"
                                      if model_gws and listed and listed[-1] < model_gws[-1] else ""))},
        "score_meaning": SCORE_PLAIN,
        "meanings": {"kickoff_day": "the weekday, date and UTC kickoff time of the fixture, from the calendar",
                     "status": "played = kicked off more than two hours ago; in progress = kicked off within the last two hours; "
                               "to come = kickoff is still ahead (against the clock at the time of the answer)",
                     "attack_score": "1 (hardest) to 10 (easiest) by tenths among every priced fixture",
                     "defence_score": "1 (hardest) to 10 (easiest) by tenths among every priced fixture",
                     "listed_gameweeks": "the gameweeks this answer lists", "gameweeks_covered": "the gameweeks the build has priced"},
        "calendar_source": {
            "file": SKELETON.name,
            "age_hours": skeleton_age_hours,
            "refresh": "refreshed WEEKLY, not by each build",
            "caveat": ("fixtures get rescheduled; a calendar this old can name a kickoff that "
                       "has since moved. Deliberate: refreshing it per build would touch the "
                       "build path for something that rarely changes."),
            "team_names_resolved": n_team_names,
        },
        "compact_columns": ("attacking = expected goals FOR this team in this fixture "
                            "(higher is easier to score in); defensive = clean-sheet "
                            "probability (higher is easier to keep one); attack_score and "
                            "defence_score = each of those ranked 1 (hardest) to 10 (easiest) "
                            "among every fixture the build has priced -- two scores, never one. "
                            "Ask for one club to get the lambdas, the provenance and the runaway flags."),
        "scores": SCORE_MEANING,
        "difficulty_is_two_numbers": ("attacking and defensive difficulty are reported "
                                      "separately and must not be averaged into one FDR-like "
                                      "score -- that would discard the distinction this model "
                                      "has and FPL's does not"),
    }
