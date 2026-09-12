# run_weekly_ingest.py -- the unattended WEEKLY INGEST (first cut 2026-09-11).
#
# THE GAP THIS CLOSES: until now the weekly ingest ran on the laptop, by hand,
# and was synced to the server by tar; nothing on the server performed it. GW4
# nearly built on history through GW2 for exactly that reason. A weekly manual
# step nothing performs is the same class of problem as an unread status file.
#
# WHAT IT DOES, in the runbook's order (Logs/gw2_ingest_and_weekly_refresh_log.md):
#     1. fetch_fpl_history --gw N       for every FINAL gameweek not yet ingested
#        (FPL's own finished+data_checked flag; the fetcher's gate refuses early pulls)
#        then --combine
#     2. understat_matches               (deferred matches are listed, never gw=None)
#     3. build_understat_aggregates      then --combine
#     4. build_crosswalk                 (the weekly rebuild; the duplicate sweep raises)
#     5. fetch_fixtures  then --combine  (results for the DC fit; PRICES PRESERVED, see below)
#     6. fetch_live_odds                 (1 credit; prices the provider's upcoming events)
#     7. build_forward_skeleton          LAST -- a master that gained a gameweek while
#                                        the skeleton still carries it trips
#                                        season_stack.load_stack's collision assert,
#                                        and the deadline build would FAIL until this runs
#
# FAILURE CONTRACT (the deadline runner's, eval/run_live_deadline.py):
#   * every subprocess exit code is checked -- non-zero FAILS the run and STOPS it;
#     no pipes anywhere (the `| grep -v` exit-code swallow of 2026-08-31);
#   * a strict stop, never a workaround: prices lost across the fixture rebuild,
#     a skeleton colliding with the master, a step that raised -- each FAILS the
#     run with the finding in the status file; nothing is patched around;
#   * ANY exception writes a FAILED status with the traceback; exit 1;
#   * atomic writes via os.replace with the bounded PermissionError retry;
#   * bounded retries per gameweek (MAX_ATTEMPTS, counted in a sidecar) so a
#     persistent failure surfaces as a standing FAILED status, not an every-6h
#     credit burn; a PARTIAL marker makes a gameweek whose chain broke half-way
#     eligible again even though its rows are already in the season file.
#
# WHAT A MAINTAINER SEES (data/live/, on the volume; also via /health):
#     INGEST_STATUS.txt   the last run that had work: SUCCESS / FAILED, first line;
#                         ACTION REQUIRED blocks first -- the elements with real
#                         minutes and NO Understat id (the Savio/Cherki class), each
#                         with its nearest Understat candidates; and any element
#                         whose id CHANGED week to week (the alarm condition)
#     INGEST_TICK.txt     the last cron tick's decision (NOTHING-NEW / DEFERRED /
#                         ran), re-listing the outstanding ACTION REQUIRED items
#     INGEST_RUN.log      full step output, nothing swallowed
#     ingest_manifest_gwN.json / ingest_manifest_latest.json
#                         sha256 + content digest + rows of every live-path input,
#                         BEFORE and AFTER -- the two machines' volumes drifted for a
#                         week unnoticed (2026-09-11: 138-row reproduction diff), so
#                         no reproduction claim is made without comparing these first
#                         (`--hash-only` prints the same manifest on any machine)
#
# SCHEDULING: host cron every 6 hours (the cron line is in the server runbook);
# the runner's own gates decide: nothing to do unless a final gameweek is
# un-ingested; refuses to START inside a deadline window (deadline-3h ..
# deadline+1h) so the T-90 build never reads inputs mid-rewrite and no odds
# credit is spent next to the build's own pull; refuses while a match is in
# play (fetch_fixtures would refuse the unscored past kickoff anyway).
#
# Usage:  python eval/run_weekly_ingest.py --season 2026-27
#         python eval/run_weekly_ingest.py --season 2026-27 --force-gw 3   # re-ingest (idempotent upsert)
#         python eval/run_weekly_ingest.py --season 2026-27 --hash-only    # print the manifest, nothing else
#
# Do not add modelling here. Ingest only.

import argparse
import hashlib
import io
import json
import re
import shutil
import subprocess
import sys
import traceback
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parent.parent
PY = sys.executable
sys.path.insert(0, str(REPO / "eval"))
from _replace_retry import replace_with_retry  # noqa: E402

API = "https://fantasy.premierleague.com/api"
MAX_ATTEMPTS = 8            # 6-hourly cron -> two days of retries, then a standing FAILED
MAX_SCORING_ATTEMPTS = 8    # same shape for squad scoring: then a standing, actionable line


def scoring_instruction(last_error, gw):
    """What a human should DO when scoring has given up -- keyed on the failure
    class the scorer puts in square brackets (the Cherki mechanism: name the
    fix, not just the failure). Every branch ends with how to re-arm."""
    rearm = (f"  re-arm: delete the '{gw if gw is not None else 'global'}' entry from "
             "data/live/scoring_attempts.json (or the file) and the next tick retries.")
    e = last_error or ""
    if "[inconsistent_versions]" in e:
        return (f"  the versions written for GW{gw} disagree with their own hit arithmetic (transfers vs "
                "allowance vs recorded hits). Inspect them:\n"
                f"    SELECT version_id, gw, created_at, squad_json->'provenance' FROM squad_versions "
                f"WHERE gw = {gw} ORDER BY version_id;\n"
                "  fix by writing a corrected version through set_my_squad (a NEW row; rows are never "
                "edited), then\n" + rearm)
    if "[master_missing]" in e:
        return (f"  GW{gw} is in the season file but the master has no rows for it. Re-ingest it outside "
                f"a deadline window:\n    docker compose run --rm fpl-scheduler uv run python "
                f"eval/run_weekly_ingest.py --season 2026-27 --force-gw {gw}\n" + rearm)
    if "[db_unreachable]" in e or "[master_unreadable]" in e:
        return ("  the scorer could not reach its inputs: check `docker ps` (fpl-postgres healthy?), the "
                "DB_* values in /root/fpl-copilot/.env, and that data/history/fpl_api_2026_27.parquet "
                "reads; try\n    docker compose run --rm --no-deps fpl-scheduler uv run python -c "
                "\"import db_write; db_write.connect(); print('db ok')\"\n" + rearm)
    return ("  unclassified failure: read the traceback in data/live/INGEST_RUN.log (the "
            "'===== score_squads' block), fix the cause, then\n" + rearm)
