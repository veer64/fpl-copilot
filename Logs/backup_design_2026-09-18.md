# Off-site backup to Backblaze B2 — design, build and restore runbook (2026-09-18)

Everything that matters lives on one DigitalOcean droplet. Two things on it are
irreplaceable: the **database** (squad versions, scores, runs, every proposal) and the
**odds snapshots** on the model volume, which cost the-odds-api credits and **cannot be
re-pulled for a past date**. A droplet failure loses both. This closes that.

---

## 1. What is taken, and what is not

**A logical dump, not a file copy.** `pg_dump -Fc --no-owner --no-privileges` via
`docker exec fpl-postgres`, taken against the running server. Copying the Postgres data
files while the server is writing gives a torn snapshot that may not restore at all — and
would look perfectly healthy until the day it was needed. Custom format gives compression,
`pg_restore --list` for verification, and selective restore.

No password appears anywhere: the container's `pg_hba.conf` carries `local all all trust`,
so `docker exec ... pg_dump -U postgres` authenticates over the local socket. The cron line
holds no credential.

**The model volume, minus `live/`.** `live/` is deadline frames, build and ingest status
archives and `dispatch_state.json` — all rebuilt by the next tick, and explicitly out of
scope.

Everything else is kept rather than enumerating odds files, for three reasons: the odds sit
in **two** places (`odds_props/`, 23.4 MB, and `history/odds_*` including
`odds_all_seasons_with_2026_27.parquet`, which carries the live pre-deadline pulls), so "the
odds snapshots" is already a list that is easy to get subtly wrong; the whole volume is
**69 MB** of which 57 MB is kept; and B2 is about **$6/TB/month**, so selectivity saves
nothing measurable while mis-classifying one irreplaceable file as rebuildable costs
everything. Measured 2026-09-18: database **23 MB**, volume **69.4 MB**
(`odds_props` 23.4, `history` 32.9, `live` 11.8, `horizon` 0.4).

**Deliberately NOT taken: `/root/fpl-copilot/.env`.** Putting plaintext Anthropic and
odds-API keys in a cloud bucket trades one exposure for another, and every key in it is
re-issuable. `gpg` is on the box if that judgement is ever revisited.

**A gap this does not close:** `fplcache`, the point-in-time availability snapshots, is
**not on the droplet** — it exists only on the laptop. Its 6-hourly cadence means it cannot
be reconstructed for a past date either. That is a separate and arguably larger exposure
than the 23 MB database.

## 2. Credentials

`/root/fpl-backup.env`, mode 600, root-owned, **never in the repo**:
`B2_KEY_ID  B2_APP_KEY  B2_BUCKET  B2_ENDPOINT`.

**A dedicated file, not `/root/fpl-copilot/.env`.** The app's `.env` is `env_file` for both
containers, so B2 credentials placed there would be injected into every container's
environment and visible in `docker inspect`, for no benefit — the backup runs on the host and
the app never needs B2.

**The key must not carry `deleteFiles`,** and is scoped to the bucket. A backup credential
that can delete backups means whoever takes the droplet takes the backups with it. Retention
is therefore a **B2 lifecycle rule, server side**, never a delete from this script.

**They never reach a command line.** rclone is configured entirely through
`RCLONE_CONFIG_B2S3_*` environment variables, so the secret is not visible in `ps`, not in
shell history, and no second copy is written to an rclone config file. A test asserts that
the only function reading `B2_APP_KEY` is `rclone_env` — in particular not the two functions
that build argv.

**The endpoint is normalised to `https://`.** B2 states it as a bare host and that is how it
lands in an env file; an off-site backup must not leave the droplet unencrypted because of
how a value was typed.

## 3. When, and with which lock

`43 3 * * *` — host cron, **its own lock `/tmp/fpl-backup.lock`**, never the dispatcher's.
Same reasoning as the alert probe: a backup that the thing it protects can block is not a
backup.

`:43` collides with nothing. Taken already: every `*/10` minute (poller, dispatcher, alert
probe) and `:17` every six hours (ingest). 03:43Z is also clear of the 11:00Z nightly and of
every deadline window.

It does need `docker exec` to reach Postgres — unavoidable, that is the thing being dumped —
but it takes no lock the pipeline uses.

## 4. Verification, because "a file was uploaded" is not "a backup exists"

| check | what it catches |
|---|---|
| row counts on `squad_versions`, `squad_scores`, `model_runs`, `model_predictions` | a dump that restores cleanly but carries half the rows |
| size floors (200 KB dump, 5 MB data) | a truncated or empty artefact |
| `pg_restore --list` **before** upload | a corrupt archive, and confirms it names TABLE DATA entries |
| remote `lsjson` **after** upload, size compared | an upload that "succeeded" and left nothing in the bucket |

