"""Book-agreement check for player-prop odds (the-odds-api.com): for 2-3 ordinary CURRENT-season fixtures, pulls the anytime-goalscorer board for uk, eu and us in ONE request per fixture (one response = one instant, like-for-like), stores raw JSON first, then compares implied probabilities per player between the UK consensus (mean of UK books), 1xBet (eu) and the US consensus: Pearson on levels, Spearman on ranks, mean absolute difference overall and by favourites / longshots, and players priced by one side and not the other. Vig: anytime-scorer outcomes are not mutually exclusive, so probabilities cannot be normalised to 1; each book is scaled proportionally to the common mean total (raw 1/price also reported). Key from .env, never printed. No feature, no crosswalk, no scale pull. Result of record: Logs/player_props_coverage_log.md section 6.

Usage: uv run python eval/probe_props_book_agreement.py [--append-log]
"""
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import pearsonr, spearmanr

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "eval"))
import probe_player_props_coverage as p  # noqa: E402  (get, save, load_key, SPORT, MARKET, BIG_SIX)

UK_BOOKS = {"paddypower", "skybet", "williamhill", "betfair_ex_uk", "betfair_sb_uk", "ladbrokes_uk", "coral",
            "betvictor", "unibet_uk", "virginbet", "livescorebet", "grosvenor", "boylesports", "betway", "sport888"}
US_BOOKS = {"fanduel", "draftkings", "betmgm", "bovada", "betrivers", "mybookieag", "betonlineag", "lowvig", "unibet_us", "williamhill_us"}
EU_BOOK = "onexbet"
N_FIXTURES = 3


def implied(od):
    """{book: {player: 1/price}} for the anytime market in one response."""
    out = {}
    for bk in od.get("bookmakers", []):
        for mk in bk.get("markets", []):
            if mk["key"] != p.MARKET:
                continue
            out[bk["key"]] = {o.get("description") or o["name"]: 1.0 / float(o["price"]) for o in mk["outcomes"]
                              if (o.get("description") or o["name"]).lower() not in ("no scorer", "no goalscorer")}
    return out


def consensus(books, keys, players):
    """Mean implied probability over the books in `keys` that price each player."""
    vals = {}
    for pl in players:
        v = [books[b][pl] for b in keys if b in books and pl in books[b]]
        if v:
            vals[pl] = float(np.mean(v))
    return pd.Series(vals)


def compare(a, b, label, tercile_ref):
    """a, b: Series indexed by player (implied probs). tercile_ref: Series used
    to split favourites / longshots (top / bottom tercile)."""
    shared = a.index.intersection(b.index)
    x, y = a.loc[shared], b.loc[shared]
    d = (x - y).abs()
    q1, q2 = tercile_ref.loc[shared].quantile([1 / 3, 2 / 3])
    fav = tercile_ref.loc[shared] >= q2; long_ = tercile_ref.loc[shared] <= q1
    return dict(label=label, n=len(shared), pearson=float(pearsonr(x, y)[0]), spearman=float(spearmanr(x, y).statistic),
                mad=float(d.mean()), mad_fav=float(d[fav].mean()), mad_long=float(d[long_].mean()),
                bias=float((x - y).mean()), rel_long=float((d[long_] / y.loc[long_]).mean()),
                only_a=sorted(set(a.index) - set(b.index)), only_b=sorted(set(b.index) - set(a.index)))


