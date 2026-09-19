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


def _difficulty(tl, ol, pcs):
    """The two quantities, never one composite.

    attacking  -- how easy is it to SCORE here: our expected goals in this fixture.
    defensive  -- how easy is a CLEAN SHEET here: p_cs primarily, opp_lambda alongside.

    p_cs is the 0.2*DC + 0.8*market blend (CS_BLEND_W) and is what the model actually uses for
    the clean-sheet term, so it is the honest defensive number. It is NOT exp(-opp_lambda): at
    step 0 the two differ (sd 0.0211, max 0.0782), which is the coupling error the quantile
    work found. Both are reported so neither is hidden behind the other.
    """
    def band(v, lo, hi):
        if v is None or v != v:
            return None
        return "easy" if v >= hi else ("hard" if v <= lo else "average")

    return {
        "attacking": {
            "measure": "expected goals FOR this team in this fixture (team_lambda)",
            "value": None if tl is None or tl != tl else round(float(tl), 4),
            "band": band(tl, 1.0, 1.8),
            "reading": "higher is EASIER to score in",
        },
        "defensive": {
            "measure": "clean-sheet probability (p_cs, the 0.2 DC / 0.8 market blend)",
            "value": None if pcs is None or pcs != pcs else round(float(pcs), 4),
            "opp_lambda": None if ol is None or ol != ol else round(float(ol), 4),
            "band": band(pcs, 0.20, 0.35),
            "reading": "higher is EASIER to keep a clean sheet",
            "note": ("p_cs is not exp(-opp_lambda): at the deadline gameweek the two differ "
                     "(sd 0.0211, max 0.0782) because p_cs blends Dixon-Coles with the market "
                     "and opp_lambda is pure market"),
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


def build(rows, cal, n_team_names, team=None, gw=None, horizon=5,
          step_rows_by_gw=None, skeleton_age_hours=None):
    """PURE. `rows` are the per-(team, gw) model rows; `cal` is calendar()'s mapping.

    A fixture beyond the model's horizon is RETURNED WITH difficulty None and a reason, never
    omitted and never given a fabricated number -- the same rule the quantile block uses for a
    run that did not compute them: a missing calculation must not read as an absence of risk.
    """
    by_key = {(str(r["team"]), int(r["gw"])): r for r in rows}
    model_gws = sorted({int(r["gw"]) for r in rows})
    horizon = max(1, min(int(horizon), MAX_HORIZON))

    if gw is not None:
        want_gws = [int(gw)]
    else:
        start = model_gws[0] if model_gws else min((k[1] for k in cal), default=1)
        want_gws = list(range(start, start + horizon))

    teams = sorted({k[0] for k in cal}) if team is None else [str(team)]
    unknown = [t for t in teams if not any(k[0] == t for k in cal)]

    out = []
    for t in teams:
        for g in want_gws:
            fixtures = cal.get((t, g), [])
            if not fixtures:
                out.append({"team": t, "gw": g, "fixtures": [], "blank_gameweek": True,
                            "note": "no fixture for this team in this gameweek (a blank)"})
                continue
            mrow = by_key.get((t, g))
            entries = []
            for f in fixtures:
                e = dict(f)
                if mrow is None:
                    e["difficulty"] = None
                    e["difficulty_unavailable"] = (
                        f"the latest run's horizon covers gameweeks "
                        f"{model_gws[0]}-{model_gws[-1]} and this is GW{g}; the fixture is real "
                        f"but the model has not priced it. This is a missing CALCULATION, not "
                        f"an easy fixture." if model_gws else
                        "no model run is available to price this fixture")
                else:
                    tl, ol = mrow.get("team_lambda"), mrow.get("opp_lambda")
                    src, const, notes = fixture_provenance(mrow, (step_rows_by_gw or {}).get(g))
                    e["difficulty"] = _difficulty(tl, ol, mrow.get("p_cs"))
                    e["lambdas"] = {
                        "team_lambda": None if tl is None or tl != tl else round(float(tl), 6),
                        "opp_lambda": None if ol is None or ol != ol else round(float(ol), 6),
                        "league_average_lambda": LEAGUE_AVG_LAMBDA,
                    }
                    e["provenance"] = {
                        "source": src,
                        "constant": const,
                        "priced_off": ("market odds (the deadline gameweek)" if market_priced(mrow)
                                       else "the fitted Dixon-Coles strengths alone -- no odds "
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

    return {
        "fixtures": out,
        "teams_requested": teams,
        "unknown_teams": unknown,
        "gameweeks": want_gws,
        "model_horizon": {"gws": model_gws,
                          "note": ("fixtures outside this range are listed with difficulty "
                                   "null and a reason, never omitted")},
        "calendar_source": {
            "file": SKELETON.name,
            "age_hours": skeleton_age_hours,
            "refresh": "written by the WEEKLY ingest, not by each build",
            "caveat": ("fixtures get rescheduled; a calendar this old can name a kickoff that "
                       "has since moved. Deliberate: refreshing it per build would touch the "
                       "build path for something that rarely changes."),
            "team_names_resolved": n_team_names,
        },
        "difficulty_is_two_numbers": ("attacking and defensive difficulty are reported "
                                      "separately and must not be averaged into one FDR-like "
                                      "score -- that would discard the distinction this model "
                                      "has and FPL's does not"),
    }
