"""Prompt F2 E (2026-11-18): return dates -- supply the fact, then check the reply. Pure; no model, no database.

F1's gate (eval/reports/f1_fixes.md): of the four runs that quoted Saka's "up to eight weeks" (BBC, 23 Oct), two turned it into a
month -- "Eight weeks from that report would put him around late December" (L1 run 2), "Eight weeks from 23 Oct points well into
December" (L7 run 2); R3f's T2 did the same twice ("mid-to-late December", "into late December"). R3g's prompt sentence alone does
not hold. So:

SUPPLY  availability_line: a player's absence in the source's own words and date -- FPL's status word and news text verbatim with
        the day FPL said it, plus, when a news report about him was used, that report's own sentence and its date. Nothing is
        worked out: a duration stays a duration, and no date the source does not give is ever written.
CHECK   check(reply, ...): a sentence about a player with a reported absence -- it names him, or "he/his/him" follows a sentence
        that does with no other player named in between, or (in the same paragraph) it names nobody and goes on from such a
        sentence -- that gives a return timing (a month, a date, a gameweek, or a calendar anchor: "late December", "well into
        December", "by GW15", "over Christmas", "the new year", "next month") together with a word about his absence or return,
        is replaced by his availability line when that timing is not in the turn's sources. A gameweek or a day-and-month counts
        as sourced when any tool result of the turn carries it; a month alone or an anchor only when the source's own words carry
        it (FPL's news text, a news report's headline or text) -- code-built date fields ("as of Sun 15 Nov") never source a
        month. Model-written text only: the caller never passes a code-built answer."""
import re

MONTHS = {"january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6, "july": 7, "august": 8, "september": 9,
          "october": 10, "november": 11, "december": 12, "jan": 1, "feb": 2, "mar": 3, "apr": 4, "jun": 6, "jul": 7, "aug": 8,
          "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dec": 12}
_MONTH = (r"(?:January|February|March|April|June|July|August|September|October|November|December|Jan|Feb|Mar|Apr|Jun|Jul|Aug|"
          r"Sept|Sep|Oct|Nov|Dec|May)")
_DATE_DM = re.compile(r"\b(\d{1,2})(?:st|nd|rd|th)?\s+(?:of\s+)?(" + _MONTH + r")\b")
_DATE_MD = re.compile(r"\b(" + _MONTH + r")\.?\s+(\d{1,2})(?:st|nd|rd|th)?\b(?!\s*(?:%|points|pts|games|weeks|days))")
_DATE_ISO = re.compile(r"\b20\d\d-(\d{2})-(\d{2})\b")
_MONTH_WORD = re.compile(r"\b(" + _MONTH + r")\b")
_MAY_OK = re.compile(r"\b(?:in|by|until|till|before|after|from|of|early|mid|late|end|start|since|around|into|through)[\s-]+May\b|\bMay\s+\d")
_GW = re.compile(r"\bGW\s?(\d{1,2})(?:\s*[–—-]\s*(?:GW\s?)?(\d{1,2}))?\b")
_GAMEWEEK = re.compile(r"\b[Gg]ame\s?weeks?\s+(\d{1,2})(?:\s*(?:[–—-]|to|and)\s*(\d{1,2}))?\b")
ANCHORS = ("christmas", "boxing day", "new year", "festive", "next month", "end of the month", "end of the year", "end of the season",
           "next season", "international break", "winter break", "turn of the year", "next week", "next weekend", "the spring",
           "the summer")
_ANCHOR = re.compile(r"\b(" + "|".join(re.escape(a) for a in ANCHORS) + r")\b", re.I)
# a word about his absence or return -- a timing without one ("Saka's December fixtures look kind.") is not a return timing
_CUE = re.compile(r"\b(?:back|return\w*|comeback|recover\w*|fit|fitness|available|availability|out|sidelined|miss\w*|absen\w*|"
                  r"injur\w*|ruled|until|expected|feature|rejoin\w*|resum\w*|lay-?off|timeline|time-?frame|approaching|estimate\w*|"
                  r"window|puts? him|takes? us|weeks? from|months? from|weeks? after|months? after|from that (?:report|date))\b", re.I)
