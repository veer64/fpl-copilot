"""Prompt R2 (3-4 Nov 2026): the understat fallback (eval/understat_fallback.py) and the understat-back check
(eval/understat_back_check.py). No network: the season file, crosswalk and per-match files are tiny parquet/csv files in
a tmp data dir; the probe, the step commands and the ntfy push are fakes.

The contract:
  * fallback rows are shaped EXACTLY like understat_matches.py's rows (the per-match schema is pinned by
    Tests/test_understat_ingest.py::test_per_match_schema_matches_2025_26, so no new column): match_id "fpl<fixture>",
    npxG := FPL xG (FPL identifies penalty misses only), npg := goals, xA := FPL xA, no shots/xGChain/xGBuildup;
  * applying the fallback for a gameweek REPLACES any rows of that gameweek (idempotent) and never touches other
    gameweeks' real rows; the sidecar names source = 'fpl_fallback'; the FILE is the truth for "which gameweeks are
    served by the fallback" (match_id prefix), the sidecar is the label;
  * the understat-back check probes with ONE request, does nothing when no fallback rows exist, re-ingests from
    understat when it answers real JSON, and pings ONCE per replaced gameweek.
"""
import io
import json
import sys
import urllib.error
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "eval"))

import understat_fallback as usf      # noqa: E402
import understat_back_check as ubc    # noqa: E402

SEASON, TAG = "2026-27", "2026_27"
NOW = datetime(2026, 11, 4, 1, 0, tzinfo=timezone.utc)
MAINTENANCE_HTML = b"<!DOCTYPE html><html><head><title>Understat.com</title></head><body>We will come back soon</body></html>"
REF_COLS = ["season", "match_id", "match_datetime", "match_date", "understat_player_id", "player_name", "team", "opponent",
            "h_a", "position", "positionOrder", "minutes", "goals", "own_goals", "npg", "assists", "shots", "key_passes",
            "xG", "xA", "npxG", "xGChain", "xGBuildup", "yellow_card", "red_card", "gw", "gw_ambiguous", "pulled_at"]


def _real_rows(gws, n=2):
    rows = []
    for g in gws:
        for i in range(n):
            rows.append(dict(season=SEASON, match_id=str(30000 + 10 * g + i), match_datetime=pd.Timestamp(2026, 8, 10 + g, 15),
                             match_date=pd.Timestamp(2026, 8, 10 + g), understat_player_id=str(8000 + i), player_name=f"P{i}",
                             team="Arsenal", opponent="Chelsea", h_a="h", position="FW", positionOrder=11, minutes=90,
                             goals=1.0, own_goals=0, npg=1.0, assists=0, shots=3, key_passes=1, xG=0.7, xA=0.1, npxG=0.7,
                             xGChain=0.9, xGBuildup=0.2, yellow_card=0, red_card=0, gw=g, gw_ambiguous=False,
                             pulled_at="2026-10-26T18:23:01+00:00"))
    df = pd.DataFrame(rows)
    for c in ("season", "match_id", "understat_player_id", "player_name", "team", "opponent", "h_a", "position", "pulled_at"):
        df[c] = df[c].astype("string")
    return df[REF_COLS]


def _seed(tmp_path, api_gws=(1, 2, 3), real_gws=(1, 2), with_prior=True):
    h = tmp_path / "history"
    h.mkdir(parents=True)
    (tmp_path / "live").mkdir()
    rows = []
    for g in api_gws:
        for el, nm, tm, pos, mins, xg, xa, goals, kp in ((1, "A One", "Arsenal", "FWD", 90, 0.55, 0.12, 1, 2),
                                                        (2, "B Two", "Chelsea", "MID", 70, 0.20, 0.31, 0, 3),
                                                        (3, "C Three", "Spurs", "GK", 0, 0.0, 0.0, 0, 0),
                                                        (9, "No Crosswalk", "Leeds", "DEF", 90, 0.05, 0.02, 0, 0)):
            rows.append(dict(season=SEASON, GW=g, element=el, fixture=100 * g + el, name=nm, team=tm, position=pos,
                             minutes=mins, kickoff_time=f"2026-08-{10 + g:02d}T14:00:00Z", opponent_team=5, was_home=el % 2 == 1,
                             expected_goals=str(xg), expected_assists=str(xa), goals_scored=goals, assists=0,
                             key_passes=float(kp) if el != 2 else float("nan"), own_goals=0, yellow_cards=0, red_cards=0))
    pd.DataFrame(rows).to_parquet(h / f"fpl_api_{TAG}.parquet", index=False)
    pd.DataFrame([dict(element=1, understat_id="8000"), dict(element=2, understat_id="8001"),
                  dict(element=3, understat_id="8002")]).to_csv(h / f"crosswalk_{TAG}.csv", index=False)
    _real_rows(real_gws).to_parquet(h / f"understat_matches_{TAG}.parquet", index=False)
    if with_prior:
        _real_rows((1,)).assign(season="2025-26").to_parquet(h / "understat_matches_2025_26.parquet", index=False)
    return h


