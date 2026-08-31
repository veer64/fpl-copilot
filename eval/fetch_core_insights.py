"""Core-insights ingestion for 2026-27 -- INGESTION ONLY. Does not change defensive.py, DC_SEASONS,
DC_RULE_SEASONS, or the DC source (the FPL-API swap is a separate, measured change). Pulls one gameweek
from olbauday/FPL-Core-Insights raw URLs and emits rows in the EXACT schema of the two parquets the DC
term reads -- data/history/core_insights_matchstats.parquet (player-match grain; the six fields
defensive.py consumes: tackles, interceptions, recoveries, blocks, clearances, minutes_played, plus
player_id/match_id/gw/season) and core_insights_gameweek_stats.parquet (the id->position map). Both
schemas -- columns, order, dtypes -- are read from the existing parquets at runtime, never hardcoded.

PATH CONSTRUCTION -- FAIL LOUDLY, NEVER GUESS. The repo's layout changed across seasons (2024-2025 used
data/<season>/playermatchstats/; 2025-2026+ uses data/<season>/By Gameweek/GW{n}/<file>), so paths come
from an explicit per-season map (SEASON_LAYOUT). An unmapped season raises with instructions to inspect
the repo and add the mapping; a 404 raises after retries; a fetched file missing any required column
raises naming the column. Nothing falls through to an empty frame.

FINALITY. Core-insights auto-commits several times daily, so a mid-round pull is incomplete. A gameweek
is FINAL only when (a) every row of the gameweek's matches.csv has finished == True, (b) every match_id
in matches.csv appears in playermatchstats.csv, and (c) the match count equals the authoritative fixture
count for that event from the FPL API fixtures/ endpoint. Anything else is refused
(ProvisionalGameweekError) unless --provisional, which writes *_PROVISIONAL_gw{n}.parquet side files
(same schema, own provenance JSON) that are NEVER merged -- the same split, file-naming and
finality-is-the-file convention as eval/fetch_fpl_history.py.

APPEND, DO NOT REBUILD. The existing parquets are never touched. Final gameweeks upsert into
data/history/core_insights_matchstats_2026_27.parquet and core_insights_gameweek_stats_2026_27.parquet
(atomic, deduped, provenance sidecars); --combine writes core_insights_*_with_2026_27.parquet =
existing parquet + season file with the schema asserted equal. Nothing in modelling reads the combined
files yet (DC_SEASONS / DC_RULE_SEASONS / defensive.SEASON / the season-less _DC_HITS_CACHE are unfixed
by design of this task).

Usage:
  uv run python eval/fetch_core_insights.py --season 2026-27 --gw 1
  uv run python eval/fetch_core_insights.py --season 2026-27 --gw 1 --verify
  uv run python eval/fetch_core_insights.py --season 2026-27 --gw 1 --crosscheck-api
  uv run python eval/fetch_core_insights.py --season 2026-27 --combine
"""
import argparse
import io
import json
import os
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parent.parent
HIST = REPO / "data" / "history"
MS_PARQUET = HIST / "core_insights_matchstats.parquet"
GS_PARQUET = HIST / "core_insights_gameweek_stats.parquet"
RAW = "https://raw.githubusercontent.com/olbauday/FPL-Core-Insights/main"
FPL_FIXTURES = "https://fantasy.premierleague.com/api/fixtures/"
UA = {"User-Agent": "Mozilla/5.0 (fpl-copilot ingestion; weekly; contact: repo owner)"}
SLEEP = 0.5
RETRIES = 3

# Per-season layout map: the ONLY place paths are built. The repo reorganised
# between 2024-2025 and 2025-2026, so nothing is derived by pattern -- an
# unknown season must be mapped here by hand after inspecting the repo.
SEASON_LAYOUT = {
    # column_map: source column -> schema column. MEASURED, not guessed (2026-08-31, GW1):
    # the repo's 2026-27 `tackles` column is 100% NULL while `tackles_won` matches the FPL
    # API's native `tackles` EXACTLY (1.000 on every played row; clearances+blocks+
    # interceptions == the API's CBI at 1.000 too). In 2025-26's own files `tackles` was
    # populated. So what defensive.py means by `tackles` is published as `tackles_won`
    # this season; the map is applied with an ambiguity guard -- if the source's own
    # `tackles` ever comes back non-null alongside, the pull raises rather than choosing.
    "2026-27": {"core_season": "2026-2027",
                "gw_dir": "data/2026-2027/By Gameweek/GW{gw}/{fname}",
                "column_map": {"tackles": "tackles_won"}},
}
REQUIRED_MS = ["player_id", "match_id", "minutes_played", "tackles", "interceptions",
               "recoveries", "blocks", "clearances"]


