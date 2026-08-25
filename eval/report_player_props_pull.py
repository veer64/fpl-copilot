"""Reports the scale pull of historical anytime-goalscorer boards (eval/pull_player_props_history.py) from the manifests and raw files under data/odds_props/raw/scale/: fixtures matched vs on file per gameweek, snapshot gap to the FPL deadline, books present and players priced per fixture (distribution, empties, thin boards), credits spent, and a re-verification of every stored file's snapshot timestamp against the deadline. No parsing of prices, no crosswalk, no feature. Result of record: Logs/player_props_coverage_log.md section 7.

Usage: uv run python eval/report_player_props_pull.py [--append-log]
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parent.parent
SCALE = REPO / "data" / "odds_props" / "raw" / "scale"
SEASONS = ["2024-25", "2025-26"]


def main():
    append = "--append-log" in sys.argv
    md = ["## 7. Scale pull — every fixture, last snapshot before each FPL deadline, eu+us (2026-08-24)\n",
          "Governed by `Logs/props_prereg.md` (committed before the pull). `eval/pull_player_props_history.py`: "
          "deadline read from the FPL events[] array per gameweek, each fixture matched to exactly one event, "
          "kickoff asserted after the deadline, query at deadline − 60 s, raw JSON written atomically per event, "
          "manifest row per event, skip-if-exists. No prices parsed, no crosswalk, no feature.\n"]
    for season in SEASONS:
        d = SCALE / season
        mp = d / "manifest.csv"
        if not mp.exists():
            print(f"{season}: no manifest"); continue
        m = pd.read_csv(mp)
        fx_total = len(m)
        ok = m[m["event_id"].notna() & (m["event_id"].astype(str) != "")]
        unmatched = m[m["books"].astype(str).str.startswith("UNMATCHED")]
        failed = m[m["books"].astype(str) == "CALL_FAILED"]
        pulled = ok[~ok["books"].astype(str).isin(["CALL_FAILED"])]
        # per-book player counts
        rows = []
        for r in pulled.itertuples():
            pb = str(r.players_by_book) if isinstance(r.players_by_book, str) else ""
            books = {kv.split(":")[0]: int(kv.split(":")[1]) for kv in pb.split("|") if ":" in kv}
            rows.append(dict(gw=int(r.gw), fixture=f"{r.home} v {r.away}", n_books=len(books),
                             onexbet=books.get("onexbet", 0), us_max=max([v for k, v in books.items() if k != "onexbet"] or [0]),
                             us_books=len([k for k in books if k != "onexbet"]), any_book=len(books) > 0,
                             gap=float(r.gap_min) if pd.notna(r.gap_min) and str(r.gap_min) != "" else np.nan,
                             cost=int(r.cost)))
        b = pd.DataFrame(rows)
        gws = sorted(m["gw"].unique())
        empties = b[~b["any_book"]]
        thin = b[b["any_book"] & (b[["onexbet", "us_max"]].max(axis=1) < 20)]
        # re-verify snapshot < deadline from the raw files themselves
        bad_ts = 0; n_files = 0
        for r in pulled.itertuples():
            f = d / f"gw{int(r.gw):02d}_{r.event_id}_euus.json"
            if not f.exists():
                continue
            n_files += 1
            j = json.loads(f.read_text(encoding="utf-8"))
            if not (j.get("timestamp") and j["timestamp"] < r.deadline):
                bad_ts += 1
        spent = int(m["cost"].sum())
        print(f"================ {season} ================")
        print(f"  gameweeks {gws[0]}-{gws[-1]} ({len(gws)}); fixtures on file {fx_total}; matched & pulled {len(pulled)}; "
              f"unmatched {len(unmatched)}; call failures {len(failed)}")
        print(f"  raw files re-verified: {n_files}, snapshot before deadline in {n_files - bad_ts} ({bad_ts} violations)")
        print(f"  snapshot gap to deadline (min): min {b['gap'].min():.1f}, median {b['gap'].median():.1f}, max {b['gap'].max():.1f}")
        print(f"  fixtures with ANY book: {int(b['any_book'].sum())} of {len(b)} ({b['any_book'].mean():.1%}); "
              f"with 1xBet: {int((b['onexbet'] > 0).sum())}; with >=1 US book: {int((b['us_books'] > 0).sum())}; "
              f"US books per fixture median {b['us_books'].median():.0f}")
        print(f"  players priced -- 1xBet: median {b.loc[b['onexbet'] > 0, 'onexbet'].median():.0f} "
              f"(min {b.loc[b['onexbet'] > 0, 'onexbet'].min()}, max {b['onexbet'].max()}); "
              f"best US book: median {b.loc[b['us_max'] > 0, 'us_max'].median():.0f}")
        print(f"  EMPTY fixtures (no book): {len(empties)}" + (f" -> " + "; ".join(f"GW{r.gw} {r.fixture}" for r in empties.itertuples()) if len(empties) else ""))
        print(f"  thin boards (<20 at every book): {len(thin)}" + (f" -> " + "; ".join(f"GW{r.gw} {r.fixture} ({max(r.onexbet, r.us_max)})" for r in thin.itertuples()) if len(thin) else ""))
        print(f"  credits spent: {spent}; remaining after last call: {int(m['remaining'].dropna().iloc[-1])}")
        per_gw = b.groupby("gw").agg(fixtures=("fixture", "size"), with_book=("any_book", "sum"),
                                     onexbet_med=("onexbet", "median"), us_med=("us_max", "median"))
        weak = per_gw[per_gw["with_book"] < per_gw["fixtures"]]
        if len(weak):
            print("  gameweeks with fixtures lacking any book: " + "; ".join(f"GW{g}: {int(r.with_book)}/{int(r.fixtures)}" for g, r in weak.iterrows()))
        md.append(f"### {season}\n")
        md.append(f"- Gameweeks {gws[0]}–{gws[-1]}; fixtures on file {fx_total}; matched to exactly one event and pulled "
                  f"{len(pulled)}; unmatched {len(unmatched)}; call failures {len(failed)}. Raw files re-verified: {n_files}, "
                  f"snapshot strictly before the deadline in all but {bad_ts}.")
        md.append(f"- Snapshot gap to deadline: min {b['gap'].min():.1f} / median {b['gap'].median():.1f} / max {b['gap'].max():.1f} minutes.")
        md.append(f"- Fixtures with any book {int(b['any_book'].sum())}/{len(b)} ({b['any_book'].mean():.1%}); with 1xBet "
                  f"{int((b['onexbet'] > 0).sum())}; with ≥1 US book {int((b['us_books'] > 0).sum())} (median {b['us_books'].median():.0f} US books).")
        md.append(f"- Players priced: 1xBet median {b.loc[b['onexbet'] > 0, 'onexbet'].median():.0f} "
                  f"(min {b.loc[b['onexbet'] > 0, 'onexbet'].min()}, max {b['onexbet'].max()}); best US book median "
                  f"{b.loc[b['us_max'] > 0, 'us_max'].median():.0f}. Thin boards (<20 everywhere): {len(thin)}.")
        md.append(f"- Empty fixtures: {len(empties)}" + (" — " + "; ".join(f"GW{r.gw} {r.fixture}" for r in empties.itertuples()) if len(empties) else "") + ".")
        if len(weak):
            md.append("- Gameweeks with fixtures lacking any book: " + "; ".join(f"GW{g} {int(r.with_book)}/{int(r.fixtures)}" for g, r in weak.iterrows()) + ".")
        md.append(f"- Credits spent {spent}; remaining after the last call {int(m['remaining'].dropna().iloc[-1])}.\n")
    text = "\n".join(md) + "\n"
    if append:
        log = REPO / "Logs" / "player_props_coverage_log.md"
        cur = log.read_text(encoding="utf-8")
        if "## 7. Scale pull" in cur:
            print("log already has section 7 -- not appended twice")
        else:
            log.write_text(cur.rstrip("\n") + "\n\n---\n\n" + text, encoding="utf-8")
            print(f"appended section 7 to {log}")


if __name__ == "__main__":
    main()
