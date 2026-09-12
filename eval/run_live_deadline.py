# run_live_deadline.py -- the unattended per-deadline runner (first used GW3,
# 2026-09-04). Runs the runbook's deadline-day refreshes IN ORDER, then the
# strict build for every config in config_roles.CONFIGS (production = baseline
# since 2026-09-11, no shadow; the props and hmin refresh steps run only when a
# props config is listed), then the free-pick solve, and writes ONE status
# file a human can read from a phone:
#
#     data/live/GW{gw}_BUILD_STATUS.txt   (first line: SUCCESS or FAILED)
#     data/live/GW{gw}_BUILD_RUN.log      (full step output, nothing swallowed)
#
# FAILURE CONTRACT (the reason this file exists):
#   * every subprocess exit code is checked -- a non-zero code FAILS the run
#     and stops it (the `| grep -v` exit-code swallow of 2026-08-31 is the
#     recorded failure this guards against; no pipes are used at all);
#   * a strict preflight raise (LiveStrictError) STOPS the run -- no build,
#     no workaround; the finding text goes in the status file;
#   * ANY exception still writes a FAILED status file with the traceback.
#
# No fetch_fpl_history and no skeleton rebuild here: the deadline gameweek has
# not been played, so there is no ingest -- and the skeleton collision assert
# only concerns a skeleton left stale AFTER an ingest. The skeleton is
# untouched on deadline day by design.
#
# The solve is the production opening convention: a FREE-PICK fifteen via the
# single-gameweek MIP (OPENING_HORIZON gates are off / not adopted). There is
# no tracked live squad state yet, so there are no transfers to price; the
# status file says so explicitly rather than inventing a state.
#
# Usage:  python eval/run_live_deadline.py --season 2026-27 --gw 3
# (any interpreter: subprocess steps reuse sys.executable, so the same file
#  runs under the Windows venv and inside the Linux container unchanged)

import argparse
import io
import json
import re
import subprocess
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PY = sys.executable
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "squad"))
# Which configs build, solve and land in Postgres, and whether the lever inputs
# (props pull + crosswalk + consensus, hmin refit) run at all. ONE source:
# config_roles.py (production = baseline since 2026-09-11; no shadow).
import config_roles as cr  # noqa: E402


def utc_now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")


class Runner:
    def __init__(self, season, gw):
        self.season, self.gw = season, gw
        live = REPO / "data" / "live"
        live.mkdir(parents=True, exist_ok=True)
        self.status_path = live / f"GW{gw}_BUILD_STATUS.txt"
        self.log_path = live / f"GW{gw}_BUILD_RUN.log"
        self.log_f = self.log_path.open("w", encoding="utf-8", errors="replace")
        self.sections = []          # (title, text) blocks for the status file
        self.step_outputs = {}      # step name -> captured output
        self.failed = None          # first failure line, if any

    def log(self, text):
        self.log_f.write(text + "\n")
        self.log_f.flush()

    def section(self, title, text):
        self.sections.append((title, text))

    def run_step(self, name, args):
        """One CLI step. Output captured to the run log; exit code is law."""
        self.log(f"\n===== {name} @ {utc_now()} =====")
        r = subprocess.run([PY] + args, cwd=str(REPO),
                           stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                           text=True, encoding="utf-8", errors="replace",
                           timeout=1200)
        out = r.stdout or ""
        self.log(out)
        self.log(f"===== {name} exit code {r.returncode} =====")
        self.step_outputs[name] = out
        if r.returncode != 0:
            raise RuntimeError(
                f"step '{name}' exited {r.returncode}. Last output:\n{out[-1500:]}")
        return out

    def write_status(self):
        first = "FAILED" if self.failed else "SUCCESS"
        buf = io.StringIO()
        buf.write(f"{first}\n")
        buf.write(f"GW{self.gw} {self.season} deadline build -- written {utc_now()}\n")
        if self.failed:
            buf.write(f"\nFAILURE:\n{self.failed}\n")
        for title, text in self.sections:
            buf.write(f"\n== {title} ==\n{text}\n")
        buf.write(f"\nFull step output: {self.log_path.name}\n")
        self.status_path.write_text(buf.getvalue(), encoding="utf-8")
        print(f"status -> {self.status_path}")


