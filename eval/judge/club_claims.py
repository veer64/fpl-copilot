"""Club claims in a reply (Part C, 2026-10-12): which club the reply puts next to a player, and whether a tool output
of the turn backs it. The user's review found the agent naming clubs from memory (Mukiele at Man City, Man Utd
and Newcastle in three answers); build_squad_from_scratch rows carried no 'team' field, so nothing could be checked.

Used by the gold labels (rule 4: a club with no tool source is an M3a FAIL) and by the eval's code checks
(wrong clubs vs the players table, unsourced clubs). Pure functions over the record and a player list; the
player list comes from players_live (load_players) or is passed in.

DEFINITION (fix batch #4 close, 2026-10-22, written before the code change): unsourced / wrong clubs fire only on
a CLUB CLAIM about a player: the player tied to a club as his own club -- "Isak (FWD, Newcastle)", "Newcastle's
Isak", "Isak, who plays for Newcastle", "Isak at Newcastle" used as his club. A fixture is NOT a club claim:
"Haaland at Aston Villa (away, Sat 24 Oct)", "Haaland vs Arsenal", "away at X", "home to X", "X (H)/(A)"."""
import re
import unicodedata

from judge import metrics as M
from judge import run_judge as RJ

ALIASES = {"ipswich": "Ipswich Town", "coventry": "Coventry City", "hull": "Hull City", "tottenham": "Spurs",
           "tottenham hotspur": "Spurs", "man united": "Man Utd", "manchester united": "Man Utd", "man utd": "Man Utd",
           "manchester city": "Man City", "man city": "Man City", "nottingham forest": "Nott'm Forest", "forest": "Nott'm Forest",
           "nottm forest": "Nott'm Forest", "newcastle united": "Newcastle", "leeds united": "Leeds", "west ham united": "West Ham",
           "wolverhampton": "Wolves", "wolverhampton wanderers": "Wolves", "brighton & hove albion": "Brighton",
           "brighton and hove albion": "Brighton", "villa": "Aston Villa", "palace": "Crystal Palace", "afc bournemouth": "Bournemouth",
           "sunderland afc": "Sunderland", "everton fc": "Everton", "fulham fc": "Fulham", "chelsea fc": "Chelsea",
           "liverpool fc": "Liverpool", "arsenal fc": "Arsenal", "brentford fc": "Brentford", "burnley fc": "Burnley"}
_STRIP = re.compile(r"\*\*|__|©|\(vc\)|\(c\)|\bVC\b|\bC\b|🔒|⭐|🔵|\((?:GK|DEF|MID|FWD)\)|\bGK\b|\bDEF\b|\bMID\b|\bFWD\b", re.I)


def fold(s):
    return "".join(c for c in unicodedata.normalize("NFKD", s or "") if not unicodedata.combining(c))


def norm(s):
    return re.sub(r"[^a-z0-9 ]+", " ", fold(s).lower()).strip()


def norm_club(text, teams):
    """The FPL team name for a club as written in prose ("Ipswich", "Tottenham", "Man United"), or None."""
    t = norm(text)
    t = re.sub(r"\bfc\b", "", t).strip()
    if not t:
        return None
    if t in ALIASES and ALIASES[t] in teams:
        return ALIASES[t]
    for team in teams:
        if norm(team) == t:
            return team
    for team in teams:                                                # "Nott'm Forest" written "Nott m Forest"
        if norm(team).replace(" ", "") == t.replace(" ", ""):
            return team
    return None


def load_players(conn=None):
    """[{element, name, position, team}] from players_live (the local players table)."""
    close = False
    if conn is None:
        import tools
        conn = tools.get_connection()
        close = True
    try:
        cur = conn.cursor()
        cur.execute("SELECT element, name, position, team FROM players_live ORDER BY element")
        return [{"element": e, "name": n, "position": p, "team": t} for e, n, p, t in cur.fetchall()]
    finally:
        if close:
            conn.close()


def _clean_name(text):
    s = _STRIP.sub(" ", text or "")
    s = re.sub(r"\s+", " ", s).strip(" -–—:·|")
    return s


def _rows_in(obj, out):
    """Every dict with a 'name' inside a parsed tool output, and (batch 3 F2, 2026-10-14) every transfer entry's two
    players as rows: {out, team_out, position_out} and {in, team_in, position_in}. Measured: the 18 'unsourced' clubs
    of 2026-10-13 were all players the transfer plan names in such entries, with the club in team_in -- 18 false alarms."""
    if isinstance(obj, dict):
        if "name" in obj and isinstance(obj.get("name"), str):
            out.append(obj)
        for side in ("out", "in"):
            if isinstance(obj.get(side), str) and (f"team_{side}" in obj or f"{side}_id" in obj):
                out.append({"name": obj[side], "team": obj.get(f"team_{side}"), "position": obj.get(f"position_{side}"),
                            "player_id": obj.get(f"{side}_id")})
        for v in obj.values():
            _rows_in(v, out)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            _rows_in(v, out)


