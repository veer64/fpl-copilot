"""News batch 2 (Prompt H, 2026-10-30): the data changes for rows stored BEFORE the batch, one step at a time. A DRY RUN by
default (read only: prints the plan and writes it as JSON); --apply writes it. USER DECISION H2: production data changes
are applied in Saturday's deploy, after the code is live (ensure_schema adds fpl_news_added and duplicate_of first).

    python eval/news_batch2_apply.py --step dates      [--apply [--rechunk]]   # N2 FPL notes dated by their last text change
    python eval/news_batch2_apply.py --step duplicates [--apply]               # N3 existing club copies -> duplicate_of
    python eval/news_batch2_apply.py --step conflicts  [--apply] [--gw 7 8]    # N4 the 7-day article-date rule, per gameweek

Saturday order: dates (--apply --rechunk, so the chunks' "[FPL official | date]" header matches the new date: one Voyage
request per 128 texts), then duplicates, then conflicts (the rebuild reads both), then eval/backfill_relevance_v4.py.
Each step is idempotent: a second dry run after --apply plans nothing (conflicts: no row changes).

conflicts dry run: for every passed deadline that has rows (or --gw), the claim each player's row would carry under the new
rule against the stored row -- rows DROPPED (no claim from an article dated in the window), rows CHANGED (another claim),
the "too old to compare" claims -- from the database alone. --apply rebuilds those gameweeks with conflict_log
(rebuild_gameweek: as of each deadline, the newest raw snapshot at or before it, outcomes refilled).
"""
import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
for p in (str(REPO), str(REPO / "eval")):
    if p not in sys.path:
        sys.path.insert(0, p)
import db_write  # noqa: E402
import news_store as ns  # noqa: E402
import conflict_log as cl  # noqa: E402

UTC = timezone.utc


def _iso(v):
    return v.isoformat() if hasattr(v, "isoformat") else v


def step_dates(conn, apply=False, rechunk=False, log=print):
    plan = ns.fpl_redate_plan(conn)
    chunks = ns.redate_chunk_rows(conn, [p["id"] for p in plan])
    log(f"dates: {len(plan)} fpl row(s) re-dated by their last text change; {len(chunks)} chunk(s) carry the old date in their header")
    for p in plan:
        log(f"  #{p['id']} {p['guid']} v{p['version']} {p['headline']}: {_iso(p['old_published_at'])} ({p['old_date_source']}) -> "
            f"{_iso(p['new_published_at'])} ({p['new_date_source']}) | {(p['body'] or '')[:60]}")
    out = {"step": "dates", "n": len(plan), "chunks": len(chunks), "plan": plan}
    if apply:
        out["applied"] = ns.apply_fpl_redate(conn, plan, rechunk=rechunk, log=log)
        log(f"dates: APPLIED {out['applied']}")
    return out


def step_duplicates(conn, apply=False, log=print):
    rep = ns.duplicate_groups(conn)
    log(f"duplicates: {len(rep['merged'])} group(s) to merge ({sum(len(g['aliases']) for g in rep['merged'])} alias(es)); "
        f"{len(rep['not_merged'])} same-headline group(s) NOT merged")
    for g in rep["merged"]:
        log(f"  MERGE {g['kind']} first #{g['first']} aliases {g['aliases']} bodies_identical={g['bodies_identical']}")
        for it in g["items"]:
            log(f"      #{it['id']} {it['body_chars']} chars {_iso(it['fetched_at'])} {it['url']} | {it['headline'][:70]}")
    for g in rep["not_merged"]:
        log(f"  NOT MERGED {g['ids']} ({g['club']}) body chars {g['body_chars']}: {g['reason']} | {g['headline'][:70]}")
    out = {"step": "duplicates", **rep}
    if apply:
        out["applied"] = ns.apply_duplicates(conn, rep)
        log(f"duplicates: APPLIED {out['applied']}")
    return out


