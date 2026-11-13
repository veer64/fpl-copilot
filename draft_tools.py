"""The squad tools inside a DRAFT chat's turn (Prompt W11, 2026-11-12) -- model_tools routes get_my_squad, get_my_xi,
set_my_squad, propose_transfers, get_my_points, get_wildcard_gap and get_price_movements' squad list here when the turn
channel says the turn is the user's draft chat (turn_context "draft"). Every other turn never reaches this module, so their
outputs are byte-identical.

The draft's rules (drafts.py): changes are free and unlimited; the only limits are £100.0m at CURRENT prices and FPL's squad
rules. No free transfers, hits or bank. A write needs a preview ticket exactly as a real squad write does (squad_previews):
a preview in an earlier turn, the same change, the same draft version; the ticket's fingerprint is drafts.fingerprint
("draft:"-prefixed). Inside a turn nothing is fetched from FPL: the cached bootstrap, else the local snapshot, else
players_live (team_card's allow_fetch=False). Predicted points always come from the LATEST predictions for the next deadline
(the production frame, as on the real team card)."""
import time
from decimal import ROUND_HALF_UP, Decimal

import datewords
import drafts
import squad_previews
import turn_context

WHAT_THIS_IS = ("This is the user's DRAFT team: 15 players built from our predictions, NOT entered in FPL. Changes are free "
                "and unlimited; the only limits are the £100.0m budget at current FPL prices and FPL's squad rules. There are "
                "no free transfers, hits or bank.")
TO_CHANGE = ("To change the draft, call set_my_squad with confirm=false (a preview the user must say yes to); apply it with "
             "confirm=true and the preview_ticket only after the user says yes in their next message. To suggest changes, "
             "call propose_transfers: in a draft it returns the best free swaps with their numbers.")
# Prompt W11f V3 (2026-11-13): "for his price" IS the human explanation, so value_facts states it (V1) and a value remark is
# allowed when it matches; the baseline's false claims were ranks the model worked out, so pick_rank states those.
# Prompt W11g (2026-11-13): an explanation of the picks is written by CODE (explain_my_draft, below) and shown as the reply;
# the model never writes one. Other answers that touch a pick (a swap, the captain) keep the W11f rule.
REASONS_RULE = ("To explain, talk through or justify the picks, call explain_my_draft; never write your own explanation. For "
                "any named swap, always preview it with set_my_squad first; never judge affordability yourself. In "
                "any other answer that touches a pick, use only how_picked, budget_line, and each player's pick_reason, "
                "pick_rank, value_facts and breakdown parts; his predicted points, price, club and next fixture are facts on "
                "his row. A value remark (\"for his price\", \"cheap\", \"good value\") is allowed only as his value_facts "
                "state it: his predicted points per £1m, or his rank at his position among the players at his price or less. "
                "A rank (biggest, second, third, lowest, strongest) only as pick_rank or value_facts states it. Never say "
                "\"almost all\", \"entirely\" or \"mostly\" about a share: give the share (captain_points.points_share, "
                "budget_line). Any other causal reason counts as invented: fixtures (easy, good, tough or hard), form, minutes, "
                "risk, upside, ceiling, playing style, formation, or budget strategy (one player's price explaining another's); "
                "so does any other claim about how the build works. Quote each number exactly as it is here.")
EXPLAIN_ANSWER_RULE = ("To explain, talk through or justify the squad or any player in it, call explain_my_draft: detail "
                       "'each_player' when the user asks about every / each player or player by player, detail 'summary' "
                       "otherwise, and player=<his name> for one player. For any captain or vice-captain question about the "
                       "draft, call explain_my_draft with detail 'captain'. Its text is shown to the user as your reply; never "
                       "write your own explanation of the picks.")
# Prompt W11h H3 (the owner's wording): every code-built answer ends with this follow-up -- fixed text, no claim. The website's
# chips under such an answer ("Explain one player", "Bring someone in") answer it (web/lib/draft-chips.ts, the same text).
EXPLAIN_FOLLOW_UP = "Which player would you like me to go into, or is there anyone you'd like to bring in?"
BONUS_NOTE = "Our model doesn't account for bonus points; top-ranked players tend to pick up a few extra points from bonus."
ROLE_WORDS = {"CAPTAIN": "captain", "VICE": "vice-captain", "start": "starting"}
SECTIONS = (("GK", "Goalkeepers"), ("DEF", "Defenders"), ("MID", "Midfielders"), ("FWD", "Forwards"))
POSITION_NAMES = {"GK": "Goalkeeper", "DEF": "Defender", "MID": "Midfielder", "FWD": "Forward"}
# W11c R4: every money figure also as it is said ("£0.1m over"), so a reply quotes it instead of restating or rounding it
MONEY_PLAIN = ("price", "out_price", "in_price", "value", "value_before", "value_after", "budget", "instead_of_price",
               "replaces_price")
MONEY_LEFT = ("left", "left_before", "left_after")
MONEY_OVER = ("over", "over_after", "over_by")
# Prompt W11b (2026-11-13): the numbers the W11 eval caught the agent working out itself now come from the tools, and the
# steps to enter the draft in FPL come from get_my_squad -- digit-free, so no reply copies an example team ID.
NUMBERS_NOTE = ("Quote these numbers exactly as they are here; do not add, subtract, double or estimate any number yourself. "
                "The captain's points with the armband are captain_points.with_armband; the XI's total (captain counted twice) "
                "is predicted_xi_points; the money is value and left (or over). A swap's price difference and the money "
                "left after it come from set_my_squad: preview the swap (confirm=false) and quote its numbers.")
ENTER_IN_FPL = {
    "steps": ["Go to fantasy.premierleague.com and sign in, or create a free account.",
              "Create your team with these fifteen players (the guide lists them with prices), set the same captain, "
              "vice-captain and bench order, and save it.",
              "Open the Points tab and copy the link from the address bar. It looks like "
              "fantasy.premierleague.com/entry/<your team ID>/ followed by the gameweek: the number after /entry/ is your "
              "team ID.",
              "Back here, open the guide with the \"How to enter it\" link above the chat and press \"Add my team ID\" to add "
              "that link or number."],
    "guide": ("The \"How to enter it\" link above the chat opens the guide: the fifteen by position with prices, Copy list, "
              "these steps and the \"Add my team ID\" button."),
    "prices_note": "FPL prices change daily: if a player now costs more and the fifteen no longer fit, ask for a swap here.",
    "how_to_answer": ("Give these steps as they are. Write the link exactly as fantasy.premierleague.com/entry/<your team ID>/ "
                      "and never put an example number in it or anywhere else."),
}


def _mt():
    import model_tools
    return model_tools


def _row(d):
    return drafts.read(int(d["user_id"]))


def _money_said(k, v):
    if k in MONEY_PLAIN:
        return f"£{v:.1f}m"
    if k in MONEY_LEFT:
        return f"£{v:.1f}m left"
    if k in MONEY_OVER:
        return f"£{v:.1f}m over"
    if k == "price_difference":
        return "the same price" if v == 0 else f"£{abs(v):.1f}m {'more' if v > 0 else 'less'}"
    return None


def _said(x):
    """W11c R4: beside every money number of a draft tool's answer, `<key>_text` -- the figure exactly as it is said."""
    if isinstance(x, dict):
        add = {}
        for k, v in x.items():
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                t = _money_said(k, v)
                if t is not None:
                    add[f"{k}_text"] = t
            else:
                _said(v)
        x.update(add)
    elif isinstance(x, list):
        for v in x:
            _said(v)
    return x


def _next_words(ctx, element, gw):
    """W11c R3: a player's next fixture as the card shows it ("FUL (H)"), or that he has none in the gameweek; None when the
    fixtures are not loaded (a cold cache inside a turn never fetches), so unknown never reads as a blank."""
    if getattr(ctx, "fixtures", None) is None:
        return None
    team = (ctx.elements.get(int(element)) or {}).get("team")
    nf = ctx.next_fixture(team) if team is not None else None
    if not nf:
        return f"no fixture in GW{gw}" if gw is not None else None
    more = f" + {nf['n'] - 1} more" if nf.get("n", 1) > 1 else ""
    return f"{nf['opp']} ({'H' if nf['home'] else 'A'}){more}"


