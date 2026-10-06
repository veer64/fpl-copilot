"""What actually happened: per-player actual points, and the user's own team score.

WHY THIS READS A PARQUET AND NOT A NEW TABLE (discovered 2026-10-05, Part 0)
The 2026-27 actuals are ALREADY stored, with the whole breakdown, in
`data/history/fpl_api_<season>.parquet`: 74 columns per (element, fixture),
GW1-5 at the time of writing, 667 elements. `eval/fetch_fpl_history.py` writes
it from `/element-summary/<id>/`, cross-checks every row against
`/event/<gw>/live/` and refuses to write a gameweek that is not both `finished`
and `data_checked`; `eval/run_weekly_ingest.py` runs that as step 1 of every
chain. It is also already the scorer's own input (`eval/score_squads.py` reads
exactly this file). A second store of the same numbers would be a second source
of truth that could disagree with the one the scorer uses, so these tools read
the file the pipeline already maintains.

The per-gameweek provenance -- when it was pulled, and whether FPL had finished
checking it -- lives beside it in `fpl_api_<season>.provenance.json`.

NOTHING HERE SCORES A SQUAD. The team score comes from
`squad_store.score_gameweek_for`, which is `squad/scoring.py`'s scorer:
autosubs, the armband with its vice fallback, and hits deducted. This module
only hands it the actuals frame it already expects.

Current season only. Past seasons' actuals sit in the frozen vaastav archive
under a different shape and are deliberately out of scope here.
"""
import json
from pathlib import Path

REPO = Path(__file__).resolve().parent

# The breakdown FPL publishes per player per gameweek, in the order a reader wants it.
# Every one of these is a column of the master parquet (checked by the tests).
BREAKDOWN_COLS = [
    "minutes", "goals_scored", "assists", "clean_sheets", "goals_conceded",
    "own_goals", "penalties_saved", "penalties_missed", "yellow_cards", "red_cards",
    "saves", "bonus", "bps", "starts", "defensive_contribution",
]
# Reported beside the breakdown but not part of FPL's points arithmetic.
EXPECTED_COLS = ["expected_goals", "expected_assists", "expected_goal_involvements",
                 "expected_goals_conceded"]
# What the scorer needs, and what master_rows_hash hashes.
MASTER_COLS = ["element", "GW", "fixture", "minutes", "total_points"]


def master_path(season, data_dir=None):
    """The file eval/score_squads.py scores from -- the same convention, deliberately."""
    root = Path(data_dir) if data_dir else REPO / "data"
    return root / "history" / f"fpl_api_{season.replace('-', '_')}.parquet"


def provenance_path(season, data_dir=None):
    p = master_path(season, data_dir)
    return p.with_name(p.stem + ".provenance.json")


def load_master(season, data_dir=None, columns=None):
    """The master frame, or None when the season has no file (nothing ingested yet)."""
    import pandas as pd
    p = master_path(season, data_dir)
    if not p.exists():
        return None
    return pd.read_parquet(p, columns=columns)


def load_provenance(season, data_dir=None):
    """{gw: {pulled_at, finished, data_checked, rows, ...}} or {} when unreadable.

    Optional: a missing sidecar costs the fetched_at line and the provisional flag,
    never the points, so it must not raise.
    """
    try:
        doc = json.loads(provenance_path(season, data_dir).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    out = {}
    for k, v in (doc.items() if isinstance(doc, dict) else []):
        try:
            out[int(k)] = v
        except (TypeError, ValueError):
            continue
    return out


def gws_held(master):
    """Sorted gameweeks the master holds. These are the answerable ones: a gameweek
    is in the file only once fetch_fpl_history accepted it as finished and checked."""
    if master is None or len(master) == 0:
        return []
    return sorted(int(g) for g in master["GW"].dropna().unique())


def provisional_for(prov, gw):
    """(provisional, fetched_at). Provisional means FPL had not finished checking the
    gameweek when it was pulled, so bonus and totals can still move."""
    meta = prov.get(int(gw)) or {}
    fetched_at = meta.get("pulled_at")
    if not meta:
        return None, None                       # no sidecar: say unknown, never "final"
    return not (bool(meta.get("finished")) and bool(meta.get("data_checked"))), fetched_at


def _int(v):
    try:
        if v is None or (isinstance(v, float) and v != v):
            return None
        return int(v)
    except (TypeError, ValueError):
        return None


def _num(v):
    try:
        if v is None or (isinstance(v, float) and v != v):
            return None
        return round(float(v), 2)
    except (TypeError, ValueError):
        return None


def player_gameweek(master, element, gw):
    """One gameweek for one player, aggregated over fixtures (a double gameweek is
    one row with both counted, which is how FPL settles it and how the scorer reads
    it). None when the player has no row in that gameweek.

    A player with a row but zero minutes DID have a gameweek -- he was in the game and
    did not play -- which is not the same as having no row, so it is reported, not
    dropped.
    """
    rows = master[(master["element"] == int(element)) & (master["GW"] == int(gw))]
    if len(rows) == 0:
        return None
    out = {"gw": int(gw), "n_fixtures": int(len(rows)),
           "total_points": _int(rows["total_points"].sum())}
    for c in BREAKDOWN_COLS:
        if c in rows.columns:
            out[c] = _int(rows[c].sum())
    for c in EXPECTED_COLS:
        if c in rows.columns:
            out[c] = _num(rows[c].astype(float).sum())
    fx = [f for f in (_int(v) for v in rows["fixture"]) if f is not None]
    out["fixtures"] = sorted(fx)
    return out


def player_season(master, element):
    """Every gameweek the master holds for one player, oldest first, plus the total."""
    weeks = [player_gameweek(master, element, g) for g in gws_held(master)]
    weeks = [w for w in weeks if w is not None]
    return weeks, sum(int(w["total_points"]) for w in weeks)


def actuals_frame(master, gw):
    """The frame squad_store's scorer expects for `gw`. Delegates the aggregation rule
    to squad_store.actuals_from_master so a double gameweek is summed in ONE place."""
    import squad_store
    return squad_store.actuals_from_master(master, int(gw))