WINDOW_BEFORE_H = 3.0       # refuse to start inside deadline-3h ..
WINDOW_AFTER_H = 1.0        # .. deadline+1h (the build and its Postgres write are done by then)
STEP_TIMEOUT = 1800         # fetch_fpl_history: ~630 element-summary calls at 0.4s
TICK_STALE_H = 13.0         # /health: a tick older than this means the cron is dead


def utc_now():
    return datetime.now(timezone.utc)


def stamp(dt=None):
    return (dt or utc_now()).strftime("%Y-%m-%d %H:%M:%SZ")


def git_sha():
    try:
        head = (REPO / ".git" / "HEAD").read_text().strip()
        if head.startswith("ref:"):
            return (REPO / ".git" / head.split(None, 1)[1]).read_text().strip()[:9]
        return head[:9]
    except OSError:
        return None


def _fetch_json(path):
    import fetch_fpl_history as ff          # its get_json: 3 tries, backoff, real UA
    return ff.get_json(path)


def _atomic_write_text(path, text):
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    replace_with_retry(tmp, path)


# ----------------------------------------------------------------------------
# the live-path input set (what a deadline build reads) -- hashed before/after
# ----------------------------------------------------------------------------
def live_inputs(data_dir, season):
    tag = season.replace("-", "_")
    short = season[2:4] + season[5:7]
    h = data_dir / "history"
    fixed = [
        h / "all_seasons_fixed.parquet",
        h / f"fpl_api_{tag}.parquet",
        h / f"all_seasons_with_{tag}.parquet",
        h / f"forward_skeleton_{tag}.parquet",
        h / f"forward_skeleton_{tag}.provenance.json",
        h / f"understat_matches_{tag}.parquet",
        h / "understat_season_aggregates.parquet",
        h / f"understat_season_aggregates_{tag}.parquet",
        h / f"understat_season_aggregates_with_{tag}.parquet",
        h / f"crosswalk_{tag}.csv",
        h / "odds_all_seasons.parquet",
        h / f"odds_fixtures_{tag}.parquet",
        h / f"odds_all_seasons_with_{tag}.parquet",
        data_dir / f"availability_{short}.parquet",
        data_dir / "live" / f"availability_{tag}_live.parquet",
        data_dir / "live" / f"availability_{season}_fplcache.parquet",
    ]
    # the prior season's per-match Understat file (the k=8 rate blend's prior)
    prior = f"{int(season[:4]) - 1}_{season[2:4]}"
    fixed.append(h / f"understat_matches_{prior}.parquet")
    # historical availability (training reads every data/availability_*.parquet that
    # availability_features.load() globs; the season files are availability_NNNN.parquet
    # -- the availability_measurement_* research files are not inputs)
    import re
    fixed += sorted(p for p in data_dir.glob("availability_*.parquet")
                    if re.fullmatch(r"availability_\d{4}\.parquet", p.name)
                    and p.name != f"availability_{short}.parquet")
    return fixed


VOLATILE_COLS = ("pulled_at", "built_at")   # run timestamps a writer stamps into its rows


def content_digest(path):
    """Order-independent digest of a table's CONTENT (parquet/csv): sorted per-row
    hashes -> sha256. Two machines writing the same rows with different pyarrow
    builds can differ in file bytes but not here. Writer timestamps
    (VOLATILE_COLS) are excluded -- they differ on every pull by construction
    and would hide a real match. None for non-tables."""
    if path.suffix == ".parquet":
        df = pd.read_parquet(path)
    elif path.suffix == ".csv":
        df = pd.read_csv(path, low_memory=False)
    else:
        return None
    df = df[sorted(c for c in df.columns if c not in VOLATILE_COLS)]
    rows = pd.util.hash_pandas_object(df, index=False).values.copy()
    rows.sort()
    return dict(digest=hashlib.sha256(rows.tobytes()).hexdigest(),
                rows=int(len(df)), cols=int(len(df.columns)))


def manifest(data_dir, season, content=True):
    out = {}
    for p in live_inputs(data_dir, season):
        rel = str(p.relative_to(data_dir)).replace("\\", "/")
        if not p.exists():
            out[rel] = None
            continue
        st = p.stat()
        entry = dict(size=st.st_size,
                     mtime=datetime.fromtimestamp(st.st_mtime, tz=timezone.utc).isoformat(),
                     sha256=hashlib.sha256(p.read_bytes()).hexdigest())
        if content:
            try:
                entry["content"] = content_digest(p)
            except Exception as e:  # noqa: BLE001 -- a digest failure is recorded, never fatal
                entry["content"] = f"ERROR {type(e).__name__}: {e}"
        out[rel] = entry
    return out