class ProvisionalGameweekError(RuntimeError):
    """The gameweek is not verifiably complete; writing it as final is refused."""


class LayoutError(RuntimeError):
    """The repo's per-season layout is not mapped or has changed."""


def log(msg):
    print(f"[{datetime.now():%H:%M:%S}] fetch_core_insights: {msg}", flush=True)


def _layout(season):
    if season not in SEASON_LAYOUT:
        raise LayoutError(
            f"no path layout mapped for season {season!r}. The FPL-Core-Insights repo has "
            f"reorganised across seasons before (2024-2025 vs 'By Gameweek'); inspect "
            f"https://github.com/olbauday/FPL-Core-Insights/tree/main/data and add an explicit "
            f"entry to SEASON_LAYOUT. Guessing paths is deliberately not supported.")
    return SEASON_LAYOUT[season]


def fetch_csv(season, gw, fname):
    lay = _layout(season)
    url = f"{RAW}/{lay['gw_dir'].format(gw=gw, fname=fname)}".replace(" ", "%20")
    for attempt in range(1, RETRIES + 1):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=60) as r:
                raw = r.read()
            time.sleep(SLEEP)
            return pd.read_csv(io.BytesIO(raw), low_memory=False)
        except urllib.error.HTTPError as e:
            if e.code == 404:
                raise LayoutError(
                    f"{url} -> 404. Either GW{gw} does not exist yet or the repo layout changed "
                    f"again; inspect the repo and update SEASON_LAYOUT. Not guessing.") from e
            if attempt == RETRIES:
                raise
            time.sleep(2 ** attempt)
        except Exception:
            if attempt == RETRIES:
                raise
            time.sleep(2 ** attempt)


def get_fpl_fixture_count(gw):
    req = urllib.request.Request(f"{FPL_FIXTURES}?event={gw}", headers=UA)
    with urllib.request.urlopen(req, timeout=30) as r:
        return len(json.loads(r.read().decode()))


def check_final(season, gw, matches, pms):
    """The three-part finality rule. Raises ProvisionalGameweekError with the reason."""
    reasons = []
    if "finished" not in matches.columns:
        raise LayoutError("matches.csv has no `finished` column -- layout changed; not guessing")
    if not matches["finished"].astype(bool).all():
        reasons.append(f"{int((~matches['finished'].astype(bool)).sum())} of {len(matches)} matches not finished")
    missing = set(matches["match_id"]) - set(pms["match_id"])
    if missing:
        reasons.append(f"{len(missing)} match(es) without playermatchstats rows: {sorted(missing)[:3]}")
    expected = get_fpl_fixture_count(gw)
    if len(matches) != expected:
        reasons.append(f"matches.csv has {len(matches)} fixtures, FPL fixtures/ says {expected}")
    if reasons:
        raise ProvisionalGameweekError(f"GW{gw} is PROVISIONAL: " + "; ".join(reasons))
    return expected


def apply_column_map(df, column_map):
    """Explicit per-season semantic renames (SEASON_LAYOUT['column_map']), each with an
    ambiguity guard: if the schema column is itself still populated in the source, the
    repo is publishing BOTH and the choice must be re-measured -- raise, never pick."""
    df = df.copy()
    for schema_col, source_col in column_map.items():
        if source_col not in df.columns:
            raise LayoutError(f"column_map expects source column {source_col!r} -- absent; layout changed again")
        if schema_col in df.columns and df[schema_col].notna().any():
            raise LayoutError(
                f"column_map maps {source_col!r} -> {schema_col!r}, but the source's own "
                f"{schema_col!r} is no longer all-null ({int(df[schema_col].notna().sum())} values). "
                f"Both populated = ambiguous; re-measure against the FPL API before trusting either.")
        df[schema_col] = df[source_col]
    return df


def _cast_to_schema(df, schema):
    """Cast to the parquet's exact dtypes. Integer schema columns with NA in the
    source are filled 0 -- NOT silently: the fill counts are returned and land in
    provenance. This mirrors the historical parquet (its int64 dtypes mean the
    original hand-ingest already did this) and defensive.py's own
    pd.to_numeric(...).fillna(0) on every field it consumes."""
    df = df[list(schema.columns)].copy()
    filled = {}
    for c in df.columns:
        want = schema[c].dtype
        try:
            df[c] = df[c].astype(want)
        except (TypeError, ValueError, pd.errors.IntCastingNaNError):
            v = pd.to_numeric(df[c], errors="coerce")
            if pd.api.types.is_integer_dtype(want):
                n = int(v.isna().sum())
                if n:
                    filled[c] = n
                v = v.fillna(0)
            df[c] = v.astype(want)
    return df, filled


