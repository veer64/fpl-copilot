"""
Seed the user's HYPOTHETICAL squad as GW4, version 1 (2026-09-12).

The fifteen are model_runs.run_id 4 -- the GW3 production solve, regenerated
post-leak-fix on e3d98af, baseline config -- priced at players_live as of
2026-09-11 21:42:31Z (every pick's price equalled its live price, verified on
the server before this script was written). It is seeded AS OF GW4, not
backdated to GW3: the GW3 deadline prices for GW1-2 were destroyed by the
weekly rebuild bug (fixed in e3d98af) and no longer exist.

purchase_price = the live price on the seed date, because a squad bought
today is bought at today's prices; bank = 100.0 - cost; one free transfer;
zero points. The arithmetic is squad_state.initial_squad_from_team -- the
one implementation of the money rules -- and the legality check is
squad_store.validate_document.

The laptop has no Postgres. This script therefore EMITS, and the SQL it emits
is what runs on the server, inside one transaction, with a cross-check that
refuses to insert unless every document row still matches run 4's picks
(element, position, role, bench order) and players_live's current price:

    uv run python eval/seed_squad_gw4.py --json   # the document
    uv run python eval/seed_squad_gw4.py --sql    # BEGIN; cross-check; INSERT; COMMIT

Run once. The cross-check also refuses if squad_versions is not empty.
"""

import json
import sys
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[1]
for p in (str(REPO), str(REPO / "squad")):
    if p not in sys.path:
        sys.path.insert(0, p)

import db_write                                            # noqa: E402
import squad_store                                         # noqa: E402
from squad_state import initial_squad_from_team            # noqa: E402

SEASON = "2026-27"
GW = 4
USER_ID = 1
SOURCE_RUN_ID = 4
SOURCE_CONFIG = "baseline"
SOURCE_GIT = "e3d98afdd"
PRICED_AT = "2026-09-11T21:42:31Z"      # players_live max(updated_at) when verified

# element, name, position, team, price in TENTHS, role, bench_order
SPEC = [
    (82,  "Caoimhín Kelleher",    "GK",  "Brentford", 50,  "start",   None),
    (250, "Bernd Leno",           "GK",  "Fulham",    45,  "bench",   1),
    (84,  "Nathan Collins",       "DEF", "Brentford", 55,  "start",   None),
    (388, "Marc Guéhi",           "DEF", "Man City",  60,  "start",   None),
    (115, "Maxim De Cuyper",      "DEF", "Brighton",  47,  "start",   None),
    (8,   "Riccardo Calafiori",   "DEF", "Arsenal",   57,  "start",   None),
    (88,  "Michael Kayode",       "DEF", "Brentford", 46,  "bench",   2),
    (367, "Cody Gakpo",           "MID", "Liverpool", 71,  "start",   None),
    (398, "Phil Foden",           "MID", "Man City",  70,  "VICE",    None),
    (427, "Bryan Mbeumo",         "MID", "Man Utd",   80,  "start",   None),
    (127, "Diego Gómez Amarilla", "MID", "Brighton",  50,  "bench",   3),
    (290, "Regan Slater",         "MID", "Hull City", 45,  "bench",   4),
    (411, "Erling Haaland",       "FWD", "Man City",  155, "CAPTAIN", None),
    (379, "Alexander Isak",       "FWD", "Liverpool", 90,  "start",   None),
    (26,  "Kai Havertz",          "FWD", "Arsenal",   75,  "start",   None),
]
NOTE = ("seed: GW3 production solve (model_runs.run_id 4, baseline, e3d98afdd) "
        "priced at players_live on 2026-09-11; hypothetical squad, not a real FPL entry; "
        "seeded as of GW4, not backdated")


