"""Live code locks on the final reply (M3a push, 2026-10-23), applied in agent.run_agent after the tool-name and
plain-word locks and before the citations are rendered. The raw reply is kept (logged) for the canary and the checkers.

L1 clubs: every club claim about a player in the reply ("Isak (FWD, Newcastle)", "Newcastle's Isak", a table's Club
   cell) is resolved with eval/judge/club_claims' resolver -- the turn's tool rows FIRST, the players table only as the
   fallback -- and when the player resolved to a TOOL ROW whose club differs from the one written, the written club is
   replaced with the tool's. A player found only in the players table, an ambiguous name or an unknown name changes
   nothing (logged). Measured before the lock: four 'Alexander Isak (FWD, Newcastle)' answers with team_out Liverpool
   in the plan the agent had just been given.
L2 weekdays (a wrong weekday before a date corrected to the calendar) was DROPPED in the same day's gate: live, it fired
   three times out of three on one answer and each time turned a sourced 'Monday' (the club's "Monday's press conference")
   into 'Tuesday', because the model had attached the wrong date -- the date was the slip, not the weekday. A lock that
   breaks its neighbour is dropped (the task's fallback). Weekdays are never touched.

The lock edits only the corrected span; everything else stays byte-identical. Pure functions; no I/O."""
import re
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parent
for _p in (str(_REPO / "eval"),):
    if _p not in sys.path:
        sys.path.insert(0, _p)
from judge import club_claims as CC          # noqa: E402  (the checker's resolver: one definition for check and lock)
from judge import metrics as M               # noqa: E402

def _tool_rows(tool_outputs):
    rows = []
    for o in tool_outputs or []:
        if not o:
            continue
        try:
            CC._rows_in(M.parse_output(o if isinstance(o, str) else str(o)), rows)
        except Exception:                                   # noqa: BLE001 -- a lock never raises
            continue
    return rows


def lock_clubs(text, tool_outputs, players):
    """(new_text, log). log entries: {lock: 'clubs', player_text, before, after, player, tool_club, resolved_by};
    `after` is None when nothing was changed for that claim (players-table-only, ambiguous, unknown, or already right)."""
    if not text or not players:
        return text, []
    teams = sorted({p["team"] for p in players if p.get("team")})
    if not teams:
        return text, []
    rows = _tool_rows(tool_outputs)
    log, edits = [], []                                      # edits: (start, end, replacement)

    def decide(ptext, ctext):
        club = CC.norm_club(ctext, teams)
        player, how = CC.resolve(ptext, rows, players)
        entry = {"lock": "clubs", "player_text": CC._clean_name(ptext), "before": ctext, "after": None, "player": None,
                 "tool_club": None, "resolved_by": how}
        if player is None or how != "tool":
            return entry, None
        entry["player"] = player["name"]
        sourced = [r.get("team") for r in rows if CC.norm(r.get("name") or "") == CC.norm(player["name"]) and r.get("team")]
        if not sourced:
            return entry, None
        entry["tool_club"] = sourced[0]
        if club is not None and club == sourced[0]:
            return entry, None
        if club is None:
            return entry, None                                # a club word the vocabulary does not know: leave it
        entry["after"] = sourced[0]
        return entry, sourced[0]

    # prose forms, spans from the checker's own patterns -- on every line, table cells included ("| Alexander Isak
    # (FWD, Newcastle) | £9.0m |" was the measured case: a transfer table with no Club column)
    lines, pos = text.split("\n"), 0
    for line in lines:
        for pat in CC.prose_patterns(teams):
            for m in pat.finditer(line):
                entry, new_club = decide(m.group("name"), m.group("club"))
                log.append(entry)
                if new_club is not None:
                    s, e = m.span("club")
                    edits.append((pos + s, pos + e, new_club))
        pos += len(line) + 1
    # tables with a Club / Team column: the cell itself
    pos = 0
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if stripped.startswith("|") and i + 1 < len(lines) and re.match(r"^\|\s*:?-+", lines[i + 1].strip()):
            head = [CC.norm(c) for c in stripped.strip("|").split("|")]
            ci = next((k for k, h in enumerate(head) if h in ("club", "team")), None)
            pi = next((k for k, h in enumerate(head) if h in ("player", "name")), None)
            pos += len(line) + 1 + len(lines[i + 1]) + 1
            i += 2
            if ci is None or pi is None:
                continue
            while i < len(lines) and lines[i].strip().startswith("|"):
                row = lines[i]
                cells = row.split("|")                        # keep the raw cells to find the span
                inner = cells[1:-1] if len(cells) >= 3 else []
                if len(inner) > max(ci, pi):
                    ptext, ctext = inner[pi].strip(), inner[ci].strip()
                    if ptext and ctext and ctext not in ("—", "-", "–") and not re.match(r"^\*?\*?(bench|starting xi)\b", ptext, re.I):
                        entry, new_club = decide(ptext, ctext)
                        log.append(entry)
                        if new_club is not None:
                            off = 1 + sum(len(c) + 1 for c in inner[:ci])          # the leading '|' then cells and their '|'
                            lead = len(inner[ci]) - len(inner[ci].lstrip())
                            s = pos + off + lead
                            edits.append((s, s + len(ctext), new_club))
                pos += len(row) + 1
                i += 1
            continue
        pos += len(line) + 1
        i += 1
    if not edits:
        return text, log
    out, last = [], 0
    for s, e, rep in sorted(edits):
        if s < last:
            continue
        out.append(text[last:s]); out.append(rep); last = e
    out.append(text[last:])
    return "".join(out), log


def players_table():
    """The players table for the locks ([] on any failure: the locks then change nothing and log nothing)."""
    try:
        import db_write
        conn = db_write.connect()
        try:
            return CC.load_players(conn)
        finally:
            conn.close()
    except Exception:                                       # noqa: BLE001
        return []


def apply_locks(text, tool_outputs, players):
    """The club lock; returns (text, the corrections that changed something)."""
    t1, log1 = lock_clubs(text, tool_outputs, players)
    return t1, [c for c in log1 if c.get("after")]
