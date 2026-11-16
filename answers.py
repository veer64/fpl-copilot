"""answers.py -- Prompt R3 (16 Nov 2026): the number-dense answers of a normal (non-draft) chat, written by CODE.

Root cause, measured (eval/reports/r3_evidence_digest.md, R1's Set B, 13 of 30 correct): no tool ranked players, so the model
ranked by hand -- partial lists called "the best", 32-45 single-player lookups in one response, tables it sorted itself and
sums it added itself; the whole-squad review was too long for one reply; and facts were given the wrong meaning (FPL's +50.6
price figure read as "toward a fall", the hold baseline described as covering three gameweeks). The rule applied here is
W11's: when the model reaches for a number, supply the fact; number-dense answers belong in code.

Seven answers are built here. Each is delivered as the reply itself (agent.DIRECT_TOOLS: the model only routes):
  rank          -- the true top N over the WHOLE player pool                    (model_tools.rank_players)
  review        -- the user's own fifteen                                       (model_tools.review_my_squad)
  plan          -- the transfer plan, from the planner's own result             (model_tools.propose_transfers)
  prices        -- the squad's price moves and the selling rule per player      (model_tools.get_price_movements)
  best_squad    -- a whole fifteen from the build's own solve (Prompt R3b)      (model_tools.get_best_squad / optimise)
  compare       -- two or more players, gameweek by gameweek (Prompt R3b)       (model_tools.compare_players)
  fixture_grid  -- club x gameweek, for all clubs or more than five (R3b)       (model_tools.get_fixtures)

PURE: no database, no file, no clock, no model. model_tools.py reads the facts and calls these builders. Every number in a
reply is a fact handed in, or one sum / difference / quotient / rank of such facts, rounded half-up here; every builder ends
with the owner's follow-up question (USER DECISION 15 Nov)."""
from decimal import ROUND_HALF_UP, Decimal

POS_WORDS = {"GK": ("goalkeeper", "goalkeepers"), "DEF": ("defender", "defenders"), "MID": ("midfielder", "midfielders"),
             "FWD": ("forward", "forwards"), "any": ("player", "players")}
SECTIONS = (("GK", "Goalkeepers"), ("DEF", "Defenders"), ("MID", "Midfielders"), ("FWD", "Forwards"))
BONUS_NOTE = "Our model doesn't account for bonus points; top-ranked players tend to pick up a few extra points from bonus."
RANK_FOLLOW_UP = "Want me to compare any of these, or check one against your squad?"
RANK_FOLLOW_UP_NO_SQUAD = "Want me to compare any of these?"                # General mode: there is no squad to check against
RANK_FOLLOW_UP_NONE = "Want me to rank them with a different price or position?"
REVIEW_FOLLOW_UP = "Which player would you like me to go into, or is there anyone you'd like to bring in?"
PLAN_FOLLOW_UP = "Want me to preview any of these moves?"
PRICE_FOLLOW_UP = "Want me to look at a replacement for any of them?"
MAX_HORIZON = 8                      # what a caller may ask for; the answer covers the gameweeks that have predictions and says so
MAX_N, DEFAULT_N = 20, 10
MAX_FREE_TRANSFERS = 5               # FPL banks at most five free transfers (== squad_state.MAX_FREE_TRANSFERS; a test pins the pair)
DEFAULT_REVIEW_HORIZON = 3
WEAK_BAND_TENTHS = 5                 # "for their price": within £0.5m either way
WEAK_MIN_START = 0.5                 # USER DECISION 16 Nov: ranked only against likely starters (>= 50% for the next gameweek)
WEAK_N = 3
MINUS = "−"


# ---- small pure helpers ---------------------------------------------------------------------------------------------------

def hu(x, d=2):
    """x rounded half-up to d decimals, as a Decimal (2.675 -> 2.68; float repr, so 0.1 + 0.2 is 0.30)."""
    return Decimal(repr(float(x))).quantize(Decimal(1).scaleb(-d), rounding=ROUND_HALF_UP)


def money(tenths):
    return f"£{int(tenths) / 10:.1f}m"


def nth(k):
    k = int(k)
    return f"{k}{'th' if 10 <= k % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(k % 10, 'th')}"


def plural(n, word):
    return f"{n} {word}{'' if n == 1 else 's'}"


def gw_label(gws):
    gws = list(gws)
    return f"GW{gws[0]}" if len(gws) == 1 else f"GW{gws[0]}–{gws[-1]}"


def span_words(gws):
    return f"{gw_label(gws)} ({plural(len(gws), 'gameweek')})"


def signed(x, d=2):
    v = hu(x, d)
    return f"+{v:.{d}f}" if v > 0 else (f"{MINUS}{abs(v):.{d}f}" if v < 0 else f"{v:.{d}f}")


def money_delta(tenths):
    t = int(tenths)
    return "no change" if t == 0 else (f"+£{t / 10:.1f}m" if t > 0 else f"{MINUS}£{abs(t) / 10:.1f}m")


def day_words(dt):
    """"Wed 11 Nov" -- the day a flag was read (no leading zero, as the other tools write dates)."""
    return f"{dt:%a} {dt.day} {dt:%b}"


def built_words(dt):
    """"Wed 11 Nov 2026, 11:01 UTC" -- when the predictions were built."""
    return f"{dt:%a} {dt.day} {dt:%b} {dt:%Y}, {dt:%H:%M} UTC"


def freshness_line(built, next_update, what="Predictions"):
    """The line every code-built prediction answer carries: when the predictions were built and when the next update is due
    (`next_update` in the words the other tools use; None when the schedule has none). `what`: "Ratings" for the fixture grid."""
    line = f"{what} from the update of {built_words(built)}."
    return f"{line} Next update: {next_update}." if next_update else line


def span(first, horizon, lo, hi):
    """(the gameweeks an answer covers, the sentence that says so when fewer exist than asked). `first` = the next deadline's
    gameweek; [lo, hi] = the gameweeks the build has predictions for. An empty list: nothing to answer from."""
    h = int(horizon)
    gws = [g for g in range(int(first), int(first) + h) if int(lo) <= g <= int(hi)]
    note = None
    if gws and len(gws) < h:
        note = (f"Predictions exist for {gw_label(range(max(int(first), int(lo)), int(hi) + 1))} only, so this covers "
                f"{plural(len(gws), 'gameweek')}, not {h}.")
    return gws, note


def points_over(pts, gws):
    """A player's predicted points added over `gws` (a gameweek he has no row for -- a blank -- adds nothing), half-up 2 dp."""
    return hu(sum(float(pts.get(g) or 0.0) for g in gws))


def fixtures_cell(cal, shorts, team, gws):
    """"FUL (H), ARS (A) + EVE (H), no fixture": one entry per gameweek, a double joined with " + ". A calendar that could not
    be read (None) reads "not known" -- never "no fixture"."""
    if cal is None:
        return "not known"
    out = []
    for g in gws:
        fx = (cal or {}).get((team, int(g))) or []
        if not fx:
            out.append("no fixture")
        else:
            out.append(" + ".join(f"{(shorts or {}).get(f['opponent']) or f['opponent']} ({'H' if f['home'] else 'A'})" for f in fx))
    return ", ".join(out)


