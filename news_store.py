"""News ingestion v1 (2026-09-25): BBC Premier League RSS and FPL availability news into
Postgres, ONE ROW PER VERSION of an item, plus the view that builds the exact text a later
embedding layer will see. No embedding, no pgvector, no relevance filter here.

"Team news" = whether a Premier League player is available for the next gameweek.

TABLE news_items (DDL below; the db_write.py pattern: idempotent CREATE ... IF NOT EXISTS
run by ensure_schema() on every connect, no migration tool exists in this repo):
  * (source, guid, version) is THE unique key. The versioning rule (bug 1, 2026-09-25): a
    candidate becomes a new version iff its content_hash differs from the LATEST stored
    version of that guid -- never "from every version". So the same raw input twice
    changes nothing (identical to the latest -> skipped), a new guid is v1, a change is
    v(n+1), and a flag that goes d -> cleared -> d with identical text is v1, v2, v3 with
    v3 ACTIVE. The first cut had UNIQUE (source, guid, content_hash) and lost exactly that
    re-flag; the constraint is dropped by the DDL on existing tables.
  * fetched_at is indexed for the as-of reads.

BBC: guid = <guid> text, falling back to the canonical <link>; content_hash over
(headline, body); published_at = pubDate as UTC (RFC 822 numeric offsets and the named
zones in NAMED_ZONES -- an unknown zone is an ERROR, never a guess); fetched_at = the
fetch time; raw_ref = the gzipped response saved BEFORE parsing (raw first). Fetches are
conditional (ETag / Last-Modified from the previous 200); a 304 stores nothing and writes
no file. The User-Agent names the project and the repo; it never impersonates a browser.

FPL: derived from the raw bootstrap-static archive (data/live/bootstrap_raw/<season>/,
every origin: poller polls, build fetches, news fetches), chronologically. guid
'fpl:<element_id>'; content_hash over (status, news, chance_of_playing_NEXT_round) -- the
chance column IS next_round (bug 2, 2026-09-25): measured over the server archive, the
news text's "<N>% chance" equals next_round in 819 of 819 rows and this_round alone in
none; this_round is the round already under way, next_round the deadline gameweek a
manager is picking for;
headline '<web_name> (<team short name>, <position>)'; published_at = news_added;
fetched_at = the snapshot time; raw_ref = the archive path of the snapshot. A player is
"flagged" when the news string is non-empty or the status is not 'a'. A CLEARED flag is a
new version with an empty body, the status and chance as reported, published_at NULL
(FPL does not bump news_added when it clears a flag, so its claim would be stale) and
fetched_at = the FIRST snapshot where the news was gone.

Raw RSS files live under data/news/raw/<source>/ -- on the model-data volume OUTSIDE
data/live/, so the off-site backup (eval/backup_b2.py, which excludes only live/) carries
them. The FPL raw_ref points into data/live/bootstrap_raw/, which the backup does NOT
carry (KNOWN_ISSUES #26).
"""
import gzip
import hashlib
import html
import json
import os
import re
import tempfile
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_tz
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

REPO = Path(__file__).resolve().parent
RAW_DIR = REPO / "data" / "news" / "raw"
USER_AGENT = "fpl-copilot news ingest (+https://github.com/veer64/fpl-copilot)"
BBC_URL = "https://feeds.bbci.co.uk/sport/football/premier-league/rss.xml"
SOURCES = ("bbc", "fpl", "club")
STATUS_WORDS = {"a": "available", "d": "doubtful", "i": "injured", "s": "suspended",
                "u": "unavailable", "n": "not in squad"}
# RFC 822 named zones that feeds actually use. email.utils knows GMT/UT/UTC/Z and the US
# zones; BST (what Sky Sports stamps) it does not. Anything else is an error, not a guess.
NAMED_ZONES = {"GMT": 0, "UT": 0, "UTC": 0, "Z": 0, "BST": 3600, "IST": 3600, "WET": 0, "WEST": 3600,
               "CET": 3600, "CEST": 7200, "EET": 7200, "EEST": 10800,
               "EST": -18000, "EDT": -14400, "CST": -21600, "CDT": -18000,
               "MST": -25200, "MDT": -21600, "PST": -28800, "PDT": -25200}

