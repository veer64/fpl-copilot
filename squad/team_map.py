"""team_map.py -- the ONE home of the odds-archive -> FPL club-name bridge.

Football-data (the odds archive, E0) and FPL / vaastav spell three clubs differently.
Audited 2026-08-17 across all ten seasons on disk: these three are the ONLY names that
differ between the sources. "Sheffield United" was missing until then -- every Sheffield
fixture join failed silently in their PL seasons (2019-20, 2020-21, 2023-24) and the
players' e_points collapsed to 0.0 all season. See KNOWN_ISSUES #14.

WHY THIS IS ITS OWN MODULE (2026-09-19). The dict lived in assembly.py, which imports the
whole model stack (minutes, bonus, dixon_coles -> sklearn, lightgbm, scipy: 1.8 s and the
model in memory). The read-side tools must answer without loading the model, and a fourth
copy of the dict would be the #14 class of defect waiting to recur -- eval/ev_surface.py
already carries a stale two-entry copy. So the literal moved here, assembly imports it, and
Tests/test_league_table.py pins assembly.TEAM_MAP to be this object. No behaviour changed.
"""

TEAM_MAP = {"Man United": "Man Utd", "Tottenham": "Spurs",
            "Sheffield United": "Sheffield Utd"}


def fpl_name(name):
    """The FPL spelling of an odds-archive club name (identity for every other club)."""
    return TEAM_MAP.get(name, name)


# football-data's E0 spelling -> FPL name for the clubs whose E0 spelling does NOT round-trip
# through TEAM_MAP: the promoted three of 2026-27. fetch_fixtures.py writes those clubs into
# the live slice under their FPL names ("Hull City"), while the live E0 file names them "Hull".
# This is the INVERSE of dixon_coles.ARCHIVE_NAME_ALIAS ("Hull City" -> "Hull") plus Coventry,
# which had no E0 rows before 2026-27 and so no alias anywhere. Read-side only (the E0 stats
# fill, eval/fill_e0_stats.py); the fit's own alias is untouched. Tests pin the inverse.
E0_PROMOTED_ALIAS = {"Hull": "Hull City", "Ipswich": "Ipswich Town", "Coventry": "Coventry City"}


def e0_to_fpl(name):
    """FPL name for a football-data E0 spelling: TEAM_MAP first, then the promoted-club alias."""
    n = TEAM_MAP.get(name, name)
    return E0_PROMOTED_ALIAS.get(n, n)


# FBref spelling -> FPL/vaastav name (eval/fbref_export.py, the manual-save pipeline). FBref
# matches neither FPL nor football-data. EVERY key below was read off a saved FBref page
# (measured 2026-09-20 across the eleven saved seasons 2016-17..2026-27; the seasons each
# spelling appeared in are listed). Clubs whose FBref spelling equals the FPL one (Arsenal,
# Burnley, Middlesbrough, ...) need no entry: the exporter maps identity, then checks the
# result against the club set measured from the stack for that season and asserts 0 unmapped,
# so a missing or wrong entry fails loudly rather than mis-joining.
#   2026-09-20: "Sheffield United" was missing and three seasons were withheld on it -- the
#   KNOWN_ISSUES #14 defect reproduced in a new map. Three keys written from memory
#   ("Newcastle Utd", "Nott'ham Forest", "Sheffield Utd") appeared on NO saved page and were
#   removed: FBref uses "Newcastle", "Nottingham" and "Sheffield United" in every season.
# Where a season's FPL spelling is the archive's ("Ipswich" in 2024-25 vs "Ipswich Town" in
# 2026-27) the exporter falls back to dixon_coles.ARCHIVE_NAME_ALIAS; no second copy here.
FBREF_TEAM_MAP = {
    "Manchester City": "Man City",          # 2016-17..2026-27
    "Manchester Utd": "Man Utd",            # 2016-17..2026-27
    "Nottingham": "Nott'm Forest",          # 2022-23..2026-27
    "Tottenham": "Spurs",                   # 2016-17..2026-27
    "Leeds United": "Leeds",                # 2020-21, 2021-22, 2022-23, 2025-26, 2026-27
    "Sheffield United": "Sheffield Utd",    # 2019-20, 2020-21, 2023-24 -- the entry that was missing
    "Leicester City": "Leicester",          # 2016-17..2022-23, 2024-25
    "Norwich City": "Norwich",              # 2019-20, 2021-22
    "Cardiff City": "Cardiff",              # 2018-19
    "Swansea City": "Swansea",              # 2016-17, 2017-18
    "Stoke City": "Stoke",                  # 2016-17, 2017-18
    "Luton Town": "Luton",                  # 2023-24
    "Newcastle": "Newcastle",               # identity, 2017-18..2026-27
    "West Brom": "West Brom",               # identity, 2016-17, 2017-18, 2020-21
    "Wolves": "Wolves",                     # identity, 2018-19..2025-26
    "Huddersfield": "Huddersfield",         # identity, 2017-18, 2018-19
    "Ipswich Town": "Ipswich Town",         # 2024-25 (FPL side "Ipswich", alias fallback), 2026-27
    "Hull City": "Hull City",               # identity, 2016-17, 2026-27
    "Coventry City": "Coventry City",       # identity, 2026-27
}

# Understat spelling -> FPL/vaastav name (model_tools.get_match_stats: team xG per match, summed
# from data/history/understat_matches_<season>.parquet). Measured 2026-09-20 across the five
# files on disk (2022-23..2026-27, 27 spellings); the six that differ from FPL are here, the
# rest are identity. Promoted-club drift ("Ipswich" in 2024-25 vs "Ipswich Town" in 2026-27)
# is handled by the same dixon_coles.ARCHIVE_NAME_ALIAS fallback the FBref bridge uses.
# eval/build_crosswalk.py holds three entries in the OTHER direction for player crosswalking;
# this is the team-level bridge and the only copy of it.
UNDERSTAT_TEAM_MAP = {
    "Manchester City": "Man City",
    "Manchester United": "Man Utd",
    "Newcastle United": "Newcastle",
    "Nottingham Forest": "Nott'm Forest",
    "Tottenham": "Spurs",
    "Wolverhampton Wanderers": "Wolves",
    "Sheffield United": "Sheffield Utd",
    "Coventry": "Coventry City",
    "Hull": "Hull City",
    "Ipswich": "Ipswich Town",              # 2024-25's FPL side is "Ipswich": alias fallback
}
