"""Regression tests for the three crosswalk defects found 2026-08-28 (read-only pass,
Handoff 2026-08-28 follow-up):

  (c) the profile audit raised KeyError on its own failure path (a `position`
      column `vp` never carried), so it could not report the wrong matches it found;
  (b) the fuzzy pass matched any single-token Understat playing name ("Rayan") at
      100 against any FPL name containing the token ("Rayan Cherki") -- a wrong id;
  (a) 2025-26 was hard-routed to the frozen legacy file and never ran the builder,
      leaving Cherki and Alex Jimenez Sanchez without an id all season.

All three tests fail against the pre-fix code.
"""
import sys
from pathlib import Path

import pandas as pd
import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "eval"))

import build_crosswalk as bc  # noqa: E402


# ---------- (c) the audit reports every hard disagreement, never raises ----------

def test_audit_reports_all_disagreements_without_raising(capsys):
    tmap = {"Man City": "Manchester City", "Bournemouth": "Bournemouth"}
    cw = pd.DataFrame({"element": [1, 2, 3],
                       "understat_id": ["10", "20", "30"]})
    vp = pd.DataFrame({"element": [1, 2, 3],
                       "name": ["A Wrong", "B Wrong", "C Right"],
                       "team": ["Man City", "Bournemouth", "Man City"],
                       "minutes": [1800, 1500, 2000], "goals_v": [4, 1, 3]})
    # Understat stores numerics as strings (KNOWN_ISSUES #2) -- keep that shape.
    us = pd.DataFrame({"id": ["10", "20", "30"],
                       "player_name": ["X", "Y", "C Right"],
                       "team_title": ["Bournemouth", "Bournemouth", "Manchester City"],
                       # element 1: goals 4 v 12 (beyond AUDIT_GOAL_ABS); element 2:
                       # minutes 1500 v 300 (beyond the tolerance); element 3: fine.
                       "time": ["900", "300", "1990"], "goals": ["12", "1", "3"]})
    hard = bc._audit(cw, vp, us, tmap, verbose=True)          # must not raise
    assert set(hard["element"]) == {1, 2}, hard
    out = capsys.readouterr().out
    assert "HARD disagreement" in out and "A Wrong" in out and "B Wrong" in out


# ---------- (b) single-token guard ----------

def test_single_token_guard_rejects_cherki_to_rayan():
    tmap = {"Man City": "Manchester City", "Bournemouth": "Bournemouth"}
    city_keys = ["mathis cherki", "erling haaland", "rodri"]
    # "rayan" is a Bournemouth player; the FPL element plays for Man City -> reject
    assert bc._single_token_ok("rayan", "Man City", "Bournemouth", tmap, city_keys) is False
    # club agrees and the token is unique at the club -> accept
    assert bc._single_token_ok("rodri", "Man City", "Manchester City", tmap, city_keys) is True
    # club agrees but the token names two club-mates -> reject
    ars_keys = ["gabriel", "gabriel martinelli", "gabriel jesus"]
    assert bc._single_token_ok("gabriel", "Arsenal", "Arsenal",
                               {"Arsenal": "Arsenal"}, ars_keys) is False
    # multi-token candidates are not the guard's business
    assert bc._single_token_ok("bruno fernandes", "Man City", "Bournemouth", tmap, city_keys) is True


# ---------- (a)+(4) the 2025-26 build resolves Cherki and Jimenez correctly ----------

@pytest.fixture(scope="module")
def cw_2025_26():
    cw, stats = bc.build("2025-26", verbose=False)
    return cw.set_index("element"), stats


def test_2025_26_cherki_and_jimenez_resolve(cw_2025_26):
    cw, _ = cw_2025_26
    assert str(cw.loc[417, "understat_id"]) == "8094"      # Rayan Cherki = 'Mathis Cherki'
    assert str(cw.loc[713, "understat_id"]) == "12168"     # Alex Jimenez Sanchez = 'Alejandro Jimenez'
    assert str(cw.loc[807, "understat_id"]) == "14395"     # Rayan Vitor keeps 'Rayan'
    claimants = cw[cw["understat_id"].astype(str) == "14395"]
    assert list(claimants.index) == [807], "id 14395 ('Rayan') must belong to Rayan Vitor only"


def test_2025_26_build_carries_no_audited_out_pair(cw_2025_26):
    cw, stats = cw_2025_26
    assert stats["audit_dropped"] == 0, stats
    # the KNOWN_ISSUES #3 collision stays resolved by hand
    assert str(cw.loc[511, "understat_id"]) == "13068"     # Morato, not Jota Silva
    assert str(cw.loc[311, "understat_id"]) == "9983"      # Beto
    assert str(cw.loc[19, "understat_id"]) == "7752"       # Martinelli
    assert cw["understat_id"].astype(str).is_unique
