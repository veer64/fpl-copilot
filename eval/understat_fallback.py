# understat_fallback.py -- Prompt R2 (3-4 Nov 2026): when understat cannot be read, a gameweek's per-match rows come from
# FPL's own per-player per-gameweek numbers, labelled, and are replaced by real understat rows when it returns.
#
# WHY: on 3 Nov 2026 understat.com moved host (the server's resolvers kept the dead address) and then served a
# maintenance page; the weekly ingest died at step 2 and, the forward skeleton being rebuilt LAST, every strict build
# after it failed on the master/skeleton collision assert -- no model until a human acted. The user's decision ("do B
# for now"): a safety net so a gameweek can be ingested without understat, labelled degraded, replaced by real data
# when understat is back, plus a phone ping then.
#
# WHAT THE ROWS ARE (the pre-registered candidate C1, chosen by the GW8 replay in eval/reports/r2_understat_fallback.md:
# Spearman(e_points) 0.9999, top-20 20/20, mean |d e_points| 0.0088 vs the real build): for every element with minutes
# in the gameweek that the crosswalk maps to an understat id, one row shaped EXACTLY like understat_matches.py's --
# the per-match schema is pinned by Tests/test_understat_ingest.py::test_per_match_schema_matches_2025_26, so there is
# no new column; the label is the match_id prefix "fpl" (understat ids are digits) plus the sidecar
# understat_matches_{tag}.fallback.json (source = "fpl_fallback"). npxG := FPL expected_goals (FPL identifies penalty
# MISSES only, never attempts or scored penalties, so no adjustment), npg := goals_scored, xA := FPL expected_assists,
# shots / xGChain / xGBuildup 0 (unused by the rate blend), position from FPL's (GK/DC/MC/FW -> the blend's groups).
# Calibration GW1-8 (2,461 player-matches): FPL xG vs understat npxG Spearman 0.98, MAE 0.04; xA 0.69 / 0.05.
#
# LEAKAGE: rows are written only for gameweeks the season file already carries (step 1 loads finished + data_checked
# gameweeks only), stamped with the fixture's kickoff and a pulled_at like understat rows.
#
# THE FILE IS THE TRUTH: understat_matches.py rewrites the whole per-match parquet from its raw cache when it succeeds,
# so fallback rows vanish the moment real rows land; fallback_gws() reads the file, never the sidecar.
import json
import os
import tempfile
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

SOURCE = "fpl_fallback"
MATCH_PREFIX = "fpl"
RULE = "C1: npxG := FPL xG, npg := goals, xA := FPL xA, no penalty columns (FPL names penalty misses only)"
LEAGUE_URL = "https://understat.com/getLeagueData/EPL/{year}"
HEADERS = {"User-Agent": "Mozilla/5.0", "X-Requested-With": "XMLHttpRequest"}
POSITION = {"GK": "GK", "DEF": "DC", "MID": "MC", "FWD": "FW"}     # -> attacking_rates._grp_from_match_pos GK / D / M / F
COLUMNS = ["season", "match_id", "match_datetime", "match_date", "understat_player_id", "player_name", "team", "opponent",
           "h_a", "position", "positionOrder", "minutes", "goals", "own_goals", "npg", "assists", "shots", "key_passes",
           "xG", "xA", "npxG", "xGChain", "xGBuildup", "yellow_card", "red_card", "gw", "gw_ambiguous", "pulled_at"]
STRING_COLS = ("season", "match_id", "understat_player_id", "player_name", "team", "opponent", "h_a", "position", "pulled_at")
INT_COLS = ("positionOrder", "minutes", "own_goals", "assists", "shots", "key_passes", "yellow_card", "red_card", "gw")
FLOAT_COLS = ("goals", "npg", "xG", "xA", "npxG", "xGChain", "xGBuildup")


def _tag(season):
    return season.replace("-", "_")


def per_match_path(data_dir, season):
    return Path(data_dir) / "history" / f"understat_matches_{_tag(season)}.parquet"


def sidecar_path(data_dir, season):
    return Path(data_dir) / "history" / f"understat_matches_{_tag(season)}.fallback.json"


def _prior_tag(season):
    y = int(season[:4])
    return f"{y - 1}_{str(y)[2:]}"