def flag_text(flag):
    """FPL's flag for one player in words: 'Doubtful — FPL: "Knock - 75% chance of playing" (as of Wed 11 Nov)'. "" for a
    player FPL does not flag. FPL's own note is quoted, never paraphrased."""
    if not flag:
        return ""
    word = str(flag.get("status_word") or "flagged")
    word = word[:1].upper() + word[1:]
    as_of = flag.get("as_of")
    when = f" (as of {day_words(as_of)})" if hasattr(as_of, "strftime") else ""
    if flag.get("news"):
        return f"{word} — FPL: \"{flag['news']}\"{when}"
    if flag.get("chance") is not None:
        return f"{word} — FPL: {int(flag['chance'])}% chance of playing{when}"
    return f"{word} — FPL{when}"


def later_line(gws, market_gw, what="the order"):
    """The sentence the system prompt requires beside any figure for a gameweek beyond the build's own: which gameweek is
    priced off the betting market and which are longer-range estimates. None when the span is the build's own gameweek only."""
    later = [g for g in gws if g != market_gw]
    if not later:
        return None
    first = f"GW{market_gw} is priced off the betting market. " if market_gw in gws else ""
    one = len(later) == 1
    return (f"{first}{gw_label(later)} {'is a' if one else 'are'} longer-range estimate{'' if one else 's'} from team strengths, with "
            f"no odds, lineups or team news yet, so {what} will move before then.")


def pct_words(p):
    """A probability as a whole percentage, the one rounding every answer uses: 0.3962 -> "40%". None -> None."""
    return None if p is None else f"{int(hu(float(p) * 100, 0))}%"


def _name(row):
    return row.get("name") or str(row.get("element"))


def _table(cols, rows):
    return ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)] + ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]


# ---- 1. rank: the true top N over the whole pool --------------------------------------------------------------------------

def rank_who(position, club, min_tenths, max_tenths):
    """Exactly what was ranked, in words: "Arsenal defenders priced £4.9m or less"."""
    who = (f"{club} " if club else "") + POS_WORDS[position][1]
    if min_tenths is not None and max_tenths is not None:
        who += f" priced {money(min_tenths)} to {money(max_tenths)}"
    elif max_tenths is not None:
        who += f" priced {money(max_tenths)} or less"
    elif min_tenths is not None:
        who += f" priced {money(min_tenths)} or more"
    return who


def rank_rows(pool, gws, position="any", sort="points", club=None, min_tenths=None, max_tenths=None):
    """Every pool player that passes the filters, in rank order, each with `total` (predicted points over gws, half-up 2 dp)
    and `value` (that shown total per £1m of today's price, half-up 2 dp). Deterministic: points -> the cheaper player, then
    name; value -> more points, then the cheaper player, then name; the element id last."""
    rows = []
    for r in pool.values():
        if r.get("price_tenths") is None:
            continue
        if position != "any" and r["position"] != position:
            continue
        if club and r["team"] != club:
            continue
        p = int(r["price_tenths"])
        if (min_tenths is not None and p < min_tenths) or (max_tenths is not None and p > max_tenths):
            continue
        total = points_over(r["pts"], gws)
        value = (total * 10 / Decimal(p)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP) if p else Decimal("0.00")
        rows.append({**r, "total": total, "value": value})
    if sort == "value":
        rows.sort(key=lambda r: (-r["value"], -r["total"], int(r["price_tenths"]), _name(r), int(r["element"])))
    else:
        rows.sort(key=lambda r: (-r["total"], int(r["price_tenths"]), _name(r), int(r["element"])))
    return rows


def rank(pool, gws, *, position="any", sort="points", n=DEFAULT_N, club=None, min_tenths=None, max_tenths=None, cal=None,
         shorts=None, flags=None, built=None, next_update=None, market_gw=None, clip=None, has_squad=True, cheapest=None,
         unrated=0):
    """The ranking answer: {"direct_reply": the text, "rows": the listed players as data, ...}. `cheapest` = the lowest price
    (tenths) at that position / club, for the sentence an empty result needs; `unrated` = how many players FPL lists through
    the same filters that this build has no prediction for (they cannot be ranked, and the answer says so)."""
    rows = rank_rows(pool, gws, position, sort, club, min_tenths, max_tenths)
    who = rank_who(position, club, min_tenths, max_tenths)
    by = "predicted points per £1m" if sort == "value" else "predicted points"
    fresh = freshness_line(built, next_update) if built is not None else None
    if not rows:
        out = [f"**No {who} in the game.**"]
        if cheapest is not None:
            out.append(f"The cheapest of the {(club + ' ') if club else ''}{POS_WORDS[position][1]} costs {money(cheapest)}.")
        out += ["", RANK_FOLLOW_UP_NONE]
        return {"direct_reply": "\n".join(out), "ranked_by": by, "gameweeks": list(gws), "pool_size": 0, "rows": []}
    top = rows[:int(n)]
    head = (f"**Top {len(top)} of {len(rows)} {who} by {by}, {span_words(gws)}.**" if len(rows) > len(top)
            else f"**All {len(rows)} {who}, by {by}, {span_words(gws)}.**")
    out = [head] + ([clip] if clip else []) + ([fresh] if fresh else []) + [""]
    label = gw_label(gws)
    cols = ["#", "Player"] + (["Pos"] if position == "any" else []) + ["Club", "Price", f"Predicted points {label}"] \
        + (["Points per £1m"] if sort == "value" else []) + [f"Fixtures {label}", "Flag"]
    table, data = [], []
    for i, r in enumerate(top, 1):
        flag = flag_text((flags or {}).get(int(r["element"])))
        fx = fixtures_cell(cal, shorts, r["team"], gws)
        table.append([i, _name(r)] + ([r["position"]] if position == "any" else []) + [r["team"], money(r["price_tenths"]), f"{r['total']:.2f}"]
                     + ([f"{r['value']:.2f}"] if sort == "value" else []) + [fx, flag])
        data.append({"rank": i, "player_id": int(r["element"]), "name": _name(r), "position": r["position"], "team": r["team"],
                     "price": round(int(r["price_tenths"]) / 10, 1), "predicted_points": float(r["total"]),
                     **({"points_per_million": float(r["value"])} if sort == "value" else {}), "fixtures": fx, "flag": flag or None})
    out += _table(cols, table)
    if sort == "value":
        how = (f"Ranked by predicted points per £1m of today's price (the points for {label} divided by the price); level values go to the "
               "player with more points, then the cheaper one.")
    else:
        how = (f"Ranked by total predicted points over {label}, every fixture in {'that gameweek' if len(gws) == 1 else 'those gameweeks'} "
               "counted; level totals go to the cheaper player, then by name.")
    all_ranked = f"All {len(rows)} {who} in the game were ranked, flagged players included."
    if unrated:
        all_ranked = (f"All {len(rows)} {who} with a prediction were ranked, flagged players included; {unrated} more that FPL lists "
                      f"{'has' if unrated == 1 else 'have'} no prediction in this update and {'is' if unrated == 1 else 'are'} not ranked.")
    out += ["", f"{how} {all_ranked}"]
    ll = later_line(gws, market_gw)
    if ll:
        out.append(ll)
    out += [BONUS_NOTE, "", RANK_FOLLOW_UP if has_squad else RANK_FOLLOW_UP_NO_SQUAD]
    return {"direct_reply": "\n".join(out), "ranked_by": by, "gameweeks": list(gws), "pool_size": len(rows), "rows": data}


# ---- 2. review: the user's own fifteen ------------------------------------------------------------------------------------

