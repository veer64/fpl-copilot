"""
Tests for scoring the hypothetical squad (squad_store scoring helpers +
eval/score_squads.py), Decision 2 of 2026-09-12.

Pure Python, no database, no network: the scorer is scoring.score_gameweek
(the simulator's own), so what is pinned here is the plumbing around it --
the document -> scoring-frame mapping (bench 1..4 -> 0..3), doubles
aggregated per element from the master, the "which version was the squad at
that deadline" rule, transfer/allowance reconstruction with the consistency
assert, the hash that identifies scoring inputs, the request loop through a
fake connection (no squad / scored / already scored / corrected), and the
DDL pin for squad_scores.

Run:
    uv run pytest Tests/test_squad_scores.py -v
"""

import hashlib
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import pytest

REPO = Path(__file__).resolve().parents[1]
for p in (str(REPO), str(REPO / "squad"), str(REPO / "eval"), str(REPO / "Tests")):
    if p not in sys.path:
        sys.path.insert(0, p)

import squad_store                                         # noqa: E402
import score_squads                                        # noqa: E402
from scoring import HIT_COST                               # noqa: E402
from test_squad_store import legal_doc, _row               # noqa: E402

T0 = datetime(2026, 9, 12, 5, 24, 53, tzinfo=timezone.utc)      # the seed
DL4 = datetime(2026, 9, 12, 12, 30, tzinfo=timezone.utc)        # GW4 deadline
DL5 = datetime(2026, 9, 18, 17, 30, tzinfo=timezone.utc)        # GW5 deadline


# ---------------------------------------------------------------- fixtures
def _master(gw, points, minutes, double=None):
    """A master slice: one row per (element, fixture); `double` = element with
    two fixtures (rows split 60/30 minutes, points split too)."""
    rows = []
    for e in range(1, 16):
        if e == double:
            rows.append(dict(element=e, GW=gw, fixture=100 + e, minutes=60, total_points=points[e] - 1))
            rows.append(dict(element=e, GW=gw, fixture=200 + e, minutes=30, total_points=1))
        else:
            rows.append(dict(element=e, GW=gw, fixture=100 + e, minutes=minutes.get(e, 90),
                             total_points=points[e]))
    return pd.DataFrame(rows)


def _versions(*recs):
    return list(recs)


def _seed_version(ft=1, gw=4, created_at=T0):
    d = legal_doc()
    d["free_transfers"] = ft
    d["provenance"] = {"kind": "seed", "hypothetical": True}
    return _row(d, version_id=1, gw=gw, created_at=created_at)


def _transfer_version(version_id, gw, created_at, n_transfers, hits, ft_after, supersedes=1):
    d = legal_doc()
    d["free_transfers"] = ft_after
    d["provenance"] = {"kind": "set_my_squad", "from_version": supersedes,
                       "transfers": [{"out": 100 + i, "in": 200 + i} for i in range(n_transfers)],
                       "hits": hits, "hypothetical": True}
    return _row(d, version_id=version_id, gw=gw, created_at=created_at, supersedes=supersedes)


# ------------------------------------------------------ frame + actuals
def test_scoring_frame_maps_bench_order_to_the_scoring_convention():
    f = squad_store.scoring_frame(legal_doc())
    bench = f[f["role"] == "bench"].sort_values("bench_order")
    assert list(bench["bench_order"]) == [0, 1, 2, 3]
    assert bench.iloc[0]["position"] == "GK"                        # slot 1 -> 0 is the bench GK
    assert f[f["role"] != "bench"]["bench_order"].isna().all()
    assert set(f.columns) >= {"element", "position", "role", "bench_order"}


def test_actuals_aggregate_a_double_gameweek_per_element():
    pts = {e: 2 for e in range(1, 16)}
    pts[13] = 9
    m = _master(4, pts, {}, double=13)
    a = squad_store.actuals_from_master(m, 4)
    assert len(a) == 15 and a["element"].is_unique
    row = a[a["element"] == 13].iloc[0]
    assert row["minutes"] == 90 and row["total_points"] == 9          # 8 + 1 over two fixtures
    with pytest.raises(ValueError):
        squad_store.actuals_from_master(m, 5)


def test_master_hash_identifies_the_scored_rows():
    pts = {e: 2 for e in range(1, 16)}
    m1 = _master(4, pts, {})
    m2 = _master(4, pts, {}).sample(frac=1, random_state=1)             # same rows, shuffled
    assert squad_store.master_rows_hash(m1, 4) == squad_store.master_rows_hash(m2, 4)
    pts2 = dict(pts); pts2[3] = 3                                        # one correction
    assert squad_store.master_rows_hash(_master(4, pts2, {}), 4) != squad_store.master_rows_hash(m1, 4)
    assert len(squad_store.master_rows_hash(m1, 4)) == 64


