"""The chunker for news_to_embed items (2026-09-30): deterministic, paragraph-based, no model,
no LLM. CHUNKER_VERSION is stamped on every news_chunks row; bump it when any rule here changes
and every item is chunked again beside the old rows.

Input: one news_embed_text string, "<header line>\\n<body>", where the header line is
"[<source label> | <date label>] <headline>" exactly as the view renders it. Output: Chunk rows
(index, text, char_count) whose text is ALWAYS "<header line>\\n<piece>", so every chunk carries
the source, the date and the headline, and a one-chunk item is its embed_text byte for byte
(when the body has no residue to remove).

Rules, in order:
  1. clean_body: drop a line made only of share words (SHARE_WORDS: "Facebook Twitter Email
     WhatsApp LinkedIn Telegram", 16 such lines in the laptop club rows); drop an app-banner line
     (BANNER_PATTERNS: "Manchester City Official App Manchester City FC Ltd", 5 lines); drop a
     FIRST line that repeats the headline (17 of the club bodies start that way) -- since
     chunk_v2 also when the headline ends in an ellipsis (the extractor truncates long headlines)
     and the headline without it is a prefix of that line, case and spacing aside; since chunk_v2
     drop a TRAILING link list: the run of lines from the end up to the first prose line (at
     least PROSE_MIN_CHARS characters ending in terminal punctuation) when that run has at least
     TAIL_MIN_LINES lines, leaves at least one line above it, and passes
     club_news.looks_like_link_list by its title-line or repetition reason -- never by its
     "short" reason, which any tail would trip, and never from the middle of a body (the Man
     City related-links tail, the Newcastle repeated links, the Chelsea results table);
     collapse blank lines. Ordinary sentences that merely mention Twitter or Email are kept.
  2. Paragraphs are the remaining lines (the extractor already put one paragraph per line).
  3. Neighbouring paragraphs merge while the piece stays within TARGET_CHARS; a paragraph longer
     than MAX_CHARS splits at sentence boundaries into pieces within TARGET_CHARS (a single
     sentence longer than MAX_CHARS, never seen in our data, splits at a space before the max).
  4. The last sentence of piece n is repeated as the first line of piece n+1 (the overlap); the
     size limits apply to the piece before its overlap and its header are added, so a chunk's
     char_count can exceed MAX_CHARS by one sentence plus the header.
  5. A cleaned body of at most MAX_CHARS is one piece whatever the target: every FPL row, every
     BBC row and the short club items stay ONE chunk.
  6. A body that cleans to nothing gives one chunk holding the header alone.
Sentence boundaries are ". ! ?" (optionally followed by a closing quote or bracket) followed by
whitespace; "Mr. Smith" therefore splits, which only moves an overlap boundary, never loses text.
"""
import re
from dataclasses import dataclass

CHUNKER_VERSION = "chunk_v2"
TARGET_CHARS = 1000                 # merge neighbouring paragraphs up to about this
MAX_CHARS = 1600                    # a body within this stays one piece; a paragraph over it splits at sentences
SHARE_WORDS = ("facebook", "twitter", "email", "whatsapp", "linkedin", "telegram", "share")
BANNER_PATTERNS = (re.compile(r"\bofficial app\b", re.I),)      # "Manchester City Official App Manchester City FC Ltd"
PROSE_MIN_CHARS = 60                # a line this long ending in terminal punctuation bounds a trailing link list
TAIL_MIN_LINES = 2                  # a trailing link list has at least this many lines (a single caption is not one)
ELLIPSES = ("...", "…")

_SHARE_LINE = re.compile(r"^\W*(?:(?:" + "|".join(SHARE_WORDS) + r")\W*)+$", re.I)
_WS = re.compile(r"\s+")
_SENTENCE_END = re.compile(r"(?:(?<=[.!?][\"'”’)\]])|(?<=[.!?]))\s+")
_PROSE_END = (".", "!", "?", '"', "”", "’", "'")


@dataclass(frozen=True)
class Chunk:
    index: int
    text: str
    char_count: int


def _norm(s):
    return _WS.sub(" ", (s or "").strip().casefold()).rstrip(" .:!?…")


def _headline_repeat(first, headline):
    """(repeats, by_ellipsis): the first body line repeats the headline exactly, or the headline
    ends in an ellipsis and its stem is a prefix of the line."""
    n_first, n_head = _norm(first), _norm(headline)
    if not n_head:
        return False, False
    if n_first == n_head:
        return True, False
    if headline.strip().endswith(ELLIPSES) and n_first.startswith(n_head):
        return True, True
    return False, False


def _is_prose(line):
    return len(line) >= PROSE_MIN_CHARS and line.endswith(_PROSE_END)


