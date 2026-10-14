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
                       "explanations given for a number (\"his match may already have been played\") are claims too. The sentences the "
                       "allowed facts list as REQUIRED (the prompt's own words and the tools' own notes: the freshness line, the bonus "
                       "and penalty sentences, the six-gameweek plan sentence, the started-gameweek note, the longer-range-estimate "
                       "wording, the squad-rule refusals, 'any Premier League side can beat anyone') are never unsupported claims. Does not count: "
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
    # Redefined 2026-10-13 (judge final) after the user's fresh review calls (compare_players:1, compare_runs:1: a doubtful
    # player's points may come before his flag): two tiers, decided by code from the tool row and listed per answer.
    "M4": {
        "name": "Availability first",
        "applies": ("ONLY when a tool result in the turn flags a player (status not available, or chance of playing below 100; "
                    "use the real field names from the tool outputs) AND the reply gives predicted points for, recommends, captains "
                    "or locks that player; a price-only mention inside a refusal or an infeasible-squad answer does not trigger it."),
        "question": ("For each flagged player the reply engages with: if he is UNAVAILABLE (status u, or injured / suspended with a "
                     "0% or unknown chance of playing), does the reply state his availability flag BEFORE any predicted number for "
                     "him, and never recommend, captain, start or lock him as if he could play? If he is DOUBTFUL (status d, or a "
                     "chance of playing between 25% and 75%), is his flag clearly stated somewhere in the reply (order does not matter)? "
                     "A player marked 'forced in by the user' may be built and started: does the reply state his flag before his "
                     "numbers and say he was forced in at the user's request?"),
        "definition": ("PASS if every flagged player the reply engages with meets his tier's rule; FAIL if any does not. The tier "
                       "of each such player, from the tool row, is listed under 'Flagged players' below for this answer. A flag "
                       "stated in the reply's own words counts (\"doubtful\", \"75% to play\", \"out\", \"suspended\", \"injured\"). "
                       "A player the USER forced in by name (marked 'forced in by the user' in the list) may be built, started and "
                       "given numbers: he PASSES when the reply states his flag before his numbers and says he was forced in at the "
                       "user's request; the never-recommend rule does not apply to him (batch 3 F12, the user's decision of 2026-10-14)."),
        "pass_example": ("DOUBTFUL: \"Gakpo: 3.2 points -- and he's doubtful (75%).\" UNAVAILABLE: \"Isak is out (thigh injury, 0%). "
                         "His 4.1-point figure is a planning number only.\""),
        "fail_example": ("UNAVAILABLE: \"Isak: 4.1 points, a strong pick\" with the injury flag at the end or missing, or Isak "
                         "captained; DOUBTFUL: a 75%-to-play player given points with no flag anywhere in the reply."),
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


def metric_text(key, sheet=None, record=None):
    """The metric block, verbatim: name, applies, question, definition, pass example, fail example. For M4 with a
    record, the answer's own flagged players and their tiers (code-decided) follow."""
    m = METRICS[key]
    q = metric_question(key, sheet)
    lines = [f"{key} {m['name']}. Applies: {m['applies']}", f"Question: \"{q}\""]
    if m["definition"]:
        lines.append(m["definition"])
    if m["pass_example"]:
        lines.append(f"Pass example: {m['pass_example']}")
    if m["fail_example"]:
        lines.append(f"Fail example: {m['fail_example']}")
    if key == "M4" and record is not None:
        flags = m4_flags(record)
        if flags:
            lines.append("Flagged players the reply engages with (tier decided by code from the tool row):")
            lines += [f"- {name} -- {tier} ({detail})" for name, tier, detail in flags]
    return "\n".join(lines)


# ------------------------------------------------------------------ M4 tiers (judge final, 2026-10-13)
UNAVAILABLE_TIER = "UNAVAILABLE"
DOUBTFUL_TIER = "DOUBTFUL"


def _chance_of(fields):
    for k in ("chance", "chance_of_playing", "chance_of_playing_next_round", "chance_of_playing_this_round"):
        v = fields.get(k)
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            return v
    av = fields.get("availability")
    if isinstance(av, dict):
        return _chance_of(av)
    return None


def flag_tier(fields):
    """UNAVAILABLE: status u or n, or injured / suspended with a 0% or unknown chance of playing, or available False with
    no chance; DOUBTFUL: status d, or any other flag with a chance between 1 and 99 (the 25-75% band and its neighbours
    read the same way: the flag must be stated, order free)."""
    status = str(fields.get("status") or "").lower()
    chance = _chance_of(fields)
    if status in ("u", "n"):
        return UNAVAILABLE_TIER
    if status in ("i", "s"):
        return UNAVAILABLE_TIER if (chance is None or chance <= 0) else DOUBTFUL_TIER
    if status == "d":
        return DOUBTFUL_TIER
    if chance is not None and chance <= 0:
        return UNAVAILABLE_TIER
    if fields.get("available") is False and chance is None:
        return UNAVAILABLE_TIER
    return DOUBTFUL_TIER


def _flag_detail(fields):
    parts = []
    status = fields.get("status")
    if status:
        parts.append(f"status {status}")
    chance = _chance_of(fields)
    if chance is not None:
        parts.append(f"{int(chance) if float(chance).is_integer() else chance}% chance of playing")
    elif fields.get("available") is False:
        parts.append("available False")
    note = fields.get("availability_note") or fields.get("news")
    if note:
        parts.append(f"note: {str(note)[:80]}")
    return ", ".join(parts) or "flagged"


FORCING_TOOLS = ("build_squad_from_scratch", "propose_transfers")


def forced_in(record):
    """(ids, warning text) of the players the USER forced in this turn: the lock / start ids passed to the squad build
    or the transfer plan, and every forced_availability_warning the tools returned (batch 3 F12)."""
    ids, warnings = set(), []
    for c in record.get("calls") or []:
        if c.get("tool") in FORCING_TOOLS:
            args = c.get("args")
            if isinstance(args, str):
                args = parse_output(args)
            if isinstance(args, dict):
                for k in ("lock_player_ids", "start_player_ids"):
                    for v in args.get(k) or []:
                        if isinstance(v, (int, float)) and not isinstance(v, bool):
                            ids.add(int(v))
        out = parse_output(c.get("output"))
        if isinstance(out, dict) and isinstance(out.get("forced_availability_warning"), str):
            warnings.append(out["forced_availability_warning"])
    return ids, " ".join(warnings)


def m4_flags(record):
    """[(name, tier, detail)] for every flagged player the reply engages with -- the list the M4 judge sees. A player
    the user forced in carries 'forced in by the user' in his detail (batch 3 F12)."""
    ids, warning = forced_in(record)
    out = []
    for name, fields in flagged_in_reply(record):
        detail = _flag_detail(fields)
        if fields.get("player_id") in ids or (warning and mentioned(name, warning)):
            detail += "; forced in by the user"
        out.append((name, flag_tier(fields), detail))
    return out


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


STATUS_WORD_LETTER = {"doubtful": "d", "injured": "i", "suspended": "s", "unavailable": "u", "not in squad": "n"}


def _status_letter(d):
    """The FPL status letter of a row: its 'status', else the letter behind its 'status_word' (batch 3 F5 rows)."""
    status = d.get("status")
    if isinstance(status, str) and status:
        return status.lower()
    word = d.get("status_word")
    return STATUS_WORD_LETTER.get(str(word).lower()) if isinstance(word, str) else None


def _is_flagged(d):
    status = _status_letter(d)
    if status in UNAVAILABLE_STATUS:
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
                    fields = {k: x.get(k) for k in ("status", "chance", "available", "availability_note", "news") if k in x}
                    if "status" not in fields and _status_letter(x):
                        fields["status"] = _status_letter(x)
                    if "player_id" in x or "element" in x:
                        fields["player_id"] = x.get("player_id", x.get("element"))
                    found.append((name, fields))
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
