# Alerting design — how the user finds out without visiting (2026-09-13). BUILT 2026-09-14 (see §6).

## 0. The problem, stated from the incident

On 2026-09-13 a dispatcher tick finished its work and never exited; its host lock silently skipped every
dispatcher and ingest tick for 13 hours. `/health` was `degraded` the whole time with two named reasons —
the alarm existed, in the one place it had been designed to exist — and nobody read it. Rule 12: a manual
step nothing performs is the same class as an unread status file; `/health` was the unread status file.
Every unattended run added this weekend (post-ingest, nightly 11:00Z, T-90 / T-30 / T-10, the scoring tick)
depends on someone noticing red. The missing piece is a CONSUMER of `/health` that reaches the user, and a
proof that the consumer itself is alive.

## 1. Two layers, because a probe on the host cannot report the host being gone

**Layer A — external watchdog (host down, API down, or degraded).** A free uptime monitor (UptimeRobot,
Better Stack — either free tier) polls `http://68.183.131.154:8000/health` every 5 minutes from outside and
alerts on: non-200 / timeout (the API or the droplet is gone) and a **keyword** match on the body,
`"degraded"` (both services offer keyword monitors on the free plan). Alert channel: the service's own push
app and/or email. This covers the failure a host-side probe cannot see, and costs one login and one form.
Limitation: its message is "keyword found", not the reasons — Layer B carries the detail.

**Layer B — a host-side probe with the reasons in the message.** A small script on the droplet, run by cron
every 10 minutes (plain `curl` + `python3` on the host — NOT a `docker compose run`, so it does not depend on
docker or the image and does not take any lock), reads `/health` and pushes a message when something changes.
Channel: **ntfy** (`https://ntfy.sh/<topic>` — one HTTPS POST per message, a free phone app that subscribes to
the topic, no account; the topic name is the only secret and lives in `/root/fpl-alert.env`, never in the
repo). Alternatives if ntfy is unwanted: Pushover (paid once, very reliable), a Telegram bot, or email through
an SMTP relay (credentials to manage). Recommendation: ntfy for pushes, with the external monitor's email as
the second path.

## 2. What is sent, and when — designed against alarm fatigue

State kept in `/var/lib/fpl-alert/state.json` (last status, last reasons set, last push per key, last
heartbeat). Messages:

| event | when | message |
|---|---|---|
| **DEGRADED** | `status != ok` on TWO consecutive probes (a single blip is not a page) | "fpl DEGRADED (since 03:20Z): • dispatcher has not ticked since … • weekly ingest cron has not ticked for 16h" — the `reasons` verbatim, plus `git_sha` |
| **changed** | the reasons set changes while degraded | the new set, once |
| **RECOVERED** | `ok` after degraded | one line, with how long it was red |
| **deadline-day runs** | each of t90 / t30 / t10 ends (from `dispatch_state.json` slots via /health) | "t90:GW5 SUCCESS run 12, 41 s, knows results through GW4" or "t10:GW5 FAILED (exit 1) → GAVE UP" — these matter on the day and are few |
| **post_ingest fired** | the slot appears | one line: GW confirmed, ingested at, build result, first `squad_scores` row written or not |
| **promise missed** | `/health` names a promised run that did not land | pushed as DEGRADED (it already is a reason) |
| **ACTION REQUIRED** | the ingest tick's `outstanding_actions` is non-empty (the scoring standing line, the manual steps) | the action text, once per distinct text per day |
| **heartbeat** | daily at 11:05Z (after the nightly slot) | "fpl ok · built <freshness line> · next <expected_next>" — one line a day |

Rate limits: one push per distinct (event, key) per 6 hours; a degraded state re-pushes at most every 6 hours
while it persists ("still degraded, 12h"). Nothing is sent for routine nightly successes except through the
heartbeat. The heartbeat is not decoration: **an alert channel that never fires is the unread status file
again**; the daily line proves the probe, the network, the topic and the phone app are all alive, and its
ABSENCE on a given day is itself the alarm ("no heartbeat since Tuesday" is something a person notices).

## 3. The probe, sketched (≈ 80 lines, pure Python 3 on the host)

