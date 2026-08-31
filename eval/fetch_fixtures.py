"""2026-27 FIXTURE UNIVERSE from the FPL API -- fixtures only, NO odds pulling (the odds
provider question is a separate job). The model's fixture universe IS the odds archive
(data/history/odds_all_seasons.parquet, football-data E0): dixon_coles._load_matches
consumes exactly Date, HomeTeam, AwayTeam, FTHG, FTAG, season (the FIXTURE columns) and
B365H/B365D/B365A (the PRICE columns). This writer supplies the fixture columns for
2026-27 from the authoritative fixtures/ endpoint and leaves every price column null:
an unpriced fixture takes the designed fallback (lam_w = 1.0, pure Dixon-Coles,
lambda_source="dc", counted per fixture -- dixon_coles.py:302/320-322).

TEAM NAMES -- the #14 (Sheffield) class of risk, handled explicitly. The archive uses
football-data spellings, the 2026-27 vaastav-shaped stack uses FPL spellings, and
assembly.TEAM_MAP bridges the two. Policy, per club, loud on failure:
  * use the HISTORICAL E0 spelling when it round-trips to the club's FPL name through
    assembly.TEAM_MAP (identity included) -- so Man United / Tottenham keep their years
    of Dixon-Coles strength under the name the fit knows;
  * otherwise use the FPL name verbatim (TEAM_MAP passes unknown names through, and the
    2026-27 stack rows carry FPL names, so the (team, match_date) join is exact).
    Documented consequence: E0 "Ipswich" (2024-25 rows) cannot be mapped to FPL's
    "Ipswich Town" without breaking the 2024-25 join, so Ipswich's old E0 strength is
    knowingly stranded; Coventry City and Hull City have no E0 rows in this archive at
    all. All three promoted clubs start the DC fit from zero-information priors.
  * a club that resolves to nothing, or to two candidate spellings, RAISES.

SCORES AND THE NaN TRAP. dixon_coles._fit_dc_decay feeds scores straight into
poisson.logpmf: one played-but-unscored row inside a training slice poisons the whole
likelihood. So: finished fixtures get team_h_score/team_a_score from the API; future
fixtures carry nulls (they can never enter a training slice -- training filters
date_parsed < cutoff and their kickoff is after any cutoff that predicts them); and a
PAST-kickoff fixture without scores (in play, abandoned, or a stale pull) REFUSES the
write. Refresh as part of every deadline run; the pull is one API call.

APPEND, DO NOT REBUILD: the archive parquet is untouched. This writes
data/history/odds_fixtures_2026_27.parquet (the season slice, fully regenerated each
run -- fixtures get rescheduled, so the slice is derived state) and --combine produces
data/history/odds_all_seasons_with_2026_27.parquet = archive + slice. One documented
dtype change: FTHG/FTAG/HTHG/HTAG int64 -> float64 in the combined file (future
fixtures are null; values cast losslessly; the DC fit is numerically indifferent).
Provenance sidecar; atomic writes.

Usage:
  uv run python eval/fetch_fixtures.py --season 2026-27
  uv run python eval/fetch_fixtures.py --season 2026-27 --combine
"""
import argparse
import json
import os
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parent.parent
HIST = REPO / "data" / "history"
ODDS = HIST / "odds_all_seasons.parquet"
API = "https://fantasy.premierleague.com/api"
UA = {"User-Agent": "Mozilla/5.0 (fpl-copilot ingestion; weekly; contact: repo owner)"}

sys.path.insert(0, str(REPO / "squad"))
from assembly import TEAM_MAP  # noqa: E402  (the odds->vaastav name bridge; read-only)

# int64 archive columns that must go nullable-float in the combined file (future
# fixtures have no result yet). Cast is lossless for every archive value.
SCORE_INT_COLS = ["FTHG", "FTAG", "HTHG", "HTAG"]


class ClubNameError(RuntimeError):
    """A club resolves to nothing or to more than one historical spelling."""


def get_json(path):
    req = urllib.request.Request(f"{API}{path}", headers=UA)
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def resolve_club_names(fpl_names, archive_home_names):
    """FPL club name -> the name to write into the fixture rows. E0 spelling when it
    round-trips through assembly.TEAM_MAP to the FPL name; else the FPL name. Raises
    on ambiguity -- a wrong club name silently drops every fixture join for that
    club's squad (the #14 Sheffield class), so nothing is guessed."""
    out = {}
    archive = set(archive_home_names)
    for fpl in sorted(fpl_names):
        candidates = sorted({e0 for e0 in archive if TEAM_MAP.get(e0, e0) == fpl})
        if len(candidates) > 1:
            raise ClubNameError(f"{fpl!r}: multiple archive spellings round-trip to it: {candidates}")
        out[fpl] = candidates[0] if candidates else fpl
    return out


