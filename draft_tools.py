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

import datewords
import drafts
import squad_previews
import turn_context

WHAT_THIS_IS = ("This is the user's DRAFT team: 15 players built from our predictions, NOT entered in FPL. Changes are free "
                "and unlimited; the only limits are the £100.0m budget at current FPL prices and FPL's squad rules. There are "
                "no free transfers, hits or bank.")
TO_CHANGE = ("To change the draft, call set_my_squad with confirm=false (a preview the user must say yes to); apply it with "
             "confirm=true and the preview_ticket only after the user says yes in their next message.")
NOT_A_TRANSFER_PLAN = ("This is a DRAFT team, not an FPL entry: there are no transfers, free transfers or hits, so there is no "
                       "transfer plan. Changes are free and unlimited within £100.0m and FPL's squad rules. To suggest "
                       "changes, compare players (compare_players, get_player_card, list_players) or solve with "
                       "build_squad_from_scratch (lock_player_ids / ban_player_ids), then preview the change with set_my_squad.")
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


def _rows(doc, prices, points, shorts=None):
    out = []
    for p in doc["players"]:
        e = int(p["element"])
        out.append({"player_id": e, "name": p["name"], "short_name": (shorts or {}).get(e) or p["name"],   # FPL's web_name
                    "position": p["position"], "team": p["team"], "role": p["role"],
                    "bench_order": p.get("bench_order"), "price": drafts.money(prices.get(e)),
                    "e_points": points.get(e)})
        _armband(out[-1])
    return out


def _armband(row):
    """W11b F1: the captain's row carries his points WITH the armband (doubled), so no reply doubles them."""
    if row["role"] == "CAPTAIN" and row.get("e_points") is not None:
        row["e_points_with_armband"] = round(2 * row["e_points"], 2)
    return row


def _captain_points(xi):
    cap = next((r for r in xi if r["role"] == "CAPTAIN"), None)
    if cap is None or cap.get("e_points") is None:
        return None
    return {"player_id": cap["player_id"], "name": cap["name"], "short_name": cap.get("short_name") or cap["name"],
            "e_points": cap["e_points"], "with_armband": cap["e_points_with_armband"]}


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
    rows = _rows(doc, prices, points, shorts)
    xi = [r for r in rows if r["role"] != "bench"]
    bench = sorted((r for r in rows if r["role"] == "bench"), key=lambda r: r["bench_order"] or 0)
    import team_card
    xi_pts = _xi_total(xi) if points else None
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
        "captain_points": _captain_points(xi),
        "xi": xi, "bench_in_order": bench,
        "predicted_xi_points": xi_pts,
        "predicted_xi_points_meaning": (f"the XI's predicted points for GW{gw} with the captain counted twice, from the latest "
                                        "predictions") if xi_pts is not None else None,
        "predictions_built": datewords.when_words(built) if built is not None else None,
        "built": {"at": datewords.when_words(row["built_at"]),
                  "from_run_id": (row.get("built_from") or {}).get("run_id"),
                  "newer_predictions_since": drafts.newer_predictions(row)},
        "changes_since_build": int(row["n_changes"]),
        "version_id": int(row["version_id"]),
        "basis": ("The draft was built as the fifteen with the most predicted points that FPL's squad rules and £100.0m allow "
                  "(the same build as the best squad from scratch). Each player's basis is his predicted points on his row. "
                  "No other reasons are available."),
        "rebuild_with": rebuild_with,
        "rebuild_would_change_players": rebuild_n,
        "to_change": TO_CHANGE,
        "numbers_note": NUMBERS_NOTE,
        "enter_in_fpl": ENTER_IN_FPL,
        "latest_run_id": run["run_id"] if run else None,
    }
    return mt._with_flags(out)


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
            alt = {"player_id": e, "name": m["name"], "team": m["team"], "position": pos,
                   "price": drafts.money(prices[e]), "e_points": round(pts.get(e, 0.0), 2),
                   "value_after": drafts.money(total), "left_after": drafts.money(max(0, drafts.BUDGET - total)),
                   "instead_of": meta[i]["name"], "instead_of_price": drafts.money(prices.get(i))}
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
        out = {"error": f"refused: {e}", "refused": True, "draft": True, "reason_kind": e.kind,
               "rule": e.details.get("rule"), "active_version": int(row["version_id"])}
        out.update({k: v for k, v in e.details.items() if k in ("over_by", "value_after", "value_before", "budget", "club", "n")})
        if e.kind in ("over_budget", "club_cap"):
            # W11b F2: price out, price in and the difference of each swap asked for, and the money now
            try:
                out["transfers"] = drafts.pairs(doc, ids, meta, prices)
            except KeyError:
                pass
            before, missing = drafts.value_of(doc, prices)
            if not missing:
                out.setdefault("value_before", drafts.money(before))
                out["left_before"] = drafts.money(max(0, drafts.BUDGET - before))
            out["legal_alternatives"] = _alternatives(doc, ids, e.kind)
            out["next_step"] = ("Say why it was refused, with the numbers above, and offer one of legal_alternatives (or "
                                "another legal swap); nothing was previewed or saved.")
        return out
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
    return out


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
           "captain_points": _captain_points(xi),
           "xi": xi, "bench_in_order": bench, "predicted_xi_points": _xi_total(xi),
           "predicted_xi_points_meaning": f"this XI's predicted points for GW{int(target)} with the captain counted twice",
           **_money_block(doc, prices), "numbers_note": NUMBERS_NOTE,
           "draft_roles_now": comparison, "missing_from_frame": missing,
           "adopt_with": {"player_ids": sorted(ids),
                          "captain_id": next(r["player_id"] for r in xi if r["role"] == "CAPTAIN"),
                          "vice_id": next(r["player_id"] for r in xi if r["role"] == "VICE"),
                          "bench_order_ids": [r["player_id"] for r in bench], "confirm": False},
           "to_change": TO_CHANGE}
    return mt._with_flags(out)


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


def not_applicable(what):
    """propose_transfers / get_my_points / get_wildcard_gap in a draft chat: a plain explanation, not an error."""
    words = {
        "transfer plan": NOT_A_TRANSFER_PLAN,
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
