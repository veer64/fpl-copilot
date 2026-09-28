"""The weekly relevance report (Part 9, 2026-09-28): what the production judge and the shadow judge
did with one gameweek's news, and a review list the user labels to grow the gold set.

    uv run python eval/relevance_report.py --gw 6          # writes eval/reports/relevance_gw6.md

The week of GW N is (deadline of GW N-1, deadline of GW N] by fetched_at. Production = config
PROMPT_VERSION / RELEVANCE_MODEL, shadow = SHADOW_JUDGE_PROMPT_VERSION / SHADOW_JUDGE_MODEL; keep =
relevant AND current. The report lists, with blank RELEVANT / CURRENT / NOTE lines for the user:
  * every item the shadow kept and production dropped;
  * every item production kept and the shadow dropped;
  * every item production dropped and the shadow REFUSED (ruling 2026-09-28: added automatically);
  * 10 random items both dropped (fixed seed).
Plus per club and source: collected, kept by production, kept by shadow; the week's LLM calls and
cost, production and shadow separately; the shadow's refusal rate and the refused items.
eval/labels/append_gold.py turns the user's labels in the report into gold rows. Not scheduled:
the user runs it after each deadline. Reports carry article excerpts, so eval/reports/*.md is
gitignored; the labels go to the committable CSV.
"""
import argparse
import random
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "eval"))
import config_roles  # noqa: E402
import db_write  # noqa: E402
import relevance as rv  # noqa: E402

UTC = timezone.utc
OUT_DIR = REPO / "eval" / "reports"
SAMPLE = 10
EXCERPT = 600


def week_window(gw, events):
    """(start, end] for GW `gw`: the previous event's deadline and this one's."""
    dls = sorted((int(e["id"]), rv._parse_iso(e.get("deadline_time"))) for e in events if rv._parse_iso(e.get("deadline_time")))
    end = next((d for i, d in dls if i == int(gw)), None)
    if end is None:
        raise ValueError(f"GW{gw} has no deadline in the events list")
    prev = [d for i, d in dls if i < int(gw)]
    start = max(prev) if prev else datetime(1970, 1, 1, tzinfo=UTC)
    return start, end


def _yn(b):
    return "y" if b else "n"


def _reason(r):
    return r.split(" | llm: ", 1)[1] if r and " | llm: " in r else (r or "")


