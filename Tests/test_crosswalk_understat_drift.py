"""Prompt X (24 Nov 2026): the crosswalk's minutes/goals audit while Understat's data stops before FPL's.

understat.com has served a maintenance page since 3 Nov; the per-match file carries Understat's own rows for GW1-8 and FPL
fallback rows (match_id prefix 'fpl') for GW9+, and the season aggregates the audit reads are frozen at GW8. The audit
compared them with FPL totals through GW11, so regular starters drifted past the tolerance and were DROPPED as wrong
matches -- 17 at the GW11 ingest (457 -> 440 ids), Dean Henderson among them (Understat 270 min, FPL 540), and the strict
top-30 preflight then refused every GW12 build (run 87).

The fix: while the per-match file holds fallback rows, the audit compares FPL totals only through Understat's last
gameweek -- read from the per-match file's own (non-fallback) rows, never hard-coded -- so like is compared with like, a
genuinely wrong match is still caught, and the full-season comparison returns by itself once Understat is back."""
import sys
from pathlib import Path

import pandas as pd
import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "eval"))

import build_crosswalk as bc  # noqa: E402

SEASON, TAG = "2026-27", "2026_27"

# element -> (name, team, position, minutes per GW1..GW11)
FPL = {
    198: ("Dean Henderson", "Crystal Palace", "GK", [90, 90, 90, 0, 0, 0, 0, 0, 90, 90, 90]),   # 270 through GW8, 540 in all
    534: ("Trai Hume", "Sunderland", "DEF", [90] * 11),                                         # 720 through GW8, 990 in all
    77: ("Wrong Guy", "Brighton", "MID", [90] * 11),                                            # matched to a different player
}
# Understat's season listing, frozen at GW8 (numerics as strings: KNOWN_ISSUES #2)
US_FROZEN = [dict(id="7702", player_name="Dean Henderson", team_title="Crystal Palace", time="270", goals="0", games="3"),
             dict(id="13713", player_name="Trai Hume", team_title="Sunderland", time="720", goals="0", games="8"),
             dict(id="999", player_name="Wrong Guy", team_title="Brighton", time="100", goals="0", games="2")]


def _history(tmp_path, monkeypatch, *, real_through=8, last_gw=11, us_rows=US_FROZEN):
    """A data/history dir with the four files build() reads + the per-match file: Understat's own rows through
    `real_through`, FPL fallback rows ('fpl…') after it up to `last_gw`."""
    h = tmp_path / "history"
    h.mkdir()
    pd.DataFrame([dict(season="2025-26", element=1, name="x", team="x", minutes=0, position="MID", goals_scored=0, GW=1)]) \
        .to_parquet(h / "all_seasons_fixed.parquet", index=False)
    rows = [dict(season=SEASON, element=el, name=n, team=t, position=p, minutes=m, goals_scored=0, GW=gw)
            for el, (n, t, p, mins) in FPL.items() for gw, m in enumerate(mins, start=1)]
    pd.DataFrame(rows).to_parquet(h / f"all_seasons_with_{TAG}.parquet", index=False)
    pd.DataFrame([dict(id="1", player_name="x", team_title="x", time="0", goals="0", games="0", understat_season="2025")]) \
        .to_parquet(h / "understat_season_aggregates.parquet", index=False)
    pd.DataFrame([dict(r, understat_season="2026") for r in us_rows]) \
        .to_parquet(h / f"understat_season_aggregates_with_{TAG}.parquet", index=False)
    pm = [dict(season=SEASON, match_id=(f"u{gw}" if gw <= real_through else f"fpl{80 + gw}"), gw=gw)
          for gw in range(1, last_gw + 1)]
    pd.DataFrame(pm).to_parquet(h / f"understat_matches_{TAG}.parquet", index=False)
    monkeypatch.setattr(bc, "HISTORY", h)
    monkeypatch.setattr(bc, "ALL_SEASONS", h / "all_seasons_fixed.parquet")
    monkeypatch.setattr(bc, "UNDERSTAT", h / "understat_season_aggregates.parquet")
    monkeypatch.setitem(bc.MANUAL, SEASON, {})            # the real pins are not this test's subject
    monkeypatch.setitem(bc.MANUAL_OVERRIDES, SEASON, {})
    return h


def _ids(cw):
    return {int(r.element): str(r.understat_id) for r in cw.itertuples()}


def test_understat_last_gw_is_read_from_the_per_match_file(tmp_path, monkeypatch):
    h = _history(tmp_path, monkeypatch)
    assert bc.understat_last_gw(SEASON) == 8
    assert bc.understat_last_gw(SEASON, history=h) == 8


def test_understat_last_gw_follows_the_data_not_a_constant(tmp_path, monkeypatch):
    _history(tmp_path, monkeypatch, real_through=9)
    assert bc.understat_last_gw(SEASON) == 9


def test_no_cap_when_understat_serves_every_gameweek(tmp_path, monkeypatch):
    _history(tmp_path, monkeypatch, real_through=11)
    assert bc.understat_last_gw(SEASON) is None


def test_no_cap_without_a_per_match_file(tmp_path, monkeypatch):
    h = _history(tmp_path, monkeypatch)
    (h / f"understat_matches_{TAG}.parquet").unlink()
    assert bc.understat_last_gw(SEASON) is None


def test_henderson_keeps_his_id_while_understat_stops_at_gw8(tmp_path, monkeypatch):
    """The GW11 case: 270 Understat minutes against 540 FPL minutes in all -- but 270 against 270 through GW8."""
    _history(tmp_path, monkeypatch)
    cw, stats = bc.build(SEASON, verbose=False)
    ids = _ids(cw)
    assert ids.get(198) == "7702", ids
    assert ids.get(534) == "13713", ids
    assert stats["audit_through_gw"] == 8


def test_a_wrong_match_is_still_dropped_under_the_cap(tmp_path, monkeypatch):
    """Like for like still catches a different player: 720 FPL minutes through GW8 against Understat's 100."""
    _history(tmp_path, monkeypatch)
    cw, stats = bc.build(SEASON, verbose=False)
    assert 77 not in _ids(cw)
    assert stats["audit_dropped"] == 1


def test_full_season_comparison_returns_once_understat_is_back(tmp_path, monkeypatch):
    """No fallback rows left: the audit compares full-season totals again. With Understat's listing current (540)
    Henderson matches; with a listing still at 270 he is dropped -- proof that no cap is applied any more."""
    current = [dict(r, time="540") if r["id"] == "7702" else dict(r, time="990") if r["id"] == "13713" else r
               for r in US_FROZEN]
    _history(tmp_path, monkeypatch, real_through=11, us_rows=current)
    cw, stats = bc.build(SEASON, verbose=False)
    assert _ids(cw).get(198) == "7702"
    assert stats["audit_through_gw"] is None


def test_full_season_comparison_has_no_cap_to_hide_behind(tmp_path, monkeypatch):
    _history(tmp_path, monkeypatch, real_through=11)
    cw, _ = bc.build(SEASON, verbose=False)
    assert 198 not in _ids(cw)
