"""fetch_fixtures.combine -- the E0 stat fill survives the rebuild.

2026-09-22: the GW5 ingest rebuilt odds_all_seasons_with_2026_27.parquet from the frozen archive
plus a fresh slice and dropped the 640 cells eval/fill_e0_stats.py had filled two days earlier.
combine() now carries the fill's own columns from the previous combined file onto the fresh
slice rows, keyed on (Date, HomeTeam, AwayTeam), nulls only. Synthetic files in tmp_path.
"""
import inspect
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

REPO = Path(__file__).resolve().parents[1]
for p in (str(REPO), str(REPO / "squad"), str(REPO / "eval")):
    if p not in sys.path:
        sys.path.insert(0, p)

import fetch_fixtures as ff                                # noqa: E402
import fill_e0_stats as fe                                 # noqa: E402

NAT = float("nan")
COLS = ["Div", "Date", "Time", "HomeTeam", "AwayTeam", "FTHG", "FTAG", "FTR", "HTHG", "HTAG", "HTR",
        "Referee", "HS", "AS", "HST", "AST", "HF", "AF", "HC", "AC", "HY", "AY", "HR", "AR",
        "B365H", "B365D", "B365A", "season"]


def _row(season, date, home, away, hg, ag, stats=None, odds=(2.0, 3.4, 3.6)):
    s = stats or {}
    r = {"Div": "E0", "Date": date, "Time": "15:00", "HomeTeam": home, "AwayTeam": away,
         "FTHG": hg, "FTAG": ag, "FTR": ("H" if hg > ag else "A" if hg < ag else "D") if hg == hg else None,
         "HTHG": s.get("HTHG", NAT), "HTAG": s.get("HTAG", NAT), "HTR": s.get("HTR"),
         "Referee": s.get("Referee"), "B365H": odds[0], "B365D": odds[1], "B365A": odds[2], "season": season}
    for c in ("HS", "AS", "HST", "AST", "HF", "AF", "HC", "AC", "HY", "AY", "HR", "AR"):
        r[c] = s.get(c, NAT)
    return r


FILLED = {"HTHG": 1.0, "HTAG": 0.0, "HTR": "H", "Referee": "M Oliver", "HS": 12.0, "AS": 7.0,
          "HST": 5.0, "AST": 2.0, "HF": 9.0, "AF": 11.0, "HC": 6.0, "AC": 3.0, "HY": 1.0, "AY": 2.0,
          "HR": 0.0, "AR": 0.0}


@pytest.fixture()
def world(tmp_path, monkeypatch):
    """A frozen archive (one 2025-26 row, int64 stat columns as the real archive has), a fresh
    slice for 2026-27 (stats null, as fetch_fixtures writes it), and a PREVIOUS combined file
    whose 2026-27 rows carry the fill on two of three played matches."""
    hist = tmp_path / "history"
    hist.mkdir()
    base = pd.DataFrame([_row("2025-26", "17/05/2026", "Arsenal", "Chelsea", 1.0, 0.0, FILLED)], columns=COLS)
    for c in ("FTHG", "FTAG", "HTHG", "HTAG", "HS", "AS", "HST", "AST", "HF", "AF", "HC", "AC", "HY", "AY", "HR", "AR"):
        base[c] = base[c].astype("int64")
    base.to_parquet(hist / "odds_all_seasons.parquet", index=False)

    slice_rows = [
        _row("2026-27", "22/08/2026", "Hull City", "Man United", 2.0, 0.0, odds=(2.1, 3.4, 3.5)),
        _row("2026-27", "22/08/2026", "Arsenal", "Tottenham", 3.0, 0.0, odds=(1.5, 4.2, 6.0)),
        _row("2026-27", "29/08/2026", "Chelsea", "Hull City", 1.0, 1.0, odds=(1.3, 5.0, 9.0)),
        _row("2026-27", "05/09/2026", "Tottenham", "Chelsea", NAT, NAT, odds=(2.4, 3.3, 3.0)),
    ]
    sl = pd.DataFrame(slice_rows, columns=COLS)
    for c in COLS:
        if base[c].dtype.kind in "iu":
            sl[c] = sl[c].astype("float64")
    sl.to_parquet(hist / "odds_fixtures_2026_27.parquet", index=False)

    prev_rows = [
        _row("2026-27", "22/08/2026", "Hull City", "Man United", 2.0, 0.0, FILLED, odds=(9.9, 9.9, 9.9)),
        _row("2026-27", "22/08/2026", "Arsenal", "Tottenham", 3.0, 0.0, dict(FILLED, HS=15.0), odds=(9.9, 9.9, 9.9)),
        _row("2026-27", "29/08/2026", "Chelsea", "Hull City", 1.0, 1.0, odds=(9.9, 9.9, 9.9)),   # never filled
        _row("2026-27", "05/09/2026", "Tottenham", "Chelsea", NAT, NAT, odds=(9.9, 9.9, 9.9)),
    ]
    prevb = base.copy()
    for c in COLS:
        if prevb[c].dtype.kind in "iu":
            prevb[c] = prevb[c].astype("float64")
    prev = pd.concat([prevb, pd.DataFrame(prev_rows, columns=COLS)], ignore_index=True)
    prev.to_parquet(hist / "odds_all_seasons_with_2026_27.parquet", index=False)

    monkeypatch.setattr(ff, "HIST", hist)
    monkeypatch.setattr(ff, "ODDS", hist / "odds_all_seasons.parquet")
    return hist


