"""The automatic fact check of the agent's final answer (Prompt H, M1, 2026-10-30).

After the agent's final answer and before it is returned, code compares the answer with THIS turn's tool outputs only
(never earlier turns, never the model's knowledge):
  (a) tables: the player in a row must match a tool row (its name, web_name or a known alias: every word of the written
      name appears in the row's name); then the row's position (GK = GKP, DEF, MID, FWD), team and price against that
      tool row. A player-column name that matches no tool row is an "unknown name" -- only in a table where at least
      UNKNOWN_MIN_MATCHED other rows matched, so a table of something else is never read as players.
  (b) prose: "Name (POS)" and "Name (Team, POS, £x.xm)", "Name, a <position>" / "Name, the <team> <position>",
      "<position plural> (Name, Name, ...)", "<Team>'s Name", and a price in the same clause as ONE player's name. A
      clause with two or more prices whose labels are unclear is skipped, never flagged; clear labels (bought / sells /
      now) are each checked against their own field; a price that reads as a difference (more, less, saving, loss, the
      bank, ...) is never a price claim.
  (c) stat labels: "X% chance of playing" must equal FPL's chance or p_play_any; "X% to start" / "chance of starting"
      must equal p_start (rounding allowed: within 1 point).
A name two players of this turn's rows share is ambiguous and never checked. Nothing that cannot be resolved -- an
unknown club word, a name with no row, a value with no reference -- is ever flagged (except (a)'s unknown name).

On a mismatch the agent gets ONE send-back (USER DECISION H1): note() builds the automatic-check message; agent.py
sends it with the tools kept and tool use off, checks the rewrite again, and never sends a second one. Every check is
logged to fact_checks (ensure_schema, idempotent). check() is pure; tool outputs saved by the eval runner as Python
reprs are read with saved_output().
"""
import ast
import hashlib
import json
import re
import unicodedata

UNKNOWN_MIN_MATCHED = 2              # an unknown table name counts only beside this many matched player rows
STAT_TOLERANCE = 1.0                 # "rounding allowed": a stated percentage within this many points of a reference
PRICE_TOLERANCE = 0.05               # prices are stated to 0.1m
CLAUSE_WINDOW = 90                   # characters after a name searched for its price in the same clause
POSITIONS = {"gk": "GK", "gkp": "GK", "goalkeeper": "GK", "goalkeepers": "GK", "keeper": "GK", "keepers": "GK",
             "def": "DEF", "defender": "DEF", "defenders": "DEF", "centre-back": "DEF", "center-back": "DEF",
             "centre-backs": "DEF", "full-back": "DEF", "full-backs": "DEF",
             "mid": "MID", "midfielder": "MID", "midfielders": "MID",
             "fwd": "FWD", "forward": "FWD", "forwards": "FWD", "striker": "FWD", "strikers": "FWD"}
SHORT_CODES = {"ARS": "Arsenal", "AVL": "Aston Villa", "BOU": "Bournemouth", "BRE": "Brentford", "BHA": "Brighton",
               "CHE": "Chelsea", "COV": "Coventry City", "CRY": "Crystal Palace", "EVE": "Everton", "FUL": "Fulham",
               "HUL": "Hull City", "IPS": "Ipswich Town", "LEE": "Leeds", "LIV": "Liverpool", "MCI": "Man City",
               "MUN": "Man Utd", "NEW": "Newcastle", "NFO": "Nott'm Forest", "TOT": "Spurs", "SUN": "Sunderland"}
NOT_PLAYERS = {"total", "totals", "bench", "starting", "xi", "starting xi", "subtotal", "sum", "average", "squad", "team",
               "all others", "others", "rest", "everyone else", "the rest",
               "captain", "vice", "vice captain", "none", "n a", "na", "tbd", "gk", "def", "mid", "fwd", "goalkeepers",
               "defenders", "midfielders", "forwards", "in", "out", "free transfer", "hit", "bank", "itb"}
ROLE_WORDS = {"c", "vc", "captain", "vice", "cpt", "v", "in", "out"}
PRICE_MIN, PRICE_MAX = 3.5, 16.0     # F3: a stated price outside this range is a total, a fee, the bank or a difference
_MULTI_NAME = re.compile(r"\s[+&/]\s|→|->|=>|\band\b", re.I)
_SIGNED_CELL = re.compile(r"[+−–]|^\W*-|\b(left|short|over|under|gain|loss|profit|change|diff|saved|spare)\b", re.I)
_RANGE_AFTER = re.compile(r"^\s?[–—-]\s?£?\d")
_ARROW = re.compile(r"→|->|=>")
FIELD_WORDS = {"position": "position", "team": "team", "price": "price", "current_price": "current price",
               "sell_price": "sell price", "purchase_price": "purchase price", "chance": "chance of playing",
               "p_play_any": "chance of playing", "p_start": "chance of starting", "name": "name"}
