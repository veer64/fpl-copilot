# run_teamnews_knowable.py
# Team-news STEP 5 -- the knowable oracle. Same instrument as step 4
# (squad/oracle_minutes.py, gated, stamped oracle_minutes_active +
# oracle_mode), three restrictions measured separately under the full
# adopted system (base opening, WC1@2, all chips). References and the
# step-4 full-oracle runs are REUSED.
#
# Arm A ("step0"): realized minutes at horizon_step 0 only -- the slice a
#   lineup service sells (perfect next-deadline knowledge, nothing beyond).
# Arm B ("masked_step0", STRUCTURALLY KNOWABLE -- definition of record):
#   step-0 minutes revealed for (gw, element) iff EITHER
#     (1) the player logged >= 60 minutes in a Premier League fixture whose
#         kickoff falls within the 4 days before his gw kickoff (congestion
#         rotation risk -- "played Wednesday, may be rested Saturday"), OR
#     (2) the gw follows an absence of 3+ consecutive gameweeks with zero
#         minutes (long-absence status -- return timing is public knowledge).
#   European/cup midweeks are NOT on disk and are NOT derivable here --
#   stated limitation; criterion (1) sees only PL congestion. This arm
#   measures a FEATURE GAP (buildable from the calendar), not a purchase.
# Arm C ("masked_step0", REPORTED): step-0 minutes revealed only for the 10
#   step-2 verified Guardian pre-deadline-signal cases -- the closest proxy
#   for what a news service delivers, and a floor (one outlet).
#
# Usage: uv run python eval/run_teamnews_knowable.py --season 2025-26
#        (runs arms A, B, C sequentially; skip-if-exists per arm)

import argparse
import json
import sys
import time
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "squad"))

import oracle_minutes  # noqa: E402
import simulator  # noqa: E402

OUT = REPO / "data" / "teamnews"
H, DECAY = 6, 0.45
WC1 = 2
WC2 = {"2023-24": 32, "2024-25": 31, "2025-26": 32}
FH2 = {"2023-24": 29, "2024-25": 29, "2025-26": 34}
BB1 = {"2023-24": 7, "2024-25": 7, "2025-26": 10}
BB2 = {"2023-24": 34, "2024-25": 33, "2025-26": 33}

VERIFIED = {("2024-25", 5, "Kevin De Bruyne"),
            ("2024-25", 14, "Gabriel dos Santos Magalhães"),
            ("2024-25", 11, "Manuel Akanji"),
            ("2023-24", 16, "Erling Haaland"),
            ("2024-25", 28, "Emiliano Martínez Romero"),
            ("2023-24", 34, "Malo Gusto"),
            ("2024-25", 29, "Cole Palmer"),
            ("2024-25", 19, "Kai Havertz"),
            ("2025-26", 30, "Ibrahima Konaté"),
            ("2025-26", 28, "Erling Haaland")}


def knowable_mask(season):
    """Criterion (1) congestion + (2) long-absence return, from vaastav."""
    hist = pd.read_parquet(REPO / "data/history/all_seasons_fixed.parquet")
    hist = hist[hist["season"] == season].copy()
    hist["kickoff_time"] = pd.to_datetime(hist["kickoff_time"], utc=True)
    hist["minutes"] = pd.to_numeric(hist["minutes"], errors="coerce").fillna(0)
    mask = set()
    # (1) per player-fixture: >= 60 min in a fixture within prior 4 days
    for e, g in hist.groupby("element"):
        g = g.sort_values("kickoff_time")
        kos = g["kickoff_time"].tolist()
        mins = g["minutes"].tolist()
        rounds = g["round"].tolist()
        for i in range(len(g)):
            for j in range(i - 1, -1, -1):
                dt = (kos[i] - kos[j]).total_seconds() / 86400
                if dt > 4:
                    break
                if mins[j] >= 60 and rounds[j] != rounds[i]:
                    mask.add((int(rounds[i]), int(e)))
                    break
    # (2) first gw after 3+ consecutive zero-minute gameweeks
    pergw = (hist.groupby(["element", "round"])["minutes"].sum()
             .unstack(fill_value=float("nan")))
    for e, row in pergw.iterrows():
        zero_run = 0
        for gw in sorted(pergw.columns):
            v = row.get(gw)
            if pd.isna(v):
                continue
            if zero_run >= 3:
                mask.add((int(gw), int(e)))
            zero_run = zero_run + 1 if v == 0 else 0
    return mask


def reported_mask(season):
    cases = pd.read_parquet(OUT / "case_list.parquet")
    m = set()
    for _, r in cases[cases["season"] == season].iterrows():
        if (season, int(r["gw"]), r["player"]) in VERIFIED:
            m.add((int(r["gw"]), int(r["element"])))
    return m


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", required=True)
    a = ap.parse_args()
    season = a.season
    tag = season.replace("-", "_")
    wf_path = REPO / "data" / f"walkforward_h6_{tag}.parquet"

    arms = {"A": ("step0", None),
            "B": ("masked_step0", knowable_mask(season)),
            "C": ("masked_step0", reported_mask(season))}
    for arm, (mode, mask) in arms.items():
        out = OUT / f"oraclelog_{tag}_{arm}.parquet"
        if out.exists():
            print(f"skip existing {out.name}", flush=True)
            continue
        oracle_minutes.ORACLE_MINUTES_ACTIVE = True
        oracle_minutes.ORACLE_MODE = mode
        oracle_minutes.ORACLE_MASK = mask
        if mask is not None:
            print(f"arm {arm}: mask {len(mask)} (gw, element) reveals",
                  flush=True)
        try:
            df = simulator.load_season(walkforward_path=str(wf_path),
                                       horizon_aware=True, season=season)
            t0 = time.time()
            state, log = simulator.simulate_season(
                df, policy="mip", horizon=H, decay=DECAY,
                wildcard_gws=[WC1, WC2[season]], free_hit_gws=FH2[season],
                bench_boost_gw=[BB1[season], BB2[season]], verbose=False)
            log = log.copy()
            assert log["oracle_minutes_active"].unique().tolist() == [True]
            assert log["oracle_mode"].unique().tolist() == [mode]
            log["all_transfers"] = log["all_transfers"].map(json.dumps)
            log["elements"] = log["elements"].map(json.dumps)
            log["season"], log["arm"] = season, arm
            log["mask_size"] = len(mask) if mask is not None else -1
            log["wf_file"] = wf_path.name
            log["final_total"] = int(state.total_points)
            tmp = out.with_suffix(".tmp.parquet")
            log.to_parquet(tmp, index=False)
            tmp.replace(out)
            print(f"DONE {out.name}: total={int(state.total_points)} "
                  f"({(time.time() - t0) / 60:.1f} min)", flush=True)
        except Exception as e:
            print(f"FAILED {out.name}: {type(e).__name__}: {e}", flush=True)
        finally:
            oracle_minutes.ORACLE_MINUTES_ACTIVE = False
            oracle_minutes.ORACLE_MODE = "full"
            oracle_minutes.ORACLE_MASK = None
    print(f"STEP5 WORKER COMPLETE {season}", flush=True)


if __name__ == "__main__":
    main()
