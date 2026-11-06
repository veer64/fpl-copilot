"""FPL team import (Prompt F1a Part 5, 2026-11-02): a real FPL team, read from FPL's public API, as a squad document.

USER DECISION (2 Nov): "Yes, we will ask user to enter the team ID, we will keep the team ids visible to them ... by this
way we can let the user add in more than 1 team." Accepted defaults: each imported team is its own squad record
(fpl_teams.py); squad_versions rows are written through squad_store.write_version as a direct user action, never through
the agent's preview lock.

WHAT IS FETCHED (server side; FPL's public JSON, no login), at most one request per MIN_INTERVAL_S per process:
  bootstrap-static/                        (cached BOOTSTRAP_TTL_S: deadlines, prices, game_settings)
  entry/{id}/                              (started_event, the team's name -- 404 here = no such team)
  entry/{id}/history/                      (per-gameweek transfers, hit costs, totals; chips played)
  entry/{id}/transfers/                    (element_in_cost of every transfer)
  entry/{id}/event/{gw}/picks/             (the fifteen, the roles, the bank) for the latest gameweek whose deadline has
                                            passed -- the previous gameweek's when that one was a free hit (the squad
                                            reverts after a free hit)
  element-summary/{el}/                    only for an entry that started after GW1, for players held since its first
                                            gameweek (their price in that gameweek)

HOW THE DOCUMENT IS BUILT (squad_store.document validates it; squad_store.to_state is the squad_state legality check):
- roles from the picks AS THE MANAGER SET THEM: FPL's picks of a played gameweek show its automatic substitutions applied
  (the sub in the starter's slot, the starter in the sub's bench slot -- a benched vice-captain, measured on the recorded
  GW8), and autosubs only score that week, so they are undone (noted); then positions 1-11 the XI, 12-15 the bench in
  order (bench_order = position - 11; 12 is FPL's bench goalkeeper slot = the document's bench_order 1); is_captain ->
  CAPTAIN, is_vice_captain -> VICE;
- bank = the picks' entry_history.bank (tenths, FPL's own figure);
- purchase_price = element_in_cost of the LATEST transfer that brought the player in (free-hit weeks' transfers ignored:
  that squad reverted); a player held since the entry's first gameweek: his price then -- for an entry that started in
  GW1 the season's start price (now_cost - cost_change_start, exact); otherwise his `value` in that round from
  element-summary (listed as estimated);
- free_transfers for the version's gameweek, derived from history with squad_state's rule (free first, the rest paid;
  +1 per gameweek up to the cap): 1 for the gameweek after the entry's first; a wildcard / free hit week spends none and
  earns none (the saved transfers are kept as they were -- the rule FPL's own hit charges fit on the team recorded 2 Nov
  2026: with +1 earned in its GW3 free hit, its GW6 hit could not have been charged; listed as estimated); FPL's own hit
  cost corrects the count when they disagree (listed). FPL's history shows event_transfers 0 for a wildcard / free hit
  week whatever was done in it. The cap: 1 + game_settings.max_extra_free_transfers when bootstrap has it, else 5
  (noted).
- total_points = the history's total for the latest passed gameweek; the version's gw = the NEXT deadline's gameweek (what
  set_my_squad requires);
- every value that could not be derived exactly is listed in squad_json.provenance.estimated.

Errors: FplNotFound (FPL answered 404 for the team) -> 404; FplUnavailable (5xx, 429, a timeout, no connection, not JSON)
-> 503, nothing written; ImportRefused (no deadline passed yet, the team has no picks yet, ...) -> 409."""
import threading
import time
from datetime import datetime, timezone

