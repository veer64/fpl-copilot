"""The admin dashboard and the users CSV (Prompt P7 Part 3, 2026-11-01). USER DECISIONS (1 Nov): "A list of who uses it:
emails, names, counts." "A dashboard with number of users." "CSV button."

Served by main.py at GET /admin (HTML) and GET /admin/users.csv, in clerk mode only and only to an admin (app_users.is_admin).
The numbers come from app_users, chat_usage (one row per answer; user_id on every signed-in turn) and cap_hits:
- total users; new sign-ups per day over the last 30 days (UTC days, today included); active today (last_active_at since
  00:00 UTC) and in the last 7 days;
- per user: answers and $ today, in the last 7 days and in all;
- cap hits today and in all; the sign-in method split (google / email / other).
The CSV has one row per user: name, email, sign-in method, joined, last active, answers, $ total. A cell that starts with
= + - or @ gets a leading ' (CSV_FORMULA_PREFIXES): a spreadsheet would otherwise run it as a formula. Read-only."""
import csv
import html
import io
from datetime import datetime, timedelta, timezone

import psycopg2.extras

import db_write

CSV_COLUMNS = ["name", "email", "sign-in method", "joined", "last active", "answers", "$ total"]
CSV_FORMULA_PREFIXES = ("=", "+", "-", "@")
SIGN_UP_DAYS = 30


def clock():
    return datetime.now(timezone.utc)


def _midnight(now):
    return now.astimezone(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)


def _rows(cur, sql, params=()):
    cur.execute(sql, params)
    return [dict(r) for r in cur.fetchall()]


def stats(conn=None):
    """Every number the page and the CSV show, as a dict (see the module docstring)."""
    now = clock()
    today, week = _midnight(now), now - timedelta(days=7)
    first_day = today - timedelta(days=SIGN_UP_DAYS - 1)
    own = conn is None
    if own:
        conn = db_write.connect()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            people = _rows(cur, "SELECT user_id, name, email, sign_in_method, created_at, last_active_at, is_admin, is_exempt "
                                "FROM app_users ORDER BY created_at, user_id")
            usage = {r["user_id"]: r for r in _rows(cur, """
                SELECT user_id,
                       count(*) FILTER (WHERE ts >= %(today)s)                AS answers_today,
                       COALESCE(sum(usd) FILTER (WHERE ts >= %(today)s), 0)  AS usd_today,
                       count(*) FILTER (WHERE ts >= %(week)s)                 AS answers_7_days,
                       COALESCE(sum(usd) FILTER (WHERE ts >= %(week)s), 0)   AS usd_7_days,
                       count(*)                                               AS answers_total,
                       COALESCE(sum(usd), 0)                                  AS usd_total
                FROM chat_usage WHERE user_id IS NOT NULL GROUP BY user_id""", {"today": today, "week": week})}
            hits = {r["user_id"]: r["n"] for r in _rows(cur, "SELECT user_id, count(*) AS n FROM cap_hits GROUP BY user_id")}
            hits_today = _rows(cur, "SELECT count(*) AS n FROM cap_hits WHERE hit_at >= %s", (today,))[0]["n"]
            sign_ups = _rows(cur, "SELECT (created_at AT TIME ZONE 'UTC')::date AS day, count(*) AS n FROM app_users "
                                  "WHERE created_at >= %s GROUP BY 1 ORDER BY 1", (first_day,))
    finally:
        if own:
            conn.close()
    users = []
    for p in people:
        u = usage.get(p["user_id"], {})
        users.append({**p,
                      "answers_today": int(u.get("answers_today", 0)), "usd_today": float(u.get("usd_today", 0)),
                      "answers_7_days": int(u.get("answers_7_days", 0)), "usd_7_days": float(u.get("usd_7_days", 0)),
                      "answers_total": int(u.get("answers_total", 0)), "usd_total": float(u.get("usd_total", 0)),
                      "cap_hits": int(hits.get(p["user_id"], 0))})
    methods = {}
    for p in people:
        m = p.get("sign_in_method") or "other"
        methods[m] = methods.get(m, 0) + 1
    return {"at": now, "total_users": len(people),
            "active_today": sum(1 for p in people if p.get("last_active_at") and p["last_active_at"] >= today),
            "active_7_days": sum(1 for p in people if p.get("last_active_at") and p["last_active_at"] >= week),
            "sign_ups_per_day": [(r["day"].isoformat(), int(r["n"])) for r in sign_ups],
            "sign_in_methods": methods, "cap_hits_today": int(hits_today), "cap_hits_total": int(sum(hits.values())),
            "users": users}


