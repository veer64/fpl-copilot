"""The Chat page's team card (Prompt W4 Data 4, 2026-11-06): GET /me/teams/{id}/card, and the Player objects the squad-change
preview draws on the pitch (turn_extras).

ONE endpoint, any of the user's teams (active or not: opening a chat is read-only -- checkpoint C1), one database connection
per request, FPL read through fpl_import's single-flight cache: bootstrap-static (BOOTSTRAP_TTL_S), fixtures/?future=1 and
entry/{id}/history/ (CACHE_TTL_S). fpl_live is true only when every FPL answer was fresh (fetched, or within its TTL). When
FPL fails the last cached copy is served past its TTL with fpl_live false (C8); with no copy at all the bootstrap falls back
to the newest local snapshot (the poller's archive, on the laptop and on the server volume), and after that to the saved
squad with price / flag from players_live (form, next fixture, FPL estimate and chips then null).

THE PLAYER OBJECT {slot, id, short_name, full_name, club, position, price, form, role, next, flag, pred, in_squad}:
slot 1-15 (XI in formation order GK, DEF, MID, FWD, the document's order within a line; bench 12-15 = bench order 1-4);
short_name = FPL's web_name; club = the short code; price = now_cost / 10 (else players_live); form = FPL's "form" (USER
DECISION: AVG PTS); role "C" / "VC" / null; next {opp, home, n} = the club's first fixture of next_gw (n fixtures that week;
null for a blank); flag {chance, news, news_date} when FPL's status is not "a" or the chance is below 100 (news_date =
news_added's day); pred {points, source}: "ours" = the production frame's row for next_gw (model_tools._load_pool), else FPL's
ep_next as "fpl_est", else null. Inside a /chat turn (the preview) nothing is fetched: the caches and the local snapshot only.

chips: FPL's history chips[] of the CURRENT half (GW1-19 when next_gw <= 19, else GW20-38), WC / FH / BB / TC in that order.
team_value = the fifteen at current prices (FPL's "squad value"; the bank apart); free_transfers derived to next_gw as
/me/squad does (squad_store.free_transfers_at)."""
import gzip
import json
from datetime import datetime, timezone

import psycopg2
import psycopg2.extras

import db_write
import fpl_import

FIXTURES_PATH = "fixtures/?future=1"
CHIPS = (("wildcard", "WC", "Wildcard"), ("freehit", "FH", "Free Hit"), ("bboost", "BB", "Bench Boost"), ("3xc", "TC", "Triple Captain"))
POS_ORDER = {"GK": 0, "DEF": 1, "MID": 2, "FWD": 3}
POSITIONS = {1: "GK", 2: "DEF", 3: "MID", 4: "FWD"}
PLAYER_KEYS = ("slot", "id", "short_name", "full_name", "club", "position", "price", "form", "role", "next", "flag", "pred", "in_squad")
_connect = db_write.connect


class TeamNotFound(Exception):
    """The user has no such team."""


def clock():
    return fpl_import.clock()


def _iso(dt):
    import threads
    return threads.iso(dt)


# ---- FPL (cached; never a fetch inside a turn) ------------------------------------------------------------------------------

def _fetch(path, ttl, get=None, allow_fetch=True):
    """(body, fresh): the cached-or-fetched body, else the last copy (stale), else None."""
    if not allow_fetch:
        body = fpl_import.peek(path, ttl)
        if body is not None:
            return body, True
        return fpl_import.last_copy(path)[0], False
    try:
        return fpl_import.cached_json(path, ttl, get=get), True
    except (fpl_import.FplUnavailable, fpl_import.FplNotFound) as e:
        print(f"  [team card: {path}: {e}]")
        return fpl_import.last_copy(path)[0], False


