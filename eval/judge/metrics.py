"""The five answer-quality metrics, VERBATIM as the user and the judge must read them, plus the
applicability rules -- decided by CODE from the recorded turn, never by the judge (an answer a metric
does not apply to is never sent).

M4 reads the tool outputs the model saw (str(dict) strings saved by the eval runner since 2026-10-11)
for a player carrying FPL's availability flag -- the real field names: `status` (FPL's one-letter code,
'a' = available; d doubtful, i injured, s suspended, u unavailable, n not in squad), `chance` (chance of
playing, below 100), `available: False` with an `availability_note` -- and applies only when such a
player is mentioned in the reply. M5 applies by sheet, one question each.
"""
import ast
import re
import unicodedata

METRICS = {
    "M1": {
        "name": "Plain language",
        "applies": "every answer",
        "question": "Is there any word or phrase in the reply that a typical football fan would not understand?",
        "definition": ("PASS if none. FAIL: model or stats jargon (npxG, xA without a plain translation, P10/P50/P90, lambda, "
                       "Dixon-Coles, decay, horizon step), tool names, run ids, variable names, formulas; also (Part C): ingest / "
                       "ingested / post-ingest, horizon, cutoff, solve / solver / optimiser / optimizer, frame, \"the run\" or run "
                       "numbers, raw status codes (u, d, a, i, s, n) and raw field names. FPL vocabulary fans know is fine (GW, "
                       "captain, vice, bench, chip, wildcard, hit, form, price, ownership); \"expected goals\" is fine; allowed "
                       "(Part C): objective, market odds / market-priced, expected goals rate, fitted."),
        "pass_example": "\"Haaland is expected to score about 9 points in GW7.\"",
        "fail_example": "\"His npxG per 90 drives a P90 of 14.2.\"",
    },
    "M2": {
        "name": "Answers the question",
        "applies": "every answer",
        "question": "Does the reply answer what the user actually asked?",
        "definition": ("PASS also when it asks a needed clarifying question (an ambiguous player name, a time that could mean two "
                       "gameweeks) or honestly states a by-design limit (e.g. prices can't be predicted). FAIL: answers a different "
                       "question, asks an unneeded clarification, refuses when the data was in the tool results, or skips part of a "
                       "multi-part question."),
        "pass_example": "\"Is Schade available?\" -> gives his FPL status.",
        "fail_example": "\"Is Schade available?\" -> talks about Brentford's fixtures only.",
    },
    "M3": {
        "name": "Faithful to the tools",
        "applies": "every answer",
        "question": ("Does the reply state any fact about a player, club or match that is NOT supported by the tool results, the "
                     "context block, the user's message or the allowed general facts?"),
        "definition": ("PASS if none. Counts: claims a user could act on (fitness, role, set pieces, bonus habits, form, league status, "
                       "transfers). Does not count: general remarks (\"any Premier League side can beat anyone\"), arithmetic whose "
                       "inputs are shown."),
        "pass_example": "every claim traces to a tool result.",
        "fail_example": "\"Haaland, a regular bonus earner\"; calling a club \"relegated\".",
    },
    # Part B (2026-10-12): M3 split. M3a is the claims in words; M3b is every number, judged and then VERIFIED
    # by code (judge/number_claims.py). M3 stays for the record (Part A's runs and the user's labels used it).
    "M3a": {
        "name": "Faithful to the tools (claims in words)",
        "applies": "every answer",
        "question": ("Does the reply state any fact in words about a player, club or match (fitness, role, penalties/set pieces, "
                     "bonus habits, form, league status, transfers, ownership) that is NOT supported by the tool results, the "
                     "context block, the user's message or the allowed general facts?"),
        "definition": ("PASS if none. Numbers are excluded here: every number in the reply is checked separately by code (M3b). "
                       "Counts: claims a user could act on (fitness, role, set pieces, bonus habits, form, league status, "
                       "transfers); club and position assignments beside a player are claims and need a tool source; reasons or "
                       "explanations given for a number (\"his match may already have been played\") are claims too. Does not count: "
                       "general remarks (\"any Premier League side can beat anyone\"), arithmetic whose inputs are shown."),
        "pass_example": "every claim traces to a tool result.",
        "fail_example": "\"Haaland, a regular bonus earner\"; calling a club \"relegated\".",
    },
    "M3b": {
        "name": "Faithful to the tools (numbers, code-verified)",
        "applies": "every answer whose reply contains at least one number claim",
        "question": ("Is every number in the reply supported by a quoted source -- direct, derived by simple arithmetic, or an "
                     "FPL rule -- about the same player, club, gameweek and stat?"),
        "definition": ("The judge returns one item per number (DIRECT / DERIVED / RULE / WRONG / UNSUPPORTED with the exact "
                       "quote it rests on); code verifies coverage, every quote, every number and every derivation, and "
                       "recomputes the verdict: FAIL if any number is WRONG or UNSUPPORTED."),
        "pass_example": "\"9.2 points\" quoted from the player's own GW7 row of a tool result.",
        "fail_example": "a number copied from another player's row, or one no tool returned.",
    },
    "M4": {
        "name": "Availability first",
        "applies": ("ONLY when a tool result in the turn flags a player (status not available, or chance of playing below 100; "
                    "use the real field names from the tool outputs) AND the reply gives predicted points for, recommends, captains "
                    "or locks that player; a price-only mention inside a refusal or an infeasible-squad answer does not trigger it."),
        "question": ("Does the reply state that player's availability flag before giving any predicted numbers for him, and avoid "
                     "recommending or captaining an unavailable player as if he could play?"),
        "definition": "",
        "pass_example": "\"Bruno Fernandes is flagged 75% to play. If he plays, expect about 5 points.\"",
        "fail_example": "points first, flag at the end or missing.",
    },
    "M5": {
        "name": "Right answer shape",
        "applies": "ONLY to these sheets, with one question each:",
        "question": None,                      # per sheet, see M5_QUESTIONS
        "definition": "",
        "pass_example": "",
        "fail_example": "(line-up) \"Want me to apply this XI?\"",
    },
}

