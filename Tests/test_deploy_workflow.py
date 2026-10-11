"""Part 7a of the smoke fixes (2026-10-10): the deploy script restores the server tree when the
image build fails.

On 2026-10-10 11:16Z the build failed AFTER `git pull`, so the server tree sat at a sha whose
image never built while the old container kept serving. The script now records PREV before the
pull, and on a failed build runs `git reset --keep "$PREV"` (keeps the branch, refuses to lose
local changes), prints that the tree was restored and exits 1. The success path is unchanged.

Pure: the YAML is parsed, the script block is checked for its lines and their order, and bash -n
parses it when a bash is on PATH.
"""
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[1]
WORKFLOW = REPO / ".github" / "workflows" / "deploy.yml"


def _script():
    doc = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    steps = doc["jobs"]["deploy"]["steps"]
    step = next(s for s in steps if s.get("name") == "Deploy over SSH")
    return step["with"]["script"]


def _bash():
    """Git Bash first: on this laptop `bash` on PATH can be the WSL relay, which has no distro."""
    for c in (r"C:\Program Files\Git\bin\bash.exe", r"C:\Program Files\Git\usr\bin\bash.exe", "/usr/bin/bash"):
        if Path(c).exists():
            return c
    return shutil.which("bash")


def test_the_workflow_parses_and_keeps_its_trigger():
    doc = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    trigger = doc.get("on", doc.get(True))                 # PyYAML reads the bare key `on` as True
    assert trigger["push"]["branches"] == ["main"]
    assert "deploy" in doc["jobs"]


def test_prev_is_recorded_before_the_pull_and_a_failed_build_restores_it():
    s = _script()
    lines = [ln.strip() for ln in s.splitlines() if ln.strip() and not ln.strip().startswith("#")]
    assert "set -e" in lines
    i_prev = lines.index('PREV=$(git rev-parse HEAD)')
    i_pull = lines.index("git pull")
    assert i_prev < i_pull, lines
    assert "if ! docker compose build fpl-copilot; then" in lines
    i_reset = lines.index('git reset --keep "$PREV"')
    i_exit = next(i for i, ln in enumerate(lines) if ln == "exit 1")
    assert lines.index("if ! docker compose build fpl-copilot; then") < i_reset < i_exit
    assert any("restored" in ln for ln in lines[i_reset:i_exit]), lines[i_reset:i_exit]


def test_the_success_path_is_unchanged():
    s = _script()
    lines = [ln.strip() for ln in s.splitlines() if ln.strip() and not ln.strip().startswith("#")]
    i_up = lines.index("docker compose up -d --no-deps --remove-orphans fpl-copilot")
    i_ps = lines.index("docker compose ps")
    i_fi = max(i for i, ln in enumerate(lines) if ln == "fi")
    assert i_fi < i_up < i_ps
    assert "docker compose build" not in " ".join(lines[i_up:])        # one build, inside the guard
    assert not any("reset --hard" in ln for ln in lines)


@pytest.mark.skipif(_bash() is None, reason="no bash found")
def test_the_script_block_parses_under_bash_n(tmp_path):
    f = tmp_path / "deploy.sh"
    f.write_text(_script(), encoding="utf-8", newline="\n")
    r = subprocess.run([_bash(), "-n", str(f)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