def weak_group(e, pool, first_gw):
    """The players `e` is ranked against "for his price" (USER DECISION 16 Nov): every pool player at his position, priced
    within £0.5m of him, whose chance of starting the next gameweek is at least 50% -- and himself, whatever his chance."""
    me = pool[e]
    group = {x for x, r in pool.items()
             if r["position"] == me["position"] and r.get("price_tenths") is not None
             and abs(int(r["price_tenths"]) - int(me["price_tenths"])) <= WEAK_BAND_TENTHS
             and (r.get("start") or {}).get(first_gw) is not None and float(r["start"][first_gw]) >= WEAK_MIN_START}
    group.add(e)
    return group


def weakest(squad_ids, pool, gws):
    """The WEAK_N squad players lowest in their group, worst first: [{element, rank, n, points}]. A player's rank = 1 + the
    group members with more predicted points over gws; "lowest" = rank relative to the group's size; level players go to
    fewer points, then name."""
    totals = {x: points_over(r["pts"], gws) for x, r in pool.items()}
    rows = []
    for e in squad_ids:
        if e not in pool or pool[e].get("price_tenths") is None:
            continue
        group = weak_group(e, pool, gws[0])
        rank_ = 1 + sum(1 for x in group if x != e and totals[x] > totals[e])
        rows.append({"element": e, "rank": rank_, "n": len(group), "points": totals[e],
                     "rel": (rank_ - 1) / max(1, len(group) - 1)})
    rows.sort(key=lambda d: (-d["rel"], d["points"], _name(pool[d["element"]]), d["element"]))
    return rows[:WEAK_N]


def review(squad, pool, gws, *, lineup, bank_tenths, free_transfers, cal=None, shorts=None, flags=None, built=None,
           next_update=None, market_gw=None, clip=None):
    """The whole-squad review. squad = [{"element", "sell_tenths"}] (the fifteen); lineup = {"roles": {element: (role,
    bench_order)}, "xi_points": the best XI's total for gws[0] with the captain's points counted twice} -- the line-up pick's
    own roles and its own total, never re-derived here. The total BEFORE the captain's double is the eleven starters'
    predicted points for gws[0] added from the pool's rows."""
    ids = [int(p["element"]) for p in squad]
    sells = {int(p["element"]): p.get("sell_tenths") for p in squad}
    first, label = gws[0], gw_label(gws)
    totals = {e: points_over(pool[e]["pts"], gws) if e in pool else Decimal("0.00") for e in ids}
    roles = lineup["roles"]

    def mark(e):
        role, bo = roles.get(e, ("start", None))
        return {"CAPTAIN": " (C)", "VICE": " (VC)", "start": ""}.get(role, f" (bench {bo})")

    def row(e):
        return pool.get(e) or {"element": e, "name": str(e), "position": "?", "team": "?", "price_tenths": None, "pts": {}, "start": {}}

    out = [f"**Your 15 players over {span_words(gws)}: {sum(totals.values(), Decimal('0.00')):.2f} predicted points between them.**"]
    out += ([clip] if clip else []) + ([freshness_line(built, next_update)] if built is not None else [])
    data = []
    for pos, title in SECTIONS:
        grp = sorted((e for e in ids if row(e)["position"] == pos), key=lambda e: (-totals[e], _name(row(e)), e))
        if not grp:
            continue
        table = []
        for e in grp:
            r = row(e)
            start = pct_words((r.get("start") or {}).get(first))
            fx = fixtures_cell(cal, shorts, r["team"], gws)
            flag = flag_text((flags or {}).get(e))
            table.append([_name(r) + mark(e), r["team"], money(r["price_tenths"]) if r.get("price_tenths") is not None else "—",
                          money(sells[e]) if sells.get(e) is not None else "—", f"{totals[e]:.2f}", start or "—", fx, flag])
            data.append({"player_id": e, "name": _name(r), "position": pos, "team": r["team"], "role": roles.get(e, ("start", None))[0],
                         "bench_order": roles.get(e, ("start", None))[1], "predicted_points": float(totals[e]),
                         "chance_of_starting": start, "fixtures": fx, "flag": flag or None})
        out += ["", f"**{title}**"] + _table(["Player", "Club", "Price", "Sells for", f"Predicted points {label}",
                                             f"Chance of starting GW{first}", f"Fixtures {label}", "Flag"], table)
    cap = next((e for e in ids if roles.get(e, ("", None))[0] == "CAPTAIN"), None)
    vice = next((e for e in ids if roles.get(e, ("", None))[0] == "VICE"), None)
    bench = sorted((e for e in ids if roles.get(e, ("", None))[0] == "bench"), key=lambda e: roles[e][1] or 0)
    doubled = hu(lineup["xi_points"])
    once = hu(sum(float(((pool.get(e) or {}).get("pts") or {}).get(first) or 0.0) for e in ids if roles.get(e, ("start", None))[0] != "bench"))
    ft = int(free_transfers)
    out += ["", f"**Line-up for GW{first}:** the (C), (VC) and bench marks above are the best XI from these 15 for GW{first}: "
                f"{doubled:.2f} predicted points with the captain's points counted twice ({once:.2f} before that). "
                f"Captain {_name(row(cap))}, vice-captain {_name(row(vice))}; bench in order: {', '.join(_name(row(e)) for e in bench)}.",
            f"**Money and transfers:** {money(bank_tenths)} in the bank; {plural(ft, 'free transfer')} for the GW{first} deadline."]
    weak = weakest(ids, pool, gws)
    if weak:
        out += ["", f"**Weakest {len(weak)} for their price** (each of your players is ranked on predicted points {label} against the players "
                    f"in the game at his position, priced within £0.5m of him, who have at least a 50% chance of starting GW{first}; he is "
                    "ranked against that group even when his own chance is lower):"]
        for d in weak:
            r = pool[d["element"]]
            p = int(r["price_tenths"])
            start = pct_words((r.get("start") or {}).get(first))
            out.append(f"- {_name(r)} ({r['position']}, {money(p)}{', ' + start + ' chance of starting GW' + str(first) if start else ''}): "
                       f"{d['points']:.2f} predicted points, {nth(d['rank'])} of the {d['n']} in his group "
                       f"({POS_WORDS[r['position']][1]} priced {money(p - WEAK_BAND_TENTHS)} to {money(p + WEAK_BAND_TENTHS)}).")
    ll = later_line(gws, market_gw)
    out += [""] + ([ll] if ll else []) + [BONUS_NOTE, "", REVIEW_FOLLOW_UP]
    return {"direct_reply": "\n".join(out), "gameweeks": list(gws), "players": data,
            "lineup": {"gw": first, "predicted_points_captain_doubled": float(doubled), "predicted_points_captain_once": float(once)},
            "weakest_for_price": [{"player_id": d["element"], "rank": d["rank"], "of": d["n"], "predicted_points": float(d["points"])}
                                  for d in weak]}


# ---- 3. plan: the transfer plan, from the planner's own result ----------------------------------------------------------------

def plan_steps(res):
    """[{gw, transfers, hits, hit_points, ft_before, ft_used, ft_after}] for the deadline gameweek and each later one of the plan.
    The deadline gameweek's free transfers are the planner's own (the squad's record). A pencilled-in gameweek's are derived
    by FPL's rule from the gameweek before it -- what was left, plus the one every gameweek earns, at most MAX_FREE_TRANSFERS
    (Prompt R3b: the planner's own counter is only exact in a gameweek where it limits the moves; a gameweek with no move
    read "0 available")."""
    td = res["this_deadline"]
    n0 = len(td.get("transfers") or [])
    steps = [{"gw": int(res["gw"]), "transfers": list(td.get("transfers") or []), "hits": int(td.get("hits") or 0),
              "hit_points": int(td.get("hit_cost_points") or 0), "ft_before": int(td["free_transfers_before"]),
              "ft_used": min(n0, int(td["free_transfers_before"])), "ft_after": int(td["free_transfers_after"])}]
    for s in res.get("later_steps_indicative") or []:
        n, ft = len(s.get("transfers") or []), min(MAX_FREE_TRANSFERS, steps[-1]["ft_after"] + 1)
        steps.append({"gw": int(s["gw"]), "transfers": list(s.get("transfers") or []), "hits": int(s.get("hits") or 0),
                      "hit_points": 4 * int(s.get("hits") or 0), "ft_before": ft, "ft_used": min(n, ft), "ft_after": max(0, ft - n)})
    return steps