def build_report(conn, gw, events=None, seed=20260926, prices=None):
    """(markdown text, summary dict) for GW `gw`."""
    if events is None:
        _, events, _ = rv.load_context()
    prices = prices or config_roles.MODEL_PRICES_USD_PER_MTOK
    start, end = week_window(gw, events)
    P = (config_roles.PROMPT_VERSION, config_roles.RELEVANCE_MODEL)
    S = (config_roles.SHADOW_JUDGE_PROMPT_VERSION, config_roles.SHADOW_JUDGE_MODEL)
    cur = conn.cursor()
    cur.execute("SELECT id, source, club, url, headline, body, published_at, fetched_at, date_source FROM news_items "
                "WHERE source IN ('bbc', 'club') AND fetched_at > %s AND fetched_at <= %s ORDER BY id", (start, end))
    cols = ("id", "source", "club", "url", "headline", "body", "published_at", "fetched_at", "date_source")
    items = {r[0]: dict(zip(cols, r)) for r in cur.fetchall()}
    ids = list(items)
    verdicts = {}
    for tag, (pv, model) in (("production", P), ("shadow", S)):
        if ids:
            cur.execute("SELECT news_item_id, relevant, current, reason, stage FROM news_relevance WHERE prompt_version = %s AND model = %s "
                        "AND news_item_id = ANY(%s)", (pv, model, ids))
            for iid, rel, cu, reason, stage in cur.fetchall():
                verdicts.setdefault(iid, {})[tag] = {"relevant": bool(rel), "current": bool(cu), "keep": bool(rel and cu), "reason": reason, "stage": stage}
    refusals = {}
    if ids:
        cur.execute("SELECT news_item_id, count(*) FROM llm_calls WHERE model = %s AND prompt_version = %s AND error = 'refusal' "
                    "AND news_item_id = ANY(%s) GROUP BY 1", (S[1], S[0], ids))
        refusals = {i: int(n) for i, n in cur.fetchall()}
    calls = {}
    for tag, (pv, model) in (("production", P), ("shadow", S)):
        cur.execute("SELECT count(*), count(*) FILTER (WHERE ok), count(*) FILTER (WHERE error = 'refusal'), COALESCE(sum(input_tokens), 0), "
                    "COALESCE(sum(output_tokens), 0) FROM llm_calls WHERE model = %s AND prompt_version = %s AND called_at > %s AND called_at <= %s",
                    (model, pv, start, end))
        n, ok, refused, ti, to = cur.fetchone()
        pi, po = prices.get(model, (0.0, 0.0))
        calls[tag] = {"model": model, "prompt_version": pv, "calls": int(n), "ok": int(ok), "refused": int(refused), "tokens_in": int(ti),
                      "tokens_out": int(to), "cost_usd": round(int(ti) / 1e6 * pi + int(to) / 1e6 * po, 4)}

    def kept(i, tag):
        return verdicts.get(i, {}).get(tag, {}).get("keep", False)

    def has(i, tag):
        return tag in verdicts.get(i, {})

    shadow_kept_prod_dropped = [i for i in ids if kept(i, "shadow") and not kept(i, "production")]
    prod_kept_shadow_dropped = [i for i in ids if kept(i, "production") and has(i, "shadow") and not kept(i, "shadow")]
    dropped_and_refused = [i for i in ids if not kept(i, "production") and not has(i, "shadow") and refusals.get(i, 0) > 0]
    both_dropped = [i for i in ids if has(i, "production") and has(i, "shadow") and not kept(i, "production") and not kept(i, "shadow")]
    sample = sorted(random.Random(seed).sample(both_dropped, min(SAMPLE, len(both_dropped))))
    groups = {}
    for i in ids:
        key = (items[i]["source"], items[i]["club"] or "-")
        g = groups.setdefault(key, {"collected": 0, "kept_production": 0, "kept_shadow": 0})
        g["collected"] += 1
        g["kept_production"] += int(kept(i, "production"))
        g["kept_shadow"] += int(kept(i, "shadow"))
    shadow_requests, shadow_refusals = calls["shadow"]["calls"], calls["shadow"]["refused"]
    rate = shadow_refusals / shadow_requests if shadow_requests else 0.0
    refused_items = sorted(i for i in ids if refusals.get(i, 0) > 0)

    lines = [f"# Relevance report: GW{gw}", "",
             f"Week: fetched after {start:%Y-%m-%d %H:%M}Z up to {end:%Y-%m-%d %H:%M}Z. Production = {P[0]} / {P[1]}; "
             f"shadow = {S[0]} / {S[1]}. keep = relevant AND current. Generated {datetime.now(UTC):%Y-%m-%d %H:%M}Z.", "",
             "Review: for each item listed below write y or n after RELEVANT and CURRENT (NOTE optional), then run",
             f"`python eval/labels/append_gold.py eval/reports/relevance_gw{gw}.md --gw {gw}` to add your labels to the gold set.",
             "Judge \"current\" as of the item's Judged-as-of date, not today.", "",
             "## Per club and source", "", "| source | club | collected | kept by production | kept by shadow |", "|---|---|---|---|---|"]
    for (src, club), g in sorted(groups.items()):
        lines.append(f"| {src} | {club} | {g['collected']} | {g['kept_production']} | {g['kept_shadow']} |")
    lines += ["", f"Totals: collected {len(ids)}, kept by production {sum(kept(i, 'production') for i in ids)}, kept by shadow {sum(kept(i, 'shadow') for i in ids)}.", "",
              "## LLM calls and cost this week", "", "| judge | model | prompt | calls | ok | refused | tokens in | tokens out | cost USD |", "|---|---|---|---|---|---|---|---|---|"]
    for tag in ("production", "shadow"):
        c = calls[tag]
        lines.append(f"| {tag} | {c['model']} | {c['prompt_version']} | {c['calls']} | {c['ok']} | {c['refused']} | {c['tokens_in']} | {c['tokens_out']} | {c['cost_usd']:.4f} |")
    lines += ["", f"Shadow refusal rate this week: {shadow_refusals}/{shadow_requests} requests ({rate:.1%}). Refused items: "
              + (", ".join(f"#{i}" for i in refused_items) if refused_items else "none") + ".", ""]

    def block(i, why):
        it = items[i]
        ctx = rv.context_for(it, events, None)
        out = [f"### Item {i}", f"Source: {rv.source_label(it)} | Club: {it['club'] or '-'} | Judged as of: {ctx['as_of']:%Y-%m-%d}",
               f"Listed because: {why}", f"Date: {rv.date_label(it)}", f"Headline: {it['headline']}"]
        for tag, (pv, model) in (("Production", P), ("Shadow", S)):
            v = verdicts.get(i, {}).get(tag.lower())
            if v is None:
                n = refusals.get(i, 0)
                out.append(f"{tag} ({pv} / {model}): " + (f"refused by the API {n} time(s), no verdict" if n else "no verdict"))
            else:
                out.append(f"{tag} ({pv} / {model}): relevant {_yn(v['relevant'])}, current {_yn(v['current'])}, keep {_yn(v['keep'])} | {_reason(v['reason'])}")
        out += [f"Text (first {EXCERPT} chars): {(it['body'] or '')[:EXCERPT]}", "RELEVANT (y/n):", "CURRENT (y/n):", "NOTE:", ""]
        return out

    for title, lst, why in (("Shadow kept, production dropped", shadow_kept_prod_dropped, "the shadow kept it and production dropped it"),
                            ("Production kept, shadow dropped", prod_kept_shadow_dropped, "production kept it and the shadow dropped it"),
                            ("Production dropped, shadow refused", dropped_and_refused, "production dropped it and the shadow judge was refused by the API"),
                            (f"Random sample of items both dropped (seed {seed})", sample, "both judges dropped it; random check")):
        lines += [f"## {title} ({len(lst)})", ""]
        if not lst:
            lines += ["(none)", ""]
        for i in lst:
            lines += block(i, why)
    summary = {"gw": int(gw), "window": (start, end), "collected": len(ids), "kept_production": sum(kept(i, "production") for i in ids),
               "kept_shadow": sum(kept(i, "shadow") for i in ids), "shadow_kept_production_dropped": shadow_kept_prod_dropped,
               "production_kept_shadow_dropped": prod_kept_shadow_dropped, "dropped_and_refused": dropped_and_refused,
               "both_dropped_sample": sample, "shadow_requests": shadow_requests, "shadow_refusals": shadow_refusals,
               "shadow_refusal_rate": rate, "refused_items": refused_items, "calls": calls, "groups": groups}
    return "\n".join(lines), summary


def write_report(conn, gw, out_dir=OUT_DIR, events=None, seed=20260926):
    text, _ = build_report(conn, gw, events=events, seed=seed)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"relevance_gw{int(gw)}.md"
    path.write_text(text, encoding="utf-8")
    return path


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--gw", type=int, required=True)
    ap.add_argument("--seed", type=int, default=20260926)
    a = ap.parse_args()
    conn = db_write.connect()
    try:
        path = write_report(conn, a.gw, seed=a.seed)
        _, s = build_report(conn, a.gw, seed=a.seed)
        print(f"written {path}: collected {s['collected']}, kept production {s['kept_production']}, kept shadow {s['kept_shadow']}, "
              f"review items {len(s['shadow_kept_production_dropped']) + len(s['production_kept_shadow_dropped']) + len(s['dropped_and_refused']) + len(s['both_dropped_sample'])}, "
              f"shadow refusal rate {s['shadow_refusals']}/{s['shadow_requests']}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
