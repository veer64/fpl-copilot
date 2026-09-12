# squad_store.py -- the user's squad as VERSIONED ROWS in Postgres
# (master plan section 1.4: "squad state as versioned rows, not a global";
# section 5.4: get_my_squad / set_my_squad read and write it).
#
# WHY THIS EXISTS
# Every solve the app has ever served was a free pick: the best fifteen from
# 100.0 as if from scratch. Nothing recorded what squad the user actually
# holds, so the six-week transfer MIP (squad/transfer_mip.py -- built,
# parity-proven, never run live), hit accounting, chip advice against a real
# squad, and lock/ban through a tool all had nothing to read. This table is
# that record. The squad is HYPOTHETICAL (not a real FPL entry) by decision
# taken 2026-09-12; it is seeded from the GW3 production solve (run_id 4)
# priced at GW4 and then carried forward by transfers.
#
# THE TABLE -- squad_versions -- IS APPEND-ONLY, BY CONSTRUCTION
#   * a change writes a NEW row and flips the previous row's is_active to
#     false; nothing else about an existing row ever changes;
#   * a trigger refuses DELETE and refuses any UPDATE that touches a column
#     other than is_active, or that turns is_active back ON. "Undo" is a new
#     row that copies an earlier squad_json (and says so in `note`) -- the
#     history stays linear and every state the user ever held is a row;
#   * a partial unique index allows at most ONE active row per user, so a
#     read is unambiguous or it raises -- never a guess between two candidates.
# The plan calls this the anti-rewrite insurance; it also gives undo and an
# audit trail for free. user_id exists from day one (always 1 for now);
# season is a column because gw alone is ambiguous across seasons.
#
# squad_json (JSONB) -- the document a row holds. Prices are in TENTHS of a
# million throughout (55 = 5.5m), the same unit as players_live.price_tenths
# and squad/squad_state.py. purchase_price is what was PAID, never the current
# price: FPL's sell rule (purchase + half the rise rounded down; falls in full)
# lives in squad_state.sell_price and is the only implementation.
#
#   {
#     "schema": 1,
#     "season": "2026-27",
#     "players": [                              -- exactly 15; 2 GK / 5 DEF / 5 MID / 3 FWD
#       {"element": 411, "name": "Erling Haaland", "position": "FWD",
#        "team": "Man City", "purchase_price": 155,
#        "role": "CAPTAIN",                     -- CAPTAIN | VICE | start | bench
#        "bench_order": null},                  -- 1..4 for bench rows, null otherwise
#       ...
#     ],
#     "bank": 4,                                -- tenths
#     "free_transfers": 1,
#     "total_points": 0,
#     "provenance": {...}                       -- free-form: where this version came from
#   }
#
# The DDL below is the schema of record. It is applied to the server database
# by piping exactly this string through psql (`python squad_store.py
# --print-ddl`) or by ensure_schema(conn); the laptop has no Postgres, so
# nothing here is exercised locally except by the pure-Python helpers' tests.

import sys

import db_write

DDL = """
CREATE TABLE IF NOT EXISTS squad_versions (
    version_id  SERIAL PRIMARY KEY,
    user_id     INT         NOT NULL DEFAULT 1,
    season      TEXT        NOT NULL,
    gw          INT         NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    squad_json  JSONB       NOT NULL,
    is_active   BOOLEAN     NOT NULL DEFAULT TRUE,
    supersedes  INT         REFERENCES squad_versions(version_id),
    note        TEXT
);

-- at most one active squad per user: a read is unambiguous or it raises
CREATE UNIQUE INDEX IF NOT EXISTS ux_squad_versions_one_active
    ON squad_versions (user_id) WHERE is_active;

-- append-only, enforced: no DELETE; the only UPDATE allowed is is_active
-- true -> false on the row being superseded. Undo = a new row.
CREATE OR REPLACE FUNCTION squad_versions_append_only() RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'squad_versions is append-only: DELETE refused'
            USING DETAIL = 'version_id ' || OLD.version_id;
    END IF;
    IF NEW.version_id IS DISTINCT FROM OLD.version_id
       OR NEW.user_id    IS DISTINCT FROM OLD.user_id
       OR NEW.season     IS DISTINCT FROM OLD.season
       OR NEW.gw         IS DISTINCT FROM OLD.gw
       OR NEW.created_at IS DISTINCT FROM OLD.created_at
       OR NEW.squad_json IS DISTINCT FROM OLD.squad_json
       OR NEW.supersedes IS DISTINCT FROM OLD.supersedes
       OR NEW.note       IS DISTINCT FROM OLD.note THEN
        RAISE EXCEPTION 'squad_versions is append-only: only is_active may change'
            USING DETAIL = 'version_id ' || OLD.version_id;
    END IF;
    IF NOT OLD.is_active AND NEW.is_active THEN
        RAISE EXCEPTION 'squad_versions: a superseded version cannot be re-activated; write a new row'
            USING DETAIL = 'version_id ' || OLD.version_id;
    END IF;
    RETURN NEW;
END
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_squad_versions_append_only ON squad_versions;
CREATE TRIGGER trg_squad_versions_append_only
    BEFORE UPDATE OR DELETE ON squad_versions
    FOR EACH ROW EXECUTE FUNCTION squad_versions_append_only();
"""


def ensure_schema(conn):
    """Create squad_versions, its one-active index and its append-only trigger
    if they do not exist. Idempotent. Call with NO query parameters (the DDL
    contains no psycopg2 placeholders and must not be interpolated)."""
    with conn.cursor() as cur:
        cur.execute(DDL)
    conn.commit()


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if argv == ["--print-ddl"]:
        sys.stdout.write(DDL)
        return 0
    if argv == ["--init"]:
        conn = db_write.connect()
        try:
            ensure_schema(conn)
        finally:
            conn.close()
        print("squad_versions schema ensured")
        return 0
    print("usage: python squad_store.py --print-ddl | --init", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