def reference_dtypes(data_dir, season):
    """The previous season's per-match file is the schema reference the ingest test pins against."""
    p = Path(data_dir) / "history" / f"understat_matches_{_prior_tag(season)}.parquet"
    if not p.exists():
        return None
    return pd.read_parquet(p).iloc[0:0].dtypes.to_dict()


def _atomic_write_parquet(df, path):
    path = Path(path)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".fb.", suffix=".parquet")
    os.close(fd)
    df.to_parquet(tmp, index=False)
    os.replace(tmp, path)


def _atomic_write_text(path, text):
    path = Path(path)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".fb.", suffix=".json")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(text)
    os.replace(tmp, path)


def _int(v):
    try:
        return 0 if pd.isna(v) else int(v)
    except (TypeError, ValueError):
        return 0


def _float(v):
    try:
        f = float(v)
        return 0.0 if f != f else f
    except (TypeError, ValueError):
        return 0.0


def fallback_rows(data_dir, season, gws, now=None):
    """C1 rows for `gws` from the season file + the crosswalk. Raises ValueError for a gameweek the season file does
    not carry (the leakage rule: finished + data_checked only, as step 1 loads them)."""
    data_dir = Path(data_dir)
    h = data_dir / "history"
    gws = sorted(int(g) for g in gws)
    api = pd.read_parquet(h / f"fpl_api_{_tag(season)}.parquet")
    have = {int(g) for g in api["GW"].dropna().unique()}
    missing = [g for g in gws if g not in have]
    if missing:
        raise ValueError(f"GW{','.join(str(g) for g in missing)}: not in the season file -- fallback rows are written "
                         f"only for finished, data_checked gameweeks that fetch_fpl_history has loaded")
    cw = pd.read_csv(h / f"crosswalk_{_tag(season)}.csv")[["element", "understat_id"]].dropna()
    cw["understat_id"] = cw["understat_id"].astype(float).astype(int).astype(str)
    sub = api[api["GW"].isin(gws) & (pd.to_numeric(api["minutes"], errors="coerce").fillna(0) > 0)]
    sub = sub.merge(cw, on="element", how="inner")
    stamp = (now or datetime.now(timezone.utc)).isoformat()
    rows = []
    for r in sub.itertuples(index=False):
        ko = pd.Timestamp(r.kickoff_time)
        if ko.tzinfo is not None:
            ko = ko.tz_convert("UTC").tz_localize(None)
        xg = _float(r.expected_goals)
        rows.append({
            "season": season, "match_id": f"{MATCH_PREFIX}{int(r.fixture)}",
            "match_datetime": ko, "match_date": ko.normalize(),
            "understat_player_id": str(r.understat_id), "player_name": str(r.name),
            "team": str(r.team), "opponent": str(getattr(r, "opponent_team", "")),
            "h_a": "h" if bool(getattr(r, "was_home", False)) else "a",
            "position": POSITION.get(str(r.position), "Sub"), "positionOrder": 0,
            "minutes": _int(r.minutes), "goals": float(_int(r.goals_scored)), "own_goals": _int(getattr(r, "own_goals", 0)),
            "npg": float(_int(r.goals_scored)), "assists": _int(r.assists), "shots": 0,
            "key_passes": _int(getattr(r, "key_passes", 0)),
            "xG": xg, "xA": _float(r.expected_assists), "npxG": xg, "xGChain": 0.0, "xGBuildup": 0.0,
            "yellow_card": _int(getattr(r, "yellow_cards", 0)), "red_card": _int(getattr(r, "red_cards", 0)),
            "gw": int(r.GW), "gw_ambiguous": False, "pulled_at": stamp,
        })
    df = pd.DataFrame(rows, columns=COLUMNS)
    for c in STRING_COLS:
        df[c] = df[c].astype("string")
    for c in INT_COLS:
        df[c] = df[c].astype("int64")
    for c in FLOAT_COLS:
        df[c] = df[c].astype("float64")
    df["gw_ambiguous"] = df["gw_ambiguous"].astype(bool)
    df["match_datetime"] = pd.to_datetime(df["match_datetime"])
    df["match_date"] = pd.to_datetime(df["match_date"])
    ref = reference_dtypes(data_dir, season)
    if ref:
        for c, dt in ref.items():
            if c in df.columns and str(df[c].dtype) != str(dt):
                try:
                    df[c] = df[c].astype(dt)
                except (TypeError, ValueError):
                    pass
    return df


