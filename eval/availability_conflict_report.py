"""The weekly availability conflict report (Piece 9, 2026-10-01): for one gameweek, club news against
FPL's official flag as of the deadline, with outcomes and who was right. Reads availability_comparisons
(conflict_log.py builds it) and writes eval/reports/availability_gw<N>.md (gitignored: evidence text
stays out of git). Record and measure only (D9).

Usage:
    uv run python eval/availability_conflict_report.py --gw 5
"""
import argparse
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "eval"))
import db_write  # noqa: E402

LIMITATIONS = ("LIMITATIONS: Not playing can mean rotation, not injury; a fit player left out counts as 'not played'. "
               "FPL's flag is read as of the deadline from the raw archive; the club claim is the newest one fetched in the "
               "7 days before the deadline; the laptop's club data mostly comes from replays and old seeds.")


def _fmt(dt):
    return f"{dt:%Y-%m-%d %H:%M}Z" if dt else "none"


def build_report(conn, gw):
    with conn.cursor() as cur:
        cur.execute("SELECT c.element_id, c.deadline, c.fpl_status, c.fpl_chance_next_round, c.fpl_snapshot_time, c.club_status, "
                    "c.claim_published_at, c.claim_fetched_at, c.bucket_fpl, c.bucket_club, c.agree, c.minutes, c.started, c.played, "
                    "c.right_source, a.return_hint, a.basis, a.evidence, n.club, n.headline, n.source, a.id "
                    "FROM availability_comparisons c JOIN availability_claims a ON a.id = c.claim_id JOIN news_items n ON n.id = a.news_item_id "
                    "WHERE c.gw = %s ORDER BY c.agree, c.element_id", (gw,))
        rows = cur.fetchall()
        names = {}
        if _has_players_live(cur):
            cur.execute("SELECT element, name FROM players_live")
            names = dict(cur.fetchall())
    agree = sum(1 for r in rows if r[10] is True)
    disagree = sum(1 for r in rows if r[10] is False)
    tally = Counter(r[14] for r in rows if r[10] is False and r[14])
    out = [f"# Availability conflict log, GW{gw}", "",
           f"Generated {datetime.now(timezone.utc):%Y-%m-%d %H:%MZ}. Rows {len(rows)}: agree {agree}, disagree {disagree}, "
           f"unbucketed {len(rows) - agree - disagree}. Deadline {_fmt(rows[0][1]) if rows else 'n/a'}.", "",
           f"Who was right across disagreements with an outcome: {dict(tally) or 'none yet'}.", "", LIMITATIONS, ""]
    if disagree:
        out += ["## Disagreements", ""]
        for r in rows:
            if r[10] is not False:
                continue
            (el, dl, fs, fc, fsnap, cs, cpub, cfet, bf, bc, _, mins, started, played, rs, hint, basis, ev, club, head, src, cid) = r
            name = names.get(el, f"element {el}")
            outcome = "no outcome yet" if played is None else f"minutes {mins}, started {started}, played {played}"
            out += [f"- **{name}** ({club or src}): FPL {fs} ({fc if fc is not None else 'no chance figure'}%) as of {_fmt(fsnap)} -> {bf}; "
                    f"club says {cs}{' (' + hint + ')' if hint else ''} by {basis} -> {bc}; claim {cid} from \"{head}\" "
                    f"published {_fmt(cpub)}, fetched {_fmt(cfet)}; evidence: \"{ev}\"; outcome: {outcome}; right_source: {rs or 'pending'}"]
        out.append("")
    if agree:
        out += ["## Agreements", ""]
        for r in rows:
            if r[10] is True:
                out.append(f"- {names.get(r[0], f'element {r[0]}')} ({r[18] or r[20]}): FPL {r[2]} -> {r[8]}, club {r[5]} -> {r[9]}; outcome: "
                           + ("pending" if r[13] is None else f"played {r[13]}, minutes {r[11]}"))
        out.append("")
    return "\n".join(out)


def _has_players_live(cur):
    cur.execute("SELECT to_regclass('players_live')")
    return cur.fetchone()[0] is not None


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--gw", type=int, required=True)
    a = ap.parse_args()
    conn = db_write.connect()
    try:
        text = build_report(conn, a.gw)
    finally:
        conn.close()
    out = REPO / "eval" / "reports" / f"availability_gw{a.gw}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    print(text)
    print(f"\nwritten {out}")


if __name__ == "__main__":
    main()
