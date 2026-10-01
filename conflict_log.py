"""The availability conflict log (Piece 9, 2026-10-01): club news versus FPL's official flag, measured
against what happened. RECORD AND MEASURE ONLY (D9): this module never writes to players_live or any
model table; FPL stays the official source until this log proves news is more accurate.

Buckets:  FPL  a -> FIT, d -> DOUBT, i / s / u / n -> OUT
          club available -> FIT, doubtful / returning -> DOUBT, out / suspended -> OUT

availability_comparisons holds one row per (gameweek, element_id) for every player with at least one
claim (availability_claims) fetched at or before that gameweek's deadline and inside the 7 days before
it: the FPL status and chance_of_playing_next_round from the newest raw bootstrap snapshot at or before
the deadline (the one date rule: strictly as of the deadline, so a rebuild gives identical rows), the
newest claim by the item's fetched_at, both buckets and `agree`. Outcomes come from the repo's own
results data, data/history/fpl_api_<season>.parquet (eval/fetch_fpl_history.py writes it per final
gameweek; the weekly ingest runs it): minutes summed over the gameweek's fixtures, started = any start,
played = minutes > 0. right_source: if played, FIT beats DOUBT beats OUT; if not, OUT beats DOUBT beats
FIT; the source with the better bucket is right, equal buckets tie. LIMITATION: not playing can mean
rotation, not injury; a fit player left out counts as 'not played'.

update_conflict_log(conn) builds comparisons for every passed deadline that lacks them and fills
outcomes where results now exist; idempotent; fetch_news.py calls it every 4 hours.
"""
from datetime import datetime, timedelta, timezone
from pathlib import Path

import relevance as rv

UTC = timezone.utc
REPO = Path(__file__).resolve().parent
HISTORY = REPO / "data" / "history" / "fpl_api_2026_27.parquet"
WINDOW = timedelta(days=7)
BUCKET_FPL = {"a": "FIT", "d": "DOUBT", "i": "OUT", "s": "OUT", "u": "OUT", "n": "OUT"}
BUCKET_CLUB = {"available": "FIT", "doubtful": "DOUBT", "returning": "DOUBT", "out": "OUT", "suspended": "OUT"}
_RANK = {"FIT": 3, "DOUBT": 2, "OUT": 1}            # the "fitter" bucket ranks higher


def bucket_fpl(status):
    return BUCKET_FPL.get(status)


def bucket_club(status):
    return BUCKET_CLUB.get(status)


def right_source(bucket_fpl_, bucket_club_, played):
    """'fpl' | 'club' | 'tie': if played the fitter bucket wins, if not the less fit one wins."""
    if bucket_fpl_ == bucket_club_:
        return "tie"
    fpl_fitter = _RANK[bucket_fpl_] > _RANK[bucket_club_]
    return "fpl" if fpl_fitter == bool(played) else "club"


def _utc(dt):
    return dt.replace(tzinfo=UTC) if dt.tzinfo is None else dt.astimezone(UTC)


def fpl_state_at(snapshots, deadline):
    """(snapshot time, {element_id: (status, chance_next)}) from the newest raw snapshot at or before
    the deadline; None when the archive has no snapshot that early (never a later one)."""
    key, boot = snapshots.get(_utc(deadline))
    if key == "always":
        ts = _utc(deadline)
    else:
        ts = _utc(datetime.fromisoformat(key))
    if ts > _utc(deadline):
        return None
    state = {}
    for e in boot.get("elements") or []:
        chance = e.get("chance_of_playing_next_round")
        state[int(e["id"])] = (e.get("status"), int(chance) if chance is not None else None)
    return ts, state


def build_comparisons(conn, gw, deadline, snapshots):
    """One row per player with a claim inside (deadline - 7 days, deadline], as of the deadline.
    Returns the number of rows inserted (existing (gw, element) rows are kept)."""
    deadline = _utc(deadline)
    got = fpl_state_at(snapshots, deadline)
    if got is None:
        return 0
    snap_ts, state = got
    with conn.cursor() as cur:
        cur.execute("SELECT DISTINCT ON (element_id) id, element_id, status, item_published_at, item_fetched_at FROM availability_claims "
                    "WHERE item_fetched_at <= %s AND item_fetched_at > %s ORDER BY element_id, item_fetched_at DESC, id DESC",
                    (deadline, deadline - WINDOW))
        claims = cur.fetchall()
        n = 0
        for cid, element, status, pub, fetched in claims:
            if element not in state:
                continue
            fstatus, fchance = state[element]
            bf, bc = bucket_fpl(fstatus), bucket_club(status)
            cur.execute("INSERT INTO availability_comparisons (gw, deadline, element_id, fpl_status, fpl_chance_next_round, fpl_snapshot_time, "
                        "claim_id, club_status, claim_published_at, claim_fetched_at, bucket_fpl, bucket_club, agree) "
                        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) ON CONFLICT (gw, element_id) DO NOTHING RETURNING id",
                        (gw, deadline, element, fstatus, fchance, snap_ts, cid, status, pub, fetched, bf, bc,
                         (bf == bc) if bf is not None and bc is not None else None))
            if cur.fetchone() is not None:
                n += 1
    conn.commit()
    return n