DDL = """
CREATE TABLE IF NOT EXISTS news_items (
    id            BIGSERIAL PRIMARY KEY,
    source        TEXT NOT NULL CHECK (source IN ('bbc', 'fpl', 'club')),
    guid          TEXT NOT NULL,
    version       INT  NOT NULL CHECK (version >= 1),
    url           TEXT,
    headline      TEXT NOT NULL,
    body          TEXT NOT NULL DEFAULT '',
    published_at  TIMESTAMPTZ,                      -- the source's claim, UTC; NULL when it has none
    fetched_at    TIMESTAMPTZ NOT NULL,             -- when WE observed this version
    content_hash  TEXT NOT NULL,
    raw_ref       TEXT NOT NULL,                    -- the raw file this version was parsed from
    element_id    INT,                              -- fpl only
    status        TEXT,                             -- fpl only
    chance        INT,                              -- fpl only: chance_of_playing_NEXT_round
    inserted_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
-- the first cut's hash-unique constraint (dropped 2026-09-25, bug 1): a re-flag after a clear
-- repeats an earlier version's hash and must be stored
ALTER TABLE news_items DROP CONSTRAINT IF EXISTS news_items_source_guid_content_hash_key;
CREATE UNIQUE INDEX IF NOT EXISTS ux_news_items_version ON news_items (source, guid, version);
CREATE INDEX IF NOT EXISTS ix_news_items_fetched ON news_items (fetched_at);
-- 2026-09-25, club news: a third source, the club the row belongs to, and HOW the row is dated:
--   'feed' (RSS pubDate), 'source_field' (FPL news_added), 'url' (a day-level date in the URL),
--   'first_seen' (no claim; fetched_at is the only time), 'backlog' (seeded history, date unknown)
ALTER TABLE news_items DROP CONSTRAINT IF EXISTS news_items_source_check;
ALTER TABLE news_items ADD CONSTRAINT news_items_source_check CHECK (source IN ('bbc', 'fpl', 'club'));
ALTER TABLE news_items ADD COLUMN IF NOT EXISTS club        TEXT;
ALTER TABLE news_items ADD COLUMN IF NOT EXISTS date_source TEXT;
UPDATE news_items SET date_source = CASE
    WHEN source = 'bbc' THEN 'feed'
    WHEN source = 'fpl' AND published_at IS NOT NULL THEN 'source_field'
    WHEN source = 'fpl' THEN 'first_seen'
    END
WHERE date_source IS NULL AND source IN ('bbc', 'fpl');
CREATE INDEX IF NOT EXISTS ix_news_items_club ON news_items (club) WHERE club IS NOT NULL;
-- body_source (2026-09-28, KNOWN_ISSUES #27): where a club row's body came from -- 'tavily_extract' or, when
-- the extract was only a link list, the page we fetched: 'page_jsonld' | 'page_embedded' | 'page_html'.
-- Existing club rows were all extracts; bbc / fpl rows are not Tavily and stay NULL.
ALTER TABLE news_items ADD COLUMN IF NOT EXISTS body_source TEXT;
UPDATE news_items SET body_source = 'tavily_extract' WHERE source = 'club' AND body_source IS NULL;

-- every Tavily call, with the credits it cost by Tavily's published rule (club_news.py's
-- credit guard sums this month's rows before any call)
CREATE TABLE IF NOT EXISTS tavily_calls (
    id         BIGSERIAL PRIMARY KEY,
    called_at  TIMESTAMPTZ NOT NULL,
    endpoint   TEXT NOT NULL,                       -- 'search' | 'extract'
    club       TEXT,
    query      TEXT,
    n_results  INT,
    credits    INT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_tavily_calls_at ON tavily_calls (called_at);

-- The exact chunk string the embedding layer will see (2026-09-25 spec):
--   RSS: "[BBC Sport | YYYY-MM-DD HH:MMZ] <headline>\\n<body>"
--   FPL: "[FPL official | published_at, or fetched_at if null] <headline>\\n
--         Status: <word>. <chance>% chance of playing. <news>"   (chance sentence omitted when null;
--         a cleared version reads "Status: available. No injury news (flag cleared).")
--   club: "[<Club> official site | published_at as YYYY-MM-DD, or 'first seen <fetched_at date>',
--          or 'date unknown (backlog)'] <headline>\\n<body>"
CREATE OR REPLACE VIEW news_embed_text AS
SELECT id, source, guid, version, fetched_at, embed_text, length(embed_text) AS char_count
FROM (
    SELECT id, source, guid, version, fetched_at,
        CASE source
            WHEN 'bbc' THEN
                '[BBC Sport | ' || to_char(COALESCE(published_at, fetched_at) AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI')
                || 'Z] ' || headline || E'\\n' || body
            WHEN 'fpl' THEN
                '[FPL official | ' || to_char(COALESCE(published_at, fetched_at) AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI')
                || 'Z] ' || headline || E'\\n'
                || CASE
                     WHEN body = '' AND status = 'a' THEN 'Status: available. No injury news (flag cleared).'
                     ELSE rtrim('Status: '
                          || CASE status WHEN 'a' THEN 'available' WHEN 'd' THEN 'doubtful' WHEN 'i' THEN 'injured'
                                         WHEN 's' THEN 'suspended' WHEN 'u' THEN 'unavailable' WHEN 'n' THEN 'not in squad'
                                         ELSE COALESCE(status, 'unknown') END
                          || '.'
                          || CASE WHEN chance IS NOT NULL THEN ' ' || chance::text || '% chance of playing.' ELSE '' END
                          || ' ' || body)
                   END
            WHEN 'club' THEN
                '[' || COALESCE(club, 'Club') || ' official site | '
                || CASE
                     WHEN published_at IS NOT NULL THEN to_char(published_at AT TIME ZONE 'UTC', 'YYYY-MM-DD')
                     WHEN date_source = 'backlog' THEN 'date unknown (backlog)'
                     ELSE 'first seen ' || to_char(fetched_at AT TIME ZONE 'UTC', 'YYYY-MM-DD')
                   END
                || '] ' || headline || E'\\n' || body
        END AS embed_text
    FROM news_items
) t;

-- ---- the relevance filter (relevance.py, 2026-09-26) ----------------------------------------
-- One verdict per (news_items row, prompt version, MODEL), append-only: a new PROMPT_VERSION or
-- another model judges everything again beside the old rows. stage: 'skipped' (fpl: trusted,
-- no LLM), 'keyword' (stage 1 said NO: no player or club named), 'llm' (the model's answer).
-- current is NULL for a keyword verdict (nobody judged it); players is what the LLM named.
-- model is the model the run was made under, also on skipped / keyword rows, so every
-- (prompt version, model) pair covers every item.
CREATE TABLE IF NOT EXISTS news_relevance (
    id              BIGSERIAL PRIMARY KEY,
    news_item_id    BIGINT NOT NULL REFERENCES news_items (id) ON DELETE CASCADE,
    prompt_version  TEXT NOT NULL,
    stage           TEXT NOT NULL CHECK (stage IN ('skipped', 'keyword', 'llm')),
    relevant        BOOLEAN NOT NULL,
    current         BOOLEAN,
    players         TEXT[] NOT NULL DEFAULT '{}',
    reason          TEXT NOT NULL,
    model           TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
-- migration of the first cut (key without model; skipped / keyword rows had NULL model): every
-- relevance_v1 row came from the Haiku run of 2026-09-26
UPDATE news_relevance SET model = 'claude-haiku-4-5-20251001' WHERE model IS NULL;
ALTER TABLE news_relevance ALTER COLUMN model SET NOT NULL;
ALTER TABLE news_relevance DROP CONSTRAINT IF EXISTS news_relevance_news_item_id_prompt_version_key;
CREATE UNIQUE INDEX IF NOT EXISTS ux_news_relevance_item_prompt_model ON news_relevance (news_item_id, prompt_version, model);

-- the production choice (one row), written by ensure_schema from config_roles.PROMPT_VERSION and
-- RELEVANCE_MODEL; news_to_embed reads it so the view needs no literals
CREATE TABLE IF NOT EXISTS relevance_production (
    one             BOOLEAN PRIMARY KEY DEFAULT TRUE CHECK (one),
    prompt_version  TEXT NOT NULL,
    model           TEXT NOT NULL,
    set_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- every LLM attempt (llm.py), one row per HTTP attempt including the retried ones
CREATE TABLE IF NOT EXISTS llm_calls (
    id             BIGSERIAL PRIMARY KEY,
    called_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    purpose        TEXT NOT NULL,
    model          TEXT NOT NULL,
    input_tokens   INT,
    output_tokens  INT,
    ok             BOOLEAN NOT NULL,
    error          TEXT
);
CREATE INDEX IF NOT EXISTS ix_llm_calls_at ON llm_calls (called_at);
-- whether the request carried temperature (config MODELS_WITHOUT_TEMPERATURE); NULL on rows older than the column
ALTER TABLE llm_calls ADD COLUMN IF NOT EXISTS temperature_sent BOOLEAN;
-- the reply as the API described it (ruling 2026-09-27): stop_reason ('end_turn', 'max_tokens', ...),
-- the content block types in order (e.g. {thinking,text}), and the characters of thinking vs text --
-- the API reports no token split, so the thinking share is measured in characters. A reply that
-- stopped at max_tokens carries error 'truncated' (the request itself was ok).
ALTER TABLE llm_calls ADD COLUMN IF NOT EXISTS stop_reason TEXT;
ALTER TABLE llm_calls ADD COLUMN IF NOT EXISTS content_block_types TEXT[];
ALTER TABLE llm_calls ADD COLUMN IF NOT EXISTS thinking_chars INT;
ALTER TABLE llm_calls ADD COLUMN IF NOT EXISTS text_chars INT;
-- which item and prompt version a call was for (ruling 2026-09-27: refusals are per item, so the
-- run loop skips an item the API refused twice under the same model and prompt version)
ALTER TABLE llm_calls ADD COLUMN IF NOT EXISTS news_item_id BIGINT;
ALTER TABLE llm_calls ADD COLUMN IF NOT EXISTS prompt_version TEXT;
CREATE INDEX IF NOT EXISTS ix_llm_calls_item ON llm_calls (news_item_id, model, prompt_version) WHERE news_item_id IS NOT NULL;

-- every Voyage embedding request (embeddings.py), one row per HTTP attempt: purpose, model, the
-- input_type sent (kind), how many texts, the API's usage.total_tokens, ok, and the error text
CREATE TABLE IF NOT EXISTS embedding_calls (
    id         BIGSERIAL PRIMARY KEY,
    called_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    purpose    TEXT NOT NULL,
    model      TEXT NOT NULL,
    kind       TEXT NOT NULL,                       -- 'document' | 'query'
    n_texts    INT NOT NULL,
    tokens     INT,
    ok         BOOLEAN NOT NULL,
    error      TEXT
);
CREATE INDEX IF NOT EXISTS ix_embedding_calls_at ON embedding_calls (called_at);

-- player_ids (2026-09-30, Piece 7): the verdict's players list mapped to FPL element ids by code
-- (player_names.py, the squad as of the item's fetched_at, the article's club as context); FPL rows
-- carry their element_id. NULL = not mapped yet (eval/backfill_player_ids.py); [] = nothing mapped.
ALTER TABLE news_relevance ADD COLUMN IF NOT EXISTS player_ids INT[];

-- every search_news call (news_search.py): what was asked, what was resolved, the fused candidates
-- with their scores, what was returned, and the timings
CREATE TABLE IF NOT EXISTS search_log (
    id            BIGSERIAL PRIMARY KEY,
    called_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    query         TEXT NOT NULL,
    players       TEXT[],
    clubs         TEXT[],
    resolved_ids  INT[],
    as_of         TIMESTAMPTZ,
    search_mode   TEXT,
    candidates    JSONB,
    returned_ids  INT[],
    embed_ms      INT,
    sql_ms        INT,
    total_ms      INT,
    error         TEXT
);
CREATE INDEX IF NOT EXISTS ix_search_log_at ON search_log (called_at);

-- the citation check after every agent reply (agent.py, Part 5, log only): the c<id> ids the reply
-- cites, the ids search_news returned in that turn, and the cited ids that were not returned
CREATE TABLE IF NOT EXISTS citation_checks (
    id          BIGSERIAL PRIMARY KEY,
    checked_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    turn_id     TEXT NOT NULL,
    cited       TEXT[],
    returned    TEXT[],
    violations  TEXT[]
);

-- the numeric grounding check after every agent reply (agent.py + numeric_grounding.py, 2026-10-02, LOG ONLY):
-- how many numbers the raw reply states, how many are found among this turn's user messages and tool results
-- (as themselves, x100 or /10, rounded to the claim's decimals), the ungrounded ones [{text, value, context}],
-- and `error` when the checker itself raised. The same turn_id as citation_checks. The reply is never altered.
CREATE TABLE IF NOT EXISTS numeric_checks (
    id             BIGSERIAL PRIMARY KEY,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    turn_id        TEXT NOT NULL,
    numbers_found  INT,
    grounded       INT,
    ungrounded     JSONB,
    notebook_size  INT,
    error          TEXT
);

-- Piece 9 (2026-10-01), record and measure only (D9): one structured availability claim per player per
-- club / bbc article (extraction.py, prompt extract_v1, the production judge model). Append-only; the
-- evidence phrase lives here and never in git.
CREATE TABLE IF NOT EXISTS availability_claims (
    id                 BIGSERIAL PRIMARY KEY,
    news_item_id       BIGINT NOT NULL REFERENCES news_items (id),
    element_id         INT NOT NULL,
    status             TEXT NOT NULL CHECK (status IN ('out', 'suspended', 'doubtful', 'returning', 'available')),
    return_hint        TEXT,
    basis              TEXT NOT NULL CHECK (basis IN ('manager_quote', 'club_statement', 'report')),
    evidence           TEXT NOT NULL,
    prompt_version     TEXT NOT NULL,
    model              TEXT NOT NULL,
    item_fetched_at    TIMESTAMPTZ NOT NULL,
    item_published_at  TIMESTAMPTZ,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (news_item_id, element_id, prompt_version, model)
);
CREATE INDEX IF NOT EXISTS ix_availability_claims_element ON availability_claims (element_id, item_fetched_at);
-- the items already extracted under (prompt_version, model), with their claim count, so an item whose
-- reply had no claims is never sent again
CREATE TABLE IF NOT EXISTS availability_extractions (
    id              BIGSERIAL PRIMARY KEY,
    news_item_id    BIGINT NOT NULL REFERENCES news_items (id),
    prompt_version  TEXT NOT NULL,
    model           TEXT NOT NULL,
    n_claims        INT NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (news_item_id, prompt_version, model)
);
-- the conflict log (conflict_log.py): club claim vs FPL's flag as of each deadline, the outcome from the
-- repo's results data, and who was right
CREATE TABLE IF NOT EXISTS availability_comparisons (
    id                     BIGSERIAL PRIMARY KEY,
    gw                     INT NOT NULL,
    deadline               TIMESTAMPTZ NOT NULL,
    element_id             INT NOT NULL,
    fpl_status             TEXT,
    fpl_chance_next_round  INT,
    fpl_snapshot_time      TIMESTAMPTZ NOT NULL,
    claim_id               BIGINT NOT NULL REFERENCES availability_claims (id),
    club_status            TEXT NOT NULL,
    claim_published_at     TIMESTAMPTZ,
    claim_fetched_at       TIMESTAMPTZ NOT NULL,
    bucket_fpl             TEXT,
    bucket_club            TEXT NOT NULL,
    agree                  BOOLEAN,
    minutes                INT,
    started                BOOLEAN,
    played                 BOOLEAN,
    outcome_filled_at      TIMESTAMPTZ,
    right_source           TEXT CHECK (right_source IN ('fpl', 'club', 'tie')),
    created_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (gw, element_id)
);

-- per-gameweek build record of the conflict log (Part A, 2026-10-01): update_conflict_log rebuilds a
-- gameweek whenever a claim inside its window was created after built_at; otherwise it leaves it alone
CREATE TABLE IF NOT EXISTS availability_builds (
    gw        INT PRIMARY KEY,
    deadline  TIMESTAMPTZ NOT NULL,
    built_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    n_rows    INT NOT NULL
);

-- What the embedding layer should take: every news_embed_text row whose verdict under the
-- PRODUCTION prompt version and model says relevant, and not known to be stale (current IS NOT
-- false). fpl rows carry a 'skipped' verdict (relevant, current) so they pass; rows without a
-- production verdict yet are absent; other models' and reference verdicts never count. A version
-- superseded by a PARSE CORRECTION (a later version of the same guid with body_source page_jsonld /
-- page_embedded / page_html, 2026-09-28) is out: its body was never the article. A later version
-- that is a normal content change (tavily_extract) supersedes nothing here; each version stands.
CREATE OR REPLACE VIEW news_to_embed AS
SELECT e.id, e.source, e.guid, e.version, e.fetched_at, e.embed_text, e.char_count,
       v.relevant, v.current, v.players, v.stage, v.prompt_version, v.model
FROM news_embed_text e
JOIN relevance_production p ON TRUE
JOIN news_relevance v ON v.news_item_id = e.id AND v.prompt_version = p.prompt_version AND v.model = p.model
WHERE v.relevant AND v.current IS NOT FALSE
  AND NOT EXISTS (SELECT 1 FROM news_items n2 WHERE n2.source = e.source AND n2.guid = e.guid AND n2.version > e.version
                  AND n2.body_source IN ('page_jsonld', 'page_embedded', 'page_html'));
"""


