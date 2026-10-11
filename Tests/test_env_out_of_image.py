"""Part 7b of the smoke fixes (2026-10-10): the .env file stays out of the image.

`COPY . .` baked the server's .env (API keys, the DB password) into every image layer. The
app never needed the FILE: docker-compose gives both services built from the image
(fpl-copilot and fpl-scheduler) `env_file: .env`, and the scheduler bind-mounts the live file
for the two scripts that parse it by path. So .env and .env.* are dockerignored. This test pins
the three facts that make that safe, and that python-dotenv is quiet when the file is absent.
"""
import os
import sys
from pathlib import Path

import yaml
from dotenv import find_dotenv, load_dotenv

REPO = Path(__file__).resolve().parents[1]


def test_dockerignore_excludes_the_env_files():
    lines = [ln.strip() for ln in (REPO / ".dockerignore").read_text(encoding="utf-8").splitlines()]
    assert ".env" in lines and ".env.*" in lines
    assert ".env.example" not in lines                       # an example, if one ever exists, may ship


def test_every_service_built_from_the_image_gets_env_file():
    doc = yaml.safe_load((REPO / "docker-compose.yml").read_text(encoding="utf-8"))
    for svc in ("fpl-copilot", "fpl-scheduler"):
        assert doc["services"][svc].get("env_file") == ".env", svc
    # the scheduler still sees the LIVE file for the scripts that parse it by path
    assert "./.env:/app/.env:ro" in doc["services"]["fpl-scheduler"]["volumes"]


def test_dotenv_is_quiet_when_the_file_is_absent(tmp_path, monkeypatch):
    assert load_dotenv(str(tmp_path / ".env")) is False      # explicit path, no file: no exception
    monkeypatch.chdir(tmp_path)
    assert find_dotenv(usecwd=True) == ""                     # the walk-up form from a tree with no .env
    assert load_dotenv(find_dotenv(usecwd=True)) is False     # ... loads nothing and raises nothing
    assert os.environ.get("THIS_KEY_IS_NOT_SET_BY_ANY_FILE") is None
