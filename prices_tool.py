"""prices_tool.py -- risers, fallers, and what your own players sell for.

PURE, like explain.py and quantiles.py: it reads the poller's stored snapshots and the
scoring/selling rule, and imports no part of the model stack.

THE SNAPSHOTS ARE NOT DAILY, and the tool is built around that rather than pretending
otherwise. Measured on the server 2026-09-19: 53 files spanning 30 days, but on SIX distinct
days -- 08-20 (2), 08-21 (1), 08-28 (11), 09-04 (13), 09-12 (13), 09-18 (13), with gaps of
6-8 days. They are burst-sampled around builds, not polled daily. Prices change every day, so
an individual daily move between two snapshots is UNOBSERVABLE, and a rise followed by a fall
cancels to "no change".

What rescues it is that FPL maintains cumulative counters. cost_change_start is the net move
since the season began and cost_change_start_fall the falls alone, so net change is exact
regardless of how sparsely we sampled, and gross up/down is recoverable from the pair. The
unit of this tool is therefore "net change between two OBSERVATIONS", and every answer carries
the two timestamps, the number of snapshots in the window and the largest gap inside it.

THE TOOL DOES NOT FORECAST, AND THE REASON IS NOT THE ONE YOU MIGHT ASSUME. FPL does publish a
progress-to-threshold figure in this data -- price_change_percent (-227.3..+129.7, moving
between snapshots), alongside price_change_hourly_rate, price_change_projections,
price_change_locked_until and price_change_calibrating. So "the thresholds are unpublished" is
not why. The reason is LAUNDERING: a projection sitting in the payload becomes the agent's own
prediction no matter what the prompt says, and a wrong price call attributed to us is worse
than no price call. Ruling 2026-09-19:
  * price_change_percent IS included, always attributed to FPL, never presented as ours;
  * price_change_projections and the other forward fields are EXCLUDED from the payload
    entirely, so there is nothing to launder.

SELLING PRICE IS NOT REIMPLEMENTED. squad_state.sell_price already encodes the asymmetric rule
(a rise is shared with FPL -- you get half, rounded down; a fall is yours in full) and is
already what the transfer MIP and propose_transfers use, with an assertion that the two agree.
Reusing the function rather than the rule is the standing lesson from 2026-09-18.
"""
import gzip
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from squad_state import sell_price

REPO = Path(__file__).resolve().parent
BOOTSTRAP_DIR = REPO / "data" / "live" / "bootstrap_raw" / "2026-27"
STAMP = re.compile(r"(\d{8})T(\d{6})Z")

# Fields deliberately NOT read out of the snapshot. Named here so the exclusion is a visible
# decision rather than an oversight, and so a test can assert they never reach the payload.
FORWARD_FIELDS = ("price_change_projections", "price_change_hourly_rate",
                  "price_change_locked_until", "price_change_calibrating")
DEFAULT_WINDOW_DAYS = 7
MAX_MOVERS = 25


