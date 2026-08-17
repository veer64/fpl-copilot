#!/usr/bin/env python
"""
build_crosswalk.py -- per-season vaastav `element` <-> Understat `id` crosswalk.

WHY THIS EXISTS
---------------
Understat ids are stable across seasons; vaastav's `element` is not -- it is
reshuffled every summer, so element 234 is one player in one season and somebody
else the next (KNOWN_ISSUES #6). `player_id_crosswalk_final.csv` bridges the two,
but ONLY for 2025-26. Porting the pipeline to any other season needs its own
bridge, and the vaastav side has to be rematched from scratch each time.

WITHOUT THIS the attacking-rate component has nothing to join on and every player
silently falls back to the position-average rate, which would gut the model while
erroring nowhere.

HOW IT MATCHES, AND WHY THAT ORDER
----------------------------------
1. Exact match on a normalised name (lowercased, accents stripped, punctuation
   removed). Cheap and unambiguous.
2. Fuzzy match on the remainder via rapidfuzz `token_set_ratio`, which handles
   FPL's full legal names against Understat's playing names ("Bruno Borges
   Fernandes" vs "Bruno Fernandes").
3. Every fuzzy candidate must clear a score floor AND win its Understat id
   outright -- an id is awarded to the single highest-scoring claimant and to
   nobody else.

THE DEFECT THIS GUARDS AGAINST (KNOWN_ISSUES #3)
------------------------------------------------
Fuzzy matching on this player pool collides on shared surname tokens. The 2025-26
build assigned ONE Understat id to two different real players -- Beto and Joao
Gomes, both of whose full legal names contain "Gomes" -- and it survived into a
file named "final". The same family of error produced duplicate "Gabriel" and
duplicate "Rayan" claims.

So a duplicate sweep over the output is not optional here; it is the check that
the 2025-26 build failed. `build()` raises if any Understat id is claimed twice.

Usage:
    uv run python eval/build_crosswalk.py --season 2023-24
"""

import argparse
import re
import sys
import unicodedata
from pathlib import Path

import numpy as np
import pandas as pd
from rapidfuzz import fuzz, process

REPO = Path(__file__).resolve().parent.parent
HISTORY = REPO / "data" / "history"
ALL_SEASONS = HISTORY / "all_seasons_fixed.parquet"
UNDERSTAT = HISTORY / "understat_season_aggregates.parquet"

# Understat labels a season by its start year: "2023" == our "2023-24".
SEASON_TO_US = {f"{y}-{str(y+1)[-2:]}": str(y) for y in range(2016, 2026)}

FUZZY_FLOOR = 88          # token_set_ratio below this is not trusted at all
FUZZY_MARGIN = 4          # best must beat runner-up by this to be unambiguous
# Relaxed floor/margin, permitted ONLY when the club agrees. Club agreement is the
# disambiguator the 2025-24 build used by hand to fix its six surname collisions;
# doing it in code is what lets "Carlos Henrique Casimiro" reach "Casemiro"
# without also letting "Gabriel Martinelli Silva" reach "Gabriel Magalhaes".
TEAM_FLOOR = 72
TEAM_MARGIN = 1

# Explicit club aliases, vaastav -> Understat. Hard-coded for the same reason
# assembly.py hard-codes its two: fuzzy-matching CLUB names does not work and
# fails silently. "Spurs" against "Tottenham" scores near zero, "Man Utd" against
# "Manchester United" and "Wolves" against "Wolverhampton Wanderers" fall below any
# usable threshold -- so club disambiguation was disabled league-wide for those
# three clubs while reporting nothing. Only clubs whose names actually differ need
# an entry; the rest match exactly.
CLUB_ALIASES = {
    "Man City": "Manchester City",
    "Man Utd": "Manchester United",
    "Spurs": "Tottenham",
    "Wolves": "Wolverhampton Wanderers",
    "Newcastle": "Newcastle United",
    "Nott'm Forest": "Nottingham Forest",
    "Sheffield Utd": "Sheffield United",
    "West Brom": "West Bromwich Albion",
    "Leeds": "Leeds",
    "Leicester": "Leicester",
    "Southampton": "Southampton",
    "Norwich": "Norwich",
    "Watford": "Watford",
    "Ipswich": "Ipswich",
}

