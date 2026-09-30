"""The embedding layer (2026-09-30): the Voyage adapter (embeddings.py), the news_chunks table with
its keyword configuration (news_store.py), the pipeline over news_to_embed (embed_pipeline.py), the
CLI (eval/run_embed.py) and the runner hooks. No network: a fake Voyage client serves scripted
vectors and errors. Pinned here:
  * embed(texts, kind): kind is "document" or "query" and is sent as input_type; the model and
    output_dimension come from config; texts are batched under the per-request caps; vectors come
    back in input order; a wrong dimension is an error, never stored;
  * retries on 429 / 5xx / timeout (two more attempts, 1 s / 2 s), fail-fast on 401 / 403, other 4xx
    raised at once; one embedding_calls row per HTTP attempt;
  * pacing within the account's RPM / TPM;
  * news_chunks exists only when the vector extension is installed; tsv uses fpl_english
    (english + unaccent) so "odegaard" finds "Ødegaard" and "Saka" finds "saka";
  * embed_pending chunks every news_to_embed item without chunks for (CHUNKER_VERSION, EMBED_MODEL),
    writes vectors and tsv, is idempotent (a second run makes zero calls), --dry-run makes zero calls
    and writes nothing, a failed group writes nothing and is retried next run, three consecutive
    same-signature failures stop the run, an auth error stops it at once;
  * without pgvector the step logs "pgvector not installed, embedding skipped" and returns;
  * the runners call the pipeline after the relevance filter.
Needs a local Postgres with the vector extension available (skips loudly without one).
"""
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "eval"))
import psycopg2  # noqa: E402
import db_write  # noqa: E402
import config_roles  # noqa: E402
import news_store as ns  # noqa: E402
import chunking as ch  # noqa: E402
import embeddings as em  # noqa: E402
import embed_pipeline as ep  # noqa: E402

UTC = timezone.utc
TEST_DB = "fpl_news_test"
DROP_ALL = ("DROP TABLE IF EXISTS news_chunks; DROP TABLE IF EXISTS embedding_calls; "
            "DROP VIEW IF EXISTS news_to_embed; DROP VIEW IF EXISTS news_embed_text; "
            "DROP TABLE IF EXISTS news_relevance; DROP TABLE IF EXISTS llm_calls; "
            "DROP TABLE IF EXISTS news_items; DROP TABLE IF EXISTS tavily_calls")


@pytest.fixture
def conn(monkeypatch):
    monkeypatch.setenv("DB_NAME", "postgres")
    try:
        admin = db_write.connect()
    except psycopg2.OperationalError as e:
        pytest.skip(f"no local Postgres: {str(e).splitlines()[0]}")
    admin.autocommit = True
    with admin.cursor() as cur:
        cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (TEST_DB,))
        if cur.fetchone() is None:
            cur.execute(f"CREATE DATABASE {TEST_DB}")
    admin.close()
    monkeypatch.setenv("DB_NAME", TEST_DB)
    c = db_write.connect()
    with c.cursor() as cur:
        cur.execute("SELECT 1 FROM pg_available_extensions WHERE name = 'vector'")
        if cur.fetchone() is None:
            c.close()
            pytest.skip("the local Postgres has no vector extension available (needs the pgvector image)")
        cur.execute(DROP_ALL)
        cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
    c.commit()
    ns.ensure_schema(c)
    yield c
    c.close()


# ---- the fake Voyage client ------------------------------------------------------------------------

class FakeStatusError(Exception):
    def __init__(self, status_code, msg="fake"):
        super().__init__(msg)
        self.status_code = status_code


class Timeout(Exception):
    """named like requests' Timeout, so the adapter's classification sees a timeout"""


def unit_vector(text, dim):
    v = [0.0] * dim
    v[sum(map(ord, text)) % dim] = 1.0
    return v


