"""Code checks on eval answers, HEAD vs base on the same data (tracked home, 2026-10-21, of the Thursday-gate script
`thu_code_checks.py` that gated every run from 15 Oct; the port keeps the functions and regexes as they were).
Usage:
    python eval/judge/code_checks.py --head h1.jsonl[,h2.jsonl] --base b1.jsonl[,b2...] --out out.json
Every answer of every file counts (re-runs included): per side, the share of answers with each finding, on the question
ids BOTH sides answered (common); HEAD's totals over all its answers are reported too.
Checks (on the rendered reply, Sources list stripped): jargon words, xPts, status letters, unsourced / wrong clubs
(eval/judge/club_claims), captain "bonus", internal ids, and FLAGS RELABELLED.

FLAGS RELABELLED -- the definition (2026-10-21):
    A sentence FAILS flags-relabelled only if it ties an FPL flag / chance of playing to a gameweek different from
    the gameweek the turn's tool output gives for that flag (e.g. 'Gakpo 25% for GW8' when the tool says GW7). A flag
    and an unrelated gameweek in the same sentence (a plan step 'GW11: ...', a gap 'for GW8 alone') is NOT a tie. A
    flag stated with no gameweek is NOT this check.
A separate REPORT-ONLY row, "flag without gameweek" (a sentence naming a flagged player with an availability word
and no gameweek at all), never gates.

The flag's gameweek comes from the turn's tool outputs: every chance_words / chance_words_out / chance_words_in label
("chance of playing in GW<n>: ..." or "latest FPL flag (for GW<n>, ...)") keyed by the player's surname."""
import argparse
import ast
import json
import os
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
for p in (str(REPO / "eval"), str(REPO), str(REPO / "squad")):
    if p not in sys.path:
        sys.path.insert(0, p)
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-used")
import agent  # noqa: E402,F401  (the tool schema: the club checker's player table reads the same data the agent does)
from judge import club_claims as CC  # noqa: E402
from judge import run_judge as RJ  # noqa: E402

JARGON = re.compile(r"\b(ingest(?:ed|ion|s)?|post-ingest|horizon|cutoff|cut-off|solve[sd]?|solver|optimi[sz]er|frame)\b|\brun \d+\b|\bthe run\b", re.I)
CAPTAIN_BONUS = re.compile(r"(captain[^.\n]{0,60}\bbonus\b|\bbonus\b[^.\n]{0,60}captain|armband[^.\n]{0,40}\bbonus\b)", re.I)
INTERNAL_ID = re.compile(r"\b(?:player[_ ]?id|element(?:[_ ]id)?|proposal[_ ]?id|run[_ ]?id|version[_ ]?id)\b\s*[:#=]?\s*\d+|\bids?\s*[:#=]?\s*\d{2,}\b", re.I)
STATUS_LETTER = re.compile(r"\bstatus\s*[:=]?\s*['\"`(]?[adisun]['\"`)]?(?![\w%])", re.I)
XPTS = re.compile(r"\bxpts\b", re.I)
AVAIL = re.compile(r"injur|suspen|doubt|unavailable|ruled out|\bout (?:for|of)\b|\bmiss(?:es|ing)?\b|\d+\s?% chance|chance of playing|\b0%|flag", re.I)
GW_RE = re.compile(r"\bGW\s?(\d{1,2})\b|\bgameweek\s(\d{1,2})\b", re.I)
FLAG_GW = re.compile(r"(?:in|for) GW(\d{1,2})")
FLAG_CHANCE = re.compile(r"(\d{1,3})\s?%")
SENT = re.compile(r"(?<=[.!?])\s+|\n+")
# A tie (the definition in the docstring): an availability token and a gameweek token bound together inside ONE
# clause -- "0% chance of playing in GW8", "miss GW8", "out until GW9", "return for GW8", "For GW8, X is unavailable".
# Clauses end at a dash, a colon, a semicolon or a pipe, which is how plan steps ("- **GW11:** ...") and gap figures
# ("+11.9 for GW8 alone -- ...") stand apart from the flag they share a sentence with. A span between the two tokens
# that names a transfer, a gain or a plan step is not a tie either ("Collins (injured) → Calafiori for GW8").
CLAUSE = re.compile(r"\s[—–]\s|[:;|]|\s-\s")
AVAIL_WORDS = (r"injur(?:y|ed|ies)?|suspen(?:ded|sion)|doubt(?:ful|s)?|unavailable|available|ruled out|\bout\b|miss(?:es|ing|ed)?|"
               r"return(?:s|ed|ing)?|\bback\b|\bfit\b|flag(?:ged|s)?|chance(?: of playing)?|playing|play")