def _bench_weight():
    from optimize import resolve_bench_weight
    return resolve_bench_weight()


def _how_picked(gw, n_changes):
    w = _bench_weight()
    out = (f"The 15 were picked by our build as the squad with the most predicted points for GW{gw}: the XI's predicted "
           f"points with the captain counted twice, plus {w:g} × the bench's, within £100.0m at current prices and FPL's "
           "squad rules (2 GK, 5 DEF, 5 MID, 3 FWD; at most 3 per club). The build's score is the XI's predicted points "
           f"with the captain counted twice, plus {w:g} × the bench's; each pick_reason says how much of it the best legal "
           "alternative would lose.")
    if n_changes:
        out += f" Since then the user has changed the draft {n_changes} time{'s' if n_changes != 1 else ''}."
    return out


def _no_draft():
    return {"draft": True, "error": "the user has no draft team any more (it was deleted); nothing to read or change"}


def _pool_points(gw):
    """{element: e_points} of the LATEST production frame for `gw`, with its build time; ({}, None) without one."""
    try:
        pool, _cutoff, built = _mt()._load_pool(gw=int(gw))
        return {int(e): round(float(p), 2) for e, p in zip(pool["element"], pool["e_points"])}, built
    except Exception:                                   # noqa: BLE001 -- no frame, or gw outside its range
        return {}, None


def _next_gw():
    try:
        return _mt()._current_gw()
    except RuntimeError:
        return None


def _rows(doc, prices, points, shorts=None, nexts=None):
    out = []
    for p in doc["players"]:
        e = int(p["element"])
        out.append({"player_id": e, "name": p["name"], "short_name": (shorts or {}).get(e) or p["name"],   # FPL's web_name
                    "position": p["position"], "team": p["team"], "role": p["role"],
                    "bench_order": p.get("bench_order"), "price": drafts.money(prices.get(e)),
                    "e_points": points.get(e)})
        if nexts is not None:
            out[-1]["next_fixture"] = nexts.get(e)
        _armband(out[-1])
    return out


def _armband(row):
    """W11b F1: the captain's row carries his points WITH the armband (doubled), so no reply doubles them."""
    if row["role"] == "CAPTAIN" and row.get("e_points") is not None:
        row["e_points_with_armband"] = round(2 * row["e_points"], 2)
    return row


def _captain_range(player_id, gw):
    """W11e E3: the captain's P10 / P50 / P90 for the gameweek from model_tools.get_prediction -- the source get_player_card
    shows (its quantiles block); None when the run did not compute them or there is no row."""
    if gw is None:
        return None
    try:
        pred = _mt().get_prediction(int(player_id), gw=int(gw))
    except Exception:                                   # noqa: BLE001 -- the rest of the answer stands
        return None
    q = (pred or {}).get("quantiles") or {}
    row = next((r for r in q.get("per_gw") or [] if r.get("gw") in (None, int(gw))), None) if q.get("computed") else None
    if not row or row.get("p50") is None:
        return None
    return {"p10": round(float(row["p10"]), 2), "p50": round(float(row["p50"]), 2), "p90": round(float(row["p90"]), 2),
            "p10_unusable": bool(row.get("p10_unusable"))}


def _captain_points(xi, gw=None):
    cap = next((r for r in xi if r["role"] == "CAPTAIN"), None)
    if cap is None or cap.get("e_points") is None:
        return None
    short = cap.get("short_name") or cap["name"]
    out = {"player_id": cap["player_id"], "name": cap["name"], "short_name": short,
           "e_points": cap["e_points"], "with_armband": cap["e_points_with_armband"]}
    rng = _captain_range(cap["player_id"], gw)                       # W11e E3
    out["range"] = rng
    out["range_with_armband"] = None if rng is None else {k: round(2 * rng[k], 2) for k in ("p10", "p50", "p90")}
    others = sorted((r for r in xi if r["player_id"] != cap["player_id"] and r.get("e_points") is not None),
                    key=lambda r: (-r["e_points"], r["player_id"]))
    nb = others[0] if others else None
    out["next_best"] = None if nb is None else {
        "player_id": nb["player_id"], "name": nb["name"], "short_name": nb.get("short_name") or nb["name"],
        "e_points": nb["e_points"], "margin": round(cap["e_points"] - nb["e_points"], 2)}
    # the W11e dev smoke doubled the margin ("a 2.46-point edge"): captaining him rather than the next-best adds it ONCE
    out["captaincy_edge"] = None if nb is None else {"over": out["next_best"]["short_name"], "points": out["next_best"]["margin"]}
    ranked = sorted((r for r in xi if r.get("e_points") is not None), key=lambda r: (-r["e_points"], r["player_id"]))
    ranges = {cap["player_id"]: out["range_with_armband"]}
    out["captain_options"] = [_option(r, ranked, gw, ranges) for r in ranked[:3]]                 # W11h H1
    top = {r["player_id"] for r in ranked[:3]}
    out["extra_options"] = [_option(r, ranked, gw, ranges) for r in ranked                        # the captain / vice
                            if r["role"] in ("CAPTAIN", "VICE") and r["player_id"] not in top]   # when not in the top 3
    words = f"{short}: {cap['e_points']:.2f} predicted points, {cap['e_points_with_armband']:.2f} with the armband"
    if rng is not None:                                              # W11h H2: one range, said with its scale
        words += f"; {_armband_words(out['range_with_armband'])}"
    if nb is not None:
        m = out["next_best"]["margin"]
        nbs = out["next_best"]["short_name"]
        words += (f"; {abs(m):.2f} {'more' if m >= 0 else 'fewer'} than the next-best option, {nbs} "
                  f"({nb['e_points']:.2f}); captaining {short} rather than {nbs} adds {m:.2f} to the XI's predicted total "
                  "(the armband counts one player twice, so the edge is the margin itself, not double it)")
    share = _points_share(cap)                                         # W11g G5: a share, never "almost all"
    out["points_share"] = share
    if share is not None:
        words += (f"; {share['part']} {share['points']:.2f} of his {share['of']:.2f} predicted points "
                  f"({share['percent']}%)")
    out["captain_words"] = words + "."
    return out


