# fetch_teamnews_guardian.py
# Team-news investigation, STEP 2: was each of the 52 fixed cases publicly
# signalled BEFORE the deadline? Guardian Open Platform, full text via
# show-fields=body; webPublicationDate is the decisive timestamp.
#
# Design:
#   - ONE query stream per unique (team, season, gw) window (49, not 52) --
#     q = the team's common name, section=football, from deadline-10d to
#     deadline+3d, order-by=oldest, paged. RAW responses stored under
#     data/teamnews/guardian_raw/ BEFORE any parsing (api-key never stored,
#     never printed, never logged; read from .env, which is gitignored).
#   - Passage extraction is LOCAL: sentences mentioning the player (per-player
#     alias regexes -- Guardian uses common names, not vaastav legal names)
#     alongside absence language. Earliest qualifying article timestamp vs
#     the deadline classifies the case:
#       pre_deadline_signal / post_deadline_only / no_coverage
#   - Pacing: 1 request/sec; 429 backs off and retries; daily-quota headers
#     checked on the first response.
#
# Outputs: data/teamnews/guardian_passages.parquet (one row per case,
# classification + earliest hit + up to 5 verbatim passages as JSON).
# Usage: uv run python eval/fetch_teamnews_guardian.py [--parse-only]

import argparse
import json
import re
import time
import unicodedata
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import pandas as pd

REPO = Path(__file__).resolve().parent.parent
RAW = REPO / "data" / "teamnews" / "guardian_raw"
API = "https://content.guardianapis.com/search"

TEAM_QUERY = {"Man City": "Manchester City", "Man Utd": "Manchester United",
              "Spurs": "Tottenham", "Newcastle": "Newcastle United",
              "West Ham": "West Ham"}

# Per-player match patterns (case-sensitive, word-boundary). Guardian uses
# common names; specials: Arsenal's Gabriel must not match Jesus/Martinelli,
# and "Trafford" must not match "Old Trafford".
ALIASES = {
    "Bernardo Veiga de Carvalho e Silva": [r"\bBernardo( Silva)?\b"],
    "Diogo Teixeira da Silva": [r"\bJota\b", r"\bDiogo Jota\b"],
    "Dominic Solanke-Mitchell": [r"\bSolanke\b"],
    "Emiliano Martínez Romero": [r"\bEmiliano Mart[ií]nez\b", r"\bMart[ií]nez\b"],
    "Gabriel dos Santos Magalhães": [r"\bGabriel(?! Jesus)(?! Martinelli)\b",
                                     r"\bMagalh[aã]es\b"],
    "Norberto Murara Neto": [r"\bNeto\b"],
    "Richarlison de Andrade": [r"\bRicharlison\b"],
    "Sávio 'Savinho' Moreira de Oliveira": [r"\bSavinho\b", r"\bS[aá]vio\b"],
    "James Trafford": [r"(?<!Old )\bTrafford\b"],
    "Benjamin White": [r"\bBen(jamin)? White\b", r"\bWhite\b"],
    "Nico O'Reilly": [r"\bO'?Reilly\b"],
    "Rico Lewis": [r"\bRico Lewis\b", r"\bLewis\b"],
    "Nicolas Jackson": [r"\bJackson\b"],
    "Luis Díaz": [r"\bD[ií]az\b"],
    "Kevin De Bruyne": [r"\bDe Bruyne\b"],
    "Jan Paul van Hecke": [r"\b[Vv]an Hecke\b"],
}
# Every term carries a LEADING word boundary: the first pass matched "ill"
# inside Colwill/still/grill, "rest" inside Forest, "missed" inside
# dismissed -- classic false-positive family, caught by reading the passages.
ABSENCE = re.compile(
    r"\b(rest(ed|ing)?|doubts?|doubtful|injur\w*|knock(ed)?|assess\w*|"
    r"benched|left out|ruled out|(will|could|may|set to|expected to|"
    r"likely to) miss|miss(es)? out|missed (training|the)|absen\w*|"
    r"sidelined|illness|ill|sick|suspen\w*|fitness|strain(ed)?|hamstring|"
    r"groin|calf|knee|ankle|virus|withdrew|withdrawn|dropped|"
    r"drops? to the bench|not involved|unavailable|out of the squad|"
    r"rotat\w*)\b", re.IGNORECASE)
# player mention and absence term must sit within this many characters of
# each other inside the sentence -- cuts cross-player noise
PROXIMITY = 140


def api_key():
    for line in (REPO / ".env").read_text().splitlines():
        if line.strip().startswith("GUARDIAN_API_KEY="):
            return line.split("=", 1)[1].strip()
    raise RuntimeError("GUARDIAN_API_KEY not found in .env")


def patterns_for(player):
    if player in ALIASES:
        return [re.compile(p) for p in ALIASES[player]]
    last = player.split()[-1]
    return [re.compile(r"\b" + re.escape(last) + r"\b"),
            re.compile(r"\b" + re.escape(player) + r"\b")]