_FOLD = {"ø": "o", "æ": "ae", "ß": "ss", "ð": "d", "þ": "th", "ł": "l", "đ": "d", "œ": "oe", "ı": "i",
         # look-alikes the model has typed into Latin names (Greek / Cyrillic): "Antόnio" with a Greek omicron
         "ο": "o", "о": "o", "а": "a", "е": "e", "і": "i", "р": "p", "с": "c", "х": "x", "у": "y", "ν": "v", "α": "a", "ε": "e"}
_TOKEN = re.compile(r"[a-z0-9]+")
_PRICE = re.compile(r"£\s?(\d{1,2}(?:\.\d{1,2})?)\s?m\b|\b(\d{1,2}\.\d)\s?m\b", re.I)
_DELTA = re.compile(r"(more|less|extra|save|saves|saving|savings|cheaper|dearer|difference|diff|gain|gained|loss|lost|profit|up|down|with|"
                    r"rise|rose|risen|fall|fell|fallen|drop|dropped|increase|decrease|bank|budget|itb|left|spare|remaining|"
                    r"over|under|gap|total|plus|minus|value|worth|another|freeing|frees|free up|room|headroom)\W*$", re.I)
_DELTA_AFTER = re.compile(r"^\W{0,3}(more|less|loss|profit|gain|in the bank|itb|left|spare|remaining|cheaper|extra|saved|saving)\b", re.I)
_LABEL_PURCHASE = re.compile(r"(bought|buy|buying|purchased?|paid|cost you|bought at|bought for|purchase price)\W{0,12}$", re.I)
_LABEL_SELL = re.compile(r"(sell|sells|selling|sale|sold|sell price|selling price|sell-on|sells for|sell for)\W{0,12}$", re.I)
_LABEL_NOW = re.compile(r"(now|current|currently|costs|priced|valued)\W{0,12}$", re.I)
_NOT_PLAY_TAIL = r"(?!\s+(?:\d|the\s+full|a\s+full|full|most|at\s+least|an\s+hour|the\s+whole|over|more\s+than|minutes|90|60))"
_PLAY_AFTER = re.compile(r"(\d{1,3}(?:\.\d)?)\s?%\s*(?:\*{0,2}\s*)(?:chance\s+(?:of\s+)?(?:playing|to\s+play)|to\s+play\b|likely\s+to\s+play)"
                         + _NOT_PLAY_TAIL, re.I)
_PLAY_BEFORE = re.compile(r"(?<![%\d])(?<!%\s)(?:chance\s+of\s+playing|chance\s+to\s+play|playing\s+chance)\s*(?:of|is|at|:|=|\()?\s*\**\s*"
                          r"(\d{1,3}(?:\.\d)?)\s?%", re.I)
_START_AFTER = re.compile(r"(\d{1,3}(?:\.\d)?)\s?%\s*(?:\*{0,2}\s*)(?:chance\s+(?:of\s+)?starting|chance\s+to\s+start|to\s+start\b|start\s+chance|start\s+probability|"
                          r"starting\s+chance|likely\s+to\s+start)", re.I)
_START_BEFORE = re.compile(r"(?<![%\d])(?<!%\s)(?:chance\s+of\s+starting|chance\s+to\s+start|start\s+probability|starting\s+chance)\s*"
                           r"(?:of|is|at|:|=|\()?\s*\**\s*(\d{1,3}(?:\.\d)?)\s?%", re.I)
_POS_LIST = re.compile(r"(?:(?P<team>[A-Z][\w'&. ]{1,30}?)\s+)?\b(?P<pos>goalkeepers|keepers|defenders|centre-backs|full-backs|midfielders|"
                       r"forwards|strikers)\b\**\s*\((?P<names>[^()\n]{2,160})\)", re.I)
_APPOSITIVE = re.compile(r"^\**\s*,\s*(?:a|an|the)\s+(?:(?P<team>[\w'&. ]{2,30}?)\s+)?(?P<pos>goalkeeper|keeper|defender|centre-back|"
                         r"center-back|full-back|midfielder|forward|striker)\b", re.I)
_PAREN = re.compile(r"^\**\s*\(([^()\n]{1,70})\)")


# ---- folding: case, accents, look-alikes, with a map back to the original text ----------------------------------------

def fold_with_map(text):
    """(folded text, index map): folded[i] came from text[index[i]]; casefolded, accents stripped, _FOLD applied."""
    out, idx = [], []
    for i, ch in enumerate(text or ""):
        for c in unicodedata.normalize("NFKD", ch):
            if unicodedata.combining(c):
                continue
            for f in _FOLD.get(c.casefold(), c.casefold()):
                out.append(f)
                idx.append(i)
    return "".join(out), idx