_PRONOUN = re.compile(r"\b(?:he|his|him|he's|he'll|he'd|himself)\b", re.I)
_REPORT_CUE = re.compile(r"\b(?:injur\w*|out|miss\w*|sidelined|ruled|weeks?|months?|surgery|knock|strain|fitness|return\w*|back|"
                         r"unavailable|absence)\b", re.I)
_SENT_END = re.compile(r"[.!?](?:[*_)\]\"'’”]*)(?=\s+|$)")
_MARKER = re.compile(r"\[(c\d+)\]")
_SOURCE_TAG = re.compile(r"^\[[^\]]*\|[^\]]*\]\s*")


def _fold(text):
    import player_names as pn
    return pn.norm(text)


# ---- the timings a text carries ------------------------------------------------------------------------------------------------
def timings(text):
    """[(kind, key, the words)] in `text`: ("gw", n), ("date", (day, month)), ("month", month), ("anchor", phrase). A month that
    is part of a date is the date only; "May" only where it is plainly the month ("in May", "May 3")."""
    out, taken = [], []
    t = str(text or "")
    for m in _GW.finditer(t):
        for g in (m.group(1), m.group(2)):
            if g:
                out.append(("gw", int(g), m.group(0)))
    for m in _GAMEWEEK.finditer(t):
        for g in (m.group(1), m.group(2)):
            if g:
                out.append(("gw", int(g), m.group(0)))
    for rx, d_i, m_i in ((_DATE_DM, 1, 2), (_DATE_MD, 2, 1)):
        for m in rx.finditer(t):
            if m.group(m_i) == "May" and not _MAY_OK.search(t[max(0, m.start() - 12): m.end() + 3]):
                continue
            day, mon = int(m.group(d_i)), MONTHS[m.group(m_i).lower()]
            if 1 <= day <= 31:
                out.append(("date", (day, mon), m.group(0)))
                taken.append((m.start(), m.end()))
    for m in _DATE_ISO.finditer(t):
        out.append(("date", (int(m.group(2)), int(m.group(1))), m.group(0)))
    for m in _MONTH_WORD.finditer(t):
        if any(a <= m.start() < b for a, b in taken):
            continue
        if m.group(1) == "May" and not _MAY_OK.search(t[max(0, m.start() - 12): m.end() + 3]):
            continue
        out.append(("month", MONTHS[m.group(1).lower()], m.group(0)))
    for m in _ANCHOR.finditer(t):
        out.append(("anchor", m.group(1).lower(), m.group(0)))
    return out


def corpus(all_text, source_words):
    """What the turn's sources carry: gameweeks and day-and-month dates from ANY tool result of the turn (`all_text`); months and
    calendar anchors only from the source's own words (`source_words`: FPL news texts, news headlines and texts)."""
    c = {"gw": set(), "date": set(), "month": set(), "anchor": set()}
    blob = str(all_text or "")
    for kind, key, _w in timings(blob):
        if kind in ("gw", "date"):
            c[kind].add(key)
    for g in re.findall(r"'gw': (\d{1,2})", blob):
        c["gw"].add(int(g))
    for group in re.findall(r"'(?:horizon_gws|gameweeks|listed_gameweeks|span_gws)': \[([0-9, ]*)\]", blob):
        c["gw"].update(int(x) for x in group.replace(" ", "").split(",") if x)
    for text in source_words or ():
        for kind, key, _w in timings(text):
            if kind == "date":
                c["date"].add(key)
                c["month"].add(key[1])
            elif kind in ("month", "anchor"):
                c[kind].add(key)
            elif kind == "gw":
                c["gw"].add(key)
    return c


def unsourced(text, c):
    """The timings of `text` the turn's sources do not carry."""
    return [(k, key, w) for k, key, w in timings(text) if key not in c[k]]


# ---- the supply ----------------------------------------------------------------------------------------------------------------
def report_sentence(text, headline, name_words):
    """A news report's own words about the player's absence: the first sentence of its text that names him and speaks of an
    absence (injury, out, weeks ...), else its headline when that names him; None otherwise. Verbatim."""
    words = {w for w in name_words if w}
    for s in re.split(r"(?<=[.!?])\s+|\n+", str(text or "")):
        s = _SOURCE_TAG.sub("", s.strip()).strip()       # the search text's own "[BBC Sport | 2026-10-23 14:09Z]" tag
        if 10 <= len(s) <= 300 and set(_fold(s).split()) & words and _REPORT_CUE.search(s):
            return s
    h = str(headline or "").strip()
    if h and set(_fold(h).split()) & words:
        return h
    return None