def build_document():
    team = pd.DataFrame(SPEC, columns=["element", "name", "position", "team", "value",
                                       "role", "bench_order"])
    state = initial_squad_from_team(team)          # purchase_price = value; bank = 1000 - spent
    provenance = {
        "kind": "seed",
        "hypothetical": True,
        "seeded_from": {"model_runs.run_id": SOURCE_RUN_ID, "config": SOURCE_CONFIG,
                        "gw_solved": 3, "git_sha": SOURCE_GIT},
        "priced_from": f"players_live.price_tenths as of {PRICED_AT}",
        "why_gw4": "GW1-2 deadline prices no longer exist (weekly rebuild bug, fixed e3d98af); "
                   "seeded as of GW4, not backdated",
        "created_by": f"eval/seed_squad_gw4.py @ {db_write.git_sha() or 'unknown'}",
    }
    return squad_store.document(state.squad, state.bank, state.free_transfers,
                                state.total_points, SEASON, provenance)


def emit_sql(doc):
    payload = json.dumps(doc, ensure_ascii=False, sort_keys=True)
    assert "$json$" not in payload
    note = NOTE.replace("'", "''")
    return f"""BEGIN;
CREATE TEMP TABLE seed_doc ON COMMIT DROP AS SELECT $json${payload}$json$::jsonb AS doc;

-- Cross-check: every document row must still be run {SOURCE_RUN_ID}'s {SOURCE_CONFIG} pick
-- with the same position, role and bench order, and its purchase_price must equal
-- the CURRENT players_live price. Refuse otherwise. Refuse if the table is not empty.
DO $$
DECLARE n_doc int; n_match int; n_rows int;
BEGIN
    SELECT count(*) INTO n_doc FROM jsonb_array_elements((SELECT doc FROM seed_doc)->'players');
    SELECT count(*) INTO n_match
      FROM jsonb_to_recordset((SELECT doc FROM seed_doc)->'players')
           AS d(element int, position text, purchase_price int, role text, bench_order int)
      JOIN model_picks p ON p.run_id = {SOURCE_RUN_ID} AND p.config = '{SOURCE_CONFIG}'
           AND p.element = d.element AND p.position = d.position AND p.role = d.role
           AND p.bench_order IS NOT DISTINCT FROM d.bench_order
      JOIN players_live l ON l.element = d.element AND l.price_tenths = d.purchase_price;
    IF n_doc <> {squad_store.SQUAD_SIZE} OR n_match <> {squad_store.SQUAD_SIZE} THEN
        RAISE EXCEPTION 'seed cross-check failed: % of % document rows match run {SOURCE_RUN_ID} picks and current players_live prices', n_match, n_doc;
    END IF;
    SELECT count(*) INTO n_rows FROM squad_versions;
    IF n_rows <> 0 THEN
        RAISE EXCEPTION 'squad_versions already holds % row(s); refusing to seed', n_rows;
    END IF;
END $$;

-- the guard probe on 2026-09-12 consumed sequence values on the empty table
ALTER SEQUENCE squad_versions_version_id_seq RESTART WITH 1;

INSERT INTO squad_versions (user_id, season, gw, squad_json, is_active, supersedes, note)
VALUES ({USER_ID}, '{SEASON}', {GW}, (SELECT doc FROM seed_doc), TRUE, NULL, '{note}')
RETURNING version_id, user_id, season, gw, created_at, is_active, supersedes;
COMMIT;
"""


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    # The emitted SQL/JSON carries accented names (Kelleher, Guehi, Gomez) and
    # runs on a UTF-8 Postgres; a Windows console defaults to cp1252 and the
    # first attempt (2026-09-12) failed in psql with "invalid byte sequence
    # for encoding UTF8". Emit UTF-8 whatever the console says.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    doc = build_document()
    if argv == ["--json"]:
        sys.stdout.write(json.dumps(doc, ensure_ascii=False, indent=1, sort_keys=True) + "\n")
        return 0
    if argv == ["--sql"]:
        sys.stdout.write(emit_sql(doc))
        return 0
    print("usage: python eval/seed_squad_gw4.py --json | --sql", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
