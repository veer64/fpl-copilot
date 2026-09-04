# The os.replace retry contract (eval/_replace_retry.py): a transient
# PermissionError is retried a bounded number of times; exhausting the budget
# re-raises the ORIGINAL PermissionError -- never swallowed, never converted.
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "eval"))

import _replace_retry  # noqa: E402
from _replace_retry import replace_with_retry  # noqa: E402


def test_retry_fires_and_succeeds(monkeypatch):
    calls = []

    def flaky(src, dst):
        calls.append((src, dst))
        if len(calls) < 3:
            raise PermissionError(5, "Access is denied", str(dst))
        return None

    monkeypatch.setattr(_replace_retry.os, "replace", flaky)
    monkeypatch.setattr(_replace_retry.time, "sleep", lambda s: None)
    replace_with_retry("a.tmp", "a.csv")           # must not raise
    assert len(calls) == 3                          # two failures, then success


def test_exhaustion_still_raises_the_original_error(monkeypatch):
    calls = []

    def locked(src, dst):
        calls.append(1)
        raise PermissionError(5, "Access is denied", str(dst))

    monkeypatch.setattr(_replace_retry.os, "replace", locked)
    monkeypatch.setattr(_replace_retry.time, "sleep", lambda s: None)
    with pytest.raises(PermissionError) as ei:
        replace_with_retry("a.tmp", "a.csv")
    assert len(calls) == 3                          # the full budget was spent
    assert ei.value.errno == 5                      # the original error, untouched


def test_non_permission_errors_are_not_retried(monkeypatch):
    calls = []

    def missing(src, dst):
        calls.append(1)
        raise FileNotFoundError(2, "No such file", str(src))

    monkeypatch.setattr(_replace_retry.os, "replace", missing)
    with pytest.raises(FileNotFoundError):
        replace_with_retry("a.tmp", "a.csv")
    assert len(calls) == 1                          # immediate, no retry