`eval/health_alert.py` (kept in the repo, copied to the host by the deploy like the cron lines are):
read `/health` with a 15 s timeout → compute events against `state.json` → for each event past its rate
limit, POST to the ntfy topic (title, priority: high for DEGRADED / FAILED, default otherwise) → write the
state atomically. Exit code 0 always except a hard failure to read or write state (so cron mails nothing).
Failure of the probe itself is covered by the heartbeat's absence and by Layer A. Tests: the event state
machine (two-probe debounce, change detection, recovery, rate limiting, heartbeat window, ACTION dedupe) as
pure functions on dicts — no network in tests. Cron line (host crontab, next to the others):
`*/10 * * * * /usr/bin/python3 /root/fpl-copilot/eval/health_alert.py >> /var/log/fpl-alert.log 2>&1`
— NO `flock` on the dispatcher lock (it must run when the dispatcher cannot), its own lock only.

## 4. What the user does once

Install the ntfy app, subscribe to the topic (or use email); create the external monitor with the keyword
`degraded`; put the topic in `/root/fpl-alert.env`. Then the weekday routine becomes: no push = nothing
needs you; a push names the reason. The Tuesday checks in the fix log remain as the manual verification of
the first week.

## 5. What this does not do, said plainly

It does not fix anything; it tells a person. It does not see a wrong model that builds cleanly (the
Coventry / Hull artefact would have built with notes only — the strict detectors are the defence there,
and they raise, which becomes a FAILED run, which this pushes). It does not replace `/health`; it consumes
it. And it adds one more thing that must itself be alive — which is why the heartbeat is part of the design
and not an option.

## 6. Built (2026-09-14) — `eval/health_alert.py`, and the three things only the user can do

**What is in the repo.** `eval/health_alert.py`: standard-library Python 3 (the host has 3.12.3), no repo
imports, no docker, no shared lock. `plan(now, health, state)` is the pure state machine of §2 — debounce
(two consecutive probes for DEGRADED and for unreachable), the reasons verbatim, `changed`, `RECOVERED` with
the duration, one push per (event key) per 6 h and a "still degraded" re-push at that cadence, run outcomes
once per slot from `/health`'s `schedule.slots_this_gameweek` (SUCCESS priority 3 with the run's `built`
line; FAILED / GAVE_UP priority 5), ACTION REQUIRED once per distinct tick line per day, the daily 11:05Z
heartbeat with the `built` line and `expected_next`, and a failed push that does not consume the rate limit.
State is written atomically; `--dry-run` prints and writes nothing; exit 0 always except a missing topic
(2) or an unwritable state file (3), both printed on the log line. Tests: `Tests/test_health_alert.py`
(12, the state machine and the shell). Proof: dry run from the laptop against the live URL with the system
Python → `health=ok reasons=0 events=none (dry-run)`.