def main():
    import json
    append = "--append-log" in sys.argv
    from_raw = "--from-raw" in sys.argv          # re-parse stored JSON; no API call, no credits
    if from_raw:
        raws = sorted((REPO / "data" / "odds_props" / "raw").glob("agree_*_ukeuus.json"))
        picks = [json.load(open(r, encoding="utf-8")) for r in raws]
        key, q = None, {"x-requests-last": 0, "x-requests-remaining": "n/a (from raw)"}
    else:
        key = p.load_key()
        ev, q = p.get(f"/sports/{p.SPORT}/events", {}, key)
        ordinary = [e for e in ev if not any(b in e["home_team"] or b in e["away_team"] for b in p.BIG_SIX)]
        picks = sorted(ordinary, key=lambda e: e["commence_time"])[:N_FIXTURES]
    rows, md = [], []
    md.append("## 6. Book-agreement check on the live market (2026-08-24; one request per fixture for uk+eu+us, so one instant per fixture)\n")
    md.append("Vig: anytime-scorer outcomes are not mutually exclusive, so implied probabilities cannot be normalised to 1. "
              "Each book is scaled proportionally so its total matches the cross-book mean total for that fixture "
              "(removes the book-level margin difference, keeps the shape); raw 1/price agreement is reported alongside. "
              "UK consensus = mean over UK books pricing the player; US consensus likewise. Favourites / longshots = "
              "top / bottom tercile by UK consensus probability.\n")
    for e in picks:
        if from_raw:
            od = e
        else:
            od, q = p.get(f"/sports/{p.SPORT}/events/{e['id']}/odds",
                          {"regions": "uk,eu,us", "markets": p.MARKET, "oddsFormat": "decimal"}, key)
            if od is None:
                continue
            p.save(od, f"agree_{e['home_team']}_{e['away_team']}_ukeuus.json".replace(" ", "_"))
        books = implied(od)
        uk = [b for b in books if b in UK_BOOKS]; us = [b for b in books if b in US_BOOKS]; eu = EU_BOOK in books
        upd = {bk["key"]: max(mk.get("last_update", "") for mk in bk["markets"]) for bk in od["bookmakers"]}
        print(f"=== {e['home_team']} v {e['away_team']} (commence {e['commence_time']}); cost {q['x-requests-last']}, remaining {q['x-requests-remaining']} ===")
        print(f"    books: uk {uk} | eu {'onexbet' if eu else 'none'} | us {us}")
        print(f"    market last_update range: {min(upd.values())} .. {max(upd.values())}")
        players = sorted({pl for b in books.values() for pl in b})
        # proportional margin adjustment: scale each book to the mean total
        totals = {b: sum(v.values()) for b, v in books.items()}
        mean_total = float(np.mean(list(totals.values())))
        adj = {b: {pl: pr * mean_total / totals[b] for pl, pr in v.items()} for b, v in books.items()}
        print(f"    book totals of raw implied prob (sum over board): " + ", ".join(f"{b} {t:.2f}" for b, t in sorted(totals.items())))
        for tag, src in (("adjusted", adj), ("raw", books)):
            uk_c = consensus(src, uk, players); us_c = consensus(src, us, players)
            one = pd.Series(src.get(EU_BOOK, {}))
            comps = []
            if len(one):
                comps.append(compare(uk_c, one, "UK consensus vs 1xBet", uk_c))
            if len(us_c):
                comps.append(compare(uk_c, us_c, "UK consensus vs US consensus", uk_c))
            for c in comps:
                print(f"    [{tag}] {c['label']:30s} n={c['n']:2d}  Pearson {c['pearson']:.3f}  Spearman {c['spearman']:.3f}  "
                      f"MAD {c['mad']:.3f} (fav {c['mad_fav']:.3f}, long {c['mad_long']:.3f}; long rel {c['rel_long']:.0%})  "
                      f"bias UK-other {c['bias']:+.3f}")
                if tag == "adjusted":
                    print(f"        priced by UK only: {c['only_a'] or '-'}; priced by other only: {c['only_b'] or '-'}")
                rows.append(dict(fixture=f"{e['home_team']} v {e['away_team']}", basis=tag, **{k: v for k, v in c.items() if k not in ('only_a', 'only_b')},
                                 only_uk=len(c["only_a"]), only_other=len(c["only_b"])))
        # UK books among themselves, adjusted -- the noise floor
        if len(uk) >= 2:
            a, b = uk[0], uk[1]
            sa, sb = pd.Series(adj[a]), pd.Series(adj[b])
            c = compare(sa, sb, f"{a} vs {b} (UK floor)", sa)
            print(f"    [adjusted] {c['label']:30s} n={c['n']:2d}  Pearson {c['pearson']:.3f}  Spearman {c['spearman']:.3f}  MAD {c['mad']:.3f} (fav {c['mad_fav']:.3f}, long {c['mad_long']:.3f})")
            rows.append(dict(fixture=f"{e['home_team']} v {e['away_team']}", basis="adjusted", **{k: v for k, v in c.items() if k not in ('only_a', 'only_b')}, only_uk=0, only_other=0))
        time.sleep(1)
    df = pd.DataFrame(rows)
    md.append("| fixture | comparison | basis | n shared | Pearson | Spearman | MAD | MAD favourites | MAD longshots | longshot rel. diff | bias UK−other | UK-only / other-only |")
    md.append("|---|---|---|---|---|---|---|---|---|---|---|---|")
    for r in df.itertuples():
        md.append(f"| {r.fixture} | {r.label} | {r.basis} | {r.n} | {r.pearson:.3f} | {r.spearman:.3f} | {r.mad:.3f} | {r.mad_fav:.3f} | {r.mad_long:.3f} | {r.rel_long:.0%} | {r.bias:+.3f} | {r.only_uk} / {r.only_other} |")
    pooled = df[df["basis"] == "adjusted"].groupby("label")[["n", "pearson", "spearman", "mad", "mad_fav", "mad_long", "rel_long", "bias"]].mean()
    md.append("\n**Pooled (mean over fixtures, adjusted basis):**\n")
    md.append("| comparison | Pearson | Spearman | MAD | MAD favourites | MAD longshots | longshot rel. diff | bias UK−other |\n|---|---|---|---|---|---|---|---|")
    for lab, r in pooled.iterrows():
        md.append(f"| {lab} | {r['pearson']:.3f} | {r['spearman']:.3f} | {r['mad']:.3f} | {r['mad_fav']:.3f} | {r['mad_long']:.3f} | {r['rel_long']:.0%} | {r['bias']:+.3f} |")
    print("\nPOOLED (adjusted):")
    print(pooled.round(3).to_string())
    print(f"\ncredits remaining: {q['x-requests-remaining']}")
    if append:
        log = REPO / "Logs" / "player_props_coverage_log.md"
        cur = log.read_text(encoding="utf-8")
        if "## 6. Book-agreement" not in cur:
            log.write_text(cur.rstrip("\n") + "\n\n---\n\n" + "\n".join(md) + "\n", encoding="utf-8")
            print(f"appended section 6 to {log}")


if __name__ == "__main__":
    main()