# Hand-resolved matches, keyed by season then vaastav element. These exist because
# FPL carries full legal names where Understat carries playing names, and no string
# metric bridges "Jorge Luiz Frello Filho" -> "Jorginho" without also creating false
# positives. Each is justified by club + position + a minutes/goals profile from two
# independent sources, recorded in `match_evidence` so it is auditable.
#
# The uniqueness rule is NOT relaxed to accommodate these. Arsenal's three Gabriels
# are still refused by the automatic passes; Martinelli and Jesus appear here
# precisely because refusing them automatically is correct behaviour.
MANUAL = {
    "2023-24": {
        365: ("2496", "Rodri; Man City MID; 2931v2967 min, 8v8 G, 10v9 A"),
        182: ("11700", "Vitinho; Burnley DEF; 2311v2324 min, 0v0 G, 3v2 A"),
        12: ("7752", "Gabriel Martinelli; Arsenal; 2010v2056 min, 6v6 G, 5v4 A"),
        376: ("2248", "Casemiro; Man Utd MID; 1981v2006 min, 1v1 G, 3v2 A"),
        567: ("6382", "Pedro Neto; Wolves MID; 1516v1524 min, 2v2 G, 11v9 A"),
        8: ("5543", "Gabriel Jesus; Arsenal FWD; 1470v1496 min, 4v4 G, 7v5 A"),
        497: ("7430", "Emerson Royal; Spurs DEF; 1152v1145 min, 1v1 G, 0v0 A"),
        121: ("6030", "Zanka; Brentford DEF; 1086v1082 min, 1v1 G, 0v0 A"),
        691: ("9983", "Beto; Everton FWD; 943v898 min, 3v3 G, 0v0 A; id independently "
                      "confirmed by KNOWN_ISSUES #3"),
        9: ("1389", "Jorginho; Arsenal MID; 913v911 min, 0v0 G, 2v2 A"),
    },
    "2024-25": {
        9: ("7752", "Gabriel Martinelli; Arsenal MID; 2284v2310 min, 8v8 G, 4v4 A"),
        188: ("9451", "Chimuanya Ugochukwu; LOAN case -- vaastav lists the parent "
                      "club (Chelsea), Understat the loan club (Southampton), so club "
                      "filtering could not reach him; 1652v1689 min, 1v1 G, 1v1 A"),
        218: ("9983", "Beto; Everton FWD; 1521v1520 min, 8v8 G, 0v0 A; same id as "
                      "2023-24 and as KNOWN_ISSUES #3"),
        596: ("12766", "Jota Silva; Nott'm Forest MID; 835v799 min, 3v3 G, 2v1 A; this "
                       "id was previously mis-assigned to element 653 by the "
                       "club+token pass -- see the uniqueness note in build()"),
        7: ("1389", "Jorginho; Arsenal MID; 701v717 min, 0v0 G, 0v0 A"),
        2: ("5543", "Gabriel Jesus; Arsenal FWD; 600v581 min, 3v3 G, 2v0 A"),
        653: ("13068", "Morato = Felipe Rodrigues da Silva; Nott'm Forest DEF; "
                       "891v852 min, 0v0 G, 0v0 A. CORRECTION: previously left "
                       "unmatched on the reasoning that no plausible Understat entry "
                       "existed -- wrong, because the candidate list had been "
                       "distorted by the very mis-match being removed. Morato was "
                       "unclaimed all along."),
    },
}


def _norm(s):
    """Lowercase, strip accents and punctuation, collapse whitespace."""
    if not isinstance(s, str):
        return ""
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"[^a-zA-Z\s]", " ", s).lower()
    return re.sub(r"\s+", " ", s).strip()


def _team_map(v_teams, u_teams):
    """Map vaastav club names onto Understat's: explicit alias, then exact, then
    fuzzy as a last resort.

    RAISES if any club fails to resolve. An unmapped club does not break loudly on
    its own -- it just quietly switches off club disambiguation for that club's
    whole squad -- so the assertion is the only thing that makes the failure
    visible. Three clubs were silently unmapped before this existed.
    """
    u_by_norm = {_norm(u): u for u in u_teams}
    out, unmapped = {}, []
    for t in sorted(v_teams):
        alias = CLUB_ALIASES.get(t)
        if alias and _norm(alias) in u_by_norm:
            out[t] = u_by_norm[_norm(alias)]
            continue
        if _norm(t) in u_by_norm:
            out[t] = u_by_norm[_norm(t)]
            continue
        hit = process.extractOne(_norm(t), list(u_by_norm), scorer=fuzz.token_set_ratio)
        if hit and hit[1] >= 85:
            out[t] = u_by_norm[hit[0]]
        else:
            unmapped.append(t)
    if unmapped:
        raise AssertionError(
            "club(s) did not resolve to an Understat club: "
            f"{unmapped}. Add them to CLUB_ALIASES in eval/build_crosswalk.py. "
            "Leaving one unmapped silently disables club disambiguation for that "
            f"club's entire squad. Understat clubs available: {sorted(u_teams)}")
    return out