def conflict_diff(conn, gw, deadline):
    """{gw, deadline, rows_before, rows_after, dropped, changed, too_old}: the stored rows against the new rule's selection"""
    pv, m = cl._claim_version()
    with conn.cursor() as cur:
        cur.execute("SELECT c.element_id, c.claim_id, c.club_status, c.claim_published_at, c.claim_fetched_at, n.headline, n.duplicate_of "
                    "FROM availability_comparisons c JOIN availability_claims a ON a.id = c.claim_id JOIN news_items n ON n.id = a.news_item_id "
                    "WHERE c.gw = %s ORDER BY c.element_id", (gw,))
        before = {r[0]: r for r in cur.fetchall()}
        cur.execute(cl._SCORED_CLAIMS, (deadline, deadline - cl.WINDOW, pv, m))
        after = {r[1]: r for r in cur.fetchall()}
    dropped, changed = [], []
    for el, b in before.items():
        a = after.get(el)
        row = {"element_id": el, "claim_id": b[1], "club_status": b[2], "published_at": _iso(b[3]), "fetched_at": _iso(b[4]),
               "headline": b[5], "duplicate": b[6] is not None}
        if a is None:
            dropped.append(row)
        elif a[0] != b[1]:
            changed.append({**row, "new_claim_id": a[0], "new_status": a[2], "new_published_at": _iso(a[3])})
    added = sorted(set(after) - set(before))
    too_old = [{k: _iso(v) for k, v in t.items()} for t in cl.too_old_claims(conn, gw, deadline)]
    return {"gw": gw, "deadline": _iso(deadline), "rows_before": len(before), "rows_after": len(after), "dropped": dropped,
            "changed": changed, "added": added, "too_old": too_old}


def step_conflicts(conn, apply=False, gws=None, log=print):
    with conn.cursor() as cur:
        cur.execute("SELECT gw, deadline FROM availability_builds ORDER BY gw")
        builds = dict(cur.fetchall())
        cur.execute("SELECT DISTINCT gw, deadline FROM availability_comparisons ORDER BY gw")
        for g, d in cur.fetchall():
            builds.setdefault(g, d)
    todo = sorted(g for g in builds if gws is None or g in gws)
    diffs = []
    for gw in todo:
        d = conflict_diff(conn, gw, builds[gw])
        diffs.append(d)
        log(f"conflicts GW{gw} (deadline {d['deadline']}): rows {d['rows_before']} -> {d['rows_after']}; dropped {len(d['dropped'])}, "
            f"changed {len(d['changed'])}, added {len(d['added'])}; too old to compare {len(d['too_old'])}")
        for r in d["dropped"]:
            log(f"  DROPPED element {r['element_id']} claim {r['claim_id']} ({r['club_status']}) published {r['published_at']} "
                f"fetched {r['fetched_at']}{' [duplicate item]' if r['duplicate'] else ''} | {r['headline'][:70]}")
        for r in d["changed"]:
            log(f"  CHANGED element {r['element_id']} claim {r['claim_id']} ({r['club_status']}, published {r['published_at']}) -> "
                f"claim {r['new_claim_id']} ({r['new_status']}, published {r['new_published_at']}) | {r['headline'][:60]}")
    out = {"step": "conflicts", "gameweeks": diffs}
    if apply:
        idx, _, _ = cl.rv.load_context()
        out["applied"] = {}
        for d in diffs:
            if d["dropped"] or d["changed"] or d["added"]:
                out["applied"][d["gw"]] = cl.rebuild_gameweek(conn, d["gw"], builds[d["gw"]], idx)
        log(f"conflicts: APPLIED rebuilt {out['applied'] or 'nothing'}")
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--step", required=True, choices=("dates", "duplicates", "conflicts"))
    ap.add_argument("--apply", action="store_true", help="write the plan (default: dry run, read only)")
    ap.add_argument("--rechunk", action="store_true", help="dates: also rebuild and re-embed the re-dated items' chunks in place")
    ap.add_argument("--gw", type=int, nargs="*", help="conflicts: only these gameweeks")
    ap.add_argument("--json", default=None, help="write the plan / result here")
    a = ap.parse_args(argv)
    conn = db_write.connect()
    try:
        ns.ensure_schema(conn)
        if a.step == "dates":
            out = step_dates(conn, a.apply, a.rechunk)
        elif a.step == "duplicates":
            out = step_duplicates(conn, a.apply)
        else:
            out = step_conflicts(conn, a.apply, set(a.gw) if a.gw else None)
    finally:
        conn.close()
    out["mode"] = "apply" if a.apply else "dry_run"
    out["at"] = datetime.now(UTC).isoformat()
    if a.json:
        Path(a.json).write_text(json.dumps(out, indent=1, default=str, ensure_ascii=False), encoding="utf-8")
        print(f"written {a.json}")
    return out


if __name__ == "__main__":
    main()