def build_frames(season, gw):
    """(matchstats frame, gameweek_stats frame, provenance) in the exact parquet schemas."""
    lay = _layout(season)
    ms_schema = pd.read_parquet(MS_PARQUET).iloc[0:0]
    gs_schema = pd.read_parquet(GS_PARQUET).iloc[0:0]
    matches = fetch_csv(season, gw, "matches.csv")
    pms = fetch_csv(season, gw, "playermatchstats.csv")
    players = fetch_csv(season, gw, "players.csv")
    pstats = fetch_csv(season, gw, "playerstats.csv")
    for c in REQUIRED_MS:
        if c not in pms.columns:
            raise LayoutError(f"playermatchstats.csv is missing required column {c!r} -- schema changed")
    pms = apply_column_map(pms, lay.get("column_map", {}))
    dead = [c for c in REQUIRED_MS if c != "player_id" and c != "match_id" and pms[c].isna().all()]
    if dead:
        raise LayoutError(
            f"required column(s) {dead} are present but ENTIRELY NULL in playermatchstats.csv -- the "
            f"repo has moved the semantic to another column (as it did tackles -> tackles_won in "
            f"2026-27); measure which column matches the FPL API and extend column_map. Not filling zeros.")
    final_reason = None
    try:
        check_final(season, gw, matches, pms)
        final = True
    except ProvisionalGameweekError as e:
        final, final_reason = False, str(e)
    # ---- matchstats in the exact parquet schema
    ms = pms.copy()
    ms["season"] = lay["core_season"]
    ms["gw"] = int(gw)
    only_src = [c for c in ms.columns if c not in ms_schema.columns]
    only_parq = [c for c in ms_schema.columns if c not in ms.columns]
    if only_src:
        log(f"matchstats: dropping {len(only_src)} source-only column(s) not in the parquet schema: {only_src[:6]}")
        ms = ms.drop(columns=only_src)
    for c in only_parq:
        ms[c] = pd.NA
    ms, ms_filled = _cast_to_schema(ms, ms_schema)
    if ms_filled:
        log(f"matchstats: NA->0 fills on int columns (the historical parquet's own convention -- its "
            f"int64 dtypes imply the hand-ingest filled these; defensive.py fillna(0)s them anyway): {ms_filled}")
    assert not ms.duplicated(["player_id", "match_id"]).any(), "duplicate (player_id, match_id) rows"
    # ---- gameweek_stats (the position map): playerstats + players' position, exact schema
    pos = players.rename(columns={"player_id": "id"})[["id", "position"]]
    gs = pstats.merge(pos, on="id", how="left")
    no_pos = gs[gs["position"].isna()]
    if no_pos["id"].isin(pms["player_id"]).any():
        raise LayoutError(f"position-less id(s) appear in matchstats: "
                          f"{sorted(no_pos.loc[no_pos['id'].isin(pms['player_id']), 'id'])} -- the DC "
                          f"position map would be wrong; not guessing")
    if len(no_pos):
        log(f"gameweek_stats: dropping {len(no_pos)} playerstats id(s) absent from players.csv "
            f"(none appears in matchstats): {sorted(no_pos['id'])[:8]}")
        gs = gs[gs["position"].notna()].copy()
    gs["season"] = lay["core_season"]
    gs["gw"] = int(gw)
    gs_only_src = [c for c in gs.columns if c not in gs_schema.columns]
    if gs_only_src:
        log(f"gameweek_stats: dropping {len(gs_only_src)} source-only column(s): {gs_only_src[:6]}")
        gs = gs.drop(columns=gs_only_src)
    for c in [c for c in gs_schema.columns if c not in gs.columns]:
        gs[c] = pd.NA
    gs, gs_filled = _cast_to_schema(gs, gs_schema)
    if gs_filled:
        log(f"gameweek_stats: NA->0 fills on int columns: {gs_filled}")
    prov = dict(season=season, core_season=lay["core_season"], gw=int(gw),
                pulled_at=datetime.now(timezone.utc).isoformat(), final=final,
                provisional_reason=final_reason, matches=int(matches["match_id"].nunique()),
                matchstats_rows=len(ms), gameweek_stats_rows=len(gs),
                source_only_columns=only_src, parquet_only_columns=only_parq,
                int_na_filled_matchstats=ms_filled, int_na_filled_gameweek_stats=gs_filled,
                column_map=lay.get("column_map", {}), positionless_ids_dropped=sorted(no_pos["id"].tolist()))
    log(f"GW{gw}: {len(ms)} matchstats rows over {prov['matches']} matches; {len(gs)} position rows; "
        f"{'FINAL' if final else 'PROVISIONAL -- ' + str(final_reason)}")
    return ms, gs, prov