# The chunk store (2026-09-30, embed_pipeline.py): one row per chunk of a news_to_embed item, with its
# vector and its keyword vector. Created ONLY when the vector extension is installed in this database
# (CREATE EXTENSION vector is a by-hand step on the pgvector image; ensure_schema never creates it):
# without it there is no table and the embed step logs "pgvector not installed, embedding skipped".
# The dimension is config EMBED_DIM. UNIQUE on (item, index, chunker version, model): a new chunker or
# model re-chunks beside the old rows. No vector index (exact scan; about 10k rows a season).
# tsv: to_tsvector('fpl_english', chunk_text) set in the INSERT -- unaccent is not IMMUTABLE, so it
# cannot be a generated column. fpl_english = the english configuration with unaccent in front of
# the stemmer, so "odegaard" matches "Ødegaard"; GIN index on tsv.
CHUNKS_DDL = """
CREATE EXTENSION IF NOT EXISTS unaccent;
CREATE TABLE IF NOT EXISTS news_chunks (
    id               BIGSERIAL PRIMARY KEY,
    news_item_id     BIGINT NOT NULL REFERENCES news_items (id),
    chunk_index      INT NOT NULL,
    chunker_version  TEXT NOT NULL,
    embed_model      TEXT NOT NULL,
    chunk_text       TEXT NOT NULL,
    char_count       INT NOT NULL,
    embedding        vector({dim}) NOT NULL,
    tsv              tsvector NOT NULL,
    embedded_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (news_item_id, chunk_index, chunker_version, embed_model)
);
CREATE INDEX IF NOT EXISTS ix_news_chunks_tsv ON news_chunks USING gin (tsv);
CREATE INDEX IF NOT EXISTS ix_news_chunks_item ON news_chunks (news_item_id, chunker_version, embed_model);
"""
FPL_ENGLISH_DDL = """
CREATE TEXT SEARCH CONFIGURATION fpl_english (COPY = english);
ALTER TEXT SEARCH CONFIGURATION fpl_english ALTER MAPPING FOR hword, hword_part, word WITH unaccent, english_stem;
"""