def plan_gain(move, gw, steps, gws, pool):
    """One move's predicted gain: (gain, the incoming player's points, the outgoing player's, the gameweeks counted) -- the
    gameweeks from the move until the plan sells the incoming player again, or the end of the plan."""
    sold = next((s["gw"] for s in steps if s["gw"] > gw and any(int(t["out_id"]) == int(move["in_id"]) for t in s["transfers"])), None)
    held = [g for g in gws if g >= gw and (sold is None or g < sold)]
    a = points_over((pool.get(int(move["in_id"])) or {}).get("pts") or {}, held)
    b = points_over((pool.get(int(move["out_id"])) or {}).get("pts") or {}, held)
    return a - b, a, b, held


def plan(res, pool, *, flags=None, built=None, next_update=None, market_gw=None, names=None):
    """The transfer-plan answer from propose_transfers' own result `res` (nothing is re-solved): the moves per gameweek, each
    with its predicted gain; free transfers, hits and the bank; the line-up total both ways; and the hold baseline in a
    sentence that says exactly what it covers -- THIS gameweek only (the planner's baseline forces no transfer at the deadline
    and leaves later gameweeks free). Returns the text."""
    names = names or {}
    first, k = int(res["gw"]), int(res.get("effective_horizon") or res.get("horizon") or 1)
    gws = list(range(first, first + k))
    td, hc = res["this_deadline"], res.get("hold_comparison") or {}
    steps = plan_steps(res)

    def nm(e):
        return names.get(int(e)) or _name(pool.get(int(e)) or {"element": e})

    def who(e, fallback_pos=None, fallback_team=None):
        r = pool.get(int(e)) or {}
        return f"{nm(e)} ({r.get('position') or fallback_pos or '?'}, {r.get('team') or fallback_team or '?'})"

    n0 = len(steps[0]["transfers"])
    most = res.get("max_transfers")                      # Prompt R3b: the most transfers the whole plan may make, when the user named a number
    most = None if most is None else int(most)
    limit = "" if most is None else (", making no transfers" if most == 0 else f", using at most {plural(most, 'transfer')}")
    if n0:
        out = [f"**Transfer plan for {span_words(gws)}{limit}: {plural(n0, 'transfer')} for the GW{first} deadline, {plural(steps[0]['hits'], 'hit')}.**"]
    else:
        out = [f"**Transfer plan for {span_words(gws)}{limit}: no transfer for the GW{first} deadline.**"]
    if most == 0:
        out.append("Making no transfers across the whole plan, as you asked.")
    elif most is not None:
        made = [sum(1 for t in s["transfers"] if t.get("in_id") is not None) for s in steps]
        split = "" if k == 1 else f" ({made[0]} for the GW{first} deadline, {sum(made[1:])} pencilled in for later gameweeks)"
        out.append(f"Using at most {plural(most, 'transfer')} across the whole plan, as you asked: the plan makes {sum(made)}{split}.")
    if res.get("forced_availability_warning"):
        out.append(str(res["forced_availability_warning"]))
    if built is not None:
        out.append(freshness_line(built, next_update))
    out.append("")
    for i, s in enumerate(steps):
        g = s["gw"]
        out.append(f"**GW{g}, this deadline** (the moves you can make now):" if i == 0 else
                   f"**GW{g}, pencilled in** (decided again that week, on that week's predictions and prices):")
        moves = list(s["transfers"])
        if not moves:
            out.append("No transfer.")
        else:
            table = []
            for t in moves:
                if t.get("in_id") is None:               # a sale the plan pairs with no buy: shown, with nothing to compare
                    table.append([who(t["out_id"], t.get("position_out"), t.get("team_out"))]
                                 + ([f"£{float(t['sold_for']):.1f}m"] if i == 0 and t.get("sold_for") is not None else (["—"] if i == 0 else []))
                                 + ["—", "—", "—", "—"])
                    continue
                d, a, b, held = plan_gain(t, g, steps, gws, pool)
                table.append([who(t["out_id"], t.get("position_out"), t.get("team_out"))]
                             + ([f"£{float(t['sold_for']):.1f}m"] if i == 0 else [])
                             + [who(t["in_id"], t.get("position_in"), t.get("team_in")),
                                f"£{float(t['bought_for']):.1f}m" if t.get("bought_for") is not None else "—",
                                f"{signed(d)} ({a:.2f} against {b:.2f})", gw_label(held) if held else "—"])
            out += _table(["Out"] + (["Sells for"] if i == 0 else []) + ["In", "Costs", "Predicted gain", "Counted over"], table)
            out.append("")
        line = (f"Free transfers: {s['ft_before']} available, {s['ft_used']} used, {s['ft_after']} left. "
                f"Hits: {s['hits']} ({s['hit_points']} points).")
        if i == 0:
            line += f" Bank: £{float(td['bank_before']):.1f}m before, £{float(td['bank_after']):.1f}m after."
        out.append(line)
        if i == 0:
            cap = next((r for r in td.get("xi") or [] if r.get("role") == "CAPTAIN"), None)
            vice = next((r for r in td.get("xi") or [] if r.get("role") == "VICE"), None)
            if cap is not None and td.get("predicted_xi_points") is not None:
                xi = hu(td["predicted_xi_points"])                       # the planner's own total, captain doubled
                once = hu(sum(float(((pool.get(int(r["player_id"])) or {}).get("pts") or {}).get(g) or 0.0) for r in td["xi"]))
                after = "after these moves" if n0 else "as it stands"
                out.append(f"Line-up {after}: {xi:.2f} predicted points for GW{g} with the captain's points counted twice "
                           f"({once:.2f} before that). Captain {nm(cap['player_id'])}"
                           + (f", vice-captain {nm(vice['player_id'])}." if vice is not None else "."))
        out.append("")
    if hc.get("refused"):
        out.append("**Against making no transfer:** this comparison is withheld this week. A club's team-strength estimate has run off "
                   "inside these gameweeks, so the gap cannot be measured honestly.")
    elif n0 and hc.get("gap_objective") is not None and hc.get("gap_this_gw") is not None:
        within = "" if most is None else f", within the same limit of {plural(most, 'transfer')}"
        out.append(f"**Against making no transfer this gameweek only** (the same 15 kept for GW{first}; later gameweeks still free to "
                   f"transfer{within}): this plan's line-up scores {hu(hc['move_predicted_xi_points']):.2f} predicted points for GW{first} against "
                   f"{hu(hc['hold_predicted_xi_points']):.2f} without the moves ({signed(hc['gap_this_gw'])}, captain counted twice in "
                   f"both). On the plan's weighted total over {gw_label(gws)}, where each later gameweek counts for less, it is "
                   f"{signed(hc['gap_objective'])}.")
    if any(t.get("in_id") is not None for s in steps for t in s["transfers"]):
        out.append("Predicted gain = the incoming player's predicted points minus the outgoing player's, added over the gameweeks shown "
                   "beside it (from the move until the plan sells him again, or the end of the plan). It compares the two players only; "
                   "it is not the change in your line-up's total.")
    if res.get("locked") or res.get("banned"):
        out.append(" ".join(([f"Kept as you asked: {', '.join(str(x) for x in res['locked'])}."] if res.get("locked") else [])
                            + ([f"Left out as you asked: {', '.join(str(x) for x in res['banned'])}."] if res.get("banned") else [])))
    ids = list(dict.fromkeys(int(t[key]) for s in steps for t in s["transfers"] for key in ("out_id", "in_id") if t.get(key) is not None))
    flagged = [f"{nm(e)}: {flag_text((flags or {}).get(e))}" for e in ids if (flags or {}).get(e)]
    if flagged:
        out.append("Flags: " + "; ".join(flagged) + ".")
    ll = later_line(gws, market_gw, what="these")
    if ll:
        out.append(ll)
    rolled = res.get("rolled_transfer") or {}
    closing = rolled["question"] if (not n0 and rolled.get("offered") and rolled.get("question")) else PLAN_FOLLOW_UP
    out += [BONUS_NOTE, "", closing]
    return "\n".join(out)