def snapshot_time(path):
    m = STAMP.search(Path(path).name)
    if not m:
        return None
    return datetime.strptime(m.group(1) + m.group(2), "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)


def snapshots(directory=None):
    d = Path(directory) if directory else BOOTSTRAP_DIR
    out = [(snapshot_time(p), p) for p in sorted(d.glob("*.json.gz"))]
    return [(t, p) for t, p in out if t is not None]


def read_snapshot(path):
    """element -> the few price fields we use. The forward-looking fields are never read."""
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        doc = json.load(fh)
    out = {}
    for e in doc.get("elements", []):
        try:
            el = int(e["id"])
        except (KeyError, TypeError, ValueError):
            continue
        pcp = e.get("price_change_percent")
        try:
            pcp = float(pcp)
        except (TypeError, ValueError):
            pcp = None
        out[el] = {
            "now_cost": e.get("now_cost"),
            "cost_change_start": e.get("cost_change_start"),
            "cost_change_start_fall": e.get("cost_change_start_fall"),
            "cost_change_event": e.get("cost_change_event"),
            "fpl_price_change_percent": pcp,
            "name": f"{e.get('first_name','')} {e.get('second_name','')}".strip()
                    or str(e.get("web_name", "")),
        }
    return out


def bracket(window_days=DEFAULT_WINDOW_DAYS, now=None, directory=None):
    """The two snapshots that bracket the window: the last one at or before its start, and the
    most recent one. O(1) reads instead of scanning the archive, which matters because the
    archive grows -- 53 files today, ~250 by May, 41 ms each."""
    snaps = snapshots(directory)
    if not snaps:
        return None, None, []
    latest_t, latest_p = snaps[-1]
    now = now or latest_t
    start = now.timestamp() - float(window_days) * 86400.0
    earlier = [(t, p) for t, p in snaps if t.timestamp() <= start]
    first = earlier[-1] if earlier else snaps[0]
    inside = [(t, p) for t, p in snaps if first[0] <= t <= latest_t]
    return first, (latest_t, latest_p), inside


def _gaps(inside):
    if len(inside) < 2:
        return None
    ts = [t for t, _ in inside]
    return round(max((b - a).total_seconds() / 3600.0 for a, b in zip(ts, ts[1:])), 1)


def movements(window_days=DEFAULT_WINDOW_DAYS, squad=None, directory=None, now=None,
              max_movers=MAX_MOVERS):
    """PURE. `squad` is the active squad_json dict (or None for movers only)."""
    first, last, inside = bracket(window_days, now=now, directory=directory)
    if first is None:
        return {"error": "no price snapshots on the volume; nothing can be said about prices"}
    t0, p0 = first
    t1, p1 = last
    a, b = read_snapshot(p0), read_snapshot(p1)

    observation = {
        "observed_from": t0.isoformat().replace("+00:00", "Z"),
        "observed_to": t1.isoformat().replace("+00:00", "Z"),
        "window_days_requested": window_days,
        "window_hours_actual": round((t1 - t0).total_seconds() / 3600.0, 1),
        "snapshots_in_window": len(inside),
        "largest_gap_hours": _gaps(inside),
        "sampling": ("the snapshots are BURST-SAMPLED around builds, not daily. A move that "
                     "happened and reversed inside a gap is invisible here, and 'no change' "
                     "means 'no NET change between these two observations', not 'the price "
                     "did not move'."),
        "basis": "observed",
    }

    movers = []
    for el, cur in b.items():
        prev = a.get(el)
        if prev is None or cur["now_cost"] is None or prev["now_cost"] is None:
            continue
        delta = int(cur["now_cost"]) - int(prev["now_cost"])
        if delta == 0:
            continue
        movers.append({
            "player_id": el, "name": cur["name"],
            "price_now": round(int(cur["now_cost"]) / 10, 1),
            "price_then": round(int(prev["now_cost"]) / 10, 1),
            "net_change": round(delta / 10, 1),
            "direction": "riser" if delta > 0 else "faller",
            "season_net_change": (None if cur["cost_change_start"] is None
                                  else round(int(cur["cost_change_start"]) / 10, 1)),
            "season_total_falls": (None if cur["cost_change_start_fall"] is None
                                   else round(int(cur["cost_change_start_fall"]) / 10, 1)),
            "fpl_price_change_percent": cur["fpl_price_change_percent"],
            "basis": "observed",
        })
    movers.sort(key=lambda m: -abs(m["net_change"]))
    risers = [m for m in movers if m["direction"] == "riser"][:max_movers]
    fallers = [m for m in movers if m["direction"] == "faller"][:max_movers]

    out = {
        "observation": observation,
        "risers": risers,
        "fallers": fallers,
        "n_moved": len(movers),
        "fpl_price_change_percent": {
            "what": ("FPL's OWN published progress-toward-a-price-change figure, carried "
                     "through unchanged. It is not our number, not our model, and not a "
                     "prediction we are making."),
            "attribute_as": "FPL's published figure",
            # The excluded fields are NOT named here on purpose: naming them would put the
            # strings in the payload and defeat the tripwire test that greps the whole
            # payload for them. They are listed in FORWARD_FIELDS, in code, where the
            # exclusion is enforced.
            "excluded": ("FPL also publishes forward-looking price projections. They are "
                         "deliberately NOT in this payload: a projection in the payload "
                         "becomes the agent's own forecast whatever the prompt says, and a "
                         "wrong price call attributed to us is worse than no price call."),
        },
        "cannot_forecast": (
            "This tool reports what HAS happened. It cannot say whether a player will rise or "
            "fall next, and a recent rise is NOT evidence of the next one -- a player who has "
            "just risen has had his transfer counter reset. Do not convert any number here "
            "into a prediction."),
    }

    if squad:
        out["my_squad"] = _squad_block(squad, b)
    return out


def _squad_block(squad, cur):
    """What each owned player would sell for now, via squad_state.sell_price -- the same
    function the transfer MIP uses, not a second copy of the rule."""
    players, total_sell, total_paid, missing = [], 0, 0, []
    for p in squad.get("players", []):
        el = int(p["element"])
        bought = int(p["purchase_price"])
        row = cur.get(el)
        if row is None or row["now_cost"] is None:
            missing.append(el)
            now = bought                       # never assume a rise: that would invent money
        else:
            now = int(row["now_cost"])
        sells = sell_price(bought, now)
        total_sell += sells
        total_paid += bought
        players.append({
            "player_id": el, "name": p.get("name"), "position": p.get("position"),
            "purchase_price": round(bought / 10, 1),
            "price_now": round(now / 10, 1),
            "sells_for": round(sells / 10, 1),
            "change_since_purchase": round((now - bought) / 10, 1),
            "profit_if_sold": round((sells - bought) / 10, 1),
            "fpl_price_change_percent": (row or {}).get("fpl_price_change_percent"),
            "price_unknown": row is None or row["now_cost"] is None,
        })
    return {
        "players": players,
        "total_paid": round(total_paid / 10, 1),
        "total_sell_value": round(total_sell / 10, 1),
        "bank": round(int(squad.get("bank", 0)) / 10, 1),
        "unpriced_elements": missing,
        "selling_rule": ("a RISE is shared with FPL -- you receive the purchase price plus "
                         "half the rise, rounded down; a FALL is yours in full. From "
                         "squad_state.sell_price, the same function the transfer MIP uses."),
        "asymmetry_matters": ("sells_for is NOT price_now for a player who has risen. Quoting "
                              "the market price as what you would receive overstates the "
                              "budget, which is how an unaffordable transfer gets proposed."),
    }
