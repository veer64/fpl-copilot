"""The void-rule book gate (2026-08-31): a book without an established void rule
must never enter the props path silently -- not at consensus build, not at hook
construction."""
import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "squad"))
sys.path.insert(0, str(ROOT / "eval"))

import props_feature as pf  # noqa: E402

CONSENSUS_27 = ROOT / "data" / "odds_props" / "props_consensus_book_2026-27.parquet"
HMIN_27 = ROOT / "data" / "horizon" / "hmin_2026_27_refit.parquet"


def test_book_lists_are_disjoint_and_exclusions_never_overlap():
    assert not (pf.PARTICIPATION_BOOKS & pf.START_BOOKS)
    assert not (pf.EXCLUDED_BOOKS_NO_VOID_RULE & (pf.PARTICIPATION_BOOKS | pf.START_BOOKS)), \
        "a book cannot be both excluded-for-unknown-rule and rule-classified"


def test_consensus_gate_matches_the_hook_lists():
    """The consensus builder's allowed set must BE the hook's rule-classified set --
    a book passing one and failing the other would either be dropped silently or
    crash the hook at construction."""
    import build_props_consensus as bpc
    assert bpc._ALLOWED_BOOKS == set(pf.PARTICIPATION_BOOKS) | set(pf.START_BOOKS)


def test_unlisted_book_raises_at_hook_construction(monkeypatch):
    """A book absent from PARTICIPATION_BOOKS / START_BOOKS raises, never silently
    dropped: doctor a per-book frame with an unknown book and construct."""
    if not CONSENSUS_27.exists():
        pytest.skip("2026-27 consensus not on disk")
    real_read_parquet = pd.read_parquet

    def doctored(path, *a, **k):
        df = real_read_parquet(path, *a, **k)
        if "props_consensus_book_2026-27" in str(path):
            row = df.iloc[[0]].copy()
            row["book"] = "some_new_book_with_no_rule"
            df = pd.concat([df, row], ignore_index=True)
        return df

    monkeypatch.setattr(pd, "read_parquet", doctored)
    with pytest.raises(AssertionError, match="books without a conditioning rule"):
        pf.PropsHook("2026-27")


@pytest.mark.skipif(not CONSENSUS_27.exists(), reason="2026-27 consensus not on disk")
def test_2026_27_consensus_carries_only_rule_classified_books():
    books = set(pd.read_parquet(CONSENSUS_27, columns=["book"])["book"].unique())
    assert books <= set(pf.PARTICIPATION_BOOKS) | set(pf.START_BOOKS)
    assert not (books & pf.EXCLUDED_BOOKS_NO_VOID_RULE)


@pytest.mark.skipif(not HMIN_27.exists(), reason="2026-27 hmin refit not on disk")
def test_hmin_refit_covers_the_live_cutoff():
    """The horizon lever's input for the live deadline: the refit file must carry
    rows at the deadline cutoff with real values (a file that exists but carries
    noise would be worse than absence -- the strict finding told the truth)."""
    h = pd.read_parquet(HMIN_27)
    assert 3 in set(h["cutoff"].astype(int))
    c3 = h[(h["cutoff"] == 3) & (h["horizon_step"] >= 1)]
    assert len(c3) and c3["e_minutes"].notna().all()
    assert 0.0 < c3["p_start"].mean() < 1.0