GW_TOKEN = r"(?:GW\s?(\d{1,2})|gameweek\s+(\d{1,2}))"
PREP = r"(?:for|in|until|through|by|from|before|after|ahead of|into|during|at|of)"
SPAN = r"[^.;:|—–\n]{0,40}?"
NON_TIE = re.compile(r"→|->|transfer|swap|move|bring|replace|sell|buy|sold|bought|gain|gap|points?\b|pts|alone|driven|plan|step", re.I)
LATEST_FLAG = re.compile(r"latest (?:FPL )?flag", re.I)


def _avail_re(chances):
    """The availability vocabulary for one player: the words plus the player's own flag percentages ("25%")."""
    pct = "|".join(rf"\b{int(c)}\s?%" for c in sorted(chances or ()))
    return re.compile(AVAIL_WORDS + (f"|{pct}" if pct else ""), re.I)


def _ties(clause, avail):
    """[(gw, span text)] for every availability token bound to a gameweek token in the clause."""
    out = []
    # no \b after the token: a percentage ("25%") ends in a non-word character and would never match one
    fwd = re.compile(rf"(?P<a>{avail.pattern})(?P<mid>{SPAN})(?:\b{PREP}\s+(?:the\s+)?)?{GW_TOKEN}\b", re.I)
    bwd = re.compile(rf"\b{GW_TOKEN}\b(?P<mid>{SPAN})(?P<a>{avail.pattern})", re.I)
    for m in list(fwd.finditer(clause)) + list(bwd.finditer(clause)):
        if NON_TIE.search(m.group("mid") or ""):
            continue
        nums = [g for g in m.groups() if g and g.isdigit()]
        if nums:
            out.append((int(nums[-1]), m.group(0)))
    return out


def load(paths):
    out = []
    for p in paths:
        for line in Path(p).read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                if r.get("result") in ("PASS", "FAIL"):
                    out.append(r)
    return out


def _parse(o):
    if isinstance(o, (dict, list)):
        return o
    if isinstance(o, str):
        for f in (json.loads, ast.literal_eval):
            try:
                return f(o)
            except Exception:                            # noqa: BLE001
                pass
    return None


def tool_flags(rec):
    """{surname_lower: {"gws": set, "chances": set}} from every chance_words* label in the record's tool outputs
    ("chance of playing in GW7: 25%, ..." / "latest FPL flag (for GW7, ...): chance of playing 25%")."""
    flags = defaultdict(lambda: {"gws": set(), "chances": set()})

    def add(name, w):
        m = FLAG_GW.search(w)
        if m and isinstance(name, str) and name.strip():
            f = flags[name.split()[-1].lower()]
            f["gws"].add(int(m.group(1)))
            c = FLAG_CHANCE.search(w)
            if c:
                f["chances"].add(int(c.group(1)))

    def walk(x):
        if isinstance(x, dict):
            for key, side in (("chance_words", None), ("chance_words_out", "out"), ("chance_words_in", "in")):
                w = x.get(key)
                if isinstance(w, str):
                    add(x.get(side) if side else x.get("name"), w)
            if isinstance(x.get("availability"), dict) and isinstance(x["availability"].get("chance_words"), str):
                add(x.get("name"), x["availability"]["chance_words"])
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)
    for t in rec.get("turns") or []:
        for c in t.get("calls") or []:
            walk(_parse(c.get("output") if c.get("output") is not None else c.get("result")))
    return dict(flags)


def relabelled(text, flags):
    """The flags-relabelled hits of a reply: one per (player, sentence) where a clause ties the player's flag / chance
    to a gameweek that is not the one the tool output gave for that flag. The F13 form ("latest flag") is never a hit."""
    hits = []
    for s in SENT.split(text):
        if LATEST_FLAG.search(s):
            continue
        for surname, f in flags.items():
            if not re.search(r"\b" + re.escape(surname) + r"\b", s, re.I):
                continue
            avail = _avail_re(f["chances"])
            wrong = []
            for clause in CLAUSE.split(s):
                if not re.search(r"\b" + re.escape(surname) + r"\b", clause, re.I) or not avail.search(clause):
                    continue
                for gw, span in _ties(clause, avail):
                    if gw not in f["gws"]:
                        wrong.append((gw, span))
            if wrong:
                hits.append({"player": surname, "flag_gw": sorted(f["gws"]), "sentence_gw": sorted({g for g, _ in wrong}),
                             "tie": wrong[0][1][:120], "sentence": s.strip()[:220]})
    return hits


