"""Prompt R3 (16 Nov 2026): the seeded player pool the code-built-answer tests read -- its own database (fpl_r3_test), so every
number is the test's own and the "whole-pool query" each test checks against is a query over exactly these rows.

48 players at 6 clubs with predictions for GW11-16 from ONE successful build (run 1, config baseline):
  - a double gameweek (Alpha, GW12: two fixtures, both counted in the row's points) and a blank (Bravo, GW13: no row at all);
  - level totals and level prices, so every tie-break is exercised;
  - flagged players (doubtful with FPL's note, injured, unavailable) and a player with no price;
  - players under and over a 50% chance of starting the first gameweek (the "weakest for their price" group rule);
  - one player in players_live with NO prediction row (never part of the pool).
e_points are REAL in the table, as in production, and carry two decimals here so no sum sits on a rounding tie."""
import os
from datetime import datetime, timezone

import pytest

TEST_DB = "fpl_r3_test"
RUN_ID = 1
GWS = [11, 12, 13, 14, 15, 16]
FIRST_GW = 11
CLUBS = ["Alpha", "Bravo", "Charlie", "Delta", "Echo", "Foxtrot"]
SHORTS = {"Alpha": "ALP", "Bravo": "BRA", "Charlie": "CHA", "Delta": "DEL", "Echo": "ECH", "Foxtrot": "FOX"}
BUILT = datetime(2026, 11, 11, 11, 1, 48, tzinfo=timezone.utc)
FLAG_AT = datetime(2026, 11, 11, 16, 37, 6, tzinfo=timezone.utc)
NEXT_UPDATE = "the nightly update, Thursday 2026-11-19 11:00 UTC"


def _players():
    """[(element, name, position, club, price_tenths)] -- 8 per club: 1 GK, 3 DEF, 2 MID, 2 FWD."""
    out, e = [], 100
    shape = [("GK", 1), ("DEF", 3), ("MID", 2), ("FWD", 2)]
    for c, club in enumerate(CLUBS):
        for pos, n in shape:
            for k in range(n):
                e += 1
                base = {"GK": 45, "DEF": 46, "MID": 62, "FWD": 70}[pos]
                price = base + 3 * ((c + k) % 4) + (5 if (pos == "FWD" and c == 0 and k == 0) else 0)
                if e == 113:
                    price = 62                                   # level with 105 on price (and on points): the name decides
                out.append((e, f"{club[:3]} {pos}{k + 1}", pos, club, price))
    return out


PLAYERS = _players()
NO_PREDICTION = (999, "Nobody Unrated", "MID", "Echo", 50)      # in players_live, in no build: never in the pool
NO_PRICE = 148                                                    # the last player: price NULL (never ranked)


def e_points(element, gw):
    """A fixed, two-decimal prediction for (player, gameweek); None for the blank (Bravo's players in GW13)."""
    row = next(p for p in PLAYERS if p[0] == element)
    club_i = CLUBS.index(row[3])
    if row[3] == "Bravo" and gw == 13:
        return None
    seed = (element * 37 + gw * 101 + club_i * 13) % 500
    pts = round(0.4 + seed / 100.0, 2)                           # 0.40 .. 5.39
    if row[3] == "Alpha" and gw == 12:                           # the double: both fixtures in the one row
        pts = round(pts * 2, 2)
    if element in (104, 112):                                    # two level totals at different prices: the tie-break
        pts = 3.21
    if element in (105, 113):                                    # level totals AND level prices: the name decides
        pts = 2.5
    return pts


def p_start(element, gw):
    return round(((element * 53 + gw * 7) % 100) / 100.0, 2)     # 0.00 .. 0.99, fixed per (player, gameweek)


def calendar():
    """{(club, gw): [{"opponent", "home"}]}: one fixture a gameweek, Alpha two in GW12, Bravo none in GW13."""
    cal = {}
    for g in GWS:
        for i, club in enumerate(CLUBS):
            if club == "Bravo" and g == 13:
                continue
            opp = CLUBS[(i + g) % len(CLUBS)] if CLUBS[(i + g) % len(CLUBS)] != club else CLUBS[(i + g + 1) % len(CLUBS)]
            cal[(club, g)] = [{"opponent": opp, "home": (i + g) % 2 == 0}]
        if g == 12:
            cal[("Alpha", 12)].append({"opponent": "Foxtrot", "home": False})
    return cal


FLAGS = {106: ("d", 75, "Knock - 75% chance of playing"), 121: ("i", 0, "Hamstring injury - Expected back 05 Dec"),
         130: ("u", 0, "Has joined Elsewhere FC permanently"), 109: ("d", 50, None)}