# ---- 4. prices: the squad's price moves and the selling rule per player ----------------------------------------------------------

def progress_words(pct):
    """FPL's own price-change progress figure in words: above zero is toward a rise, below zero toward a fall."""
    if pct is None:
        return "no figure"
    v = float(pct)
    if v > 0:
        return f"{v:.1f}% toward a rise"
    if v < 0:
        return f"{abs(v):.1f}% toward a fall"
    return "0.0% (no progress either way)"


def prices(players, sell_price, *, seen_from, seen_to, readings):
    """The price-moves answer for a squad. players = [{"element", "name", "position", "bought", "now", "then", "pct"}], prices
    in tenths (`then` = the price at the window's first reading, None when unknown; `now` None when the latest reading has no
    price for him); `pct` = FPL's own published progress figure, carried through unchanged. sell_price(bought, now) is
    squad_state.sell_price -- the ONE implementation of FPL's selling rule. Returns the text."""
    rows = []
    for p in players:
        r = dict(p)
        if r.get("now") is not None:
            r["sells"] = sell_price(int(r["bought"]), int(r["now"]))
            r["up"], r["down"] = sell_price(int(r["bought"]), int(r["now"]) + 1), sell_price(int(r["bought"]), int(r["now"]) - 1)
            r["sells_then"] = sell_price(int(r["bought"]), int(r["then"])) if r.get("then") is not None else None
        rows.append(r)
    rows.sort(key=lambda r: (0 if r.get("pct") is not None else 1, -(float(r["pct"]) if r.get("pct") is not None else 0.0), r["name"]))

    def would(r, key):
        return f"{money(r[key])} ({money_delta(r[key] - r['sells'])})"

    out = ["**Your 15 players: FPL's price-change progress, and what each sells for.**",
           f"Prices seen from {seen_from} to {seen_to} ({plural(int(readings), 'price reading')}; \"no change\" means no net change "
           "between those two readings).", ""]
    table = []
    for r in rows:
        if r.get("now") is None:
            table.append([r["name"], r["position"], progress_words(r.get("pct")), money(r["bought"]), "not known", "not known", "—", "—", "—"])
            continue
        moved = money_delta(int(r["now"]) - int(r["then"])) if r.get("then") is not None else "—"
        table.append([r["name"], r["position"], progress_words(r.get("pct")), money(r["bought"]), money(r["now"]), money(r["sells"]),
                      moved, would(r, "up"), would(r, "down")])
    out += _table(["Player", "Pos", "FPL's progress figure", "Bought at", "Price now", "Sells for now", "Moved in this window",
                   "Sells for after one more rise", "Sells for after one fall"], table)
    known = [r for r in rows if r.get("pct") is not None]
    tail = ("The figure is FPL's own published progress toward a price change, not ours; it says what has happened so far and cannot "
            "say whether a price will change next.")
    if known:
        out += ["", f"Listed from the highest figure to the lowest. Highest: {known[0]['name']}, {progress_words(known[0]['pct'])}. "
                    f"Lowest: {known[-1]['name']}, {progress_words(known[-1]['pct'])}. {tail}"]
    else:
        out += ["", tail]
    changed = sorted((r for r in rows if r.get("now") is not None and int(r["now"]) != int(r["bought"])),
                     key=lambda r: (-(int(r["now"]) - int(r["bought"])), r["name"]))
    if changed:
        out += ["", "**The selling rule, worked out for each player whose price differs from what you paid:**"]
        for r in changed:
            rise = int(r["now"]) - int(r["bought"])
            if rise > 0:
                keep = r["sells"] - int(r["bought"])
                out.append(f"- {r['name']}: bought at {money(r['bought'])}, now {money(r['now'])}. You keep half of a rise, rounded down to "
                           f"£0.1m: half of £{rise / 10:.1f}m gives {f'£{keep / 10:.1f}m' if keep else 'nothing yet'}, so he sells for "
                           f"{money(r['sells'])}.")
            else:
                out.append(f"- {r['name']}: bought at {money(r['bought'])}, now {money(r['now'])}. A fall is yours in full, so he sells "
                           f"for {money(r['sells'])}.")
    moved = sorted((r for r in rows if r.get("now") is not None and r.get("then") is not None and int(r["now"]) != int(r["then"])),
                   key=lambda r: (-(int(r["now"]) - int(r["then"])), r["name"]))
    if moved:
        out += ["", "**Moves in this window and your sell prices:**"]
        for r in moved:
            verb = "rose" if int(r["now"]) > int(r["then"]) else "fell"
            same = r["sells"] == r["sells_then"]
            out.append(f"- {r['name']} {verb} from {money(r['then'])} to {money(r['now'])}: his sell price "
                       + (f"stayed at {money(r['sells'])}." if same else f"went from {money(r['sells_then'])} to {money(r['sells'])}."))
    out += ["", PRICE_FOLLOW_UP]
    return "\n".join(out)


# ---- Prompt R3b (2026-11-16): three more answers written by code --------------------------------------------------------------
# R3's gate (eval/reports/r3_answers.md): all six slips of Set B sat in the two number-heavy answers the model still wrote --
# the best squad (its own XI sum, "(£99.9m spent)" on the XI's header, a (C) on the vice-captain, a price band nobody
# filtered by) and the comparison ("the gap reverses", "80p cheaper") -- and the one cut-off was a 20-club fixture table.
#   best_squad    -- a whole fifteen from the build's own solve              (model_tools.get_best_squad / optimise)
#   compare       -- two or more players, gameweek by gameweek               (model_tools.compare_players)
#   fixture_grid  -- club x gameweek for all clubs, or more than five        (model_tools.get_fixtures)

BEST_FOLLOW_UP = "Want me to explain any of these picks?"
BEST_FOLLOW_UP_SQUAD = "Want me to explain any of these picks, or compare any of them with your players?"
COMPARE_FOLLOW_UP = "Want me to check either of them against your squad?"
COMPARE_FOLLOW_UP_MANY = "Want me to check any of them against your squad?"
COMPARE_FOLLOW_UP_NO_SQUAD = "Want me to compare either of them with anyone else?"      # General mode: no squad to check against
COMPARE_FOLLOW_UP_NO_SQUAD_MANY = "Want me to compare any of them with anyone else?"
GRID_FOLLOW_UP = "Want me to rank the best players from any of these clubs?"
GRID_FOLLOW_UP_MINE = "Want me to review your squad over these gameweeks?"
ROUNDING_NOTE = ("Totals are added from the unrounded predictions, so a total can differ by 0.01 from its rounded figures added up.")
PICK_BASIS = ("The build picks the fifteen with the most predicted points that FPL's squad rules and the budget allow. "
              "No other reasons are available.")
