"""Prompt R3e (2026-11-16): does a normal turn compare named players? Pure; no model, no database.

R3d's gate (eval/reports/r3d_answers.md, Set D case 6, run 3): "Over the coming gameweeks, is Doku or Semenyo the better pick?"
-- the model resolved both players, opened ONE player card and wrote the comparison itself. R3d's guard stops only a second
card. This module is the reading the agent's guard rests on (agent._comparison_turn): a turn whose user message reads as a
comparison (COMPARISON_WORDS) and names two or more different players -- by an exact match of the message against the player
list, or by two different players already resolved in the turn -- is a comparison, and its single-player lookups are not run
until compare_players has run.

Names are matched on accent-folded, case-folded, punctuation-free words (player_names.norm: "Gyökeres" == "gyokeres",
"M.Salah" == "m salah"), longest first, left to right, each word used once. A player's forms: the players_live name ("first
second"), FPL's web_name, and the web_name without its initial ("B.Fernandes" -> "fernandes"). A form shared by several
players ("Palmer": Cole and Alex) is ONE name in the message, never two players. Nine forms on build 78 are also ordinary
words (Gray, Hill, James, John, King, Mount, Pope, Rice, Wood); a misfire on one needs a comparison word and a second name too,
and only holds a single-player lookup with a note pointing at the comparison tool."""
import re

import player_names as pn

# THE FIXED WORD LIST (the brief's, in its order). " or " and the phrases match as whole words; "compare", "comparison" and
# "better" also match their longer forms ("compared", "comparisons"), never a word that merely contains them.
COMPARISON_WORDS = (" or ", "vs", "versus", "compare", "comparison", "better", "best of", "stack up",
                    "difference between", "rather have", "which of")
_STEMS = ("compare", "comparison", "better")
_WORD_RE = re.compile("|".join(r"\b" + re.escape(w.strip()) + ("" if w in _STEMS else r"\b") for w in COMPARISON_WORDS))
MAX_NAME_WORDS = 4


def _fold(text):
    return pn.norm(text)


def reads_as_comparison(text):
    """True when the message contains a word or phrase of COMPARISON_WORDS (folded; whole words)."""
    t = _fold(text)
    return bool(t) and _WORD_RE.search(t) is not None


def name_forms(players):
    """{folded name form: frozenset(element ids)} for `players` = (element, players_live name, web_name) triples."""
    out = {}
    for element, name, web in players:
        keys = {_fold(name), _fold(web)}
        w = _fold(web).split()
        if len(w) > 1 and len(w[0]) == 1:
            keys.add(" ".join(w[1:]))
        for k in keys:
            if k and len(k.split()) <= MAX_NAME_WORDS:
                out.setdefault(k, set()).add(int(element))
    return {k: frozenset(v) for k, v in out.items()}


def _spans_words(text, forms):
    """[(the matched words, their players)] -- the message's name spans, longest first, left to right, each word once."""
    toks = _fold(text).split()
    spans, i = [], 0
    while i < len(toks):
        for n in range(min(MAX_NAME_WORDS, len(toks) - i), 0, -1):
            words = " ".join(toks[i:i + n])
            ids = forms.get(words)
            if ids:
                spans.append((words, ids))
                i += n
                break
        else:
            i += 1
    return spans


def _spans(text, forms):
    return [ids for _w, ids in _spans_words(text, forms)]


def players_named(text, forms):
    """How many different players the message names: its name spans, a span whose players include another span's counted
    once ("Gabriel Magalhães or Gabriel": one; "Palmer or Palmer": one; "Saka or Palmer": two)."""
    spans = set(_spans(text, forms or {}))
    minimal = [s for s in spans if not any(o < s for o in spans)]
    return len(minimal)


def resolved_players(turn_calls):
    """The players resolve_player has resolved in the turn: the best match of each lookup that was not ambiguous."""
    out = set()
    for call in turn_calls or ():
        try:
            name, _inp, res = call
        except (TypeError, ValueError):
            continue
        if name != "resolve_player" or not isinstance(res, dict) or res.get("ambiguous"):
            continue
        matches = res.get("matches") or []
        if matches and isinstance(matches[0], dict) and matches[0].get("player_id") is not None:
            out.add(int(matches[0]["player_id"]))
    return out


def resolver_forms(players):
    """Prompt R3f: name_forms, plus the first and last word of a players_live name of three words or more ("Gabriel Fernando
    de Jesus" -> "gabriel jesus", "Bruno Borges Fernandes" -> "bruno fernandes") -- the fuller forms a user types."""
    out = {k: set(v) for k, v in name_forms(players).items()}
    for element, name, _web in players:
        w = _fold(name).split()
        if len(w) > 2:
            out.setdefault(f"{w[0]} {w[-1]}", set()).add(int(element))
    return {k: frozenset(v) for k, v in out.items()}


def named_one(text, players):
    """Prompt R3f: (element, the words) when the message names exactly ONE of `players` -- (element, players_live name,
    web_name) triples, the candidates of one lookup -- by a form no other of them shares; else None. A form they share
    ("sangare" for both Sangarés) names none of them; two different players named in full name neither."""
    if not text:
        return None
    named = {}
    for words, ids in _spans_words(text, resolver_forms(players)):
        if len(ids) == 1:
            named.setdefault(next(iter(ids)), words)
    if len(named) != 1:
        return None
    (element, words), = named.items()
    return element, words


def fires(text, forms, resolved=()):
    """(a) the message reads as a comparison and (b) it names two or more different players -- by the message's own names, or
    by the players resolved in the turn. (c), compare_players not yet run, is the agent's to check."""
    if not reads_as_comparison(text):
        return False
    return len(set(resolved or ())) >= 2 or players_named(text, forms) >= 2