@pytest.fixture
def pool_db(monkeypatch):
    """The seeded database, with model_tools pointed at it: the next deadline is GW11, the names are players_live's, the
    calendar and the short names are the seed's. Yields a connection (autocommit) for the test's own whole-pool queries."""
    import psycopg2

    import db_write
    import model_tools as mt
    monkeypatch.setenv("DB_NAME", "postgres")
    try:
        admin = db_write.connect()
    except psycopg2.OperationalError as e:
        pytest.skip(f"no local Postgres: {str(e).splitlines()[0]}")
    admin.autocommit = True
    with admin.cursor() as cur:
        cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (TEST_DB,))
        if cur.fetchone() is None:
            cur.execute(f"CREATE DATABASE {TEST_DB}")
    admin.close()
    monkeypatch.setenv("DB_NAME", TEST_DB)
    c = db_write.connect()
    db_write.ensure_schema(c)
    with c.cursor() as cur:
        cur.execute("TRUNCATE model_predictions, model_picks, model_runs RESTART IDENTITY CASCADE")
        cur.execute("DELETE FROM players_live")
        cur.execute("INSERT INTO model_runs (run_id, season, gw, started_at, finished_at, status, git_sha, kind) "
                    "VALUES (%s, '2026-27', %s, %s, %s, 'SUCCESS', 'r3seed', 'nightly')", (RUN_ID, FIRST_GW, BUILT, BUILT))
        for e, name, pos, club, price in PLAYERS + [NO_PREDICTION]:
            st, chance, news = FLAGS.get(e, ("a", None, None))
            cur.execute("INSERT INTO players_live (element, name, position, team, price_tenths, status, chance, news, updated_at) "
                        "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                        (e, name, pos, club, None if e == NO_PRICE else price, st, chance, news, FLAG_AT))
        for e, _name, _pos, _club, _price in PLAYERS:
            for g in GWS:
                pts = e_points(e, g)
                if pts is None:
                    continue
                cur.execute("INSERT INTO model_predictions (run_id, config, element, gw, cutoff, horizon_step, e_points, p_start) "
                            "VALUES (%s, 'baseline', %s, %s, %s, %s, %s, %s)", (RUN_ID, e, g, FIRST_GW, g - FIRST_GW, pts, p_start(e, g)))
    c.commit()
    c.autocommit = True
    cal = calendar()
    monkeypatch.setattr(mt, "_current_gw", lambda: FIRST_GW)
    monkeypatch.setattr(mt, "_web_names", lambda: {})
    monkeypatch.setattr(mt, "_club_short_names", lambda: dict(SHORTS))
    monkeypatch.setattr(mt, "_answer_calendar", lambda: cal)
    monkeypatch.setattr(mt, "_next_run", lambda: {"expected": None, "source": None, "words": NEXT_UPDATE, "deadline_day_runs": None})
    monkeypatch.setattr(mt, "_has_saved_squad", lambda user_id: True)
    yield c
    c.close()


def q(conn, sql, params=()):
    with conn.cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchall()


# The whole-pool query every ranking number is checked against: EVERY player with a prediction row in the build and a price,
# his points added over the span in SQL (numeric, 2 dp), in the answer's own order.
POOL_SQL = """
WITH pool AS (
    SELECT l.element, l.name, l.position, l.team, l.price_tenths,
           round(COALESCE(sum(p.e_points::float8) FILTER (WHERE p.gw = ANY(%(gws)s)), 0)::numeric, 2) AS total
    FROM players_live l JOIN model_predictions p ON p.element = l.element AND p.run_id = %(run)s AND p.config = 'baseline'
    WHERE l.price_tenths IS NOT NULL
    GROUP BY l.element, l.name, l.position, l.team, l.price_tenths)
SELECT element, name, position, team, price_tenths, total, round(total * 10 / price_tenths, 2) AS value FROM pool
"""


def table_rows(text):
    """The data rows of the FIRST markdown table in `text`, each a list of cell strings."""
    out, seen_sep = [], False
    for line in text.split("\n"):
        if line.startswith("|---"):
            if seen_sep:
                break
            seen_sep = True
            continue
        if seen_sep:
            if not line.startswith("|"):
                break
            out.append([c.strip() for c in line.strip().strip("|").split("|")])
    return out


def tables(text):
    """Every markdown table in `text`: [(header cells, [row cells])]."""
    out, lines, i = [], text.split("\n"), 0
    while i < len(lines):
        if lines[i].startswith("|") and i + 1 < len(lines) and lines[i + 1].startswith("|---"):
            head = [c.strip() for c in lines[i].strip().strip("|").split("|")]
            rows, j = [], i + 2
            while j < len(lines) and lines[j].startswith("|"):
                rows.append([c.strip() for c in lines[j].strip().strip("|").split("|")])
                j += 1
            out.append((head, rows))
            i = j
        else:
            i += 1
    return out