def compare_manifests(a, b):
    """Paths whose sha256 or content digest differ (or exist on one side only)."""
    diffs = []
    for k in sorted(set(a) | set(b)):
        x, y = a.get(k), b.get(k)
        if (x is None) != (y is None):
            diffs.append((k, "present on one side only"))
        elif x is not None and y is not None:
            if x.get("sha256") != y.get("sha256"):
                cx, cy = x.get("content"), y.get("content")
                same_content = (isinstance(cx, dict) and isinstance(cy, dict)
                                and cx.get("digest") == cy.get("digest"))
                diffs.append((k, "bytes differ, content identical" if same_content else "content differs"))
    return diffs


# ----------------------------------------------------------------------------
# the checks
# ----------------------------------------------------------------------------
def played_priced(slice_path):
    """{(Date, HomeTeam, AwayTeam): (H, D, A)} for PLAYED fixtures that carry prices --
    the market the deadline frame was built with; must survive the rebuild."""
    if not slice_path.exists():
        return {}
    df = pd.read_parquet(slice_path, columns=["Date", "HomeTeam", "AwayTeam", "FTHG",
                                              "B365H", "B365D", "B365A"])
    df = df[df["FTHG"].notna() & df["B365H"].notna()]
    return {(r.Date, r.HomeTeam, r.AwayTeam): (float(r.B365H), float(r.B365D), float(r.B365A))
            for r in df.itertuples()}


def prices_lost(before, after):
    lost = []
    for k, v in before.items():
        w = after.get(k)
        if w is None or any(abs(a - b) > 1e-9 for a, b in zip(v, w)):
            lost.append((k, v, w))
    return lost


def stack_collision(data_dir, season):
    """season_stack.load_stack's assert, evaluated on the files directly: a
    forward-skeleton fixture the master also carries means a STALE skeleton."""
    tag = season.replace("-", "_")
    h = data_dir / "history"
    stack = h / f"all_seasons_with_{tag}.parquet"
    skel = h / f"forward_skeleton_{tag}.parquet"
    if not (stack.exists() and skel.exists()):
        return None
    m = pd.read_parquet(stack, columns=["season", "fixture"])
    m = m[m["season"] == season]
    f = pd.read_parquet(skel, columns=["season", "fixture"])
    dup = set(m["fixture"].astype(int)) & set(f["fixture"].astype(int))
    return sorted(dup)


def crosswalk_map(path):
    if not path.exists():
        return {}
    cw = pd.read_csv(path)
    cw = cw[cw["understat_id"].notna()]
    return {int(e): str(u).split(".")[0] for e, u in zip(cw["element"], cw["understat_id"])}


def unmatched_with_minutes(data_dir, season, top=3):
    """Elements with real minutes this season and no Understat id -- the one thing
    a human must look at each week. Each with its nearest Understat candidates
    (name score over the season's aggregate listing) so the MANUAL entry can be
    evidenced in one look."""
    tag = season.replace("-", "_")
    h = data_dir / "history"
    api_p = h / f"fpl_api_{tag}.parquet"
    if not api_p.exists():
        return []
    api = pd.read_parquet(api_p, columns=["element", "name", "team", "position", "minutes"])
    played = (api[api["minutes"] > 0].groupby("element")
              .agg(name=("name", "last"), team=("team", "last"),
                   position=("position", "last"), minutes=("minutes", "sum")))
    cw = crosswalk_map(h / f"crosswalk_{tag}.csv")
    missing = played[~played.index.isin(cw)]
    if len(missing) == 0:
        return []
    claimed = {u: e for e, u in cw.items()}
    cands = None
    agg_p = h / f"understat_season_aggregates_with_{tag}.parquet"
    if agg_p.exists():
        year = season[:4]
        a = pd.read_parquet(agg_p, columns=["id", "player_name", "team_title", "games", "time",
                                            "understat_season"])
        cands = a[a["understat_season"].astype(str) == year]
    out = []
    try:
        from rapidfuzz import fuzz
        from build_crosswalk import _norm
    except ImportError:            # candidates are a convenience; the list is the contract
        fuzz = None
    for el, r in missing.sort_values("minutes", ascending=False).iterrows():
        item = dict(element=int(el), name=r["name"], team=r["team"], position=r["position"],
                    minutes=int(r["minutes"]), candidates=[])
        if cands is not None and fuzz is not None and len(cands):
            key = _norm(r["name"])
            sc = cands["player_name"].map(lambda s: fuzz.token_set_ratio(key, _norm(s)))
            best = cands.assign(score=sc).sort_values("score", ascending=False).head(top)
            for c in best.itertuples():
                item["candidates"].append(dict(
                    id=str(c.id), name=c.player_name, team=c.team_title,
                    games=str(c.games), minutes=str(c.time), score=int(c.score),
                    claimed_by=claimed.get(str(c.id))))
        out.append(item)
    return out


def format_unmatched(items):
    if not items:
        return "  none -- every element with real minutes carries an Understat id"
    lines = [f"  {len(items)} element(s) with real minutes and NO Understat id. Each rides the "
             f"positional prior (the Cherki class, ~+1.3 e_points/row if it reaches the top 30)",
             "  until an evidenced MANUAL entry lands in eval/build_crosswalk.py (a human step;",
             "  the next weekly run rebuilds the crosswalk with it). Understat lists a player only",
             "  after his first appearance, so a candidate list that is empty or low-scoring can",
             "  mean 'not listed yet' -- check again next week before pinning."]
    for it in items:
        lines.append(f"  element {it['element']:<4d} {it['name']:<34.34s} {it['team']:<14.14s} "
                     f"{it['position']:<3s} {it['minutes']:>4d} min")
        for c in it["candidates"]:
            tag = f"  [already claimed by element {c['claimed_by']}]" if c["claimed_by"] else ""
            lines.append(f"      candidate {c['id']:>6s} {c['name']:<28.28s} {c['team']:<22.22s} "
                         f"{c['games']:>2s} games {c['minutes']:>4s} min  score {c['score']:3d}{tag}")
        if not it["candidates"]:
            lines.append("      (no Understat listing scored -- probably not listed yet)")
    return "\n".join(lines)


