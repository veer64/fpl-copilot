"""One row per (season, element, fixture) in the history stack -- KNOWN_ISSUES #17, closed 2026-11-14 (M1).

The cause, located by the X2 review: the vaastav-sourced archive carried REPEATED fixture rows of two
kinds, and the per-gameweek collapse summed them.
  * 2025-26: ten byte-identical pairs (element 100, gameweeks 1-9; element 391, gameweek 1), already
    repeated in the public vaastav 2025-26 file. In the frame of record they doubled those players'
    expected minutes and expected points on ten rows and their ACTUAL points on six (the D1 merge in
    assemble_fixtures fanned each fixture row out twice; the minutes model collapsed them as a double).
  * 2019-20: fifty-nine phantom rows -- fixture 275 was postponed from gameweek 29 and played in gameweek
    39; the archive kept a 0-minute row at the original gameweek beside the real row.
The rule (squad/season_stack.dedupe_fixture_rows): keep the PLAYED row -- most minutes, then the later
gameweek, then the first of exact copies. It lives in the stack builder (eval/fetch_fpl_history.combine),
so every rebuilt stack is right, and the frozen archive was rewritten once through the same function.

Pure tests on synthetic frames always run; the two data guards skip when the files are not on disk.
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "squad"))
sys.path.insert(0, str(ROOT / "eval"))

import season_stack  # noqa: E402
from season_stack import FIXTURE_ROW_KEY, dedupe_fixture_rows  # noqa: E402

ARCHIVE = ROOT / "data" / "history" / "all_seasons_fixed.parquet"
FRAME_2526 = ROOT / "data" / "walkforward_h6_2025_26.parquet"


def _rows(*rows):
    cols = ["season", "element", "fixture", "GW", "minutes", "total_points", "name"]
    return pd.DataFrame([dict(zip(cols, r)) for r in rows])


def test_identical_copies_keep_one_and_it_is_the_first():
    df = _rows(("2025-26", 100, 1, 1, 1, 1, "a"), ("2025-26", 7, 1, 1, 90, 2, "b"), ("2025-26", 100, 1, 1, 1, 1, "a"))
    clean, removed = dedupe_fixture_rows(df)
    assert len(clean) == 2 and len(removed) == 1
    assert list(clean["element"]) == [100, 7], "survivors keep their original order"
    assert list(removed.index) == [2], "the later exact copy is the one removed"


def test_a_postponed_fixture_keeps_the_played_row():
    df = _rows(("2019-20", 11, 275, 29, 0, 0, "phantom"), ("2019-20", 11, 275, 39, 90, 2, "played"))
    clean, removed = dedupe_fixture_rows(df)
    assert list(clean["name"]) == ["played"] and list(removed["name"]) == ["phantom"]
    # the same pair in the other order
    clean, removed = dedupe_fixture_rows(df.iloc[::-1].reset_index(drop=True))
    assert list(clean["name"]) == ["played"] and list(removed["name"]) == ["phantom"]


def test_an_unused_substitute_keeps_the_row_at_the_gameweek_the_match_was_played():
    df = _rows(("2019-20", 3, 275, 29, 0, 0, "phantom"), ("2019-20", 3, 275, 39, 0, 0, "real, did not play"))
    clean, removed = dedupe_fixture_rows(df)
    assert list(clean["name"]) == ["real, did not play"] and list(removed["GW"]) == [29]


def test_two_different_played_rows_for_one_fixture_are_refused():
    """That is not a recording duplicate; choosing between them would invent data."""
    df = _rows(("2025-26", 5, 9, 2, 60, 2, "a"), ("2025-26", 5, 9, 2, 45, 1, "a"))
    with pytest.raises(ValueError, match="DIFFERENT rows"):
        dedupe_fixture_rows(df)


def test_a_clean_frame_is_returned_untouched_and_the_rule_is_idempotent():
    df = _rows(("2025-26", 1, 1, 1, 90, 2, "a"), ("2025-26", 1, 2, 2, 90, 6, "a"), ("2024-25", 1, 1, 1, 0, 0, "x"))
    clean, removed = dedupe_fixture_rows(df)
    assert clean is df and len(removed) == 0
    dirty = pd.concat([df, df.iloc[[0]]], ignore_index=True)
    once, r1 = dedupe_fixture_rows(dirty)
    twice, r2 = dedupe_fixture_rows(once)
    assert len(r1) == 1 and len(r2) == 0 and twice is once
    pd.testing.assert_frame_equal(once, df)


def test_the_same_fixture_id_in_two_seasons_is_not_a_duplicate():
    df = _rows(("2024-25", 100, 1, 1, 90, 2, "a"), ("2025-26", 100, 1, 1, 90, 2, "a"))
    clean, removed = dedupe_fixture_rows(df)
    assert clean is df and len(removed) == 0


def test_dtypes_and_columns_survive():
    df = _rows(("2025-26", 100, 1, 1, 1, 1, "a"), ("2025-26", 100, 1, 1, 1, 1, "a"), ("2025-26", 8, 3, 1, 90, 2, "b"))
    df["value"] = np.array([45, 45, 60], dtype="int64")
    df["flag"] = pd.Series([True, True, None], dtype="object")
    clean, _ = dedupe_fixture_rows(df)
    assert list(clean.columns) == list(df.columns) and (clean.dtypes == df.dtypes).all()


def test_combine_builds_a_stack_with_one_row_per_fixture(tmp_path, monkeypatch):
    """THE BUILDER: an archive that still carries repeated rows (the server's does until it is rewritten)
    must still combine into a clean stack, and the API season's rows must all survive."""
    import fetch_fpl_history as ff
    base = _rows(("2019-20", 11, 275, 29, 0, 0, "phantom"), ("2019-20", 11, 275, 39, 90, 2, "played"),
                 ("2025-26", 100, 1, 1, 1, 1, "copy"), ("2025-26", 100, 1, 1, 1, 1, "copy"),
                 ("2025-26", 7, 1, 1, 90, 2, "b"))
    api = _rows(("2026-27", 100, 1, 1, 90, 5, "new season, same ids"), ("2026-27", 7, 1, 1, 12, 1, "c"))
    base.to_parquet(tmp_path / "all_seasons_fixed.parquet", index=False)
    api.to_parquet(tmp_path / "fpl_api_2026_27.parquet", index=False)
    monkeypatch.setattr(ff, "HIST", tmp_path)
    monkeypatch.setattr(ff, "STACK", tmp_path / "all_seasons_fixed.parquet")
    out = ff.combine("2026-27")
    got = pd.read_parquet(out)
    assert not got.duplicated(FIXTURE_ROW_KEY).any()
    assert len(got) == 5 and (got["season"] == "2026-27").sum() == 2
    assert set(got.loc[got["season"] == "2019-20", "name"]) == {"played"}
    assert len(pd.read_parquet(tmp_path / "all_seasons_fixed.parquet")) == 5, "combine never rewrites the archive"


def test_dedupe_archive_rewrites_the_archive_once(tmp_path, monkeypatch):
    import fetch_fpl_history as ff
    base = _rows(("2019-20", 11, 275, 29, 0, 0, "phantom"), ("2019-20", 11, 275, 39, 90, 2, "played"),
                 ("2025-26", 100, 1, 1, 1, 1, "copy"), ("2025-26", 100, 1, 1, 1, 1, "copy"))
    p = tmp_path / "all_seasons_fixed.parquet"
    base.to_parquet(p, index=False)
    monkeypatch.setattr(ff, "HIST", tmp_path)
    monkeypatch.setattr(ff, "STACK", p)
    removed = ff.dedupe_archive()
    assert len(removed) == 2 and len(pd.read_parquet(p)) == 2
    assert (pd.read_parquet(p).dtypes == base.dtypes).all()
    assert len(ff.dedupe_archive()) == 0, "a second run finds nothing"


@pytest.mark.skipif(not ARCHIVE.exists(), reason="history stack not on disk")
def test_the_stacks_on_disk_carry_one_row_per_fixture():
    """Fails on a stack built before 2026-11-14: run `eval/fetch_fpl_history.py --dedupe-archive` and
    `--season <live season> --combine`, then rebuild the frames that read it."""
    for p in {ARCHIVE, season_stack.stack_path()}:
        s = pd.read_parquet(p, columns=FIXTURE_ROW_KEY)
        n = int(s.duplicated(FIXTURE_ROW_KEY).sum())
        assert n == 0, f"{p.name}: {n} repeated (season, element, fixture) rows -- KNOWN_ISSUES #17"


@pytest.mark.skipif(not (ARCHIVE.exists() and FRAME_2526.exists()), reason="2025-26 frame of record not on disk")
def test_the_2025_26_frame_of_record_no_longer_doubles_anyone():
    """What #17 looked like in the record: ten step-0 rows with expected minutes exactly twice the minutes
    model's and, on six of them, ACTUAL points twice the truth. Asserted for every step-0 row, not only
    the two players it happened to be."""
    frame = pd.read_parquet(FRAME_2526, columns=["cutoff", "gw", "element", "horizon_step", "n_fixtures",
                                                 "actual_points", "minutes", "e_minutes"])
    s0 = frame[frame["horizon_step"] == 0]
    h = pd.read_parquet(ARCHIVE, columns=["season", "element", "GW", "fixture", "minutes", "total_points", "position"])
    h = h[(h["season"] == "2025-26") & (h["position"] != "AM")].drop_duplicates(["element", "fixture"])
    truth = h.groupby(["element", "GW"], as_index=False).agg(pts=("total_points", "sum"), mins=("minutes", "sum"))
    j = s0.merge(truth, left_on=["element", "gw"], right_on=["element", "GW"], how="left")
    assert j["pts"].notna().all()
    bad = j[(j["actual_points"] != j["pts"]) | (j["minutes"] != j["mins"])]
    assert bad.empty, f"{len(bad)} step-0 rows disagree with the stack's truth, e.g. {bad.head(3).to_dict('records')}"
    single = s0[s0["n_fixtures"] == 1]
    assert float(single["minutes"].max()) <= 90, (
        "a single fixture cannot carry more than 90 realised minutes -- the record had 148 and 136 "
        "(element 100, gameweeks 8 and 9)")
