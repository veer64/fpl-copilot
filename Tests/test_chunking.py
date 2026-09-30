"""The chunker for news_to_embed items (chunking.py, 2026-09-30): deterministic, paragraph-based,
no model. Pinned here:
  * a short item (every FPL row, the BBC rows, short club pieces) is ONE chunk, byte-identical to its
    news_embed_text string;
  * the residue lines seen in our club data are removed: the social-share line, the Man City app
    banner, a first line that repeats the headline; blank lines collapse;
  * a long article splits at paragraph boundaries, small paragraphs merge up to the target, an
    over-long paragraph splits at sentence boundaries, never mid-sentence;
  * the last sentence of chunk n opens chunk n+1 (the overlap);
  * every chunk starts with the SAME header line as news_embed_text; char_count = len(text);
  * the same input always gives the same chunks (CHUNKER_VERSION chunk_v1).
"""
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
import chunking as ch  # noqa: E402

HEADLINE = "Team news: Rodri fit for Sunday"
HEADER = f"[Man City official site | 2026-09-26] {HEADLINE}"
SHARE = "Facebook Twitter Email WhatsApp LinkedIn Telegram"                 # 16 lines in the laptop club rows
BANNER = "Manchester City Official App Manchester City FC Ltd"              # 5 lines in the laptop club rows


def sentence(i, width=60):
    """one deterministic sentence of about `width` characters ending in a full stop"""
    core = f"Sentence {i} of the article says that the squad trained again"
    return (core + " and again" * 10)[: width - 1].rstrip() + "."


def paragraph(i, sentences=3, width=60):
    return " ".join(sentence(i * 100 + k, width) for k in range(sentences))


def body_lines(chunk):
    """the body lines of a chunk, after its header line"""
    lines = chunk.text.split("\n")
    assert lines[0] == HEADER
    return lines[1:]


def test_version_and_limits_pinned():
    assert ch.CHUNKER_VERSION == "chunk_v2"
    assert ch.TARGET_CHARS == 1000 and ch.MAX_CHARS == 1600


# ---- chunk_v2: the truncated headline and the trailing link list (rulings 2026-09-30) -------------------

TRUNCATED_HEADLINE = "Manager provides injury update and team news ahead of ..."       # the extractor's ellipsis
FULL_FIRST_LINE = "Manager provides injury update and team news ahead of Canaries clash"

# the shape of the Man City related-links tail: 5 short title lines, two 76-character lines without
# terminal punctuation and a short call to action ending in "!"; no publisher text
TAIL = ["Club v Rivals: Player in the spotlight for the cup programme",
        "Manager: Everyone who plays against Rivals will be vital for us this season",
        "Watch: the manager's cup press conference in full",
        "Band to stage record-breaking 11-show stadium residency",
        "Club launch website dedicated to athlete health support and education programme",
        "How the club won away from home",
        "Manager provides injury update on two players",
        "Join our video call with a player today!"]
PROSE = ["The club are nine-time winners of the competition, having emerged victorious in nine seasons since 1970.",
         "Make sure you secure your spot at the stadium as we look for more glory this season!"]


def test_truncated_headline_prefix_is_dropped_as_a_repeat():
    body = f"{FULL_FIRST_LINE}\nMore text about the squad."
    assert ch.clean_body(body, TRUNCATED_HEADLINE) == "More text about the squad."
    assert ch.clean_body(body, TRUNCATED_HEADLINE.replace("...", "…")) == "More text about the squad."
    assert ch.clean_body(f"  {FULL_FIRST_LINE.upper()}\nMore text.", TRUNCATED_HEADLINE) == "More text."


def test_headline_without_ellipsis_is_not_a_prefix_rule():
    body = "Team news and more besides.\nMore text."
    assert ch.clean_body(body, "Team news") == body


def test_trailing_link_list_is_dropped_and_prose_kept():
    lines = [paragraph(1, 4, 70), paragraph(2, 4, 70)] + PROSE + TAIL
    cleaned = ch.clean_body("\n".join(lines), "Some headline")
    assert cleaned.split("\n") == [paragraph(1, 4, 70), paragraph(2, 4, 70)] + PROSE
    assert len(TAIL) == 8 and sum(len(ln) < 70 and not ln.endswith((".", "!", "?", '"', "”", ":")) for ln in TAIL) == 5


