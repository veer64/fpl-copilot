"""
Chip-schedule legality (squad/chip_legality.py) -- the guard the exogenous
read layer never had.

Until 2026-08-24 the chip-inclusive convention added BOTH the Bench Boost
bench read and the Triple Captain 2 captain-bonus read on the same gameweek
(TC2 = biggest DGW = BB2's week in all three seasons). FPL allows one chip
per gameweek, so 2299/2301/2219 priced an illegal play. The only guard was a
total-vs-total drift assert, which is circular: it compares a recompute to a
figure produced by the same convention and would have passed forever.

These tests pin the structural guard: it must FAIL on the old convention,
pass on the corrected one, enforce each rule independently of any total,
and -- when the frozen logs are on disk -- hold for every row the season
totals index emits.
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "squad"))
sys.path.insert(0, str(ROOT / "eval"))

from chip_legality import ChipLegalityError, check_chip_schedule  # noqa: E402

P1 = ROOT / "data" / "p1"
FSLOG = P1 / "fslog_2023_24_base_wc2.parquet"
ALL_GWS = set(range(1, 39))


# --- the old convention must fire ------------------------------------------

def test_old_convention_tc2_at_bb2_week_fires():
    # 2023-24 full-system reference cell, exactly as P4 read it
    old = {"wildcard": [2, 32], "free_hit": [29], "bench_boost": [7, 34],
           "triple_captain": [6, 34]}
    with pytest.raises(ChipLegalityError, match="GW34: bench_boost \\+ triple_captain"):
        check_chip_schedule(old, played_gws=ALL_GWS, source="old convention")


def test_corrected_convention_passes():
    corrected = {"wildcard": [2, 32], "free_hit": [29], "bench_boost": [7, 34],
                 "triple_captain": [6]}
    out = check_chip_schedule(corrected, played_gws=ALL_GWS)
    assert out["triple_captain"] == [6] and out["bench_boost"] == [7, 34]


# --- each rule, independently of any total ---------------------------------

def test_rule_i_pairwise_distinct_across_any_two_chips():
    with pytest.raises(ChipLegalityError, match="one chip per gameweek"):
        check_chip_schedule({"wildcard": [29], "free_hit": [29]})
    with pytest.raises(ChipLegalityError, match="one chip per gameweek"):
        check_chip_schedule({"wildcard": [2], "bench_boost": [2]})


@pytest.mark.parametrize("chip,weeks", [
    ("bench_boost", [7, 9]),        # two in the first half
    ("wildcard", [2, 3]),
    ("triple_captain", [33, 36]),   # two in the second half
    ("free_hit", [20, 34]),         # GW20 is already second half
])
def test_rule_ii_one_of_each_chip_per_half(chip, weeks):
    with pytest.raises(ChipLegalityError, match="more than one"):
        check_chip_schedule({chip: weeks})


def test_rule_ii_half_boundary_is_configurable():
    check_chip_schedule({"bench_boost": [19, 20]})          # legal at 20
    with pytest.raises(ChipLegalityError):
        check_chip_schedule({"bench_boost": [19, 20]}, second_half_start=21)


def test_rule_iii_reads_only_on_played_weeks():
    played = ALL_GWS - {34}
    with pytest.raises(ChipLegalityError, match="did not play"):
        check_chip_schedule({"bench_boost": [7, 34]}, played_gws=played)
    check_chip_schedule({"bench_boost": [7, 34]})            # no played set: skip


def test_unknown_chip_type_is_refused():
    with pytest.raises(ChipLegalityError, match="unknown chip type"):
        check_chip_schedule({"tripple_captain": [5]})


def test_empty_and_none_are_legal():
    assert check_chip_schedule({}) == {c: [] for c in
                                       ("wildcard", "free_hit", "bench_boost",
                                        "triple_captain")}
    check_chip_schedule({"triple_captain": None, "bench_boost": []})


# --- against the real frozen log -------------------------------------------

@pytest.mark.skipif(not FSLOG.exists(), reason="frozen fslog not on disk")
def test_real_fslog_old_convention_fires_and_corrected_passes():
    import pandas as pd
    d = pd.read_parquet(FSLOG).set_index("gw")
    wc1, wc2, fh2, bb1, bb2 = (int(d[c].iloc[0]) for c in
                               ("wc1", "wc2", "fh2", "bb1", "bb2"))
    played = {int(g) for g in d.index}
    old = {"wildcard": [wc1, wc2], "free_hit": [fh2],
           "bench_boost": [bb1, bb2], "triple_captain": [6, bb2]}
    with pytest.raises(ChipLegalityError, match=f"GW{bb2}"):
        check_chip_schedule(old, played_gws=played, source=FSLOG.name)
    corrected = dict(old, triple_captain=[6])
    check_chip_schedule(corrected, played_gws=played, source=FSLOG.name)


@pytest.mark.skipif(not P1.exists(), reason="frozen simlogs not on disk")
def test_every_indexed_chip_row_is_a_legal_play():
    """The generator calls check_chip_schedule inside row(); building the
    chip-carrying families therefore proves every emitted row is legal.
    Guards future measure conventions, not just today's."""
    import build_season_totals_index as bsti
    rows = (bsti.rows_chips() + bsti.rows_fullsystem() + bsti.rows_p3()
            + bsti.rows_p5() + bsti.rows_oracle())
    assert rows, "no chip-family rows built"
    dropped = [r for r in rows if any(x[3] for x in r["reads"])]
    assert dropped, "expected the dropped TC2@BB2 reads to be visible in rows"
    for r in rows:
        kept_tc = [gw for lbl, gw, _, drop in r["reads"]
                   if lbl.startswith("TC") and not drop and gw]
        check_chip_schedule({"wildcard": r["wc"], "free_hit": r["fh"],
                             "bench_boost": r["bb"], "triple_captain": kept_tc},
                            played_gws=r["played"], source=r["source"])
