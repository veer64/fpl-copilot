"""Builds the synthetic page fixtures for Tests/test_page_body.py. They copy the STRUCTURES measured on
2026-09-28 (KNOWN_ISSUES #27) with invented text, so no publisher's article enters the repo:
  stadion_article.html  -- manutd.com / nufc.co.uk shape: a Next.js flight payload (self.__next_f.push)
                           holding Contentful rich-text documents: MUTV-style accordion sections AND the
                           article under "bodyCopy"; <main> is only the related-links sidebar; no JSON-LD.
  stadion_nobody.html   -- the same page with no bodyCopy document (four of the eight Man Utd pages).
  jsonld_article.html   -- JSON-LD NewsArticle with articleBody, plus an <article> element.
  plain_article.html    -- no JSON-LD, no flight; the article sits in <article> inside <main>.
Run: python Tests/fixtures/pages/make_fixtures.py
"""
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent

def text(v):
    return {"nodeType": "text", "value": v, "marks": [], "data": {}}

def para(*nodes):
    return {"nodeType": "paragraph", "data": {}, "content": list(nodes)}

def doc(*paras):
    return {"nodeType": "document", "data": {}, "content": list(paras)}

ACCORDION = [
    {"title": "What programmes can I watch?", "assistiveText": "$undefined",
     "content": {"json": doc(para(text("Club TV offers the most in-depth on-demand and live coverage of the club anywhere. ")),
                             para(text("Our dedicated teams produce original programmes that get you closer to the sides."))),
                 "__typename": "AccordionSectionContent"}},
    {"title": "Can I add shows to my list?", "assistiveText": "$undefined",
     "content": {"json": doc(para(text("Create your own watchlists of your favourite shows by adding them to My List."))),
                 "__typename": "AccordionSectionContent"}},
]
BODY = doc(
    para(text("The Netherlands international is yet to feature under the new head coach, having missed the last two wins with a hamstring injury.")),
    para(text("However, the forward has been able to work with the group at the training ground again, alongside "),
         {"nodeType": "entry-hyperlink", "data": {"target": {"sys": {"id": "x"}}}, "content": [text("Harry Example")]},
         text(", in a boost for the club's attacking plans ahead of Saturday's league match.")),
    para(text("“Josh is back training this week, which is good news,” the head coach said on Friday.")),
    para(text("The squad trains again on Saturday morning before the trip south; a final decision on the pair follows the session.")),
)

def flight_chunk(obj, key):
    """one self.__next_f.push line as Next.js renders it: a JS string literal holding the RSC row"""
    row = f"{key}:" + json.dumps(["$", "$L3c", None, obj], separators=(",", ":"))
    return "<script>self.__next_f.push([1," + json.dumps(row + "\n") + "])</script>"

SIDEBAR = """<main>
<section><h2>Related Content</h2><p>You might also like</p>
<article><a href="/news/one">Team news for United v Fulham</a><span>News 11 hours ago</span><a href="/news/one">Team news for United v Fulham</a></article>
<article><a href="/news/two">Striker trains at Carrington</a><span>News 11 hours ago</span><a href="/news/two">Striker trains at Carrington</a></article>
<article><a href="/news/three">How to watch and follow: Fulham v United</a><span>News 12 hours ago</span><a href="/news/three">How to watch and follow: Fulham v United</a></article>
</section></main>"""

def stadion(with_body):
    page_obj = {"pageTitle": "Team news for United v Fulham", "sections": [{"__typename": "AccordionBlock", "items": ACCORDION}]}
    if with_body:
        page_obj["article"] = {"publishedAt": "2026-09-15T10:00:00.000Z", "bodyCopy": {"json": BODY, "__typename": "ArticlePageBodyCopy"}}
    return ("<!DOCTYPE html><html><head><title>Team news for United v Fulham | Club</title>"
            '<meta name="description" content="A positive update about a squad member returning to training this week."/></head><body>'
            + flight_chunk({"locale": "en", "children": ["$", "$L3d", None, {"siteHeader": {"links": []}}]}, "3b")
            + SIDEBAR + flight_chunk(page_obj, "50") + "<footer>©2026 Club</footer></body></html>")

JSONLD = ("<!DOCTYPE html><html><head><title>Boss gives team news update</title>"
          '<script type="application/ld+json">' + json.dumps({
              "@context": "https://schema.org", "@type": "NewsArticle", "headline": "Boss gives team news update",
              "datePublished": "2026-09-16T10:00:00Z",
              "articleBody": "The defender was injured in a first-half challenge and was withdrawn for treatment. "
                             "Ahead of Wednesday's cup quarter-final the head coach confirmed his side will be without him for around four weeks. "
                             "He also gave an update on the young full-back, who trained on Tuesday and is in contention for the weekend. "
                             "The midfielder who limped off at the weekend has had a scan and the club expects him back after the international break. "
                             "Everyone else in the squad trained on Thursday morning and the head coach said he would name his side on Friday."}) +
          "</script></head><body><main><article><p>The defender was injured in a first-half challenge and was withdrawn for treatment.</p>"
          "<p>Ahead of Wednesday's cup quarter-final the head coach confirmed his side will be without him for around four weeks.</p></article>"
          "<aside><a href='/a'>Related one</a><a href='/b'>Related two</a></aside></main></body></html>")

PLAIN = ("<!DOCTYPE html><html><head><title>Injury update from the head coach</title></head><body><nav><a href='/'>Home</a><a href='/news'>News</a></nav>"
         "<main><article><h1>Injury update from the head coach</h1>"
         "<p>The head coach reported no fresh injury concerns ahead of Saturday's league meeting at home.</p>"
         "<p>The winger, absent on Wednesday night with adductor issues, trained on Friday morning and is expected to be available for selection.</p>"
         "<p>Two long-term absentees remain sidelined and will be assessed again after the international break.</p>"
         "<p>The captain, who missed the last three matches with a calf problem, completed a full session on Thursday and will travel with the squad.</p>"
         "<p>The head coach added that the goalkeeper who was ill during the week has recovered and is available for selection.</p></article>"
         "<aside><a href='/x'>More news</a></aside></main><footer>Contact</footer></body></html>")

if __name__ == "__main__":
    (HERE / "stadion_article.html").write_text(stadion(True), encoding="utf-8")
    (HERE / "stadion_nobody.html").write_text(stadion(False), encoding="utf-8")
    (HERE / "jsonld_article.html").write_text(JSONLD, encoding="utf-8")
    (HERE / "plain_article.html").write_text(PLAIN, encoding="utf-8")
    for p in sorted(HERE.glob("*.html")):
        print(p.name, p.stat().st_size, "bytes")
