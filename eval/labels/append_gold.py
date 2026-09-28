"""Append the user's labels from a weekly relevance report to the gold set (Part 9, 2026-09-28).

    uv run python eval/labels/append_gold.py eval/reports/relevance_gw6.md --gw 6

Reads every "### Item <id>" block of the report; an item whose RELEVANT and CURRENT lines are
both y/n is appended to eval/labels/relevance_gold_v1_labels.csv with the gameweek recorded
(subset review_gw<N>, gw <N>, original = final, adjudicated n); blank or non-y/n items are
skipped and listed; items already in the CSV are never duplicated. No article text is written:
the CSV holds ids, url, headline and the labels only.
"""
import argparse
import csv
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "eval"))
CSV_PATH = REPO / "eval" / "labels" / "relevance_gold_v1_labels.csv"
FIELDS = ["item_id", "source", "url", "headline", "gold_relevant_original", "gold_current_original", "gold_relevant_final",
          "gold_current_final", "adjudicated", "note", "subset", "gw"]


def parse_report(text):
    """{item id: {"relevant": True/False/None, "current": ..., "note": str}} from the report's blocks."""
    out = {}
    blocks = re.split(r"^### Item (\d+)\s*$", text, flags=re.M)
    for k in range(1, len(blocks), 2):
        iid, body = int(blocks[k]), blocks[k + 1]
        got = {}
        for field in ("RELEVANT", "CURRENT"):
            m = re.search(rf"^{field} \(y/n\):\s*(.*?)\s*$", body, flags=re.M)
            val = (m.group(1) if m else "").strip().lower()
            got[field] = True if val in ("y", "yes") else False if val in ("n", "no") else None
        note = re.search(r"^NOTE:\s*(.*?)\s*$", body, flags=re.M)
        out[iid] = {"relevant": got["RELEVANT"], "current": got["CURRENT"], "note": note.group(1) if note else ""}
    return out


def append_labels(conn, report_path, csv_path, gw):
    """Append the labelled items of `report_path` to `csv_path`. Returns {added, skipped_blank, skipped_existing}."""
    labels = parse_report(Path(report_path).read_text(encoding="utf-8"))
    csv_path = Path(csv_path)
    existing, rows = set(), []
    if csv_path.exists():
        with csv_path.open(encoding="utf-8", newline="") as f:
            rows = list(csv.DictReader(f))
        existing = {int(r["item_id"]) for r in rows}
        header = list(rows[0].keys()) if rows else FIELDS
        missing = [f for f in FIELDS if f not in header]
        assert not missing, f"{csv_path} lacks columns {missing}"          # extra columns (adjudication rounds, excluded) are kept
    else:
        header = FIELDS
    result = {"added": [], "skipped_blank": [], "skipped_existing": []}
    todo = []
    for iid in sorted(labels):
        lab = labels[iid]
        if lab["relevant"] is None or lab["current"] is None:
            result["skipped_blank"].append(iid)
        elif iid in existing:
            result["skipped_existing"].append(iid)
        else:
            todo.append(iid)
    if todo:
        with conn.cursor() as cur:
            cur.execute("SELECT id, source, url, headline FROM news_items WHERE id = ANY(%s)", (todo,))
            info = {r[0]: r for r in cur.fetchall()}
        new_file = not csv_path.exists() or not csv_path.stat().st_size
        with csv_path.open("a", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=header)
            if new_file:
                w.writeheader()
            for iid in todo:
                if iid not in info:
                    continue
                lab = labels[iid]
                rel, cu = "y" if lab["relevant"] else "n", "y" if lab["current"] else "n"
                row = {k: "" for k in header}
                row.update({"item_id": iid, "source": info[iid][1], "url": info[iid][2], "headline": info[iid][3],
                            "gold_relevant_original": rel, "gold_current_original": cu, "gold_relevant_final": rel, "gold_current_final": cu,
                            "adjudicated": "n", "note": lab["note"], "subset": f"review_gw{int(gw)}", "gw": int(gw)})
                for k in ("gold_relevant_adj1",):
                    if k in row: row[k] = rel
                for k in ("gold_current_adj1",):
                    if k in row: row[k] = cu
                for k in ("excluded", "adjudicated2"):
                    if k in row: row[k] = "n"
                w.writerow(row)
                result["added"].append(iid)
    return result


def main():
    import db_write
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("report")
    ap.add_argument("--gw", type=int, required=True)
    ap.add_argument("--csv", default=str(CSV_PATH))
    a = ap.parse_args()
    conn = db_write.connect()
    try:
        r = append_labels(conn, a.report, a.csv, a.gw)
    finally:
        conn.close()
    print(f"added {len(r['added'])} item(s) {r['added']}; skipped blank {r['skipped_blank']}; already present {r['skipped_existing']}")


if __name__ == "__main__":
    main()
