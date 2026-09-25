"""Club-news ingestion v1 (2026-09-25): the official sites of the nine clubs whose pages
Tavily can actually read, searched once per club per run and extracted once per URL, into
news_items as source 'club'. No relevance filter, no chunking, no embeddings here.

WHAT WAS MEASURED FIRST (the same day), and what each rule below answers:
  * Tavily basic search returns real availability text for 9 of 20 club sites; the other
    11 return ~150-char stubs or nothing at any depth -> CLUB_NEWS_CLUBS in config_roles.
  * include_domains is NOT reliably honoured (an advanced search for ccfc.co.uk returned
    reddit.com, cbsnews.com, ...) -> every result's host is checked here: the club's
    registrable domain or a subdomain of it, never a look-alike (arsenal.com.evil.io).
  * the date filter is NOT honoured and Tavily gives no publish date on these sites
    (search: 0 of 52 results; extract: 0 of 19 pages) -> published_at comes from the URL
    when it carries an unambiguous day-level date with a year, otherwise NULL and the row
    says how it is dated: date_source 'url' / 'first_seen' / 'backlog' (--seed).
  * results include listing pages (?page=1, /listing/, bare /news) and old articles -> the
    listing filter here; old articles are kept and dated by the rule above.
  * Extract returns Markdown with navigation residue -> clean_markdown(), deterministic.

CREDITS (by Tavily's published rule: basic search 1, basic extract 1 per 5 URLs): every
call writes a tavily_calls row, and before ANY call the month's recorded total plus the
worst-case plan for this run must not exceed config_roles.TAVILY_MONTHLY_LIMIT, else
nothing is called (CreditLimit). The usage endpoint was observed to lag by hours, so the
guard trusts the table, not the endpoint.

IDEMPOTENCY: guid = canonical URL (https, host without www., no query/fragment/trailing
slash). A guid already stored for source 'club' is skipped without a second extract (v1:
no re-extract, so a club article is one version). Raw search and extract responses are
gzipped under data/news/raw/tavily/ (backed up: outside data/live/) before anything is
parsed; raw_ref is the extract file.
"""
import gzip
import json
import math
import os
import re
import ssl
import tempfile
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import parse_qsl, urlparse
from urllib.request import Request, urlopen

import config_roles
from config_roles import CLUB_DOMAINS, CLUB_NEWS_CLUBS, TAVILY_MONTHLY_LIMIT, TEAM_ALIASES  # noqa: F401  (re-exported)
import news_store as ns

REPO = Path(__file__).resolve().parent
RAW_DIR = REPO / "data" / "news" / "raw" / "tavily"
QUERY = "{club} team news injury update"
SEARCH_CREDITS = 1
EXTRACT_URLS_PER_CREDIT = 5
EXTRACT_BATCH = 20                       # Tavily's per-request URL limit
MAX_RESULTS = 10                         # basic search: still 1 credit (v2, Part A)
USER_AGENT = "fpl-copilot club news (+https://github.com/veer64/fpl-copilot)"
MONTHS = {m: i for i, m in enumerate(("january", "february", "march", "april", "may", "june", "july",
                                      "august", "september", "october", "november", "december"), 1)}
MONTHS.update({m[:3]: i for m, i in list(MONTHS.items())})
MONTHS["sept"] = 9


def search_request(query, domains, start_date=None, end_date=None):
    """The one place a search body is built: basic depth, MAX_RESULTS, the domains given.
    The date range is passed when known (it is not reliably honoured, so the old-article
    guard decides what is kept); the Guardian is never among the domains."""
    allowed = set(CLUB_DOMAINS.values())
    assert domains and all(d in allowed for d in domains), (
        f"only the club domains in config_roles.CLUB_DOMAINS may be searched, never {sorted(set(domains) - allowed)}: "
        f"bbc.co.uk, skysports.com and theguardian.com are excluded by decision (2026-09-25)")
    body = {"query": query, "search_depth": "basic", "include_domains": list(domains), "max_results": MAX_RESULTS}
    if start_date:
        body["start_date"] = start_date
    if end_date:
        body["end_date"] = end_date
    return body