# --------------------------------------------- which squad, which allowance
def test_version_at_deadline_picks_the_latest_before_the_deadline():
    v1 = _seed_version(created_at=T0)
    v2 = _transfer_version(2, 5, DL4 + timedelta(hours=2), 1, 0, 1)      # set for GW5 after DL4
    vs = _versions(v1, v2)
    assert squad_store.version_at_deadline(vs, 4, DL4)["version_id"] == 1
    assert squad_store.version_at_deadline(vs, 5, DL5)["version_id"] == 2
    assert squad_store.version_at_deadline(vs, 3, DL4 - timedelta(days=7)) is None   # before the seed


def test_transfer_accounting_seed_gameweek_and_rolled_allowance():
    v1 = _seed_version(ft=1, created_at=T0)
    # GW5: two transfers in one version against the rolled allowance of 2 -> 0 paid
    v2 = _transfer_version(2, 5, DL4 + timedelta(hours=2), 2, 0, 0)
    vs = _versions(v1, v2)
    assert squad_store.transfer_accounting(vs, 4, DL4) == {"transfers_made": 0, "free_transfers": 1, "paid": 0}
    assert squad_store.transfer_accounting(vs, 5, DL5) == {"transfers_made": 2, "free_transfers": 2, "paid": 0}


def test_transfer_accounting_sums_versions_within_a_gameweek_and_checks_hits():
    v1 = _seed_version(ft=1, created_at=T0)
    v2 = _transfer_version(2, 5, DL4 + timedelta(hours=2), 2, 0, 0)          # uses both FTs
    v3 = _transfer_version(3, 5, DL4 + timedelta(hours=3), 1, 1, 0, supersedes=2)   # one more: a hit
    vs = _versions(v1, v2, v3)
    acc = squad_store.transfer_accounting(vs, 5, DL5)
    assert acc == {"transfers_made": 3, "free_transfers": 2, "paid": 1}
    v3_bad = _transfer_version(3, 5, DL4 + timedelta(hours=3), 1, 0, 0, supersedes=2)   # claims no hit
    with pytest.raises(RuntimeError) as ei:
        squad_store.transfer_accounting(_versions(v1, v2, v3_bad), 5, DL5)
    assert "inconsistent" in str(ei.value)


def test_versions_written_after_the_deadline_do_not_count():
    v1 = _seed_version(ft=1, created_at=T0)
    late = _transfer_version(2, 4, DL4 + timedelta(minutes=5), 1, 0, 0)    # GW4 change after DL4
    vs = _versions(v1, late)
    assert squad_store.version_at_deadline(vs, 4, DL4)["version_id"] == 1
    assert squad_store.transfer_accounting(vs, 4, DL4)["transfers_made"] == 0


# ------------------------------------------------------------- the score
def test_score_gameweek_for_applies_autosub_armband_and_hit():
    """legal_doc roles: captain 13, vice 9, starters 1,3,4,5,6,8,10,14,15, bench 2(GK),7,11,12.
    Captain blank -> vice doubled; starter 6 blank -> first outfield bench who
    played comes on (7); two transfers over an allowance of 1 -> one hit."""
    v1 = _seed_version(ft=1, created_at=T0)
    v2 = _transfer_version(2, 5, DL4 + timedelta(hours=2), 3, 1, 0)        # 3 transfers vs allowance 2
    vs = _versions(v1, v2)
    pts = {e: 2 for e in range(1, 16)}
    pts.update({13: 0, 9: 6, 6: 0, 7: 5, 2: 1})
    minutes = {13: 0, 6: 0}
    actuals = squad_store.actuals_from_master(_master(5, pts, minutes), 5)
    row = squad_store.score_gameweek_for(vs, 5, DL5, actuals)
    assert row["version_id"] == 2 and row["gw"] == 5
    assert row["doubled"] == 9 and row["doubled_role"] == "vice" and row["captain_bonus"] == 6
    assert [6, 7] in row["subs_made"] and 7 in row["final_xi"] and 6 not in row["final_xi"]
    # the blank captain is autosubbed out too (a MID comes on for a FWD, 4-4-2 is legal)
    assert [13, 11] in row["subs_made"] and 13 not in row["final_xi"] and 11 in row["final_xi"]
    assert len(row["final_xi"]) == 11
    assert row["transfers_made"] == 3 and row["free_transfers"] == 2 and row["hit"] == HIT_COST
    xi_pts = sum(pts[e] for e in row["final_xi"])
    assert row["points_raw"] == xi_pts + 6
    assert row["points_net"] == row["points_raw"] - HIT_COST              # HITS DEDUCTED
    assert row["bench_points"] == pts[2] + pts[12]                         # 7 and 11 came on


def test_no_squad_at_that_deadline_scores_nothing():
    vs = _versions(_seed_version(created_at=T0))
    actuals = squad_store.actuals_from_master(_master(3, {e: 2 for e in range(1, 16)}, {}), 3)
    assert squad_store.score_gameweek_for(vs, 3, DL4 - timedelta(days=7), actuals) is None


