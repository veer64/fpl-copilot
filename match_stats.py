"""match_stats.py -- rich factual team stats: the registry and the arithmetic. PURE.

ONE STAT, ONE SOURCE. Shots exist in three places on the volume and the three disagree --
different providers, different definitions. REGISTRY fixes one origin per stat, and nothing
outside it decides where a number comes from: a stat whose own source lacks a season is a
stated gap, never filled from a neighbour. The same question always returns the same number
with the same attribution. (The discipline that caught the Bet365 mislabel: the answer says
where the number came from.)

GRAIN IS STATED, NEVER INFERRED. Odds-archive and Understat stats are per match; FBref stats
are SEASON AGGREGATES from manual browser saves. A form window, a venue split or a head-to-head
asked of a season aggregate is refused by name with the season figure returned beside it,
labelled -- never widened, narrowed or substituted. Every returned stat carries `grain` and
its measured season coverage.

NO DATE COMPARISON HERE. Per-match rows reach this module already admitted by the one as-of
rule, dixon_coles.knowable_before, applied in model_tools.get_match_stats (its fourth caller).
Tests grep this source for any cutoff comparison.

NOT ADVICE. Nothing here prices, predicts or recommends; the tool sits inside the system
prompt's betting boundary.
"""
from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class Stat:
    source: object          # "odds_archive" | "understat" | "fbref" | None (held nowhere)
    grain: object           # "per_match" | "season_aggregate" | None
    columns: tuple          # archive/understat: (home_col, away_col); fbref: (category, column)
    label: str
    note: str = ""


REGISTRY = {
    # odds archive (football-data E0 for archive seasons; the live season's stat columns are the
    # E0 fill, its scores FPL's) -- per match
    "goals":           Stat("odds_archive", "per_match", ("home_goals", "away_goals"), "goals"),
    "shots":           Stat("odds_archive", "per_match", ("HS", "AS"), "shots"),
    "shots_on_target": Stat("odds_archive", "per_match", ("HST", "AST"), "shots on target"),
    "corners":         Stat("odds_archive", "per_match", ("HC", "AC"), "corners"),
    "fouls":           Stat("odds_archive", "per_match", ("HF", "AF"), "fouls committed"),
    "yellow_cards":    Stat("odds_archive", "per_match", ("HY", "AY"), "yellow cards"),
    "red_cards":       Stat("odds_archive", "per_match", ("HR", "AR"), "red cards"),
    # Understat, per-player rows summed to the team per match -- per match
    "xg":              Stat("understat", "per_match", ("xg_home", "xg_away"), "expected goals (xG), team total"),
    "npxg":            Stat("understat", "per_match", ("npxg_home", "npxg_away"), "non-penalty xG, team total"),
    # FBref squad tables, manual browser saves -- SEASON AGGREGATES
    "possession":      Stat("fbref", "season_aggregate", ("standard", "possession"), "possession %"),
    "crosses":         Stat("fbref", "season_aggregate", ("misc", "crosses"), "crosses"),
    "interceptions":   Stat("fbref", "season_aggregate", ("misc", "interceptions"), "interceptions"),
    "tackles_won":     Stat("fbref", "season_aggregate", ("misc", "tackles_won"), "tackles won"),
    "offsides":        Stat("fbref", "season_aggregate", ("misc", "offsides"), "offsides"),
    "fouled":          Stat("fbref", "season_aggregate", ("misc", "fouled"), "fouls drawn"),
    "pens_won":        Stat("fbref", "season_aggregate", ("misc", "pens_won"), "penalties won"),
    "pens_conceded":   Stat("fbref", "season_aggregate", ("misc", "pens_conceded"), "penalties conceded"),
    # asked for, held nowhere at team level -- refused by name, never approximated
    "big_chances":     Stat(None, None, (), "big chances", "no source on the volume at team level"),
    "woodwork":        Stat(None, None, (), "shots hitting the woodwork", "no source on the volume"),
    "passing":         Stat(None, None, (), "passing", "no source on the volume (FBref's Passing page is gone)"),
    "aerials":         Stat(None, None, (), "aerial duels", "no source on the volume"),
}
CORE_STATS = ["goals", "shots", "shots_on_target", "corners", "xg", "possession"]
VENUES = ("home", "away")
SIDES = ("for", "against", "both")
MAX_SEASONS, MAX_WINDOW = 11, 100
NOT_ADVICE = ("a stats lookup of matches already played: it states no price, no chance of a "
              "future result and no recommendation, and none can be derived from it")


# ------------------------------------------------------------------ validation