def _upsert(df, path, gw, keys):
    if path.exists():
        old = pd.read_parquet(path)
        df = pd.concat([old[old["gw"] != gw], df], ignore_index=True).sort_values(keys).reset_index(drop=True)
    tmp = path.with_suffix(".tmp.parquet")
    df.to_parquet(tmp, index=False)
    os.replace(tmp, path)
    return df


def write(ms, gs, prov, season, final):
    tag = season.replace("-", "_")
    if final:
        p_ms = HIST / f"core_insights_matchstats_{tag}.parquet"
        p_gs = HIST / f"core_insights_gameweek_stats_{tag}.parquet"
        _upsert(ms, p_ms, prov["gw"], ["gw", "match_id", "player_id"])
        _upsert(gs, p_gs, prov["gw"], ["gw", "id"])
        side = HIST / f"core_insights_{tag}.provenance.json"
        meta = json.loads(side.read_text(encoding="utf-8")) if side.exists() else {}
        meta[str(prov["gw"])] = prov
        side.write_text(json.dumps(meta, indent=1), encoding="utf-8")
        log(f"FINAL -> {p_ms.name} + {p_gs.name}; provenance -> {side.name}")
    else:
        p_ms = HIST / f"core_insights_matchstats_{tag}_PROVISIONAL_gw{prov['gw']}.parquet"
        p_gs = HIST / f"core_insights_gameweek_stats_{tag}_PROVISIONAL_gw{prov['gw']}.parquet"
        for df, p in ((ms, p_ms), (gs, p_gs)):
            tmp = p.with_suffix(".tmp.parquet")
            df.to_parquet(tmp, index=False)
            os.replace(tmp, p)
        p_ms.with_suffix(".provenance.json").write_text(json.dumps(prov, indent=1), encoding="utf-8")
        log(f"PROVISIONAL -> {p_ms.name} + {p_gs.name} -- never merged")


def combine(season):
    tag = season.replace("-", "_")
    for base_p, add_p, out_p in (
            (MS_PARQUET, HIST / f"core_insights_matchstats_{tag}.parquet",
             HIST / f"core_insights_matchstats_with_{tag}.parquet"),
            (GS_PARQUET, HIST / f"core_insights_gameweek_stats_{tag}.parquet",
             HIST / f"core_insights_gameweek_stats_with_{tag}.parquet")):
        base, add = pd.read_parquet(base_p), pd.read_parquet(add_p)
        assert list(base.columns) == list(add.columns), f"schema drift: {add_p.name}"
        for c in base.columns:
            if add[c].dtype != base[c].dtype:
                add[c] = add[c].astype(base[c].dtype)   # lossless parquet round-trip cast, else raises
        assert _layout(season)["core_season"] not in set(base["season"]), "season already in the base parquet"
        out = pd.concat([base, add], ignore_index=True)
        tmp = out_p.with_suffix(".tmp.parquet")
        out.to_parquet(tmp, index=False)
        os.replace(tmp, out_p)
        log(f"COMBINED -> {out_p.name}: {len(base)} existing (untouched) + {len(add)} new rows")


