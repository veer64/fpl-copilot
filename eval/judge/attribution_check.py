"""M3b attribution spot-check by CODE (judge final, 2026-10-13): for the number items the judge marked DIRECT / DERIVED,
does the quote it rests on belong to the same player, gameweek and stat family as the claim? Three checks per item,
each MATCH / CONFLICT / NOT CHECKABLE; the output workbook holds ONLY the CONFLICT rows (review sheet first), then
the counts and every item.

    python eval/judge/attribution_check.py --results <answers.jsonl> [--results more] --run <judge M3b run.jsonl>
                                           [--numbers-sheet eval/judge/fresh_v1_numbers_check.xlsx] --out <xlsx>

Rules: the claim is located in the reply through its context; a claim inside a markdown table takes its player from
the same row (a full name beats a surname; a row whose name fits several players is NOT CHECKABLE), its gameweek from
the row's GW column (or the column header) and its stat family from the column header; a claim in prose takes the
nearest player named BEFORE it in the same sentence (then the same paragraph; a pronoun between that name and the
claim, or a pronoun subject, is NOT CHECKABLE), the gameweek named within ~45 characters before it or a relative word
("next week") resolved through the context block, and the stat family named within a tight window on its own line
(28 before / 22 after; a scoreline beside a result word is goals) -- exactly one family, else NOT CHECKABLE. The
quote's player is a full name, a unique surname or a player_id / element; its gameweek is 'gw': n / GW n / 'event': n;
its stat family is the field names it carries. Player names come from the players table (club_claims.load_players)."""
import argparse
import json
import re
import sys
import unicodedata
from collections import Counter
from pathlib import Path

import openpyxl
from openpyxl.styles import Font, PatternFill

REPO = Path(__file__).resolve().parents[2]
for p in (str(REPO), str(REPO / "squad"), str(REPO / "eval")):
    if p not in sys.path:
        sys.path.insert(0, p)
from judge import club_claims as CC                    # noqa: E402
from judge import run_judge as RJ                      # noqa: E402

PASS_TYPES = ("DIRECT", "DERIVED")
FAMILIES = {
    "points": re.compile(r"\b(points?|pts|xp(?:ts)?|expected points|e_points|median|middle|floor|ceiling)\b", re.I),
    "price": re.compile(r"£|\b(price|cost|costs|budget|bank|million|sell|sells|buy|bought|paid)\b|\d\.\d+m\b", re.I),
    "probability": re.compile(r"\b(chance|probabilit\w*|odds|p_start|p_60|p_play|to play|to start)\b", re.I),
    "minutes": re.compile(r"\b(minutes?|mins?)\b", re.I),
    "goals": re.compile(r"\b(goals?|scored|conceded|xg|expected goals|goal difference|gd|gf|ga)\b", re.I),
    "assists": re.compile(r"\b(assists?|xa)\b", re.I),
    "clean sheets": re.compile(r"\b(clean.sheets?)\b", re.I),
    "saves": re.compile(r"\b(saves?)\b", re.I),
    "score out of 10": re.compile(r"\b(out of 10|/10|attack(?:ing)? score|defen[cs]\w* score|attack_score|defence_score|fixture score|ease|difficulty|tenth)\b", re.I),
    "possession": re.compile(r"\b(possession)\b", re.I),
    "matches": re.compile(r"\b(games?|matches|played|wins?|won|draws?|drawn|loss(?:es)?|lost)\b", re.I),
    "rank": re.compile(r"\b(place|position|rank)\b|\d+(?:st|nd|rd|th)\b", re.I),
}
QUOTE_FIELD = {
    "points": ("e_points", "points", "xp", "total_points", "q_p50", "q_p10", "q_p90", "expected", "event_points", "season_points", "gw_points", "pts", "objective"),
    "price": ("price", "now_cost", "sell", "buy", "bank", "budget", "cost"),
    "probability": ("p_start", "p_60", "p_play", "chance", "prob", "likelihood"),
    "minutes": ("minutes", "mins", "exp_minutes"),
    "goals": ("goals", "xg", "goals_scored", "gf", "ga", "gd", "goals_for", "goals_against", "goal_difference", "score"),
    "assists": ("assists", "xa"),
    "clean sheets": ("clean_sheet", "clean_sheets", "cs"),
    "saves": ("saves",),
    "score out of 10": ("attack_score", "defence_score", "ease", "difficulty", "attack_ease", "defence_ease"),
    "possession": ("possession",),
    "matches": ("played", "won", "drawn", "lost", "matches", "games"),
    "rank": ("rank", "position"),
}
GW_CTX = re.compile(r"\b(?:GW|gameweek|gw)\s?(\d{1,2})\b", re.I)
GW_QUOTE = re.compile(r"'gw'\s*:\s*(\d{1,2})|\b(?:GW|gameweek)\s?(\d{1,2})\b|'gameweek'\s*:\s*(\d{1,2})|'event'\s*:\s*(\d{1,2})", re.I)
RELATIVE_GW = re.compile(r"\b(this week|this gameweek|next week|next gameweek|the weekend|this weekend)\b", re.I)
PRONOUN = re.compile(r"\b(he|his|him)\b", re.I)