def tool_rows(record):
    """The player rows of every tool output in the question turn and the setup turn."""
    outs = [c.get("output") for c in (record.get("calls") or [])]
    st = RJ.setup_turn(record)
    outs += [c.get("output") for c in ((st or {}).get("calls") or [])]
    rows = []
    for o in outs:
        if o:
            _rows_in(M.parse_output(o), rows)
    return rows


def _match(text, rows):
    """The rows whose name matches the text: the whole name, or every word of the text as whole words of the
    name (surname, or 'Pedro Neto'), accents folded."""
    t = norm(text)
    if not t:
        return []
    exact = [r for r in rows if norm(r["name"]) == t]
    if exact:
        return exact
    words = t.split()
    out = []
    for r in rows:
        nw = norm(r["name"]).split()
        if all(w in nw for w in words):
            out.append(r)
    return out


PREFIX_MIN = 3                                                       # a token prefix must be at least this long ("Ant" ~ "António"), initials never match


def _tool_match(text, rows):
    """The tool rows the reply name matches under the resolver definition (2026-10-22): the full name or the FPL
    display name (web_name) equal to the text, accent-folded, wins outright; else every reply word that matches any
    row must be a whole token or a token prefix (PREFIX_MIN+ chars) of this row's name or display-name tokens, and at
    least one word must match ("Nuno Tavares" ~ 'António ... Tavares da Silva' by "tavares"; "Antón" ~ "António").
    Returns every matching row; the caller treats 2+ distinct players as unresolved."""
    t = norm(text)
    if not t:
        return []
    words = t.split()
    exact = [r for r in rows if norm(r.get("name") or "") == t or (r.get("web_name") and norm(r["web_name"]) == t)]
    if exact:
        return exact
    toks = {id(r): set(norm(r.get("name") or "").split()) | set(norm(r.get("web_name") or "").split()) for r in rows}

    def hits(w, r):
        return any(tok == w or (len(w) >= PREFIX_MIN and tok.startswith(w)) for tok in toks[id(r)])
    live = [w for w in words if any(hits(w, r) for r in rows)]          # the reply words that match some row
    if not live:
        return []
    return [r for r in rows if all(hits(w, r) for w in live)]


def resolve(text, rows, players):
    """The player the reply means: unique among the turn's tool rows first, else unique in the players table.
    Returns (player dict or None, how) with how in exact/tool/table/ambiguous/unknown.

    DEFINITION (club resolver, 2026-10-22, written before the code change): a player named in a reply is matched FIRST
    against the player rows in that turn's tool outputs: full name, FPL display name, first or last name,
    accent-folded; a reply name that is a whole token or a token prefix of exactly one tool row's name (e.g. 'Antón' ~
    'António ... Tavares da Silva') resolves to that row. Only when no tool row matches is the players table used. A
    name that matches more than one player at either step is not resolved (no club claim is scored)."""
    text = _clean_name(text)
    if not text or norm(text) in ("", "bench", "captain", "vice", "total", "order"):
        return None, "unknown"
    seen, cands = set(), []
    for r in _tool_match(text, rows):
        key = norm(r["name"])
        if key not in seen:
            seen.add(key)
            cands.append(r)
    if len(cands) == 1:
        return cands[0], "tool"
    if len(cands) > 1:
        return None, "ambiguous"
    seen, cands = set(), []
    for r in _match(text, players):
        key = norm(r["name"])
        if key not in seen:
            seen.add(key)
            cands.append(r)
    if len(cands) == 1:
        return cands[0], "table"
    return None, "ambiguous" if cands else "unknown"


def _table_claims(reply, teams):
    """(player text, club text) from markdown tables with a Club / Team column."""
    out = []
    lines = reply.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if line.startswith("|") and i + 1 < len(lines) and re.match(r"^\|\s*:?-+", lines[i + 1].strip()):
            head = [norm(c) for c in line.strip("|").split("|")]
            ci = next((k for k, h in enumerate(head) if h in ("club", "team")), None)
            pi = next((k for k, h in enumerate(head) if h in ("player", "name")), None)
            i += 2
            if ci is None or pi is None:
                continue
            while i < len(lines) and lines[i].strip().startswith("|"):
                cells = [c.strip() for c in lines[i].strip().strip("|").split("|")]
                if len(cells) > max(ci, pi):
                    club, player = cells[ci], cells[pi]
                    if club and player and club not in ("—", "-", "–") and not re.match(r"^\*?\*?(bench|starting xi)\b", player, re.I):
                        out.append((player, club, "table"))
                i += 1
            continue
        i += 1
    return out


