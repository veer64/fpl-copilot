"""Prompt F1b Part 2 (2026-11-02): HTTPS for the API at https://api.fplcopilot.app -- Caddy as part of the deploy mechanism.

USER DECISIONS: "B" (own domain); fplcopilot.app bought, DNS A api -> 68.183.131.154, DNS only.

K1 docker-compose.yml defines fpl-caddy: an exact Caddy version tag (x.y.z, no floating tag), restart unless-stopped, ports
   80 and 443 (tcp only), the named volumes caddy_data:/data and caddy_config:/config (certificates survive every deploy),
   ./docker/caddy mounted read-only as /etc/caddy, no build and no depends_on; fpl-postgres's definition is unchanged.
K2 the deploy workflow brings Caddy up with --no-deps after the app (it can never start or recreate fpl-postgres); the app's
   own line is unchanged.
K3 docker/caddy/Caddyfile: the site api.fplcopilot.app, reverse_proxy to the app's internal port (the Dockerfile's uvicorn
   --port), request body limit 1 MB, Let's Encrypt as the only issuer, no account email, HTTP/1.1 + HTTP/2 only, and an
   access log without the query string or any credential header.
Pure: the YAML is parsed and the Caddyfile read as text (validated with the pinned image on the server: `caddy validate`)."""
import re
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
COMPOSE = REPO / "docker-compose.yml"
WORKFLOW = REPO / ".github" / "workflows" / "deploy.yml"
CADDYFILE = REPO / "docker" / "caddy" / "Caddyfile"


def _services():
    return yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))["services"]


def _caddy_lines():
    return [ln.strip() for ln in CADDYFILE.read_text(encoding="utf-8").splitlines() if ln.strip() and not ln.strip().startswith("#")]


def _script_lines():
    doc = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    step = next(s for s in doc["jobs"]["deploy"]["steps"] if s.get("name") == "Deploy over SSH")
    return [ln.strip() for ln in step["with"]["script"].splitlines() if ln.strip() and not ln.strip().startswith("#")]


# ---- K1 -----------------------------------------------------------------------------------------------------------------

def test_k1_compose_defines_caddy_pinned_with_ports_volumes_and_a_read_only_config():
    s = _services()["fpl-caddy"]
    assert re.fullmatch(r"caddy:2\.\d+\.\d+(-alpine)?", s["image"]), s["image"]          # an exact version, never "2" / "latest"
    assert s["container_name"] == "fpl-caddy" and s["restart"] == "unless-stopped"
    assert sorted(s["ports"]) == ["443:443", "80:80"]                                    # tcp only: no 443/udp
    assert sorted(s["volumes"]) == ["./docker/caddy:/etc/caddy:ro", "caddy_config:/config", "caddy_data:/data"]
    assert "build" not in s and "depends_on" not in s
    vols = yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))["volumes"]
    assert "caddy_data" in vols and "caddy_config" in vols


def test_k1_postgres_is_defined_exactly_as_before():
    p = _services()["fpl-postgres"]
    assert p["image"] == "fpl-postgres-pgvector:16.14-0.8.6" and p["container_name"] == "fpl-postgres"
    assert "ports" not in p and p["volumes"] == ["fpl_pgdata:/var/lib/postgresql/data"]
    app = _services()["fpl-copilot"]
    assert app["ports"] == ["8000:8000"]                                                  # the old address keeps working


# ---- K2 -----------------------------------------------------------------------------------------------------------------

def test_k2_the_deploy_brings_caddy_up_without_its_dependencies_after_the_app():
    lines = _script_lines()
    i_app = lines.index("docker compose up -d --no-deps --remove-orphans fpl-copilot")
    i_caddy = lines.index("docker compose up -d --no-deps fpl-caddy")
    assert i_app < i_caddy < lines.index("docker compose ps")
    assert not [ln for ln in lines if "fpl-postgres" in ln and "up" in ln]               # the database is never brought up here


# ---- K3 -----------------------------------------------------------------------------------------------------------------

def test_k3_the_caddyfile_proxies_the_site_to_the_apps_internal_port():
    lines = _caddy_lines()
    assert "api.fplcopilot.app {" in lines
    port = re.search(r'"--port", "(\d+)"', (REPO / "Dockerfile").read_text(encoding="utf-8")).group(1)
    assert f"reverse_proxy fpl-copilot:{port}" in lines


def test_k3_body_limit_issuer_protocols_and_no_email():
    lines = _caddy_lines()
    i = lines.index("request_body {")
    assert lines[i + 1] == "max_size 1MB"
    assert "dir https://acme-v02.api.letsencrypt.org/directory" in lines and "issuer acme {" in lines
    assert "protocols h1 h2" in lines
    assert not [ln for ln in lines if ln.startswith("email") or "@" in ln]


def test_k3_the_access_log_carries_no_query_string_and_no_credential():
    lines = _caddy_lines()
    assert "output stdout" in lines and "format filter {" in lines
    assert r'request>uri regexp \?.*$ ""' in lines
    for h in ("Authorization", "X-Api-Key", "Cookie", "Referer"):
        assert f"request>headers>{h} delete" in lines, h
    assert "resp_headers>Set-Cookie delete" in lines
