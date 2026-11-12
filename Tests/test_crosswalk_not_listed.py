"""Prompt U1 (12 Nov 2026): two guards added to eval/build_crosswalk.py while understat.com is down.

1. The NOT_LISTED allowance -- an evidenced, dated "Understat has not listed this player yet" entry that the
   weekly runner's ACTION REQUIRED check and the coverage test honour. It expires on its date (UTC) or as soon as
   understat is restored on the volume (the understat-back check's markers, or no fallback rows left in the
   per-match file), whichever comes first; after that the element must be matched like anyone else.
2. The MANUAL conflict alarm -- a pinned element the automatic passes matched to a DIFFERENT id raises a clear
   AssertionError and nothing is overwritten (Understat may have re-listed the player, or the pin is stale).
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "eval"))

import build_crosswalk as bc  # noqa: E402

SEASON, TAG = "2026-27", "2026_27"
NOW = datetime(2026, 11, 12, 15, 0, tzinfo=timezone.utc)
WAITING = "WAITING -- understat still down for GW[9, 10]: not JSON (26719 bytes: <!DOCTYPE html> ...)"


def _data_dir(tmp_path, fallback=True, back_first_line=WAITING, pings=None, manifest=None):
    """A data dir with the three things the allowance reads: the per-match file (fallback rows or not), the
    understat-back status file, and the back-check's durable markers."""
    h, live = tmp_path / "history", tmp_path / "live"
    h.mkdir()
    live.mkdir()
    rows = [dict(gw=8, match_id="u71"), dict(gw=8, match_id="u72")]
    if fallback:
        rows += [dict(gw=9, match_id="fpl81"), dict(gw=10, match_id="fpl91")]
    pd.DataFrame(rows).to_parquet(h / f"understat_matches_{TAG}.parquet", index=False)
    if back_first_line is not None:
        (live / "UNDERSTAT_BACK.txt").write_text(back_first_line + "\nunderstat-back check 2026-27 -- ...\n",
                                                 encoding="utf-8")
    if pings is not None:
        (live / "understat_back_pings.json").write_text(json.dumps(pings), encoding="utf-8")
    if manifest is not None:
        (live / "ingest_manifest_latest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return tmp_path


@pytest.fixture
def allowance(monkeypatch):
    monkeypatch.setitem(bc.NOT_LISTED, SEASON, {645: ("Mouzakitis evidence (test)", "2026-12-31"),
                                                601: ("Williams-Barnett evidence (test)", "2026-12-31")})
    return bc.NOT_LISTED[SEASON]


# ------------------------------------------------------------------ the allowance
def test_allowance_in_force_while_understat_is_down(tmp_path, allowance):
    d = _data_dir(tmp_path)
    assert not bc.understat_restored(d, SEASON)
    assert bc.not_listed_allowance(SEASON, d, now=NOW) == {645: "Mouzakitis evidence (test)",
                                                            601: "Williams-Barnett evidence (test)"}


def test_allowance_expires_on_its_date(tmp_path, allowance):
    d = _data_dir(tmp_path)
    last_day = datetime(2026, 12, 31, 23, 59, tzinfo=timezone.utc)
    assert set(bc.not_listed_allowance(SEASON, d, now=last_day)) == {645, 601}
    assert bc.not_listed_allowance(SEASON, d, now=datetime(2027, 1, 1, 0, 0, tzinfo=timezone.utc)) == {}


def test_allowance_ends_when_the_back_check_has_pinged(tmp_path, allowance):
    d = _data_dir(tmp_path, pings={"9": {"at": "2026-11-20T10:49:00+00:00", "http": 200}})
    assert bc.understat_restored(d, SEASON)
    assert bc.not_listed_allowance(SEASON, d, now=NOW) == {}


def test_allowance_ends_on_a_replaced_status_line(tmp_path, allowance):
    d = _data_dir(tmp_path, back_first_line="REPLACED GW[9, 10] from understat (JSON, 380 dates); no new ping")
    assert bc.not_listed_allowance(SEASON, d, now=NOW) == {}


def test_allowance_ends_on_the_manifest_marker(tmp_path, allowance):
    d = _data_dir(tmp_path, manifest={"understat_restored_at": "2026-11-20T10:49:00+00:00"})
    assert bc.not_listed_allowance(SEASON, d, now=NOW) == {}


def test_allowance_ends_when_no_fallback_rows_remain(tmp_path, allowance):
    """The per-match file is the truth the back-check itself relies on: no `fpl` rows -> understat is serving
    the season again (or never fell back), so nothing is 'not listed yet' for want of a listing."""
    d = _data_dir(tmp_path, fallback=False)
    assert bc.understat_restored(d, SEASON)
    assert bc.not_listed_allowance(SEASON, d, now=NOW) == {}


def test_allowance_survives_an_unreadable_live_dir(tmp_path, allowance):
    """No live dir and no per-match file at all (a bare test data dir): nothing says 'restored', the dated
    allowance holds -- the item must not fire for want of a status file."""
    assert set(bc.not_listed_allowance(SEASON, tmp_path, now=NOW)) == {645, 601}


def test_allowance_is_empty_for_a_season_without_entries(tmp_path):
    assert bc.not_listed_allowance("2023-24", _data_dir(tmp_path), now=NOW) == {}


def test_the_real_entries_are_evidenced_and_expire_2026_12_31():
    entries = bc.NOT_LISTED["2026-27"]
    assert set(entries) == {645, 601}
    for el, (why, exp) in entries.items():
        assert isinstance(el, int)
        assert exp == "2026-12-31"
        assert "Mouzakitis" in why or "Williams-Barnett" in why
        assert "Understat" in why and len(why) > 80


# ------------------------------------------------------------------ the conflict alarm
US = pd.DataFrame([dict(id="6874", player_name="Yann Gboho"), dict(id="9999", player_name="Somebody Else")])


def test_manual_pin_on_an_unmatched_element_is_applied():
    matched = {}
    ev = bc._apply_manual(matched, {655: ("6874", "why")}, US)
    assert matched[655][:3] == ("6874", "Yann Gboho", "manual")
    assert ev == {655: "why"}


def test_manual_pin_absent_from_the_listing_keeps_the_id_with_an_unknown_name():
    matched = {}
    bc._apply_manual(matched, {170: ("11817", "why")}, US)
    assert matched[170][:3] == ("11817", "?", "manual")


def test_manual_pin_agreeing_with_the_automatic_match_is_fine():
    matched = {655: ("6874", "Yann Gboho", "exact", 100.0)}
    bc._apply_manual(matched, {655: ("6874", "why")}, US)
    assert matched[655][2] == "manual"


def test_manual_pin_conflicting_with_the_automatic_match_raises_and_never_overwrites():
    matched = {655: ("9999", "Somebody Else", "fuzzy", 91.0)}
    with pytest.raises(AssertionError, match="MANUAL CONFLICT.*element 655.*6874.*9999"):
        bc._apply_manual(matched, {655: ("6874", "why")}, US)
    assert matched[655] == ("9999", "Somebody Else", "fuzzy", 91.0)


def test_manual_pin_whose_id_belongs_to_another_element_raises():
    matched = {12: ("6874", "Yann Gboho", "exact", 100.0)}
    with pytest.raises(AssertionError, match="collides"):
        bc._apply_manual(matched, {655: ("6874", "why")}, US)
    assert 655 not in matched


def test_a_declared_override_corrects_exactly_the_named_wrong_automatic_id():
    """Morato's case (2025-26 element 511): the club+token pass hands him Jota Silva's 12766 and the pin
    corrects it -- declared in MANUAL_OVERRIDES, so it applies; a THIRD id would still be a conflict."""
    us = pd.DataFrame([dict(id="13068", player_name="Morato"), dict(id="12766", player_name="Jota Silva")])
    matched = {511: ("12766", "Jota Silva", "club+token", 66.7)}
    bc._apply_manual(matched, {511: ("13068", "why")}, us, overrides={511: "12766"})
    assert matched[511][:3] == ("13068", "Morato", "manual")
    matched = {511: ("7777", "Someone", "fuzzy", 90.0)}
    with pytest.raises(AssertionError, match="MANUAL CONFLICT"):
        bc._apply_manual(matched, {511: ("13068", "why")}, us, overrides={511: "12766"})
    assert matched[511][0] == "7777"


def test_the_real_overrides_name_only_morato():
    assert bc.MANUAL_OVERRIDES == {"2025-26": {511: "12766"}}
    assert bc.MANUAL["2025-26"][511][0] == "13068"