def availability_line(name, status_word, news, as_of_words, report=None):
    """The code-built availability line: '<name>: FPL lists him as <status>, "<news>" (FPL, <day>).' plus, when a report was used,
    ' <source> reported on <day>: "<its sentence>" [<id>].' -- the source's words and dates only."""
    line = f"{name}: FPL lists him as {status_word}"
    if news:
        line += f', "{str(news).strip()}"'
    if as_of_words:
        line += f" (FPL, {as_of_words})"
    line += "."
    if report and report.get("words"):
        when = f" on {report['date_words']}" if report.get("date_words") else ""
        mark = f" [{report['id']}]" if report.get("id") else ""
        line += f' {report.get("source") or "A report"} reported{when}: "{report["words"]}"{mark}.'
    return line


# ---- the check -----------------------------------------------------------------------------------------------------------------
def _sentences(line):
    """[(start, end)] of the sentences of one line of text (a period inside a number or a word never ends one)."""
    spans, start = [], 0
    for m in _SENT_END.finditer(line):
        spans.append((start, m.end()))
        start = m.end()
        while start < len(line) and line[start] == " ":
            start += 1
    if start < len(line) and line[start:].strip():
        spans.append((start, len(line)))
    return spans


_PREFIX = re.compile(r"^(\s*(?:#{1,6}\s+|[-*+]\s+|\d+[.)]\s+|>\s*)*)")
_EMPH = re.compile(r"^((?:\*\*|\*|__|_)*)(.*?)((?:\*\*|\*|__|_)*)$", re.S)


def check(reply, names, absent, c, lines):
    """(the reply to send, the replacements). `names(sentence)` -> the player ids the sentence names (exactly-one matches only);
    `absent` -- the ids FPL flags; `c` -- the turn's corpus; `lines(element, sentence)` -> his availability line. Table rows and
    code are left alone; a sentence whose players are none of them absent is left alone."""
    out_lines, replaced = [], []
    topic, topic_para, para, fence = set(), -1, 0, False
    for raw_line in str(reply or "").split("\n"):
        stripped = raw_line.strip()
        if stripped.startswith("```"):
            fence = not fence
        if fence or stripped.startswith("```") or stripped.startswith("|"):
            out_lines.append(raw_line)
            continue
        if not stripped:
            para += 1
            out_lines.append(raw_line)
            continue
        if re.fullmatch(r"[-*_]{3,}", stripped):
            topic, topic_para = set(), -1
            para += 1
            out_lines.append(raw_line)
            continue
        pm = _PREFIX.match(raw_line)
        head, body = raw_line[:pm.end()], raw_line[pm.end():]
        pieces, pos = [], 0
        for a, b in _sentences(body):
            sent = body[a:b]
            ids = set(names(sent))
            if ids:
                subject = ids
                topic, topic_para = ids, para
            elif _PRONOUN.search(sent) and topic:
                subject = topic
                topic_para = para                        # "he" keeps him the paragraph's subject
            elif topic and topic_para == para:
                subject = topic
            else:
                subject = set()
            hit = next((e for e in sorted(subject) if e in absent), None)
            new = sent
            if hit is not None and _CUE.search(sent):
                bad = unsourced(sent, c)
                if bad:
                    em = _EMPH.match(sent.rstrip())
                    lead, core, tail = em.group(1), em.group(2), em.group(3)
                    line = lines(hit, sent)
                    new = f"{lead}{line}{tail}" + sent[len(sent.rstrip()):]
                    replaced.append({"element": hit, "sentence": core.strip(), "timing": [w for _k, _key, w in bad], "line": line})
            pieces.append(body[pos:a] + new)
            pos = b
        pieces.append(body[pos:])
        out_lines.append(head + "".join(pieces))
    return "\n".join(out_lines), replaced


def markers(text):
    """The c<id> markers a text cites."""
    return _MARKER.findall(str(text or ""))
