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