# ----------------------------------------------------------------------------
# the plan: what this tick should do
# ----------------------------------------------------------------------------
def plan(events, fixtures, have_gws, partial_gws, now, force_gw=None):
    """Returns (decision, todo, detail). decision in {"RUN", "NOTHING-NEW", "DEFERRED"}."""
    final = sorted(int(e["id"]) for e in events if e.get("finished") and e.get("data_checked"))
    todo = [g for g in final if g not in have_gws or g in partial_gws]
    if force_gw is not None:
        todo = [int(force_gw)]
    nxt = None
    for e in events:
        dl = datetime.fromisoformat(e["deadline_time"].replace("Z", "+00:00"))
        if dl > now:
            nxt = (int(e["id"]), dl)
            break
    pending = next((e for e in events if not (e.get("finished") and e.get("data_checked"))), None)
    detail = dict(final_gws=final, have_gws=sorted(have_gws), partial_gws=sorted(partial_gws),
                  next_deadline=(f"GW{nxt[0]} {nxt[1]:%Y-%m-%dT%H:%MZ}" if nxt else None),
                  next_unfinal=(f"GW{pending['id']}: finished={pending.get('finished')} "
                                f"data_checked={pending.get('data_checked')}" if pending else None))
    if not todo:
        return "NOTHING-NEW", [], detail
    # every deadline, past or future: the window straddles it (the build fires at
    # T-90 and writes Postgres just after the deadline)
    for e in events:
        dl = datetime.fromisoformat(e["deadline_time"].replace("Z", "+00:00"))
        if dl - timedelta(hours=WINDOW_BEFORE_H) <= now <= dl + timedelta(hours=WINDOW_AFTER_H):
            detail["reason"] = (f"inside the GW{int(e['id'])} deadline window (deadline "
                                f"{dl:%Y-%m-%dT%H:%MZ}; window deadline-{WINDOW_BEFORE_H:.0f}h .. "
                                f"+{WINDOW_AFTER_H:.0f}h): the T-90 build must not read inputs mid-rewrite")
            return "DEFERRED", todo, detail
    in_play = []
    for f in fixtures or []:
        ko = f.get("kickoff_time")
        if not ko:
            continue
        kot = datetime.fromisoformat(ko.replace("Z", "+00:00"))
        scored = f.get("finished") or (f.get("finished_provisional") and f.get("team_h_score") is not None)
        if kot < now and not scored:
            in_play.append(int(f["id"]))
    if in_play:
        detail["reason"] = (f"{len(in_play)} fixture(s) past kickoff without a score (in play / "
                            f"abandoned): {in_play[:4]} -- fetch_fixtures would refuse; next tick")
        return "DEFERRED", todo, detail
    return "RUN", todo, detail


