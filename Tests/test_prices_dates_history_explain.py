"""B27, B33, B36, B39 (measured 2026-10-04).

B27 -- price snapshots are burst-sampled, 6-8 days apart. get_price_movements(window_days=1)
reported window_days_requested 1 beside window_hours_actual 153.8 and nothing reconciling them,
so "who rose in the last day?" was answered off six days.

B33 -- as_of took anything pandas could parse: "01/02/2026" became 2 January (month-first)
while the archive's own dates are parsed day-first, "now" bound the answer to the wall clock,
and "2030" was accepted as 1 January 2030. Only prose was refused.

B36 -- the archive stores 4 Ipswich-Arsenal rows across the last three seasons, 2 spelled
"Ipswich" (2024-25) and 2 spelled "Ipswich Town" (2026-27), of which 2 are played. Each
season's rows are mapped into that season's own club names, but club_rows filters on ONE name,
so a question about "Ipswich Town" saw none of the older rows and the tool answered
"0 meetings ... a stated zero".

B39 -- the constants census appended the penalties sub-line to the list of LINES, so Nicolas
Jackson's GW6 breakdown said "4 of 9 lines are constants" when three of the nine were.
"""
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
for p in (str(REPO), str(REPO / "squad")):
    if p not in sys.path:
        sys.path.insert(0, p)

import league_table as lt                                  # noqa: E402


# ---- B33: the as_of format ------------------------------------------------------------
@pytest.mark.parametrize("good", ["2026-08-01", "2026-12-31",
                                  "2026-08-01T12:00:00", "2026-08-01T12:00:00Z",
                                  "2026-09-05T15:00:00+01:00"])
def test_an_unambiguous_date_or_iso_timestamp_is_accepted(good):
    ts, err = lt.parse_as_of(good)
    assert err is None, (good, err)
    assert ts is not None and ts.tzinfo is None


@pytest.mark.parametrize("bad", ["01/02/2026", "1/2/26", "2026/08/01", "now", "today",
                                 "2030", "2026", "last Tuesday", "August 2026", "",
                                 "2026-8-1", "20260801"])
def test_an_ambiguous_as_of_is_refused_and_the_format_is_shown(bad):
    ts, err = lt.parse_as_of(bad)
    assert ts is None, (bad, ts)
    assert "YYYY-MM-DD" in err, (bad, err)


def test_the_refusal_names_what_was_sent():
    _, err = lt.parse_as_of("01/02/2026")
    assert "01/02/2026" in err


# ---- B27: the widened window ---------------------------------------------------------
def test_a_widened_window_says_so_in_the_same_block(tmp_path):
    # Data-independent since 2026-10-16: the live archive (205 snapshots after the 15 Oct refresh) is dense enough
    # that a 1-day window no longer widens, so the test skipped. Two snapshots three days apart -- the burst sampling
    # of B27 in miniature -- make a 1-day window widen on every machine; the assertions are unchanged.
    import gzip
    import json
    import prices_tool as pt
    for stamp in ("20261001T120000Z", "20261004T120000Z"):
        with gzip.open(tmp_path / f"{stamp}.json.gz", "wt", encoding="utf-8") as fh:
            json.dump({"elements": [{"id": 1, "first_name": "A", "second_name": "Player", "now_cost": 50,
                                     "cost_change_start": 0, "cost_change_start_fall": 0, "cost_change_event": 0}]}, fh)
    out = pt.movements(window_days=1, directory=tmp_path)
    obs = out["observation"]
    assert obs["window_widened"] is True
    note = obs["window_widened_note"]
    assert "1 day" in note and "widened" in note
    assert str(round(obs["window_hours_actual"] / 24, 1)) in note


def test_a_window_that_was_not_widened_says_false(monkeypatch):
    import prices_tool as pt
    out = pt.movements(window_days=365, directory=None)
    if out.get("error"):
        pytest.skip("no price snapshots on this machine")
    obs = out["observation"]
    assert obs["window_widened"] is False
    assert obs.get("window_widened_note") is None


# ---- B36: one spelling across seasons ------------------------------------------------
def test_a_club_whose_name_changed_between_seasons_keeps_its_meetings():
    """The archive's own rows are the check: 4 Ipswich-Arsenal rows across three seasons, 2 of
    them played, so the head-to-head must find 2 -- not 0."""
    import model_tools as mt
    raw = mt._ms_archive(["2024-25", "2025-26", "2026-27"])
    ips = raw["home"].isin(["Ipswich", "Ipswich Town"])
    ars = raw["away"] == "Arsenal"
    both = raw[(ips & ars) | ((raw["home"] == "Arsenal") & raw["away"].isin(["Ipswich", "Ipswich Town"]))]
    played = int(both["home_goals"].notna().sum())
    out = mt.get_match_stats(team="Ipswich Town", opponent="Arsenal", stats=["goals"], seasons=3)
    assert "error" not in out, out.get("error")
    h2h = out["head_to_head"]
    assert h2h["matches_counted"] == played, (h2h["matches_counted"], played)
    assert played > 0, "the archive holds no played meeting; this test would prove nothing"
    assert sum(h2h["record"].values()) == played


# ---- B39: the constants census -------------------------------------------------------
def test_the_constants_count_counts_lines_only():
    import model_tools as mt
    hit = mt._q("SELECT element FROM players_live WHERE name ILIKE %s LIMIT 1",
                ("%Nicolas Jackson%",))
    if not hit:
        pytest.skip("Nicolas Jackson is not in this data")
    # The frame's own gameweek, computed (2026-10-16): a fixed gw=6 skipped once GW6 had been played.
    try:
        _, frame_gw, _ = mt._frame_raw()
    except (FileNotFoundError, RuntimeError) as e:
        pytest.skip(f"no production frame: {e}")
    out = mt.explain_prediction(hit[0]["element"], gw=int(frame_gw))
    if "error" in out:
        pytest.skip(f"no breakdown available: {out['error'][:60]}")
    d = out["detail"]                                            # 2026-10-09: the technical parts sit under detail
    n_const_lines = sum(1 for l in d["lines"] if l["source"] == "constant")
    assert n_const_lines == 3, [l["term"] for l in d["lines"] if l["source"] == "constant"]
    assert f"{n_const_lines} of 9 lines are constants" in d["summary"], d["summary"]
    # the penalties sub-line is still reported, just not counted as one of the nine
    goals = next(l for l in d["lines"] if l["term"] == "goals")
    assert goals["penalties"]["source"] == "constant"
    assert "penalt" in d["summary"].lower()
    assert "4 of 9" not in d["summary"]
    assert list(out)[0] == "summary_plain" and "lines" not in out