def fold(text):
    return fold_with_map(text)[0]


def tokens(text):
    return _TOKEN.findall(fold(text).replace("'", "").replace("’", ""))


# ---- tool rows ----------------------------------------------------------------------------------------------------------

def _num(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if f != f else f


def _price(v):
    if isinstance(v, bool):
        return None
    f = _num(v)
    if f is None or f <= 0:
        return None
    return round(f / 10.0, 1) if f >= 30 else round(f, 1)           # get_my_squad's element rows carry tenths (45 = 4.5)


def _pos(v):
    return POSITIONS.get(str(v or "").strip().lower())


def _add_ref(row, key, value):
    if value is not None:
        row.setdefault(key, set()).add(value)


def tool_rows(calls):
    """Player rows from this turn's tool outputs: calls = [(tool name, input, result)]. Every dict carrying a name (name
    or web_name) and a position, team or price field is a row; its nested prediction rows add p_start / p_play_any.
    Rows are merged per player (player_id / element, else the full name). Returns {key: row}, row = {tool, names (list),
    tokens (set), web_tokens, name_tokens, position, team, prices {field: {values}}, refs {chance, p_play_any, p_start}}."""
    players = {}

    def merge(tool, d, inherited=None):
        name = d.get("name") or d.get("web_name") or (inherited or {}).get("name")
        if not name:
            return None
        pid = d.get("player_id", d.get("element", (inherited or {}).get("player_id")))
        key = f"id:{pid}" if pid is not None else f"name:{fold(name)}"
        row = players.setdefault(key, {"tool": tool, "names": [], "tokens": set(), "position": None, "team": None,
                                       "prices": {}, "refs": {}, "fields_from": {}})
        for n in (d.get("name"), d.get("web_name"), d.get("display_name")):
            if n and n not in row["names"]:
                row["names"].append(str(n))
                row["tokens"] |= set(tokens(str(n)))
        pos = _pos(d.get("position"))
        if pos and not row["position"]:
            row["position"] = pos
            row["fields_from"]["position"] = tool
        team = d.get("team")
        if isinstance(team, str) and team and not row["team"]:
            row["team"] = team
            row["fields_from"]["team"] = tool
        for k, f in (("price", "price"), ("current_price", "current_price"), ("sell_price", "sell_price"),
                     ("purchase_price", "purchase_price"), ("now", "current_price"), ("bought", "purchase_price"),
                     ("sells_for", "sell_price")):
            p = _price(d.get(k))
            if p is not None:
                row["prices"].setdefault(f, set()).add(p)
                row["fields_from"].setdefault(f, tool)
        ch = _num(d.get("chance", d.get("chance_of_playing_next_round")))
        if ch is not None:
            _add_ref(row["refs"], "chance", ch)
            row["fields_from"].setdefault("chance", tool)
        for k, ref in (("p_play_any", "p_play_any"), ("p_start", "p_start"), ("first_gw_p_start", "p_start")):
            v = _num(d.get(k))
            if v is not None:
                _add_ref(row["refs"], ref, v * 100 if v <= 1 else v)
                row["fields_from"].setdefault(ref, tool)
        return row

    def walk(tool, o, inherited=None):
        if isinstance(o, dict) and any(k in o for k in ("out_id", "in_id", "team_out", "team_in", "position_out", "position_in")):
            for side, pk, field in (("out", "sold_for", "sell_price"), ("in", "bought_for", "price")):   # F1: a transfer's two players
                nm = o.get(side)
                if isinstance(nm, str) and nm:
                    merge(tool, {"name": nm, "player_id": o.get(f"{side}_id"), "team": o.get(f"team_{side}"),
                                 "position": o.get(f"position_{side}"), field: o.get(pk)})
        if isinstance(o, dict):
            has_name = bool(o.get("name") or o.get("web_name"))
            row = None
            # a player row: a name AND a player identity (player_id / element / web_name) or an FPL position -- a league
            # table row ({"name": "Arsenal", "position": 1}) is not one
            if has_name and (any(k in o for k in ("player_id", "element", "web_name")) or _pos(o.get("position"))):
                row = merge(tool, o)
                inherited = {"name": o.get("name") or o.get("web_name"), "player_id": o.get("player_id", o.get("element"))}
            elif inherited and any(k in o for k in ("p_start", "p_play_any")):
                merge(tool, o, inherited)                         # a prediction row under its player
            for v in o.values():
                walk(tool, v, inherited if row is not None or inherited else None)
        elif isinstance(o, (list, tuple)):
            for v in o:
                walk(tool, v, inherited)

    for tool, _inp, result in calls or []:
        walk(tool, result)
    return players


def saved_output(text):
    """A tool output saved as str(result) (the eval runner) -> the Python value. datetime / Timestamp calls become
    their repr string, numpy scalars their number, anything else unknown None. None when it does not parse."""
    if not isinstance(text, str):
        return text
    try:
        tree = ast.parse(text, mode="eval")
    except (SyntaxError, ValueError):
        return None

    def conv(n):
        if isinstance(n, ast.Constant):
            return n.value
        if isinstance(n, ast.Dict):
            return {conv(k): conv(v) for k, v in zip(n.keys, n.values)}
        if isinstance(n, (ast.List, ast.Tuple, ast.Set)):
            return [conv(e) for e in n.elts]
        if isinstance(n, ast.UnaryOp) and isinstance(n.op, ast.USub):
            v = conv(n.operand)
            return -v if isinstance(v, (int, float)) else None
        if isinstance(n, ast.Name):
            return {"True": True, "False": False, "None": None, "nan": None, "inf": None}.get(n.id)
        if isinstance(n, ast.Call):
            fn = ast.unparse(n.func)
            if fn.split(".")[-1] in ("float64", "float32", "int64", "int32", "float", "int", "Decimal") and n.args:
                v = conv(n.args[0])
                try:
                    return float(v)
                except (TypeError, ValueError):
                    return None
            return ast.unparse(n)
        return None
    try:
        return conv(tree.body)
    except Exception:                                    # noqa: BLE001
        return None


# ---- matching names and clubs -----------------------------------------------------------------------------------------

def _clean_name(cell):
    """A table cell or a prose name -> its name words: markdown, emoji, bracketed roles and role words dropped."""
    s = re.sub(r"\([^)]*\)|\[[^\]]*\]", " ", cell or "")
    s = re.sub(r"[*_`~]", " ", s)
    toks = [t for t in tokens(s)]
    while toks and toks[-1] in ROLE_WORDS:
        toks.pop()
    while toks and toks[0] in ROLE_WORDS:
        toks.pop(0)
    return toks


def match_rows(name_tokens, rows):
    """The single player whose names contain every written word, else None; ('ambiguous', [...]) when 2+ players do and
    none is an exact name."""
    if not name_tokens:
        return None
    want = set(name_tokens)
    cands = [(k, r) for k, r in rows.items() if want <= r["tokens"]]
    if not cands:
        return None
    if len(cands) == 1:
        return cands[0]
    exact = [(k, r) for k, r in cands if any(tokens(n) == list(name_tokens) for n in r["names"])]
    if len(exact) == 1:
        return exact[0]
    return ("ambiguous", cands)


def club_of(text, extra=None):
    """The canonical FPL club name a written club resolves to (names, config aliases, three-letter codes), else None."""
    import config_roles
    s = re.sub(r"[*_`]", "", text or "").strip()
    if not s:
        return None
    if s.upper() in SHORT_CODES and (s.isupper() or len(s) == 3):
        return SHORT_CODES[s.upper()]
    f = " ".join(tokens(s))
    for club, aliases in (config_roles.TEAM_ALIASES or {}).items():
        for form in [club, *aliases]:
            if " ".join(tokens(form)) == f:
                return club
    for club in extra or ():
        if " ".join(tokens(club)) == f:
            return club
    return None


# ---- the checks ------------------------------------------------------------------------------------------------------------

def _mismatch(phrase, row, field, value, kind):
    tool = row["fields_from"].get(field, row["tool"])
    return {"phrase": phrase, "tool": tool, "field": field, "value": value, "kind": kind}


def _fmt_price(v):
    return f"£{v:.1f}m"


def _check_price(stated, label, row, phrase, out, counted):
    if not (PRICE_MIN <= stated <= PRICE_MAX):
        return                                                    # F3
    fields = {"purchase": ["purchase_price"], "sell": ["sell_price"], "now": ["current_price", "price"]}.get(label)
    if fields:
        fields = [f for f in fields if row["prices"].get(f)]
    if not fields:
        fields = [f for f in ("price", "current_price", "sell_price", "purchase_price") if row["prices"].get(f)]
    if not fields:
        return
    counted.append("price")
    refs = sorted(v for f in fields for v in row["prices"][f])
    if any(abs(stated - v) < PRICE_TOLERANCE for v in refs):
        return
    field = fields[0]
    out.append(_mismatch(phrase, row, field, _fmt_price(sorted(row["prices"][field])[0]), "price"))


def _check_position(stated, row, phrase, out, counted):
    if not row["position"] or not stated:
        return
    counted.append("position")
    if stated != row["position"]:
        out.append(_mismatch(phrase, row, "position", row["position"], "position"))


def _check_team(stated_text, row, phrase, out, counted, clubs):
    if not row["team"]:
        return
    stated = club_of(stated_text, clubs)
    have = club_of(row["team"], clubs) or row["team"]
    if stated is None:
        return
    counted.append("team")
    if stated != have:
        out.append(_mismatch(phrase, row, "team", row["team"], "team"))


def _check_stat(stated, kind, row, phrase, out, counted):
    keys = ("chance", "p_play_any") if kind == "play" else ("p_start",)
    refs = sorted(v for k in keys for v in row["refs"].get(k, ()))
    if not refs:
        return
    counted.append(kind)
    if any(abs(stated - v) < STAT_TOLERANCE for v in refs):
        return
    key = next(k for k in keys if row["refs"].get(k))
    best = sorted(row["refs"][key])[0]
    out.append(_mismatch(phrase, row, key, f"{best:.0f}%", "stat"))


def _split_row(line):
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|"):
        s = s[:-1]
    return [c.strip() for c in s.split("|")]


def _tables(lines):
    """[(header cells, [(line index, cells)])] for every markdown table"""
    out, i = [], 0
    while i < len(lines):
        if lines[i].lstrip().startswith("|") and i + 1 < len(lines) and re.match(r"^\s*\|?\s*:?-{2,}", lines[i + 1]):
            header = _split_row(lines[i])
            body, j = [], i + 2
            while j < len(lines) and lines[j].lstrip().startswith("|"):
                body.append((j, _split_row(lines[j])))
                j += 1
            out.append((header, body))
            i = j
        else:
            i += 1
    return out


def _col_kind(h):
    h = fold(re.sub(r"[*_`]", "", h)).strip()
    if re.search(r"\bplayer\b|\bname\b", h) or h in ("out", "in", "player out", "player in", "transfer out", "transfer in"):
        return "player"
    if h in ("pos", "pos.", "position", "posn"):
        return "position"
    if re.search(r"\bclub\b|\bteam\b", h) and "news" not in h:
        return "team"
    if re.search(r"start", h) and "%" in h or re.search(r"chance of starting|p\(start\)|start prob", h):
        return "start"
    if re.search(r"chance of playing|play %|p\(play\)|chance to play", h):
        return "play"
    if re.search(r"\bsell", h):
        return "price:sell"
    if re.search(r"\bbought\b|\bbuy\b|purchase|\bpaid\b", h):
        return "price:purchase"
    if re.search(r"\bprice\b|\bcost\b|£|\bnow\b", h) and not re.search(r"change|diff|gain|profit|loss|\+|-", h):
        return "price:now" if "now" in h or "current" in h else "price"
    return None


def _phrase(line, start_cell, end_cell):
    a = line.find(start_cell)
    b = line.find(end_cell, a if a >= 0 else 0)
    if a < 0 or b < 0:
        return end_cell or start_cell
    return line[a:b + len(end_cell)]


def check_tables(text, rows, out, counted, clubs):
    lines = (text or "").split("\n")
    for header, body in _tables(lines):
        kinds = [_col_kind(h) for h in header]
        player_cols = [i for i, k in enumerate(kinds) if k == "player"]
        if not player_cols:
            for i in range(len(header)):                         # no player header: the column whose cells match tool rows
                hits = sum(1 for _, cells in body if i < len(cells) and isinstance(match_rows(_clean_name(cells[i]), rows), tuple)
                           and match_rows(_clean_name(cells[i]), rows)[0] != "ambiguous")
                if body and hits >= max(2, len(body) // 2):
                    player_cols = [i]
                    break
        if not player_cols:
            continue
        unknown = []
        matched = 0
        for li, cells in body:
            for pc in player_cols:
                if pc >= len(cells):
                    continue
                cell = cells[pc]
                nt = _clean_name(cell)
                if not nt or " ".join(nt) in NOT_PLAYERS or not re.search(r"[A-Za-zÀ-ÿ]", cell) or _MULTI_NAME.search(cell):
                    continue
                m = match_rows(nt, rows)
                if m is None:
                    unknown.append((li, cell, nt))
                    continue
                if m[0] == "ambiguous":
                    continue
                matched += 1
                _key, row = m
                counted.append("name")
                pm = re.search(r"\(([^()]{1,40})\)", cell)                       # "Kai Havertz (DEF)" inside the cell
                if pm:
                    for part in re.split(r"[,/;]", pm.group(1)):
                        p = _pos(part.strip())
                        if p:
                            _check_position(p, row, _phrase(lines[li], cell, cell), out, counted)
                if len(player_cols) > 1:
                    continue                                                      # Out / In tables: names only
                for ci, kind in enumerate(kinds):
                    if ci >= len(cells) or ci == pc or kind is None:
                        continue
                    val = cells[ci]
                    phrase = _phrase(lines[li], cell, val)
                    if kind == "position":
                        _check_position(_pos(re.sub(r"[*_`]", "", val).strip()), row, phrase, out, counted)
                    elif kind == "team":
                        _check_team(val, row, phrase, out, counted, clubs)
                    elif kind.startswith("price"):
                        if _SIGNED_CELL.search(val):
                            continue                                      # F4: a difference, not a price
                        prices = [float(a or b) for a, b in _PRICE.findall(val)] or \
                                 ([float(x) for x in re.findall(r"^\**\s*(\d{1,2}\.\d)\s*\**$", val.strip())])
                        if len(prices) == 1:
                            _check_price(prices[0], kind.split(":")[1] if ":" in kind else None, row, phrase, out, counted)
                    elif kind in ("play", "start"):
                        pc_m = re.search(r"(\d{1,3}(?:\.\d)?)\s?%", val)
                        if pc_m:
                            _check_stat(float(pc_m.group(1)), kind, row, phrase, out, counted)
        if matched >= UNKNOWN_MIN_MATCHED:
            for li, cell, nt in unknown:
                inner = re.search(r"\(([^()]{2,60})\)", cell)
                hit = match_rows(_clean_name(inner.group(1)), rows) if inner else None
                if hit and hit[0] != "ambiguous":
                    continue                                                     # F13: the parenthesis names the player
                counted.append("name")
                share = [(k, r) for k, r in rows.items() if set(nt) & r["tokens"]]
                if len(share) == 1:
                    r = share[0][1]
                    out.append({"phrase": re.sub(r"^\*+|\*+$", "", cell.strip()), "tool": r["tool"], "field": "name",
                                "value": r["names"][0], "kind": "unknown_name"})
                else:
                    out.append({"phrase": re.sub(r"^\*+|\*+$", "", cell.strip()), "tool": None, "field": "name", "value": None,
                                "kind": "unknown_name"})


def _name_occurrences(folded, rows, original=None, idx=None):
    """[(start, end, row key, row)] for every unambiguous name form of the turn's rows found in the folded text, longest
    form first, non-overlapping."""
    forms = {}
    for k, r in rows.items():
        for n in r["names"]:
            toks = tokens(n)
            cands = {" ".join(toks)}
            if len(toks) >= 2:
                cands.add(toks[-1])
                cands.add(" ".join(toks[:2]))
                cands.add(toks[0])
            for c in cands:
                if len(c) >= 3:
                    forms.setdefault(c, set()).add(k)
    found, taken = [], []
    for form in sorted(forms, key=len, reverse=True):
        keys = forms[form]
        if len(keys) != 1:
            continue
        pat = re.compile(r"(?<![a-z0-9'’])" + r"[\W_]*".join(re.escape(t) for t in form.split()) + r"(?![a-z0-9])")
        for m in pat.finditer(folded):
            if any(not (m.end() <= a or m.start() >= b) for a, b in taken):
                continue
            if original is not None and not original[idx[m.start()]].isupper():
                continue                                          # a name is written with a capital: "White" yes, "white" no
            k = next(iter(keys))
            found.append((m.start(), m.end(), k, rows[k]))
            taken.append((m.start(), m.end()))
    return sorted(found, key=lambda x: x[0])


_CLAUSE_END = re.compile(r"(?<!\d)[.!?](?=\s|$)|\n|;|\s[—–]\s|\s-\s|\b(?:but|while|whereas|than|vs|versus|instead|replac\w*)\b")
_AND_OR = re.compile(r"\b(?:and|or)\b\s*\**\s*")


def _clause_end(folded, start):
    m = _CLAUSE_END.search(folded, start)
    return m.start() if m else len(folded)


def _price_label(before):
    if _LABEL_SELL.search(before):
        return "sell"
    if _LABEL_PURCHASE.search(before):
        return "purchase"
    if _LABEL_NOW.search(before):
        return "now"
    return None


def check_prose(text, rows, out, counted, clubs):
    lines = (text or "").split("\n")
    prose = "\n".join("" if l.lstrip().startswith("|") else l for l in lines)       # tables are check_tables'
    folded, idx = fold_with_map(prose)

    def orig(a, b):
        if a >= len(idx):
            return ""
        return prose[idx[a]:idx[min(b, len(idx)) - 1] + 1]

    occ = _name_occurrences(folded, rows, prose, idx)
    starts = [o[0] for o in occ]
    for n, (a, b, _k, row) in enumerate(occ):
        nxt = starts[n + 1] if n + 1 < len(starts) else len(folded)
        after = folded[b:]
        pm = _PAREN.match(after)
        if pm:                                                                   # Name (Team, POS, £x.xm)
            phrase = orig(a, b + pm.end())
            parts = [p.strip() for p in re.split(r"[,/;|]", pm.group(1))]
            prices = [p for p in parts if _PRICE.search(p)]
            if any(len(_PRICE.findall(p)) > 1 or _ARROW.search(p) for p in prices):
                prices = []                                                      # F9: "£4.5m -> £4.7m" is two players' prices
            for p in parts:
                pos = _pos(p)
                if pos:
                    _check_position(pos, row, phrase, out, counted)
                elif club_of(p, clubs):
                    _check_team(p, row, phrase, out, counted, clubs)
            if len(prices) == 1 and not re.search(r"[+\-−]|bank|itb|more|less|sav|loss|profit", prices[0], re.I):
                m = _PRICE.search(prices[0])
                _check_price(float(m.group(1) or m.group(2)), _price_label(prices[0][:m.start()]), row, phrase, out, counted)
        am = _APPOSITIVE.match(after)
        if am:                                                                   # Name, a defender / Name, the Arsenal forward
            phrase = orig(a, b + am.end())
            _check_position(_pos(am.group("pos")), row, phrase, out, counted)
            if am.group("team"):
                _check_team(am.group("team"), row, phrase, out, counted, clubs)
        pre = folded[max(0, a - 32):a]                                           # Chelsea's Palmer
        pm2 = re.search(r"([a-z][a-z'&. ]{1,28}?)['’]s\s+$", pre)
        if pm2 and club_of(pm2.group(1), clubs):
            _check_team(pm2.group(1), row, orig(a - len(pre) + pm2.start(1), b), out, counted, clubs)
        end = min(_clause_end(folded, b), nxt, b + CLAUSE_WINDOW)                # a price in the same clause
        for am2 in _ARROW.finditer(folded, b, end):                              # F5: "X -> Y" ends X's clause at the arrow
            k2 = am2.end()
            while k2 < len(folded) and folded[k2] in " *_":
                k2 += 1
            if k2 < len(idx) and prose[idx[k2]].isupper():
                end = am2.start()
                break
        for ao in _AND_OR.finditer(folded, b, end):                              # F8: "and" / "or" before a new subject
            if ao.end() < len(idx) and prose[idx[ao.end()]].isupper():
                end = ao.start()
                break
        if pm and _PRICE.search(pm.group(1)):
            end = b                                                              # its parenthesis already gave its price
        line_start = folded.rfind("\n", 0, a) + 1
        prev_end = max([o[1] for o in occ if line_start <= o[0] < a and o[2] != _k] or [line_start])      # F12
        if _ARROW.search(folded[prev_end:a]):
            end = b                                                              # F5: the right side of "X -> Y": no clause prices
        seg = folded[b:end]
        found = []
        for m in _PRICE.finditer(seg):
            before, after_p = seg[max(0, m.start() - 22):m.start()], seg[m.end():m.end() + 16]
            if _DELTA.search(before) or _DELTA_AFTER.search(after_p) or re.search(r"[+\-−]\s?$", before):
                continue
            if _RANGE_AFTER.search(seg[m.end():m.end() + 6]) or re.search(r"\d\s?[–—-]\s?$", before):
                continue                                                         # F4: a range
            if re.search(r"\b(?:a|an|combined|total|totalling|totaling)\s*\**\s*$", before):
                continue                                                         # F11: "a £5.4m player", "a combined £15.9m"
            if pm and m.start() < pm.end():
                continue                                                         # the parentheses were read above
            found.append((float(m.group(1) or m.group(2)), _price_label(before), m))
        if len(found) == 1 or (len(found) > 1 and all(lbl in ("sell", "purchase", "now") for _, lbl, _ in found)
                               and len({lbl for _, lbl, _ in found}) == len(found)):
            for v, lbl, m in found:
                stop = b + m.end()
                while stop < len(folded) and folded[stop] == "*":
                    stop += 1
                _check_price(v, lbl, row, orig(a, stop), out, counted)
    for m in _POS_LIST.finditer(folded):                                         # Arsenal defenders (Gabriel, Calafiori, ...)
        pos = _pos(m.group("pos"))
        names = re.split(r"\s[—–-]\s|\)", m.group("names"))[0]
        team = m.group("team")
        for part in re.split(r",|\band\b|&", names):
            nt = _clean_name(part)
            hit = match_rows(nt, rows)
            if not hit or hit[0] == "ambiguous":
                continue
            row = hit[1]
            phrase = orig(m.start(), m.end())
            _check_position(pos, row, phrase, out, counted)
            if team and club_of(team.strip(), clubs):
                _check_team(team.strip(), row, phrase, out, counted, clubs)
    for regs, kind in (((_PLAY_AFTER, _PLAY_BEFORE), "play"), ((_START_AFTER, _START_BEFORE), "start")):
        for reg in regs:
            for m in reg.finditer(folded):
                line_start = folded.rfind("\n", 0, m.start()) + 1
                prior = [o for o in occ if line_start <= o[0] < m.start()]
                if not prior:
                    continue
                a, b, _k, row = prior[-1]
                if re.search(r"[.!?](?=\s)", folded[b:m.start()]):
                    continue                                                     # F7: the stat and the name share a sentence
                _check_stat(float(m.group(1)), kind, row, orig(a, m.end()), out, counted)


def check(text, calls):
    """{facts_checked, mismatches: [{phrase, tool, field, value, kind}], rows} for the final answer `text` against this
    turn's `calls` [(tool, input, result)]. No calls or no player rows -> nothing checked."""
    rows = tool_rows(calls)
    out, counted = [], []
    if rows and text:
        clubs = sorted({r["team"] for r in rows.values() if r["team"]})
        check_tables(text, rows, out, counted, clubs)
        check_prose(text, rows, out, counted, clubs)
    seen, uniq = set(), []
    for m in out:
        key = (m["phrase"], m["field"], m["value"])
        if key not in seen:
            seen.add(key)
            uniq.append(m)
    return {"facts_checked": len(counted), "mismatches": uniq, "n_rows": len(rows)}


# ---- the send-back note (USER DECISION H1) ---------------------------------------------------------------------------

def _line(i, m):
    if m["kind"] == "unknown_name" and m["value"] is None:
        return f'{i}. You wrote "{m["phrase"]}". No tool output this turn has that player. -> Use only players from this turn\'s tool output.'
    field = FIELD_WORDS.get(m["field"], m["field"])
    return f'{i}. You wrote "{m["phrase"]}". {m["tool"]} says {field}: {m["value"]}. -> Use {m["value"]}.'


def note(mismatches):
    """The automatic-check message: what was wrong, quoted exactly, the tool, the field and the right value; fix only
    these, keep the rest, no new facts. Marked as an automatic check, never the user's words."""
    n = len(mismatches)
    head = (f"Automatic fact check: your answer has {n} fact(s) that don't match this turn's tool output. Fix only these, "
            f"keep everything else exactly as written, and don't add new facts.")
    return "\n".join([head] + [_line(i, m) for i, m in enumerate(mismatches, 1)])


# ---- the log -------------------------------------------------------------------------------------------------------------

DDL = """
CREATE TABLE IF NOT EXISTS fact_checks (
    id                   BIGSERIAL PRIMARY KEY,
    checked_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    turn_id              TEXT NOT NULL,
    facts_checked        INT,
    mismatches           JSONB,             -- [{phrase, tool, field, value, kind}] of the first answer
    sent_back            BOOLEAN NOT NULL DEFAULT FALSE,
    outcome              TEXT NOT NULL,     -- clean | fixed | still_wrong | tool_call_in_rewrite | no_text | sendback_failed | check_error
    rewrite_mismatches   JSONB,             -- the rewrite's own check, when there was one
    extra_usd            NUMERIC,
    extra_seconds        REAL,
    error                TEXT
);
CREATE INDEX IF NOT EXISTS ix_fact_checks_at ON fact_checks (checked_at);
"""
_SCHEMA_READY = []                   # ensure_schema once per process


def ensure_schema(conn):
    with conn.cursor() as cur:
        cur.execute(DDL)
    conn.commit()


def record(turn_id, info, conn=None):
    """One fact_checks row. Raises on a DB failure (the agent catches and prints; the reply never depends on it)."""
    import db_write
    own = conn is None
    if own:
        conn = db_write.connect()
    try:
        if not _SCHEMA_READY:
            ensure_schema(conn)
            _SCHEMA_READY.append(True)
        with conn.cursor() as cur:
            cur.execute("INSERT INTO fact_checks (turn_id, facts_checked, mismatches, sent_back, outcome, rewrite_mismatches, extra_usd, "
                        "extra_seconds, error) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                        (turn_id, info.get("facts_checked"), json.dumps(info.get("mismatches") or []), bool(info.get("sent_back")),
                         info.get("outcome") or "clean", json.dumps(info.get("rewrite_mismatches")) if info.get("rewrite_mismatches") is not None else None,
                         info.get("extra_usd"), info.get("extra_seconds"), info.get("error")))
        conn.commit()
    finally:
        if own:
            conn.close()


def fingerprint(text):
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()[:12]