def fetch_window(key, team, season, gw, deadline, quota_seen=[False]):
    slug = f"{team.replace(' ', '_')}_{season.replace('-', '_')}_gw{gw}"
    pages = sorted(RAW.glob(f"{slug}_p*.json"))
    if pages:
        return pages
    q = TEAM_QUERY.get(team, team)
    frm = (deadline - pd.Timedelta(days=10)).date().isoformat()
    to = (deadline + pd.Timedelta(days=3)).date().isoformat()
    page, out = 1, []
    while True:
        params = {"q": f'"{q}"', "section": "football",
                  "from-date": frm, "to-date": to, "order-by": "oldest",
                  "show-fields": "body", "page-size": 50, "page": page,
                  "api-key": key}
        req = Request(API + "?" + urlencode(params),
                      headers={"User-Agent": "fpl-copilot-research"})
        for attempt in range(4):
            try:
                with urlopen(req, timeout=30) as resp:
                    if not quota_seen[0]:
                        rem = resp.headers.get("X-RateLimit-Remaining-day")
                        print(f"  [rate] daily remaining: {rem}", flush=True)
                        quota_seen[0] = True
                    data = json.load(resp)
                break
            except Exception as e:
                if attempt == 3:
                    raise
                wait = 5 * (attempt + 1)
                print(f"  [retry] {type(e).__name__}, waiting {wait}s",
                      flush=True)
                time.sleep(wait)
        resp_block = data["response"]
        # raw-first, key never stored (params are not persisted)
        p = RAW / f"{slug}_p{page}.json"
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(data), encoding="utf-8")
        tmp.replace(p)
        out.append(p)
        if page >= min(resp_block["pages"], 5):
            break
        page += 1
        time.sleep(1.0)
    time.sleep(1.0)
    return out


def strip_html(s):
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", s or ""))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--parse-only", action="store_true")
    a = ap.parse_args()
    RAW.mkdir(parents=True, exist_ok=True)
    cases = pd.read_parquet(REPO / "data" / "teamnews" / "case_list.parquet")
    key = None if a.parse_only else api_key()

    results = []
    windows = {}
    for i, r in cases.iterrows():
        wkey = (r["team"], r["season"], int(r["gw"]))
        deadline = pd.Timestamp(r["deadline_utc"])
        if wkey not in windows:
            if a.parse_only:
                slug = (f"{r['team'].replace(' ', '_')}_"
                        f"{r['season'].replace('-', '_')}_gw{int(r['gw'])}")
                windows[wkey] = sorted(RAW.glob(f"{slug}_p*.json"))
            else:
                print(f"fetch {wkey} ...", flush=True)
                windows[wkey] = fetch_window(key, r["team"], r["season"],
                                             int(r["gw"]), deadline)
        pats = patterns_for(r["player"])
        hits = []
        for p in windows[wkey]:
            data = json.loads(p.read_text(encoding="utf-8"))
            for art in data["response"].get("results", []):
                ts = pd.Timestamp(art["webPublicationDate"])
                body = strip_html(art.get("fields", {}).get("body", ""))
                for sent in re.split(r"(?<=[.!?])\s+", body):
                    if len(sent) > 600:
                        continue
                    pm = next((m for pt in pats for m in [pt.search(sent)]
                               if m), None)
                    if pm is None:
                        continue
                    am = ABSENCE.search(sent)
                    if am is None:
                        continue
                    if abs(am.start() - pm.start()) > PROXIMITY:
                        continue
                    hits.append({"ts": ts, "url": art["webUrl"],
                                 "passage": sent.strip()})
        hits.sort(key=lambda h: h["ts"])
        pre = [h for h in hits if h["ts"] < deadline]
        if pre:
            cls, first = "pre_deadline_signal", pre[0]
        elif hits:
            cls, first = "post_deadline_only", hits[0]
        else:
            cls, first = "no_coverage", None
        results.append({
            "season": r["season"], "gw": int(r["gw"]),
            "player": r["player"], "team": r["team"],
            "element": int(r["element"]), "group": r["group"],
            "deadline_utc": deadline,
            "classification": cls,
            "n_passages": len(hits),
            "n_pre_deadline": len(pre),
            "first_ts": first["ts"] if first else pd.NaT,
            "first_url": first["url"] if first else None,
            "first_passage": first["passage"] if first else None,
            "hours_before_deadline": (
                round((deadline - first["ts"]).total_seconds() / 3600, 1)
                if first else None),
            "passages_json": json.dumps(
                [{"ts": str(h["ts"]), "url": h["url"],
                  "passage": h["passage"]} for h in hits[:5]]),
        })
        print(f"  {r['season']} GW{r['gw']:2d} {r['player'][:28]:28s} "
              f"{cls:20s} pre={len(pre)} all={len(hits)}", flush=True)

    out = pd.DataFrame(results)
    out.to_parquet(REPO / "data" / "teamnews" / "guardian_passages.parquet",
                   index=False)
    print("\ncounts by classification:")
    print(out["classification"].value_counts().to_string())
    print("\nclassification x step-1 group:")
    print(out.groupby(["group", "classification"]).size()
          .unstack(fill_value=0).to_string())


if __name__ == "__main__":
    main()