def _when(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC") if dt else ""


def csv_cell(value):
    """A CSV cell as text; one starting with = + - or @ gets a leading ' (formula injection)."""
    s = "" if value is None else str(value)
    return "'" + s if s.startswith(CSV_FORMULA_PREFIXES) else s


def users_csv(s):
    out = io.StringIO()
    w = csv.writer(out, lineterminator="\n")
    w.writerow(CSV_COLUMNS)
    for u in s["users"]:
        w.writerow([csv_cell(x) for x in (u.get("name"), u.get("email"), u.get("sign_in_method"), _when(u.get("created_at")),
                                          _when(u.get("last_active_at")), u["answers_total"], f"{u['usd_total']:.4f}")])
    return out.getvalue()


def _e(x):
    return html.escape("" if x is None else str(x), quote=True)


PAGE = """<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>FPL Copilot admin</title><style>
body{{font-family:sans-serif;max-width:1100px;margin:30px auto;padding:0 16px;line-height:1.4}}
.cards{{display:flex;gap:12px;flex-wrap:wrap}}.card{{border:1px solid #ddd;border-radius:6px;padding:10px 16px;min-width:150px}}
.big{{font-size:28px;font-weight:bold}}table{{border-collapse:collapse;width:100%;margin:12px 0}}
td,th{{border-bottom:1px solid #eee;padding:4px 8px;text-align:left}}td.n{{text-align:right}}
</style></head><body>
<h1>FPL Copilot admin</h1><p>As of {at}. <a href="/admin/users.csv">Download users.csv</a></p>
<div class="cards">
<div class="card">Total users<div class="big">{total}</div></div>
<div class="card">Active today<div class="big">{today}</div></div>
<div class="card">Active in the last 7 days<div class="big">{week}</div></div>
<div class="card">Cap hits today / all<div class="big">{hits_today} / {hits_total}</div></div>
</div>
<h2>Sign-in methods</h2><table><tr><th>method</th><th>users</th></tr>{methods}</table>
<h2>Sign-ups per day (last 30 days)</h2><table><tr><th>day (UTC)</th><th>new users</th></tr>{signups}</table>
<h2>Users</h2><table><tr><th>name</th><th>email</th><th>method</th><th>joined</th><th>last active</th>
<th>answers today</th><th>$ today</th><th>answers 7 days</th><th>$ 7 days</th><th>answers all</th><th>$ all</th>
<th>cap hits</th><th>admin</th></tr>{users}</table>
</body></html>"""


def render_html(s):
    methods = "".join(f"<tr><td>{_e(m)}</td><td class=n>{n}</td></tr>" for m, n in sorted(s["sign_in_methods"].items()))
    signups = "".join(f"<tr><td>{_e(d)}</td><td class=n>{n}</td></tr>" for d, n in s["sign_ups_per_day"]) or \
        "<tr><td colspan=2>none</td></tr>"
    rows = "".join(
        f"<tr><td>{_e(u.get('name'))}</td><td>{_e(u.get('email'))}</td><td>{_e(u.get('sign_in_method'))}</td>"
        f"<td>{_e(_when(u.get('created_at')))}</td><td>{_e(_when(u.get('last_active_at')))}</td>"
        f"<td class=n>{u['answers_today']}</td><td class=n>{u['usd_today']:.4f}</td>"
        f"<td class=n>{u['answers_7_days']}</td><td class=n>{u['usd_7_days']:.4f}</td>"
        f"<td class=n>{u['answers_total']}</td><td class=n>{u['usd_total']:.4f}</td>"
        f"<td class=n>{u['cap_hits']}</td><td>{'yes' if u.get('is_admin') else ''}</td></tr>" for u in s["users"])
    return PAGE.format(at=_e(_when(s["at"])), total=s["total_users"], today=s["active_today"], week=s["active_7_days"],
                       hits_today=s["cap_hits_today"], hits_total=s["cap_hits_total"], methods=methods, signups=signups,
                       users=rows)