API = "https://fantasy.premierleague.com/api"
UA = {"User-Agent": "Mozilla/5.0 (fpl-copilot team import; contact: repo owner)"}
MIN_INTERVAL_S = 1.0                      # politeness: at least this long between two FPL requests of this process
TIMEOUT_S = 10
BOOTSTRAP_TTL_S = 600
DEFAULT_FT_CAP = 5
POSITIONS = {1: "GK", 2: "DEF", 3: "MID", 4: "FWD"}
CHIP_KEEPS_TRANSFERS = ("wildcard", "freehit")

_LOCK = threading.Lock()
_STATE = {"last": 0.0, "bootstrap": None, "bootstrap_at": 0.0, "requests": 0}
# Prompt W4 (2026-11-06): the per-process cache of FPL answers the Chat page's team card reads (bootstrap, fixtures?future=1,
# entry history), one entry per path behind its own lock -- SINGLE-FLIGHT: concurrent callers of one path wait for the one
# fetch and share its body (T1 measured three bootstrap fetches from three concurrent first calls). A failed refetch leaves
# the old copy in place for last_copy() (checkpoint C8: served past its TTL with fpl_live false rather than nothing).
CACHE_TTL_S = 300
_CACHE = {}                               # path -> {"body", "at" (monotonic), "lock"}
_CACHE_LOCK = threading.Lock()


class FplNotFound(Exception):
    """FPL answered 404: no such team."""


class FplUnavailable(Exception):
    """FPL could not be read (5xx, 429, a timeout, no connection, not JSON): nothing is written."""


class ImportRefused(Exception):
    """The team exists but cannot be imported now (no deadline has passed, the team has no picks yet, ...)."""


def clock():
    return datetime.now(timezone.utc)


def _reset():
    """Forget the cached bootstrap, the W4 cache and the request clock (tests only)."""
    with _LOCK:
        _STATE.update(last=0.0, bootstrap=None, bootstrap_at=0.0, requests=0)
    with _CACHE_LOCK:
        _CACHE.clear()


def _http_get(url):
    """(status, parsed JSON or None) from FPL; raises FplUnavailable on a network failure."""
    import requests
    try:
        r = requests.get(url, headers=UA, timeout=TIMEOUT_S)
    except Exception as e:                                # noqa: BLE001 -- timeout, DNS, refused: FPL unavailable
        raise FplUnavailable(f"FPL could not be reached: {type(e).__name__}") from e
    try:
        body = r.json()
    except ValueError:
        body = None
    return r.status_code, body


def fetch_json(path, get=None):
    """GET API/<path> (spaced MIN_INTERVAL_S from this process's previous request). `get(url) -> (status, body)` is the
    transport (tests pass recorded responses; no network in pytest)."""
    get = get or _http_get
    url = f"{API}/{path}"
    with _LOCK:
        wait = MIN_INTERVAL_S - (time.monotonic() - _STATE["last"])
        if wait > 0:
            time.sleep(wait)
        try:
            status, body = get(url)
        finally:
            _STATE["last"] = time.monotonic()
            _STATE["requests"] += 1
    if status == 404:
        raise FplNotFound(path)
    if status != 200 or body is None:
        raise FplUnavailable(f"FPL answered {status} for {path}")
    return body


def _entry(path):
    with _CACHE_LOCK:
        return _CACHE.setdefault(path, {"body": None, "at": 0.0, "lock": threading.Lock()})


def cached_json(path, ttl=CACHE_TTL_S, get=None, now_mono=None):
    """GET API/<path> at most once per `ttl` seconds per process; one fetch at a time per path (the second concurrent caller
    waits and finds the body cached). Raises FplNotFound / FplUnavailable; the old copy, if any, stays for last_copy()."""
    entry = _entry(path)
    with entry["lock"]:
        now = time.monotonic() if now_mono is None else now_mono
        if entry["body"] is not None and now - entry["at"] < ttl:
            return entry["body"]
        body = fetch_json(path, get=get)
        entry.update(body=body, at=time.monotonic() if now_mono is None else now_mono)
        return body


