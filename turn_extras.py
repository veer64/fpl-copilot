"""What a /chat turn produced for the Chat page beside its text (Prompt W4 Data 1 + 3, 2026-11-06), derived SERVER-SIDE from
the turn's tool calls -- never parsed from the answer text, never a model call, never a network call:

sources[]  the news items the answer CITED (news_search.cited_ids over the raw reply, among the ids search_news returned this
           turn -- checkpoint C4: an uncited item is never a chip), {name, headline, date, url?}; FPL rows (source "FPL
           official") as name "FPL" with no url; plus FPL injury notes from this turn's player cards whose player the answer
           names (the fact check's folded name tokens), name "FPL", headline = the note, date = news_added (the snapshot
           archive, model_tools._snapshot_news) else the card's as-of day. Deduped on (name, headline), at most MAX_SOURCES.
squad_preview  from the turn's LAST successful set_my_squad(confirm=false) call: its arguments (the fifteen, captain, vice,
           bench order), its result (change.transfers, the money and free-transfer numbers, gw, preview_expires_at) and the
           ACTIVE version it previewed against (read here; the preview rolled back). Rows: transfer (change.transfers),
           captain / vice_captain (the armband moved), bench (an XI<->bench swap = one row out: the XI player, in: the bench
           player; a reorder = one row per changed bench position). slot = the current card's slot of the OUT player (C2).
           impact: bank_after / ft_before / ft_after / hit_pts from the tool; pts_delta / pts_horizon_gws ONLY from the same
           turn's propose_transfers result whose proposal_id the preview carries (hold_comparison.gap_objective,
           effective_horizon), else null. No ticket id.
squad_applied  {gw, version_id} from a committed set_my_squad(confirm=true) in the turn.

Any failure here is printed and leaves the field null / []: the reply never depends on it."""
import copy

MAX_SOURCES = 6
NAME_TOKEN_MIN = 3


# ---- sources -------------------------------------------------------------------------------------------------------------

def _news_source(r):
    from news_search import source_headline, source_url
    if r.get("source") == "FPL official":
        return {"name": "FPL", "headline": source_headline(r.get("headline")), "date": str(r.get("date") or "")[:10]}
    out = {"name": str(r.get("source") or ""), "headline": source_headline(r.get("headline")), "date": str(r.get("date") or "")[:10]}
    url = source_url(r.get("url"))
    if url:
        out["url"] = url
    return out


def _answer_tokens(text):
    from fact_check import fold, tokens
    return set(tokens(fold(text or "")))


def _named(name, answer_tokens):
    from fact_check import fold, tokens
    words = [t for t in tokens(fold(name or "")) if len(t) >= NAME_TOKEN_MIN]
    return bool(words) and any(w in answer_tokens for w in words)


def _card_notes(turn_calls, answer_tokens, snapshot_news):
    """FPL notes from this turn's player cards whose player the answer names."""
    out = []
    for tool, _inp, result in turn_calls or []:
        if tool != "get_player_card" or not isinstance(result, dict):
            continue
        av = result.get("availability") if isinstance(result.get("availability"), dict) else {}
        note = (av.get("news") or result.get("news") or "").strip()
        if not note:
            continue
        pid = result.get("player_id")
        if not (_named(result.get("web_name"), answer_tokens) or _named(result.get("name"), answer_tokens)):
            continue
        when = None
        try:
            snap = snapshot_news(av.get("as_of")).get(int(pid)) if pid is not None else None
            if snap and (snap[0] or "").strip() == note and snap[1]:
                when = str(snap[1])[:10]
        except Exception:                               # noqa: BLE001 -- the set date is a courtesy
            when = None
        if when is None and av.get("as_of"):
            when = str(av.get("as_of"))[:10]
        out.append({"name": "FPL", "headline": note, "date": when or ""})
    return out


def sources(raw, returned_results, turn_calls, snapshot_news=None):
    """See the module docstring. Pure given snapshot_news (element -> (news, news_added))."""
    from news_search import cited_ids
    if snapshot_news is None:
        import model_tools
        snapshot_news = model_tools._snapshot_news
    by_id = {str(r.get("id")): r for r in (returned_results or []) if isinstance(r, dict) and r.get("id")}
    items = [_news_source(by_id[cid]) for cid in cited_ids(raw) if cid in by_id]
    items += _card_notes(turn_calls, _answer_tokens(raw), snapshot_news)
    out, seen = [], set()
    for it in items:
        key = (it["name"], it["headline"])
        if key in seen or not it["headline"]:
            continue
        seen.add(key)
        out.append(it)
        if len(out) >= MAX_SOURCES:
            break
    return out