def _local_snapshot():
    """The newest raw bootstrap snapshot on this machine (the poller's archive), or None."""
    try:
        import prices_tool
        snaps = prices_tool.snapshots()
        if not snaps:
            return None
        with gzip.open(str(snaps[-1][1]), "rt", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:                                   # noqa: BLE001 -- a fallback, never fatal
        return None


def _bootstrap(get=None, now=None, allow_fetch=True):
    """(the bootstrap, live): cached / fetched (live), else the last copy, else the local snapshot (both not live)."""
    boot, fresh = _fetch("bootstrap-static/", fpl_import.BOOTSTRAP_TTL_S, get=get, allow_fetch=allow_fetch)
    if boot is not None:
        return boot, fresh
    return _local_snapshot(), False


def _fixtures(get=None, allow_fetch=True):
    return _fetch(FIXTURES_PATH, fpl_import.CACHE_TTL_S, get=get, allow_fetch=allow_fetch)


def _history(fpl_team_id, get=None, allow_fetch=True):
    return _fetch(f"entry/{int(fpl_team_id)}/history/", fpl_import.CACHE_TTL_S, get=get, allow_fetch=allow_fetch)


def _pool(next_gw):
    """({element: e_points} of the production frame for next_gw, the frame's build time) or (None, None)."""
    if next_gw is None:
        return None, None
    try:
        import model_tools
        pool, _cutoff, built = model_tools._load_pool(gw=int(next_gw))
        return {int(e): round(float(p), 2) for e, p in zip(pool["element"], pool["e_points"])}, built
    except Exception as e:                              # noqa: BLE001 -- no frame, or next_gw beyond its horizon
        print(f"  [team card: no predictions for GW{next_gw}: {type(e).__name__}: {str(e)[:120]}]")
        return None, None


def _live_rows(elements, conn=None):
    """{element: players_live row} (name, position, team, price_tenths, status, chance, news, updated_at); {} when the table
    is absent or the read fails. On a caller's connection the read is rolled back; without one, model_tools' reader."""
    ids = sorted({int(e) for e in elements if e is not None})
    if not ids:
        return {}
    sql = "SELECT element, name, position, team, price_tenths, status, chance, news, updated_at FROM players_live WHERE element = ANY(%s)"
    try:
        if conn is None:
            import model_tools
            rows = model_tools._q(sql, (ids,))
        else:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(sql, (ids,))
                rows = [dict(r) for r in cur.fetchall()]
            conn.rollback()
    except Exception:                                   # noqa: BLE001 -- cosmetic, never fatal
        if conn is not None:
            try:
                conn.rollback()
            except Exception:                           # noqa: BLE001
                pass
        return {}
    return {int(r["element"]): r for r in rows if isinstance(r, dict) and r.get("element") is not None}


# ---- the context: everything a player object is built from --------------------------------------------------------------------

class Context:
    def __init__(self, boot, boot_live, fixtures, fixtures_live, now=None):
        self.boot, self.boot_live = boot or None, bool(boot_live)
        self.fixtures, self.fixtures_live = fixtures, bool(fixtures_live)
        self.now = now or clock()
        self.elements = {int(e["id"]): e for e in ((boot or {}).get("elements") or []) if e.get("id") is not None}
        self.teams = {int(t["id"]): t for t in ((boot or {}).get("teams") or []) if t.get("id") is not None}
        self.by_club_name = {str(t.get("name")): t for t in self.teams.values()}
        self.next_gw, self.deadline = None, None
        if boot:
            _latest, nxt = fpl_import.gameweeks(boot, self.now)
            if nxt is not None:
                self.next_gw = int(nxt)
                ev = next((e for e in boot.get("events", []) if int(e["id"]) == self.next_gw), None)
                self.deadline = fpl_import._deadline(ev).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") if ev else None
        self.pool, self.built = (None, None)
        self.live_rows = {}

    def load_predictions(self):
        self.pool, self.built = _pool(self.next_gw)
        return self

    def club_code(self, team_id=None, club_name=None):
        t = self.teams.get(int(team_id)) if team_id is not None else self.by_club_name.get(str(club_name))
        return (t or {}).get("short_name") or (str(club_name) if club_name else None)

    def next_fixture(self, team_id):
        """{opp, home, n} for the club's first fixture of next_gw, or None (a blank, or no fixtures known)."""
        if self.fixtures is None or self.next_gw is None or team_id is None:
            return None
        mine = [f for f in self.fixtures if f.get("event") == self.next_gw and int(team_id) in (f.get("team_h"), f.get("team_a"))]
        if not mine:
            return None
        mine.sort(key=lambda f: str(f.get("kickoff_time") or ""))
        f = mine[0]
        home = f.get("team_h") == int(team_id)
        return {"opp": self.club_code(f.get("team_a") if home else f.get("team_h")), "home": bool(home), "n": len(mine)}

    def player(self, element, slot=None, role=None, in_squad=True, doc=None, price_tenths=None):
        """The Player object of one element: the bootstrap first, players_live (and the squad document) as the fallback."""
        e = self.elements.get(int(element)) or {}
        live = self.live_rows.get(int(element)) or {}
        doc = doc or {}
        first, second = (e.get("first_name") or "").strip(), (e.get("second_name") or "").strip()
        full = " ".join(x for x in (first, second) if x) or live.get("name") or doc.get("name") or f"Player {int(element)}"
        short = e.get("web_name") or live.get("name") or doc.get("name") or full
        position = POSITIONS.get(e.get("element_type")) if e else None
        position = position or doc.get("position") or live.get("position")
        club = self.club_code(e.get("team")) if e else self.club_code(club_name=live.get("team") or doc.get("team"))
        price = None
        if e.get("now_cost") is not None:
            price = round(int(e["now_cost"]) / 10, 1)
        elif live.get("price_tenths") is not None:
            price = round(int(live["price_tenths"]) / 10, 1)
        elif price_tenths is not None:
            price = round(int(price_tenths) / 10, 1)
        form = _num(e.get("form")) if e else None
        status, chance, news, news_added = (e.get("status"), e.get("chance_of_playing_next_round"), e.get("news"), e.get("news_added")) if e else \
            (live.get("status"), live.get("chance"), live.get("news"), None)
        flag = None
        if status is not None and (status != "a" or (chance is not None and int(chance) < 100)):
            when = news_added or live.get("updated_at")
            flag = {"chance": None if chance is None else int(chance), "news": (news or "").strip() or None,
                    "news_date": str(when)[:10] if when else None}
        pred = None
        if self.pool is not None and int(element) in self.pool:
            pred = {"points": self.pool[int(element)], "source": "ours"}
        elif e and _num(e.get("ep_next")) is not None:
            pred = {"points": _num(e.get("ep_next")), "source": "fpl_est"}
        return {"slot": slot, "id": int(element), "short_name": short, "full_name": full, "club": club, "position": position,
                "price": price, "form": form, "role": role, "next": self.next_fixture(e.get("team")) if e else None,
                "flag": flag, "pred": pred, "in_squad": bool(in_squad)}


def _num(v):
    try:
        return None if v is None or v == "" else round(float(v), 1)
    except (TypeError, ValueError):
        return None


def gather(get=None, now=None, allow_fetch=True, fpl_team_id=None):
    """The Context for a card (fetching) or a turn (allow_fetch False: caches and the local snapshot only). With fpl_team_id,
    the team's history is read too (ctx.history, ctx.history_live)."""
    boot, boot_live = _bootstrap(get=get, now=now, allow_fetch=allow_fetch)
    fixtures, fixtures_live = _fixtures(get=get, allow_fetch=allow_fetch)
    ctx = Context(boot, boot_live, fixtures, fixtures_live, now=now)
    ctx.history, ctx.history_live = (None, False)
    if fpl_team_id is not None:
        ctx.history, ctx.history_live = _history(fpl_team_id, get=get, allow_fetch=allow_fetch)
    return ctx


# ---- the squad document's slots and roles -----------------------------------------------------------------------------------

def slots(doc):
    """{element: slot 1-15} of a squad document: XI by position (GK, DEF, MID, FWD) in the document's order, bench by order."""
    players = list(doc.get("players") or [])
    xi = [p for p in players if p.get("role") != "bench"]
    xi.sort(key=lambda p: POS_ORDER.get(p.get("position"), 9))
    bench = sorted((p for p in players if p.get("role") == "bench"), key=lambda p: int(p.get("bench_order") or 0))
    out = {int(p["element"]): i for i, p in enumerate(xi, start=1)}
    out.update({int(p["element"]): 11 + i for i, p in enumerate(bench, start=1)})
    return out


def roles(doc):
    """{element: "C" | "VC" | None}"""
    return {int(p["element"]): ("C" if p.get("role") == "CAPTAIN" else "VC" if p.get("role") == "VICE" else None)
            for p in (doc.get("players") or [])}


def formation(doc):
    n = {"DEF": 0, "MID": 0, "FWD": 0}
    for p in doc.get("players") or []:
        if p.get("role") != "bench" and p.get("position") in n:
            n[p["position"]] += 1
    return f"{n['DEF']}-{n['MID']}-{n['FWD']}"


def players_of(ctx, doc, conn=None):
    """The fifteen of a squad document as Player objects, in slot order."""
    ctx.live_rows = _live_rows([p["element"] for p in doc.get("players") or []], conn=conn)
    sl, rl = slots(doc), roles(doc)
    by = {int(p["element"]): p for p in doc.get("players") or []}
    return [ctx.player(e, slot=sl[e], role=rl.get(e), in_squad=True, doc=by[e], price_tenths=by[e].get("purchase_price"))
            for e in sorted(sl, key=sl.get)]


def chips_block(history, next_gw):
    """The current half's chips from FPL's history, or None without a history."""
    if history is None or next_gw is None:
        return None
    lo, hi = (1, 19) if int(next_gw) <= 19 else (20, 38)
    used = {}
    for ch in history.get("chips") or []:
        ev = ch.get("event")
        if ev is not None and lo <= int(ev) <= hi:
            used[str(ch.get("name"))] = int(ev)
    items = [{"code": code, "name": name, "used_gw": used.get(key)} for key, code, name in CHIPS]
    n_used = sum(1 for it in items if it["used_gw"] is not None)
    return {"half": {"from": lo, "to": hi}, "used": n_used, "left": len(items) - n_used, "items": items}


# ---- the endpoint --------------------------------------------------------------------------------------------------------------

def build(user_id, fpl_team_id, get=None, now=None):
    """GET /me/teams/{id}/card. Raises TeamNotFound; squad_store.SquadStateError when the team has no active version."""
    import fpl_teams
    import squad_store
    uid, fid = int(user_id), int(fpl_team_id)
    conn = _connect()
    try:
        fpl_teams._ready(conn)
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT squad_key, label, entry_name, manager_name FROM user_fpl_teams WHERE user_id = %s AND fpl_team_id = %s",
                        (uid, fid))
            team = cur.fetchone()
        conn.rollback()
        if team is None:
            raise TeamNotFound(str(fid))
        record = squad_store.read_active(int(team["squad_key"]), conn=conn)
        conn.rollback()
        ctx = gather(get=get, now=now, allow_fetch=True, fpl_team_id=fid).load_predictions()
        doc = record["squad_json"]
        players = players_of(ctx, doc, conn=conn)
    finally:
        conn.close()
    ft = squad_store.free_transfers_at(record, ctx.next_gw) if ctx.next_gw is not None else doc.get("free_transfers")
    prices = [p["price"] for p in players if p["price"] is not None]
    prov = doc.get("provenance") or {}
    as_of = prov.get("picks_gw") if prov.get("source") == "fpl_import" and prov.get("picks_gw") is not None else record["gw"]
    return {"team": {"fpl_team_id": fid, "name": team["label"] or team["entry_name"] or f"Team {fid}",
                     "entry_name": team["entry_name"], "manager_name": team["manager_name"]},
            "version_id": int(record["version_id"]), "squad_as_of_gw": int(as_of), "squad_updated_at": _iso(record["created_at"]),
            "formation": formation(doc), "bank": round(int(doc["bank"]) / 10, 1), "free_transfers": None if ft is None else int(ft),
            "team_value": round(sum(prices), 1) if len(prices) == len(players) else None,
            "next_gw": ctx.next_gw, "next_deadline": ctx.deadline,
            "predictions_gw": ctx.next_gw if ctx.pool is not None else None,
            "predictions_updated_at": _iso(ctx.built) if ctx.built is not None else None,
            "chips": chips_block(ctx.history, ctx.next_gw), "players": players,
            "fpl_live": bool(ctx.boot_live and ctx.fixtures_live and ctx.history_live),
            "fetched_at": _iso(ctx.now)}