def build_slice(season):
    assert season == "2026-27", "this writer is for the live season; the archive holds the past"
    bs = get_json("/bootstrap-static/")
    teams = {t["id"]: t["name"] for t in bs["teams"]}
    fx = get_json("/fixtures/")
    schema = pd.read_parquet(ODDS).iloc[0:0]
    name_map = resolve_club_names(set(teams.values()), pd.read_parquet(ODDS, columns=["HomeTeam"])["HomeTeam"].unique())
    now = datetime.now(timezone.utc)
    rows, unscored_past = [], []
    n_provisional = 0
    for f in fx:
        ko = datetime.fromisoformat(f["kickoff_time"].replace("Z", "+00:00")) if f["kickoff_time"] else None
        # `finished` lags `finished_provisional` until FPL's post-match processing
        # (bonus/data checks) completes -- the SCORES exist from full time. Accept
        # provisional scores (counted in provenance; final goals rarely move in
        # review) and refuse only a past kickoff with NO score at all.
        finished = bool(f["finished"]) or (bool(f.get("finished_provisional"))
                                           and f["team_h_score"] is not None)
        if bool(f.get("finished_provisional")) and not bool(f["finished"]):
            n_provisional += 1
        if not finished and ko is not None and ko < now:
            unscored_past.append((f["id"], f["kickoff_time"], teams[f["team_h"]], teams[f["team_a"]]))
        rows.append({
            "Div": "E0",
            "Date": ko.strftime("%d/%m/%Y") if ko else None,
            "Time": ko.strftime("%H:%M") if ko else None,
            "HomeTeam": name_map[teams[f["team_h"]]],
            "AwayTeam": name_map[teams[f["team_a"]]],
            "FTHG": float(f["team_h_score"]) if finished and f["team_h_score"] is not None else np.nan,
            "FTAG": float(f["team_a_score"]) if finished and f["team_a_score"] is not None else np.nan,
            "FTR": (("H" if f["team_h_score"] > f["team_a_score"] else
                     "A" if f["team_h_score"] < f["team_a_score"] else "D")
                    if finished and f["team_h_score"] is not None else None),
            "season": season,
        })
    if unscored_past:
        raise RuntimeError(
            f"{len(unscored_past)} fixture(s) have a PAST kickoff but no final score "
            f"(in play / abandoned / stale pull): {unscored_past[:4]}. A played-but-unscored row "
            f"inside a Dixon-Coles training slice poisons the likelihood (NaN logpmf); "
            f"re-run after the matches finish.")
    df = pd.DataFrame(rows)
    for c in schema.columns:                 # every price/stat column: null, correct dtype
        if c not in df.columns:
            df[c] = pd.NA
    df = df[list(schema.columns)]
    for c in schema.columns:
        want = "float64" if c in SCORE_INT_COLS else str(schema[c].dtype)
        try:
            df[c] = df[c].astype(want)
        except (TypeError, ValueError):
            df[c] = pd.to_numeric(df[c], errors="coerce").astype(want)
    assert len(df) == 380 and not df.duplicated(["Date", "HomeTeam", "AwayTeam"]).any()
    prov = dict(season=season, pulled_at=now.isoformat(), fixtures=len(df),
                finished=int(df["FTHG"].notna().sum()),
                provisional_scored=n_provisional,
                club_name_map={k: v for k, v in name_map.items() if k != v} or "all identity",
                e0_spellings_reused=sorted(v for k, v in name_map.items() if k != v),
                promoted_no_archive_strength=["Coventry City", "Hull City", "Ipswich Town"])
    return df, prov


def write_slice(df, prov, season):
    tag = season.replace("-", "_")
    out = HIST / f"odds_fixtures_{tag}.parquet"
    tmp = out.with_suffix(".tmp.parquet")
    df.to_parquet(tmp, index=False)
    os.replace(tmp, out)
    out.with_suffix(".provenance.json").write_text(json.dumps(prov, indent=1), encoding="utf-8")
    print(f"-> {out.name}: {len(df)} fixtures, {prov['finished']} finished with scores; "
          f"E0 spellings reused: {prov['e0_spellings_reused']}")
    return out


def combine(season):
    tag = season.replace("-", "_")
    add = pd.read_parquet(HIST / f"odds_fixtures_{tag}.parquet")
    base = pd.read_parquet(ODDS)
    assert season not in set(base["season"]), "season already in the archive"
    for c in SCORE_INT_COLS:
        base[c] = base[c].astype("float64")      # documented lossless cast (future fixtures are null)
    assert list(base.columns) == list(add.columns)
    out = HIST / f"odds_all_seasons_with_{tag}.parquet"
    combined = pd.concat([base, add], ignore_index=True)
    tmp = out.with_suffix(".tmp.parquet")
    combined.to_parquet(tmp, index=False)
    os.replace(tmp, out)
    print(f"COMBINED -> {out.name}: {len(base)} archive rows (source file untouched) + {len(add)}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", required=True)
    ap.add_argument("--combine", action="store_true")
    a = ap.parse_args()
    if a.combine:
        combine(a.season)
        return
    df, prov = build_slice(a.season)
    write_slice(df, prov, a.season)


if __name__ == "__main__":
    main()