**Install on the droplet (three steps; the classifier blocks remote writes from the assistant, so these are
the user's):**

1. Pick a topic name nobody would guess (it is the only secret) and subscribe to it in the ntfy app on the
   phone (Android / iOS, free; or a browser at `https://ntfy.sh/<topic>`). Put it on the host:
   ```
   printf 'NTFY_TOPIC=<topic>\nHEALTH_URL=http://127.0.0.1:8000/health\n' > /root/fpl-alert.env && chmod 600 /root/fpl-alert.env
   ```
2. Add the cron line (host crontab, next to the three fpl lines; its OWN lock, never the dispatcher's):
   ```
   */10 * * * * flock -n /tmp/fpl-alert.lock /usr/bin/python3 /root/fpl-copilot/eval/health_alert.py >> /var/log/fpl-alert.log 2>&1
   ```
   First run by hand to see the log line and receive nothing (health is ok):
   `python3 /root/fpl-copilot/eval/health_alert.py` — then, to prove the phone end, a one-off manual message:
   `curl -d "fpl alert channel test" https://ntfy.sh/<topic>`. The first heartbeat arrives at 11:05Z the next
   day; if it does not, the channel is broken and that absence is the alarm.
3. Layer A, the external monitor: UptimeRobot (or Better Stack) free plan, HTTP(s) monitor on
   `http://68.183.131.154:8000/health`, interval 5 min, plus a keyword monitor on the same URL with keyword
   `degraded` (alert when found). Their app or email is the channel. This is what covers "the host is gone",
   which no probe on the host can report.

**The file reaches the host with every deploy** (`/root/fpl-copilot` is the checkout the deploy updates),
so cron always runs the committed version; an edit to the probe is a push, not a copy.

## 7. The blind spot it inherits (2026-09-15/16), and the rule

The probe was installed and correct when the dispatcher crashed after each of four successful builds on the
15th, and it pushed nothing: `/health` read `ok` for the whole incident because no failure was ever recorded.
An alert that consumes `/health` inherits every blind spot `/health` has. Rule, now in the handoff: alerting
on a health endpoint only alarms on states that endpoint can represent — for every alarm ask what failure
would leave the endpoint saying ok. Two reasons were added on the endpoint side for the two classes found
this week: a slot RUNNING for more than 90 minutes (a tick that died after or during its build), and a
served build whose model is degraded (the loud detector's MODEL DEGRADED findings, naming the club and its
lambda). The heartbeat remains the proof that the probe itself is alive; it is not a proof that `/health`
sees everything.

---

## 8. Topic rotation (2026-09-18)

**Why.** The ntfy topic was rotated because the old name had been pasted into a chat. On the public
ntfy.sh server the topic name is the ONLY access control — there is no key, no account, no ACL — so
anyone holding it can both read every alert and inject fake ones. `NTFY_SERVER` is unset, so the
public server is what we are on.

Checked before rotating, and worth recording because it bounds the exposure: the old topic value had
**never been committed** — zero commits across the whole history contained it, and no file in the
working tree did. The chat paste was its only escape.

**Neither the old nor the new value is recorded here, in any commit message, or in any log line.**

**How.** `/root/fpl-alert.env` rewritten atomically (`os.replace` onto a mode-600 temp file), with
`HEALTH_URL` preserved. The new value was staged to the server over stdin and consumed from a file,
never passed on a command line where it would reach `ps` or the shell history; the staged copies on
both ends were deleted. Verified afterwards without printing anything: topic changed, `HEALTH_URL`
unchanged and still `http://127.0.0.1:8000/health`, both keys present, mode 600, root-owned, old
value absent from the live file.

**Tested end to end, in two stages, against the real env and the real code path.**

1. A direct POST to the new topic — HTTP 200, accepted by the server.
2. The real probe run TWICE against a temporary state file, so `DEBOUNCE_PROBES = 2` pushed a genuine
   DEGRADED (the six Coventry reasons) rather than a synthetic message. `bad_streak = 2`,
   `degraded_pushed = True`.

Both arrived on the phone; the user then unsubscribed from the old topic.

**Three pushes arrived, not two, and that is expected.** Probe 1 also fired a heartbeat: a blank temp
state file has no `last_heartbeat_date`, and the run was past `HEARTBEAT_UTC`, so the probe correctly
concluded today's heartbeat had not been sent *on that state*. An artefact of testing against a fresh
state, not a fault.

**The production state file was not disturbed.** `/var/lib/fpl-alert/state.json` was last written by
the 19:30:02Z cron tick, before the 19:37:23Z test, and its mtime and hash were unchanged afterwards;
the test wrote only to `/tmp/alert-rotate-test.json`, which was removed. `/var/log/fpl-alert.log`
continued its ten-minute cadence throughout, every line `health=degraded reasons=6 events=none`.

**What rotation does NOT do.** It stops future traffic; it does not recall past traffic. Every message
already published to the old topic stays retrievable on ntfy.sh by anyone who knows the old name until
those messages age out of the server's cache. Rotation is the right fix and it is not retroactive.

Because the production state still records `degraded_pushed` for the standing Coventry condition, the
probe will not re-push DEGRADED on the new topic inside the six-hour rate limit. The first unprompted
production push on the new topic is therefore the daily heartbeat at 11:05Z — that, not the manual
test, is the proof that the CRON path picked up the new env.

**Open, minor: the old value still exists in two places on the server** — `/root/.bash_history` (from
when it was first set up by hand) and `/root/fpl-alert.env.bak.rotate-2026-09-18`, the pre-rotation
backup. Neither is read by anything. The backup's only sensitive content is the dead topic, since
`HEALTH_URL` is trivially recoverable, so it can be deleted once the rotation is considered settled;
the history line wants scrubbing for the same reason. Low urgency — the name is already burned and
nothing subscribes to it — but it is residue, and residue is how a value leaks a second time.