def peek(path, ttl=CACHE_TTL_S):
    """The cached body of `path` when it is younger than `ttl`, else None -- never a fetch (what a /chat turn may read)."""
    entry = _entry(path)
    body, at = entry["body"], entry["at"]
    return body if body is not None and time.monotonic() - at < ttl else None


def last_copy(path):
    """(the last successfully fetched body of `path` whatever its age, its age in seconds) or (None, None)."""
    entry = _entry(path)
    if entry["body"] is None:
        return None, None
    return entry["body"], time.monotonic() - entry["at"]


def bootstrap(get=None, now_mono=None):
    """bootstrap-static, cached BOOTSTRAP_TTL_S per process (through the single-flight cache since Prompt W4; _STATE keeps
    its copy for the callers that read it)."""
    body = cached_json("bootstrap-static/", BOOTSTRAP_TTL_S, get=get, now_mono=now_mono)
    _STATE.update(bootstrap=body, bootstrap_at=_entry("bootstrap-static/")["at"])
    return body


def _deadline(e):
    return datetime.fromisoformat(str(e["deadline_time"]).replace("Z", "+00:00"))


def gameweeks(boot, now):
    """(the latest gameweek whose deadline has passed, the next deadline's gameweek); either may be None."""
    passed = [int(e["id"]) for e in boot.get("events", []) if _deadline(e) <= now]
    upcoming = [int(e["id"]) for e in boot.get("events", []) if _deadline(e) > now]
    return (max(passed) if passed else None), (min(upcoming) if upcoming else None)


def ft_cap(boot):
    """(the free-transfer cap, a note): 1 + game_settings.max_extra_free_transfers when present, else DEFAULT_FT_CAP."""
    extra = (boot.get("game_settings") or {}).get("max_extra_free_transfers")
    if isinstance(extra, int) and not isinstance(extra, bool) and extra >= 0:
        return 1 + extra, f"free-transfer cap {1 + extra} = 1 + game_settings.max_extra_free_transfers ({extra})"
    return DEFAULT_FT_CAP, f"free-transfer cap {DEFAULT_FT_CAP} assumed: bootstrap game_settings has no max_extra_free_transfers"


def fetch_team(fpl_team_id, now=None, get=None):
    """Every FPL response the import needs, as a dict (see the module docstring). Raises FplNotFound / FplUnavailable /
    ImportRefused."""
    now = now or clock()
    tid = int(fpl_team_id)
    boot = bootstrap(get=get)
    latest, nxt = gameweeks(boot, now)
    if latest is None:
        raise ImportRefused("no gameweek deadline has passed yet, so FPL has no picks to import")
    if nxt is None:
        raise ImportRefused("the season has no upcoming deadline, so there is no gameweek to import the squad for")
    entry = fetch_json(f"entry/{tid}/", get=get)
    started = int(entry.get("started_event") or 1)
    if started > latest:
        raise ImportRefused(f"this FPL team has no picks yet: it starts in GW{started}")
    history = fetch_json(f"entry/{tid}/history/", get=get)
    transfers = fetch_json(f"entry/{tid}/transfers/", get=get)
    picks = {latest: fetch_json(f"entry/{tid}/event/{latest}/picks/", get=get)}
    picks_gw, notes = latest, []
    if picks[latest].get("active_chip") == "freehit":
        if latest - 1 < started:
            raise ImportRefused(f"GW{latest} was a free hit in the team's first gameweek; there is no squad to revert to")
        picks_gw = latest - 1
        picks[picks_gw] = fetch_json(f"entry/{tid}/event/{picks_gw}/picks/", get=get)
        notes.append(f"GW{latest} was a free hit: the squad is GW{picks_gw}'s, the one the free hit reverts to")
    held = [int(p["element"]) for p in picks[picks_gw].get("picks", [])]
    bought = _latest_buys(transfers, _chip_weeks(history, ("freehit",)), picks_gw)
    summaries = {}
    if started > 1:
        for el in held:
            if el not in bought:
                summaries[el] = fetch_json(f"element-summary/{el}/", get=get)
    return {"fpl_team_id": tid, "now": now, "bootstrap": boot, "latest_gw": latest, "next_gw": nxt, "entry": entry,
            "history": history, "transfers": transfers, "picks": picks, "picks_gw": picks_gw,
            "element_summaries": summaries, "notes": notes}


