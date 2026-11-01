"""Prompt P6 Part 3 (2026-11-01): get_my_squad's roles warning when the roles' gameweek differs from the current build's.

The case (30 Oct 21:04Z, user 9001; the laptop's 31 Oct 22:18Z version reads the same): GW6 roles were recorded AFTER the
GW8 build of Fri 23 Oct 17:21Z, and the warning said the build "was made at ... Fri 23 Oct ..., AFTER that" -- an order of
dates that was false. When the gameweeks differ the warning now states both gameweeks and both dates and claims no order
between them. When the gameweek is the same and the build is the later one (the only way a same-gameweek record goes stale)
the old wording stays: its "AFTER" is then true."""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
for p in (str(REPO), str(REPO / "squad"), str(REPO / "Tests")):
    if p not in sys.path:
        sys.path.insert(0, p)

import squad_store                                         # noqa: E402
from test_squad_store import legal_doc, _row               # noqa: E402

UTC = timezone.utc
ROLES_AT = datetime(2026, 10, 30, 21, 4, 0, tzinfo=UTC)     # GW6 roles, recorded after ...
BUILD_AT = datetime(2026, 10, 23, 17, 21, 20, tzinfo=UTC)   # ... the GW8 build (run 51)
ORDER_WORDS = ("after", "before", "since", "earlier", "later", "newer", "older", "then")


def _gw8():
    return {"run_id": 51, "gw": 8, "finished_at": BUILD_AT}


def test_w1_the_oct_30_case_states_both_gameweeks_and_both_dates_and_no_order():
    st = squad_store.roles_status(_row(legal_doc(), gw=6, created_at=ROLES_AT, user_id=9001), _gw8())
    assert st["status"] == "STALE"
    assert st["warning"] == (
        "these roles were recorded at 2026-10-30 21:04:00+00:00 (Fri 30 Oct 2026 21:04 UTC) for GW6; the model build for "
        "GW8 was made at 2026-10-23 17:21:20+00:00 (Fri 23 Oct 2026 17:21 UTC) -- a different gameweek from the roles' GW6. "
        "They are a record of what was set, not a recommendation for GW8 -- the line-up pick gives that.")
    words = st["warning"].lower().replace("-", " ").split()
    assert not [w for w in ORDER_WORDS if w in words]                # no claim that one date came before the other


def test_w1_a_later_gameweek_built_after_the_roles_gets_the_same_wording():
    t0 = datetime(2026, 9, 12, 5, 24, 53, tzinfo=UTC)
    st = squad_store.roles_status(_row(legal_doc(), gw=4, created_at=t0), {"run_id": 5, "gw": 5, "finished_at": t0 + timedelta(hours=6)})
    assert st["status"] == "STALE" and "AFTER" not in st["warning"]
    assert "for GW4" in st["warning"] and "the model build for GW5 was made at" in st["warning"]
    assert "a different gameweek from the roles' GW4" in st["warning"] and "not a recommendation for GW5" in st["warning"]


def test_w2_the_same_gameweek_built_later_keeps_its_true_after():
    t0 = datetime(2026, 9, 12, 5, 24, 53, tzinfo=UTC)
    st = squad_store.roles_status(_row(legal_doc(), gw=4, created_at=t0), {"run_id": 5, "gw": 4, "finished_at": t0 + timedelta(hours=5)})
    assert st["warning"] == (
        "these roles were recorded at 2026-09-12 05:24:53+00:00 (Sat 12 Sep 2026 05:24 UTC) for GW4; the model build for "
        "GW4 was made at 2026-09-12 10:24:53+00:00 (Sat 12 Sep 2026 10:24 UTC), AFTER that. They are a record of what was "
        "set, not a recommendation for GW4 -- the line-up pick gives that.")


def test_w3_get_my_squad_carries_the_new_wording():
    out = squad_store.summary(_row(legal_doc(), gw=6, created_at=ROLES_AT, user_id=9001), {}, latest_run=_gw8())
    assert out["roles"]["status"] == "STALE" and "AFTER" not in out["roles"]["warning"]
    assert "a different gameweek from the roles' GW6" in out["roles"]["warning"]