def vector_installed(conn):
    """True when the pgvector extension is created in this database (pg_extension), the guard
    for news_chunks and the embed step."""
    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM pg_extension WHERE extname = 'vector'")
        return cur.fetchone() is not None


def ensure_schema(conn):
    import config_roles
    with conn.cursor() as cur:
        cur.execute(DDL)
        cur.execute("INSERT INTO relevance_production (one, prompt_version, model) VALUES (TRUE, %s, %s) "
                    "ON CONFLICT (one) DO UPDATE SET prompt_version = EXCLUDED.prompt_version, model = EXCLUDED.model, set_at = now() "
                    "WHERE relevance_production.prompt_version <> EXCLUDED.prompt_version OR relevance_production.model <> EXCLUDED.model",
                    (config_roles.PROMPT_VERSION, config_roles.RELEVANCE_MODEL))
        if vector_installed(conn):
            cur.execute(CHUNKS_DDL.format(dim=config_roles.EMBED_DIM))
            cur.execute("SELECT 1 FROM pg_ts_config WHERE cfgname = 'fpl_english'")
            if cur.fetchone() is None:
                cur.execute(FPL_ENGLISH_DDL)
    conn.commit()


# ---- pure helpers -----------------------------------------------------------------------

def content_hash(*parts):
    """sha256 over the parts, None and '' distinct from each other only by position, never
    by absence: every part is always present, joined by a unit separator."""
    h = hashlib.sha256()
    for p in parts:
        h.update(("" if p is None else str(p)).encode("utf-8"))
        h.update(b"\x1f")
    return h.hexdigest()


