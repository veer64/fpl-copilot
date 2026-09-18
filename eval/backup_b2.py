#!/usr/bin/env python3
"""
backup_b2.py -- nightly off-site backup to Backblaze B2 (Logs/backup_design_2026-09-18.md).

Everything that matters lives on one droplet. The database holds the squad versions, the
scores, the runs and every proposal; the model volume holds odds snapshots that cost API
credits and CANNOT be re-pulled for a past date. A droplet failure loses all of it.

WHAT IT TAKES
  * a LOGICAL dump -- `pg_dump -Fc`, taken against the RUNNING database. Not a file copy of
    the volume: copying Postgres data files while the server is writing gives a torn
    snapshot that may not restore at all, and would fail silently until the day it is needed.
  * the model-data volume EXCEPT `live/`. `live/` is the deadline frames, the build and
    ingest status archives and dispatch_state -- all rebuilt by the next tick. Everything
    else is kept, rather than enumerating odds files: the odds sit in two places
    (`odds_props/` and `history/odds_*`), the whole volume is under 70 MB, and B2 is about
    $6/TB/month, so being selective saves nothing and risks mis-classifying one
    irreplaceable file as rebuildable.

WHAT IT DOES NOT TAKE
  /root/fpl-copilot/.env. Putting plaintext Anthropic and odds-API keys in a cloud bucket
  trades one exposure for another, and every key in it is re-issuable.

CREDENTIALS come from /root/fpl-backup.env (mode 600, never in the repo):
  B2_KEY_ID  B2_APP_KEY  B2_BUCKET  B2_ENDPOINT
They are handed to rclone through its RCLONE_CONFIG_* environment variables, so they never
reach a command line (visible in `ps`), never reach a shell history, and no second copy is
written to an rclone config file. Nothing in this script prints them.

The key should be scoped to the bucket and should NOT carry deleteFiles: a backup credential
that can delete backups means whoever takes the droplet takes the backups too. Retention is
therefore a B2 lifecycle rule, server side, not a delete from here.

VERIFICATION, because "a file was uploaded" is not "a backup exists":
  * row-count tripwires on four tables -- a truncated dump is otherwise invisible;
  * a size floor on each artefact;
  * `pg_restore --list` against the dump BEFORE upload, which proves the archive is readable
    and carries the expected tables;
  * after upload, the remote object is listed back and its size compared.
  None of this proves a full restore works. Only a restore rehearsal does; see the design log.

ALARMING. The status file lands on the model volume at data/live/BACKUP_STATUS.json, the same
convention the weekly ingest uses, and model_tools.health() turns it into /health reasons --
so the existing probe and ntfy path carry it and there is no second alert channel. It alarms
on FAILURE and on SILENCE: a backup that stopped three weeks ago looks identical to a working
one from outside, so absence is a reason in its own right.

Cron (root, its own lock -- NEVER the dispatcher's; a backup that the thing it protects can
block is not a backup):
  43 3 * * * flock -n /tmp/fpl-backup.lock /usr/bin/python3 /root/fpl-copilot/eval/backup_b2.py >> /var/log/fpl-backup.log 2>&1

Usage: backup_b2.py [--dry-run] [--env PATH] [--keep-local]
"""
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone

ENV_FILE = "/root/fpl-backup.env"
VOLUME = "/var/lib/docker/volumes/fpl-copilot_fpl_model_data/_data"
STATUS_PATH = os.path.join(VOLUME, "live", "BACKUP_STATUS.json")
PG_CONTAINER = "fpl-postgres"
DB_NAME = "fpl"
SKIP_DIRS = ("live",)                 # rebuilt by the next tick
REMOTE = "b2s3"

# Floors, not targets: they exist to make a truncated artefact loud. The database is ~23 MB
# and the kept volume ~57 MB as of 2026-09-18, so these sit far below normal and far above
# empty. Raise them if the data grows an order of magnitude; never lower them to make a run
# pass.
MIN_DUMP_BYTES = 200_000
MIN_DATA_BYTES = 5_000_000
COUNT_TABLES = ("squad_versions", "squad_scores", "model_runs", "model_predictions")
TIMEOUT_S = 900