The floors are deliberately far below current reality (23 MB / 57 MB) and far above empty.
**Raise them if the data grows an order of magnitude; never lower them to make a run pass.**

## 5. Alarming — on failure AND on silence

Status is written to `data/live/BACKUP_STATUS.json` on the model volume, the same convention
the weekly ingest uses, and `model_tools._backup_status()` turns it into `/health` reasons.
The **existing probe and ntfy path** carry it; there is no second alert channel to keep alive.

Applying the standing rule — *what failure would leave this looking fine?*

| failure | caught by |
|---|---|
| cron removed, nothing ever runs | `BACKUP_STATUS.json` missing → "has NEVER run" |
| cron silently stops; last status still says SUCCESS | `last_success_at` older than **30 h** → "has not succeeded for Nh". **This is the one the whole feature exists for**: from outside, a backup that stopped three weeks ago is indistinguishable from a working one |
| a run fails | `status: FAILED` + the error text |
| every run fails, none ever succeeded | "has never SUCCEEDED" |
| status file corrupt | "unreadable" |
| `/health` itself down | the UptimeRobot monitor (§9 of the alerting log) |
| the droplet is gone | UptimeRobot — and at that point the backups being off-site is the entire point |

30 h is chosen so **one missed nightly is already a reason**, not tolerated.

**What none of this proves is that a dump can actually be restored.** `pg_restore --list`
proves the archive is readable, not that a restore succeeds. Only a rehearsal does. Until one
is scheduled, "backup succeeded" is a claim about the uploader.

## 6. What it logs

`/var/log/fpl-backup.log`, one line per run, plus the status JSON: status, started/finished,
duration, **size of each artefact**, **destination key**, sha256 of each, the four row counts,
and the `pg_restore --list` table count.

## 7. Restore runbook — read this before you need it

A backup nobody has restored is a hypothesis. To restore the database into a scratch
database on the droplet, without touching `fpl`:

```
# 1. fetch the artefact (rclone env as in the script)
rclone copyto b2s3:<bucket>/db/YYYY/MM/fpl_<stamp>.dump /tmp/restore.dump

# 2. prove it is readable and see what is in it
docker cp /tmp/restore.dump fpl-postgres:/tmp/r.dump
docker exec fpl-postgres pg_restore --list /tmp/r.dump | head

# 3. restore into a SCRATCH database, never over fpl
docker exec fpl-postgres psql -U postgres -c 'CREATE DATABASE fpl_restore_test'
docker exec fpl-postgres pg_restore -U postgres -d fpl_restore_test --no-owner /tmp/r.dump

# 4. compare the tripwires against the row counts in BACKUP_STATUS.json
docker exec fpl-postgres psql -U postgres -d fpl_restore_test -tAc \
  "select 'squad_versions='||(select count(*) from squad_versions)
      ||' squad_scores='||(select count(*) from squad_scores)"

# 5. drop it
docker exec fpl-postgres psql -U postgres -c 'DROP DATABASE fpl_restore_test'
```

The volume archive is a plain `tar.gz` of the volume root; unpack it over a fresh
`fpl_model_data` volume, then let the next tick rebuild `live/`.

**gzip, not zstd**, deliberately: parquet is already compressed so the ratio barely differs,
and gzip is readable on any machine someone might be restoring from in a hurry.

## 8. Where it lives

| path | what |
|---|---|
| `eval/backup_b2.py` | the script — host, stdlib only, mirroring `eval/health_alert.py` |
| `model_tools.py` | `_backup_status()` + `freshness["backup"]` and the reasons |
| `Tests/test_backup_b2.py` | 19 tests — env contract, secret handling, endpoint normalisation, floors, and every alarm branch |
| `/root/fpl-backup.env` | credentials, mode 600, untracked |
| `data/live/BACKUP_STATUS.json` | status, on the volume, read by `/health` |
| `/var/log/fpl-backup.log` | the log |

## 9. Open

* **No restore rehearsal is scheduled yet.** §7 is the manual procedure; a monthly automated
  rehearsal into a scratch database, checking row counts against the status file, is the only
  thing that converts "a file was uploaded" into "a backup exists".
* **Retention is not configured here.** It belongs in a B2 lifecycle rule so the key never
  needs delete. Proposed: 90 daily copies, monthly kept indefinitely.
* **`fplcache` is unprotected** (§1).
