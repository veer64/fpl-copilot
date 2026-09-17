"""In-image proof of the term columns: run the same idempotent ensure_schema the next write_run
runs, then read the catalogue -- the 24 columns exist, nullable, no default; existing rows are
NULL there (never backfilled); the table comment is set."""
import sys
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, "/app")
import db_write

conn = db_write.connect()
db_write.ensure_schema(conn)
with conn.cursor() as cur:
    cur.execute("""SELECT column_name, data_type, is_nullable, column_default
                   FROM information_schema.columns WHERE table_name = 'model_predictions'
                   ORDER BY ordinal_position""")
    cols = cur.fetchall()
    print(f"model_predictions has {len(cols)} columns:")
    for name, typ, nullable, default in cols:
        flag = " <- term" if name in db_write.TERM_COLS else ""
        print(f"  {name:18s} {typ:18s} nullable={nullable} default={default}{flag}")
    missing = [c for c in db_write.TERM_COLS if c not in {c[0] for c in cols}]
    print("missing term columns:", missing or "none")
    cur.execute("SELECT COUNT(*), COUNT(pts_goals), MAX(run_id) FROM model_predictions")
    n, n_terms, max_run = cur.fetchone()
    print(f"rows {n}, rows with pts_goals recorded {n_terms} (expected 0 until the first run after this deploy), max run_id {max_run}")
    cur.execute("SELECT obj_description('model_predictions'::regclass, 'pg_class')")
    print("table comment:", (cur.fetchone()[0] or "")[:160])
conn.close()