def test_link_list_in_the_middle_of_a_body_is_kept():
    lines = [paragraph(1, 4, 70)] + TAIL + PROSE
    assert ch.clean_body("\n".join(lines), "Some headline") == "\n".join(lines)


def test_trailing_repeated_links_are_dropped():
    pair = ["International duty: a player named in the under-21s squad", "Match officials for the next clash confirmed",
            "Loan Watch: a loanee off the mark for his new club"]
    lines = [paragraph(1, 5, 70), paragraph(2, 5, 70)] + pair + pair
    assert ch.clean_body("\n".join(lines), "Some headline").split("\n") == [paragraph(1, 5, 70), paragraph(2, 5, 70)]


def test_trailing_short_quotes_are_prose_not_a_link_list():
    lines = [paragraph(1, 4, 70), "“He is very close,” said the manager.", "“For us it is a big blow,” he said."]
    assert ch.clean_body("\n".join(lines), "Some headline") == "\n".join(lines)


def test_trailing_footer_that_is_not_title_like_is_kept():
    lines = [paragraph(1, 4, 70), "Club v Visitors", "Continental league: league phase matchday one",
             "Tickets available here.", "Live audio commentary on the club's channel."]
    assert ch.clean_body("\n".join(lines), "Some headline") == "\n".join(lines)


def test_tail_rule_runs_after_the_share_line_rule():
    lines = [paragraph(1, 4, 70)] + PROSE + TAIL + [SHARE]
    assert ch.clean_body("\n".join(lines), "Some headline").split("\n") == [paragraph(1, 4, 70)] + PROSE


def test_clean_details_report_which_v2_rules_fired():
    body = "\n".join([FULL_FIRST_LINE] + PROSE + TAIL)
    cleaned, d = ch.clean_body_details(body, TRUNCATED_HEADLINE)
    assert cleaned == "\n".join(PROSE)
    assert d == {"headline_repeat": True, "ellipsis_headline": True, "trailing_link_list": 8, "residue_lines": 0}
    _, d2 = ch.clean_body_details("\n".join([SHARE] + PROSE), "Other")
    assert d2 == {"headline_repeat": False, "ellipsis_headline": False, "trailing_link_list": 0, "residue_lines": 1}


# ---- cleaning ----------------------------------------------------------------------------------------

def test_residue_lines_removed_with_the_real_strings():
    body = "\n".join([HEADLINE, SHARE, BANNER, "Rodri has trained fully this week.", "", "", SHARE,
                      "He should start on Sunday.", "Share", "Facebook | Twitter | Email"])
    assert ch.clean_body(body, HEADLINE) == "Rodri has trained fully this week.\nHe should start on Sunday."


def test_headline_repeat_is_dropped_only_as_the_first_line():
    body = f"Intro line.\n{HEADLINE}\nMore text."
    assert ch.clean_body(body, HEADLINE) == body
    body2 = f"  {HEADLINE.upper()}  \nMore text."
    assert ch.clean_body(body2, HEADLINE) == "More text."


def test_ordinary_lines_naming_a_share_word_are_kept():
    body = "He posted on Twitter that he is fit.\nEmail the club for tickets."
    assert ch.clean_body(body, HEADLINE) == body


# ---- one chunk ---------------------------------------------------------------------------------------

def test_short_item_is_one_chunk_identical_to_embed_text():
    text = "[FPL official | 2026-09-26 11:00Z] Palmer (CHE, MID)\nStatus: doubtful. 75% chance of playing. Knock - 75% chance of playing"
    chunks = ch.chunk_embed_text(text)
    assert len(chunks) == 1
    c = chunks[0]
    assert (c.index, c.text, c.char_count) == (0, text, len(text))


def test_body_that_fits_in_the_max_stays_one_chunk_even_over_the_target():
    paras = [paragraph(i, 5, 70) for i in range(4)]         # about 1,400 characters, over the target
    body = "\n".join(paras)
    assert ch.TARGET_CHARS < len(body) <= ch.MAX_CHARS
    chunks = ch.chunk_embed_text(HEADER + "\n" + body)
    assert len(chunks) == 1 and body_lines(chunks[0]) == paras