def verify(season, gw):
    """Rows, coverage, per-column presence/dtype vs the parquet, and the cbit/cbirt
    distribution computed EXACTLY as defensive.py does."""
    tag = season.replace("-", "_")
    ms_schema = pd.read_parquet(MS_PARQUET).iloc[0:0]
    ms = pd.read_parquet(HIST / f"core_insights_matchstats_{tag}.parquet")
    ms = ms[ms["gw"] == gw]
    print(f"\nVERIFY GW{gw}: {len(ms)} rows, {ms['match_id'].nunique()} matches, "
          f"{ms['player_id'].nunique()} players")
    same_cols = list(ms.columns) == list(ms_schema.columns)
    dt = {c: (str(ms[c].dtype), str(ms_schema[c].dtype)) for c in ms_schema.columns if ms[c].dtype != ms_schema[c].dtype}
    print(f"columns identical+ordered: {same_cols}; dtype mismatches: {dt if dt else 'none'}")
    nullcols = [c for c in ms.columns if ms[c].isna().all()]
    print(f"all-null columns in the pull (parquet-only, no 2026-27 source): {nullcols if nullcols else 'none'}")
    # cbit/cbirt exactly as defensive.py:41-50
    d = ms.copy()
    for c in ["tackles", "interceptions", "recoveries", "blocks", "clearances", "minutes_played"]:
        d[c] = pd.to_numeric(d[c], errors="coerce").fillna(0)
    d["cbit"] = d["clearances"] + d["blocks"] + d["interceptions"] + d["tackles"]
    d["cbirt"] = d["cbit"] + d["recoveries"]
    played = d[d["minutes_played"] >= 1]
    for name in ("cbit", "cbirt"):
        q = played[name].quantile([0.5, 0.9, 0.99]).round(1).tolist()
        print(f"{name}: played n {len(played)}, mean {played[name].mean():.2f}, "
              f"p50/p90/p99 {q}, max {int(played[name].max())}")
    gs = pd.read_parquet(HIST / f"core_insights_gameweek_stats_{tag}.parquet")
    print(f"position map: {len(gs)} rows, positions {sorted(gs['position'].dropna().unique())}")
    return d, played


def crosscheck_api(season, gw):
    """Report-only: core-insights-derived dc_metric vs the FPL API's native
    defensive_contribution count for the same gameweek. Evidence for the later
    swap decision; nothing is acted on."""
    tag = season.replace("-", "_")
    d, played = verify(season, gw)
    gs = pd.read_parquet(HIST / f"core_insights_gameweek_stats_{tag}.parquet")
    pos = gs.drop_duplicates("id").set_index("id")["position"]
    d = d.assign(position=d["player_id"].map(pos))
    d["dc_metric"] = np.where(d["position"] == "Defender", d["cbit"], d["cbirt"])
    ci = d.groupby("player_id").agg(dc_metric=("dc_metric", "sum"), minutes=("minutes_played", "sum")).reset_index()
    api = pd.read_parquet(HIST / f"fpl_api_{tag}.parquet")
    api = api[api["GW"] == gw].groupby("element").agg(dc_api=("defensive_contribution", "sum"),
                                                     api_minutes=("minutes", "sum")).reset_index()
    j = ci.merge(api, left_on="player_id", right_on="element", how="inner")
    jp = j[(j["minutes"] > 0) & (j["api_minutes"] > 0)].copy()
    jp["diff"] = jp["dc_metric"] - jp["dc_api"]
    exact = (jp["diff"] == 0).mean()
    print(f"\nCROSS-CHECK vs FPL API GW{gw} (report only): joined {len(j)} players, played {len(jp)}")
    print(f"dc_metric == API defensive_contribution: {exact:.2%}  (2025-26 GW20 historical: 87.25%)")
    print(f"disagreement distribution (core minus API): {jp['diff'].value_counts().sort_index().to_dict()}")
    print(f"|diff| mean {jp['diff'].abs().mean():.2f}, max {int(jp['diff'].abs().max())}; "
          f"threshold-relevant flips (crossing 10/12): "
          f"{int(((jp['dc_metric'] >= 10) != (jp['dc_api'] >= 10)).sum())} at 10, "
          f"{int(((jp['dc_metric'] >= 12) != (jp['dc_api'] >= 12)).sum())} at 12")
    return exact


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--season", required=True)
    ap.add_argument("--gw", type=int)
    ap.add_argument("--provisional", action="store_true")
    ap.add_argument("--verify", action="store_true")
    ap.add_argument("--crosscheck-api", action="store_true")
    ap.add_argument("--combine", action="store_true")
    a = ap.parse_args()
    if a.combine:
        combine(a.season)
        return
    if a.verify and a.gw and not a.crosscheck_api:
        verify(a.season, a.gw)
        return
    if a.crosscheck_api and a.gw:
        crosscheck_api(a.season, a.gw)
        return
    assert a.gw, "--gw required"
    ms, gs, prov = build_frames(a.season, a.gw)
    if not prov["final"] and not a.provisional:
        raise ProvisionalGameweekError(prov["provisional_reason"] +
                                       " -- use --provisional for a side file that is never merged")
    write(ms, gs, prov, a.season, final=prov["final"])


if __name__ == "__main__":
    main()