class FakeVoyage:
    """Serves scripted outcomes in order: "ok" (or nothing left) returns one unit vector per text,
    an int returns vectors of THAT dimension, an Exception is raised."""

    def __init__(self, script=None):
        self.script, self.calls = list(script or []), []

    def embed(self, texts, model, input_type, output_dimension):
        self.calls.append({"texts": list(texts), "model": model, "input_type": input_type, "output_dimension": output_dimension})
        nxt = self.script.pop(0) if self.script else "ok"
        if isinstance(nxt, Exception):
            raise nxt
        dim = nxt if isinstance(nxt, int) else output_dimension
        return [unit_vector(t, dim) for t in texts], sum(len(t) // 4 + 1 for t in texts)


class Clock:
    def __init__(self):
        self.t, self.sleeps = 0.0, []

    def __call__(self):
        return self.t

    def sleep(self, s):
        self.sleeps.append(s)
        self.t += s


def free_pacer():
    """a pacer that never waits, for tests about other things"""
    return em.Pacer(rpm=10 ** 6, tpm=10 ** 9)


# ---- config --------------------------------------------------------------------------------------------

def test_config_pins():
    assert config_roles.EMBED_MODEL == "voyage-4" and config_roles.EMBED_DIM == 1024
    assert config_roles.EMBED_MAX_TEXTS_PER_REQUEST == 1000 and config_roles.EMBED_MAX_TOKENS_PER_REQUEST == 320_000
    assert config_roles.EMBED_RPM == 1000 and config_roles.EMBED_TPM == 4_000_000  # Tier 1 halved (ruling 2026-09-30)
    assert config_roles.EMBED_PRICE_USD_PER_MTOK == 0.06 and config_roles.EMBED_FREE_TOKENS == 200_000_000
    assert config_roles.EMBED_CHARS_PER_TOKEN == 3 and config_roles.EMBED_TOKENS_PER_TEXT == 24      # ruling 2026-09-30
    assert config_roles.EMBED_REQUEST_TPM_SHARE == 0.8
    assert ch.CHUNKER_VERSION == "chunk_v2"


# ---- the adapter ----------------------------------------------------------------------------------------

def test_kind_is_validated_and_empty_input_makes_no_calls():
    fake = FakeVoyage()
    with pytest.raises(ValueError):
        em.embed(["x"], "passage", client=fake, pacer=free_pacer())
    assert em.embed([], "document", client=fake, pacer=free_pacer()) == []
    assert fake.calls == []


def test_input_type_model_and_dimension_are_sent():
    fake = FakeVoyage()
    vecs = em.embed(["Saka is fit.", "Palmer is a doubt."], "document", client=fake, pacer=free_pacer())
    assert len(vecs) == 2 and all(len(v) == config_roles.EMBED_DIM for v in vecs)
    assert fake.calls == [{"texts": ["Saka is fit.", "Palmer is a doubt."], "model": "voyage-4",
                           "input_type": "document", "output_dimension": 1024}]
    em.embed(["Is Saka fit?"], "query", client=fake, pacer=free_pacer())
    assert fake.calls[-1]["input_type"] == "query"


def test_batching_by_text_count_keeps_order(monkeypatch):
    monkeypatch.setattr(config_roles, "EMBED_MAX_TEXTS_PER_REQUEST", 2)
    fake = FakeVoyage()
    texts = [f"text {i}" for i in range(5)]
    vecs = em.embed(texts, "document", client=fake, pacer=free_pacer())
    assert [len(c["texts"]) for c in fake.calls] == [2, 2, 1]
    assert vecs == [unit_vector(t, 1024) for t in texts]


def test_batching_by_token_budget(monkeypatch):
    monkeypatch.setattr(config_roles, "EMBED_TPM", 1000)                     # 1,000 tokens per request at most
    monkeypatch.setattr(config_roles, "EMBED_CHARS_PER_TOKEN", 3)
    fake = FakeVoyage()
    texts = ["a" * 2000, "b" * 2000, "c" * 100, "d" * 100]                   # 691, 691, 58, 58 estimated tokens (24 per text)
    em.embed(texts, "document", client=fake, pacer=free_pacer())
    assert em.request_token_budget() == 800                                   # 80% of the TPM
    assert [len(c["texts"]) for c in fake.calls] == [1, 2, 1]                 # a alone; b + c = 749; + d would be 807 > 800


def test_batches_helper_is_pure():
    assert em.batches(["ab", "cd", "ef"], max_texts=2, max_tokens=100, chars_per_token=1) == [[0, 1], [2]]
    assert em.batches(["abcd", "ab", "abcd"], max_texts=10, max_tokens=5, chars_per_token=1) == [[0], [1], [2]]
    assert em.batches(["ab", "cd", "ef"], max_texts=10, max_tokens=12, chars_per_token=1, per_text=3) == [[0, 1], [2]]   # 6 + 6 + 6
    assert em.batches([], 10, 10, 1) == []


# the four successful requests of the 2026-09-30 run: (texts, characters, usage.total_tokens)
RECORDED = [(155, 23726, 8669), (27, 26657, 6616), (26, 27608, 6791), (19, 18790, 4564)]
MEASURED_CHARS_PER_TOKEN, MEASURED_PER_TEXT = 4.44, 21.5                  # least-squares fit over those four


def synthetic_texts(n, chars):
    """n texts whose lengths add up to chars, as evenly as possible"""
    base, extra = divmod(chars, n)
    return ["x" * (base + (1 if i < extra else 0)) for i in range(n)]


def test_estimate_is_never_below_the_measured_formula():
    for n, chars, actual in RECORDED:
        est = sum(em.estimate_tokens(t) for t in synthetic_texts(n, chars))
        assert est >= chars / MEASURED_CHARS_PER_TOKEN + MEASURED_PER_TEXT * n
        assert est >= actual


def test_the_failed_fpl_group_now_splits_under_80_percent_of_the_budget(monkeypatch):
    monkeypatch.setattr(config_roles, "EMBED_TPM", 10_000)                      # the account limit of the 2026-09-30 run
    texts = synthetic_texts(223, 29426)                                         # the group that got three 429s
    assert sum(em.estimate_tokens(t) for t in texts) > config_roles.EMBED_TPM   # it no longer fits one request
    groups = em.batches(texts, config_roles.EMBED_MAX_TEXTS_PER_REQUEST, em.request_token_budget(),
                        config_roles.EMBED_CHARS_PER_TOKEN, config_roles.EMBED_TOKENS_PER_TEXT)
    assert len(groups) >= 2 and sum(len(g) for g in groups) == 223
    for g in groups:
        est = sum(em.estimate_tokens(texts[i]) for i in g)
        assert est <= 0.8 * config_roles.EMBED_TPM
        assert est >= sum(len(texts[i]) for i in g) / MEASURED_CHARS_PER_TOKEN + MEASURED_PER_TEXT * len(g)


def test_retries_on_429_5xx_and_timeout_with_backoff(conn):
    clock = Clock()
    fake = FakeVoyage([FakeStatusError(429), FakeStatusError(503), Timeout("read"), "ok"])
    with pytest.raises(em.EmbedError):                                        # 3 attempts, then gives up
        em.embed(["x"], "document", client=fake, conn=conn, sleep=clock.sleep, pacer=free_pacer())
    assert len(fake.calls) == 3 and clock.sleeps == [1.0, 2.0]
    fake2 = FakeVoyage([FakeStatusError(500), "ok"])
    clock2 = Clock()
    vecs = em.embed(["x"], "document", client=fake2, conn=conn, sleep=clock2.sleep, pacer=free_pacer())
    assert len(vecs) == 1 and len(fake2.calls) == 2 and clock2.sleeps == [1.0]
    with conn.cursor() as cur:
        cur.execute("SELECT ok, error, n_texts, tokens, kind, model, purpose FROM embedding_calls ORDER BY id")
        rows = cur.fetchall()
    assert [r[0] for r in rows] == [False, False, False, False, True]
    assert rows[0][1].startswith("HTTP 429") and rows[1][1].startswith("HTTP 503") and rows[2][1].startswith("timeout")
    assert rows[4][1] is None and rows[4][2:] == (1, 1, "document", "voyage-4", "news_chunks")


def test_fail_fast_on_401_and_403_and_other_4xx_not_retried(conn):
    for status in (401, 403):
        fake = FakeVoyage([FakeStatusError(status)])
        clock = Clock()
        with pytest.raises(em.EmbedAuthError) as e:
            em.embed(["x"], "document", client=fake, conn=conn, sleep=clock.sleep, pacer=free_pacer())
        assert e.value.status == status and len(fake.calls) == 1 and clock.sleeps == []
    fake = FakeVoyage([FakeStatusError(400)])
    with pytest.raises(em.EmbedError) as e:
        em.embed(["x"], "document", client=fake, conn=conn, pacer=free_pacer())
    assert not isinstance(e.value, em.EmbedAuthError) and e.value.status == 400 and len(fake.calls) == 1
    with conn.cursor() as cur:
        cur.execute("SELECT count(*), bool_or(ok) FROM embedding_calls")
        assert cur.fetchone() == (3, False)


def test_wrong_dimension_is_an_error(conn):
    fake = FakeVoyage([8])
    with pytest.raises(em.EmbedError) as e:
        em.embed(["x"], "document", client=fake, conn=conn, pacer=free_pacer())
    assert e.value.error_type == "bad_response"
    with conn.cursor() as cur:
        cur.execute("SELECT ok, error FROM embedding_calls")
        rows = cur.fetchall()
    assert len(rows) == 1 and rows[0][0] is False and "dimension" in rows[0][1]


def test_signature_and_classify():
    assert em.signature(FakeStatusError(429)) == (429, "FakeStatusError")
    assert em.signature(Timeout("t")) == (None, "timeout")
    assert em.classify(FakeStatusError(500))[0] == "retry"
    assert em.classify(FakeStatusError(404))[0] == "fail"
    assert em.classify(FakeStatusError(403))[0] == "auth"
    assert em.classify(Timeout("t"))[0] == "retry"


def test_stats_accumulate_calls_and_tokens():
    fake = FakeVoyage()
    stats = {}
    em.embed(["abcd" * 10, "ef"], "document", client=fake, pacer=free_pacer(), stats=stats)
    assert stats["calls"] == 1 and stats["texts"] == 2 and stats["tokens"] == (40 // 4 + 1) + (2 // 4 + 1)


# ---- pacing ----------------------------------------------------------------------------------------------

def test_pacer_waits_for_the_rpm_window():
    clock = Clock()
    p = em.Pacer(rpm=3, tpm=10_000, clock=clock, sleep=clock.sleep)
    for _ in range(3):
        p.wait(10)
        p.record(10)
    assert clock.sleeps == []
    p.wait(10)                                                # the 4th within the minute waits for the 1st to age out
    assert clock.sleeps and abs(clock.t - 60.0) < 1e-6


def test_pacer_waits_for_the_tpm_window():
    clock = Clock()
    p = em.Pacer(rpm=1000, tpm=100, clock=clock, sleep=clock.sleep)
    p.wait(60)
    p.record(60)
    clock.t = 20.0
    p.wait(50)                                                # 60 + 50 > 100: wait until the first request is 60 s old
    assert abs(clock.t - 60.0) < 1e-6
    p.record(50)
    p.wait(40)                                                # 50 + 40 <= 100: no wait
    assert abs(clock.t - 60.0) < 1e-6


def test_embed_paces_every_attempt(monkeypatch):
    clock = Clock()
    pacer = em.Pacer(rpm=2, tpm=10_000, clock=clock, sleep=clock.sleep)
    monkeypatch.setattr(config_roles, "EMBED_MAX_TEXTS_PER_REQUEST", 1)
    fake = FakeVoyage()
    em.embed(["a", "b", "c"], "document", client=fake, pacer=pacer, sleep=clock.sleep)
    assert len(fake.calls) == 3 and clock.t >= 60.0


# ---- the table and the keyword configuration ---------------------------------------------------------------

def test_news_chunks_table_and_fpl_english_exist(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT column_name, data_type, udt_name FROM information_schema.columns WHERE table_name = 'news_chunks' ORDER BY ordinal_position")
        cols = cur.fetchall()
        cur.execute("SELECT indexname, indexdef FROM pg_indexes WHERE tablename = 'news_chunks' ORDER BY indexname")
        idx = cur.fetchall()
        cur.execute("SELECT count(*) FROM pg_ts_config WHERE cfgname = 'fpl_english'")
        cfg = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM pg_extension WHERE extname IN ('vector', 'unaccent')")
        ext = cur.fetchone()[0]
        cur.execute("SELECT atttypmod FROM pg_attribute WHERE attrelid = 'news_chunks'::regclass AND attname = 'embedding'")
        dim = cur.fetchone()[0]
    names = [c[0] for c in cols]
    assert names == ["id", "news_item_id", "chunk_index", "chunker_version", "embed_model", "chunk_text", "char_count",
                     "embedding", "tsv", "embedded_at"]
    assert dict((c[0], c[2]) for c in cols)["embedding"] == "vector" and dim == config_roles.EMBED_DIM
    assert dict((c[0], c[2]) for c in cols)["tsv"] == "tsvector"
    assert any("UNIQUE" in d and "(news_item_id, chunk_index, chunker_version, embed_model)" in d for _, d in idx)
    assert any("USING gin (tsv)" in d for _, d in idx)
    assert not any("hnsw" in d.lower() or "ivfflat" in d.lower() for _, d in idx)
    assert cfg == 1 and ext == 2


def test_tsv_matches_accents_and_case(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT to_tsvector('fpl_english', 'Ødegaard and Saka trained on Tuesday') @@ to_tsquery('fpl_english', 'odegaard'), "
                    "to_tsvector('fpl_english', 'Ødegaard and Saka trained on Tuesday') @@ to_tsquery('fpl_english', 'Saka'), "
                    "to_tsvector('fpl_english', 'nothing here') @@ to_tsquery('fpl_english', 'saka')")
        assert cur.fetchone() == (True, True, False)


def test_ensure_schema_is_idempotent_with_the_chunks_table(conn):
    ns.ensure_schema(conn)
    ns.ensure_schema(conn)
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM pg_ts_config WHERE cfgname = 'fpl_english'")
        assert cur.fetchone()[0] == 1


def test_guard_without_pgvector_skips_the_table_and_the_step(conn, capsys):
    with conn.cursor() as cur:
        cur.execute("DROP TABLE IF EXISTS news_chunks; DROP EXTENSION IF EXISTS vector CASCADE")
    conn.commit()
    try:
        assert ns.vector_installed(conn) is False
        ns.ensure_schema(conn)
        with conn.cursor() as cur:
            cur.execute("SELECT to_regclass('news_chunks')")
            assert cur.fetchone()[0] is None
        fake = FakeVoyage()
        out = ep.embed_pending(conn, client=fake, log=print)
        assert out["skipped_no_pgvector"] is True and fake.calls == []
        assert "pgvector not installed, embedding skipped" in capsys.readouterr().out
    finally:
        with conn.cursor() as cur:
            cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
        conn.commit()
        ns.ensure_schema(conn)
        assert ns.vector_installed(conn) is True


# ---- the pipeline ---------------------------------------------------------------------------------------------

def sentence(i, width=70):
    core = f"Sentence {i} of the article says that the squad trained again"
    return (core + " and again" * 10)[: width - 1].rstrip() + "."


def paragraph(i, sentences=6, width=70):
    return " ".join(sentence(i * 100 + k, width) for k in range(sentences))


def add_item(conn, source, headline, body, *, guid=None, club=None, relevant=True, current=True, status="d", chance=75,
             fetched=datetime(2026, 9, 26, 11, 0, tzinfo=UTC), verdict=True):
    """a news_items row plus (by default) a production verdict, so the item is in news_to_embed"""
    guid = guid or f"{source}:{headline}"
    with conn.cursor() as cur:
        cur.execute("INSERT INTO news_items (source, guid, version, url, headline, body, published_at, fetched_at, content_hash, raw_ref, "
                    "element_id, status, chance, club, date_source, body_source) VALUES (%s, %s, 1, %s, %s, %s, %s, %s, %s, 'test', %s, %s, %s, %s, %s, %s) "
                    "RETURNING id",
                    (source, guid, f"https://example.org/{guid}", headline, body, fetched, fetched, ns.content_hash(headline, body),
                     1 if source == "fpl" else None, status if source == "fpl" else None, chance if source == "fpl" else None,
                     club, "meta" if source == "club" else ("feed" if source == "bbc" else "source_field"),
                     "tavily_extract" if source == "club" else None))
        item_id = cur.fetchone()[0]
        if verdict:
            cur.execute("INSERT INTO news_relevance (news_item_id, prompt_version, model, stage, relevant, current, players, reason) "
                        "VALUES (%s, %s, %s, %s, %s, %s, %s, 'test')",
                        (item_id, config_roles.PROMPT_VERSION, config_roles.RELEVANCE_MODEL, "skipped" if source == "fpl" else "llm",
                         relevant, current, []))
    conn.commit()
    return item_id


def seed(conn):
    long_body = "\n".join([paragraph(i) for i in range(10)])                 # about 4,200 characters -> several chunks
    ids = {"fpl": add_item(conn, "fpl", "Palmer (CHE, MID)", "Knock - 75% chance of playing"),
           "bbc": add_item(conn, "bbc", "Palmer a doubt for Chelsea", "Cole Palmer is a doubt for Saturday with a knock."),
           "club": add_item(conn, "club", "Team news: Rodri fit for Sunday", long_body, club="Man City"),
           "dropped": add_item(conn, "bbc", "Match report", "Chelsea won 2-1.", relevant=False),
           "unjudged": add_item(conn, "bbc", "No verdict yet", "Nothing to see.", verdict=False)}
    return ids


def chunk_rows(conn):
    with conn.cursor() as cur:
        cur.execute("SELECT news_item_id, chunk_index, chunker_version, embed_model, char_count, length(chunk_text), "
                    "vector_dims(embedding), tsv IS NOT NULL, embedded_at IS NOT NULL FROM news_chunks ORDER BY news_item_id, chunk_index")
        return cur.fetchall()


def test_embed_pending_writes_chunks_with_vectors_and_tsv(conn):
    ids = seed(conn)
    fake = FakeVoyage()
    out = ep.embed_pending(conn, client=fake, log=lambda m: None, pacer=free_pacer())
    rows = chunk_rows(conn)
    by_item = {}
    for r in rows:
        by_item.setdefault(r[0], []).append(r)
    assert set(by_item) == {ids["fpl"], ids["bbc"], ids["club"]}                # dropped and unjudged items are not embedded
    assert len(by_item[ids["fpl"]]) == 1 and len(by_item[ids["bbc"]]) == 1 and len(by_item[ids["club"]]) >= 4
    for r in rows:
        assert r[2:4] == (ch.CHUNKER_VERSION, "voyage-4") and r[4] == r[5] and r[6] == 1024 and r[7] and r[8]
    assert [c["input_type"] for c in fake.calls] == ["document"] * len(fake.calls)
    assert out["items"] == 3 and out["chunks"] == len(rows) and out["written_chunks"] == len(rows) and out["failed_groups"] == 0
    assert out["calls"] == len(fake.calls) and out["tokens"] > 0
    with conn.cursor() as cur:
        cur.execute("SELECT chunk_text FROM news_chunks WHERE news_item_id = %s AND chunk_index = 0", (ids["club"],))
        text = cur.fetchone()[0]
        cur.execute("SELECT embed_text FROM news_embed_text WHERE id = %s", (ids["fpl"],))
        fpl_text = cur.fetchone()[0]
        cur.execute("SELECT chunk_text FROM news_chunks WHERE news_item_id = %s", (ids["fpl"],))
        assert cur.fetchone()[0] == fpl_text                                   # a short item is its embed_text, byte for byte
        cur.execute("SELECT embedding::text FROM news_chunks WHERE news_item_id = %s", (ids["fpl"],))
        stored = [float(x) for x in cur.fetchone()[0].strip("[]").split(",")]
        assert stored == unit_vector(fpl_text, 1024)                          # the fake's vector, stored exactly
        cur.execute("SELECT count(*) FROM news_chunks WHERE tsv @@ to_tsquery('fpl_english', 'rodri')")
        assert cur.fetchone()[0] >= 1
    assert text.startswith("[Man City official site | 2026-09-26] Team news: Rodri fit for Sunday\n")


def test_second_run_makes_zero_calls(conn):
    seed(conn)
    ep.embed_pending(conn, client=FakeVoyage(), log=lambda m: None, pacer=free_pacer())
    n = len(chunk_rows(conn))
    fake = FakeVoyage()
    out = ep.embed_pending(conn, client=fake, log=lambda m: None, pacer=free_pacer())
    assert fake.calls == [] and out["items"] == 0 and len(chunk_rows(conn)) == n
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM embedding_calls")
        calls_before = cur.fetchone()[0]
    ep.embed_pending(conn, client=fake, log=lambda m: None, pacer=free_pacer())
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM embedding_calls")
        assert cur.fetchone()[0] == calls_before


def test_dry_run_makes_zero_calls_and_writes_nothing(conn, capsys):
    seed(conn)
    fake = FakeVoyage()
    out = ep.embed_pending(conn, client=fake, dry_run=True, log=print)
    assert fake.calls == [] and chunk_rows(conn) == []
    assert out["dry_run"] is True and out["items"] == 3 and out["chunks"] >= 6
    assert out["by_source"]["club"]["items"] == 1 and out["by_source"]["club"]["chunks"] >= 4
    assert out["by_source"]["fpl"] == {"items": 1, "chunks": 1}
    assert "dry run" in capsys.readouterr().out
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM embedding_calls")
        assert cur.fetchone()[0] == 0


def test_dry_run_counts_the_v2_fixes_over_club_items(conn):
    seed(conn)
    tail = ["Club v Rivals: Player in the spotlight for the cup programme", "Watch: the manager's cup press conference in full",
            "How the club won away from home", "Manager provides injury update on two players", "Join our video call with a player today!"]
    body = "\n".join(["Manager provides injury update and team news ahead of Canaries clash", paragraph(1), paragraph(2)] + tail)
    add_item(conn, "club", "Manager provides injury update and team news ahead of ...", body, club="Man City")
    out = ep.embed_pending(conn, client=FakeVoyage(), dry_run=True, log=lambda m: None)
    assert out["fixes"] == {"headline_repeat": 1, "ellipsis_headline": 1, "trailing_link_list": 1, "residue_lines": 0}
    assert out["by_source"]["club"]["items"] == 2


def test_limit_takes_the_oldest_ids_first(conn):
    ids = seed(conn)
    fake = FakeVoyage()
    out = ep.embed_pending(conn, limit=1, client=fake, log=lambda m: None, pacer=free_pacer())
    rows = chunk_rows(conn)
    assert out["items"] == 1 and {r[0] for r in rows} == {ids["fpl"]}


def test_failed_group_writes_nothing_and_is_retried_next_run(conn, monkeypatch):
    ids = seed(conn)
    monkeypatch.setattr(config_roles, "EMBED_MAX_TEXTS_PER_REQUEST", 1)       # every item is its own group
    clock = Clock()
    fake = FakeVoyage([FakeStatusError(500), FakeStatusError(500), FakeStatusError(500)])   # the first group fails 3 times
    log = []
    out = ep.embed_pending(conn, client=fake, log=log.append, sleep=clock.sleep, pacer=free_pacer())
    rows = chunk_rows(conn)
    assert {r[0] for r in rows} == {ids["bbc"], ids["club"]}                   # the fpl item (lowest id) got nothing
    assert out["failed_groups"] == 1 and out["written_chunks"] == len(rows)
    assert any("FAILED" in m and "written nothing" in m for m in log)
    fake2 = FakeVoyage()
    ep.embed_pending(conn, client=fake2, log=lambda m: None, pacer=free_pacer())
    assert len(fake2.calls) == 1 and {r[0] for r in chunk_rows(conn)} == {ids["fpl"], ids["bbc"], ids["club"]}


def test_three_consecutive_same_signature_failures_stop_the_run(conn, monkeypatch):
    seed(conn)
    monkeypatch.setattr(config_roles, "EMBED_MAX_TEXTS_PER_REQUEST", 1)
    clock = Clock()
    fake = FakeVoyage([FakeStatusError(500)] * 9)
    log = []
    with pytest.raises(em.EmbedRepeatedError):
        ep.embed_pending(conn, client=fake, log=log.append, sleep=clock.sleep, pacer=free_pacer())
    assert len(fake.calls) == 9 and chunk_rows(conn) == []
    assert any("repeated error, run stopped: 500" in m for m in log)
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM embedding_calls WHERE NOT ok")
        assert cur.fetchone()[0] == 9


def test_a_success_resets_the_streak(conn, monkeypatch):
    seed(conn)
    monkeypatch.setattr(config_roles, "EMBED_MAX_TEXTS_PER_REQUEST", 1)
    clock = Clock()
    fake = FakeVoyage([FakeStatusError(500)] * 3 + ["ok"] + [FakeStatusError(500)] * 3)
    out = ep.embed_pending(conn, client=fake, log=lambda m: None, sleep=clock.sleep, pacer=free_pacer())
    assert out["failed_groups"] == 2 and out["written_items"] == 1


def test_auth_error_stops_the_run_at_once(conn, monkeypatch):
    seed(conn)
    monkeypatch.setattr(config_roles, "EMBED_MAX_TEXTS_PER_REQUEST", 1)
    fake = FakeVoyage([FakeStatusError(401)])
    log = []
    with pytest.raises(em.EmbedAuthError):
        ep.embed_pending(conn, client=fake, log=log.append, pacer=free_pacer())
    assert len(fake.calls) == 1 and chunk_rows(conn) == []
    assert any("auth failed, run stopped" in m for m in log)


def test_groups_keep_an_item_whole(monkeypatch):
    monkeypatch.setattr(config_roles, "EMBED_MAX_TEXTS_PER_REQUEST", 3)
    monkeypatch.setattr(config_roles, "EMBED_TPM", 10 ** 9)
    items = [(1, ["a", "b"]), (2, ["c", "d"]), (3, ["e"]), (4, ["f", "g", "h", "i"]), (5, ["j"])]
    groups = ep.group_items(items)
    assert [[i for i, _ in g] for g in groups] == [[1], [2, 3], [4], [5]]


# ---- the CLI and the runner hooks -----------------------------------------------------------------------------

def test_cli_dry_run_and_limit(conn, monkeypatch):
    import run_embed
    seen = {}
    monkeypatch.setattr(ep, "embed_pending", lambda c, limit=None, **kw: seen.update(kw, limit=limit) or {"items": 0})
    monkeypatch.setattr(sys, "argv", ["run_embed.py", "--dry-run", "--limit", "7"])
    run_embed.main()
    assert seen["dry_run"] is True and seen["limit"] == 7


def test_cli_exits_1_on_failure(conn, monkeypatch, capsys):
    import run_embed
    monkeypatch.setattr(ep, "embed_pending", lambda c, limit=None, **kw: (_ for _ in ()).throw(em.EmbedRepeatedError("boom")))
    monkeypatch.setattr(sys, "argv", ["run_embed.py"])
    with pytest.raises(SystemExit) as e:
        run_embed.main()
    assert e.value.code == 1 and "FAILED" in capsys.readouterr().out


def test_news_runner_embeds_after_relevance(conn, monkeypatch):
    import fetch_news as runner
    order = []
    monkeypatch.setattr(runner, "run_bbc", lambda c, now: order.append("bbc"))
    monkeypatch.setattr(runner, "run_fpl", lambda c, season, store, archive: order.append("fpl"))
    monkeypatch.setattr(runner, "run_relevance", lambda c: order.append("relevance"))
    monkeypatch.setattr(runner, "run_embed", lambda c: order.append("embed"))
    monkeypatch.setattr(sys, "argv", ["fetch_news.py", "--season", "2026-27"])
    runner.main()
    assert order == ["bbc", "fpl", "relevance", "embed"]


def test_club_runner_embeds_after_relevance_even_when_the_gate_is_closed(conn, tmp_path, monkeypatch):
    import fetch_club_news as runner
    order = []
    monkeypatch.setattr(runner, "run_relevance", lambda c: order.append("relevance"))
    monkeypatch.setattr(runner, "run_embed", lambda c: order.append("embed"))
    monkeypatch.setattr(runner, "make_tavily", lambda: (_ for _ in ()).throw(AssertionError("no Tavily outside the window")))
    monkeypatch.setattr(runner, "load_events", lambda: [{"id": 6, "deadline_time": "2026-10-10T10:00:00Z"}])
    monkeypatch.setattr(runner, "RAW_DIR", tmp_path / "raw")
    monkeypatch.setattr(sys, "argv", ["fetch_club_news.py", "--now", "2026-09-25T15:07:00Z"])
    with pytest.raises(SystemExit) as e:
        runner.main()
    assert e.value.code == 0 and order == ["relevance", "embed"]


def test_runner_hooks_use_the_real_pipeline(conn, monkeypatch):
    import fetch_news, fetch_club_news
    calls = []
    monkeypatch.setattr(ep, "embed_pending", lambda c, *a, **k: calls.append(c) or {})
    fetch_news.run_embed(conn)
    fetch_club_news.run_embed(conn)
    assert calls == [conn, conn]