def team_block(team, availability):
    """Format a solved fifteen for the status file, with sanity flags."""
    av = availability  # element -> (status, chance, news)
    lines = []
    starters = team[team["role"] != "bench"]
    bench = team[team["role"] == "bench"]
    order = {"GKP": 0, "DEF": 1, "MID": 2, "FWD": 3}
    for label, part in (("XI", starters), ("BENCH (in order)", bench)):
        lines.append(f"{label}:")
        rows = part if label == "XI" else part  # bench already ordered by assign_bench_order
        for _, r in rows.iterrows():
            tag = {"CAPTAIN": " (C)", "VICE": " (V)"}.get(r["role"], "")
            st, ch, news = av.get(int(r["element"]), ("?", None, ""))
            flag = ""
            if st not in ("a", "?"):
                flag = f"  [FLAG status={st}" + (f" chance={ch}" if ch is not None else "") + \
                       (f" news={news[:60]}" if news else "") + "]"
            lines.append(f"  {r['name']:24s} {r['position']:3s} {r['team']:14.14s} "
                         f"{r['value']/10:5.1f}  e_pts {r['e_points']:.2f}{tag}{flag}")
    cost = team["value"].sum() / 10
    lines.append(f"squad cost {cost:.1f} / 100.0 | predicted XI+C points "
                 f"{starters['e_points'].sum() + team.loc[team['role'] == 'CAPTAIN', 'e_points'].iloc[0]:.2f}")
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", required=True)
    ap.add_argument("--gw", type=int, required=True)
    # multi-run schedule (2026-09-12): which slot this build serves. The
    # dispatcher passes them; a hand run defaults to a plain 'deadline' build.
    ap.add_argument("--kind", default="deadline",
                    choices=["deadline", "t90", "t30", "t10", "nightly", "post_ingest"])
    ap.add_argument("--slot", default=None)
    ap.add_argument("--attempt", type=int, default=1)
    a = ap.parse_args()
    started_at = datetime.now(timezone.utc)      # recorded on the run row (was None until 2026-09-12)
    slot = a.slot or f"{a.kind}:GW{a.gw}"
    R = Runner(a.season, a.gw)
    R.kind, R.slot, R.attempt = a.kind, slot, a.attempt
    try:
        run(R, a.season, a.gw, started_at=started_at)
    except Exception:
        if R.failed is None:
            R.failed = traceback.format_exc()[-3000:]
    finally:
        R.write_status()
        archive_status(R, a.kind, started_at)
        if R.failed:
            # best-effort FAILED row so /health surfaces the failure even if
            # nobody reads the status file; never masks the original error
            try:
                import db_write
                db_write.write_failed_run(a.season, a.gw, R.failed, kind=a.kind, slot=slot,
                                          attempt=a.attempt)
            except Exception:
                pass
    sys.exit(1 if R.failed else 0)


def archive_status(R, kind, started_at):
    """Keep every run's status file (the named one stays 'the latest')."""
    try:
        d = REPO / "data" / "live" / "runs"
        d.mkdir(parents=True, exist_ok=True)
        (d / f"GW{R.gw}_{kind}_{started_at:%Y%m%dT%H%MZ}.txt").write_text(
            R.status_path.read_text(encoding="utf-8"), encoding="utf-8")
    except OSError:
        pass


def _read_json(p):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def knowledge_block(season, gw, frames, started_at, finished_at, kind, slot, attempt, credits):
    """WHAT THIS RUN KNEW, from artefacts the steps already write (design
    section 5): the season file's max gameweek + when the ingest wrote it, the
    availability merge's time (the poller's snapshot is <= 10 min older), the
    odds pull time, the frame's cutoff and gameweeks."""
    import pandas as pd
    tag = season.replace("-", "_")
    short = season[2:4] + season[5:7]
    live = REPO / "data" / "live"
    try:
        hist_gw = int(pd.read_parquet(REPO / "data" / "history" / f"fpl_api_{tag}.parquet",
                                      columns=["GW"])["GW"].max())
    except Exception:
        hist_gw = None
    man = _read_json(live / "ingest_manifest_latest.json")
    avp = _read_json(REPO / "data" / f"availability_{short}.provenance.json")
    odp = _read_json(REPO / "data" / "history" / f"odds_live_pull_{tag}.provenance.json")
    f = next(iter(frames.values())) if frames else None
    import config_roles as cr
    dl_at = None
    try:
        import requests
        ev = requests.get("https://fantasy.premierleague.com/api/bootstrap-static/", timeout=10).json()["events"]
        dl_at = next((e["deadline_time"] for e in ev if int(e["id"]) == gw), None)
    except Exception:
        pass
    return {
        "kind": kind, "slot": slot, "attempt": attempt,
        "started_at": started_at.isoformat(), "finished_at": finished_at.isoformat(),
        "duration_s": round((finished_at - started_at).total_seconds(), 1),
        "history_through_gw": hist_gw, "history_ingested_at": man.get("written"),
        "availability_asof": avp.get("built_at"),
        "odds_pulled_at": odp.get("pulled_at"), "credits_remaining": credits,
        "calendar_snapshot_at": started_at.isoformat(),      # the strict re-pull is in-build
        "frame_cutoff_gw": (int(f["cutoff"].min()) if f is not None and "cutoff" in f.columns else gw),
        "frame_gws": (sorted(int(g) for g in f["gw"].unique()) if f is not None else None),
        "deadline_at": dl_at, "config": cr.PRODUCTION_CONFIG,
    }