def validate(stats, venue, side, seasons, last_n_matches):
    """(stat names to answer, error dict or None). Unknown stats are an error naming the valid
    ones -- a hallucinated column can never be silently dropped."""
    names = list(CORE_STATS) if not stats else [str(s).strip().lower() for s in stats]
    unknown = [s for s in names if s not in REGISTRY]
    if unknown:
        return names, {"error": f"unknown stat(s) {unknown}; valid stats are {sorted(REGISTRY)}",
                       "unknown_stats": unknown, "valid_stats": sorted(REGISTRY)}
    if venue is not None and venue not in VENUES:
        return names, {"error": f"venue must be one of {VENUES} or omitted, got {venue!r}"}
    if side not in SIDES:
        return names, {"error": f"side must be one of {SIDES}, got {side!r}"}
    for label, v, cap in (("seasons", seasons, MAX_SEASONS), ("last_n_matches", last_n_matches, MAX_WINDOW)):
        if v is not None and (not isinstance(v, int) or isinstance(v, bool) or v < 1 or v > cap):
            return names, {"error": f"{label} must be an integer from 1 to {cap}, got {v!r}"}
    return list(dict.fromkeys(names)), None


def previous_season(key):
    """'2026-27' -> '2025-26'."""
    y0 = int(key[:4])
    return f"{y0 - 1}-{str(y0)[-2:]}"


def season_keys(current, n):
    out = [current]
    while len(out) < (n or 1):
        out.append(previous_season(out[-1]))
    return list(reversed(out))


# ------------------------------------------------------------------ per-match arithmetic

def club_rows(matches, team):
    """The admitted matches from `team`'s side: opponent, venue, gf/ga/result, and every
    per-match stat as <stat>_for / <stat>_against. Most recent first."""
    per_match = {n: s for n, s in REGISTRY.items() if s.grain == "per_match"}
    parts = []
    for venue, own, opp in (("H", "home", "away"), ("A", "away", "home")):
        g = matches[matches[own] == team]
        if g.empty:
            continue
        d = pd.DataFrame({"season": g["season"].values, "date": g["date_parsed"].values,
                          "opponent": g[opp].values, "venue": venue})
        for n, s in per_match.items():
            h, a = s.columns
            own_col, opp_col = (h, a) if venue == "H" else (a, h)
            d[f"{n}_for"] = g[own_col].values if own_col in g.columns else float("nan")
            d[f"{n}_against"] = g[opp_col].values if opp_col in g.columns else float("nan")
        parts.append(d)
    if not parts:
        return pd.DataFrame(columns=["season", "date", "opponent", "venue"])
    rows = pd.concat(parts, ignore_index=True)
    gf, ga = rows["goals_for"], rows["goals_against"]
    rows["result"] = ["W" if f > a else ("L" if f < a else "D") for f, a in zip(gf, ga)]
    return rows.sort_values("date", ascending=False, kind="stable").reset_index(drop=True)


def select(rows, opponent=None, venue=None, last_n=None):
    r = rows
    if opponent is not None:
        r = r[r["opponent"] == opponent]
    if venue == "home":
        r = r[r["venue"] == "H"]
    elif venue == "away":
        r = r[r["venue"] == "A"]
    if last_n is not None:
        r = r.head(last_n)
    return r.reset_index(drop=True)


def _num(v):
    return None if v is None or v != v else (int(v) if float(v).is_integer() else round(float(v), 3))


def aggregate(rows, stat, side, last_n):
    """Totals and per-match means over the rows where THIS stat has a value; the count of
    those rows travels with it so a short window or a coverage gap is never mistaken for a full
    one."""
    f_col, a_col = f"{stat}_for", f"{stat}_against"
    have = rows[f_col].notna() & rows[a_col].notna() if len(rows) else pd.Series([], dtype=bool)
    r = rows[have] if len(rows) else rows
    n = int(len(r))
    out = {"window": {"requested": last_n, "matches_in_scope": int(len(rows)), "matches_counted": n,
                      "complete": (n == last_n) if last_n else True}}
    for name, col in (("for", f_col), ("against", a_col)):
        if side != "both" and side != name:
            continue
        total = float(r[col].sum()) if n else None
        out[name] = {"total": _num(total), "per_match": (round(total / n, 3) if n else None)}
    by = {}
    for season, g in r.groupby("season"):
        by[season] = {"matches": int(len(g)),
                      "for_total": _num(float(g[f_col].sum())) if side != "against" else None,
                      "against_total": _num(float(g[a_col].sum())) if side != "for" else None}
    out["by_season"] = by
    return out


def head_to_head(rows, team, opponent):
    rec = {"won": int((rows["result"] == "W").sum()), "drawn": int((rows["result"] == "D").sum()),
           "lost": int((rows["result"] == "L").sum())}
    meetings = [{"season": r.season, "date": f"{pd.Timestamp(r.date):%Y-%m-%d}", "venue": r.venue,
                 "score": f"{int(r.goals_for)}-{int(r.goals_against)}", "result": r.result}
                for r in rows.itertuples(index=False)]
    st = (f"no meeting between {team} and {opponent} in the seasons and window requested, as of "
          f"the cutoff -- a stated zero, not an empty result" if not meetings else
          f"{len(meetings)} meeting(s), most recent first; the record is {team}'s")
    return {"opponent": opponent, "record": rec, "meetings": meetings, "matches_counted": len(meetings),
            "statement": st}


# ------------------------------------------------------------------ season aggregates (FBref)