# ----------------------------------------------------------------------------
# the runner
# ----------------------------------------------------------------------------
class Runner:
    def __init__(self, season, data_dir=None, run_cmd=None, fetch_json=None):
        self.season = season
        self.tag = season.replace("-", "_")
        self.data_dir = Path(data_dir) if data_dir else REPO / "data"
        self.live = self.data_dir / "live"
        self.live.mkdir(parents=True, exist_ok=True)
        self.run_cmd = run_cmd or self._subprocess
        self.fetch_json = fetch_json or _fetch_json
        self.status_path = self.live / "INGEST_STATUS.txt"
        self.tick_path = self.live / "INGEST_TICK.txt"
        self.log_path = self.live / "INGEST_RUN.log"
        self.log_f = None
        self.sections = []
        self.actions = []           # ACTION REQUIRED blocks (title, text) -- printed FIRST
        self.failed = None
        self.decision = None
        self.todo = []
        self.detail = {}
        self.steps_run = []

    # -- infrastructure -------------------------------------------------------
    def _subprocess(self, args, timeout):
        r = subprocess.run([PY] + args, cwd=str(REPO), stdout=subprocess.PIPE,
                           stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                           errors="replace", timeout=timeout)
        return r.returncode, r.stdout or ""

    def log(self, text):
        if self.log_f is None:
            self.log_f = self.log_path.open("w", encoding="utf-8", errors="replace")
        self.log_f.write(text + "\n")
        self.log_f.flush()

    def section(self, title, text):
        self.sections.append((title, text))

    def action(self, title, text):
        self.actions.append((title, text))

    def run_step(self, name, args, timeout=STEP_TIMEOUT):
        """One CLI step. Output to the run log; the exit code is law."""
        self.log(f"\n===== {name} @ {stamp()} =====")
        self.log("$ " + " ".join(["python"] + args))
        code, out = self.run_cmd(args, timeout)
        self.log(out)
        self.log(f"===== {name} exit code {code} =====")
        self.steps_run.append((name, code))
        if code != 0:
            raise RuntimeError(f"step '{name}' exited {code}. Last output:\n{out[-1500:]}")
        return out

    # -- markers ----------------------------------------------------------------
    def _partial(self, gw):
        return self.live / f"ingest_gw{gw}.partial.json"

    def _attempts(self, gw):
        return self.live / f"ingest_gw{gw}.attempts.json"

    def partial_gws(self):
        return {int(p.name[len("ingest_gw"):-len(".partial.json")])
                for p in self.live.glob("ingest_gw*.partial.json")}

    def have_gws(self):
        p = self.data_dir / "history" / f"fpl_api_{self.tag}.parquet"
        if not p.exists():
            return set()
        return {int(g) for g in pd.read_parquet(p, columns=["GW"])["GW"].unique()}

    # -- the status files -------------------------------------------------------
    def _header(self, first):
        return (f"{first}\n"
                f"weekly ingest {self.season} -- written {stamp()} -- git {git_sha() or 'unknown'} -- "
                f"data {self.data_dir}\n")

    def write_tick(self, first, body):
        buf = io.StringIO()
        buf.write(self._header(first))
        buf.write(body)
        buf.write(f"\nLast run with work: {self.status_path.name} "
                  f"({'exists' if self.status_path.exists() else 'none yet'})\n")
        _atomic_write_text(self.tick_path, buf.getvalue())
        print(f"tick -> {self.tick_path}: {first}")

    def write_status(self):
        n_act = len(self.actions)
        if self.failed:
            first = "FAILED"
        elif n_act:
            first = f"SUCCESS -- ACTION REQUIRED ({n_act} item{'s' if n_act > 1 else ''}, see below)"
        else:
            first = "SUCCESS"
        buf = io.StringIO()
        buf.write(self._header(first))
        buf.write(f"gameweek(s) ingested this run: {self.todo or 'none'}\n")
        if self.failed:
            buf.write(f"\nFAILURE:\n{self.failed}\n")
            buf.write("\nCONSEQUENCE: the chain stopped where it failed; earlier steps' files are "
                      "written (each step is idempotent). Until a re-run SUCCEEDS the forward "
                      "skeleton may be STALE against the master and the next deadline build will "
                      "FAIL on the collision assert -- by design, not silently.\n"
                      f"The next cron tick retries (attempt budget {MAX_ATTEMPTS} per gameweek).\n")
        for title, text in self.actions:
            buf.write(f"\n== ACTION REQUIRED: {title} ==\n{text}\n")
        for title, text in self.sections:
            buf.write(f"\n== {title} ==\n{text}\n")
        buf.write(f"\nFull step output: {self.log_path.name}\n")
        _atomic_write_text(self.status_path, buf.getvalue())
        print(f"status -> {self.status_path}: {first}")
        if self.log_f is not None:
            self.log_f.close()
            self.log_f = None
        # per-gameweek copies for history (the latest files are overwritten weekly)
        for gw in self.todo:
            try:
                shutil.copyfile(self.status_path, self.live / f"INGEST_GW{gw}_STATUS.txt")
                if self.log_path.exists():
                    shutil.copyfile(self.log_path, self.live / f"INGEST_GW{gw}_RUN.log")
            except OSError:
                pass
        return first

    # -- the run ----------------------------------------------------------------
    def decide(self, now=None, force_gw=None):
        now = now or utc_now()
        events = self.fetch_json("/bootstrap-static/")["events"]
        fixtures = self.fetch_json("/fixtures/")
        self.events = events
        self.decision, self.todo, self.detail = plan(
            events, fixtures, self.have_gws(), self.partial_gws(), now, force_gw)
        return self.decision

    def outstanding_actions(self):
        """Recomputed on every tick from the files on disk, so a standing item
        stays visible until a human closes it."""
        items = unmatched_with_minutes(self.data_dir, self.season)
        if items:
            self.action("crosswalk -- elements with minutes and no Understat id",
                        format_unmatched(items))
        return items

    # ------------------------------------------------ squad scoring (tick-level)
    def _scoring_attempts(self):
        p = self.live / "scoring_attempts.json"
        try:
            return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
        except (OSError, ValueError):
            return {}

    def _save_scoring_attempts(self, d):
        p = self.live / "scoring_attempts.json"
        if d:
            _atomic_write_text(p, json.dumps(d, indent=1))
        elif p.exists():
            p.unlink()

    def score_outstanding(self):
        """Score every ingested gameweek that has no squad_scores row yet
        (eval/score_squads.py; Decision 2, 2026-09-12). Runs on EVERY tick --
        after a successful chain and on NOTHING-NEW ticks -- so a scoring
        failure (Postgres down, inconsistent versions) is retried six hours
        later without anyone remembering to. It never fails the ingest: a
        non-zero exit becomes an ACTION REQUIRED line (so /health degrades)
        and the chain's markers are untouched. Gameweeks whose deadline came
        before the squad existed are reported and skipped, never backfilled.

        Retries are BOUNDED, like the ingest's own: after MAX_SCORING_ATTEMPTS
        failures for one gameweek (or for the scorer as a whole) that gameweek
        is left out of the request and a STANDING line names what a human
        should do and how to re-arm -- an alarm that can never clear is closed
        by being ignored. Success clears the counter."""
        events = getattr(self, "events", None)
        if not events:
            return None
        have = sorted(self.have_gws())
        att = self._scoring_attempts()
        gave_up = sorted(g for g in have if att.get(str(g), {}).get("attempts", 0) >= MAX_SCORING_ATTEMPTS)
        for g in gave_up:
            e = att[str(g)]
            self.action(f"squad scoring for GW{g} GAVE UP after {e['attempts']} attempts -- human needed",
                        f"  last failure {e.get('last_failed')}: {e.get('last_error')}\n"
                        + scoring_instruction(e.get("last_error") or "", g))
        if att.get("global", {}).get("attempts", 0) >= MAX_SCORING_ATTEMPTS:
            e = att["global"]
            self.action(f"squad scoring GAVE UP after {e['attempts']} whole-run failures -- human needed",
                        f"  last failure {e.get('last_failed')}: {e.get('last_error')}\n"
                        + scoring_instruction(e.get("last_error") or "", None))
            return None
        deadlines = {str(e["id"]): e["deadline_time"] for e in events
                     if int(e["id"]) in have and int(e["id"]) not in gave_up}
        title = "SQUAD SCORES (hypothetical squad; operational evidence only -- rule 1)"
        if not deadlines:
            self.section(title, "nothing to request (no ingested gameweek eligible)")
            return 0
        req = self.live / "_scoring_request.json"
        _atomic_write_text(req, json.dumps(dict(season=self.season, deadlines=deadlines)))
        args = ["eval/score_squads.py", "--season", self.season, "--request", str(req)]
        self.log(f"\n===== score_squads @ {stamp()} =====\n$ python {' '.join(args)}")
        try:
            code, out = self.run_cmd(args, 600)
        except Exception as e:                       # timeout / spawn failure
            code, out = 1, f"score_squads could not run: {e!r}"
        self.log(out)
        self.log(f"===== score_squads exit code {code} =====")
        text = (out or "").strip()
        failed_gws = {}
        ok_gws = set()
        for line in text.splitlines():
            m = re.match(r"^GW(\d+): (scored|DRY RUN would write|already scored|no squad|FAILED)", line)
            if not m:
                continue
            if m.group(2) == "FAILED":
                failed_gws[m.group(1)] = line
            else:
                ok_gws.add(m.group(1))
        for g in ok_gws:
            att.pop(g, None)
        for g, line in failed_gws.items():
            prev = att.get(g, {}).get("attempts", 0)
            att[g] = dict(attempts=prev + 1, last_failed=stamp(), last_error=line[:600])
        if code != 0 and not failed_gws:
            prev = att.get("global", {}).get("attempts", 0)
            att["global"] = dict(attempts=prev + 1, last_failed=stamp(), last_error=text[-600:])
        elif code == 0:
            att.pop("global", None)
        self._save_scoring_attempts(att)
        self.section(title, text[-2500:] or "(no output)")
        if code != 0:
            counts = {g: att[g]["attempts"] for g in failed_gws} or {"run": att.get("global", {}).get("attempts")}
            self.action(f"squad scoring FAILED (attempt(s) {counts} of {MAX_SCORING_ATTEMPTS}; retried on the "
                        "next tick; the ingest itself is unaffected)",
                        text[-2500:] or "(no output)")
        return code

    def run_chain(self):
        h = self.data_dir / "history"
        tag = self.tag
        slice_p = h / f"odds_fixtures_{tag}.parquet"
        cw_p = h / f"crosswalk_{tag}.csv"
        skel_prov = h / f"forward_skeleton_{tag}.provenance.json"

        # attempt budget
        for gw in self.todo:
            ap = self._attempts(gw)
            n = json.loads(ap.read_text())["attempts"] if ap.exists() else 0
            if n >= MAX_ATTEMPTS:
                self.failed = (f"GW{gw}: {n} failed attempts -- giving up; fix the cause, then delete "
                               f"{ap.name} (or run by hand with --force-gw {gw}) to re-arm")
                return
        for gw in self.todo:
            _atomic_write_text(self._partial(gw), json.dumps(dict(started_at=stamp())))

        # BEFORE: the state a reproduction claim would have to match
        before = manifest(self.data_dir, self.season)
        priced_before = played_priced(slice_p)
        cw_before = crosswalk_map(cw_p)
        self.log(f"BEFORE: {sum(v is not None for v in before.values())}/{len(before)} live inputs present; "
                 f"played fixtures priced {len(priced_before)}; crosswalk ids {len(cw_before)}")

        # 1. master ingest, one gameweek at a time, then the combined stack
        for gw in self.todo:
            self.run_step(f"fetch_fpl_history gw{gw}",
                          ["eval/fetch_fpl_history.py", "--season", self.season, "--gw", str(gw)])
        self.run_step("fetch_fpl_history --combine",
                      ["eval/fetch_fpl_history.py", "--season", self.season, "--combine"])
        # 2-3. Understat per-match + season aggregates
        us_out = self.run_step("understat_matches", ["eval/understat_matches.py", "--season", self.season])
        self.run_step("build_understat_aggregates",
                      ["eval/build_understat_aggregates.py", "--season", self.season])
        self.run_step("build_understat_aggregates --combine",
                      ["eval/build_understat_aggregates.py", "--season", self.season, "--combine"])
        # 4. the crosswalk (the weekly rebuild)
        cw_out = self.run_step("build_crosswalk", ["eval/build_crosswalk.py", "--season", self.season])
        # 5. fixture universe (results for the DC fit) -- prices carried forward
        self.run_step("fetch_fixtures", ["eval/fetch_fixtures.py", "--season", self.season])
        self.run_step("fetch_fixtures --combine",
                      ["eval/fetch_fixtures.py", "--season", self.season, "--combine"])
        # 6. odds refill (1 credit) -- LAST but one
        odds_out = self.run_step("fetch_live_odds", ["eval/fetch_live_odds.py", "--season", self.season])
        # 7. skeleton -- LAST
        skel_out = self.run_step("build_forward_skeleton",
                                 ["eval/build_forward_skeleton.py", "--season", self.season])

        # ---- strict post-checks: each a stop, never a workaround ----
        priced_after = played_priced(slice_p)
        lost = prices_lost(priced_before, priced_after)
        if lost:
            self.failed = (f"PRICES LOST across the fixture rebuild: {len(lost)} played fixture(s) that "
                           f"carried pre-deadline prices before this run do not now (or changed). "
                           f"e.g. {lost[:3]}. The e3d98af carry-forward in fetch_fixtures.build_slice did "
                           f"not hold; the played gameweek(s) can no longer be reproduced. STOP.")
            return
        prov = {}
        pp = slice_p.with_suffix(".provenance.json")
        if pp.exists():
            prov = json.loads(pp.read_text(encoding="utf-8"))
        n_played_priced = len(priced_after)
        upcoming_priced = int(pd.read_parquet(slice_p, columns=["FTHG", "B365H"])
                              .pipe(lambda d: (d["FTHG"].isna() & d["B365H"].notna()).sum()))
        import re
        m = re.search(r"(\d+)/(\d+) events priced.*credits remaining (\d+)", odds_out, re.S)
        self.section("PRICES (preserved across the rebuild)",
                     f"played fixtures priced before {len(priced_before)} / after {n_played_priced}, "
                     f"all {len(priced_before)} identical\n"
                     f"fetch_fixtures provenance: prices_preserved_from_previous_slice="
                     f"{prov.get('prices_preserved_from_previous_slice')}, finished={prov.get('finished')}\n"
                     + (f"fetch_live_odds: {m.group(1)}/{m.group(2)} upcoming events priced, credits "
                        f"remaining {m.group(3)}" if m else "fetch_live_odds: could not parse -- see log")
                     + f"\nupcoming fixtures priced in the slice: {upcoming_priced}")

        dup = stack_collision(self.data_dir, self.season)
        if dup:
            self.failed = (f"SKELETON STALE after rebuild: {len(dup)} fixture(s) in both the master and the "
                           f"forward skeleton {dup[:5]} -- load_stack's collision assert would fire at the "
                           f"deadline build. STOP.")
            return
        sk = json.loads(skel_prov.read_text(encoding="utf-8")) if skel_prov.exists() else {}
        gws = sk.get("gws_covered") or []
        self.section("FORWARD SKELETON",
                     f"{sk.get('rows')} rows, {sk.get('fixtures_forward')} fixtures, "
                     f"gws {gws[0] if gws else '?'}..{gws[-1] if gws else '?'}; "
                     f"postponed excluded: {sk.get('postponed_excluded') or 'none'}; "
                     f"collision check vs master: OK (0 shared fixtures)")

        # ---- reports ----
        api_p = h / f"fpl_api_{tag}.parquet"
        api = pd.read_parquet(api_p, columns=["GW", "element", "fixture", "minutes"])
        fx_prov = json.loads((h / f"fpl_api_{tag}.provenance.json").read_text(encoding="utf-8")) \
            if (h / f"fpl_api_{tag}.provenance.json").exists() else {}
        lines = []
        for gw in self.todo:
            p = fx_prov.get(str(gw), {})
            sub = api[api["GW"] == gw]
            lines.append(f"GW{gw}: {len(sub)} player-fixture rows, {sub['fixture'].nunique()} fixtures, "
                         f"cross-check vs event/live mismatches {p.get('live_crosscheck_mismatches', '?')}, "
                         f"data_checked={p.get('data_checked')}")
        lines.append(f"season file gws: {sorted(int(g) for g in api['GW'].unique())}, {len(api)} rows")
        self.section("MASTER INGEST (fetch_fpl_history)", "\n".join(lines))

        us_p = h / f"understat_matches_{tag}.parquet"
        us = pd.read_parquet(us_p, columns=["gw", "match_id"]) if us_p.exists() else pd.DataFrame(columns=["gw", "match_id"])
        us_prov_p = h / f"understat_matches_{tag}.provenance.json"
        us_prov = json.loads(us_prov_p.read_text(encoding="utf-8")) if us_prov_p.exists() else {}
        per_gw = us.groupby("gw")["match_id"].nunique().to_dict() if len(us) else {}
        fx_per_gw = api.groupby("GW")["fixture"].nunique().to_dict()
        lag = [f"GW{g}: {per_gw.get(g, 0)}/{n} matches" for g, n in fx_per_gw.items()
               if per_gw.get(g, 0) < n]
        deferred = us_prov.get("deferred_matches") or []
        self.section("UNDERSTAT",
                     f"{us['match_id'].nunique()} matches on file; per gw {per_gw}\n"
                     f"deferred (not yet final / incomplete on Understat): {len(deferred)}"
                     + (f" -- {deferred[:5]}" if deferred else "")
                     + (f"\nWARNING lagging gameweek(s) (rates blend on fewer matches until they land): "
                        f"{lag}" if lag else "\nevery ingested gameweek fully covered")
                     + ("\nFAILED match(es) reported by the fetcher -- see log"
                        if "FAILED match" in us_out else ""))

        cw_after = crosswalk_map(cw_p)
        gained = sorted(set(cw_after) - set(cw_before))
        lost_ids = sorted(set(cw_before) - set(cw_after))
        changed = sorted(e for e in set(cw_before) & set(cw_after) if cw_before[e] != cw_after[e])
        played_min = api.groupby("element")["minutes"].sum()
        lost_playing = [e for e in lost_ids if played_min.get(e, 0) > 0]
        stats = "\n".join("  " + ln.strip() for ln in cw_out.splitlines()
                          if any(k in ln for k in ("matched", "pct_", "audit_", "unmatched_with")))
        self.section("CROSSWALK (weekly rebuild)",
                     f"ids: {len(cw_before)} -> {len(cw_after)}; gained {len(gained)} {gained[:12]}"
                     f"{' (+more)' if len(gained) > 12 else ''}; lost {len(lost_ids)}; CHANGED {len(changed)}\n"
                     + stats)
        if changed or lost_playing:
            self.action("crosswalk -- id CHANGED or LOST for a playing element (the alarm condition)",
                        "\n".join([f"  CHANGED element {e}: {cw_before[e]} -> {cw_after[e]}" for e in changed]
                                  + [f"  LOST element {e} (had {cw_before[e]}, {int(played_min.get(e, 0))} min)"
                                     for e in lost_playing])
                        + "\n  A changed id imports another player's scoring rate. Diagnose against "
                          "Logs/crosswalk_2026_27_log.md before the next deadline; pin by MANUAL if wrong.")
        self.outstanding_actions()

        # AFTER: the hashes a reproduction on another machine must match
        after = manifest(self.data_dir, self.season)
        changed_files = [k for k, _ in compare_manifests(before, after)]
        man = dict(season=self.season, gws_ingested=self.todo, written=stamp(), git=git_sha(),
                   host=self._host(), before=before, after=after, changed=changed_files)
        for gw in self.todo:
            _atomic_write_text(self.live / f"ingest_manifest_gw{gw}.json", json.dumps(man, indent=1))
        _atomic_write_text(self.live / "ingest_manifest_latest.json", json.dumps(man, indent=1))
        present = [k for k, v in after.items() if v is not None]
        self.section("INPUT HASHES (verify before any reproduction claim)",
                     f"{len(present)}/{len(after)} live-path inputs hashed (sha256 + order-independent "
                     f"content digest + rows) -> ingest_manifest_latest.json"
                     + (f" (copy: ingest_manifest_gw{self.todo[-1]}.json)" if self.todo else "") + "\n"
                     f"changed by this run: {len(changed_files)} -- {changed_files}\n"
                     "Another machine claims to reproduce this state only if `run_weekly_ingest.py "
                     "--hash-only` there matches every content digest here; bytes may differ across "
                     "pyarrow builds, content may not.")

        # success: clear the markers
        for gw in self.todo:
            for p in (self._partial(gw), self._attempts(gw)):
                if p.exists():
                    p.unlink()

        # then score what is now scoreable (never fails the chain)
        self.score_outstanding()

    def _host(self):
        import socket
        try:
            return socket.gethostname()
        except OSError:
            return None

    def finish(self):
        """FAILED bookkeeping: count the attempt, keep the partial marker."""
        if self.failed:
            for gw in self.todo:
                ap = self._attempts(gw)
                n = json.loads(ap.read_text())["attempts"] if ap.exists() else 0
                _atomic_write_text(ap, json.dumps(dict(attempts=n + 1, last_failed=stamp(),
                                                       last_error=self.failed[-500:])))

    def execute(self):
        """run_chain under the failure contract: ANY exception becomes a FAILED
        status with the traceback; the status file is always written; returns the
        status file's first line."""
        try:
            self.run_chain()
        except Exception:
            if self.failed is None:
                self.failed = traceback.format_exc()[-3000:]
        finally:
            self.finish()
            first = self.write_status()
        return first


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", required=True)
    ap.add_argument("--force-gw", type=int, default=None,
                    help="re-ingest this gameweek even if it is already in the season file")
    ap.add_argument("--hash-only", action="store_true",
                    help="print the live-input manifest (for cross-machine comparison) and exit")
    ap.add_argument("--data-dir", default=None, help="(tests) data directory override")
    a = ap.parse_args(argv)
    R = Runner(a.season, data_dir=a.data_dir)
    if a.hash_only:
        print(json.dumps(dict(season=a.season, host=R._host(), git=git_sha(), written=stamp(),
                              manifest=manifest(R.data_dir, a.season)), indent=1))
        return 0
    try:
        decision = R.decide(force_gw=a.force_gw)
    except Exception:
        R.write_tick("FAILED -- could not decide (API unreachable?)", traceback.format_exc()[-2000:])
        return 1
    d = R.detail
    body = (f"final gameweeks (finished+data_checked): {d['final_gws']}\n"
            f"ingested (season file): {d['have_gws']}; partial (chain broke mid-way): {d['partial_gws']}\n"
            f"next un-final: {d['next_unfinal']}\nnext deadline: {d['next_deadline']}\n")
    if decision != "RUN":
        scores = ""
        if decision == "NOTHING-NEW":                # not DEFERRED: the deadline window stays quiet
            R.score_outstanding()
            scores = "".join(f"\n== {t} ==\n{x}\n" for t, x in R.sections if t.startswith("SQUAD SCORES"))
        items = R.outstanding_actions()
        first = decision + (f" -- ACTION REQUIRED ({len(R.actions)} item(s), see below)" if R.actions else "")
        extra = (f"\nDEFERRED: {d.get('reason')}\npending gameweek(s): {R.todo}\n" if decision == "DEFERRED" else "")
        act = "".join(f"\n== ACTION REQUIRED: {t} ==\n{x}\n" for t, x in R.actions)
        R.write_tick(first, body + extra + act + scores)
        return 0
    R.write_tick(f"RUNNING gameweek(s) {R.todo} -- see {R.status_path.name}", body)
    first = R.execute()
    R.write_tick(f"RAN gameweek(s) {R.todo} -> {first}", body)
    return 1 if R.failed else 0


if __name__ == "__main__":
    sys.exit(main())