def _teams_agree(v_team, u_title, tmap):
    """Understat's team_title is comma-separated for a player who moved clubs."""
    if not isinstance(u_title, str) or v_team not in tmap:
        return False
    want = _norm(tmap[v_team])
    return any(_norm(p) == want for p in u_title.split(","))


# Post-build audit thresholds. A one-to-one WRONG match is invisible to the
# duplicate sweep -- the mapping is unique, it is just pointing at the wrong
# player -- so profile agreement is the only thing that can catch it. Two
# instances have now surfaced (Felipe/Jota in 2024-25 and again in the 2025-26
# canonical file) and BOTH were found by accident while chasing an unmatched
# player, never by a check on the matched ones.
#
# MINUTES: the tolerance scales, because 60 minutes apart is nothing on 2,500 and
# damning on 150. Below the floor, short-season and cameo players would trip
# constantly on noise.
AUDIT_MIN_FLOOR = 240       # minutes of absolute slack before proportional kicks in
AUDIT_MIN_FRAC = 0.35       # ...or 35% of the larger of the two, whichever is larger
# GOALS: an absolute margin of 3 tolerates definitional differences (own goals,
# disputed awards) without tolerating a different player.
AUDIT_GOAL_ABS = 3
AUDIT_MIN_MINUTES = 450     # only audit players with enough football to judge


def _audit(cw, vp, us, tmap, verbose=True):
    """Profile-agreement audit. RAISES on minutes or goals disagreement; club
    disagreement only WARNS, because mid-season transfers produce genuine false
    positives (Ouattara, Ramsey, Garnacho, Nelson and Doak all legitimately show
    one club in vaastav and another in Understat)."""
    d = (cw.merge(vp, on="element", how="inner")
           .merge(us[["id", "player_name", "team_title", "time", "goals"]],
                  left_on=cw["understat_id"].name, right_on="id", how="left",
                  suffixes=("", "_u")))
    # Understat stores every numeric column as a STRING (KNOWN_ISSUES #2), and the
    # comparisons below would silently do the wrong thing -- or here, raise --
    # without the cast.
    for c in ("time", "goals"):
        d[c] = pd.to_numeric(d[c], errors="coerce")
    d = d[d["time"].notna() & (d["minutes"] >= AUDIT_MIN_MINUTES)]
    if not len(d):
        return

    tol = np.maximum(AUDIT_MIN_FLOOR,
                     AUDIT_MIN_FRAC * np.maximum(d["minutes"], d["time"]))
    bad_min = (d["minutes"] - d["time"]).abs() > tol
    bad_goal = (d["goals_v"] - d["goals"]).abs() > AUDIT_GOAL_ABS
    bad_club = ~pd.Series(
        [_teams_agree(t, u, tmap) for t, u in zip(d["team"], d["team_title"])],
        index=d.index)

    if bad_club.any() and verbose:
        print(f"  [audit] {int(bad_club.sum())} pair(s) disagree on club -- usually a "
              "mid-season transfer, reported not enforced")

    hard = d[bad_min | bad_goal]
    if len(hard):
        cols = ["element", "name", "team", "position", "minutes", "goals_v",
                "understat_id", "player_name", "team_title", "time", "goals"]
        raise AssertionError(
            "profile audit FAILED: matched pair(s) disagree on minutes or goals by "
            "more than the tolerance, which is the signature of a one-to-one wrong "
            "match. Resolve by hand (add to MANUAL) before using this crosswalk.\n"
            + hard[cols].sort_values("minutes", ascending=False).to_string(index=False))
    if verbose:
        print(f"  [audit] {len(d)} pairs checked on minutes+goals, all within tolerance")