def results_for_gw(gw, path=None):
    """{element_id: {minutes, started}} from the history parquet for one gameweek (minutes summed over the
    gameweek's fixtures, started = any start), or None when the file or the gameweek is not there."""
    import pandas as pd
    p = Path(path) if path else HISTORY
    if not p.exists():
        return None
    df = pd.read_parquet(p)
    col = "GW" if "GW" in df.columns else "round"
    g = df[df[col] == gw]
    if g.empty:
        return None
    out = {}
    for element, grp in g.groupby("element"):
        started = bool((grp["starts"].fillna(0) > 0).any()) if "starts" in grp.columns else None
        out[int(element)] = {"minutes": int(grp["minutes"].fillna(0).sum()), "started": started}
    return out


def fill_outcomes(conn, gw, results):
    """Fill minutes / started / played / right_source for the gameweek's rows that have no outcome yet
    and whose player is in results. Returns the number of rows filled."""
    with conn.cursor() as cur:
        cur.execute("SELECT id, element_id, bucket_fpl, bucket_club FROM availability_comparisons WHERE gw = %s AND outcome_filled_at IS NULL "
                    "ORDER BY element_id", (gw,))
        rows = cur.fetchall()
        n = 0
        for rid, element, bf, bc in rows:
            r = results.get(element)
            if r is None:
                continue
            played = int(r["minutes"] or 0) > 0
            rs = right_source(bf, bc, played) if bf is not None and bc is not None else None
            cur.execute("UPDATE availability_comparisons SET minutes = %s, started = %s, played = %s, outcome_filled_at = now(), right_source = %s "
                        "WHERE id = %s", (int(r["minutes"] or 0), r.get("started"), played, rs, rid))
            n += 1
    conn.commit()
    return n


def passed_deadlines(events, now):
    out = []
    for e in events or []:
        try:
            dl = _utc(datetime.fromisoformat(str(e["deadline_time"]).replace("Z", "+00:00")))
        except (KeyError, ValueError):
            continue
        if dl <= now:
            out.append((int(e["id"]), dl))
    return sorted(out)


def update_conflict_log(conn, *, snapshots=None, events=None, results_loader=None, now=None, log=print):
    """Build comparisons for every passed deadline that lacks them; fill outcomes where results exist.
    Idempotent. Returns {"built": {gw: rows}, "filled": {gw: rows}}."""
    now = _utc(now) if now is not None else datetime.now(UTC)
    if snapshots is None or events is None:
        import sys
        eval_dir = str(REPO / "eval")                 # relevance.load_context imports poll_availability from eval/
        if eval_dir not in sys.path:
            sys.path.insert(0, eval_dir)
        idx, ev, _ = rv.load_context()
        snapshots = snapshots or idx
        events = events if events is not None else ev
    results_loader = results_loader or results_for_gw
    built, filled = {}, {}
    for gw, deadline in passed_deadlines(events, now):
        with conn.cursor() as cur:
            cur.execute("SELECT count(*), count(*) FILTER (WHERE outcome_filled_at IS NULL) FROM availability_comparisons WHERE gw = %s", (gw,))
            have, open_rows = cur.fetchone()
        if have == 0:
            n = build_comparisons(conn, gw, deadline, snapshots)
            if n:
                built[gw] = n
                open_rows = n
        if open_rows:
            results = results_loader(gw)
            if results:
                n = fill_outcomes(conn, gw, results)
                if n:
                    filled[gw] = n
    log(f"conflict_log: built {built or 'nothing'}, outcomes filled {filled or 'nothing'} (as of {now:%Y-%m-%dT%H:%M:%SZ})")
    return {"built": built, "filled": filled}