def _fbref_value(tables, season, category, column, team, side_key):
    t = ((tables.get(season) or {}).get(category) or {}).get(side_key)
    if t is None or column not in t.columns:
        return None, "absent"
    hit = t[t["team"] == team]
    if hit.empty:
        return None, "absent"
    v = hit.iloc[0][column]
    if v is None or (isinstance(v, float) and v != v) or str(v).strip() == "":
        return None, "empty"
    try:
        return _num(float(v)), "ok"
    except (TypeError, ValueError):
        return str(v), "ok"


def season_figure(stat, spec, tables, season, team, side, all_null_cols, post_cutoff):
    """One season's aggregate for one club: value (and the _against value), the matches the
    aggregate covers, and the post-cutoff flag the IO layer computed with the as-of rule."""
    category, column = spec.columns
    entry = {"matches_in_aggregate": None}
    games, _ = _fbref_value(tables, season, "standard", "games", team, "for")
    entry["matches_in_aggregate"] = games
    null_here = column in (all_null_cols.get(season) or {}).get(category, [])
    if side != "against":
        v, status = _fbref_value(tables, season, category, column, team, "for")
        entry["value"] = v
        if v is None:
            entry["reason"] = (f"{stat} is empty in FBref's export for {season} (the column is all-null "
                               f"in the saved page): null, not zero" if null_here or status == "empty"
                               else f"{stat}: no FBref row for {team} in {season}")
    if side != "for":
        v, status = _fbref_value(tables, season, category, column, team, "against")
        entry["against"] = v
        if v is None and "reason" not in entry:
            entry["reason"] = (f"{stat} (against) is empty in FBref's export for {season}: null, not zero"
                               if null_here or status == "empty" else f"no FBref _against row for {team} in {season}")
    flag, n_after, saved_at = post_cutoff.get(season, (False, 0, None))
    entry["includes_post_cutoff"] = bool(flag)
    entry["matches_after_cutoff_in_aggregate"] = int(n_after)
    entry["statement"] = (
        f"season aggregate saved {saved_at}: {n_after} fixture(s) are dated after the cutoff day and "
        f"on or before the save, so matches played after the cutoff are inside this figure while "
        f"the per-match stats beside it stop at the cutoff" if flag else
        f"season aggregate; every fixture of {season} is dated before the cutoff day, so nothing "
        f"after the cutoff is inside it")
    return entry


# ------------------------------------------------------------------ assembly

def build(team, opponent, names, side, venue, last_n, seasons, rows, tables, coverage,
          all_null_cols, post_cutoff, sources):
    """PURE. `rows` = club_rows(...) of the ADMITTED matches; `tables` = FBref frames keyed by
    stack season; `coverage` = {source: {stat or "*": [seasons]}} measured by the IO layer."""
    scoped = select(rows, opponent=opponent, venue=venue, last_n=last_n)
    stats = {}
    for name in names:
        spec = REGISTRY[name]
        base = {"source": spec.source, "grain": spec.grain, "label": spec.label}
        if spec.source is None:
            base["refusal"] = (f"{name} ({spec.label}) is held nowhere: {spec.note}. Not approximated "
                               f"from anything adjacent.")
            base["coverage"] = {"seasons": []}
            stats[name] = base
            continue
        cov = coverage.get(spec.source, {})
        covered = list(cov.get(name, cov.get("*", [])))
        base["coverage"] = {"seasons": covered, "source": spec.source, "grain": spec.grain}
        missing = [s for s in seasons if s not in covered]
        if missing:
            base["coverage_note"] = (f"{name} is covered by {spec.source} for {covered or 'no season'}; "
                                     f"{', '.join(missing)} not covered -- a gap, not a zero, and not "
                                     f"filled from another source")
        if spec.grain == "per_match":
            base.update(aggregate(scoped, name, side, last_n))
            stats[name] = base
            continue
        # season aggregate: refuse the window / venue / opponent by name, return the season figure
        base["window"] = None
        if last_n is not None:
            base["window_refusal"] = (f"{name} is season-level (FBref season aggregate); a {last_n}-match "
                                      f"window is not available for it. The season figure is returned "
                                      f"below, labelled as such -- it is NOT the window's number.")
        if venue is not None:
            base["venue_refusal"] = (f"{name} has no home/away split at season level in the FBref squad "
                                     f"tables; the season figure covers all venues")
        if opponent is not None:
            base["opponent_refusal"] = (f"{name} cannot be restricted to head-to-head meetings: it is a "
                                        f"season aggregate over every opponent")
        base["by_season"] = {s: season_figure(name, spec, tables, s, team, side, all_null_cols, post_cutoff)
                             for s in seasons if s in covered}
        stats[name] = base
    out = {"team": team, "opponent": opponent, "seasons": seasons, "side": side, "venue": venue,
           "last_n_matches": last_n, "stats": stats, "sources": sources,
           "grain_note": ("per_match stats are aggregated over admitted matches only and carry "
                          "matches_counted; season_aggregate stats are FBref's season totals and "
                          "cannot be windowed, split by venue or restricted to an opponent"),
           "not_advice": NOT_ADVICE}
    if opponent is not None:
        out["head_to_head"] = head_to_head(scoped, team, opponent)
    return out