def build(season, verbose=True):
    """Return (crosswalk DataFrame, stats dict). Raises on a duplicate claim."""
    us_season = SEASON_TO_US[season]

    v = pd.read_parquet(ALL_SEASONS, columns=["season", "element", "name", "team",
                                              "minutes", "position", "goals_scored"])
    v = v[(v.season == season) & (v.position != "AM")]
    # One row per element, carrying total minutes so coverage can be weighted by
    # who actually matters rather than by raw headcount.
    vp = (v.groupby("element")
          .agg(name=("name", "first"), team=("team", "first"),
               minutes=("minutes", "sum"), goals_v=("goals_scored", "sum"))
          .reset_index())
    vp["key"] = vp["name"].map(_norm)

    us = pd.read_parquet(UNDERSTAT)
    us = us[us.understat_season == us_season].copy()
    us["key"] = us["player_name"].map(_norm)
    us = us.drop_duplicates("id")

    # ---- pass 1: exact ----
    exact = vp.merge(us[["id", "player_name", "key"]], on="key", how="inner")
    exact = exact.drop_duplicates("element").drop_duplicates("id")
    matched = {r.element: (r.id, r.player_name, "exact", 100.0)
               for r in exact.itertuples()}
    claimed = {r.id for r in exact.itertuples()}

    # ---- pass 2: fuzzy on the remainder ----
    rem_v = vp[~vp.element.isin(matched)]
    rem_u = us[~us.id.isin(claimed)]
    choices = rem_u["key"].tolist()
    u_ids = rem_u["id"].tolist()
    u_names = rem_u["player_name"].tolist()

    tmap = _team_map(set(vp.team.dropna()), sorted(set(us.team_title.dropna()
                                                       .str.split(",").explode())))
    if verbose:
        print(f"  club map built for {len(tmap)} clubs")
    u_titles = rem_u["team_title"].tolist()
    # Full-season club-mate view, used by the discriminating-token pass below so
    # that ALREADY-MATCHED club-mates still count against a token's uniqueness.
    us_keys = us["key"].tolist()
    us_ids_all = us["id"].tolist()
    us_titles_all = us["team_title"].tolist()

    proposals = []
    for r in rem_v.itertuples():
        if not r.key or not choices:
            continue
        top = process.extract(r.key, choices, scorer=fuzz.token_set_ratio, limit=5)
        if not top:
            continue
        best_s, runner = top[0][1], (top[1][1] if len(top) > 1 else 0.0)
        j, kind = None, None

        if best_s >= FUZZY_FLOOR and (best_s - runner) >= FUZZY_MARGIN:
            j, kind = top[0][2], "fuzzy"
        else:
            # Ambiguous on name alone. Allow the club to break the tie, but only
            # if EXACTLY ONE plausible candidate plays for the right club --
            # otherwise this reintroduces the very collision it is meant to fix.
            same = [t for t in top
                    if t[1] >= TEAM_FLOOR and _teams_agree(r.team, u_titles[t[2]], tmap)]
            if len(same) == 1 and same[0][1] - max(
                    [t[1] for t in top if t[2] != same[0][2]] or [0]) >= -100:
                others = [t for t in same[1:]]
                if not others:
                    j, kind = same[0][2], "fuzzy+club"
        if j is None:
            # Last resort: a DISCRIMINATING TOKEN within the club. FPL carries
            # full legal names ("Carlos Henrique Casimiro", "Gabriel Martinelli
            # Silva") where Understat carries playing names, so token_set_ratio
            # over the whole string is diluted by the extra tokens.
            #
            # A token qualifies only if it identifies exactly ONE Understat player
            # at that club. That uniqueness requirement is what keeps Arsenal's
            # three Gabriels apart: "gabriel" maps to three players and is
            # rejected, while "martinelli" maps to one and is accepted.
            #
            # Uniqueness is tested against EVERY club-mate in the season, not just
            # the unclaimed ones. Testing only the unclaimed pool is a real defect:
            # it let Felipe Rodrigues da Silva (Forest DEF, 0G) claim Jota Silva
            # (Forest MID, 3G) because the other "Silva" at the club had already
            # been matched and was therefore invisible to the check. "silva" is not
            # a discriminating token in that squad, and the test must be able to
            # see that. A wrong id is worse than a null -- it imports another
            # player's scoring rate rather than falling back to a position prior.
            v_toks = [t for t in r.key.split() if len(t) >= 4]
            all_mates = [(i, k) for i, k in enumerate(us_keys)
                         if _teams_agree(r.team, us_titles_all[i], tmap)]
            shared = [i for i, k in all_mates
                      if any(fuzz.ratio(a, b) >= 85
                             for a in v_toks for b in k.split() if len(b) >= 4)]
            if len(shared) == 1:
                uid = us_ids_all[shared[0]]
                if uid not in claimed and uid in set(u_ids):
                    j, kind = u_ids.index(uid), "club+token"
        if j is None:
            # Dropped rather than guessed -- a wrong id is worse than a null,
            # because the null falls back to a position prior while a wrong id
            # silently imports another player's scoring rate.
            continue
        proposals.append({"element": r.element, "id": u_ids[j],
                          "player_name": u_names[j],
                          "score": best_s, "kind": kind, "minutes": r.minutes})

    # An Understat id goes to its single best claimant, never to two.
    if proposals:
        pr = pd.DataFrame(proposals).sort_values(["id", "score", "minutes"],
                                                 ascending=[True, False, False])
        pr = pr.drop_duplicates("id", keep="first").drop_duplicates("element",
                                                                   keep="first")
        for r in pr.itertuples():
            matched[r.element] = (r.id, r.player_name, r.kind, float(r.score))

    evidence = {}
    for el, (uid, why) in MANUAL.get(season, {}).items():
        prior = {e for e, (v0, _, _, _) in matched.items() if str(v0) == str(uid)}
        if prior - {el}:
            raise AssertionError(
                f"manual mapping element {el} -> understat {uid} collides with an "
                f"automatic match on element(s) {sorted(prior - {el})}. Resolve by "
                "hand before proceeding; a silent overwrite is how KNOWN_ISSUES #3 "
                "happened.")
        row = us[us["id"].astype(str) == str(uid)]
        name = row["player_name"].iloc[0] if len(row) else "?"
        matched[el] = (row["id"].iloc[0] if len(row) else uid, name, "manual", 100.0)
        evidence[el] = why

    cw = pd.DataFrame([
        {"season": season, "element": e, "understat_id": v0,
         "matched_name": n, "match_type": t, "match_score": s,
         "match_evidence": evidence.get(e, "")}
        for e, (v0, n, t, s) in matched.items()]).sort_values("element")

    # ---- the sweep that the 2025-26 build failed ----
    dup = cw[cw.duplicated("understat_id", keep=False)]
    if len(dup):
        raise AssertionError(
            "duplicate understat_id claimed by more than one element "
            f"(KNOWN_ISSUES #3):\n{dup.to_string(index=False)}")
    assert cw.element.is_unique, "an element was matched twice"

    _audit(cw, vp, us, tmap, verbose=verbose)

    cov = vp.merge(cw[["element", "understat_id"]], on="element", how="left")
    got = cov.understat_id.notna()
    stats = {
        "season": season, "understat_season": us_season,
        "vaastav_elements": len(vp), "understat_players": len(us),
        "matched": int(got.sum()),
        "matched_exact": int((cw.match_type == "exact").sum()),
        "matched_fuzzy": int((cw.match_type == "fuzzy").sum()),
        "matched_fuzzy_club": int((cw.match_type == "fuzzy+club").sum()),
        "matched_club_token": int((cw.match_type == "club+token").sum()),
        "matched_manual": int((cw.match_type == "manual").sum()),
        "pct_elements": round(100 * got.mean(), 1),
        # The number that matters: unmatched players are overwhelmingly zero-minute
        # squad filler Understat never tracked, so headcount understates coverage.
        "pct_minutes_covered": round(
            100 * cov.loc[got, "minutes"].sum() / max(cov.minutes.sum(), 1), 1),
        "unmatched_with_450plus_min": int(
            ((~got) & (cov.minutes >= 450)).sum()),
    }
    if verbose:
        for k, val in stats.items():
            print(f"  {k:<28} {val}")
        big = cov[(~got) & (cov.minutes >= 450)].sort_values("minutes",
                                                            ascending=False)
        if len(big):
            print("\n  unmatched players with 450+ minutes (these DO cost accuracy):")
            print(big[["element", "name", "team", "minutes"]].head(15)
                  .to_string(index=False))
    return cw, stats


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--season", required=True)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    print(f"building crosswalk for {args.season} ...")
    cw, stats = build(args.season)
    out = Path(args.out) if args.out else (
        HISTORY / f"crosswalk_{args.season.replace('-', '_')}.csv")
    cw.to_csv(out, index=False)
    print(f"\nwrote {out}  ({len(cw)} rows)")


if __name__ == "__main__":
    main()