# ----------------------------------------------------------------------------- rows + apply
def test_fallback_rows_match_the_per_match_schema_and_the_c1_rule(tmp_path):
    h = _seed(tmp_path)
    fb = usf.fallback_rows(tmp_path, SEASON, [3], now=NOW)
    ref = pd.read_parquet(h / "understat_matches_2025_26.parquet").iloc[0:0]
    assert list(fb.columns) == list(ref.columns)
    mism = {c: (str(fb[c].dtype), str(ref[c].dtype)) for c in ref.columns if fb[c].dtype != ref[c].dtype}
    assert not mism, mism
    # minutes > 0 only, crosswalk-mapped only (element 9 has no understat id, element 3 played 0 min)
    assert sorted(fb["understat_player_id"].tolist()) == ["8000", "8001"]
    a = fb[fb["understat_player_id"] == "8000"].iloc[0]
    assert a["match_id"] == "fpl301" and a["match_id"].startswith(usf.MATCH_PREFIX)
    assert a["xG"] == pytest.approx(0.55) and a["npxG"] == pytest.approx(0.55)        # C1: FPL names no penalty attempts/goals
    assert a["xA"] == pytest.approx(0.12) and a["goals"] == 1.0 and a["npg"] == 1.0
    assert a["position"] == "FW" and a["minutes"] == 90 and a["h_a"] == "h" and a["gw"] == 3
    assert a["shots"] == 0 and a["xGChain"] == 0.0 and a["xGBuildup"] == 0.0 and not a["gw_ambiguous"]
    assert str(a["match_datetime"]) == "2026-08-13 14:00:00" and a["pulled_at"] == NOW.isoformat()
    b = fb[fb["understat_player_id"] == "8001"].iloc[0]
    assert b["key_passes"] == 0 and b["position"] == "MC"                                # NaN key passes -> 0


def test_apply_fallback_replaces_only_its_gameweek_idempotently_and_labels_the_sidecar(tmp_path):
    h = _seed(tmp_path, api_gws=(1, 2, 3), real_gws=(1, 2))
    p = h / f"understat_matches_{TAG}.parquet"
    before = pd.read_parquet(p)
    r1 = usf.apply_fallback(tmp_path, SEASON, [3], reason="step 'understat_matches' exited 1 ... JSONDecodeError", now=NOW)
    r2 = usf.apply_fallback(tmp_path, SEASON, [3], reason="again", now=NOW)
    after = pd.read_parquet(p)
    assert r1["rows"] == 2 and r2["rows"] == 2 and r1["gws"] == [3]
    assert list(after.columns) == REF_COLS
    real = after[after["gw"].isin([1, 2])].reset_index(drop=True)
    pd.testing.assert_frame_equal(real, before.reset_index(drop=True))                 # other gameweeks untouched
    assert (after[after["gw"] == 3]["match_id"].str.startswith("fpl")).all() and len(after[after["gw"] == 3]) == 2
    side = json.loads(usf.sidecar_path(tmp_path, SEASON).read_text(encoding="utf-8"))
    assert side["source"] == "fpl_fallback" and side["gws"] == [3] and side["match_ids"] == ["fpl301", "fpl302"]
    assert "JSONDecodeError" in side["reason"]
    assert usf.fallback_gws(tmp_path, SEASON) == [3]
    # a real understat rewrite (no fpl rows) is the truth: the fallback is gone even if the sidecar lingers
    _real_rows((1, 2, 3)).to_parquet(p, index=False)
    assert usf.fallback_gws(tmp_path, SEASON) == []


def test_apply_fallback_refuses_an_unfinished_or_absent_gameweek(tmp_path):
    """Leakage rule: fallback rows only for gameweeks the season file (finished + data_checked by step 1) carries."""
    _seed(tmp_path, api_gws=(1, 2, 3))
    with pytest.raises(ValueError, match="GW7"):
        usf.fallback_rows(tmp_path, SEASON, [7], now=NOW)


# ----------------------------------------------------------------------------- the probe
class _Resp(io.BytesIO):
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_probe_once_tells_json_from_the_maintenance_page_and_from_a_timeout():
    calls = []

    def html(req, timeout):
        calls.append(req.full_url); return _Resp(MAINTENANCE_HTML)

    def js(req, timeout):
        calls.append(req.full_url); return _Resp(json.dumps({"dates": [{"id": 1, "isResult": True}] * 3}).encode())

    def boom(req, timeout):
        calls.append(req.full_url); raise urllib.error.URLError("timed out")

    ok, why = usf.probe_once(opener=html)
    assert ok is False and "not JSON" in why and "We will come back soon" in why
    ok, why = usf.probe_once(opener=boom)
    assert ok is False and "timed out" in why
    ok, why = usf.probe_once(opener=js)
    assert ok is True and "3 dates" in why
    assert len(calls) == 3 and all(u.startswith("https://understat.com/getLeagueData/EPL/") for u in calls)   # one request each