# ---- the squad-change preview and the applied write ----------------------------------------------------------------------

def _set_my_squad_calls(turn_calls):
    return [(inp or {}, res) for tool, inp, res in (turn_calls or [])
            if tool == "set_my_squad" and isinstance(res, dict) and "error" not in res and not res.get("refused")]


def _iso(value):
    import threads
    try:
        return threads.iso(value)
    except Exception:                                   # noqa: BLE001
        return None


def applied(turn_calls):
    """{gw, version_id} of a committed write in this turn, else None."""
    for _inp, res in reversed(_set_my_squad_calls(turn_calls)):
        if res.get("committed") is True and res.get("version_id") is not None:
            if res.get("draft"):                        # Prompt W11: "Saved to your draft." / "Draft rebuilt from the best picks."
                return {"gw": int(res["gw"]), "version_id": int(res["version_id"]), "draft": True,
                        "kind": res.get("kind") or "change"}
            return {"gw": int(res["gw"]), "version_id": int(res["version_id"])}
    return None


def _plan_gain(turn_calls, proposal_id):
    """(pts_delta, horizon) from this turn's propose_transfers result with that proposal id, else (None, None)."""
    if proposal_id is None:
        return None, None
    for tool, _inp, res in turn_calls or []:
        if tool != "propose_transfers" or not isinstance(res, dict) or res.get("proposal_id") != proposal_id:
            continue
        hc = res.get("hold_comparison") or {}
        if hc.get("refused") or hc.get("gap_objective") is None:
            return None, None
        try:
            return round(float(hc["gap_objective"]), 2), int(res.get("effective_horizon") or res.get("horizon") or 0) or None
        except (TypeError, ValueError):
            return None, None
    return None, None


def changes(active_doc, inp, res, player):
    """The preview's change rows (see the module docstring). `player(element, slot, role, in_squad)` builds a Player."""
    from team_card import roles, slots
    sl, rl = slots(active_doc), roles(active_doc)
    old_ids = {int(p["element"]) for p in active_doc.get("players") or []}
    old_bench = [int(p["element"]) for p in sorted((p for p in active_doc.get("players") or [] if p.get("role") == "bench"),
                                                   key=lambda p: int(p.get("bench_order") or 0))]
    new_ids = {int(x) for x in (inp.get("player_ids") or [])}
    new_bench = [int(x) for x in (inp.get("bench_order_ids") or [])]
    old_c = next((e for e, r in rl.items() if r == "C"), None)
    old_v = next((e for e, r in rl.items() if r == "VC"), None)
    new_c, new_v = inp.get("captain_id"), inp.get("vice_id")
    new_role = {int(new_c): "C"} if new_c is not None else {}
    if new_v is not None:
        new_role[int(new_v)] = "VC"

    def cur(e):
        return player(e, sl.get(e), rl.get(e), e in old_ids)

    def nxt(e, slot):
        return player(e, slot, new_role.get(e), e in old_ids)                  # C2: drawn in the OUT player's slot
    rows = []
    for t in ((res.get("change") or {}).get("transfers") or []):
        o, i = t.get("out_id"), t.get("in_id")
        if o is None or i is None:
            continue
        rows.append({"type": "transfer", "out": cur(int(o)), "in": nxt(int(i), sl.get(int(o))), "slot": sl.get(int(o))})
    if new_c is not None and old_c is not None and int(new_c) != int(old_c):
        rows.append({"type": "captain", "out": cur(old_c), "in": cur(int(new_c)), "slot": None})
    if new_v is not None and old_v is not None and int(new_v) != int(old_v):
        rows.append({"type": "vice_captain", "out": cur(old_v), "in": cur(int(new_v)), "slot": None})
    kept = old_ids & new_ids
    leaving = [e for e in new_bench if e in kept and e not in old_bench]          # XI -> bench
    entering = [e for e in old_bench if e in kept and e not in new_bench]         # bench -> XI
    for x, b in zip(leaving, entering):
        rows.append({"type": "bench", "out": cur(x), "in": cur(b), "slot": sl.get(x)})
    for k, (o, n) in enumerate(zip(old_bench, new_bench), start=1):
        if o != n and o in kept and n in kept and o not in entering and n not in leaving:
            rows.append({"type": "bench", "out": cur(o), "in": cur(n), "slot": 11 + k})
    return rows