ANYONE_CAN_WIN = "Any Premier League side can beat anyone."
MAX_COMPARE = 6
GRID_MIN_CLUBS = 6                   # a request for more than 5 clubs is answered with the code-built grid
# a fixture's rating is the tenth it sits in among every fixture the update rated (1 hardest .. 10 easiest); the word is its fifth
DIFFICULTY_WORDS = {1: "very hard", 2: "very hard", 3: "hard", 4: "hard", 5: "middling", 6: "middling", 7: "easy", 8: "easy",
                    9: "very easy", 10: "very easy"}
DIFFICULTY_LEGEND = "1–2 very hard, 3–4 hard, 5–6 middling, 7–8 easy, 9–10 very easy"


def money_gap(tenths):
    """A price difference as a bare amount: 8 -> "£0.8m"."""
    return f"£{abs(int(tenths)) / 10:.1f}m"


def squad_mark(role, bench_order=None):
    """" (C)", " (VC)", " (bench 2)" -- the solver's own role for a player, as the squad review writes it."""
    if role in ("CAPTAIN", "VICE", "start"):
        return {"CAPTAIN": " (C)", "VICE": " (VC)", "start": ""}[role]
    return f" (bench {int(bench_order)})" if bench_order is not None else " (bench)"


# ---- 5. best squad: a whole fifteen from the build's own solve ------------------------------------------------------------

def best_squad(rows, gw, *, budget_tenths, cal=None, shorts=None, flags=None, built=None, next_update=None, market_gw=None,
               has_squad=False, planning_note=None, warning=None, forced=(), must_start=(), banned=(), prices_now=None):
    """The best-squad answer. rows = the solver's fifteen, each {"element", "name", "position", "team", "price_tenths" (the
    price the solve used), "points" (his predicted points for `gw`, the solve's own row), "role" (CAPTAIN / VICE / start /
    bench), "bench_order"} -- roles and bench order are the solver's, never re-derived. Every total here is one sum of those
    rows: the XI's points both ways, and the spend of the XI, the bench and the fifteen against the budget the solve was
    given. forced / must_start / banned = the names the user asked for; prices_now = {element: today's price in tenths}, for
    the line that says which prices have moved since the solve."""
    gw = int(gw)
    rows = [dict(r) for r in rows]
    label = f"GW{gw}"
    xi = [r for r in rows if r["role"] != "bench"]
    bench = sorted((r for r in rows if r["role"] == "bench"), key=lambda r: (r.get("bench_order") is None, r.get("bench_order") or 0))
    cap = next((r for r in rows if r["role"] == "CAPTAIN"), None)
    vice = next((r for r in rows if r["role"] == "VICE"), None)
    once = hu(sum(float(r["points"] or 0.0) for r in xi))
    doubled = hu(sum(float(r["points"] or 0.0) for r in xi) + (float(cap["points"] or 0.0) if cap else 0.0))
    xi_cost, bench_cost = sum(int(r["price_tenths"]) for r in xi), sum(int(r["price_tenths"]) for r in bench)
    total_cost = xi_cost + bench_cost
    left = int(budget_tenths) - total_cost
    out = [f"**Best 15 from scratch for {label} on a {money(budget_tenths)} budget: the starting XI is predicted {doubled:.2f} points "
           f"with the captain's points counted twice, {once:.2f} before that.**"]
    if warning:
        out.append(str(warning))
    if planning_note:
        out.append(str(planning_note))
    if built is not None:
        out.append(freshness_line(built, next_update))
    data = []
    for pos, title in SECTIONS:
        grp = [r for r in xi if r["position"] == pos] + [r for r in bench if r["position"] == pos]
        grp.sort(key=lambda r: (r["role"] == "bench", (r.get("bench_order") or 0) if r["role"] == "bench" else 0,
                                -hu(r["points"] or 0.0), _name(r), int(r["element"])))
        if not grp:
            continue
        table = []
        for r in grp:
            fx = fixtures_cell(cal, shorts, r["team"], [gw])
            flag = flag_text((flags or {}).get(int(r["element"])))
            table.append([_name(r) + squad_mark(r["role"], r.get("bench_order")), r["team"], money(r["price_tenths"]),
                          f"{hu(r['points'] or 0.0):.2f}", fx, flag])
            data.append({"player_id": int(r["element"]), "name": _name(r), "position": pos, "team": r["team"], "role": r["role"],
                         "bench_order": r.get("bench_order"), "price": round(int(r["price_tenths"]) / 10, 1),
                         "predicted_points": float(hu(r["points"] or 0.0)), "fixtures": fx, "flag": flag or None})
        out += ["", f"**{title}**"] + _table(["Player", "Club", "Price", f"Predicted points {label}", f"Fixtures {label}", "Flag"], table)
    line = (f"**Line-up for {label}:** the (C), (VC) and bench marks above are the build's own. "
            f"Captain {_name(cap) if cap else '—'}, vice-captain {_name(vice) if vice else '—'}; bench in order: "
            f"{', '.join(_name(r) for r in bench)}. The starting XI: {doubled:.2f} predicted points with the captain's points counted "
            f"twice, {once:.2f} before that.")
    spend = (f"**Spend:** the starting XI costs {money(xi_cost)} and the bench {money(bench_cost)}; all 15 cost {money(total_cost)}, "
             f"which leaves {money(left)} of the {money(budget_tenths)} budget in the bank.")
    out += ["", line, spend]
    asked = []
    if forced:
        asked.append(f"Put in as you asked: {', '.join(str(x) for x in forced)}"
                     + (f" (to start: {', '.join(str(x) for x in must_start)})." if must_start else "."))
    if banned:
        asked.append(f"Left out as you asked: {', '.join(str(x) for x in banned)}.")
    if asked:
        out.append(" ".join(asked))
    moved = [(r, int(prices_now[int(r["element"])])) for r in rows
             if prices_now and prices_now.get(int(r["element"])) is not None and int(prices_now[int(r["element"])]) != int(r["price_tenths"])]
    if moved:
        out.append("Prices are the ones the build used. Since then: "
                   + "; ".join(f"{_name(r)} is now {money(now)}" for r, now in moved) + ".")
    shown = sum(hu(r["points"] or 0.0) for r in xi)
    out += ["", f"Each pick's basis is his predicted points for {label}. {PICK_BASIS}"]
    if shown != once:
        out.append(ROUNDING_NOTE)
    ll = later_line([gw], market_gw, what="these picks")
    if ll:
        out.append(ll)
    out += [BONUS_NOTE, "", BEST_FOLLOW_UP_SQUAD if has_squad else BEST_FOLLOW_UP]
    return {"direct_reply": "\n".join(out), "gw": gw, "players": data,
            "xi_points": {"captain_counted_twice": float(doubled), "before_that": float(once)},
            "spend": {"xi": round(xi_cost / 10, 1), "bench": round(bench_cost / 10, 1), "all_15": round(total_cost / 10, 1),
                      "bank": round(left / 10, 1), "budget": round(int(budget_tenths) / 10, 1)}}


