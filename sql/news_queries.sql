-- News ingestion v1 (2026-09-25): the standing queries over news_items / news_embed_text.
-- Run against the database that eval/fetch_news.py writes to:
--     docker exec -i fpl-postgres psql -U postgres -d fpl < sql/news_queries.sql
-- Every timestamp is UTC (timestamptz); the as-of query (d) is the shape retrieval will use.

-- (a) Row counts by source and version number.
\echo === (a) rows by source and version
SELECT source, version, count(*) AS rows
FROM news_items
GROUP BY source, version
ORDER BY source, version;

-- (b) The 10 newest embed_text rows PER SOURCE, newest first by when we observed the version
--     (fetched_at), then by the source's own claim. Both sources side by side: an overall
--     top-10 would be all BBC, because one fetch of the feed is newer than every archived
--     FPL snapshot.
\echo === (b) 10 newest embed_text rows per source
SELECT source, version, fetched_at, char_count, embed_text
FROM (
    SELECT v.*, row_number() OVER (PARTITION BY v.source ORDER BY v.fetched_at DESC, n.published_at DESC NULLS LAST, v.id DESC) AS rn
    FROM news_embed_text v JOIN news_items n ON n.id = v.id
) t
WHERE rn <= 10
ORDER BY source, rn;

-- (c) Full version history for the FPL player with the most versions (ties: lowest id first).
\echo === (c) full version history, most-versioned FPL player
WITH most AS (
    SELECT guid FROM news_items WHERE source = 'fpl'
    GROUP BY guid ORDER BY count(*) DESC, min(id) LIMIT 1
)
SELECT n.guid, n.headline, n.version, n.fetched_at, n.published_at, n.status, n.chance, n.body, n.raw_ref
FROM news_items n JOIN most USING (guid)
WHERE n.source = 'fpl'
ORDER BY n.version;

-- (d) AS-OF retrieval: the latest version of every FPL item as of a given moment -- the
--     newest version whose fetched_at is at or before the cutoff (by fetched_at, then version,
--     so a version number assigned out of time order can never win). This is the view a
--     retrieval query must take: never a version observed after the moment being asked about.
--     Cutoff here: GW5's deadline, 2026-09-18 17:30Z.
\echo === (d) latest version per guid as of 2026-09-18 17:30Z, FPL only (count, then the first 15 by fetched_at desc)
SELECT count(*) AS items_as_of
FROM (
    SELECT DISTINCT ON (guid) guid
    FROM news_items
    WHERE source = 'fpl' AND fetched_at <= TIMESTAMPTZ '2026-09-18 17:30:00+00'
    ORDER BY guid, fetched_at DESC, version DESC
) x;
SELECT v.guid, v.version, v.fetched_at, v.embed_text
FROM (
    SELECT DISTINCT ON (guid) id
    FROM news_items
    WHERE source = 'fpl' AND fetched_at <= TIMESTAMPTZ '2026-09-18 17:30:00+00'
    ORDER BY guid, fetched_at DESC, version DESC
) latest
JOIN news_embed_text v ON v.id = latest.id
ORDER BY v.fetched_at DESC, v.guid
LIMIT 15;

-- (e) char_count distribution of the embed text per source.
\echo === (e) char_count per source
SELECT source, count(*) AS rows, min(char_count) AS min,
       percentile_cont(0.5) WITHIN GROUP (ORDER BY char_count) AS median,
       max(char_count) AS max
FROM news_embed_text
GROUP BY source
ORDER BY source;

-- (f) BBC rows whose headline or body mentions any of: injury, doubt, ruled out, fitness,
--     training, return (case-insensitive, substring match: "injured" and "returns" count).
\echo === (f) BBC rows mentioning injury / doubt / ruled out / fitness / training / return
SELECT count(*) AS matching_rows
FROM news_items
WHERE source = 'bbc' AND (headline || ' ' || body) ~* '(injur|doubt|ruled out|fitness|training|return)';
SELECT id, version, published_at, headline, body
FROM news_items
WHERE source = 'bbc' AND (headline || ' ' || body) ~* '(injur|doubt|ruled out|fitness|training|return)'
ORDER BY published_at DESC
LIMIT 5;
