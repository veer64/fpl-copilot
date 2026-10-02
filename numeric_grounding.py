"""Numeric grounding checker (2026-10-02), LOG ONLY: after every agent reply, which numbers the model stated and
whether each one can be found among the numbers it could see this turn. Pure code, no LLM; the reply is never
altered and the caller (agent.py) catches every exception and logs it to numeric_checks (news_store DDL).

check(raw_reply, messages) -> {numbers_found, grounded, ungrounded: [{text, value, context}], notebook_size}

1. NOTEBOOK: every number the model could see: all user messages and all tool_result blocks in the messages that
   were sent to the model (history included; assistant turns excluded). JSON numeric values count (bool does not);
   numbers inside strings count (agent.py passes tool results as str(result), so most arrive that way).
2. CLAIMS: numbers in the RAW reply (before render_citations), with an optional leading £ and a trailing % or m.
   SKIPPED as labels, not claims: GW<n> / gameweek <n>, dates (10 Oct, Oct 10, 2026-10-10), times (14:00, 10:00Z),
   4-digit years 19xx / 20xx, [n] citation markers, c<digits> result ids, ordinals (1st, 2nd), numbers inside URLs,
   list markers at a line start ("1." / "2)"). Skipped spans are blanked before the claim scan.
3. MATCH: a claim with d decimal places is grounded when, for some notebook number n, any of n, n*100 or n/10
   rounded (half-up, on the decimal repr) to d places equals the claim (absolute values). No other tolerance:
   5.83 grounds "5.8", 0.75 grounds "75%", 75 (price tenths) grounds "£7.5m"; nothing grounds "5.9" from 5.83,
   and 0.35 does NOT ground "0.3" (it rounds to 0.4; float round() would have said 0.3).
4. UNGROUNDED: every claim without a match, with up to 12 words of context from the reply.
Out of scope (2026-10-02): arithmetic on notebook numbers, number words, marking or blocking anything."""
import json
import re
from decimal import ROUND_HALF_UP, Decimal

_NUM = re.compile(r"(?<![\w.])-?\d+(?:,\d{3})*(?:\.\d+)?")
_CLAIM = re.compile(r"(?<![\w.£])(£?)(\d+(?:,\d{3})*(?:\.\d+)?)(%|m\b)?")
_MONTH = r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*"
SKIP_PATTERNS = (
    re.compile(r"https?://\S+"),                                       # numbers inside URLs
    re.compile(r"\bGW\s?\d+\b", re.I),                                 # GW6, GW 6
    re.compile(r"\bgameweeks?\s+\d+\b", re.I),                         # gameweek 6
    re.compile(r"\b\d{1,2}(?:st|nd|rd|th)?\s+" + _MONTH + r"\b", re.I),  # 10 Oct, 1 October
    re.compile(r"\b" + _MONTH + r"\.?\s+\d{1,2}\b", re.I),             # Oct 10
    re.compile(r"\b\d{4}-\d{2}-\d{2}\b"),                              # 2026-10-10
    re.compile(r"\b\d{1,2}:\d{2}(?::\d{2})?Z?\b"),                     # 14:00, 10:00Z, 11:01:48
    re.compile(r"\b(?:19|20)\d{2}\b"),                                 # 4-digit years
    re.compile(r"\[\d+\]"),                                            # [n]
    re.compile(r"\bc\d+\b"),                                           # c<digits>
    re.compile(r"\b\d+(?:st|nd|rd|th)\b"),                             # ordinals
    re.compile(r"(?m)^[ \t]*(?:[-*]\s+)?\d+[.)](?=\s)"),               # list markers at a line start
)
CONTEXT_BEFORE, CONTEXT_AFTER = 6, 5                                  # words around the claim (<= 12 with the claim)


def _to_float(s):
    try:
        return float(s.replace(",", ""))
    except ValueError:
        return None


def _walk(x, out):
    if isinstance(x, bool) or x is None:
        return
    if isinstance(x, (int, float)):
        out.add(float(x))
    elif isinstance(x, str):
        for m in _NUM.finditer(x):
            v = _to_float(m.group(0))
            if v is not None:
                out.add(v)
    elif isinstance(x, dict):
        for v in x.values():
            _walk(v, out)
    elif isinstance(x, (list, tuple)):
        for v in x:
            _walk(v, out)
    else:
        d = getattr(x, "__dict__", None)
        if isinstance(d, dict):
            _walk(d, out)


