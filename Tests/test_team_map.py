"""TEAM_MAP has ONE home (squad/team_map.py) and assembly imports it from there.

2026-09-19: the literal moved out of assembly.py so read-side tools can use the odds-archive
-> FPL name bridge without importing the model stack (assembly pulls sklearn, lightgbm and
scipy). No behaviour change: this pins the dict identical, by identity and by value, and
pins the three entries the 2026-08-17 audit found (KNOWN_ISSUES #14 is the Sheffield one).
"""
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
for p in (str(REPO), str(REPO / "squad")):
    if p not in sys.path:
        sys.path.insert(0, p)


def test_team_map_has_one_home_and_assembly_imports_it():
    import team_map
    import assembly
    assert assembly.TEAM_MAP is team_map.TEAM_MAP
    assert team_map.TEAM_MAP == {"Man United": "Man Utd", "Tottenham": "Spurs",
                                 "Sheffield United": "Sheffield Utd"}
    assert team_map.fpl_name("Tottenham") == "Spurs" and team_map.fpl_name("Hull City") == "Hull City"
