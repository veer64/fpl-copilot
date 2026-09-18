"""The off-site backup (eval/backup_b2.py) and its /health reasons.

Design: Logs/backup_design_2026-09-18.md.

Everything lives on one droplet, and two things on it are irreplaceable: the database and
the odds snapshots, which cost API credits and cannot be re-pulled for a past date.

These tests cover the parts that can be tested without a droplet, a database or a bucket --
the env contract, the exclusion list, the verification floors, and above all the ALARMING,
which is the half most likely to rot unnoticed. A backup that stopped three weeks ago looks
identical to a working one from outside, so SILENCE is tested as carefully as failure.
"""
import importlib
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "eval"))

import backup_b2 as bb                                        # noqa: E402


def iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


# ------------------------------------------------------------------ the script
def test_env_contract_and_that_no_secret_is_logged(tmp_path):
    p = tmp_path / "env"
    p.write_text("# a comment\nB2_KEY_ID=kid\nB2_APP_KEY=secret\nB2_BUCKET=buck\n"
                 "B2_ENDPOINT=https://example\n", encoding="utf-8")
    cfg = bb.read_env(str(p))
    assert cfg == {"B2_KEY_ID": "kid", "B2_APP_KEY": "secret",
                   "B2_BUCKET": "buck", "B2_ENDPOINT": "https://example"}


def test_credentials_go_to_rclone_by_ENVIRONMENT_never_a_command_line():
    """A secret on argv is visible in `ps` to every user on the box, and a secret written
    to an rclone config file is a second copy to protect. Neither happens: the only route
    is the RCLONE_CONFIG_* environment, and the functions that build argv never touch the
    key."""
    import inspect
    cfg = {"B2_KEY_ID": "kid", "B2_APP_KEY": "shhh", "B2_BUCKET": "buck",
           "B2_ENDPOINT": "https://example"}
    env = bb.rclone_env(cfg)
    assert env["RCLONE_CONFIG_B2S3_ACCESS_KEY_ID"] == "kid"
    assert env["RCLONE_CONFIG_B2S3_SECRET_ACCESS_KEY"] == "shhh"
    assert env["RCLONE_CONFIG_B2S3_TYPE"] == "s3"
    # the two functions that build a command line must pass env= and never read the key
    for fn in (bb.upload, bb.verify_remote):
        src = inspect.getsource(fn)
        assert "env=env" in src, fn.__name__
        assert "B2_APP_KEY" not in src and "B2_KEY_ID" not in src, fn.__name__
    # and no rclone config FILE is involved: no --config flag, and the only place the key
    # is read is rclone_env, which returns an environment mapping rather than writing one
    import ast
    tree = ast.parse((REPO / "eval" / "backup_b2.py").read_text(encoding="utf-8"))
    code_only = "\n".join(ast.unparse(n) for n in tree.body
                          if not (isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant)))
    assert "--config" not in code_only
    readers = sorted(n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)
                     and "B2_APP_KEY" in ast.unparse(n))
    # rclone_env uses the VALUE; main only names the key to check it is PRESENT. Nothing
    # else in the file may mention it -- in particular not the argv builders above.
    assert readers == ["main", "rclone_env"], readers
    main_src = next(ast.unparse(n) for n in ast.walk(tree)
                    if isinstance(n, ast.FunctionDef) and n.name == "main")
    assert "cfg.get(k)" in main_src and "cfg['B2_APP_KEY']" not in main_src


@pytest.mark.parametrize("raw,want", [
    ("s3.us-east-005.backblazeb2.com", "https://s3.us-east-005.backblazeb2.com"),
    ("https://s3.us-east-005.backblazeb2.com", "https://s3.us-east-005.backblazeb2.com"),
    ("https://s3.us-east-005.backblazeb2.com/", "https://s3.us-east-005.backblazeb2.com"),
    ("  s3.us-east-005.backblazeb2.com  ", "https://s3.us-east-005.backblazeb2.com"),
])
def test_a_bare_endpoint_is_forced_to_https(raw, want):
    """B2 states the endpoint as a bare host and that is how it lands in an env file. An
    off-site backup must not leave the droplet unencrypted because of how it was typed."""
    assert bb.endpoint_url(raw) == want


def test_live_is_excluded_and_nothing_else_is():
    """live/ is frames, status archives and dispatch_state -- rebuilt by the next tick.
    Everything else is kept, including BOTH places odds live."""
    assert bb.SKIP_DIRS == ("live",)


def test_the_tripwire_tables_include_the_two_that_were_asked_for():
    assert "squad_versions" in bb.COUNT_TABLES
    assert "squad_scores" in bb.COUNT_TABLES
    # and the big one, because a half-written dump shows up there first
    assert "model_predictions" in bb.COUNT_TABLES