def _flag_re(chances):
    """A FLAG statement (for the report-only row): the flag vocabulary the gating check always used, plus the player's
    own percentages -- not the wider tie vocabulary ("play", "back", "out"), which would count "barely plays" as a flag."""
    pct = "|".join(rf"\b{int(c)}\s?%" for c in sorted(chances or ()))
    return re.compile(AVAIL.pattern + (f"|{pct}" if pct else ""), re.I)


def flag_without_gw(text, flags):
    """REPORT-ONLY: sentences that name a flagged player with a flag statement and no gameweek at all."""
    out = []
    for s in SENT.split(text):
        if GW_RE.search(s):
            continue
        for surname, f in flags.items():
            if re.search(r"\b" + re.escape(surname) + r"\b", s, re.I) and _flag_re(f["chances"]).search(s):
                out.append({"player": surname, "flag_gw": sorted(f["gws"]), "sentence": s.strip()[:220]})
    return out


PLAYERS = CC.load_players()


def checks(rec):
    rend = RJ.strip_sources(rec.get("rendered_reply") or "")
    r2 = dict(rec, rendered_reply=rec.get("rendered_reply") or "")
    r2.setdefault("calls", [c for t in (rec.get("turns") or [])[-1:] for c in t.get("calls") or []])
    try:
        cs = CC.summary(CC.check(r2, PLAYERS))
    except Exception:                                    # noqa: BLE001
        cs = {"unsourced": 0, "wrong_vs_table": 0}
    flags = tool_flags(rec)
    return {"jargon": sorted({m.group(0).lower() for m in JARGON.finditer(rend)}),
            "xpts": len(XPTS.findall(rend)),
            "status_letters": [m.group(0) for m in STATUS_LETTER.finditer(rend)],
            "unsourced_clubs": cs["unsourced"], "wrong_clubs": cs["wrong_vs_table"],
            "captain_bonus": [m.group(0) for m in CAPTAIN_BONUS.finditer(rend)],
            "internal_ids": [m.group(0) for m in INTERNAL_ID.finditer(rend)],
            "flag_relabelled": relabelled(rend, flags),
            "flag_without_gw": flag_without_gw(rend, flags)}


KEYS = ("jargon", "xpts", "status_letters", "unsourced_clubs", "wrong_clubs", "captain_bonus", "internal_ids", "flag_relabelled")
REPORT_ONLY_KEYS = ("flag_without_gw",)          # reported beside the gating rows, never compared for a verdict


def totals(recs):
    t = Counter()
    for r in recs:
        c = r["_checks"]
        for k in KEYS + REPORT_ONLY_KEYS:
            t[k + ("_replies" if k not in ("unsourced_clubs", "wrong_clubs") else "")] += (c[k] if k in ("unsourced_clubs", "wrong_clubs") else int(bool(c[k])))
    t["answers"] = len(recs)
    return dict(t)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--head", required=True)
    ap.add_argument("--base", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    head, base = load(a.head.split(",")), load(a.base.split(","))
    for r in head + base:
        r["_checks"] = checks(r)
    common = sorted({r["id"] for r in head} & {r["id"] for r in base})
    hc, bc = [r for r in head if r["id"] in common], [r for r in base if r["id"] in common]
    out = {"common_questions": common, "head_on_common": totals(hc), "base_on_common": totals(bc), "head_all": totals(head),
           "head_findings": {f"{r['id']}#{i}": {k: r["_checks"][k] for k in KEYS + REPORT_ONLY_KEYS if r["_checks"][k]}
                             for i, r in enumerate(head) if any(r["_checks"][k] for k in KEYS + REPORT_ONLY_KEYS)},
           "base_findings": {f"{r['id']}#{i}": {k: r["_checks"][k] for k in KEYS + REPORT_ONLY_KEYS if r["_checks"][k]}
                             for i, r in enumerate(base) if any(r["_checks"][k] for k in KEYS + REPORT_ONLY_KEYS)}}
    Path(a.out).write_text(json.dumps(out, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
    for k in ("head_on_common", "base_on_common", "head_all"):
        print(k, out[k])
    print("common", len(common))


if __name__ == "__main__":
    main()