def test_the_fill_survives_the_rebuild_nulls_only(world, capsys):
    ff.combine("2026-27")
    out = pd.read_parquet(world / "odds_all_seasons_with_2026_27.parquet")
    cur = out[out["season"] == "2026-27"].set_index(["Date", "HomeTeam", "AwayTeam"])
    hull = cur.loc[("22/08/2026", "Hull City", "Man United")]
    assert hull["HS"] == 12.0 and hull["HC"] == 6.0 and hull["HTR"] == "H" and hull["Referee"] == "M Oliver"
    assert cur.loc[("22/08/2026", "Arsenal", "Tottenham")]["HS"] == 15.0
    assert pd.isna(cur.loc[("29/08/2026", "Chelsea", "Hull City")]["HS"])          # never filled: stays null
    assert pd.isna(cur.loc[("05/09/2026", "Tottenham", "Chelsea")]["HS"])
    assert "E0 stat cells preserved from the previous combined file: 32" in capsys.readouterr().out
    assert len(out) == 5 and list(out.columns) == COLS


def test_the_fresh_slices_own_values_win_and_odds_are_never_carried(world):
    """The slice's scores, dates and prices are the truth of the rebuild; only the stat fill is
    carried, and only into nulls. The previous file's 9.9 prices must not come back."""
    ff.combine("2026-27")
    out = pd.read_parquet(world / "odds_all_seasons_with_2026_27.parquet")
    cur = out[out["season"] == "2026-27"].set_index(["Date", "HomeTeam", "AwayTeam"])
    assert cur.loc[("22/08/2026", "Hull City", "Man United")]["B365H"] == 2.1
    assert (cur["B365H"] != 9.9).all()
    assert cur.loc[("22/08/2026", "Hull City", "Man United")]["FTHG"] == 2.0


def test_a_rescheduled_fixture_does_not_inherit_the_old_dates_stats(world):
    sl = pd.read_parquet(world / "odds_fixtures_2026_27.parquet")
    sl.loc[sl["HomeTeam"] == "Hull City", "Date"] = "23/08/2026"        # moved a day
    sl.to_parquet(world / "odds_fixtures_2026_27.parquet", index=False)
    ff.combine("2026-27")
    out = pd.read_parquet(world / "odds_all_seasons_with_2026_27.parquet")
    moved = out[(out["HomeTeam"] == "Hull City") & (out["Date"] == "23/08/2026")].iloc[0]
    assert pd.isna(moved["HS"]) and len(out) == 5


def test_no_previous_combined_file_means_nothing_to_carry(world, capsys):
    (world / "odds_all_seasons_with_2026_27.parquet").unlink()
    ff.combine("2026-27")
    assert "preserved from the previous combined file: 0" in capsys.readouterr().out
    out = pd.read_parquet(world / "odds_all_seasons_with_2026_27.parquet")
    assert len(out) == 5 and out[out["season"] == "2026-27"]["HS"].isna().all()


def test_the_column_set_is_the_fills_own_and_not_a_second_list():
    assert ff.E0_FILL_COLS is fe.FILL_COLS
    src = inspect.getsource(ff)
    assert "from fill_e0_stats import FILL_COLS" in src
    assert '"HST", "AST", "HF"' not in src, "a second list of the stat columns in fetch_fixtures"
    assert set(fe.FILL_COLS) == {"HTHG", "HTAG", "HTR", "Referee", "HS", "AS", "HST", "AST",
                                 "HF", "AF", "HC", "AC", "HY", "AY", "HR", "AR"}


def test_the_change_is_confined_to_combine_and_its_helper():
    """Model-path file: the slice builder is untouched by this change."""
    src = inspect.getsource(ff.build_slice)
    assert "E0_FILL_COLS" not in src and "preserve_e0_fill" not in src
    assert "preserve_e0_fill(add, out, season)" in inspect.getsource(ff.combine)