def parse_rfc822(text):
    """RFC 822 date -> aware UTC datetime, or None when it cannot be read. Numeric offsets
    and the named zones in NAMED_ZONES; '-0000' (RFC 5322: UTC, local unknown) is UTC."""
    if not text:
        return None
    t = str(text).strip()
    parsed = parsedate_tz(t)
    if parsed is None:
        return None
    # The zone is read HERE, not from parsedate_tz: that function treats an alphabetic zone
    # it does not know (BST, XYZ, ...) as offset zero, which is exactly the silent guess this
    # parser refuses to make.
    zone = t.split()[-1].strip()
    if re.fullmatch(r"[+-]\d{4}", zone):
        sign = -1 if zone[0] == "-" else 1
        offset = sign * (int(zone[1:3]) * 3600 + int(zone[3:5]) * 60)
    elif zone.upper() in NAMED_ZONES:
        offset = NAMED_ZONES[zone.upper()]
    else:
        return None
    try:
        local = datetime(*parsed[:6], tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None
    return local - timedelta(seconds=offset)


def parse_iso_utc(text):
    if not text:
        return None
    try:
        d = datetime.fromisoformat(str(text).replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")


def strip_html(s):
    """Tags removed, entities unescaped, whitespace collapsed. The body is text to embed."""
    if s is None:
        return ""
    return _WS.sub(" ", html.unescape(_TAG.sub(" ", str(s)))).strip()


def parse_rss(xml_bytes):
    """RSS 2.0 bytes -> ([item dict], [error string]). An item without guid AND link is an
    error and is dropped; an unparseable pubDate is an error and the item keeps
    published_at None."""
    root = ET.fromstring(xml_bytes)
    channel = root.find("channel")
    nodes = (channel if channel is not None else root).findall("item")
    items, errors = [], []
    for i, it in enumerate(nodes):
        guid = (it.findtext("guid") or "").strip()
        link = (it.findtext("link") or "").strip()
        if not guid and not link:
            errors.append(f"item {i}: no guid and no link; dropped")
            continue
        guid = guid or link
        pub_text = (it.findtext("pubDate") or "").strip()
        published = parse_rfc822(pub_text) if pub_text else None
        if pub_text and published is None:
            errors.append(f"{guid}: unparseable pubDate {pub_text!r}; published_at left NULL")
        items.append({"guid": guid, "url": link or guid,
                      "headline": strip_html(it.findtext("title")),
                      "body": strip_html(it.findtext("description")),
                      "published_at": published})
    return items, errors


# ---- the versioned store ----------------------------------------------------------------

_COLS = ("source", "guid", "version", "url", "headline", "body", "published_at", "fetched_at",
         "content_hash", "raw_ref", "element_id", "status", "chance", "club", "date_source", "body_source")
_DEFAULT_DATE_SOURCE = {"bbc": "feed"}          # fpl is decided per row: source_field when it has a claim, else first_seen


def upsert_versions(conn, source, candidates):
    """Each candidate: guid, url, headline, body, published_at, fetched_at, content_hash,
    raw_ref, element_id, status, chance. A candidate is compared against the version that
    was CURRENT at its own fetched_at (the newest stored version observed at or before it):
    same hash -> skipped, else it is stored as the next version number. When the archive is
    processed chronologically that reference is simply the latest version, so d -> cleared
    -> d with identical text is v1, v2, v3; and re-processing a snapshot that was already
    processed is a no-op, because each of its candidates meets the version it created.
    Returns {new, new_versions, skipped}. One transaction; candidates for one guid within a
    call are applied in order."""
    assert source in SOURCES, source
    counts = {"new": 0, "new_versions": 0, "skipped": 0}
    with conn.cursor() as cur:
        for c in candidates:
            cur.execute("SELECT content_hash FROM news_items WHERE source = %s AND guid = %s AND fetched_at <= %s "
                        "ORDER BY fetched_at DESC, version DESC LIMIT 1", (source, c["guid"], c["fetched_at"]))
            ref = cur.fetchone()
            if ref is not None and ref[0] == c["content_hash"]:
                counts["skipped"] += 1
                continue
            cur.execute("SELECT COALESCE(MAX(version), 0) FROM news_items WHERE source = %s AND guid = %s",
                        (source, c["guid"]))
            version = int(cur.fetchone()[0]) + 1
            date_source = c.get("date_source") or _DEFAULT_DATE_SOURCE.get(source) or \
                ("source_field" if c.get("published_at") is not None else "first_seen")
            row = (source, c["guid"], version, c.get("url"), c["headline"], c.get("body") or "",
                   c.get("published_at"), c["fetched_at"], c["content_hash"], c["raw_ref"],
                   c.get("element_id"), c.get("status"), c.get("chance"), c.get("club"), date_source,
                   c.get("body_source") or ("tavily_extract" if source == "club" else None))
            cur.execute(f"INSERT INTO news_items ({', '.join(_COLS)}) VALUES ({', '.join(['%s'] * len(_COLS))}) "
                        f"ON CONFLICT (source, guid, version) DO NOTHING RETURNING id", row)
            if cur.fetchone() is None:
                counts["skipped"] += 1
            elif version == 1:
                counts["new"] += 1
            else:
                counts["new_versions"] += 1
    conn.commit()
    return counts


def ingest_rss(conn, xml_bytes, raw_ref, fetched_at, source="bbc"):
    """Parse one saved RSS response and store its items as versions.
    Returns {fetched, new, new_versions, skipped, errors}."""
    items, errors = parse_rss(xml_bytes)
    cands = [{**it, "fetched_at": fetched_at, "raw_ref": raw_ref,
              "content_hash": content_hash(it["headline"], it["body"])} for it in items]
    counts = upsert_versions(conn, source, cands)
    return {"fetched": len(items), **counts, "errors": len(errors)}


# ---- fetching: raw first, conditional GET, honest UA ----------------------------------------

def _http_get(url, headers):
    req = Request(url, headers=headers)
    try:
        with urlopen(req, timeout=30) as r:
            return r.status, dict(r.headers), r.read()
    except HTTPError as e:
        if e.code == 304:
            return 304, dict(e.headers), b""
        raise


def _hdr(headers, name):
    for k, v in (headers or {}).items():
        if k.lower() == name.lower():
            return v
    return None


def _write_atomic(path, data):
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def raw_ref_for(path):
    p = Path(path)
    try:
        return p.resolve().relative_to(REPO).as_posix()
    except ValueError:
        return p.as_posix()


def fetch_rss(url, raw_dir, now=None, http=None, state_path=None):
    """One conditional GET. 200 -> the response is gzipped to <raw_dir>/<utc-ts>.xml.gz BEFORE
    anything parses it, and the validators are kept for the next call; 304 -> nothing is
    written, nothing is stored. Returns {status, raw_path, raw_ref, body, headers}."""
    raw_dir = Path(raw_dir)
    now = now or datetime.now(timezone.utc)
    state_path = Path(state_path) if state_path else raw_dir / "state.json"
    state = {}
    if state_path.exists():
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
        except ValueError:
            state = {}
    headers = {"User-Agent": USER_AGENT, "Accept": "application/rss+xml, application/xml, text/xml;q=0.9"}
    if state.get("etag"):
        headers["If-None-Match"] = state["etag"]
    if state.get("last_modified"):
        headers["If-Modified-Since"] = state["last_modified"]
    status, resp_headers, body = (http or _http_get)(url, headers)
    if status == 304:
        return {"status": 304, "raw_path": None, "raw_ref": None, "body": None, "headers": resp_headers}
    if status != 200:
        raise RuntimeError(f"HTTP {status} from {url}")
    raw_dir.mkdir(parents=True, exist_ok=True)
    path = raw_dir / f"{now:%Y%m%dT%H%M%SZ}.xml.gz"
    if not path.exists():                                    # never overwrite a raw file
        _write_atomic(path, gzip.compress(body))
    state = {"url": url, "etag": _hdr(resp_headers, "ETag"), "last_modified": _hdr(resp_headers, "Last-Modified"),
             "last_status": 200, "last_fetched_at": now.isoformat(), "last_raw": path.name}
    _write_atomic(state_path, json.dumps(state, indent=1).encode("utf-8"))
    return {"status": 200, "raw_path": path, "raw_ref": raw_ref_for(path), "body": body, "headers": resp_headers}


# ---- FPL: versions derived from the raw snapshot archive -------------------------------------

def snapshot_time(name):
    return datetime.strptime(str(name).split(".")[0], "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)


def _load_gz_json(path):
    with gzip.open(path, "rt", encoding="utf-8") as f:
        return json.load(f)


def fpl_candidates(doc, fetched_at, raw_ref):
    """(flagged: {guid: candidate}, reported: {guid: (status, chance, headline)}) for one
    bootstrap-static document. Flagged = news non-empty or status != 'a'."""
    teams = {int(t["id"]): str(t.get("short_name") or t.get("name") or t["id"]) for t in doc.get("teams", [])}
    types = {int(e["id"]): str(e.get("singular_name_short") or e["id"]) for e in doc.get("element_types", [])}
    flagged, reported = {}, {}
    for e in doc.get("elements", []):
        el = int(e["id"])
        guid = f"fpl:{el}"
        status = e.get("status")
        chance = e.get("chance_of_playing_next_round")           # NOT this_round (bug 2)
        chance = int(chance) if chance is not None else None
        news = (e.get("news") or "").strip()
        headline = f"{e.get('web_name', el)} ({teams.get(int(e.get('team', 0)), '?')}, {types.get(int(e.get('element_type', 0)), '?')})"
        reported[guid] = (status, chance, headline)
        if not news and status == "a":
            continue
        flagged[guid] = {"guid": guid, "url": None, "headline": headline, "body": news,
                         "published_at": parse_iso_utc(e.get("news_added")), "fetched_at": fetched_at,
                         "raw_ref": raw_ref, "content_hash": content_hash(status, news, chance),
                         "element_id": el, "status": status, "chance": chance}
    return flagged, reported


def _latest_fpl_state(conn, as_of=None):
    """guid -> active? from the newest stored version AS OF a snapshot time (active = not a cleared
    version). The as-of matters (defect of 2026-09-26): every run re-walks the whole archive, and
    judged by the newest version overall, a player first flagged after the archive began looked
    "active" at the archive's first snapshot, so a cleared row stamped with that old time was
    written as a new version number (122 guids on the server). Judged as of the snapshot, no
    version exists yet and nothing is written."""
    with conn.cursor() as cur:
        if as_of is None:
            cur.execute("SELECT DISTINCT ON (guid) guid, body, status FROM news_items "
                        "WHERE source = 'fpl' ORDER BY guid, fetched_at DESC, version DESC")
        else:
            cur.execute("SELECT DISTINCT ON (guid) guid, body, status FROM news_items "
                        "WHERE source = 'fpl' AND fetched_at <= %s ORDER BY guid, fetched_at DESC, version DESC", (as_of,))
        return {g: not (b == "" and s == "a") for g, b, s in cur.fetchall()}


# guids whose highest version number is not their newest row in time: the version numbers follow
# insertion order, so this is 0 whenever the archive was walked in snapshot-time order
FPL_VERSION_ORDER_SQL = ("SELECT count(*) FROM (SELECT guid, (array_agg(fetched_at ORDER BY version DESC))[1] AS latest_fetched, "
                         "max(fetched_at) AS max_fetched FROM news_items WHERE source = 'fpl' GROUP BY guid) v "
                         "WHERE latest_fetched < max_fetched")


def fpl_version_order_mismatches(conn):
    """How many FPL guids have a higher version number on an older row (see FPL_VERSION_ORDER_SQL);
    /health reports it, the rebuild of 2026-10-01 must leave it at 0."""
    with conn.cursor() as cur:
        cur.execute(FPL_VERSION_ORDER_SQL)
        return int(cur.fetchone()[0])


def derive_fpl(conn, snapshot_dir, season, files=None):
    """Walk every snapshot in the archive directory -- or the given files -- in SNAPSHOT-TIME order,
    whatever order they are listed or stored in, and store the versions they imply. raw_ref is the
    snapshot's canonical archive path data/live/bootstrap_raw/<season>/<file>, whatever directory
    the copy is read from. The cleared-flag candidates are judged as of each snapshot's time, so a
    re-walk of an archive already stored adds nothing.
    Returns {snapshots, fetched, new, new_versions, skipped, errors}."""
    d = Path(snapshot_dir)
    paths = [Path(p) for p in files] if files is not None else list(d.glob("*.json.gz"))
    files = sorted((snapshot_time(p.name), p.name, p) for p in paths)
    counts = {"snapshots": 0, "fetched": 0, "new": 0, "new_versions": 0, "skipped": 0, "errors": 0}
    for ts, name, path in files:
        try:
            doc = _load_gz_json(path)
        except (OSError, ValueError) as e:
            counts["errors"] += 1
            continue
        raw_ref = f"data/live/bootstrap_raw/{season}/{name}"
        flagged, reported = fpl_candidates(doc, ts, raw_ref)
        cands = list(flagged.values())
        for guid, active in _latest_fpl_state(conn, ts).items():
            if active and guid not in flagged and guid in reported:
                status, chance, headline = reported[guid]
                cands.append({"guid": guid, "url": None, "headline": headline, "body": "",
                              "published_at": None, "fetched_at": ts, "raw_ref": raw_ref,
                              "content_hash": content_hash(status, "", chance),
                              "element_id": int(guid[4:]), "status": status, "chance": chance})
        c = upsert_versions(conn, "fpl", cands)
        counts["snapshots"] += 1
        counts["fetched"] += len(cands)
        for k in ("new", "new_versions", "skipped"):
            counts[k] += c[k]
    return counts