def _half_up_int(num, den):
    return int((Decimal(str(num)) * 100 / Decimal(str(den))).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def _armband_words(a):
    """W11h H2: a likely range WITH the armband as one self-contained phrase -- never beside the bare range."""
    return f"with the armband: low {a['p10']:.1f}, middle {a['p50']:.1f}, top {a['p90']:.1f}"


def _option(r, ranked, gw, ranges):
    """W11h H1: one captain option's own facts -- points, with the armband, his likely range WITH the armband, his biggest
    part's share, his chance of 60+ minutes and his margin over the next option in the XI by predicted points."""
    pid = r["player_id"]
    if pid not in ranges:
        rng = _captain_range(pid, gw)
        ranges[pid] = None if rng is None else {k: round(2 * rng[k], 2) for k in ("p10", "p50", "p90")}
    i = next(k for k, x in enumerate(ranked) if x["player_id"] == pid)
    nxt = ranked[i + 1] if i + 1 < len(ranked) else None
    b = r.get("breakdown") or {}
    return {"player_id": pid, "short_name": r.get("short_name") or r["name"], "role": r["role"], "team": r.get("team"),
            "e_points": r["e_points"], "with_armband": round(2 * r["e_points"], 2), "range_with_armband": ranges[pid],
            "points_share": _points_share(r), "chance_of_60_plus": b.get("chance_of_60_plus"),
            "margin_to_next": None if nxt is None else {"short_name": nxt.get("short_name") or nxt["name"],
                                                        "e_points": nxt["e_points"],
                                                        "points": round(r["e_points"] - nxt["e_points"], 2)}}


def _points_share(row):
    """W11g G5 / W11h H1: the share of his predicted points that his biggest part makes -- {"part", "points", "of",
    "percent"}, from his own breakdown; None without one."""
    parts = (row.get("breakdown") or {}).get("parts") or []
    if not parts or not row.get("e_points"):
        return None
    part = max(parts, key=lambda x: x["points"])
    return {"part": part["part"], "points": part["points"], "of": row["e_points"],
            "percent": _half_up_int(f"{part['points']:.2f}", f"{row['e_points']:.2f}")}


def squad_explanation_reply(user_id):
    """W11e E2 / W11g G4: the "Why these players?" chip's answer, from code ($0, no model call): explain_my_draft's summary --
    the same builder the model's tool uses. NoDraft without a draft."""
    sq = get_my_squad({"user_id": int(user_id)})
    if sq.get("error"):
        raise drafts.NoDraft(str(user_id))
    return explain_text(sq, "summary")


# ---- W11g G1: the explanation, written by code ------------------------------------------------------------------------
# W11f measured the free-form walkthrough: ~70 facts per reply, and about half the replies carried one slip. Here every
# sentence is assembled from the row's own fields: the price relation from the two prices, the shares computed, the rank and
# value phrases copied from pick_rank / value_facts. Tests/test_drafts.py G2 checks each rule over random drafts.

class NotInDraft(ValueError):
    pass


def _tenths(m):
    return int(round(float(m) * 10))


def _price_relation(price, alt_price):
    """'the same price' / '£3.6m cheaper' / '£0.8m dearer': the alternative's price against his."""
    d = _tenths(alt_price) - _tenths(price)
    return "the same price" if d == 0 else f"£{abs(d) / 10:.1f}m {'cheaper' if d < 0 else 'dearer'}"


def _sq_rows(sq):
    return [r for pos, _ in SECTIONS for r in sq["squad_by_position"].get(pos) or []]


def _parts_words(r):
    parts = (r.get("breakdown") or {}).get("parts") or []
    return ", ".join(f"{x['part']} {x['points']:+.2f}" for x in parts)


def _pick_sentence(r):
    alt, loss = r.get("best_alternative"), r.get("build_score_loss")
    if alt is None or loss is None:
        return "No legal alternative fits his place within £100.0m and FPL's squad rules." if r.get("pick_reason") else None
    rel = f", {_price_relation(r['price'], alt['price'])}" if r.get("price") is not None else ""
    where = f"{alt['short_name']} (£{alt['price']:.1f}m{rel})"
    if loss < 0:
        return f"Not the build's pick now: {where} would raise the build's score by {-loss:.2f}."
    out = f"The best legal alternative, {where}, would lower the build's score by {loss:.2f}"
    pr = r.get("pick_rank")
    if pr:
        out += f": {_nth(pr['rank'], pr['joint'], 'biggest')} of the {pr['of']} picks"
    return out + "."


def _player_line(r):
    role = ROLE_WORDS.get(r["role"]) or f"bench {r.get('bench_order')}"
    price = f"£{r['price']:.1f}m, " if r.get("price") is not None else ""
    bits = []
    if r.get("e_points") is not None:
        parts = _parts_words(r)
        bits.append(f"{r['e_points']:.2f} predicted points" + (f": {parts}." if parts else "."))
    pick = _pick_sentence(r)
    if pick:
        bits.append(pick)
    v = r.get("value_facts")
    if v:
        bits.append(v["words"] + ".")
    return f"- **{r['short_name']}** ({r['team']}, {price}{role}): " + " ".join(bits)


def _head(sq):
    w = _bench_weight()
    head = (f"How the 15 were picked: the most predicted points for GW{sq.get('gw')}, the XI's (captain counted twice) plus "
            f"{w:g} × the bench's, within £100.0m and FPL's squad rules. Each player's reason is what the best legal "
            "alternative would cost the build's score.")
    n = int(sq.get("changes_since_build") or 0)
    if n:
        head += f" You have changed it {n} time{'s' if n != 1 else ''} since."
    return head


def _captain_line(sq):
    cap = sq.get("captain_points")
    if not cap:
        return None
    out = f"Captain: {cap['short_name']}, {cap['e_points']:.2f} predicted points, {cap['with_armband']:.2f} with the armband"
    share = cap.get("points_share")
    if share:
        out += f"; {share['part']} {share['points']:.2f} of his {share['of']:.2f} predicted points ({share['percent']}%)"
    return out + "."


def _money_line(sq, rows):
    left = sq.get("left_text") or (f"£{sq['left']:.1f}m left" if sq.get("left") is not None else None)
    over = sq.get("over_text") or (f"£{sq['over']:.1f}m over" if sq.get("over") is not None else None)
    tail = f" {over} £100.0m." if over else (f" {left[0].upper()}{left[1:]}." if left else "")
    return f"Budget: {_budget_line(rows)}{tail}"


def _biggest_picks(rows, n=4):
    picks = sorted((r for r in rows if r.get("build_score_loss") is not None and r["build_score_loss"] > 0
                    and r.get("best_alternative") and r.get("price") is not None),
                   key=lambda r: (-r["build_score_loss"], r["player_id"]))[:n]
    if not picks:
        return None
    return ("Biggest picks, by what the best legal alternative would cost the build's score: "
            + ", ".join(f"{r['short_name']} {r['build_score_loss']:.2f} ({r['best_alternative']['short_name']}, "
                        f"£{r['best_alternative']['price']:.1f}m, {_price_relation(r['price'], r['best_alternative']['price'])})"
                        for r in picks) + ".")


def _norm(t):
    import unicodedata
    return "".join(c for c in unicodedata.normalize("NFKD", str(t)) if not unicodedata.combining(c)).lower().strip()


def _find_player(rows, name):
    """The draft player a name means: exactly his short or full name, else every word of the name in his, else a prefix."""
    q = _norm(name)
    exact = [r for r in rows if q in (_norm(r["short_name"]), _norm(r["name"]))]
    if len(exact) == 1:
        return exact[0]
    words = q.split()
    def has_words(r):
        mine = set(_norm(r["name"]).split()) | set(_norm(r["short_name"]).split())
        return all(w in mine for w in words)
    hits = exact or [r for r in rows if has_words(r)] or \
        [r for r in rows if any(x.startswith(q) for x in _norm(r["name"]).split() + _norm(r["short_name"]).split())]
    if len(hits) != 1:
        names = ", ".join(r["short_name"] for r in rows)
        what = "matches several of" if hits else "is not one of"
        raise NotInDraft(f"{name} {what} the draft's 15 players: {names}.")
    return hits[0]


def _option_line(o):
    role = ROLE_WORDS.get(o["role"]) or "bench"
    team = f"{o['team']}, " if o.get("team") else ""
    out = f"- **{o['short_name']}** ({team}{role}): {o['e_points']:.2f} predicted points, {o['with_armband']:.2f} with the armband"
    if o.get("range_with_armband"):
        out += f"; {_armband_words(o['range_with_armband'])}"
    out += "."
    sh = o.get("points_share")
    if sh:
        out += f" {sh['part'][0].upper()}{sh['part'][1:]} {sh['points']:.2f} of his {sh['of']:.2f} predicted points ({sh['percent']}%)."
    if o.get("chance_of_60_plus") is not None:
        out += f" A {round(o['chance_of_60_plus'] * 100)}% chance of playing 60+ minutes."
    m = o.get("margin_to_next")
    if m:
        if m["points"] > 0:
            out += f" {m['points']:.2f} more than {m['short_name']} ({m['e_points']:.2f})."
        else:
            out += f" Level with {m['short_name']} ({m['e_points']:.2f})."
    return out


def captain_text(sq):
    """W11h H1: the captain answer -- the current captain and vice, the top 3 options by predicted points (plus the captain
    and vice when they are not among them), each with his own facts; the bonus sentence and the owner's follow-up."""
    cap = sq.get("captain_points")
    rows = _sq_rows(sq)
    captain = next((r for r in rows if r["role"] == "CAPTAIN"), None)
    vice = next((r for r in rows if r["role"] == "VICE"), None)
    if not cap or captain is None:
        raise NotInDraft("There are no predictions for the draft's captain yet.")
    head = f"Captain: {captain['short_name']}." + (f" Vice-captain: {vice['short_name']}." if vice else "")
    opts = list(cap.get("captain_options") or [])
    lines = [head, "", f"The top {len(opts)} captain options in your XI, by predicted points:"]
    lines += [_option_line(o) for o in opts]
    extra = cap.get("extra_options") or []
    if extra:
        lines += ["", "Your current captain or vice-captain outside those:"] + [_option_line(o) for o in extra]
    return "\n".join(lines + ["", BONUS_NOTE, "", EXPLAIN_FOLLOW_UP])


def explain_text(sq, detail="summary", player=None):
    """W11g G1: the explanation as it is shown (get_my_squad's draft answer in, text out): 'summary' (how the 15 were
    picked, the captain, the biggest picks, the budget), 'each_player' (all fifteen by position, one line each) or one
    player. Every fact is a field of the answer; nothing is judged. NotInDraft for a name that is not one of the 15."""
    if detail == "captain" and not player:                             # W11h H1
        return captain_text(sq)
    rows = _sq_rows(sq)
    if player:
        r = _find_player(rows, player)
        lines = [f"**{POSITION_NAMES.get(r['position'], r['position'])}**", _player_line(r)]
        cap = sq.get("captain_points")
        if r["role"] == "CAPTAIN" and cap and cap.get("captain_words"):
            lines.append(f"As captain: {cap['captain_words']}")
        return "\n".join(lines + ["", BONUS_NOTE, "", EXPLAIN_FOLLOW_UP])
    out = [_head(sq)]
    cap = _captain_line(sq)
    if cap:
        out.append(cap)
    if detail == "each_player":
        out.append(_money_line(sq, rows))
        for pos, title in SECTIONS:
            group = sq["squad_by_position"].get(pos) or []
            if group:
                out += ["", f"**{title}**"] + [_player_line(r) for r in group]
    else:
        big = _biggest_picks(rows)
        if big:
            out.append(big)
        out.append(_money_line(sq, rows))
    return "\n".join(out + ["", BONUS_NOTE, "", EXPLAIN_FOLLOW_UP])


def explain_my_draft(d, detail="summary", player=None):
    """W11g G1: the tool. Its "direct_reply" IS the turn's reply (agent.DIRECT_TOOLS): the model writes no explanation."""
    sq = get_my_squad(d)
    if sq.get("error"):
        return sq
    detail = detail if detail in ("summary", "each_player", "captain") else "summary"
    try:
        text = explain_text(sq, detail, player)
    except NotInDraft as e:
        return {"error": str(e)}
    return {"direct_reply": text, "detail": detail, "player": player,
            "shown": "This text is shown to the user as the reply; write nothing more."}


def _xi_total(xi):
    """The XI's predicted points with the captain counted twice, from the rows' own (shown) numbers (a player missing from the
    predictions counts 0, as on the card); None without any predictions."""
    if not xi or all(r.get("e_points") is None for r in xi):
        return None
    return round(sum(r["e_points"] or 0.0 for r in xi)
                 + next((r["e_points"] or 0.0 for r in xi if r["role"] == "CAPTAIN"), 0.0), 1)


def _money_block(doc, prices):
    value, missing = drafts.value_of(doc, prices)
    if missing:
        return {"value": None, "budget": 100.0, "left": None, "unpriced_player_ids": missing}
    out = {"value": drafts.money(value), "budget": 100.0, "left": drafts.money(max(0, drafts.BUDGET - value))}
    if value > drafts.BUDGET:
        over = drafts.money(value - drafts.BUDGET)
        out["over"] = over
        out["over_note"] = (f"Price rises since the build have pushed the draft £{over:.1f}m over £100.0m. Suggest a swap that "
                            "brings it back to £100.0m or less (any change that costs no more than the draft does now is "
                            "allowed meanwhile).")
    return out


def _rebuild_with(doc):
    """The set_my_squad arguments that rebuild the draft to today's best picks, and how many players that changes; None
    when the best picks are unavailable."""
    try:
        picks = drafts.best_picks(prices_fn=lambda ids: drafts.current_prices(ids, allow_fetch=False))
    except Exception:                                   # noqa: BLE001 -- the rest of the answer stands
        return None, None
    ids = sorted(p["element"] for p in picks["players"])
    now = {int(p["element"]) for p in doc["players"]}
    args = {"player_ids": ids, "captain_id": picks["captain"], "vice_id": picks["vice"], "bench_order_ids": picks["bench"],
            "confirm": False}
    return args, len(set(ids) - now)


def get_my_squad(d):
    row = _row(d)
    if row is None:
        return _no_draft()
    mt = _mt()
    doc = row["squad_json"]
    ids = [int(p["element"]) for p in doc["players"]]
    ctx = drafts.context(allow_fetch=False)
    prices = drafts.current_prices(ids, ctx=ctx)
    shorts = {e: (ctx.elements.get(e) or {}).get("web_name") for e in ids}
    gw = _next_gw()
    points, built = _pool_points(gw) if gw is not None else ({}, None)
    rows = _rows(doc, prices, points, shorts, nexts={e: _next_words(ctx, e, gw) for e in ids})
    xi = [r for r in rows if r["role"] != "bench"]
    bench = sorted((r for r in rows if r["role"] == "bench"), key=lambda r: r["bench_order"] or 0)
    import team_card
    xi_pts = _xi_total(xi) if points else None
    reasons, values = {}, {}
    if gw is not None:                                  # W11d D1: reasons computed from the build's own objective
        try:
            S = _Scoring(doc, gw)
            reasons = {} if S.missing else _pick_reasons(S)
            values = _value_facts(S)                    # W11f V1: the same predictions and current prices
        except Exception:                               # noqa: BLE001 -- no frame: the rest of the answer stands
            reasons, values = {}, {}
    parts = _breakdowns(ids, gw) if gw is not None else {}
    order = {"CAPTAIN": 0, "VICE": 1, "start": 2, "bench": 3}
    for r in rows:
        r["position_name"] = POSITION_NAMES.get(r["position"], r["position"])
        r["in_xi"] = r["role"] != "bench"
        r.update(reasons.get(r["player_id"]) or {"pick_reason": None, "best_alternative": None, "build_score_loss": None})
        r["breakdown"] = parts.get(r["player_id"])
        r["value_facts"] = values.get(r["player_id"])
    _pick_ranks(rows)                                   # W11f V3
    cap_pts = _captain_points(xi, gw)                   # W11e E3: with the range and the margin over the next-best
    by_position = {pos: sorted((r for r in rows if r["position"] == pos),
                               key=lambda r: (not r["in_xi"], r["bench_order"] or 0, -(r["e_points"] or 0.0)))
                   for pos in ("GK", "DEF", "MID", "FWD")}
    rebuild_with, rebuild_n = _rebuild_with(doc)
    run = mt._latest_run()
    out = {
        "draft": True, "not_in_fpl": True, "what_this_is": WHAT_THIS_IS,
        "rules": {"budget": 100.0, "squad": "2 GK, 5 DEF, 5 MID, 3 FWD", "max_per_club": drafts.MAX_PER_CLUB,
                  "xi": "1 GK, 3-5 DEF, 2-5 MID, 1-3 FWD", "changes": "free and unlimited"},
        **_money_block(doc, prices),
        "gw": gw, "formation": team_card.formation(doc),
        "captain": next((r["name"] for r in xi if r["role"] == "CAPTAIN"), None),
        "vice": next((r["name"] for r in xi if r["role"] == "VICE"), None),
        "captain_points": cap_pts,
        "squad_by_position": by_position,
        "bench_in_order": [r["short_name"] for r in bench],
        "predicted_xi_points": xi_pts,
        "predicted_xi_points_meaning": (f"the XI's predicted points for GW{gw} with the captain counted twice, from the latest "
                                        "predictions") if xi_pts is not None else None,
        "predictions_built": datewords.when_words(built) if built is not None else None,
        "built": {"at": datewords.when_words(row["built_at"]),
                  "from_run_id": (row.get("built_from") or {}).get("run_id"),
                  "newer_predictions_since": drafts.newer_predictions(row)},
        "changes_since_build": int(row["n_changes"]),
        "version_id": int(row["version_id"]),
        "how_picked": _how_picked(gw, int(row["n_changes"])),
        "explain_answer_rule": EXPLAIN_ANSWER_RULE,                   # W11g: explanations come from explain_my_draft
        "budget_line": _budget_line(rows),
        "reasons_rule": REASONS_RULE,
        "rebuild_with": rebuild_with,
        "rebuild_would_change_players": rebuild_n,
        "to_change": TO_CHANGE,
        "numbers_note": NUMBERS_NOTE,
        "enter_in_fpl": ENTER_IN_FPL,
        "latest_run_id": run["run_id"] if run else None,
    }
    return _said(mt._with_flags(out))


def _meta_and_prices(ids):
    ctx = drafts.context(allow_fetch=False)
    return drafts.player_meta(ids, ctx=ctx), drafts.current_prices(ids, ctx=ctx)


def _alternatives(doc, new_ids, kind, prices_all=None, limit=3):
    """Up to `limit` legal, affordable alternatives for the INCOMING player(s) of a refused request: same position, not in
    the requested fifteen, the club cap kept, the fifteen within £100.0m (or no dearer than now); most predicted points first."""
    mt = _mt()
    gw = _next_gw()
    if gw is None:
        return []
    try:
        pool, _c, _b = mt._load_pool(gw=int(gw))
    except Exception:                                   # noqa: BLE001
        return []
    old = {int(p["element"]): p for p in doc["players"]}
    ins = [e for e in new_ids if e not in old]
    if not ins:
        return []
    cand_ids = [int(e) for e in pool["element"]]
    meta, prices = _meta_and_prices(cand_ids + list(old) + ins)
    before, _ = drafts.value_of(doc, prices)
    pts = {int(e): float(p) for e, p in zip(pool["element"], pool["e_points"])}
    try:                                                # W11b F2: who each incoming player would replace
        out_of = {t["in_id"]: t["out_id"] for t in drafts.pairs(doc, new_ids, meta, prices)}
    except KeyError:
        out_of = {}
    out = []
    for i in ins:
        if i not in meta:
            continue
        pos = meta[i]["position"]
        base = [e for e in new_ids if e != i]
        clubs = {}
        for e in base:
            c = (old.get(e) or meta.get(e) or {}).get("team")
            clubs[c] = clubs.get(c, 0) + 1
        base_cost = sum(int(prices.get(e, 0)) for e in base)
        for e in sorted(cand_ids, key=lambda x: -pts.get(x, 0.0)):
            m = meta.get(e)
            if not m or m["position"] != pos or e in base or e == i or e in old or e not in prices:
                continue
            if clubs.get(m["team"], 0) >= drafts.MAX_PER_CLUB:
                continue
            total = base_cost + int(prices[e])
            if total > drafts.BUDGET and total > before:
                continue
            alt = {"player_id": e, "name": m["name"], "short_name": m.get("web_name") or m["name"], "team": m["team"],
                   "position": pos,
                   "price": drafts.money(prices[e]), "e_points": round(pts.get(e, 0.0), 2),
                   "value_after": drafts.money(total), "left_after": drafts.money(max(0, drafts.BUDGET - total)),
                   "instead_of": meta[i]["name"], "instead_of_price": drafts.money(prices.get(i)),
                   "money_words": f"With {m['name']} instead: £{drafts.money(total):.1f}m, {drafts._left_or_over(total)}."}
            if total > drafts.BUDGET:
                alt["over_after"] = drafts.money(total - drafts.BUDGET)
            o = out_of.get(i)
            if o is not None and o in prices:
                diff = int(prices[e]) - int(prices[o])
                alt.update(replaces=old[o]["name"], replaces_price=drafts.money(prices[o]), price_difference=drafts.money(diff),
                           difference_words=drafts.difference_words(m["name"], old[o]["name"], diff))
            out.append(alt)
            if len([x for x in out if x["instead_of"] == meta[i]["name"]]) >= limit:
                break
    return out


def _join(parts):
    return parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + " or " + parts[-1]


def _instead(alts):
    """W11c R2: the alternatives as one sentence the reply can lead with, e.g. Instead you could bring in Janelt (£5.0m, £0.1m
    left), Rudoni (£4.9m, £0.2m left) or Kamara (£5.0m, £0.1m left)."""
    if not alts:
        return "No legal alternative in that position fits within £100.0m and FPL's squad rules."
    def part(a):
        money = f"£{a['over_after']:.1f}m over" if a.get("over_after") else f"£{a['left_after']:.1f}m left"
        return f"{a['short_name']} (£{a['price']:.1f}m, {money})"
    groups = {}
    for a in alts:
        groups.setdefault(a["instead_of"], []).append(part(a))
    if len(groups) == 1:
        return f"Instead you could bring in {_join(next(iter(groups.values())))}."
    return "; ".join(f"{'Instead' if i == 0 else 'instead'} of {k} you could bring in {_join(v)}"
                     for i, (k, v) in enumerate(groups.items())) + "."


def set_my_squad(d, player_ids=None, captain_id=None, vice_id=None, bench_order_ids=None, gw=None, note=None,
                 confirm=False, user_id=None, proposal_id=None, preview_ticket=None):
    """A draft change: the fifteen + roles, checked against the squad rules and £100.0m at current prices, free. Preview
    (confirm=false) issues a ticket; confirm=true spends it and writes the draft in ONE transaction."""
    import db_write
    uid = int(d["user_id"])
    if confirm and not preview_ticket:
        return {"error": squad_previews.refusal("missing"), "refused": True, "reason": "missing", "draft": True}
    row = drafts.read(uid)
    if row is None:
        return _no_draft()
    doc = row["squad_json"]
    ids = [int(x) for x in (player_ids or []) if isinstance(x, int) and not isinstance(x, bool)]
    involved = sorted(set(ids) | {int(p["element"]) for p in doc["players"]})
    meta, prices = _meta_and_prices(involved)
    try:
        new_doc, change = drafts.plan_change(doc, player_ids, captain_id, vice_id, bench_order_ids, meta, prices)
    except drafts.Refused as e:
        out = {}
        if e.kind in ("over_budget", "club_cap"):       # W11c R2: the legal alternatives FIRST, in a ready sentence
            alts = _alternatives(doc, ids, e.kind)
            out = {"instead": _instead(alts), "legal_alternatives": alts}
        out.update({"error": f"refused: {e}", "refused": True, "draft": True, "reason_kind": e.kind,
                    "rule": e.details.get("rule"), "active_version": int(row["version_id"])})
        out.update({k: v for k, v in e.details.items() if k in ("over_by", "value_after", "value_before", "budget", "club", "n")})
        if e.kind in ("over_budget", "club_cap"):
            # W11b F2: price out, price in and the difference of each swap asked for, and the money now
            try:
                out["transfers"] = drafts.pairs(doc, ids, meta, prices)
            except KeyError:
                pass
            before, missing = drafts.value_of(doc, prices)
            if not missing and all(x in prices for x in ids):
                after = sum(int(prices[x]) for x in ids)
                out.setdefault("value_before", drafts.money(before))
                out["left_before"] = drafts.money(max(0, drafts.BUDGET - before))
                out.setdefault("value_after", drafts.money(after))
                out["left_after" if after <= drafts.BUDGET else "over_after"] = drafts.money(abs(drafts.BUDGET - after))
                out["money_words"] = drafts.money_words(before, after, refused=e.kind == "over_budget")
            out["next_step"] = ("Say why it was refused in its own words and numbers (money_words says the money in one "
                                "sentence: quote it, do not work the money out), and name at least one of the alternatives "
                                "from `instead`; nothing was previewed or saved.")
        return _said(out)
    if change["no_change"]:
        return {"draft": True, "refused": True, "reason_kind": "no_change",
                "error": "refused: that is the draft exactly as it is now; there is nothing to change",
                "active_version": int(row["version_id"])}
    # a rebuild = the fifteen and the roles of today's best picks (previewed from get_my_squad's rebuild_with)
    kind, built_from, picks_gw = "change", None, None
    try:
        picks = drafts.best_picks(prices_fn=lambda x: drafts.current_prices(x, allow_fetch=False))
        if (sorted(p["element"] for p in picks["players"]) == sorted(ids) and int(captain_id) == picks["captain"]
                and int(vice_id) == picks["vice"] and [int(x) for x in bench_order_ids] == picks["bench"]):
            kind, built_from, picks_gw = "rebuild", picks["built_from"], picks["gw"]
    except Exception:                                   # noqa: BLE001 -- an ordinary change then
        pass
    turn = turn_context.current() or turn_context.adhoc()
    fp = drafts.fingerprint(player_ids, captain_id, vice_id, bench_order_ids)
    conn = db_write.connect()
    ticket, written = None, None
    try:
        squad_previews.ensure_schema(conn)
        if confirm:
            reason = squad_previews.consume(conn, uid, preview_ticket, turn, fp, int(row["version_id"]))
            if reason:
                conn.rollback()
                return {"error": squad_previews.refusal(reason), "refused": True, "reason": reason, "draft": True,
                        "preview_ticket": str(preview_ticket), "active_version": int(row["version_id"])}
            try:
                written = drafts.write_change(conn, uid, int(row["version_id"]), new_doc, kind=kind, built_from=built_from,
                                              gw=picks_gw)
            except drafts.Changed as e:
                conn.rollback()
                return {"error": str(e), "draft": True}
            conn.commit()
        else:
            ticket = squad_previews.issue(conn, uid, turn, fp, int(row["version_id"]))
    finally:
        conn.close()
    next_gw = _next_gw()
    out = {"draft": True, "committed": bool(confirm), "preview": not confirm, "kind": kind,
           "message": ("saved to the draft (free: drafts have no free transfers or hits)" if confirm else
                       "PREVIEW ONLY -- nothing was saved; show the user the change and ask them to confirm"),
           "version_id": int(written["version_id"]) if written else int(row["version_id"]),
           "gw": next_gw if next_gw is not None else int(row["gw"]),
           "change": change}
    if ticket is not None:
        out["preview_ticket"] = ticket["id"]
        out["preview_expires_at"] = ticket["expires_at"].isoformat()
        out["preview_expires_words"] = datewords.when_words(ticket["expires_at"])
        out["message"] = f"{out['message']} {squad_previews.ticket_sentence(ticket['id'])}"
    return _said(out)


def get_my_xi(d, gw=None):
    """The best XI, captain, vice and bench order over the draft's fifteen (the same single-gameweek solve as get_my_xi),
    from the latest predictions; nothing is written. adopt_with previews through set_my_squad."""
    import squad_store
    row = _row(d)
    if row is None:
        return _no_draft()
    mt = _mt()
    target = gw if gw is not None else _next_gw()
    if target is None:
        return {"error": "the next deadline's gameweek is unknown right now (the FPL bootstrap is unreachable)", "draft": True}
    try:
        pool, cutoff, built = mt._load_pool(gw=int(target))
    except Exception as e:                              # noqa: BLE001
        return {"error": f"there are no predictions for GW{target}: {e}", "draft": True}
    doc = row["squad_json"]
    ids = [int(p["element"]) for p in doc["players"]]
    prices = drafts.current_prices(ids, allow_fetch=False)
    shell = {"schema": 1, "season": doc.get("season"), "bank": 0, "free_transfers": 0, "total_points": 0, "provenance": {},
             "players": [{**p, "purchase_price": int(prices.get(int(p["element"]), 0))} for p in doc["players"]]}
    state = squad_store.to_state(shell)
    t0 = time.time()
    team, missing = squad_store.xi_over_fifteen(pool, state, prices)
    roles = squad_store.roles_from_team(team)
    comparison = squad_store.compare_roles(doc["players"], team)
    rows = []
    for r in team.itertuples(index=False):
        role, bo = roles[int(r.element)]
        rows.append(_armband({"player_id": int(r.element), "name": r.name, "position": r.position, "team": str(r.team),
                              "role": role, "bench_order": bo, "e_points": round(float(r.e_points), 2)}))
    order = {"CAPTAIN": 0, "VICE": 1, "start": 2, "bench": 3}
    rows.sort(key=lambda r: (order[r["role"]], r["bench_order"] or 0, -r["e_points"]))
    xi = [r for r in rows if r["role"] != "bench"]
    bench = [r for r in rows if r["role"] == "bench"]
    out = {"draft": True, "gw": int(target), "solve_seconds": round(time.time() - t0, 1),
           "captain": next(r["name"] for r in xi if r["role"] == "CAPTAIN"),
           "vice": next(r["name"] for r in xi if r["role"] == "VICE"),
           "captain_points": _captain_points(xi, int(target)),
           "xi": xi, "bench_in_order": bench, "predicted_xi_points": _xi_total(xi),
           "predicted_xi_points_meaning": f"this XI's predicted points for GW{int(target)} with the captain counted twice",
           **_money_block(doc, prices), "numbers_note": NUMBERS_NOTE,
           "draft_roles_now": comparison, "missing_from_frame": missing,
           "adopt_with": {"player_ids": sorted(ids),
                          "captain_id": next(r["player_id"] for r in xi if r["role"] == "CAPTAIN"),
                          "vice_id": next(r["player_id"] for r in xi if r["role"] == "VICE"),
                          "bench_order_ids": [r["player_id"] for r in bench], "confirm": False},
           "to_change": TO_CHANGE}
    return _said(mt._with_flags(out))


def resolve_in_draft(d, name, cands, out):
    """resolve_player inside a draft chat (W11b F4): the name is matched against the draft's fifteen too, because a player going
    OUT can only be one of them. One draft player at the best rank -> in_your_draft (with his id, even when the name is
    ambiguous across the league: "Gomez" -> the Gomez in the draft); two or more -> draft_matches, ask which; none ->
    in_your_draft None. The league-wide answer (matches, ambiguous, the lock) is left as it was."""
    import player_names as pn
    row = _row(d)
    if row is None:
        return out
    doc = {int(p["element"]): p for p in row["squad_json"]["players"]}
    mine = pn.rank_matches(name, [c for c in cands if int(c["id"]) in doc])
    out = dict(out)
    if not mine:
        out["in_your_draft"] = None
        out["draft_note"] = "No player in the user's draft answers to that name."
        return out
    best = mine[0][0]
    rows = [{"player_id": int(c["id"]), "name": doc[int(c["id"])]["name"], "short_name": c.get("web_name") or None,
             "position": doc[int(c["id"])]["position"], "team": doc[int(c["id"])]["team"]} for r, c in mine if r == best]
    if len(rows) == 1:
        out["in_your_draft"] = rows[0]
        out["draft_note"] = (f"{rows[0]['name']} is the player in the user's draft with that name: when the user is taking a "
                             "player of this name OUT of the draft, it is him.")
        if out.get("action"):
            out["action"] = ("for the player going OUT of the draft, use in_your_draft without asking; ask which one only if "
                             "the user wants to bring a player of this name IN")
    else:
        out["in_your_draft"] = None
        out["draft_matches"] = rows
        out["draft_note"] = (f"{len(rows)} players in the user's draft answer to that name: if one of them is going OUT, ask "
                             "which.")
    return out


def _lineup(players, pts):
    """The build's own line-up rule over a fixed fifteen (optimize_squad's objective: the XI's points + the captain's again +
    the bench weight x the bench's + VICE_WEIGHT x the vice's): the best legal XI by points, the captain and vice its top two,
    the bench GK first then the outfielders by points. players = [(element, position)]; returns (score, xi, captain, vice,
    bench_order). Exact for one fixed fifteen without a MIP: every formation keeps the top 1 GK / 3 DEF / 2 MID / 1 FWD, so
    only the outfield split varies."""
    from optimize import VICE_WEIGHT
    by = {pos: sorted((e for e, p in players if p == pos), key=lambda e: (-pts.get(e, 0.0), e)) for pos in ("GK", "DEF", "MID", "FWD")}
    best = None
    for d in range(3, 6):
        for m in range(2, 6):
            f = 10 - d - m
            if not 1 <= f <= 3 or d > len(by["DEF"]) or m > len(by["MID"]) or f > len(by["FWD"]):
                continue
            s = sum(pts.get(e, 0.0) for e in by["DEF"][:d] + by["MID"][:m] + by["FWD"][:f])
            if best is None or s > best[0] + 1e-12:
                best = (s, d, m, f)
    _, d, m, f = best
    xi = by["GK"][:1] + by["DEF"][:d] + by["MID"][:m] + by["FWD"][:f]
    chosen = set(xi)
    bench = [e for e, _ in players if e not in chosen]
    top = sorted(xi, key=lambda e: (-pts.get(e, 0.0), e))
    cap, vice = top[0], top[1]
    w = _bench_weight()
    score = (sum(pts.get(e, 0.0) for e in xi) + pts.get(cap, 0.0) + w * sum(pts.get(e, 0.0) for e in bench)
             + VICE_WEIGHT * pts.get(vice, 0.0))
    pos = dict(players)
    order = [e for e in bench if pos[e] == "GK"] + sorted((e for e in bench if pos[e] != "GK"), key=lambda e: (-pts.get(e, 0.0), e))
    return score, xi, cap, vice, order


def _shown_total(xi, cap, shown):
    return round(sum(shown.get(e, 0.0) for e in xi) + shown.get(cap, 0.0), 1)


class _Scoring:
    """The build's own scoring of the draft (W11c R1, shared by W11d D1): the latest production frame for the next deadline,
    current prices, the club counts and the best line-up's score of the fifteen as they are."""

    def __init__(self, doc, gw):
        mt = _mt()
        pool, _cutoff, self.built = mt._load_pool(gw=int(gw))
        self.gw = int(gw)
        self.have = [int(p["element"]) for p in doc["players"]]
        self.by_id = {int(p["element"]): p for p in doc["players"]}
        self.raw = {int(e): float(x) for e, x in zip(pool["element"], pool["e_points"])}
        self.shown = {e: round(v, 2) for e, v in self.raw.items()}
        self.ctx = drafts.context(allow_fetch=False)
        self.cand = sorted(set(self.raw) - set(self.have))
        self.meta = drafts.player_meta(self.cand + self.have, ctx=self.ctx)
        self.prices = drafts.current_prices(self.cand + self.have, ctx=self.ctx)
        self.before, self.missing = drafts.value_of(doc, self.prices)
        self.players = [(e, self.by_id[e]["position"]) for e in self.have]
        self.base_score = _lineup(self.players, self.raw)[0]
        self.clubs = {}
        for e in self.have:
            self.clubs[self.by_id[e]["team"]] = self.clubs.get(self.by_id[e]["team"], 0) + 1
        self.short = {e: (self.meta.get(e) or {}).get("web_name") or (self.meta.get(e) or {}).get("name")
                      or self.by_id.get(e, {}).get("name") for e in self.cand + self.have}

    def swaps_for(self, o):
        """Every legal single swap of `o` (same position, the club cap kept, within £100.0m or no dearer than now), scored by
        the build's objective with the line-up re-picked: [(score, o, i, value after)]."""
        pos, club_o = self.by_id[o]["position"], self.by_id[o]["team"]
        out = []
        for i in self.cand:
            m = self.meta.get(i)
            if not m or m["position"] != pos or i not in self.prices:
                continue
            if self.clubs.get(m["team"], 0) - (1 if m["team"] == club_o else 0) >= drafts.MAX_PER_CLUB:
                continue
            after = self.before - int(self.prices[o]) + int(self.prices[i])
            if after > drafts.BUDGET and after > self.before:
                continue
            new = [(i, pos) if e == o else (e, p) for e, p in self.players]
            out.append((_lineup(new, self.raw)[0], o, i, after))
        return out


def _pick_reasons(S):
    """W11d D1: for each of the fifteen, the best legal replacement (S.swaps_for) and how much of the build's score that swap
    loses (negative = the replacement would raise it: not the build's pick now), as a ready sentence."""
    out = {}
    for o in S.have:
        swaps = S.swaps_for(o)
        if not swaps:
            out[o] = {"pick_reason": "Picked: no legal alternative fits his place within £100.0m and FPL's squad rules.",
                      "best_alternative": None, "build_score_loss": None}
            continue
        score, _o, i, _after = max(swaps, key=lambda t: (t[0], -t[2]))
        loss = round(S.base_score - score, 2)
        alt = {"player_id": i, "short_name": S.short[i], "name": S.meta[i]["name"], "team": S.meta[i]["team"],
               "price": drafts.money(S.prices[i])}
        where = f"{alt['short_name']} (£{alt['price']:.1f}m)"
        if loss >= 0:
            reason = f"Picked: the best legal alternative, {where}, would lower the build's score by {loss:.2f}."
        else:
            reason = f"Not the build's pick now: {where} would raise the build's score by {-loss:.2f}."
        out[o] = {"pick_reason": reason, "best_alternative": alt, "build_score_loss": loss}
    return out


def _nth(rank, joint, word):
    """A rank as it is said (W11f): 'the most', 'the 2nd-most', 'the joint 3rd-biggest'."""
    if rank == 1:
        return f"the joint {word}" if joint else f"the {word}"
    suf = "th" if 10 <= rank % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(rank % 10, "th")
    return f"the {'joint ' if joint else ''}{rank}{suf}-{word}"


def _value_facts(S):
    """W11f V1: for each of the fifteen, his predicted points per £1m (shown points / current price, half-up to 2 places)
    and his rank at his position among ALL players priced at or below him -- the same predictions (the latest frame, as
    shown) and current prices as the build. None for a player without a price or predicted points."""
    pos = {e: (S.meta.get(e) or {}).get("position") for e in S.cand}
    pos.update({e: S.by_id[e]["position"] for e in S.have})
    out = {}
    for e in S.have:
        p, price, pts = pos[e], S.prices.get(e), S.shown.get(e)
        if not price or pts is None:
            out[e] = None
            continue
        group = [i for i in S.shown if pos.get(i) == p and S.prices.get(i) is not None and S.prices[i] <= price]
        rank = 1 + sum(1 for i in group if S.shown[i] > pts)
        joint = any(S.shown[i] == pts for i in group if i != e)
        ppm = float((Decimal(f"{pts:.2f}") * 10 / Decimal(int(price))).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
        out[e] = {"points_per_million": ppm, "position": p, "rank": rank, "joint": joint, "of": len(group),
                  "words": (f"{ppm:.2f} predicted points per £1m; {_nth(rank, joint, 'most')} predicted points of any {p} "
                            f"at £{drafts.money(price):.1f}m or less ({len(group)} players)")}
    return out


def _pick_ranks(rows):
    """W11f V3: each pick's rank among the fifteen by build_score_loss (what the best legal alternative would cost the
    build's score), on the rows in place; None for a player the build would not pick now, or without a reason."""
    ranked = [r for r in rows if r.get("build_score_loss") is not None and r["build_score_loss"] >= 0]
    ids = {r["player_id"] for r in ranked}
    for r in rows:
        if r["player_id"] not in ids:
            r["pick_rank"] = None
            continue
        loss = r["build_score_loss"]
        rank = 1 + sum(1 for x in ranked if x["build_score_loss"] > loss)
        joint = any(x["build_score_loss"] == loss for x in ranked if x["player_id"] != r["player_id"])
        r["pick_rank"] = {"rank": rank, "joint": joint, "of": len(ranked),
                          "words": (f"{_nth(rank, joint, 'biggest')} of the {len(ranked)} picks by what the best legal "
                                    f"alternative would cost the build's score ({loss:.2f})")}


def _breakdowns(ids, gw):
    """W11d D4: each player's 2-3 biggest breakdown parts and his chances of playing, from the SAME source as
    explain_prediction (the production frame's raw row through explain.breakdown). {} without a frame."""
    import explain
    mt = _mt()
    try:
        df, cutoff, _built = mt._frame_raw()
    except (FileNotFoundError, RuntimeError):
        return {}
    out = {}
    for e in ids:
        try:
            row, step, err = mt._explain_row(df, cutoff, e, gw)
            if err:
                continue
            lines = explain.breakdown(row, step)["lines"]
        except Exception:                               # noqa: BLE001 -- one player's breakdown never breaks the answer
            continue
        parts = [{"part": ln["term"].replace("_", " "), "points": round(ln["points"], 2)} for ln in lines
                 if round(ln["points"], 2) != 0][:3]
        p60, ppa = float(row.get("p_60plus", float("nan"))), float(row.get("p_play_any", float("nan")))
        words = ", ".join(f"{x['part']} {x['points']:+.2f}" for x in parts)
        if p60 == p60:
            words += f"; a {round(p60 * 100)}% chance of playing 60+ minutes"
        out[e] = {"parts": parts, "chance_of_60_plus": round(p60, 2) if p60 == p60 else None,
                  "chance_of_playing": round(ppa, 2) if ppa == ppa else None, "breakdown_words": words}
    return out


def _budget_line(rows):
    """The money split, with the XI's share computed (W11g G1: "the XI takes 77% of the £99.9m spent", never "almost all")."""
    w = _bench_weight()
    xi = sum(_tenths(r["price"]) for r in rows if r["in_xi"] and r["price"] is not None)
    bench = sum(_tenths(r["price"]) for r in rows if not r["in_xi"] and r["price"] is not None)
    share = f"; the XI takes {_half_up_int(xi, xi + bench)}% of the £{(xi + bench) / 10:.1f}m spent" if xi + bench else ""
    return f"XI £{xi / 10:.1f}m, bench £{bench / 10:.1f}m{share}; bench points count {w:g}×, so most of the budget goes on the XI."


def free_swaps(d, limit=3):
    """propose_transfers in a draft chat (W11c R1): up to `limit` best FREE single swaps for the draft -- the build's own
    predictions (the latest production frame for the next deadline) and its own score (_lineup: the solver's objective at
    its defaults, the line-up re-picked for each swap), within £100.0m at current prices (or no dearer than now) and FPL's
    squad rules; distinct players out and in. Already the solver's best -> says so and gives the closest alternatives.
    Each: out / in with both players' predicted points, the difference, the XI's predicted total before and after, the price
    difference, value and money left after, a ready sentence and the set_my_squad arguments to preview it. Nothing written."""
    row = _row(d)
    if row is None:
        return _no_draft()
    mt = _mt()
    gw = _next_gw()
    if gw is None:
        return {"error": "the next deadline's gameweek is unknown right now (the FPL bootstrap is unreachable)", "draft": True}
    doc = row["squad_json"]
    try:
        S = _Scoring(doc, gw)
    except Exception as e:                              # noqa: BLE001
        return {"error": f"there are no predictions for GW{gw}: {e}", "draft": True}
    if S.missing:
        return {"error": f"no current price for player(s) {S.missing}", "draft": True}
    have, by_id, raw, shown, ctx, meta, prices = S.have, S.by_id, S.raw, S.shown, S.ctx, S.meta, S.prices
    before, players, base_score, built = S.before, S.players, S.base_score, S.built
    scored = [t for o in have for t in S.swaps_for(o)]
    scored.sort(key=lambda t: (-t[0], t[1], t[2]))
    picked, outs, ins = [], set(), set()
    for t in scored:
        if t[1] in outs or t[2] in ins:
            continue
        picked.append(t)
        outs.add(t[1])
        ins.add(t[2])
        if len(picked) >= limit:
            break
    already_best = not scored or scored[0][0] <= base_score + 1e-9
    xi_now = [e for e in have if by_id[e]["role"] != "bench"]
    cap_now = next((e for e in have if by_id[e]["role"] == "CAPTAIN"), xi_now[0])
    xi_before = _shown_total(xi_now, cap_now, shown)
    short = S.short
    swaps = []
    for rank, (score, o, i, after) in enumerate(picked, 1):
        new = [(i, by_id[o]["position"]) if e == o else (e, p) for e, p in players]
        _s, xi, cap, vice, bench = _lineup(new, raw)
        xi_after = _shown_total(xi, cap, shown)
        change = round(xi_after - xi_before, 1)
        diff = int(prices[i]) - int(prices[o])
        po, pi = shown.get(o, 0.0), shown.get(i, 0.0)
        pdiff = round(pi - po, 2)
        xi_words = (f"the XI's predicted total (captain counted twice) goes from {xi_before:.1f} to {xi_after:.1f}"
                    + (f" ({abs(change):.1f} {'higher' if change > 0 else 'lower'})" if change else " (no change)"))
        left_words = drafts._left_or_over(after)
        swaps.append({
            "rank": rank,
            "suggestion_words": (f"Bring in {short[i]} ({meta[i]['team']}, £{drafts.money(prices[i]):.1f}m, {pi:.2f} predicted "
                                 f"points) for {short[o]} (£{drafts.money(prices[o]):.1f}m, {po:.2f}): {xi_words}; the draft "
                                 f"would cost £{drafts.money(after):.1f}m ({left_words})."),
            "out": {"player_id": o, "name": by_id[o]["name"], "short_name": short[o], "position": by_id[o]["position"],
                    "team": by_id[o]["team"], "role": by_id[o]["role"], "price": drafts.money(prices[o]), "e_points": po},
            "in": {"player_id": i, "name": meta[i]["name"], "short_name": short[i], "position": meta[i]["position"],
                   "team": meta[i]["team"], "price": drafts.money(prices[i]), "e_points": pi,
                   "next_fixture": _next_words(ctx, i, gw)},
            "points_difference": pdiff,
            "points_words": (f"{short[i]} is predicted {pi:.2f} points against {po:.2f} for {short[o]}"
                             + (f" ({abs(pdiff):.2f} {'more' if pdiff > 0 else 'fewer'})" if pdiff else " (the same)")),
            "xi_points_before": xi_before, "xi_points_after": xi_after, "xi_points_change": change, "xi_words": xi_words,
            "build_score_change": round(score - base_score, 2),
            "price_difference": drafts.money(diff), "difference_words": drafts.difference_words(short[i], short[o], diff),
            "value_after": drafts.money(after),
            **({"left_after": drafts.money(drafts.BUDGET - after)} if after <= drafts.BUDGET else
               {"over_after": drafts.money(after - drafts.BUDGET)}),
            "money_words": drafts.money_words(before, after),
            "preview_with": {"player_ids": sorted(e for e, _ in new), "captain_id": cap, "vice_id": vice,
                             "bench_order_ids": bench, "confirm": False},
        })
    _rw, rebuild_n = _rebuild_with(doc)
    w = _bench_weight()
    if already_best and rebuild_n == 0:
        summary = ("Your draft is already the best 15 by our predictions: no free swap raises the build's score. The closest "
                   "alternatives are below, each with what it would cost in predicted points.")
    elif already_best:
        summary = ("No single free swap raises the draft's score; the closest alternatives are below. A rebuild to the best "
                   f"picks would change {rebuild_n} player{'s' if rebuild_n != 1 else ''} (get_my_squad's rebuild_with).")
    else:
        summary = f"These are the best free swaps for your draft for GW{gw}, best first; each raises the build's score."
    out = {"draft": True, "kind": "free_swaps", "gw": int(gw), "already_best": bool(already_best), "summary": summary,
           "how_to_present": ("Present these as suggestions, with their numbers exactly as given (suggestion_words). Nothing "
                              "is previewed or saved: preview one with set_my_squad (its preview_with) only after the user "
                              "picks it."),
           "swaps": swaps,
           "xi_points_now": xi_before,
           "how_ranked": (f"By the build's own score: the XI's predicted points with the captain counted twice, plus {w:g} x "
                          "the bench's, the line-up re-picked for each swap; within £100.0m at current prices and FPL's "
                          "squad rules. Draft changes are free and unlimited."),
           "predictions_built": datewords.when_words(built) if built is not None else None,
           "summary_plain": (f"Free swaps for GW{gw} from the latest predictions; draft changes are free and unlimited, so "
                             "there is no transfer plan to keep.")}
    return _said(out)


def not_applicable(what):
    """propose_transfers / get_my_points / get_wildcard_gap in a draft chat: a plain explanation, not an error."""
    words = {
        "points": ("This is a DRAFT team, not entered in FPL, so it has scored no points. Its predicted points for the "
                          "next deadline are in get_my_squad (predicted_xi_points)."),
        "wildcard": ("This is a DRAFT team: no wildcard is needed, because draft changes are free and unlimited within "
                             "£100.0m and FPL's squad rules. To compare it with the best squad from scratch, use "
                             "best_squad_from_scratch."),
    }[what]
    return {"draft": True, "not_applicable": True, "message": words}


def price_movements(window_days=7):
    """get_price_movements in a draft chat: the market's movers, no squad sell prices (a draft has no purchase prices)."""
    import prices_tool as pt
    out = pt.movements(window_days=window_days, squad=None)
    if isinstance(out, dict) and "error" not in out:
        out["draft_note"] = ("The user's team is a DRAFT: its prices are always current (no purchase or sell prices); its "
                             "value and money left are in get_my_squad.")
    return out