def fold(s):
    """Lower-case with accents stripped, ONE character per input character (positions stay aligned)."""
    out = []
    for c in s or "":
        d = unicodedata.normalize("NFKD", c)
        out.append((d[0] if d else c).lower())
    return "".join(out)


SCORELINE = re.compile(r"(?<!\d)(\d{1,2})\s?[-–]\s?(\d{1,2})(?!\d)")
MATCH_WORD = re.compile(r"\b(won|win|winning|lost|loss|losing|beat|beaten|drew|draw|result|defeat|defeated)\b", re.I)


def load_items(run_path, numbers_sheet=None):
    """(key -> item) from the numbers sheet's non-WRONG rows (if given) and the judge run's M3b items (DIRECT / DERIVED)."""
    out, src = {}, Counter()
    rows = []
    if numbers_sheet:
        ws = openpyxl.load_workbook(numbers_sheet, read_only=True)["numbers"]
        rows = list(ws.iter_rows(values_only=True))
    H = {h: i for i, h in enumerate(rows[0])} if rows else {}
    for r in rows[1:]:
        final = r[H["final"]]
        if final in ("WRONG", "UNSUPPORTED"):
            continue
        key = (r[H["sheet:#"]], r[H["claim"]], str(float(r[H["number"]])), (r[H["context"]] or "")[:40])
        out[key] = {"id": r[H["sheet:#"]], "claim": r[H["claim"]], "number": r[H["number"]], "context": r[H["context"]],
                    "about": r[H["about"]], "type": final, "quote": r[H["quote"]] or "", "inputs": None, "source": "numbers sheet (random 20)"}
        src["numbers sheet (random 20)"] += 1
    for line in Path(run_path).read_text(encoding="utf-8").splitlines():
        d = json.loads(line)
        if d.get("metric") != "M3b" or not d.get("items"):
            continue
        for it in d["items"]:
            if it.get("final") not in PASS_TYPES:
                continue
            key = (d["id"], it["text"], str(float(it["number"])), (it["context"] or "")[:40])
            if key in out:
                out[key]["source"] += " + run-1 items"
                out[key]["inputs"] = it.get("inputs")
                src["overlap"] += 1
                continue
            out[key] = {"id": d["id"], "claim": it["text"], "number": it["number"], "context": it["context"], "about": it.get("about"),
                        "type": it["final"], "quote": it.get("quote") or "", "inputs": it.get("inputs"), "source": "run-1 DIRECT/DERIVED items"}
            src["run-1 DIRECT/DERIVED items"] += 1
    return out, src


def quote_text(item):
    """The quote plus every DERIVED input quote (nested), joined."""
    parts = [item.get("quote") or ""]

    def walk(inputs):
        for x in inputs or []:
            if isinstance(x, dict):
                if x.get("quote"):
                    parts.append(x["quote"])
                walk(x.get("inputs"))
    walk(item.get("inputs"))
    return " ... ".join(p for p in parts if p)


def player_index(players):
    """[(folded surname, folded full name, element, name)] for the players table."""
    idx = []
    for p in players:
        full = fold(p["name"])
        toks = [t for t in re.split(r"[\s\-]+", full) if len(t) > 1]
        idx.append((toks[-1] if toks else full, full, p["element"], p["name"]))
    return idx


