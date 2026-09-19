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