def iso(dt=None):
    return (dt or datetime.now(timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ")


def log(msg):
    print(f"[{iso()}] {msg}", flush=True)


def read_env(path):
    out = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                out[k.strip()] = v.strip()
    return out


def run(cmd, env=None, capture=True, timeout=TIMEOUT_S):
    """Run a command. `cmd` is a list, never a shell string: no secret can be split into a
    shell word and no argument needs quoting."""
    return subprocess.run(cmd, capture_output=capture, text=True, timeout=timeout,
                          env=env if env is None else {**os.environ, **env})


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def row_counts():
    """Tripwires. A dump that restores cleanly but carries half the rows is the failure this
    catches; nothing else in the chain would notice."""
    sql = " union all ".join(
        f"select '{t}', count(*)::text from {t}" for t in COUNT_TABLES)
    r = run(["docker", "exec", PG_CONTAINER, "psql", "-U", "postgres", "-d", DB_NAME,
             "-tAF", "|", "-c", sql])
    if r.returncode != 0:
        raise RuntimeError(f"row counts failed: {r.stderr.strip()[:200]}")
    out = {}
    for line in r.stdout.strip().splitlines():
        if "|" in line:
            k, v = line.split("|", 1)
            out[k.strip()] = int(v)
    missing = [t for t in COUNT_TABLES if t not in out]
    if missing:
        raise RuntimeError(f"row counts missing for {missing}")
    return out


def make_dump(workdir, stamp):
    path = os.path.join(workdir, f"fpl_{stamp}.dump")
    with open(path, "wb") as f:
        p = subprocess.run(
            ["docker", "exec", PG_CONTAINER, "pg_dump", "-U", "postgres", "-d", DB_NAME,
             "-Fc", "--no-owner", "--no-privileges"],
            stdout=f, stderr=subprocess.PIPE, timeout=TIMEOUT_S)
    if p.returncode != 0:
        raise RuntimeError(f"pg_dump failed: {p.stderr.decode('utf-8', 'replace')[:300]}")
    size = os.path.getsize(path)
    if size < MIN_DUMP_BYTES:
        raise RuntimeError(f"dump is {size} bytes, below the {MIN_DUMP_BYTES} floor -- refusing")
    return path, size


def verify_dump(path):
    """`pg_restore --list` proves the archive is readable and names its contents. It does not
    prove a restore works -- only a rehearsal does -- but it turns a corrupt upload from a
    silent success into a failure."""
    tmp_in_container = "/tmp/_verify.dump"
    cp = run(["docker", "cp", path, f"{PG_CONTAINER}:{tmp_in_container}"])
    if cp.returncode != 0:
        raise RuntimeError(f"docker cp for verification failed: {cp.stderr.strip()[:200]}")
    try:
        r = run(["docker", "exec", PG_CONTAINER, "pg_restore", "--list", tmp_in_container])
        if r.returncode != 0:
            raise RuntimeError(f"pg_restore --list rejected the archive: {r.stderr.strip()[:300]}")
        tables = [l for l in r.stdout.splitlines() if " TABLE DATA " in l]
        if not tables:
            raise RuntimeError("pg_restore --list shows no TABLE DATA entries -- empty archive")
        return len(tables)
    finally:
        run(["docker", "exec", PG_CONTAINER, "rm", "-f", tmp_in_container])


def make_data_tar(workdir, stamp):
    """gzip, not zstd: parquet is already compressed so the ratio barely differs, and gzip is
    readable on any machine someone might be restoring from in a hurry."""
    path = os.path.join(workdir, f"model_data_{stamp}.tar.gz")
    cmd = ["tar", "-czf", path, "-C", VOLUME]
    for d in SKIP_DIRS:
        cmd += ["--exclude", f"./{d}"]
    cmd += ["."]
    r = run(cmd)
    if r.returncode != 0:
        raise RuntimeError(f"tar failed: {r.stderr.strip()[:300]}")
    size = os.path.getsize(path)
    if size < MIN_DATA_BYTES:
        raise RuntimeError(f"data archive is {size} bytes, below the {MIN_DATA_BYTES} floor")
    return path, size


def endpoint_url(raw):
    """B2 gives the endpoint as a bare host (`s3.us-east-005.backblazeb2.com`) and that is
    how it tends to get pasted into an env file. rclone wants a URL, and a bare host silently
    becomes an http:// attempt on some paths -- an off-site backup must not leave the droplet
    unencrypted. Normalise here rather than depending on how it was typed."""
    raw = (raw or "").strip().rstrip("/")
    return raw if raw.startswith(("http://", "https://")) else "https://" + raw


def rclone_env(cfg):
    """rclone configured entirely through the environment: no config file is written, and the
    secret never appears in a command line."""
    return {
        f"RCLONE_CONFIG_{REMOTE.upper()}_TYPE": "s3",
        f"RCLONE_CONFIG_{REMOTE.upper()}_PROVIDER": "Other",
        f"RCLONE_CONFIG_{REMOTE.upper()}_ACCESS_KEY_ID": cfg["B2_KEY_ID"],
        f"RCLONE_CONFIG_{REMOTE.upper()}_SECRET_ACCESS_KEY": cfg["B2_APP_KEY"],
        f"RCLONE_CONFIG_{REMOTE.upper()}_ENDPOINT": endpoint_url(cfg["B2_ENDPOINT"]),
        "RCLONE_S3_NO_CHECK_BUCKET": "true",
    }


def upload(local, key, cfg, env):
    dest = f"{REMOTE}:{cfg['B2_BUCKET']}/{key}"
    r = run(["rclone", "copyto", local, dest, "--retries", "3", "--low-level-retries", "5",
             "--stats", "0", "--log-level", "ERROR"], env=env)
    if r.returncode != 0:
        raise RuntimeError(f"upload of {key} failed: {r.stderr.strip()[:300]}")
    return dest


def verify_remote(key, cfg, env, expect_bytes):
    """The upload can 'succeed' and leave nothing there. Ask the bucket."""
    r = run(["rclone", "lsjson", f"{REMOTE}:{cfg['B2_BUCKET']}/{key}", "--log-level", "ERROR"],
            env=env)
    if r.returncode != 0:
        raise RuntimeError(f"remote verification of {key} failed: {r.stderr.strip()[:300]}")
    try:
        entries = json.loads(r.stdout or "[]")
    except ValueError:
        raise RuntimeError(f"remote verification of {key}: unreadable listing")
    if not entries:
        raise RuntimeError(f"remote verification of {key}: the object is NOT in the bucket")
    got = int(entries[0].get("Size", -1))
    if got != expect_bytes:
        raise RuntimeError(f"remote size mismatch for {key}: {got} != {expect_bytes}")
    return got


def write_status(payload):
    os.makedirs(os.path.dirname(STATUS_PATH), exist_ok=True)
    tmp = STATUS_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=1, sort_keys=True)
    os.replace(tmp, STATUS_PATH)


def previous_status():
    try:
        with open(STATUS_PATH, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--env", default=ENV_FILE)
    ap.add_argument("--dry-run", action="store_true",
                    help="build and verify the artefacts, upload nothing, write no status")
    ap.add_argument("--keep-local", action="store_true")
    a = ap.parse_args(argv)

    t0 = time.time()
    started = iso()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    prefix = datetime.now(timezone.utc).strftime("%Y/%m")
    prev = previous_status()
    status = {"started_at": started, "status": "RUNNING", "stamp": stamp,
              "last_success_at": prev.get("last_success_at")}

    workdir = tempfile.mkdtemp(prefix="fplbackup-")
    try:
        cfg = read_env(a.env)
        missing = [k for k in ("B2_KEY_ID", "B2_APP_KEY", "B2_BUCKET", "B2_ENDPOINT")
                   if not cfg.get(k)]
        if missing:
            raise RuntimeError(f"{a.env} is missing {missing}")

        counts = row_counts()
        log(f"row counts {counts}")
        status["row_counts"] = counts

        dump_path, dump_size = make_dump(workdir, stamp)
        n_tables = verify_dump(dump_path)
        log(f"dump {dump_size} bytes, pg_restore --list shows {n_tables} tables")

        data_path, data_size = make_data_tar(workdir, stamp)
        log(f"data archive {data_size} bytes (volume minus {list(SKIP_DIRS)})")

        status.update(dump_bytes=dump_size, data_bytes=data_size, dump_tables=n_tables,
                      dump_sha256=sha256(dump_path), data_sha256=sha256(data_path))

        dump_key = f"db/{prefix}/fpl_{stamp}.dump"
        data_key = f"data/{prefix}/model_data_{stamp}.tar.gz"
        status.update(dump_key=dump_key, data_key=data_key, bucket=cfg["B2_BUCKET"])

        if a.dry_run:
            log("dry run -- nothing uploaded, no status written")
            return 0

        env = rclone_env(cfg)
        upload(dump_path, dump_key, cfg, env)
        verify_remote(dump_key, cfg, env, dump_size)
        upload(data_path, data_key, cfg, env)
        verify_remote(data_key, cfg, env, data_size)

        status["status"] = "SUCCESS"
        status["finished_at"] = iso()
        status["last_success_at"] = status["finished_at"]
        status["duration_s"] = round(time.time() - t0, 1)
        write_status(status)
        log(f"SUCCESS in {status['duration_s']}s -- {dump_key} ({dump_size} B) + "
            f"{data_key} ({data_size} B), both verified in the bucket")
        return 0

    except Exception as e:                                   # noqa: BLE001
        status["status"] = "FAILED"
        status["finished_at"] = iso()
        status["duration_s"] = round(time.time() - t0, 1)
        status["error"] = f"{type(e).__name__}: {e}"[:400]
        if not a.dry_run:
            try:
                write_status(status)
            except OSError as e2:
                log(f"could not write the status file: {e2}")
        log(f"FAILED after {status['duration_s']}s -- {status['error']}")
        return 1
    finally:
        if not a.keep_local:
            shutil.rmtree(workdir, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