def run(R, season, gw, started_at=None):
    import pandas as pd

    # ---- 1. deadline-day refreshes, runbook order (no ingest, no skeleton) ----
    try:
        R.run_step("merge_live_availability",
                   ["eval/merge_live_availability.py", "--season", season])
        odds_out = R.run_step("fetch_live_odds",
                              ["eval/fetch_live_odds.py", "--season", season])
        if cr.LEVER_INPUTS_ACTIVE:
            # The combined config's inputs only. OFF since 2026-09-11 (production =
            # baseline, no shadow): the paid props tier, the per-gameweek name
            # crosswalk and consensus, and the hmin delete-and-refit are not run.
            # Kept, not deleted -- config_roles.SHADOW_CONFIG = "combined" re-enables them.
            R.run_step("pull_live_props",
                       ["eval/pull_live_props.py", "--season", season, "--gw", str(gw)])
            R.run_step("build_props_crosswalk", ["eval/build_props_crosswalk.py"])
            R.run_step("build_props_consensus",
                       ["eval/build_props_consensus.py", "--seasons", season])
            R.run_step("run_horizon_minutes (skip-if-exists)",
                       ["eval/run_horizon_minutes.py", "--season", season,
                        "--levers", "refit", "--cutoffs", str(gw)])
        else:
            R.log("\n===== lever inputs OFF (config_roles: production = "
                  f"{cr.PRODUCTION_CONFIG}, shadow = {cr.SHADOW_CONFIG}): pull_live_props, "
                  "build_props_crosswalk, build_props_consensus and run_horizon_minutes "
                  "skipped =====")
    except RuntimeError as e:
        R.failed = str(e)
        return

    # ---- 2. the named check: Jackson's props mapping (props configs only) ----
    if cr.LEVER_INPUTS_ACTIVE:
        tagged = season  # csv naming uses the dashed season
        cw = pd.read_csv(REPO / "data" / "odds_props" / f"props_crosswalk_{tagged}.csv")
        jk = cw[(cw["gw"] == gw) & cw["key"].str.contains("jackson", na=False)]
        if len(jk) == 0:
            jackson = ("NOT ON THE BOARD: no 'jackson' key on any GW%d board -- his props "
                       "cannot reach the model this gameweek (positional/model paths only). "
                       "NOT a build blocker, but the Cherki-class risk stands." % gw)
        else:
            r0 = jk.iloc[0]
            ok = pd.notna(r0["element"]) and r0["match_type"] == "exact"
            jackson = (f"key='{r0['book_name']}' fixture='{r0['fixture']}' -> element "
                       f"{r0['element']} match_type={r0['match_type']} score={r0['score']:.0f}"
                       + ("  [OK]" if ok else "  [** FAILED TO EXACT-MATCH -- Cherki class, "
                                              "investigate before trusting his rows **]"))
        R.section("JACKSON PROPS MAPPING", jackson)
    else:
        R.section("JACKSON PROPS MAPPING", "not applicable -- props are not an input of the "
                                           f"production config ({cr.PRODUCTION_CONFIG}); no shadow")

    # ---- 3. strict builds, production first; a raise STOPS the run ----
    import live_deadline as ld
    frames = {}
    findings_by = {}
    for config in cr.CONFIGS:
        try:
            frame, findings = ld.build_deadline_frame(
                season, gw, strict=True, config=config, horizon=6)
            frames[config] = frame
            findings_by[config] = list(findings)
            note = "\n".join(f"  - {f}" for f in findings) if findings else "  (no findings)"
            R.section(f"STRICT BUILD {config.upper()}",
                      f"PASSED, {len(frame)} rows. Findings (notes):\n{note}")
        except ld.LiveStrictError as e:
            R.failed = (f"STRICT PREFLIGHT RAISED for config={config} -- stopping, "
                        f"not building, per the failure contract:\n{e}")
            R.section(f"STRICT BUILD {config.upper()}", f"RAISED:\n{e}")
            return
    R.log(f"strict builds passed for {list(cr.CONFIGS)}")

    # ---- 4. coverage + credits (parsed from this run's own step output) ----
    m = re.search(r"(\d+)/(\d+) events priced.*credits remaining (\d+)", odds_out, re.S)
    odds_line = (f"h2h events priced {m.group(1)}/{m.group(2)}, credits remaining {m.group(3)}"
                 if m else "could not parse fetch_live_odds output -- see run log")
    if cr.LEVER_INPUTS_ACTIVE:
        priced, total = ld.props_fixture_coverage(season, gw)
        props_out = R.step_outputs.get("pull_live_props", "")
        props_line = (f"props: {priced}/{total} GW{gw} fixtures have a consensus board\n"
                      f"props pull output tail: {props_out.strip()[-400:] if props_out else 'n/a'}")
    else:
        props_line = "props: not pulled (lever inputs OFF; production = baseline)"
    R.section("COVERAGE & CREDITS", f"{props_line}\nodds:  {odds_line}")

    # ---- 5. solve both configs (free pick -- no tracked squad state) ----
    import simulator as sim
    from optimize import optimize_squad
    import pulp
    hist = pd.read_parquet(REPO / "data" / "history" /
                           f"fpl_api_{season.replace('-', '_')}.parquet",
                           columns=["season", "element", "round", "value"])
    skel = pd.read_parquet(REPO / "data" / "history" /
                           f"forward_skeleton_{season.replace('-', '_')}.parquet",
                           columns=["season", "element", "round", "value"])
    tmp_dir = REPO / "data" / "live"
    tmp_hist = tmp_dir / f"_tmp_prices_{season.replace('-', '_')}.parquet"
    pd.concat([hist, skel], ignore_index=True).to_parquet(tmp_hist, index=False)

    # availability lookup for sanity flags (the deadline gameweek's as-of view)
    av = pd.read_parquet(REPO / "data" / f"availability_{season[2:4]}{season[5:7]}.parquet")
    av = av[av["gw"] == gw]
    avmap = {int(r["element"]): (r.get("asof_status"), r.get("asof_chance_of_playing_this_round"),
                                 str(r.get("asof_news") or ""))
             for _, r in av.iterrows()}

    teams = {}
    for config, frame in frames.items():
        fp = tmp_dir / f"_tmp_frame_{config}.parquet"
        f2 = frame.copy()
        for c in ("actual_points", "minutes"):
            if c not in f2.columns:
                f2[c] = float("nan")
        f2.to_parquet(fp, index=False)
        df = sim.load_season(walkforward_path=str(fp), history_path=str(tmp_hist),
                             horizon_aware=True, season=season)
        pool = sim.gw_slice(df, gw, cutoff=gw)
        prob, sol = optimize_squad(pool)
        if pulp.LpStatus[prob.status] != "Optimal":
            raise RuntimeError(f"{config} solve status {pulp.LpStatus[prob.status]}")
        team = sim.solution_to_squad(pool, sol)
        teams[config] = team
        R.section(f"SQUAD -- {config.upper()}"
                  + (" (production)" if config == cr.PRODUCTION_CONFIG else " (shadow)"),
                  team_block(team, avmap)
                  + "\nTransfers: none possible -- no tracked live squad state; this is "
                    "the free-pick fifteen (opening convention, single-gw objective).")

    # ---- 6. where the configs disagree (only when a shadow is run) ----
    tc = teams[cr.PRODUCTION_CONFIG]
    if cr.SHADOW_CONFIG in teams:
        tb = teams[cr.SHADOW_CONFIG]
        pn, sn = cr.PRODUCTION_CONFIG, cr.SHADOW_CONFIG
        s_c, s_b = set(tc["element"]), set(tb["element"])
        xi_c = set(tc.loc[tc["role"] != "bench", "element"])
        xi_b = set(tb.loc[tb["role"] != "bench", "element"])
        cap = {k: t.loc[t["role"] == "CAPTAIN", "name"].iloc[0] for k, t in teams.items()}
        vice = {k: t.loc[t["role"] == "VICE", "name"].iloc[0] for k, t in teams.items()}
        name_of = dict(zip(pd.concat([tc, tb])["element"], pd.concat([tc, tb])["name"]))
        only_c = sorted(name_of[e] for e in s_c - s_b)
        only_b = sorted(name_of[e] for e in s_b - s_c)
        xi_only_c = sorted(name_of[e] for e in xi_c - xi_b)
        xi_only_b = sorted(name_of[e] for e in xi_b - xi_c)
        R.section(f"CONFIG DISAGREEMENT ({pn} vs {sn})",
                  f"fifteen: {len(s_c & s_b)}/15 shared\n"
                  f"  only {pn}: {only_c or 'none'}\n"
                  f"  only {sn}: {only_b or 'none'}\n"
                  f"XI: {len(xi_c & xi_b)}/11 shared\n"
                  f"  XI only {pn}: {xi_only_c or 'none'}\n"
                  f"  XI only {sn}: {xi_only_b or 'none'}\n"
                  f"captain: {pn}={cap[pn]} {sn}={cap[sn]}"
                  f"{'  [SAME]' if cap[pn] == cap[sn] else '  [DIFFER]'}\n"
                  f"vice: {pn}={vice[pn]} {sn}={vice[sn]}")
    else:
        R.section("CONFIG DISAGREEMENT", f"no shadow configuration is run (production = "
                                         f"{cr.PRODUCTION_CONFIG}; config_roles.py, 2026-09-11)")

    # ---- 7. plain-terms sanity flags on the production squad ----
    flags = []
    for _, r in tc.iterrows():
        st, ch, news = avmap.get(int(r["element"]), ("?", None, ""))
        if st not in ("a", "?") and r["role"] != "bench":
            flags.append(f"starter {r['name']} has status '{st}'"
                         + (f" chance {ch}" if ch is not None else "")
                         + (f" -- {news[:80]}" if news else ""))
    gk_cap = tc.loc[tc["role"] == "CAPTAIN", "position"].iloc[0] == "GKP"
    if gk_cap:
        flags.append("CAPTAIN IS A GOALKEEPER -- almost certainly wrong")
    R.section("SANITY FLAGS (production squad)",
              "\n".join(f"  - {f}" for f in flags) if flags else "  none raised")

    # ---- 8. write the run to Postgres (serving reads it; /health watches it) ----
    # A failure here after a successful build is NOT silent: it goes in the
    # status file as its own section, the runner exits non-zero (the
    # dispatcher counts it as a failed attempt), and /health reports the
    # missing run because no model_runs row landed for this gameweek.
    try:
        import db_write
        price_df = pd.read_parquet(tmp_hist)
        price_map = dict(zip(price_df[price_df["round"] == gw]["element"].astype(int),
                             price_df[price_df["round"] == gw]["value"].astype(int)))
        kind = getattr(R, "kind", "deadline")
        slot = getattr(R, "slot", f"deadline:GW{gw}")
        attempt = getattr(R, "attempt", 1)
        finished_at = datetime.now(timezone.utc)
        credits = int(m.group(3)) if m else None
        knowledge = knowledge_block(season, gw, frames, started_at or finished_at, finished_at,
                                    kind, slot, attempt, credits)
        run_id = db_write.write_run(
            season, gw, frames, teams, findings_by,
            started_at=started_at, recovered=False,
            credits_remaining=credits,
            note=f"unattended {kind} build ({slot}, attempt {attempt})",
            availability=avmap, prices=price_map,
            kind=kind, slot=slot, attempt=attempt, knowledge=knowledge)
        # the frame sidecar: which run the file on the volume belongs to, and
        # what it knew -- the file-based tools quote it and check it against
        # the database's latest run
        for config in frames:
            (tmp_dir / f"_tmp_frame_{config}.provenance.json").write_text(
                json.dumps(dict(run_id=run_id, config=config, gw=gw, kind=kind, slot=slot,
                                built_at=finished_at.isoformat(), knowledge=knowledge), indent=1),
                encoding="utf-8")
        R.section("POSTGRES", f"run_id {run_id} written (predictions x{sum(len(f) for f in frames.values())}, "
                              f"picks x{sum(len(t) for t in teams.values())}, players_live refreshed); "
                              f"kind {kind}, slot {slot}, attempt {attempt}, duration {knowledge['duration_s']} s")
        R.section("KNOWLEDGE (what this run knew)",
                  "\n".join(f"  {k}: {v}" for k, v in knowledge.items()))
    except Exception as e:
        R.failed = (f"DB WRITE FAILED after a successful build -- the frame exists on "
                    f"the volume but Postgres is STALE for GW{gw}. /health will show "
                    f"the missing run. Error: {type(e).__name__}: {e}")
        R.section("POSTGRES", f"WRITE FAILED: {type(e).__name__}: {e}")
        return


if __name__ == "__main__":
    main()