def test_bbc_and_short_club_items_are_one_chunk():
    text = HEADER + "\n" + SHARE + "\n" + paragraph(1) + "\n" + paragraph(2)
    chunks = ch.chunk_embed_text(text)
    assert len(chunks) == 1
    assert body_lines(chunks[0]) == [paragraph(1), paragraph(2)]        # the share line is gone


# ---- splitting ---------------------------------------------------------------------------------------

def test_long_article_splits_at_paragraph_boundaries():
    paras = [paragraph(i, 6, 70) for i in range(10)]        # about 4,200 characters
    chunks = ch.chunk_embed_text(HEADER + "\n" + "\n".join(paras))
    assert len(chunks) >= 4
    seen = []
    for k, c in enumerate(chunks):
        lines = body_lines(c)
        if k > 0:
            lines = lines[1:]                               # the overlap line
        assert all(ln in paras for ln in lines), "a chunk holds something that is not a whole paragraph"
        seen.extend(lines)
    assert seen == paras                                     # every paragraph once, in order


def test_small_paragraphs_are_merged_up_to_the_target():
    paras = [paragraph(i, 2, 50) for i in range(30)]        # 30 short paragraphs, about 100 chars each
    chunks = ch.chunk_embed_text(HEADER + "\n" + "\n".join(paras))
    assert 3 <= len(chunks) <= 5
    first = body_lines(chunks[0])
    assert len(first) >= 8                                   # merged, not one paragraph per chunk
    assert len("\n".join(first)) <= ch.TARGET_CHARS
    for c in chunks:
        assert len("\n".join(body_lines(c)[1:])) <= ch.TARGET_CHARS


def test_overlong_paragraph_splits_at_sentence_boundaries():
    sentences = [sentence(i, 80) for i in range(40)]         # one 3,200-character paragraph
    para = " ".join(sentences)
    assert len(para) > ch.MAX_CHARS
    chunks = ch.chunk_embed_text(HEADER + "\n" + para)
    assert len(chunks) >= 3
    covered = []
    for k, c in enumerate(chunks):
        lines = body_lines(c)
        piece = lines[-1]
        assert piece.endswith(".")
        parts = ch.split_sentences(piece)
        assert all(p in sentences for p in parts), "a sentence was cut"
        assert len(piece) <= ch.MAX_CHARS
        covered.extend(parts)
    # every sentence appears, in order, once in the non-overlap text
    non_overlap = []
    for c in chunks:
        non_overlap.extend(ch.split_sentences(body_lines(c)[-1]))      # the overlap sits on its own line above
    assert non_overlap == sentences


def test_overlap_is_the_last_sentence_of_the_previous_chunk():
    paras = [paragraph(i, 6, 70) for i in range(10)]
    chunks = ch.chunk_embed_text(HEADER + "\n" + "\n".join(paras))
    assert len(chunks) >= 3
    for prev, nxt in zip(chunks, chunks[1:]):
        last_line = body_lines(prev)[-1]
        assert body_lines(nxt)[0] == ch.split_sentences(last_line)[-1]


def test_header_on_every_chunk_and_char_count():
    paras = [paragraph(i, 6, 70) for i in range(10)]
    chunks = ch.chunk_embed_text(HEADER + "\n" + "\n".join(paras))
    assert [c.index for c in chunks] == list(range(len(chunks)))
    for c in chunks:
        assert c.text.split("\n")[0] == HEADER
        assert c.char_count == len(c.text)


def test_same_input_gives_identical_output():
    text = HEADER + "\n" + "\n".join([SHARE] + [paragraph(i, 6, 70) for i in range(10)] + [BANNER])
    a = ch.chunk_embed_text(text)
    b = ch.chunk_embed_text(text)
    assert [(c.index, c.text, c.char_count) for c in a] == [(c.index, c.text, c.char_count) for c in b]


def test_header_only_item_is_one_chunk():
    chunks = ch.chunk_embed_text(HEADER + "\n" + SHARE)
    assert len(chunks) == 1 and chunks[0].text == HEADER