M5_QUESTIONS = {
    "lineup_value": ("Does it give the gain from rearranging the squad, then ASK whether to compare with transfers or the best "
                     "possible squad (and not offer to apply the XI)?"),
    "fixture_scores": ("Does it give two separate scores out of 10 (attack and defence), never one combined score, and carry in its "
                       "last two paragraphs (not necessarily the final line) a short reminder that any Premier League side can beat anyone?"),
    "get_fixtures": ("Does it give two separate scores out of 10 (attack and defence), never one combined score, and carry in its "
                     "last two paragraphs (not necessarily the final line) a short reminder that any Premier League side can beat anyone?"),
    "propose_transfers": "Does it say plans cover at most six gameweeks and advise checking back?",
    "forced_starters": "Do the forced-in players start, and is the bench shown?",
}
M5_SHEETS = tuple(M5_QUESTIONS)
ALL = ("M1", "M2", "M3", "M4", "M5")                   # Part A's set (the user's labels)
ALL_B = ("M1", "M2", "M3a", "M3b", "M4", "M5")         # Part B's set (M3 split)

# FPL's status codes; 'a' is the only "available". Everything else is a flag.
UNAVAILABLE_STATUS = {"d", "i", "s", "u", "n"}
NAME_KEYS = ("name", "web_name", "player", "player_name")


def metric_question(key, sheet=None):
    """The one question the judge (and the user) answers for this metric; M5's depends on the sheet."""
    if key == "M5":
        return M5_QUESTIONS.get(sheet)
    return METRICS[key]["question"]


def metric_text(key, sheet=None):
    """The metric block, verbatim: name, applies, question, definition, pass example, fail example."""
    m = METRICS[key]
    q = metric_question(key, sheet)
    lines = [f"{key} {m['name']}. Applies: {m['applies']}", f"Question: \"{q}\""]
    if m["definition"]:
        lines.append(m["definition"])
    if m["pass_example"]:
        lines.append(f"Pass example: {m['pass_example']}")
    if m["fail_example"]:
        lines.append(f"Fail example: {m['fail_example']}")
    return "\n".join(lines)


# ------------------------------------------------------------------ M4: flagged players in the tool outputs
_NP_REPR = re.compile(r"\bnp\.(?:float64|float32|int64|int32|int16|bool_|str_)\(([^()]*)\)")
_DT_REPR = re.compile(r"\bdatetime\.(?:datetime|date)\(([^()]*)\)")
_TS_REPR = re.compile(r"\bTimestamp\('([^']*)'(?:,\s*tz='[^']*')?\)")
_NAN = re.compile(r"(?<![\w.])nan(?![\w.])")
_INF = re.compile(r"(?<![\w.])-?inf(?![\w.])")


def parse_output(text):
    """The Python object behind a saved tool output (agent.py sends str(result)); None if it does not parse.
    Tolerant (Part C) of the reprs a str(dict) can carry that are not literals: np.float64(x) / np.int64(x) ->
    x, datetime.datetime(...) -> 'datetime(...)', Timestamp('...') -> '...', nan -> None, inf -> 1e309."""
    if not isinstance(text, str) or not text.strip():
        return None
    s = _NP_REPR.sub(r"\1", text)
    s = _DT_REPR.sub(r"'datetime(\1)'", s)
    s = _TS_REPR.sub(r"'\1'", s)
    s = _NAN.sub("None", s)
    s = _INF.sub("1e309", s)
    try:
        return ast.literal_eval(s)
    except (ValueError, SyntaxError, MemoryError, RecursionError, TypeError):
        return None


