"""Player names -> FPL element ids (2026-09-30, Piece 7), no LLM. One matcher serves the relevance
verdicts (news_relevance.player_ids, mapped against the squad AS OF the item's fetched_at) and
search_news (the names the user asks about, against the squad as of the search's as_of).

Matching, on accent-folded, case-folded, punctuation-free tokens ("J.Timber" -> "j timber"):
  tier 1  the name equals a player's web_name or "first_name second_name";
  tier 2  the name equals a second_name or a first_name;
  tier 3  every token of the name is a token of the player's full name ("Junqueira" -> João Pedro).
The first tier with hits wins. A club (the article's club, or the search's) narrows several hits to
the ones at that club when that leaves at least one; when it leaves none the hits stand, unresolved.
A name with 2+ hits after that is AMBIGUOUS (left out of the ids, reported with labels such as
"Cole Palmer (CHE)"); a name with no hits is UNMAPPED. Nothing is guessed.
"""
import re
import unicodedata

_FOLD = {"ø": "o", "æ": "ae", "ß": "ss", "ð": "d", "þ": "th", "ł": "l", "đ": "d", "œ": "oe", "ı": "i"}
_PUNCT = re.compile(r"[^\w\s]")
_WS = re.compile(r"\s+")


def norm(s):
    """accent-insensitive, case-insensitive, punctuation as spaces, single-spaced (casefold first,
    so Ø folds through ø like the lower-case letters NFKD leaves alone)"""
    t = unicodedata.normalize("NFKD", str(s or "").casefold())
    t = "".join(_FOLD.get(c, c) for c in t if not unicodedata.combining(c))
    t = _PUNCT.sub(" ", t)
    return _WS.sub(" ", t).strip()


def candidates_from_bootstrap(bootstrap):
    """[{id, web_name, first_name, second_name, team, short}] for every element of a bootstrap snapshot"""
    teams = {int(t["id"]): t for t in (bootstrap.get("teams") or []) if "id" in t}
    out = []
    for e in bootstrap.get("elements") or []:
        t = teams.get(int(e.get("team") or 0), {})
        out.append({"id": int(e["id"]), "web_name": str(e.get("web_name") or ""), "first_name": str(e.get("first_name") or ""),
                    "second_name": str(e.get("second_name") or ""), "team": str(t.get("name") or ""), "short": str(t.get("short_name") or "")})
    return out


def label(c):
    return f"{c['first_name']} {c['second_name']} ({c['short']})".replace("  ", " ")


def match_players(name, candidates, club=None):
    """The candidates a name denotes (see the module docstring); [] when none, 2+ when ambiguous."""
    n = norm(name)
    if not n:
        return []
    tokens = set(n.split())
    tiers = ([], [], [])
    for c in candidates:
        web, first, second = norm(c["web_name"]), norm(c["first_name"]), norm(c["second_name"])
        full = f"{first} {second}".strip()
        if n in (web, full):
            tiers[0].append(c)
        elif n in (second, first) and n:
            tiers[1].append(c)
        elif tokens and tokens <= set(full.split()):
            tiers[2].append(c)
    hits = next((t for t in tiers if t), [])
    if club and len(hits) > 1:
        at_club = [c for c in hits if norm(c["team"]) == norm(club)]
        if at_club:
            hits = at_club
    return hits


def map_names(names, candidates, club=None):
    """{"ids": [element ids in first-seen order, no repeats], "unmapped": [names], "ambiguous": {name: [labels]}}"""
    ids, unmapped, ambiguous = [], [], {}
    for name in names or []:
        hits = match_players(name, candidates, club)
        if len(hits) == 1:
            if hits[0]["id"] not in ids:
                ids.append(hits[0]["id"])
        elif not hits:
            if name not in unmapped:
                unmapped.append(name)
        else:
            ambiguous[name] = [label(c) for c in hits]
    return {"ids": ids, "unmapped": unmapped, "ambiguous": ambiguous}