def _chip_weeks(history, names):
    return {int(c["event"]) for c in (history.get("chips") or []) if c.get("name") in names and c.get("event") is not None}


def _latest_buys(transfers, freehit_weeks, up_to_gw):
    """{element: element_in_cost} of the latest transfer that brought each player in, up to `up_to_gw`; free-hit weeks'
    transfers are ignored (that squad reverted)."""
    rows = [t for t in (transfers or []) if t.get("event") is not None and int(t["event"]) <= up_to_gw
            and int(t["event"]) not in freehit_weeks]
    rows.sort(key=lambda t: (int(t["event"]), str(t.get("time") or "")))
    out = {}
    for t in rows:
        out[int(t["element_in"])] = int(t["element_in_cost"])
    return out


def derive_free_transfers(history, started, latest, cap):
    """(free transfers for the gameweek after `latest`, [estimated notes]) with squad_state's rule: 1 for the gameweek
    after the entry's first; each later gameweek spends its free transfers (FPL's hit cost says how many were paid) and
    earns +1 up to `cap`; a wildcard / free hit week spends none and earns none."""
    rows = {int(r["event"]): r for r in (history.get("current") or []) if r.get("event") is not None}
    chips = {int(c["event"]): c.get("name") for c in (history.get("chips") or []) if c.get("event") is not None}
    ft, estimated = 1, []
    for g in range(started + 1, latest + 1):
        r = rows.get(g) or {}
        n = int(r.get("event_transfers") or 0)
        paid = int(r.get("event_transfers_cost") or 0) // 4
        if chips.get(g) in CHIP_KEEPS_TRANSFERS:
            estimated.append(f"free_transfers: GW{g} was a {chips[g]} -- its transfers were free, the saved free "
                             f"transfers kept and none earned that week")
            continue
        else:
            free_used = n - paid
            if paid != max(0, n - ft) or free_used > ft:
                estimated.append(f"free_transfers: at GW{g} FPL charged {paid} hit(s) for {n} transfer(s) against "
                                 f"{ft} derived free transfer(s); FPL's charge was used")
                ft = free_used if paid > 0 else max(ft, free_used)
            ft = max(0, ft - free_used)
        ft = min(cap, ft + 1)
    return ft, estimated


def _start_price(boot_el):
    return int(boot_el["now_cost"]) - int(boot_el.get("cost_change_start") or 0)


def _price_in_round(summary, rnd):
    rows = sorted((h for h in (summary.get("history") or []) if h.get("round") is not None and h.get("value") is not None),
                  key=lambda h: (int(h["round"]), str(h.get("kickoff_time") or "")))
    for h in rows:
        if int(h["round"]) >= rnd:
            return int(h["value"]), int(h["round"])
    return None, None


def manager_positions(pk, gw):
    """{element: position} as the manager set the team: the picks' automatic substitutions of `gw` undone, last first
    (each swapped the sub on into the starter's slot and the starter into the sub's)."""
    pos = {int(p["element"]): int(p["position"]) for p in pk.get("picks", [])}
    subs = [s for s in (pk.get("automatic_subs") or []) if s.get("event") is None or int(s["event"]) == int(gw)]
    for s in reversed(subs):
        a, b = int(s["element_in"]), int(s["element_out"])
        if a in pos and b in pos:
            pos[a], pos[b] = pos[b], pos[a]
    return pos, len(subs)