# ----------------------------------------------------------------------------- the understat-back check
class FakeSteps:
    def __init__(self, h, fail=None):
        self.h, self.fail, self.calls = h, fail, []

    def __call__(self, args, timeout):
        name = Path(args[0]).stem + ("_combine" if "--combine" in args else "")
        self.calls.append(name)
        if self.fail == name:
            return 1, f"{name}: boom"
        if name == "understat_matches":        # the real step rewrites the file from understat: no fpl rows any more
            _real_rows((1, 2, 3)).to_parquet(self.h / f"understat_matches_{TAG}.parquet", index=False)
        return 0, f"{name} ok"


def test_back_check_does_nothing_without_fallback_rows(tmp_path):
    h = _seed(tmp_path)
    probes, pushes = [], []
    rc = ubc.check(SEASON, data_dir=tmp_path, probe=lambda: probes.append(1) or (True, "json"),
                   run_cmd=FakeSteps(h), push=lambda t, m: pushes.append((t, m)) or 200, now=NOW)
    assert rc == 0 and probes == [] and pushes == []
    assert "no fallback rows" in (tmp_path / "live" / "UNDERSTAT_BACK.txt").read_text(encoding="utf-8")


def test_back_check_waits_while_understat_is_down(tmp_path):
    h = _seed(tmp_path)
    usf.apply_fallback(tmp_path, SEASON, [3], reason="down", now=NOW)
    steps, pushes = FakeSteps(h), []
    rc = ubc.check(SEASON, data_dir=tmp_path, probe=lambda: (False, "not JSON (We will come back soon)"),
                   run_cmd=steps, push=lambda t, m: pushes.append((t, m)) or 200, now=NOW)
    assert rc == 0 and steps.calls == [] and pushes == []
    assert usf.fallback_gws(tmp_path, SEASON) == [3]
    assert "still down" in (tmp_path / "live" / "UNDERSTAT_BACK.txt").read_text(encoding="utf-8")


def test_back_check_replaces_the_fallback_rows_and_pings_once_per_gameweek(tmp_path):
    h = _seed(tmp_path)
    usf.apply_fallback(tmp_path, SEASON, [3], reason="down", now=NOW)
    (tmp_path / "live" / "ingest_manifest_latest.json").write_text(json.dumps({"understat_fallback_gws": [3]}), encoding="utf-8")
    steps, pushes = FakeSteps(h), []
    rc = ubc.check(SEASON, data_dir=tmp_path, probe=lambda: (True, "JSON, 30 dates"), run_cmd=steps,
                   push=lambda t, m: pushes.append((t, m)) or 200, now=NOW)
    assert rc == 0
    assert steps.calls == ["understat_matches", "build_understat_aggregates", "build_understat_aggregates_combine", "build_crosswalk"]
    assert usf.fallback_gws(tmp_path, SEASON) == []
    assert not usf.sidecar_path(tmp_path, SEASON).exists()
    assert json.loads((tmp_path / "live" / "ingest_manifest_latest.json").read_text(encoding="utf-8"))["understat_fallback_gws"] == []
    assert pushes == [("FPL Copilot: understat is back", "GW3 replaced with real xG.")]
    txt = (tmp_path / "live" / "UNDERSTAT_BACK.txt").read_text(encoding="utf-8")
    assert txt.startswith("REPLACED") and "GW[3]" in txt and "ntfy 200" in txt
    # a second tick: nothing left to do, no second ping
    rc2 = ubc.check(SEASON, data_dir=tmp_path, probe=lambda: (True, "json"), run_cmd=steps,
                    push=lambda t, m: pushes.append((t, m)) or 200, now=NOW)
    assert rc2 == 0 and len(pushes) == 1 and len(steps.calls) == 4


def test_back_check_keeps_the_fallback_when_the_reingest_fails(tmp_path):
    h = _seed(tmp_path)
    usf.apply_fallback(tmp_path, SEASON, [3], reason="down", now=NOW)
    steps, pushes = FakeSteps(h, fail="build_understat_aggregates"), []
    rc = ubc.check(SEASON, data_dir=tmp_path, probe=lambda: (True, "json"), run_cmd=steps,
                   push=lambda t, m: pushes.append((t, m)) or 200, now=NOW)
    assert rc == 1 and pushes == []
    txt = (tmp_path / "live" / "UNDERSTAT_BACK.txt").read_text(encoding="utf-8")
    assert txt.startswith("FAILED") and "build_understat_aggregates" in txt