# Site suffixes a club headline carries: "Xabi Alonso confirms ... | News | Official Site |
# Chelsea Football Club", "... - Liverpool FC", "... | NUFC". Segments are split on " | " and
# " - " and dropped from the RIGHT while they look like a site/club label; the first
# segment always stays, and a segment with real words ("key questions answered") stops it.
_SEP = re.compile(r"\s+[|\-\u2013\u2014]\s+")
_SITE_WORDS = re.compile(r"^(news|home|latest|latest news|men'?s team|club news|official site|official website|website)$"
                         r"|\bofficial\b|\bfootball club\b|\bfc\b|\.(com|co\.uk|net)$", re.I)
_SITE_CODES = re.compile(r"^(NUFC|MUFC|THFC|CPFC|LUFC|SAFC|AVFC|MCFC|LFC|NFFC|EFC|FFC|BFC|AFC)$")      # case-sensitive


def _club_labels():
    labels = set(CLUB_DOMAINS)
    for k, v in TEAM_ALIASES.items():
        labels.update(v)
    return {x.lower() for x in labels}


def trim_headline(title):
    t = " ".join((title or "").split())
    labels = _club_labels()
    seps = list(_SEP.finditer(t))
    while seps:
        last = t[seps[-1].end():].strip()
        if _SITE_WORDS.search(last) or _SITE_CODES.match(last) or last.lower() in labels:
            t = t[:seps[-1].start()].rstrip()          # cut the ORIGINAL string: separators stay as written
            seps.pop()
            continue
        break
    return t


class CreditLimit(RuntimeError):
    """The month's recorded credits plus this run's plan would exceed TAVILY_MONTHLY_LIMIT."""


def extract_credits(n_urls):
    return math.ceil(n_urls / EXTRACT_URLS_PER_CREDIT)


# ---- URL rules ---------------------------------------------------------------------------

def _host(url):
    return (urlparse(url.strip()).netloc or "").lower().split("@")[-1].split(":")[0]


def on_domain(url, domain):
    """The registrable domain itself or a subdomain of it -- never a look-alike."""
    h, d = _host(url), domain.lower().strip()
    return h == d or h.endswith("." + d)


def canonical_guid(url):
    """https, lowercase host without 'www.', path without trailing slash, no query, no fragment."""
    p = urlparse(url.strip())
    host = _host(url)
    if host.startswith("www."):
        host = host[4:]
    path = p.path or ""
    path = path.rstrip("/")
    return f"https://{host}{path}"


def listing_reason(url):
    """Why a URL is an index/listing page rather than an article, or None."""
    p = urlparse(url.strip())
    if any(k.lower() == "page" for k, _ in parse_qsl(p.query, keep_blank_values=True)):
        return "listing:page="
    path = (p.path or "").lower()
    if "/listing" in path:
        return "listing:/listing"
    if path.rstrip("/") in ("", "/news", "/en/news"):
        return "listing:index"
    return None


_URL_DATE = re.compile(r"/(20\d{2})/(\d{1,2}|[a-z]+)/(\d{1,2})(?:/|$)", re.I)


def url_date(url):
    """An unambiguous day-level date WITH a year in the path (/2026/september/14/, /2026/09/14/),
    else None. A slug with a day but no year, or a month and year but no day, is not a date."""
    m = _URL_DATE.search(urlparse(url.strip()).path or "")
    if not m:
        return None
    year, month, day = m.groups()
    mon = int(month) if month.isdigit() else MONTHS.get(month.lower())
    if not mon:
        return None
    try:
        return date(int(year), mon, int(day))
    except ValueError:
        return None