def fallback_gws(data_dir, season):
    """Gameweeks the per-match FILE currently serves from the fallback (match_id prefix). The sidecar is a label."""
    p = per_match_path(data_dir, season)
    if not p.exists():
        return []
    df = pd.read_parquet(p, columns=["match_id", "gw"])
    m = df["match_id"].astype(str).str.startswith(MATCH_PREFIX)
    return sorted({int(g) for g in df.loc[m, "gw"].dropna().unique()})


def sync_sidecar(data_dir, season, reason=None, now=None):
    """Make the sidecar say what the file says: removed when no fallback rows remain."""
    gws = fallback_gws(data_dir, season)
    sp = sidecar_path(data_dir, season)
    if not gws:
        if sp.exists():
            sp.unlink()
        return gws
    p = per_match_path(data_dir, season)
    df = pd.read_parquet(p, columns=["match_id", "gw"])
    ids = sorted(df.loc[df["gw"].isin(gws) & df["match_id"].astype(str).str.startswith(MATCH_PREFIX), "match_id"].astype(str).unique())
    old = {}
    if sp.exists():
        try:
            old = json.loads(sp.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            old = {}
    first_reason = old.get("reason") or (reason or "")
    side = {"source": SOURCE, "season": season, "gws": gws, "match_ids": ids, "rule": RULE,
            "written": (now or datetime.now(timezone.utc)).isoformat(),
            "reason": first_reason[-600:],                       # why the fallback began
            "last_reason": (reason if reason is not None else old.get("last_reason") or first_reason)[-600:]}
    _atomic_write_text(sp, json.dumps(side, indent=1))
    return gws


def apply_fallback(data_dir, season, gws, reason="", now=None):
    """Write C1 rows for `gws` into the per-match file, replacing any rows of those gameweeks (idempotent); other
    gameweeks' rows are untouched. Returns {gws, rows, match_ids, path}."""
    gws = sorted(int(g) for g in gws)
    fb = fallback_rows(data_dir, season, gws, now=now)
    p = per_match_path(data_dir, season)
    if p.exists():
        cur = pd.read_parquet(p)
        keep = cur[~cur["gw"].isin(gws)]
        # the file's columns first (its schema wins), then any the file lacks (a test's minimal file; never production)
        cols = list(cur.columns) + [c for c in fb.columns if c not in cur.columns]
        out = pd.concat([keep.reindex(columns=cols), fb.reindex(columns=cols)], ignore_index=True)
        # the kept rows' dtypes win (pyarrow strings stay strings)
        for c in cur.columns:
            if c in fb.columns and str(out[c].dtype) != str(cur[c].dtype):
                try:
                    out[c] = out[c].astype(cur[c].dtype)
                except (TypeError, ValueError):
                    pass
    else:
        out = fb
    _atomic_write_parquet(out, p)
    sync_sidecar(data_dir, season, reason=reason, now=now)
    return {"gws": gws, "rows": int(len(fb)), "match_ids": sorted(fb["match_id"].astype(str).unique().tolist()),
            "path": str(p)}


def understat_year(now=None):
    """Understat labels a season by its starting year: 2026-27 -> 2026 (July onwards)."""
    now = now or datetime.now(timezone.utc)
    return now.year if now.month >= 7 else now.year - 1


def probe_once(year=None, opener=None, timeout=30):
    """ONE request to the league endpoint. (True, detail) when it answers the league JSON; (False, why) on a timeout,
    an HTTP error, the maintenance page or any non-JSON body."""
    url = LEAGUE_URL.format(year=year or understat_year())
    req = urllib.request.Request(url, headers=HEADERS)
    try:
        with (opener or urllib.request.urlopen)(req, timeout=timeout) as r:
            raw = r.read()
    except Exception as e:                                   # noqa: BLE001 -- the probe reports, never raises
        return False, f"{type(e).__name__}: {e}"[:300]
    if raw[:2] == b"\x1f\x8b":
        import gzip
        raw = gzip.decompress(raw)
    try:
        d = json.loads(raw.decode("utf-8"))
    except ValueError:
        text = raw[:600].decode("utf-8", errors="replace")
        snippet = "We will come back soon" if "We will come back soon" in text else " ".join(text.split())[:80]
        return False, f"not JSON ({len(raw)} bytes: {snippet})"
    if isinstance(d, dict) and isinstance(d.get("dates"), list):
        return True, f"JSON, {len(d['dates'])} dates"
    return False, "JSON without the league 'dates' block"
