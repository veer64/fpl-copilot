"""D6 post-window steps, automated (Logs/d6_live_availability_log.md s.8). Runs unattended after the deadline:
  1. verify data/live/bootstrap_raw/<season>/ holds the window's polls (count, cadence, a post-deadline poll);
  2. run `poll_availability.py --build`;
  3. blind-window diff vs fplcache IF the fplcache clone holds a snapshot after the deadline (else 'pending');
  4. write ONE summary file data/live/GW<n>_WINDOW_STATUS.txt whose first line is SUCCESS / PARTIAL / FAIL.
Everything is appended to data/live/poller.log as well.
"""
import gzip, json, subprocess, sys, traceback
from datetime import datetime, timezone, timedelta
from pathlib import Path
REPO = Path(__file__).resolve().parent.parent
LIVE = REPO / "data" / "live"; RAW = LIVE / "bootstrap_raw"; UV = r"C:\Users\veers\.local\bin\uv.exe"
LOG = LIVE / "poller.log"
def log(msg):
    line = f"[{datetime.now():%Y-%m-%d %H:%M:%S}] postwindow: {msg}"
    print(line, flush=True)
    with open(LOG, "a", encoding="utf-8") as f: f.write(line + "\n")

def main():
    lines, verdict = [], "SUCCESS"
    try:
        seasons = sorted(p.name for p in RAW.iterdir() if p.is_dir()) if RAW.exists() else []
        season = seasons[-1] if seasons else None
        if season is None:
            raise RuntimeError("no raw archive directory")
        files = sorted((RAW / season).glob("*.json.gz"))
        if not files:
            raise RuntimeError("no raw polls at all")
        # deadline from the newest raw file's events
        with gzip.open(files[-1], "rt", encoding="utf-8") as f:
            data = json.load(f)
        now = datetime.now(timezone.utc)
        ev = sorted(((datetime.fromisoformat(e["deadline_time"].replace("Z", "+00:00")), e["id"]) for e in data["events"]))
        past = [(d, i) for d, i in ev if d <= now]
        if not past:
            raise RuntimeError("no completed deadline in the newest poll's events")
        deadline, gw = past[-1]
        stamps = [datetime.strptime(p.name[:16], "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc) for p in files]
        in_window = [t for t in stamps if deadline - timedelta(hours=4) <= t < deadline]
        final_hour = [t for t in in_window if t >= deadline - timedelta(hours=1)]
        post = [t for t in stamps if deadline <= t <= deadline + timedelta(hours=3)]
        gaps = [(b - a).total_seconds() / 60 for a, b in zip(in_window, in_window[1:])]
        lines += [f"season {season} GW{gw} deadline {deadline:%Y-%m-%d %H:%M}Z (local {deadline.astimezone():%H:%M})",
                  f"polls in window (deadline-4h .. deadline): {len(in_window)} (expected ~8 at 30 min + ~6 at 10 min); final-hour polls {len(final_hour)}; post-deadline polls {len(post)}",
                  f"max gap between window polls: {max(gaps):.0f} min" if gaps else "max gap: n/a (<2 polls)"]
        if len(in_window) == 0:
            verdict = "FAIL"; lines.append("FAIL: no pre-deadline poll landed -- window missed")
        elif len(in_window) < 8 or not post or (gaps and max(gaps) > 45):
            verdict = "PARTIAL"; lines.append("PARTIAL: window under-sampled, a gap > 45 min, or no post-deadline poll")
        # change rows near the deadline
        try:
            import pandas as pd
            ch = pd.read_parquet(LIVE / f"availability_changes_{season.replace(chr(45), chr(95))}.parquet")
            near = ch[(ch.get("gw", gw) == gw)] if "gw" in ch.columns else ch
            m = near["minutes_to_deadline"] if "minutes_to_deadline" in near.columns else None
            lines.append(f"change rows for GW{gw}: {len(near)}" + (f"; within 4h of deadline: {int((m <= 240).sum())}; within 1h: {int((m <= 60).sum())}" if m is not None else ""))
        except Exception as e:
            lines.append(f"change rows: could not read ({type(e).__name__}: {e})")
        # build
        r = subprocess.run([UV, "run", "python", "eval/poll_availability.py", "--build"], cwd=REPO, capture_output=True, text=True, timeout=600)
        lines.append(f"--build exit {r.returncode}: {(r.stdout or r.stderr).strip().splitlines()[-1] if (r.stdout or r.stderr).strip() else ''}")
        if r.returncode != 0:
            verdict = "PARTIAL" if verdict == "SUCCESS" else verdict
        # blind-window diff vs fplcache (needs a snapshot AFTER the deadline in the clone)
        # repo-local clone (exists, gitignored) first; an out-of-OneDrive clone at C:/Users/veers/fplcache as fallback
        cache = next((c for c in (REPO / "fplcache" / "cache", Path("C:/Users/veers/fplcache/cache")) if c.exists()), REPO / "fplcache" / "cache")
        if not cache.exists():
            lines.append("blind-window diff: PENDING -- fplcache clone not present (git clone https://github.com/Randdalf/fplcache into repo/fplcache, then rerun this script)")
        else:
            subprocess.run(["git", "-C", str(cache.parent), "pull", "--ff-only", "-q"], capture_output=True, text=True, timeout=600)
            snaps = sorted(cache.glob("*/*/*/*.json.xz"))
            def ts(p):
                y, mo, d, hm = p.parts[-4], p.parts[-3], p.parts[-2], p.name.split(".")[0]
                return datetime(int(y), int(mo), int(d), int(hm[:2]), int(hm[2:]), tzinfo=timezone.utc)
            after = [p for p in snaps if ts(p) >= deadline]
            if not after:
                lines.append(f"blind-window diff: PENDING -- fplcache has no snapshot after the deadline yet (newest {ts(snaps[-1]):%Y-%m-%d %H:%M}Z if snaps else 'none'); rerun later")
            else:
                r2 = subprocess.run([UV, "run", "python", "eval/build_availability.py", "--season", season, "--cache", str(cache), "--out", str(LIVE / f"availability_{season}_fplcache.parquet")], cwd=REPO, capture_output=True, text=True, timeout=900)
                lines.append(f"fplcache build exit {r2.returncode}")
                import pandas as pd
                stag = season.replace(chr(45), chr(95)); a = pd.read_parquet(LIVE / f"availability_{stag}_live.parquet"); b = pd.read_parquet(LIVE / f"availability_{season}_fplcache.parquet")
                a, b = a[a.gw == gw], b[b.gw == gw]
                j = a.merge(b, on=["gw", "element"], suffixes=("_live", "_fplcache"))
                diff_status = j[j["asof_status_live"] != j["asof_status_fplcache"]] if "asof_status_live" in j else j.iloc[0:0]
                diff_chance = j[j["asof_chance_of_playing_this_round_live"].fillna(-1) != j["asof_chance_of_playing_this_round_fplcache"].fillna(-1)] if "asof_chance_of_playing_this_round_live" in j else j.iloc[0:0]
                lines.append(f"BLIND-WINDOW DIFF GW{gw}: {len(j)} players compared; asof_status differs on {len(diff_status)}; asof_chance differs on {len(diff_chance)}")
                out = LIVE / f"blind_window_diff_GW{gw}.csv"; pd.concat([diff_status, diff_chance]).drop_duplicates().to_csv(out, index=False); lines.append(f"diff rows written to {out.name}")
    except Exception as e:
        verdict = "FAIL"; lines.append(f"FAIL: {type(e).__name__}: {e}"); lines.append(traceback.format_exc(limit=3))
    gw_txt = next((l for l in lines if l.startswith("season ")), "")
    n = "".join(ch for ch in gw_txt.split("GW")[1].split(" ")[0] if ch.isdigit()) if "GW" in gw_txt else "x"
    summary = LIVE / f"GW{n}_WINDOW_STATUS.txt"
    summary.write_text(f"{verdict}  ({datetime.now():%Y-%m-%d %H:%M} local)\n" + "\n".join(lines) + "\n", encoding="utf-8")
    for l in [f"VERDICT {verdict}"] + lines: log(l)
    print(f"summary -> {summary}")

if __name__ == "__main__":
    main()