# ----------------------------------------------------- the request loop
class _Cur:
    def __init__(self, conn):
        self.c = conn

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, params=None):
        self.c.executed.append((" ".join(sql.split()), params))
        self.last = sql

    def fetchall(self):
        if "FROM squad_versions" in self.last:
            return [dict(v) for v in self.c.versions]
        if "FROM squad_scores" in self.last:
            return list(self.c.hashes)
        return []

    def fetchone(self):
        if "INSERT INTO squad_scores" in self.last:
            h = self.c.executed[-1][1][15]
            gw = self.c.executed[-1][1][2]
            if any(x[0] == gw and x[1] == h for x in self.c.hashes):
                return None                                             # ON CONFLICT DO NOTHING
            self.c.next_id += 1
            self.c.hashes.append((gw, h, self.c.next_id, self.c.executed[-1][1][4]))
            return (self.c.next_id,)
        return None


class _Conn:
    def __init__(self, versions, hashes=()):
        self.versions, self.hashes, self.executed = versions, list(hashes), []
        self.next_id, self.commits, self.rollbacks = 0, 0, 0

    def cursor(self, cursor_factory=None):
        return _Cur(self)

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


def _serialised(v):
    v = dict(v)
    v["squad_json"] = json.dumps(v["squad_json"])
    return v


def test_request_loop_skips_scores_and_reports_each_gameweek():
    v1 = _seed_version(ft=1, created_at=T0)
    vs = [_serialised(v1)]
    pts = {e: 2 for e in range(1, 16)}
    master = pd.concat([_master(3, pts, {}), _master(4, pts, {})], ignore_index=True)
    conn = _Conn(vs)
    lines = []
    n = score_squads.score_request(conn, master, "2026-27",
                                   {"3": (DL4 - timedelta(days=7)).isoformat(), "4": DL4.isoformat()},
                                   out=lines.append)
    assert n == 1
    assert lines[0].startswith("GW3: no squad at deadline")
    assert lines[1].startswith("GW4: scored") and "-> score_id 1" in lines[1]
    assert conn.commits == 1
    # second pass: identical inputs -> already scored, nothing written
    lines.clear()
    n = score_squads.score_request(conn, master, "2026-27", {"4": DL4.isoformat()}, out=lines.append)
    assert n == 0 and "already scored" in lines[0]


def test_request_loop_dry_run_writes_nothing():
    conn = _Conn([_serialised(_seed_version(created_at=T0))])
    master = _master(4, {e: 2 for e in range(1, 16)}, {})
    lines = []
    n = score_squads.score_request(conn, master, "2026-27", {"4": DL4.isoformat()}, dry_run=True,
                                   out=lines.append)
    assert n == 0 and "DRY RUN would write" in lines[0]
    assert conn.commits == 0 and conn.rollbacks == 1


def test_request_loop_records_a_correction_as_a_new_row():
    pts = {e: 2 for e in range(1, 16)}
    m1 = _master(4, pts, {})
    conn = _Conn([_serialised(_seed_version(created_at=T0))])
    lines = []
    score_squads.score_request(conn, m1, "2026-27", {"4": DL4.isoformat()}, out=lines.append)
    pts2 = dict(pts); pts2[13] = 9                                       # FPL corrects the captain's points
    m2 = _master(4, pts2, {})
    lines.clear()
    n = score_squads.score_request(conn, m2, "2026-27", {"4": DL4.isoformat()}, out=lines.append)
    assert n == 1 and "FPL CORRECTION: supersedes score_id 1" in lines[0]
    assert len(conn.hashes) == 2                                          # both rows kept


# ---------------------------------------------------------- summary read
def test_summary_total_points_come_from_scores_not_the_document():
    rec = _row(legal_doc(), gw=4, created_at=T0)
    scores = [{"gw": 4, "points_net": 61, "hit": 4, "version_id": 1},
              {"gw": 5, "points_net": 48, "hit": 0, "version_id": 2}]
    out = squad_store.summary(rec, {}, current_gw=6, scores=scores)
    assert out["total_points"] == 109 and out["total_points_recorded"] == 0
    assert [s["gw"] for s in out["scored_gameweeks"]] == [4, 5]
    assert "rule 1" in out["total_points_meaning"]
    out0 = squad_store.summary(rec, {}, current_gw=6, scores=[])
    assert out0["total_points"] == 0 and out0["scored_gameweeks"] == []
    outn = squad_store.summary(rec, {}, current_gw=6)
    assert outn["total_points"] is None


# ------------------------------------------------------------ the DDL pin
SCORES_DDL_SHA256 = "6f15ca40208f01b8574be9c206f5a8ac15ab612555d55af9269079342771f186"


def test_scores_ddl_is_stable_and_carries_rule_1():
    assert hashlib.sha256(squad_store.SCORES_DDL.encode("utf-8")).hexdigest() == SCORES_DDL_SHA256
    for must in ("CREATE TABLE IF NOT EXISTS squad_scores", "ux_squad_scores_inputs",
                 "trg_squad_scores_append_only", "COMMENT ON TABLE squad_scores",
                 "NEVER evidence about configuration choice", "p_start >= 0.75"):
        assert must in squad_store.SCORES_DDL, must