def preview(turn_calls, active_doc, player):
    """The structured preview of the turn's last successful preview call, or None."""
    last = None
    for inp, res in _set_my_squad_calls(turn_calls):
        if res.get("preview") is True and not inp.get("confirm"):
            last = (inp, res)
    if last is None:
        return None
    inp, res = last
    ch = res.get("change") or {}
    pts, horizon = _plan_gain(turn_calls, inp.get("proposal_id"))
    impact = {"pts_delta": pts, "pts_horizon_gws": horizon,
              "bank_after": ch.get("bank_after"), "ft_before": ch.get("free_transfers_before"),
              "ft_after": ch.get("free_transfers_after"), "hit_pts": ch.get("hit_cost_points")}
    out = {"gw": int(res["gw"]) if res.get("gw") is not None else None, "expires_at": _iso(res.get("preview_expires_at")),
           "changes": changes(active_doc, inp, res, player), "impact": impact}
    if res.get("draft"):                                # Prompt W11: a draft change is free -- value, not bank / FT / hits
        impact.update(value_before=ch.get("value_before"), value_after=ch.get("value_after"),
                      left_after=ch.get("left_after"), over_after=ch.get("over_after"))
        out.update(draft=True, kind=res.get("kind") or "change")
    return out


# ---- the turn's record ---------------------------------------------------------------------------------------------------

def record_for(st):
    """{sources, squad_preview, squad_applied} for agent._finish from the turn's state; every part guarded."""
    out = {"sources": [], "squad_preview": None, "squad_applied": None}
    try:
        out["sources"] = sources(st.get("raw") or "", st.get("returned_results"), st.get("turn_calls"))
    except Exception as e:                              # noqa: BLE001 -- the reply never depends on this
        print(f"  [sources not derived: {type(e).__name__}: {str(e)[:200]}]")
    try:
        out["squad_applied"] = applied(st.get("turn_calls"))
    except Exception as e:                              # noqa: BLE001
        print(f"  [squad_applied not derived: {type(e).__name__}: {str(e)[:200]}]")
    try:
        if _set_my_squad_calls(st.get("turn_calls")):
            out["squad_preview"] = _preview_for_turn(st)
    except Exception as e:                              # noqa: BLE001
        print(f"  [squad_preview not derived: {type(e).__name__}: {str(e)[:200]}]")
    return out


def _preview_for_turn(st):
    import config_roles
    import fpl_teams
    import squad_store
    import team_card
    calls = st.get("turn_calls") or []
    if not any(res.get("preview") is True for _inp, res in _set_my_squad_calls(calls)):
        return None
    user_id = config_roles.DEFAULT_USER_ID()
    import turn_context
    draft = (turn_context.current() or {}).get("draft")
    if draft is not None:                               # Prompt W11: the draft chat's preview draws on the draft
        import drafts
        doc = drafts.read(int(draft["user_id"]))["squad_json"]
    else:
        owner = fpl_teams.squad_owner_id(user_id)
        active = squad_store.read_active(owner)         # the preview rolled back: the active version is the card's
        doc = active["squad_json"]
    ctx = team_card.gather(allow_fetch=False).load_predictions()
    involved = {int(p["element"]) for p in doc.get("players") or []}
    for _inp, res in _set_my_squad_calls(calls):
        for t in ((res.get("change") or {}).get("transfers") or []):
            for k in ("out_id", "in_id"):
                if t.get(k) is not None:
                    involved.add(int(t[k]))
    ctx.live_rows = team_card._live_rows(involved)
    by_doc = {int(p["element"]): p for p in doc.get("players") or []}
    bought = {}
    for _inp, res in _set_my_squad_calls(calls):
        for t in ((res.get("change") or {}).get("transfers") or []):
            if t.get("in_id") is not None and t.get("bought_for") is not None:
                bought[int(t["in_id"])] = int(round(float(t["bought_for"]) * 10))

    def player(element, slot, role, in_squad):
        return ctx.player(element, slot=slot, role=role, in_squad=in_squad, doc=by_doc.get(element),
                          price_tenths=bought.get(element))
    return copy.deepcopy(preview(calls, doc, player))