# ---- 6. compare: two or more players, gameweek by gameweek ---------------------------------------------------------------------

def gap_trend(first, last):
    """How the gap between two players moves from the span's first gameweek to its last. first / last = one player's shown
    points minus the other's in that gameweek (the same order both times). "reverses": the other player is ahead at the end;
    "level": the gap is the same size; "widens" / "narrows": it is larger / smaller (a gap that opens from level widens, one
    that closes to level narrows)."""
    first, last = Decimal(first), Decimal(last)
    if (first > 0 > last) or (first < 0 < last):
        return "reverses"
    if abs(first) == abs(last):
        return "level"
    return "widens" if abs(last) > abs(first) else "narrows"


def _ahead_words(d, a, b):
    """Who is ahead for a difference d = a's points minus b's: "Rice ahead by 0.75" / "level"."""
    d = Decimal(d)
    return "level" if d == 0 else f"{a if d > 0 else b} ahead by {abs(d):.2f}"


def compare(players, gws, *, cal=None, shorts=None, flags=None, built=None, next_update=None, market_gw=None, clip=None,
            has_squad=True):
    """The comparison answer. players = two or more pool rows ({"element", "name", "position", "team", "price_tenths", "pts",
    "start"}) in the order the user named them. Every figure is a pool row's own number at 2 dp half-up, or one sum /
    difference of shown figures: each player's total over `gws` (a gameweek he has no row for -- a blank -- adds nothing),
    the gap between totals, each gameweek's gap, the price difference, and how the gap moves from the first gameweek to the
    last (gap_trend). The table's columns run from the highest total to the lowest (level totals: the order named)."""
    gws = list(gws)
    label = gw_label(gws)
    rows = []
    for i, p in enumerate(players):
        cells = {g: hu((p.get("pts") or {}).get(g) or 0.0) for g in gws}
        rows.append({**p, "named": i, "cells": cells, "total": points_over(p.get("pts") or {}, gws)})
    rows.sort(key=lambda r: (-r["total"], r["named"]))
    lead, two = rows[0], len(rows) == 2
    names = [_name(r) for r in rows]

    def gap_words(a, b):
        d = a["total"] - b["total"]
        return f"{_name(a)} and {_name(b)} are level" if d == 0 else f"{_name(a)} is ahead of {_name(b)} by {d:.2f}"

    totals = ", ".join(f"{_name(r)} {r['total']:.2f}" for r in rows)
    if two:
        d = lead["total"] - rows[1]["total"]
        verdict = "They are level." if d == 0 else f"{names[0]} is ahead by {d:.2f}."
        head = f"**{names[0]} against {names[1]} on predicted points, {span_words(gws)}: {totals}. {verdict}**"
    else:
        head = (f"**{len(rows)} players on predicted points, {span_words(gws)}, highest total first: {totals}. "
                + "; ".join(gap_words(lead, r) for r in rows[1:]) + ".**")
    out = [head] + ([clip] if clip else []) + ([freshness_line(built, next_update)] if built is not None else [])
    flagged = [f"{_name(r)}: {flag_text((flags or {}).get(int(r['element'])))}" for r in rows if (flags or {}).get(int(r["element"]))]
    none_flagged = "Neither is flagged by FPL." if two else "None of them is flagged by FPL."
    out.append(("Flags: " + "; ".join(flagged) + ".") if flagged else none_flagged)
    out.append("")
    table = []
    for g in gws:
        cells = []
        for r in rows:
            fx = fixtures_cell(cal, shorts, r["team"], [g]) if cal is not None else None
            cells.append(f"{r['cells'][g]:.2f}" + (f" — {fx}" if fx else ""))
        best = max(r["cells"][g] for r in rows)
        top = [_name(r) for r in rows if r["cells"][g] == best]
        if two:
            last = _ahead_words(rows[0]["cells"][g] - rows[1]["cells"][g], names[0], names[1])
            last = last.replace(" ahead by ", " by ")
        else:
            last = top[0] if len(top) == 1 else " and ".join(top) + " level"
        table.append([f"GW{g}"] + cells + [last])
    if two:
        d = lead["total"] - rows[1]["total"]
        end = "level" if d == 0 else f"{names[0]} by {d:.2f}"
    else:
        tops = [_name(r) for r in rows if r["total"] == lead["total"]]
        end = tops[0] if len(tops) == 1 else " and ".join(tops) + " level"
    table.append([f"**Total {label}**"] + [f"**{r['total']:.2f}**" for r in rows] + [end])
    out += _table(["Gameweek"] + [f"{_name(r)} ({r['team']}, {r['position']})" for r in rows] + ["Ahead" if two else "Most"], table)
    out.append("")
    # the gap, gameweek by gameweek, and how it moves across the span -- each other player against the leader
    if len(gws) > 1:
        for r in rows[1:]:
            first, last = lead["cells"][gws[0]] - r["cells"][gws[0]], lead["cells"][gws[-1]] - r["cells"][gws[-1]]
            n_a = sum(1 for g in gws if lead["cells"][g] > r["cells"][g])
            n_b = sum(1 for g in gws if lead["cells"][g] < r["cells"][g])
            n_l = len(gws) - n_a - n_b
            counts = (f"{_name(lead)} has the higher figure in {n_a} of the {len(gws)} gameweeks, {_name(r)} in {n_b}"
                      + (f", and they are level in {n_l}" if n_l else "") + ".")
            word = {"reverses": "reverses", "level": "stays level", "widens": "widens", "narrows": "narrows"}[gap_trend(first, last)]
            out.append(f"**The gap ({_name(lead)} and {_name(r)}):** {counts} From GW{gws[0]} to GW{gws[-1]} it {word}: "
                       f"{_ahead_words(first, _name(lead), _name(r))} in GW{gws[0]}, {_ahead_words(last, _name(lead), _name(r))} in "
                       f"GW{gws[-1]} (the first and the last gameweek compared).")
    priced = [r for r in rows if r.get("price_tenths") is not None]
    if len(priced) == len(rows):
        if two:
            pd_ = int(rows[0]["price_tenths"]) - int(rows[1]["price_tenths"])
            each = f"{names[0]} {money(rows[0]['price_tenths'])}, {names[1]} {money(rows[1]['price_tenths'])}"
            out.append(f"**Price:** {each}: " + ("they cost the same." if pd_ == 0 else
                                                 f"{names[1] if pd_ > 0 else names[0]} is {money_gap(pd_)} cheaper."))
        else:
            bits = [f"{names[0]} {money(lead['price_tenths'])}"]
            for r in rows[1:]:
                pd_ = int(r["price_tenths"]) - int(lead["price_tenths"])
                rel = "the same price" if pd_ == 0 else f"{money_gap(pd_)} {'cheaper' if pd_ < 0 else 'more expensive'} than {names[0]}"
                bits.append(f"{_name(r)} {money(r['price_tenths'])} ({rel})")
            out.append("**Price:** " + "; ".join(bits) + ".")
    starts = [(r, pct_words((r.get("start") or {}).get(gws[0]))) for r in rows]
    if all(s for _, s in starts):
        out.append(f"**Chance of starting GW{gws[0]}:** " + ", ".join(f"{_name(r)} {s}" for r, s in starts) + ".")
    if any(sum(r["cells"].values(), Decimal("0.00")) != r["total"] for r in rows):
        out.append(ROUNDING_NOTE)
    ll = later_line(gws, market_gw, what="these")
    if ll:
        out.append(ll)
    follow = ((COMPARE_FOLLOW_UP if two else COMPARE_FOLLOW_UP_MANY) if has_squad
              else (COMPARE_FOLLOW_UP_NO_SQUAD if two else COMPARE_FOLLOW_UP_NO_SQUAD_MANY))
    out += [BONUS_NOTE, "", follow]
    data = [{"player_id": int(r["element"]), "name": _name(r), "position": r["position"], "team": r["team"],
             "price": None if r.get("price_tenths") is None else round(int(r["price_tenths"]) / 10, 1),
             "predicted_points_total": float(r["total"]), "predicted_points_by_gw": {int(g): float(v) for g, v in r["cells"].items()},
             "flag": flag_text((flags or {}).get(int(r["element"]))) or None} for r in rows]
    return {"direct_reply": "\n".join(out), "gameweeks": gws, "players": data,
            "ahead": None if lead["total"] == rows[1]["total"] else int(lead["element"])}