def filter_results(results, domain):
    """(kept, dropped[(url, reason)]) -- off-domain first, then listing pages."""
    kept, dropped = [], []
    for r in results or []:
        url = (r.get("url") or "").strip()
        if not url:
            dropped.append((url, "no url"))
            continue
        if not on_domain(url, domain):
            dropped.append((url, f"off-domain: {_host(url)}"))
            continue
        why = listing_reason(url)
        if why:
            dropped.append((url, why))
            continue
        kept.append(r)
    return kept, dropped


# ---- Markdown -> plain text (deterministic) --------------------------------------------------

_LINK_ONLY = re.compile(r"^(?:\s*!?\[[^\]]*\]\([^)]*\)\s*)+$")
_IMAGE = re.compile(r"!\[[^\]]*\]\([^)\n]*\)")
_LINK = re.compile(r"\[((?:[^\[\]]|\[[^\]]*\])*)\]\([^)\n]*\)")   # text may span lines and nest once; the URL may not
_REF_LINK = re.compile(r"\[([^\]]+)\]\[[^\]]*\]")
_BARE_URL = re.compile(r"https?://\S+")
_HEADING = re.compile(r"^#{1,6}\s*")
_LIST = re.compile(r"^(?:[-*+]|\d+[.)])\s+")
_EMPH = re.compile(r"(?<![\w'’])[*_]{1,3}(?=\S)|(?<=\S)[*_]{1,3}(?![\w'’])")
_WS = re.compile(r"\s+")
_ENDS = re.compile(r"[.!?…\"”’')\]]$")
MIN_WORDS = 4


def clean_markdown(md):
    """Keep link text, drop URLs and images, drop link-only lines and short menu lines
    (fewer than MIN_WORDS words without terminal punctuation), strip heading/list/emphasis
    markers, collapse whitespace. Same input, same output.

    Two passes on purpose: link-only lines are dropped while the links are still visible
    (a menu of five links is five words of text once unwrapped), and THEN images and
    links are unwrapped over the whole text, because club sites emit link cards whose
    text spans several lines -- "[![alt](img)\n\n### Heading\n\nMen's Team](/news/...)" --
    which a line-by-line pass would leave as a stray "](/news/...)"."""
    def link_only(line):
        # balanced brackets, or the line is the OPENING of a multi-line link card
        # ("[![alt](img)") and must survive to the whole-text pass
        return bool(_LINK_ONLY.match(line)) and line.count("[") == line.count("]")
    kept = [raw for raw in (md or "").replace("\r\n", "\n").split("\n")
            if not link_only(_HEADING.sub("", raw.strip()))]
    text = "\n".join(kept)
    text = _IMAGE.sub("", text)
    text = _LINK.sub(r"\1", text)
    text = _REF_LINK.sub(r"\1", text)
    out = []
    for raw in text.split("\n"):
        line = _HEADING.sub("", raw.strip())
        line = _BARE_URL.sub("", line)
        line = _LIST.sub("", line)
        line = re.sub(r"^>\s*", "", line)
        line = _EMPH.sub("", line)
        line = _WS.sub(" ", line).strip()
        if not line:
            continue
        if len(line.split()) < MIN_WORDS and not _ENDS.search(line):
            continue
        out.append(line)
    return "\n".join(out)


# ---- the credit ledger --------------------------------------------------------------------

def month_credits(conn, now):
    start = datetime(now.year, now.month, 1, tzinfo=timezone.utc)
    with conn.cursor() as cur:
        cur.execute("SELECT COALESCE(SUM(credits), 0) FROM tavily_calls WHERE called_at >= %s", (start,))
        return int(cur.fetchone()[0])


def record_call(conn, endpoint, club, query, n_results, credits, called_at=None):
    with conn.cursor() as cur:
        cur.execute("INSERT INTO tavily_calls (called_at, endpoint, club, query, n_results, credits) "
                    "VALUES (%s, %s, %s, %s, %s, %s)",
                    (called_at or datetime.now(timezone.utc), endpoint, club, query, n_results, int(credits)))
    conn.commit()