def _prose_claims(reply, teams):
    """(player text, club text) from "Name (Club", "Name — Club", "Name, Club", "Name of Club", "Name at Club",
    "Club's Name" in prose (tables excluded)."""
    text = "\n".join(l for l in reply.splitlines() if not l.strip().startswith("|"))
    names = sorted(set(list(teams) + list(ALIASES)), key=len, reverse=True)
    clubs = "|".join(re.escape(n) for n in names)
    name = r"(?P<name>[A-ZÀ-Ž][\w'’.\-À-ž]+(?:\s[A-ZÀ-Ž][\w'’.\-À-ž]+){0,3})"
    out = []
    club = r"(?P<club>(?i:" + clubs + r"))"                            # clubs case-insensitive, names capitalised
    # fix batch #4 close (2026-10-22): a club followed by a fixture marker -- "(away", "(home", "(A)", "(H)", ", away",
    # "(a)", "(h)" -- is a FIXTURE, not the player's club (the definition in the module docstring)
    not_fixture = r"(?!\s*,?\s*\(?\s*(?:away|home|[AHah])\b)"
    pos = r"(?:(?:GK|GKP|DEF|MID|FWD)\s*[,/|·\-–—]\s*\**)?"           # "Isak (FWD, Newcastle)": the position before the club
    who = r",?\s+who\s+(?:plays\s+(?:for|at)|is\s+(?:at|with))\s+"      # "Isak, who plays for Newcastle"
    sep = r"(?:\(\s*\**" + pos + r"|(?:—|–|-|,|\bof\b|\bat\b|\bfrom\b)\s*\**|" + who + r")"
    for m in re.finditer(name + r"\**\s*" + sep + club + r"\b" + not_fixture, text):
        out.append((m.group("name"), m.group("club"), "prose"))
    for m in re.finditer(r"\b" + club + r"(?:'s|’s)\s+\**" + name, text):
        out.append((m.group("name"), m.group("club"), "prose"))
    return out


def club_claims(reply, teams):
    return _table_claims(reply, teams) + _prose_claims(reply, teams)


def check(record, players):
    """One row per club claim: the player (resolved), the club the reply names, the club a tool output gives
    (sourced), the players-table club, and a status:
      sourced_ok        the turn's tool output gives this club
      sourced_wrong     a tool output gives a different club
      unsourced         no tool output gives the player's club (db_differs says whether the table disagrees)
      unknown_player    the name could not be resolved (ambiguous or not a player)"""
    reply = RJ.strip_sources(record.get("rendered_reply") or "")
    teams = sorted({p["team"] for p in players if p.get("team")})
    rows = tool_rows(record)
    out, seen = [], set()
    for ptext, ctext, where in club_claims(reply, teams):
        club = norm_club(ctext, teams)
        player, how = resolve(ptext, rows, players)
        key = (norm(_clean_name(ptext)), norm(ctext))
        if key in seen:
            continue
        seen.add(key)
        row = {"player_text": _clean_name(ptext), "club_text": ctext, "club": club, "where": where, "player": None,
               "resolved_by": how, "tool_club": None, "db_club": None, "status": None, "db_differs": None}
        if player is None:
            row["status"] = "unknown_player"
            out.append(row)
            continue
        row["player"] = player["name"]
        sourced = [r.get("team") for r in rows if norm(r["name"]) == norm(player["name"]) and r.get("team")]
        db = next((p["team"] for p in players if norm(p["name"]) == norm(player["name"])), None)
        row["db_club"] = db
        row["db_differs"] = (db is not None and club != db)
        if sourced:
            row["tool_club"] = sourced[0]
            row["status"] = "sourced_ok" if club == sourced[0] else "sourced_wrong"
        else:
            row["status"] = "unsourced"
        out.append(row)
    return out


def summary(rows):
    c = {"claims": len(rows)}
    for s in ("sourced_ok", "sourced_wrong", "unsourced", "unknown_player"):
        c[s] = sum(1 for r in rows if r["status"] == s)
    c["unsourced_db_differs"] = sum(1 for r in rows if r["status"] == "unsourced" and r["db_differs"])
    c["wrong_vs_table"] = sum(1 for r in rows if r["status"] in ("unsourced", "sourced_wrong", "sourced_ok") and r["db_differs"])
    return c