def build(raw, meta, season):
    """(the squad document, info) from fetch_team's output. `meta` = {element: {name, position, team}} (players_live);
    an element missing there takes its name / position / club from bootstrap. Raises ValueError for an illegal squad."""
    import squad_store
    boot, entry, history = raw["bootstrap"], raw["entry"], raw["history"]
    picks_gw, latest, started = raw["picks_gw"], raw["latest_gw"], int(entry.get("started_event") or 1)
    pk = raw["picks"][picks_gw]
    els = {int(e["id"]): e for e in boot.get("elements", [])}
    clubs = {int(t["id"]): t.get("name") for t in boot.get("teams", [])}
    bought = _latest_buys(raw["transfers"], _chip_weeks(history, ("freehit",)), picks_gw)
    estimated, notes = [], list(raw.get("notes") or [])
    positions, n_subs = manager_positions(pk, picks_gw)
    if n_subs:
        notes.append(f"GW{picks_gw}'s {n_subs} automatic substitution(s) undone: the line-up as the manager set it")
    players = []
    for p in sorted(pk.get("picks", []), key=lambda x: positions[int(x["element"])]):
        el = int(p["element"])
        pos = positions[el]
        b = els.get(el) or {}
        m = meta.get(el) or {}
        name = m.get("name") or " ".join(x for x in (b.get("first_name"), b.get("second_name")) if x) or f"element {el}"
        position = m.get("position") or POSITIONS.get(int(b.get("element_type") or 0))
        team = m.get("team") or clubs.get(int(b.get("team") or 0))
        if el in bought:
            price = bought[el]
        elif started == 1 and b:
            price = _start_price(b)
        else:
            price, rnd = _price_in_round(raw["element_summaries"].get(el) or {}, started)
            if price is None:
                price = int(b.get("now_cost") or 0)
                estimated.append(f"purchase_price of {el} ({name}): no price found for his first gameweek with this "
                                 f"team (GW{started}); today's price used")
            else:
                estimated.append(f"purchase_price of {el} ({name}): his price in GW{rnd} (element-summary), the team's "
                                 f"first gameweek with him")
        if p.get("is_captain"):
            role, bo = "CAPTAIN", None
        elif p.get("is_vice_captain"):
            role, bo = "VICE", None
        elif pos <= 11:
            role, bo = "start", None
        else:
            role, bo = "bench", pos - 11
        players.append({"element": el, "name": name, "position": position, "team": team, "purchase_price": int(price),
                        "role": role, "bench_order": bo})
    cap, cap_note = ft_cap(boot)
    notes.append(cap_note)
    ft, ft_est = derive_free_transfers(history, started, latest, cap)
    estimated += ft_est
    from squad_state import MAX_FREE_TRANSFERS
    if ft > MAX_FREE_TRANSFERS:
        estimated.append(f"free_transfers: derived {ft}, above the squad document's limit {MAX_FREE_TRANSFERS}; "
                         f"{MAX_FREE_TRANSFERS} recorded")
        ft = MAX_FREE_TRANSFERS
    totals = {int(r["event"]): r for r in (history.get("current") or []) if r.get("event") is not None}
    total_points = int((totals.get(latest) or {}).get("total_points") or (pk.get("entry_history") or {}).get("total_points") or 0)
    bank = int((pk.get("entry_history") or {}).get("bank"))
    provenance = {"source": "fpl_import", "fpl_team_id": int(raw["fpl_team_id"]), "picks_gw": int(picks_gw),
                  "fetched_at": raw["now"].astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                  "estimated": estimated, "notes": notes, "hypothetical": False}
    doc = squad_store.document(players, bank, ft, total_points, season, provenance)
    squad_store.to_state(doc)                                       # squad_state's own legality: raises if not
    info = {"picks_gw": int(picks_gw), "version_gw": int(raw["next_gw"]), "latest_gw": int(latest),
            "estimated": estimated, "notes": notes, "entry_name": str(entry.get("name") or "").strip() or None}
    return doc, info