def locate_claim(reply, item):
    """(claim_start, claim_end) in the folded reply, from the context (which holds the claim text once, near its centre
    when the claim is not at an edge). None if the context cannot be found."""
    rf = fold(reply).replace(chr(10), " ")                      # the context was built with newlines as spaces
    cf = fold(item["context"] or "")
    claim = fold(str(item["claim"]))
    occ = [m.start() for m in re.finditer(re.escape(claim), cf)] if claim else []
    off = min(occ, key=lambda o: abs(o - len(cf) // 2)) if occ else None
    if off is None:
        return None
    pos = rf.find(cf.strip())
    if pos < 0:
        mid = cf[max(0, len(cf) // 2 - 20): len(cf) // 2 + 20]
        j = rf.find(mid) if len(mid) >= 12 else -1
        if j < 0:
            return None
        pos = j - max(0, len(cf) // 2 - 20)
    else:
        pos -= len(cf) - len(cf.lstrip())
    start = pos + off
    return start, start + len(claim)


def table_cell(reply, start):
    """If the claim sits in a markdown table row: (header cell, row cells, header cells) for its column, else None."""
    lines = reply.split("\n")
    offset, row_i = 0, None
    for i, ln in enumerate(lines):
        if offset <= start < offset + len(ln) + 1:
            row_i = i
            break
        offset += len(ln) + 1
    if row_i is None or not lines[row_i].lstrip().startswith("|"):
        return None
    line = lines[row_i]
    col = line[:start - offset].count("|") - 1
    cells = [c.strip() for c in line.strip().strip("|").split("|")]
    for h in range(row_i - 1, -1, -1):
        if re.match(r"^\s*\|?\s*:?-{2,}", lines[h]) and h >= 1 and lines[h - 1].lstrip().startswith("|"):
            hcells = [c.strip() for c in lines[h - 1].strip().strip("|").split("|")]
            header = hcells[col] if 0 <= col < len(hcells) else ""
            return header, cells, hcells
        if not lines[h].lstrip().startswith("|"):
            break
    return None


def nearest_player(reply, item, idx):
    """The player named nearest the claim: a name in the same table row; else the nearest name BEFORE the claim in the
    same sentence, then the same paragraph (a pronoun subject before the claim is NOT CHECKABLE), else the nearest
    after it in the same line, else within 200 characters."""
    rf = fold(reply)
    loc = locate_claim(reply, item)
    if loc is None:
        return None, "context not located in the reply"
    start, end = loc
    found = []
    for surname, full, element, name in idx:
        for cand in {full, surname}:
            if len(cand) < 3:
                continue
            for m in re.finditer(r"(?<![a-z])" + re.escape(cand) + r"(?![a-z])", rf):
                found.append((m.start(), m.end(), element, name, cand == full))
    if not found:
        return None, "no player name in the reply"
    tc = table_cell(reply, start)
    line_start = rf.rfind("\n", 0, start) + 1
    line_end = rf.find("\n", start)
    line_end = len(rf) if line_end < 0 else line_end
    if tc is not None:
        row = [f for f in found if line_start <= f[0] < line_end]
        full_row = [f for f in row if f[4]]
        pick = full_row or row
        if len({f[2] for f in pick}) == 1:
            return (pick[0][2], pick[0][3]), "same table row"
        if pick:
            return None, "the table row's name fits several players"
        return None, "table row names no player"
    sent_start = max(rf.rfind(". ", 0, start), rf.rfind("\n", 0, start), rf.rfind("! ", 0, start), rf.rfind("? ", 0, start)) + 1
    para_start = rf.rfind("\n\n", 0, start) + 1
    sent = rf[sent_start:start]
    before_sent = [f for f in found if sent_start <= f[0] and f[1] <= start + 1]
    if before_sent:
        best = max(before_sent, key=lambda f: f[1])
        if PRONOUN.search(rf[best[1]:start]):
            return None, "a pronoun stands between the last name and the claim"
        return (best[2], best[3]), "same sentence, before the claim"
    if PRONOUN.search(sent):
        return None, "the sentence's subject is a pronoun before the claim"
    before_para = [f for f in found if para_start <= f[0] and f[1] <= start + 1]
    if before_para:
        best = max(before_para, key=lambda f: f[1])
        return (best[2], best[3]), "same paragraph, before the claim"
    after_line = [f for f in found if start <= f[0] < line_end]
    if after_line:
        best = min(after_line, key=lambda f: f[0])
        return (best[2], best[3]), "same line, after the claim"
    near = [f for f in found if abs(f[0] - start) <= 200]
    if near:
        best = min(near, key=lambda f: abs(f[0] - start))
        return (best[2], best[3]), "within 200 chars"
    return None, "no player name near the claim"


def players_in_quote(quote, idx):
    qf = fold(quote)
    out = set()
    surn = Counter(s for s, _, _, _ in idx)
    for surname, full, element, name in idx:
        if re.search(r"(?<![a-z])" + re.escape(full) + r"(?![a-z])", qf):
            out.add((element, name))
        elif re.search(r"'player_id'\s*:\s*" + str(element) + r"\b|'element'\s*:\s*" + str(element) + r"\b", quote):
            out.add((element, name))
        elif surn[surname] == 1 and len(surname) >= 4 and re.search(r"(?<![a-z])" + re.escape(surname) + r"(?![a-z])", qf):
            out.add((element, name))
    return out


def check_player(item, record, idx):
    reply = RJ.strip_sources(record.get("rendered_reply") or "")
    near, how = nearest_player(reply, item, idx)
    if near is None:
        return "NOT CHECKABLE", f"reply: {how}"
    inq = players_in_quote(quote_text(item), idx)
    if not inq:
        return "NOT CHECKABLE", f"nearest {near[1]} ({how}); the quote names no player"
    if near in inq:
        return "MATCH", f"nearest {near[1]} ({how}) is in the quote"
    return "CONFLICT", f"nearest {near[1]} ({how}); the quote names {sorted(n for _, n in inq)}"


def context_gw(record):
    """The deadline gameweek from the context block."""
    cb = (RJ.question_turn(record).get("context_block") or "")
    for pat in (r"next deadline[^\n]*?GW\s?(\d{1,2})", r"deadline gameweek[^\n]*?GW\s?(\d{1,2})", r"GW\s?(\d{1,2})\s*deadline", r"predicting GW\s?(\d{1,2})"):
        m = re.search(pat, cb, re.I)
        if m:
            return int(m.group(1))
    return None


def check_gw(item, record):
    reply = RJ.strip_sources(record.get("rendered_reply") or "")
    ctx = item["context"] or ""
    gws, src = set(), "context"
    loc = locate_claim(reply, item)
    tc = table_cell(reply, loc[0]) if loc else None
    if tc is not None:
        header, cells, hcells = tc
        for i, h in enumerate(hcells):
            if re.fullmatch(r"\s*(gw|gameweek|week|event)\s*", h, re.I) and i < len(cells):
                m = re.search(r"\d{1,2}", cells[i])
                if m:
                    gws, src = {int(m.group(0))}, "table row"
        hm = GW_CTX.search(header or "")
        if hm and not gws:
            gws, src = {int(hm.group(1))}, "column header"
    if not gws:
        c = str(item["claim"]).lower()
        i = ctx.lower().find(c)
        i = len(ctx) // 2 if i < 0 else i
        gws = {int(g) for g in GW_CTX.findall(ctx[max(0, i - 45): i + len(c) + 20])}
    if not gws and RELATIVE_GW.search(ctx):
        g = context_gw(record)
        if g is None:
            return "NOT CHECKABLE", "relative gameweek in the context; the context block names no deadline gameweek"
        gws, src = {g}, "relative word via the context block"
    if not gws:
        return "NOT CHECKABLE", "no gameweek in the claim's context"
    q = quote_text(item)
    qg = {int(x) for tup in GW_QUOTE.findall(q) for x in tup if x}
    if not qg:
        return "NOT CHECKABLE", f"{src} GW {sorted(gws)}; the quote names no gameweek"
    if gws & qg:
        return "MATCH", f"{src} GW {sorted(gws)}, quote GW {sorted(qg)}"
    return "CONFLICT", f"{src} GW {sorted(gws)}, quote GW {sorted(qg)}"


def family_of(text, table):
    return [fam for fam, pat in table.items() if pat.search(text or "")]


def quote_families(quote):
    ql = (quote or "").lower()
    fams = []
    for fam, fields in QUOTE_FIELD.items():
        for f in fields:
            if re.search(r"'" + re.escape(f) + r"\w*'\s*:|\b" + re.escape(f) + r"\b", ql):
                fams.append(fam)
                break
    return fams


def check_stat(item, record):
    reply = RJ.strip_sources(record.get("rendered_reply") or "")
    ctx = item["context"] or ""
    loc = locate_claim(reply, item)
    tc = table_cell(reply, loc[0]) if loc else None
    if tc is not None:
        cf = family_of(tc[0], FAMILIES)
        where = f"column '{tc[0]}'"
    else:
        if loc is not None:
            start, end = loc
            ls = reply.rfind(chr(10), 0, start) + 1
            le = reply.find(chr(10), end)
            le = len(reply) if le < 0 else le
            tight = reply[max(ls, start - 28): min(le, end + 22)]
            around = reply[max(ls, start - 3): min(le, end + 3)]
        else:
            c = str(item["claim"]).lower()
            i = ctx.lower().find(c)
            i = len(ctx) // 2 if i < 0 else i
            tight = ctx[max(0, i - 28): i + len(c) + 22]
            around = tight
        cf = family_of(tight, FAMILIES)
        if SCORELINE.search(around) and MATCH_WORD.search(tight) and not re.search(r"\d\.\d", around):
            cf = ["goals"]                                             # a scoreline beside a result word: "(1-0)", "winning 2-1"
        where = f"window '{tight.strip()}'"
    if not cf:
        return "NOT CHECKABLE", f"no stat family in {where}"
    if len(cf) > 1:
        return "NOT CHECKABLE", f"several families in {where}: {cf}"
    qf = quote_families(quote_text(item))
    if not qf:
        return "NOT CHECKABLE", f"{where} -> {cf}; the quote names no stat field"
    if set(cf) & set(qf):
        return "MATCH", f"{where} -> {cf}, quote {qf}"
    return "CONFLICT", f"{where} -> {cf}, quote {qf}"


def run(results, run_path, numbers_sheet, out, players=None):
    """Check every item and write the workbook; returns the summary dict (items, sources, counts, conflicts, out)."""
    items, src = load_items(run_path, numbers_sheet)
    recs = {}
    for path in results:
        for l in Path(path).read_text(encoding="utf-8").splitlines():
            d = json.loads(l)
            recs[d["id"]] = d
    idx = player_index(players if players is not None else CC.load_players())
    counts = {c: Counter() for c in ("player", "gameweek", "stat")}
    conflicts, rows = [], []
    for key, it in items.items():
        rec = recs[it["id"]]
        res = {"player": check_player(it, rec, idx), "gameweek": check_gw(it, rec), "stat": check_stat(it, rec)}
        for c, (verdict, why) in res.items():
            counts[c][verdict] += 1
            if verdict == "CONFLICT":
                conflicts.append({"id": it["id"], "claim": it["claim"], "number": it["number"], "context": it["context"],
                                  "quote": quote_text(it)[:400], "which check": c, "why": why, "judge about": it.get("about"), "type": it["type"], "source": it["source"]})
        rows.append({"id": it["id"], "claim": it["claim"], "number": it["number"], "type": it["type"], "source": it["source"],
                     **{c: v for c, (v, _) in res.items()}, **{f"{c} why": w for c, (_, w) in res.items()}})
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "review"
    hdr = ["id", "claim", "number", "context", "quote", "which check", "why", "judge about", "type", "source"]
    ws.append(hdr)
    for c in ws[1]:
        c.font = Font(bold=True)
    for r in conflicts:
        ws.append([r[h] for h in hdr])
    if not conflicts:
        ws.append(["(no CONFLICT rows: every checkable item matched on player, gameweek and stat family)"] + [None] * (len(hdr) - 1))
    red = PatternFill("solid", fgColor="FFC7CE")
    for row in ws.iter_rows(min_row=2, max_row=1 + len(conflicts)):
        for c in row:
            c.fill = red
    ws2 = wb.create_sheet("counts")
    ws2.append(["check", "MATCH", "CONFLICT", "NOT CHECKABLE"])
    for c in ("player", "gameweek", "stat"):
        ws2.append([c, counts[c]["MATCH"], counts[c]["CONFLICT"], counts[c]["NOT CHECKABLE"]])
    ws2.append([])
    ws2.append(["items checked", len(items)])
    for k, v in src.items():
        ws2.append([k, v])
    ws3 = wb.create_sheet("all items")
    h3 = ["id", "claim", "number", "type", "source", "player", "player why", "gameweek", "gameweek why", "stat", "stat why"]
    ws3.append(h3)
    for r in rows:
        ws3.append([r.get(h) for h in h3])
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    wb.save(out)
    return {"items": len(items), "sources": dict(src), "counts": {c: dict(v) for c, v in counts.items()}, "conflicts": conflicts, "out": str(out)}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--results", action="append", required=True, help="answers jsonl (repeatable; a later file wins)")
    ap.add_argument("--run", required=True, help="the judge run jsonl holding the M3b items")
    ap.add_argument("--numbers-sheet", dest="numbers_sheet", help="a numbers-check workbook whose non-WRONG rows join the items")
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    summary = run(a.results, a.run, a.numbers_sheet, a.out)
    print(json.dumps({k: v for k, v in summary.items() if k != "conflicts"}, indent=1))
    for c in summary["conflicts"]:
        print("CONFLICT", c["id"], c["claim"], c["which check"], "|", c["why"], "| ctx:", (c["context"] or "")[:90].replace(chr(10), " "))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