def notebook(messages):
    """The set of numbers in every user message and every tool_result block of `messages`."""
    out = set()
    for m in messages or []:
        role = m.get("role") if isinstance(m, dict) else getattr(m, "role", None)
        if role != "user":
            continue
        content = m.get("content") if isinstance(m, dict) else getattr(m, "content", None)
        if isinstance(content, str):
            _walk(content, out)
            continue
        for block in content or []:
            b = block if isinstance(block, dict) else getattr(block, "__dict__", {})
            if b.get("type") == "tool_result":
                _walk(b.get("content"), out)
            elif b.get("type") == "text":
                _walk(b.get("text"), out)
            else:
                _walk(b, out)
    return out


def mask_labels(text):
    """The reply with every skipped label blanked to spaces (same length, so positions still map to the original)."""
    chars = list(text or "")
    for pat in SKIP_PATTERNS:
        for m in pat.finditer(text or ""):
            for i in range(m.start(), m.end()):
                chars[i] = " "
    return "".join(chars)


def claims(raw_reply):
    """[{text, value, decimals, start, end}] for every number claim in the reply, labels skipped."""
    masked = mask_labels(raw_reply)
    out = []
    for m in _CLAIM.finditer(masked):
        number = m.group(2)
        v = _to_float(number)
        if v is None:
            continue
        decimals = len(number.split(".")[1]) if "." in number else 0
        out.append({"text": m.group(0), "value": v, "decimals": decimals, "start": m.start(), "end": m.end()})
    return out


def _context(text, start, end):
    before = text[:start].split()[-CONTEXT_BEFORE:]
    after = text[end:].split()[:CONTEXT_AFTER]
    return " ".join(before + [text[start:end]] + after)


def _round(x, d):
    """Conventional half-up rounding to d decimal places on the number's shortest repr (0.35 -> 0.4, 5.83 -> 5.8),
    not float round() (which gives round(0.35, 1) == 0.3 and would ground an invented 0.3 from a 0.35 start chance)."""
    return float(Decimal(repr(float(x))).quantize(Decimal(1).scaleb(-d), rounding=ROUND_HALF_UP))


def check(raw_reply, messages):
    nb = notebook(messages)
    cs = claims(raw_reply)
    by_dec = {}
    grounded, ungrounded = 0, []
    for c in cs:
        d = c["decimals"]
        if d not in by_dec:
            s = set()
            for n in nb:
                a = abs(n)
                s.update((_round(a, d), _round(a * 100, d), _round(a / 10, d)))
            by_dec[d] = s
        if _round(abs(c["value"]), d) in by_dec[d]:
            grounded += 1
        else:
            ungrounded.append({"text": c["text"], "value": c["value"], "context": _context(raw_reply or "", c["start"], c["end"])})
    return {"numbers_found": len(cs), "grounded": grounded, "ungrounded": ungrounded, "notebook_size": len(nb)}


def record_numeric_check(turn_id, result, error=None, conn=None):
    """One numeric_checks row per reply: the counts and the ungrounded list, or the checker's error."""
    import psycopg2.extras
    own = conn is None
    if own:
        import db_write
        conn = db_write.connect()
    try:
        r = result or {}
        with conn.cursor() as cur:
            cur.execute("INSERT INTO numeric_checks (turn_id, numbers_found, grounded, ungrounded, notebook_size, error) "
                        "VALUES (%s, %s, %s, %s, %s, %s)",
                        (turn_id, r.get("numbers_found"), r.get("grounded"),
                         psycopg2.extras.Json(r["ungrounded"]) if "ungrounded" in r else None, r.get("notebook_size"), error))
        conn.commit()
    finally:
        if own:
            conn.close()


if __name__ == "__main__":                       # python numeric_grounding.py "<reply>" '<json messages>'
    import sys
    print(json.dumps(check(sys.argv[1], json.loads(sys.argv[2]) if len(sys.argv) > 2 else []), indent=1))