def credit_guard(conn, planned, now, limit=None):
    limit = TAVILY_MONTHLY_LIMIT if limit is None else limit
    used = month_credits(conn, now)
    if used + planned > limit:
        raise CreditLimit(f"TAVILY_MONTHLY_LIMIT {limit}: {used} credits recorded for {now:%Y-%m} plus "
                          f"{planned} planned for this run = {used + planned} > {limit}; no call made")
    return used


def existing_guids(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT guid FROM news_items WHERE source = 'club'")
        return {r[0] for r in cur.fetchall()}


# ---- raw first ----------------------------------------------------------------------------

def save_raw(raw_dir, name, obj):
    raw_dir = Path(raw_dir)
    raw_dir.mkdir(parents=True, exist_ok=True)
    path = raw_dir / name
    n = 1
    while path.exists():                                   # never overwrite a raw file
        n += 1
        path = raw_dir / name.replace(".json.gz", f".{n}.json.gz")
    fd, tmp = tempfile.mkstemp(dir=str(raw_dir), suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(gzip.compress(json.dumps(obj).encode("utf-8")))
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise
    return path


# ---- Tavily -------------------------------------------------------------------------------

class TavilyClient:
    """search(query, domain) and extract(urls) over the public API. The key is read from the
    environment at construction and never logged, printed or stored anywhere else."""
    def __init__(self, key=None):
        self._key = key or os.environ.get("TAVILY_API_KEY", "")
        if not self._key:
            raise RuntimeError("TAVILY_API_KEY is not set")
        try:
            import certifi
            self._ctx = ssl.create_default_context(cafile=certifi.where())
        except ImportError:
            self._ctx = ssl.create_default_context()

    def _post(self, url, body):
        req = Request(url, data=json.dumps(body).encode("utf-8"), method="POST",
                      headers={"Authorization": f"Bearer {self._key}", "Content-Type": "application/json",
                               "User-Agent": USER_AGENT})
        try:
            with urlopen(req, timeout=90, context=self._ctx) as r:
                return json.loads(r.read().decode("utf-8"))
        except HTTPError as e:
            raise RuntimeError(f"Tavily HTTP {e.code} from {url}: {e.read().decode('utf-8', 'replace')[:200]}") from None

    def search(self, query, domain, start_date=None, end_date=None):
        domains = [domain] if isinstance(domain, str) else list(domain)
        return self._post("https://api.tavily.com/search", search_request(query, domains, start_date, end_date))

    def extract(self, urls):
        return self._post("https://api.tavily.com/extract", {"urls": list(urls), "extract_depth": "basic"})



# ---- v2 (2026-09-25): the schedule gate, opponents, aliases, dates, the guard ------------------

WINDOW_DAYS = 3


def parse_iso(v):
    try:
        d = datetime.fromisoformat(str(v).strip().replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def gate(now, events, days=WINDOW_DAYS):
    """The next gameweek is the first event whose deadline is at or after `now`; the run may
    search only inside [deadline - days, deadline], both ends inclusive, so a run AT the
    deadline still counts. Returns {open, gw, deadline, opens_at, window}."""
    nxt = None
    for e in sorted(events or [], key=lambda e: str(e.get("deadline_time"))):
        d = parse_iso(e.get("deadline_time"))
        if d is not None and d >= now:
            nxt = (int(e["id"]), d)
            break
    if nxt is None:
        return {"open": False, "gw": None, "deadline": None, "opens_at": None, "window": None}
    gw, dl = nxt
    opens = dl - timedelta(days=days)
    return {"open": opens <= now <= dl, "gw": gw, "deadline": dl, "opens_at": opens, "window": (opens, dl)}


def team_aliases(teams=None):
    """{FPL team name: [every form it is called]} = the FPL name and short code (from the
    bootstrap-static teams block) plus config_roles.TEAM_ALIASES."""
    out = {}
    fpl = {t["name"]: t for t in (teams or []) if t.get("name")}
    for club in set(CLUB_DOMAINS) | set(fpl) | set(TEAM_ALIASES):
        forms = [club]
        if club in fpl and fpl[club].get("short_name"):
            forms.append(str(fpl[club]["short_name"]))
        forms += TEAM_ALIASES.get(club, [])
        seen, uniq = set(), []
        for f in forms:
            if f and f not in seen:
                seen.add(f)
                uniq.append(f)
        out[club] = uniq
    return out


def names_team(text, club, aliases):
    """Whole-word match on any alias. Short upper-case codes (TOT, MUN) match case-sensitively
    and as whole words only, so 'total' is not Spurs and 'United' alone is nobody."""
    t = text or ""
    for a in aliases.get(club, [club]):
        if a.isupper() and len(a) <= 4:
            if re.search(r"(?<![A-Za-z])" + re.escape(a) + r"(?![A-Za-z])", t):
                return True
        elif re.search(r"(?<![A-Za-z])" + re.escape(a) + r"(?![A-Za-z])", t, re.I):
            return True
    return False


def opponents_from_rows(rows, teams):
    """{club: [opponent names in fixture order]} from the stack's per-player rows (team,
    opponent_team id); a double gameweek gives two opponents, a blank gives no entry."""
    names = {int(t["id"]): t["name"] for t in (teams or []) if "id" in t}
    out = {}
    for r in rows or []:
        club = r.get("team")
        try:
            opp = names.get(int(r.get("opponent_team")))
        except (TypeError, ValueError):
            opp = None
        if not club or not opp:
            continue
        lst = out.setdefault(club, [])
        if opp not in lst:
            lst.append(opp)
    return out


def fixture_rows_for_gw(gw, season):
    """The stack rows for one gameweek: the FPL-API history when the gameweek is in it, else
    the forward skeleton. Only team / opponent_team / GW are read."""
    import pandas as pd
    tag = season.replace("-", "_")
    for name in (f"fpl_api_{tag}.parquet", f"forward_skeleton_{tag}.parquet"):
        path = REPO / "data" / "history" / name
        if not path.exists():
            continue
        df = pd.read_parquet(path, columns=["team", "opponent_team", "GW"])
        df = df[df["GW"].astype(int) == int(gw)]
        if len(df):
            return df.drop_duplicates(["team", "opponent_team"]).to_dict("records")
    return []


_JSONLD = re.compile(r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', re.I | re.S)
_TIME = re.compile(r'<time[^>]+datetime=["\']([^"\']+)["\']', re.I)


def hidden_date(html):
    """(published datetime UTC, 'jsonld' | 'time') from the page, or (None, None). JSON-LD
    datePublished first (walking @graph and lists), then the first <time datetime>."""
    if not html:
        return None, None
    for m in _JSONLD.finditer(html):
        try:
            obj = json.loads(m.group(1).strip())
        except ValueError:
            continue
        stack = [obj]
        while stack:
            o = stack.pop(0)
            if isinstance(o, dict):
                d = parse_iso(o.get("datePublished")) if o.get("datePublished") else None
                if d:
                    return d, "jsonld"
                stack.extend(v for v in o.values() if isinstance(v, (dict, list)))
            elif isinstance(o, list):
                stack.extend(o)
    m = _TIME.search(html)
    if m:
        d = parse_iso(m.group(1))
        if d:
            return d, "time"
    return None, None


_DATELINES = [
    re.compile(r"\b(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)[a-z]*,?\s+(\d{1,2})\s+([A-Za-z]{3,9})\s+(20\d{2})\b"),
    re.compile(r"\b(\d{1,2})\s+([A-Za-z]{3,9})\s+(20\d{2})\b"),
    re.compile(r"\b([A-Za-z]{3,9})\s+(\d{1,2}),?\s+(20\d{2})\b"),
    re.compile(r"\b(20\d{2})-(\d{2})-(\d{2})\b"),
]


def _dateline_to_date(m, pattern_index):
    g = m.groups()
    try:
        if pattern_index == 3:
            return date(int(g[0]), int(g[1]), int(g[2]))
        if pattern_index == 2:
            mon, day, year = g
        else:
            day, mon, year = g
        mo = MONTHS.get(mon.lower())
        return date(int(year), mo, int(day)) if mo else None
    except ValueError:
        return None


def page_date(body, fetched_at):
    """A dateline WITH a four-digit year in the first five non-empty lines of the cleaned body,
    at or before fetched_at; prose dates further down are not datelines."""
    lines = [l.strip() for l in (body or "").splitlines() if l.strip()][:5]
    for line in lines:
        for i, pat in enumerate(_DATELINES):
            for m in pat.finditer(line):
                d = _dateline_to_date(m, i)
                if d:
                    dt = datetime(d.year, d.month, d.day, tzinfo=timezone.utc)
                    if dt <= fetched_at:
                        return dt
    return None


def best_date(meta_dt, url, body, fetched_at):
    """First hit wins: meta > url > page > first_seen. A date after fetched_at is rejected at
    every level and the chain falls through."""
    if meta_dt is not None and meta_dt <= fetched_at:
        return meta_dt, "meta"
    d = url_date(url)
    if d:
        dt = datetime(d.year, d.month, d.day, tzinfo=timezone.utc)
        if dt <= fetched_at:
            return dt, "url"
    pdt = page_date(body, fetched_at)
    if pdt is not None:
        return pdt, "page"
    return None, "first_seen"


def guard(text, best_dt, window, opponents, aliases):
    """KEEP if the best date's DAY lies inside the window; KEEP if undated and the text names
    one of the club's opponents this gameweek (a double accepts either); else DROP."""
    if best_dt is not None:
        inside = window[0].date() <= best_dt.date() <= window[1].date()
        return inside, "dated inside window" if inside else "dated outside window"
    if any(names_team(text, o, aliases) for o in (opponents or [])):
        return True, "undated, opponent named"
    return False, "undated, opponent not named"


class PageFetcher:
    """One GET per URL with the honest User-Agent, at most one request per second. A 403 or
    any error returns an empty page and is never retried with another agent."""
    def __init__(self, delay=1.0):
        self.delay, self._last, self.requests = delay, 0.0, 0
        try:
            import certifi
            self._ctx = ssl.create_default_context(cafile=certifi.where())
        except ImportError:
            self._ctx = ssl.create_default_context()

    def get(self, url):
        wait = self.delay - (time.time() - self._last)
        if wait > 0:
            time.sleep(wait)
        self._last = time.time()
        self.requests += 1
        req = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html,*/*;q=0.8", "Accept-Encoding": "identity"})
        try:
            with urlopen(req, timeout=30, context=self._ctx) as r:
                return r.status, r.geturl(), r.read(2_000_000).decode("utf-8", "replace")
        except HTTPError as e:
            return e.code, url, ""
        except Exception:                                    # noqa: BLE001 -- a page fetch never fails a run
            return None, url, ""


def _page_name(guid):
    import hashlib
    return hashlib.sha1(guid.encode("utf-8")).hexdigest() + ".json.gz"


def _load_gz(path):
    return json.loads(gzip.decompress(Path(path).read_bytes()).decode("utf-8"))


class ReplayTavily:
    """Serves saved search and extract responses from a raw directory. No key, no network."""
    network = 0

    def __init__(self, raw_dir):
        self.raw_dir = Path(raw_dir)
        self.searches, self.pool = {}, {}
        for f in sorted(self.raw_dir.glob("*.search.json.gz")):
            d = _load_gz(f)
            req = d.get("request") or {}
            self.searches[(req.get("query"), tuple(req.get("include_domains") or ()))] = d.get("response") or {}
        for f in sorted(self.raw_dir.glob("*.extract.json.gz")):
            for r in (_load_gz(f).get("response") or {}).get("results", []):
                if r.get("url"):
                    self.pool[r["url"]] = r
                    self.pool.setdefault(canonical_guid(r["url"]), r)

    def search(self, query, domain, start_date=None, end_date=None):
        domains = tuple([domain] if isinstance(domain, str) else domain)
        return self.searches.get((query, domains), {"results": []})

    def extract(self, urls):
        got = [self.pool[u] if u in self.pool else self.pool.get(canonical_guid(u)) for u in urls]
        return {"results": [g for g in got if g], "failed_results": [u for u, g in zip(urls, got) if not g]}


class ReplayHttp:
    """Serves saved pages from <raw_dir>/pages; a page never saved is an empty page."""
    def __init__(self, raw_dir):
        self.dir, self.requests, self.lookups = Path(raw_dir) / "pages", 0, 0

    def get(self, url):
        self.lookups += 1
        p = self.dir / _page_name(canonical_guid(url))
        if not p.exists():
            return None, url, ""
        rec = _load_gz(p)
        return rec.get("status"), rec.get("final_url") or url, rec.get("html") or ""


# ---- the run ------------------------------------------------------------------------------

def run(conn, clubs, tavily, now=None, seed=False, raw_dir=None, log=print,
        http=None, window=None, opponents=None, aliases=None, replay=False):
    """One pass over `clubs` ({team name: domain}). With `window` (the gate's
    [deadline - 3 days, deadline]) the v2 path runs: dated search, one page GET per new kept
    URL, the date chain, the old-article guard, then Extract. Without it the v1 path runs
    (generic query, no guard). `replay` serves everything from saved files: no ledger rows,
    no credits, no network. Returns the summary it logs; raises CreditLimit before any call."""
    now = now or datetime.now(timezone.utc)
    raw_dir = Path(raw_dir or RAW_DIR)
    ns.ensure_schema(conn)
    planned = len(clubs) * SEARCH_CREDITS + extract_credits(MAX_RESULTS * len(clubs))   # worst case: every result new
    if replay:
        log("replay: serving saved raw files; no Tavily calls, no HTTP requests, no ledger rows")
    else:
        try:
            used = credit_guard(conn, planned, now)
        except CreditLimit as e:
            conn.rollback()
            log(f"credit guard REFUSED: {e}")
            raise
        conn.commit()
        log(f"credit guard: {used} recorded for {now:%Y-%m}, {planned} planned (worst case), limit {TAVILY_MONTHLY_LIMIT}")
    v2 = window is not None
    aliases = aliases or team_aliases()
    opponents = opponents or {}
    seen = existing_guids(conn)
    stamp = f"{now:%Y%m%dT%H%M%SZ}"
    summary = {"clubs": {}, "dropped": [], "credits": 0, "new": 0, "already_seen": 0, "extracted": 0,
               "seed": seed, "replay": replay, "window": window}
    pending, queued = [], set()
    for club, domain in clubs.items():
        query = QUERY.format(club=club)
        if v2:
            resp = tavily.search(query, domain, f"{window[0]:%Y-%m-%d}", f"{now:%Y-%m-%d}")
            request = search_request(query, [domain], f"{window[0]:%Y-%m-%d}", f"{now:%Y-%m-%d}")
        else:
            resp = tavily.search(query, domain)
            request = search_request(query, [domain])
        results = resp.get("results", []) if isinstance(resp, dict) else []
        if not replay:
            record_call(conn, "search", club, query, len(results), SEARCH_CREDITS, now)
            summary["credits"] += SEARCH_CREDITS
            save_raw(raw_dir, f"{stamp}_{domain}.search.json.gz",
                     {"request": request, "fetched_at": now.isoformat(), "club": club, "response": resp})
        kept, dropped = filter_results(results, domain)
        new, already = 0, 0
        for r in kept:
            g = canonical_guid(r["url"])
            if g in seen or g in queued:
                already += 1
                continue
            queued.add(g)
            pending.append((club, domain, r, g))
            new += 1
        summary["clubs"][club] = {"results": len(results), "kept": len(kept), "dropped": list(dropped), "new": new,
                                  "already_seen": already, "extracted": 0, "extract_failed": 0,
                                  "guard_dropped": 0, "credits": 0 if replay else SEARCH_CREDITS}
        summary["dropped"] += [(club, u, why) for u, why in dropped]
        summary["new"] += new
        summary["already_seen"] += already
        for u, why in dropped:
            log(f"  dropped [{club}] {why}: {u}")
        log(f"{club}: results {len(results)}, kept {len(kept)}, dropped {len(dropped)}, new {new}, already seen {already}")

    # v2: the page fetch, the date chain on what is known before Extract, the guard
    meta = {}
    if v2 and pending:
        passing = []
        for club, domain, r, g in pending:
            status, final, html = http.get(r["url"]) if http is not None else (None, r["url"], "")
            if not replay and http is not None:
                save_raw(raw_dir / "pages", _page_name(g),
                         {"url": r["url"], "guid": g, "final_url": final, "status": status, "fetched_at": now.isoformat(), "html": html})
            mdt, tag = hidden_date(html)
            meta[g] = (mdt, tag, status)
            # the search snippet is Markdown-ish with the same menu residue as the page: clean it
            # first, so a dateline lands in the first lines exactly as it does in the stored body
            snippet = clean_markdown(f"{r.get('title') or ''}\n{r.get('content') or ''}")
            bdt, _src = best_date(mdt, r["url"], snippet, now)
            keep, why = guard(snippet, bdt, window, opponents.get(club, []), aliases)
            if keep:
                passing.append((club, domain, r, g))
            else:
                summary["clubs"][club]["guard_dropped"] += 1
                summary["dropped"].append((club, r["url"], why))
                log(f"  dropped [{club}] {why}: {r['url']}")
        pending = passing

    for i in range(0, len(pending), EXTRACT_BATCH):
        batch = pending[i:i + EXTRACT_BATCH]
        urls = [p[2]["url"] for p in batch]
        resp = tavily.extract(urls)
        got_list = resp.get("results", []) if isinstance(resp, dict) else []
        credits = 0 if replay else extract_credits(len(urls))
        raw_ref = None
        if not replay:
            record_call(conn, "extract", None, None, len(got_list), credits, now)
            summary["credits"] += credits
            path = save_raw(raw_dir, f"{stamp}_{i // EXTRACT_BATCH + 1}.extract.json.gz",
                            {"urls": urls, "fetched_at": now.isoformat(), "response": resp})
            raw_ref = ns.raw_ref_for(path)
        got = {r.get("url"): r for r in got_list}
        by_guid = {canonical_guid(u): r for u, r in got.items() if u}
        cands = []
        for club, domain, r, g in batch:
            er = got.get(r["url"]) or by_guid.get(g)
            if er is None:
                summary["clubs"][club]["extract_failed"] += 1
                log(f"  extract FAILED [{club}]: {r['url']}")
                continue
            body = clean_markdown(er.get("raw_content") or "")
            headline = trim_headline(r.get("title") or er.get("title") or "") or g
            if v2:
                mdt = meta.get(g, (None, None, None))[0]
                dt, src = best_date(mdt, r["url"], body, now)
                if src == "first_seen" and seed:
                    src = "backlog"
            else:
                d = url_date(r["url"])
                dt = datetime(d.year, d.month, d.day, tzinfo=timezone.utc) if d else None
                src = "backlog" if seed else ("url" if d else "first_seen")
            cands.append({"guid": g, "url": r["url"], "headline": headline, "body": body, "published_at": dt,
                          "fetched_at": now, "raw_ref": raw_ref or f"replay:{raw_dir.name}",
                          "content_hash": ns.content_hash(headline, body), "club": club, "date_source": src})
            summary["clubs"][club]["extracted"] += 1
        ns.upsert_versions(conn, "club", cands)
        summary["extracted"] += len(cands)
        log(f"extract batch {i // EXTRACT_BATCH + 1}: {len(urls)} urls, {len(cands)} stored, {credits} credits")
    log(f"run total: credits {summary['credits']}, new {summary['new']}, already seen {summary['already_seen']}, "
        f"extracted {summary['extracted']}, dropped {len(summary['dropped'])}, seed={seed}, replay={replay}")
    return summary