def _is_flagged(d):
    status = d.get("status")
    if isinstance(status, str) and status.lower() in UNAVAILABLE_STATUS:
        return True
    for k in ("chance", "chance_of_playing", "chance_of_playing_next_round", "chance_of_playing_this_round"):
        v = d.get(k)
        if isinstance(v, (int, float)) and not isinstance(v, bool) and v < 100:
            return True
    if d.get("available") is False:
        return True
    return False


def _name_of(d):
    for k in NAME_KEYS:
        v = d.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return None


def flagged_players(outputs):
    """Every player a tool output flags: [(name, {field: value}) ...], from any dict (at any depth) that
    carries a name and a flag. Outputs that do not parse contribute nothing (the judge is never guessed in)."""
    found = []
    seen = set()

    def walk(x):
        if isinstance(x, dict):
            name = _name_of(x)
            if name and _is_flagged(x):
                key = name.lower()
                if key not in seen:
                    seen.add(key)
                    found.append((name, {k: x.get(k) for k in ("status", "chance", "available", "availability_note", "news") if k in x}))
            for v in x.values():
                walk(v)
        elif isinstance(x, (list, tuple)):
            for v in x:
                walk(v)

    for out in outputs or []:
        walk(parse_output(out))
    return found


def _fold(s):
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c)).lower()


def mentioned(name, reply):
    """Is this player named in the reply? Whole-word match on his surname (the last name token) or the
    whole name, accents folded, so 'Guéhi' and 'Guehi' agree and 'Son' does not hit 'Robertson'."""
    text = _fold(reply or "")
    tokens = [t for t in re.split(r"[\s\-]+", _fold(name)) if len(t) > 1]
    if not tokens:
        return False
    for cand in {tokens[-1], " ".join(tokens)}:
        if re.search(r"(?<![^\W_])" + re.escape(cand) + r"(?![^\W_])", text):
            return True
    return False


_ENGAGE = re.compile(r"\d+(?:\.\d+)?\s*(?:pts|points|xp|expected)|\b(captain|vice|start(?:s|ing|er)?|lock(?:ed)?|force(?:d)?|"
                     r"recommend(?:ed|s)?|pick(?:s|ed)?|bench(?:ed)?|xi|line-?up|transfer in|buy|keep|hold)\b", re.I)


_REFUSAL = re.compile(r"\b(infeasible|not feasible|can(?:no|')t (?:build|do|make|force|fit|afford)|cannot (?:build|force|fit|afford)|"
                      r"no legal squad|not possible|impossible|over budget|breaks? the (?:rule|limit)|allows at most|too tight)\b", re.I)
_PRICE = re.compile(r"£\s?\d+(?:\.\d+)?\s?m?\b|\b\d+(?:\.\d+)?m\b", re.I)


def _engaged(name, reply):
    """Does the reply engage with this player -- predicted points, a recommendation, captaincy, a lock, a listing?
    Any mention counts, EXCEPT a price-only mention inside a refusal / infeasible-squad answer (Part C): there the
    sentence naming the player (or the one after it, a pronoun carries on) must say more than his price."""
    if not mentioned(name, reply):
        return False
    if not _REFUSAL.search(reply or ""):
        return True
    for para in re.split(r"\n+", reply or ""):
        sents = [_PRICE.sub("", s) for s in re.split(r"(?<=[.!?])\s+", para)]
        for i, sent in enumerate(sents):
            if mentioned(name, sent) and (_ENGAGE.search(sent) or (i + 1 < len(sents) and _ENGAGE.search(sents[i + 1]))):
                return True
    return False


def flagged_in_reply(record):
    """The flagged players the reply engages with: the M4 trigger. Reads every tool output of the question
    turn (record['calls'][*]['output']); the player must be named in a line that gives him predicted points,
    recommends, captains, starts or locks him."""
    outputs = [c.get("output") for c in (record.get("calls") or []) if c.get("output")]
    reply = record.get("rendered_reply") or ""
    return [(n, f) for n, f in flagged_players(outputs) if _engaged(n, reply)]


def applicable(key, record):
    """Does metric `key` apply to this recorded answer? M1-M3 always; M4 only with a flagged, mentioned
    player; M5 only on its sheets."""
    if key in ("M1", "M2", "M3", "M3a"):
        return True
    if key == "M3b":
        from judge import number_claims                    # lazy: it imports run_judge, which imports this module
        return bool(number_claims.extract_claims(record.get("rendered_reply") or ""))
    if key == "M4":
        return bool(flagged_in_reply(record))
    if key == "M5":
        return record.get("sheet") in M5_SHEETS
    raise KeyError(key)


def applicable_metrics(record, keys=ALL):
    return [k for k in keys if applicable(k, record)]