# ---- 7. fixture grid: club x gameweek ---------------------------------------------------------------------------------------

def gws_words(gws):
    """"GW11–15" for a run of gameweeks, "GW11, GW12, GW14" when one is missing from the run."""
    gws = list(gws)
    return gw_label(gws) if gws == list(range(gws[0], gws[-1] + 1)) else ", ".join(f"GW{g}" for g in gws)


def difficulty_words(attack, defence):
    """One fixture's two ratings in words: "scoring easy (8), clean sheet middling (5)"."""
    return f"scoring {DIFFICULTY_WORDS[int(attack)]} ({int(attack)}), clean sheet {DIFFICULTY_WORDS[int(defence)]} ({int(defence)})"


def grid_cell(entry, shorts=None, with_day=False):
    """One club's cell for one gameweek. entry = "blank" (no fixture in the calendar), "played" (kicked off already), None
    (a fixture exists but is not among the ones asked for), or the gameweek's fixtures as a list of {"opponent", "home",
    "attack", "defence", "status", "kickoff_day"} -- two for a double, whose ratings are the gameweek's and are said once."""
    if entry == "blank":
        return "no fixture"
    if entry == "played":
        return "already played"
    if not entry:
        return "—"
    opps = " + ".join(f"{(shorts or {}).get(f['opponent']) or f['opponent']} ({'H' if f['home'] else 'A'})"
                      + (f", {f['kickoff_day']}" if with_day and f.get("kickoff_day") else "") for f in entry)
    if any(f.get("status") in ("played", "in progress") for f in entry):
        return f"{opps}: {entry[0]['status']}"
    a, d = entry[0].get("attack"), entry[0].get("defence")
    if a is None or d is None:
        return f"{opps}: not rated yet"
    return f"{opps}: {difficulty_words(a, d)}" + (" (the two fixtures together)" if len(entry) > 1 else "")


def _run_order(sums, n=3):
    """(highest, lowest) lists of (club, sum) -- three each, plus any club level with the third; every club once, highest
    first, when there are fewer than eight."""
    ranked = sorted(sums.items(), key=lambda kv: (-kv[1], kv[0]))
    if len(ranked) < 8:
        return ranked, None
    top = [kv for kv in ranked if kv[1] >= ranked[n - 1][1]]
    low = sorted((kv for kv in ranked if kv[1] <= ranked[-n][1]), key=lambda kv: (kv[1], kv[0]))
    return top, low


def fixture_grid(clubs, gws, cells, *, shorts=None, players=None, deadline=None, built=None, next_update=None, market_gw=None,
                 all_clubs=True, mine=False):
    """The fixture grid: one row a club, one column a gameweek. cells = {(club, gw): entry} (grid_cell); players = {club:
    "Raya (GK), Saliba (DEF)"} for the user's own players (the "Your players" column); deadline = the next-deadline line as
    the clock helper writes it. Under the table, each club's scoring ratings and clean-sheet ratings are added up over the
    gameweeks shown -- two separate sums, never one -- and the highest and lowest runs are named."""
    clubs, gws = list(clubs), list(gws)
    one = len(gws) == 1
    span_ = f"{gws_words(gws)} ({plural(len(gws), 'gameweek')})"
    if mine:
        head = f"**Your players' fixtures, {span_}: the {plural(len(clubs), 'club')} in your squad.**"
    elif all_clubs:
        head = f"**Fixtures for all {len(clubs)} clubs, {span_}.**"
    else:
        head = f"**Fixtures for {plural(len(clubs), 'club')}, {span_}.**"
    out = [head] + ([f"{deadline}."] if deadline else [])
    if built is not None:
        out.append(freshness_line(built, next_update, what="Ratings"))
    out.append("")
    table = []
    for c in clubs:
        table.append([c] + ([players.get(c) or "—"] if players is not None else [])
                     + [grid_cell(cells.get((c, g)), shorts, with_day=one) for g in gws])
    out += _table(["Club"] + (["Your players"] if players is not None else []) + [f"GW{g}" for g in gws], table)
    out += ["", "How to read a cell: the opponent (H = at home, A = away), then two separate ratings of that fixture for the club "
                "in the row: how easy it is to score in, and how easy a clean sheet is. Each is the tenth the fixture sits in among "
                f"every fixture this update rated, 1 (hardest) to 10 (easiest): {DIFFICULTY_LEGEND}. The two often disagree and "
                "are never merged into one."]
    shown = [cells.get((c, g)) for c in clubs for g in gws]
    if any(e is None for e in shown):
        out.append("A dash: the club has a fixture that gameweek, beyond the number of fixtures asked for.")
    rated = {(c, g): e for (c, g), e in cells.items() if isinstance(e, list) and e and e[0].get("attack") is not None
             and e[0].get("defence") is not None and not any(f.get("status") in ("played", "in progress") for f in e)}
    rated_gws = sorted({g for (_c, g) in rated})
    unrated_gws = [g for g in gws if any(isinstance(cells.get((c, g)), list) and cells.get((c, g)) and (c, g) not in rated
                                         and not any(f.get("status") in ("played", "in progress") for f in cells[(c, g)]) for c in clubs)]
    if rated and len(rated_gws) > 1 and len(clubs) > 1:
        att = {c: sum(int(rated[(c, g)][0]["attack"]) for g in gws if (c, g) in rated) for c in clubs}
        dfn = {c: sum(int(rated[(c, g)][0]["defence"]) for g in gws if (c, g) in rated) for c in clubs}
        over = gws_words(rated_gws)

        def run(sums):
            top, low = _run_order(sums)
            listed = ", ".join(f"{c} {v}" for c, v in top)
            return f"highest {listed}; lowest {', '.join(f'{c} {v}' for c, v in low)}" if low else f"highest first: {listed}"

        out += ["", f"**Runs over {over}** (each club's ratings added up over those gameweeks; a gameweek with no fixture adds nothing):",
                f"- Scoring ratings: {run(att)}.", f"- Clean-sheet ratings: {run(dfn)}."]
    if unrated_gws:
        out.append(f"{', '.join(f'GW{g}' for g in unrated_gws)}: scheduled but not rated yet; this update rates "
                   f"{gws_words(rated_gws) if rated_gws else 'no gameweek'} only. That is a missing rating, not an easy fixture.")
    ll = later_line([g for g in gws if g in rated_gws], market_gw, what="these ratings") if rated_gws else None
    if ll:
        out.append(ll)
    out += [ANYONE_CAN_WIN, "", GRID_FOLLOW_UP_MINE if mine else GRID_FOLLOW_UP]
    return "\n".join(out)