def test_size_floors_exist_and_are_below_current_reality_but_above_empty():
    # database ~23 MB, kept volume ~57 MB on 2026-09-18
    assert 0 < bb.MIN_DUMP_BYTES < 23_000_000
    assert 0 < bb.MIN_DATA_BYTES < 57_000_000


class _FakeProc:
    def __init__(self, returncode=0, stdout="", stderr=b""):
        self.returncode, self.stdout, self.stderr = returncode, stdout, stderr


def test_a_short_dump_is_refused(tmp_path, monkeypatch):
    """The floor must REFUSE, not warn: a truncated dump that uploads is worse than a
    failed run, because it looks like a backup and is only discovered on the day it is
    needed."""
    def fake_run(cmd, **kw):
        kw["stdout"].write(b"x" * 10)          # a dump far below the floor
        return _FakeProc()
    monkeypatch.setattr(bb.subprocess, "run", fake_run)
    with pytest.raises(RuntimeError, match="below the .* floor"):
        bb.make_dump(str(tmp_path), "STAMP")


def test_a_failing_pg_dump_raises_rather_than_leaving_a_stub(tmp_path, monkeypatch):
    monkeypatch.setattr(bb.subprocess, "run",
                        lambda cmd, **kw: _FakeProc(returncode=1, stderr=b"connection refused"))
    with pytest.raises(RuntimeError, match="pg_dump failed"):
        bb.make_dump(str(tmp_path), "STAMP")


# ------------------------------------------------------- the /health reasons
@pytest.fixture()
def mt(monkeypatch, tmp_path):
    monkeypatch.setenv("APP_API_KEY", "x" * 48)
    import model_tools
    model_tools = importlib.reload(model_tools)
    monkeypatch.setattr(model_tools, "REPO", tmp_path)
    (tmp_path / "data" / "live").mkdir(parents=True)
    return model_tools


def _write(mt_mod, payload):
    p = Path(mt_mod.REPO) / "data" / "live" / "BACKUP_STATUS.json"
    p.write_text(json.dumps(payload), encoding="utf-8")
    return p


def test_a_backup_that_never_ran_is_a_reason_not_a_blank(mt):
    reasons = []
    assert mt._backup_status(reasons) is None
    assert any("NEVER run" in r for r in reasons), reasons


def test_a_fresh_success_is_silent(mt):
    _write(mt, {"status": "SUCCESS",
                "last_success_at": iso(datetime.now(timezone.utc) - timedelta(hours=2)),
                "dump_bytes": 3_000_000, "data_bytes": 55_000_000})
    reasons = []
    out = mt._backup_status(reasons)
    assert reasons == []
    assert out["status"] == "SUCCESS" and out["last_success_age_hours"] < 3


def test_a_failed_run_is_a_reason_and_carries_the_error(mt):
    _write(mt, {"status": "FAILED", "error": "RuntimeError: upload of db/... failed",
                "last_success_at": iso(datetime.now(timezone.utc) - timedelta(hours=2))})
    reasons = []
    mt._backup_status(reasons)
    assert any("backup FAILED" in r and "upload of" in r for r in reasons), reasons


def test_SILENCE_is_a_reason_even_when_the_last_recorded_run_SUCCEEDED(mt):
    """The failure this whole feature is aimed at: cron removed, nothing fails, the last
    status on disk still says SUCCESS, and from outside everything looks fine."""
    old = iso(datetime.now(timezone.utc) - timedelta(hours=72))
    _write(mt, {"status": "SUCCESS", "last_success_at": old})
    reasons = []
    mt._backup_status(reasons)
    assert any("has not succeeded for" in r for r in reasons), reasons


def test_the_staleness_threshold_tolerates_a_late_run_but_not_a_missed_day(mt):
    now = datetime.now(timezone.utc)
    for hours, expect_reason in ((25, False), (31, True)):
        _write(mt, {"status": "SUCCESS", "last_success_at": iso(now - timedelta(hours=hours))})
        reasons = []
        mt._backup_status(reasons)
        assert bool(reasons) is expect_reason, (hours, reasons)


def test_failures_only_with_no_success_ever_is_its_own_reason(mt):
    _write(mt, {"status": "FAILED", "error": "boom", "last_success_at": None})
    reasons = []
    mt._backup_status(reasons)
    assert any("never SUCCEEDED" in r for r in reasons), reasons


def test_an_unreadable_status_file_is_a_reason_not_a_crash(mt):
    p = Path(mt.REPO) / "data" / "live" / "BACKUP_STATUS.json"
    p.write_text("{not json", encoding="utf-8")
    reasons = []
    assert mt._backup_status(reasons) is None
    assert any("unreadable" in r for r in reasons), reasons


def test_health_surfaces_the_backup_block(mt, monkeypatch):
    """The wiring: a reason produced by _backup_status must reach /health's reasons list,
    because the ntfy probe reads /health and nothing else."""
    src = (REPO / "model_tools.py").read_text(encoding="utf-8")
    assert 'freshness["backup"] = _backup_status(reasons)' in src