# ---- the Home page's score summary and deadlines (Prompt W3, 2026-11-05) ------------------------------------------------------

def _int(v):
    return int(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def finished_gws(boot):
    """(the set of gameweeks FPL flags finished, whether the bootstrap carries the flag at all). The recorded fixture's
    events have no flags; the live bootstrap has `finished` on every event."""
    events = boot.get("events") or []
    known = any("finished" in e for e in events)
    done = {int(e["id"]) for e in events if e.get("id") is not None and e.get("finished") is True}
    return done, known


def latest_finished_gw(boot):
    """FPL's latest finished gameweek by the bootstrap's flags, or None (no flag, or none finished)."""
    done, known = finished_gws(boot)
    return max(done) if known and done else None


def team_summary(raw):
    """The team's score card from the responses the import already fetched (fetch_team's `entry`, `history`, `bootstrap`):
    entry_name, manager_name, total_points, overall_rank (FPL's history row of the last FINISHED gameweek -- the entry's own
    summary totals when the team has no finished gameweek yet), last_gw, last_gw_points (that row), updated_after_gw (the
    gameweek the card reflects). USER DECISION (5 Nov): scores from FPL's public history, the total from GW1."""
    entry, history, boot = raw.get("entry") or {}, raw.get("history") or {}, raw.get("bootstrap") or {}
    rows = sorted((r for r in (history.get("current") or []) if r.get("event") is not None), key=lambda r: int(r["event"]))
    done, known = finished_gws(boot)
    played = [r for r in rows if not known or int(r["event"]) in done]
    last = played[-1] if played else None
    manager = " ".join(str(x).strip() for x in (entry.get("player_first_name"), entry.get("player_last_name")) if x) or None
    return {"entry_name": str(entry.get("name") or "").strip() or None,
            "manager_name": manager,
            "total_points": _int(last.get("total_points")) if last else _int(entry.get("summary_overall_points")),
            "overall_rank": _int(last.get("overall_rank")) if last else _int(entry.get("summary_overall_rank")),
            "last_gw": int(last["event"]) if last else None,
            "last_gw_points": _int(last.get("points")) if last else None,
            "updated_after_gw": int(last["event"]) if last else None}


def fetch_summary(fpl_team_id, get=None):
    """The weekly job's read: the bootstrap (cached BOOTSTRAP_TTL_S) and ONE request, entry/{id}/history/ -- no names (the
    import stored them; write_summary keeps them). Raises FplNotFound / FplUnavailable."""
    boot = bootstrap(get=get)
    history = fetch_json(f"entry/{int(fpl_team_id)}/history/", get=get)
    return team_summary({"entry": {}, "history": history, "bootstrap": boot})


def upcoming_events(boot, now=None, limit=4):
    """The next `limit` gameweek deadlines still ahead of `now`: [{gw, deadline_time, finished}], soonest first (the Home
    page's deadline pill rolls over to the next one when one passes)."""
    now = now or clock()
    out = []
    for e in sorted((e for e in (boot.get("events") or []) if e.get("id") is not None and e.get("deadline_time")),
                    key=lambda e: int(e["id"])):
        if _deadline(e) > now:
            out.append({"gw": int(e["id"]), "deadline_time": _deadline(e).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                        "finished": bool(e.get("finished"))})
        if len(out) >= limit:
            break
    return out


def players_live_meta(elements, conn=None):
    """{element: {name, position, team}} from players_live (the names every other squad tool uses)."""
    import db_write
    import psycopg2.extras
    own = conn is None
    if own:
        conn = db_write.connect()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT element, name, position, team FROM players_live WHERE element = ANY(%s)",
                        ([int(e) for e in elements],))
            return {int(r["element"]): {"name": r["name"], "position": r["position"], "team": r["team"]}
                    for r in cur.fetchall()}
    finally:
        if own:
            conn.rollback()
            conn.close()
