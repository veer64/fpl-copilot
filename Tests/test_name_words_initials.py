"""Owner's extra on the F5 branch (24 Nov 2026; eval/reports/f6_fixes.md section 8.1): agent._name_words took EVERY token of a
player's names, so FPL's initials became name words -- 40 web names carry one: "A.Becker" gave "a", "I.Sangaré" gave "i" -- and
every source sentence with the article "a" or the pronoun "I" then counted as naming those players: in fix E's sourcing (F2b, F6:
"a source sentence naming him"), in _report_for (the report the availability line quotes) and in the search results said to be
about him. One-letter tokens are dropped; every longer token stays (two-letter particles such as "de" are untouched). No model, no
network, no database."""
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
for p in (str(REPO), str(REPO / "squad")):
    if p not in sys.path:
        sys.path.insert(0, p)

import agent                                                                # noqa: E402
import availability_check as av                                            # noqa: E402

BECKER = {"name": "Alisson Ramses Becker", "web_name": "A.Becker"}
SANGARE = {"name": "Ibrahim Sangaré", "web_name": "I.Sangaré"}


def test_an_initial_is_not_a_name_word():
    assert agent._name_words(BECKER) == {"alisson", "ramses", "becker"}
    assert agent._name_words(SANGARE) == {"ibrahim", "sangare"}


def test_every_longer_token_stays():
    assert agent._name_words({"name": "Benjamin Sesko", "web_name": "Šeško"}) == {"benjamin", "sesko"}
    assert agent._name_words({"name": "Matthijs de Ligt", "web_name": "De Ligt"}) == {"matthijs", "de", "ligt"}
    assert agent._name_words({"name": "Ji-soo Ma", "web_name": "Ma"}) == {"ji", "soo", "ma"}
    assert agent._name_words({}) == set()


def test_a_sentence_with_the_article_a_or_the_pronoun_i_no_longer_names_him():
    text = "I think it is a big week for the club. Becker has a hamstring injury and will be out for three weeks."
    said = av.name_sentences(text, agent._name_words(BECKER))
    assert said == ["Becker has a hamstring injury and will be out for three weeks."]
    assert av.report_sentence("I expect a tough game on Saturday. Nobody else is out.", None, agent._name_words(BECKER)) is None
    assert av.name_sentences("I was told the club have a plan.", agent._name_words(SANGARE)) == []
