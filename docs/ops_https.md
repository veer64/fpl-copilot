# HTTPS for the API — https://api.fplcopilot.app (Prompt F1b, 2026-11-02)

**What it is.** A Caddy 2 container, `fpl-caddy`, in front of the app:
- Image: `caddy:2.11.7-alpine`, an exact version tag. Caddy v2.11.7 was released 3 Oct 2026; the digest pulled on 2 Nov was
  `sha256:e70b164da81ef698b3ad19af799ea6086ce6d9e48ed4079eb9fe26f6fbf14ee5`.
- Where it runs: as a compose service in `docker-compose.yml`, on the project network, so `fpl-copilot:8000` resolves.
- Ports: 80 and 443 (tcp). There is no HTTP/3, so nothing listens on 443/udp.
- Certificate: Caddy obtains and renews it from Let's Encrypt only, with no fallback CA and no account email.
- Redirect: Caddy sends http:// to https:// (its default).

**Config.** `docker/caddy/Caddyfile`, mounted read-only as the directory `./docker/caddy -> /etc/caddy`, so a `git pull`
changes what the container sees. It sets:
- a 1 MB request body limit;
- an access log on stdout without the query string, Authorization, X-Api-Key, Cookie, Set-Cookie or Referer.

**State.**
- Certificates and the ACME account live in the named volume `caddy_data` (`fpl-copilot_caddy_data`, at /data).
- Caddy's autosave lives in `caddy_config` (/config).
- The deploy recreates only `fpl-copilot` (`up -d --no-deps --remove-orphans fpl-copilot`), so neither volume is touched.
- Never run `docker compose down -v`: it would delete the certificates. Let's Encrypt limits re-issuance.

**Deploy.** The workflow runs `docker compose up -d --no-deps fpl-caddy` after the app:
- Creates Caddy if it is missing; a no-op when it already runs unchanged.
- Never starts or recreates `fpl-postgres` (`--no-deps`).

**Commands** (on the server, in `/root/fpl-copilot`):
- start or ensure: `docker compose up -d --no-deps fpl-caddy`
- after editing the Caddyfile: `docker compose exec fpl-caddy caddy reload --config /etc/caddy/Caddyfile`
- logs (certificate lines): `docker logs fpl-caddy 2>&1 | grep -iE 'certificate|acme|error'`
- validate a Caddyfile without running it:
  `docker run --rm -v <dir>:/etc/caddy:ro caddy:2.11.7-alpine caddy validate --config /etc/caddy/Caddyfile`

**Firewall.**
- ufw allows 80/tcp and 443/tcp (added 2 Nov), next to 8000 and OpenSSH.
- Docker-published ports bypass ufw, so the published ports themselves are what expose Caddy. A preflight on 2 Nov (a
  throwaway Caddy with `tls internal`, no ACME) answered on 80 and 443 from outside, so no cloud firewall blocks them.

**Still open (decided at switch-on, F4).**
- The plain-HTTP address `http://68.183.131.154:8000` keeps working.
- Closing it is a separate decision: remove the `8000:8000` publish and the ufw rule.

**Client IP behind Caddy.**
- The app sees requests from Caddy's container address. Through 8000 they already arrived from Docker's bridge gateway.
- So the off-mode per-IP limit (30 /chat an hour) was never per real client; the global 60 an hour bounds it either way.
- Clerk mode limits per user, not per IP.