def trailing_link_list(lines):
    """How many lines at the end of `lines` form a link list (rule 1, chunk_v2): the run up to the
    first prose line from the end, when it is a proper suffix of at least TAIL_MIN_LINES lines and
    club_news.looks_like_link_list passes it by a reason other than "short"."""
    k = 0
    for ln in reversed(lines):
        if _is_prose(ln):
            break
        k += 1
    if k < TAIL_MIN_LINES or k >= len(lines):
        return 0
    from club_news import looks_like_link_list
    ok, reasons = looks_like_link_list("\n".join(lines[len(lines) - k:]))
    if ok and any(not r.startswith("short") for r in reasons.split("; ") if r):
        return k
    return 0


def clean_body_details(body, headline):
    """(cleaned body, details): the residue lines removed, blank lines collapsed, a first line that
    repeats the headline dropped, a trailing link list dropped. details counts what fired:
    headline_repeat, ellipsis_headline (a repeat found through the ellipsis rule),
    trailing_link_list (lines dropped), residue_lines (share and banner lines dropped)."""
    details = {"headline_repeat": False, "ellipsis_headline": False, "trailing_link_list": 0, "residue_lines": 0}
    lines = []
    for raw in (body or "").split("\n"):
        line = raw.strip()
        if not line:
            continue
        if _SHARE_LINE.match(line) or any(p.search(line) for p in BANNER_PATTERNS):
            details["residue_lines"] += 1
            continue
        lines.append(line)
    if lines and headline:
        repeats, by_ellipsis = _headline_repeat(lines[0], headline)
        if repeats:
            details["headline_repeat"], details["ellipsis_headline"] = True, by_ellipsis
            lines = lines[1:]
    k = trailing_link_list(lines)
    if k:
        details["trailing_link_list"] = k
        lines = lines[:-k]
    return "\n".join(lines), details


def clean_body(body, headline):
    return clean_body_details(body, headline)[0]


def split_paragraphs(text):
    return [ln for ln in (text or "").split("\n") if ln.strip()]


def split_sentences(paragraph):
    """Sentences of a paragraph, whitespace-stripped, nothing lost: the text is split at the
    boundaries, never matched piecewise."""
    return [s.strip() for s in _SENTENCE_END.split(paragraph or "") if s.strip()]


def _hard_split(text, max_chars):
    """A single sentence over max_chars: split at the last space before the limit."""
    out = []
    while len(text) > max_chars:
        cut = text.rfind(" ", 0, max_chars)
        if cut <= 0:
            cut = max_chars
        out.append(text[:cut].rstrip())
        text = text[cut:].lstrip()
    if text:
        out.append(text)
    return out


def _merge(units, target, sep):
    """Greedy: neighbouring units join with sep while the piece stays within target; a unit
    longer than target is a piece on its own."""
    pieces, cur, cur_len = [], [], 0
    for u in units:
        if cur and cur_len + len(sep) + len(u) > target:
            pieces.append(sep.join(cur))
            cur, cur_len = [], 0
        cur.append(u)
        cur_len += len(u) + (len(sep) if len(cur) > 1 else 0)
    if cur:
        pieces.append(sep.join(cur))
    return pieces


def _split_long_paragraph(paragraph, target, max_chars):
    sentences = []
    for s in split_sentences(paragraph):
        sentences.extend(_hard_split(s, max_chars) if len(s) > max_chars else [s])
    return _merge(sentences, target, " ")


def chunk_body(body, target=TARGET_CHARS, max_chars=MAX_CHARS):
    """The cleaned body -> pieces with the overlap applied (rules 2-5). A body within max_chars
    is one piece; an empty body gives no pieces."""
    paras = split_paragraphs(body)
    if not paras:
        return []
    joined = "\n".join(paras)
    if len(joined) <= max_chars:
        return [joined]
    units = []
    for p in paras:
        units.extend([p] if len(p) <= max_chars else _split_long_paragraph(p, target, max_chars))
    pieces = _merge(units, target, "\n")
    out = [pieces[0]]
    for prev, piece in zip(pieces, pieces[1:]):
        last = split_sentences(prev.split("\n")[-1])
        out.append((last[-1] + "\n" + piece) if last else piece)
    return out


def chunk_embed_text_details(embed_text):
    """news_embed_text string -> ([Chunk], cleaning details); each text = header line + "\\n" + piece."""
    header, _, body = (embed_text or "").partition("\n")
    headline = header.split("] ", 1)[1] if "] " in header else ""
    cleaned, details = clean_body_details(body, headline)
    pieces = chunk_body(cleaned)
    texts = [header + "\n" + p for p in pieces] or [header]
    return [Chunk(i, t, len(t)) for i, t in enumerate(texts)], details


def chunk_embed_text(embed_text):
    return chunk_embed_text_details(embed_text)[0]
