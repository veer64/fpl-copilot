"""The live build's availability must be AS-OF the build, by the training rule.

PRINCIPLE (2026-09-25): for a live build at time T for deadline gameweek g, the
availability rows the model receives for g must come from the NEWEST snapshot with
snapshot_time <= min(T, deadline(g)) -- the same rule eval/build_availability.py uses
for the training asof_* columns (last snapshot STRICTLY before the deadline). One date
rule, no second one.

WHAT THE CODE DID BEFORE THE FIX (measured on the server, run 19 / nightly 2026-09-24):
  * eval/poll_availability.py::build skipped every gameweek whose deadline had not passed
    (`if not prior or deadline > _now(): continue`), so the LIVE gameweek never got
    poller rows, however fresh the raw archive was;
  * eval/merge_live_availability.py then filled the live gameweek from the fplcache-derived
    file, whose newest snapshot on the server is 2026-08-29 16:36Z;
  * squad/availability_features.py::load globs the merged file, and the minutes model
    scored GW6 on a snapshot 25.8 days older than the build.

THE FIX (same date): the deadline runner stores ONE bootstrap-static fetch into the raw
archive at the start of every build (asof_source 'build_fetch', its own file name tag,
never overwriting), runs `poll_availability.py --build --now <build time>` -- which now
builds EVERY gameweek from the newest snapshot <= min(now, deadline) -- and then the
merge. A failed build-time fetch is logged and the build falls back to the newest
archived snapshot; the strict preflight's MAX_AVAILABILITY_AGE (config_roles, user
decision: 6 h) refuses a live build whose deadline-gameweek rows are older than that.

These tests drive the REAL derivation chain (poller build -> merge) on a synthetic
archive with snapshots at known times and a build clock T, and read back what the
model would see.
"""
import gzip
import json
import lzma
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "squad"))
sys.path.insert(0, str(REPO / "eval"))
import config_roles  # noqa: E402
import poll_availability as pa  # noqa: E402
import merge_live_availability as mla  # noqa: E402
import build_availability as ba  # noqa: E402
import live_deadline as ld  # noqa: E402
import run_live_deadline as rld  # noqa: E402

SEASON = "2026-27"
GW = 6
REF = REPO / "data" / "availability_2526.parquet"       # the merge's schema reference
LIVE_FILE = REPO / "data" / f"availability_{SEASON[2:4]}{SEASON[5:7]}.parquet"

UTC = timezone.utc
GW1_DEADLINE = datetime(2026, 8, 15, 17, 30, tzinfo=UTC)
DEADLINES = {k: GW1_DEADLINE + timedelta(days=7 * (k - 1)) for k in range(1, 39)}
DEADLINE = DEADLINES[GW]                                  # 2026-09-19 17:30Z

T0 = datetime(2026, 8, 10, 12, 0, tzinfo=UTC)             # fplcache snapshot: everyone fit
T1 = datetime(2026, 9, 10, 12, 0, tzinfo=UTC)             # poller: player 2 doubtful
T2 = datetime(2026, 9, 17, 12, 0, tzinfo=UTC)             # poller: player 2 injured, 3 doubtful
T3 = datetime(2026, 9, 19, 18, 0, tzinfo=UTC)             # poller: post-deadline recovery poll

STATUSES = {
    T0: {1: ("a", None, ""), 2: ("a", None, ""), 3: ("a", None, "")},
    T1: {1: ("a", None, ""), 2: ("d", 75, "Knock - 75% chance of playing"), 3: ("a", None, "")},
    T2: {1: ("a", None, ""), 2: ("i", 0, "Hamstring - Unknown return date"),
         3: ("d", 50, "Knock - 50% chance of playing")},
    T3: {1: ("a", None, ""), 2: ("i", 0, "Hamstring - Unknown return date"),
         3: ("i", 0, "Knock - Unknown return date")},
}


def _iso(t):
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def _payload(ts, statuses=None):
    """A bootstrap-static shaped document as fetched at `ts`. news_added never lies after
    the snapshot that carries it (build_availability asserts exactly that). The
    post-deadline poll's news is stamped AT the poll, i.e. after the deadline, so the
    training rule's late-news recovery (news stamped inside the gap before the deadline)
    does not apply to it: these tests are about snapshot SELECTION, not recovery."""
    events = [{"id": k, "deadline_time": _iso(d), "finished": d < ts} for k, d in DEADLINES.items()]
    stamped = ts if ts >= DEADLINE else ts - timedelta(hours=1)
    elements = []
    for el, (st, cop, news) in (statuses or STATUSES[ts]).items():
        elements.append({"id": el, "web_name": f"p{el}", "status": st,
                         "chance_of_playing_this_round": cop,
                         "chance_of_playing_next_round": cop,
                         "news": news,
                         "news_added": _iso(stamped) if news else None})
    return {"events": events, "elements": elements}


def _write_raw(live, ts, source=pa.SOURCE_POLLER):
    d = live / "bootstrap_raw" / SEASON
    d.mkdir(parents=True, exist_ok=True)
    p = d / pa.raw_name(ts, source)
    p.write_bytes(gzip.compress(json.dumps(_payload(ts)).encode("utf-8")))
    return p


def _write_fplcache(cache, ts):
    d = cache / str(ts.year) / str(ts.month) / str(ts.day)
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{ts.strftime('%H%M')}.json.xz"
    with lzma.open(p, "wt", encoding="utf-8") as f:
        json.dump(_payload(ts), f)
    return p


@pytest.fixture
def archive(tmp_path, monkeypatch):
    """A repo-shaped tmp tree: the two live archives under data/live, the schema
    reference under data/, and every module constant pointed at it. Returns a function
    that runs the real chain at build clock T and returns the merged rows for GW.
    raw items are datetimes (poller files) or (datetime, source) pairs."""
    if not REF.exists():
        pytest.skip(f"{REF.name} not on disk (the merge reads it for the schema)")
    root = tmp_path / "repo"
    data, live, cache = root / "data", root / "data" / "live", tmp_path / "fplcache"
    live.mkdir(parents=True)
    pd.read_parquet(REF).iloc[0:0].to_parquet(data / REF.name, index=False)

    # fplcache side: ONE old snapshot, derived by the training builder itself
    _write_fplcache(cache, T0)
    fplc = ba.build(SEASON, cache=cache)
    fplc.to_parquet(live / f"availability_{SEASON}_fplcache.parquet", index=False)

    monkeypatch.setattr(pa, "REPO", root)
    monkeypatch.setattr(pa, "LIVE", live)
    monkeypatch.setattr(mla, "REPO", root)
    monkeypatch.setattr(mla, "LIVE", live)

    def run(now, raw_items):
        for item in raw_items:
            ts, source = item if isinstance(item, tuple) else (item, pa.SOURCE_POLLER)
            _write_raw(live, ts, source)
        pa.build(SEASON, now=now)                # live archive -> *_live.parquet
        try:
            out = mla.merge(SEASON)              # live + fplcache -> data/availability_2627.parquet
        except FileNotFoundError as e:
            pytest.fail(f"the merge could not run: {e} -- the poller build wrote nothing")
        merged = pd.read_parquet(out)
        return merged[merged["gw"] == GW].sort_values("element").reset_index(drop=True)

    run.live = live
    return run


# ---- 1. the principle: newest snapshot <= min(T, deadline), through the real chain ----

CASES = [
    pytest.param(datetime(2026, 9, 18, 12, 0, tzinfo=UTC), [T1, T2], T2,
                 id="T_before_deadline_newest_poll_wins"),
    pytest.param(datetime(2026, 9, 15, 12, 0, tzinfo=UTC), [T1, T2], T1,
                 id="T_between_polls_nothing_after_T_is_used"),
    pytest.param(datetime(2026, 9, 20, 12, 0, tzinfo=UTC), [T1, T2, T3], T2,
                 id="T_after_deadline_post_deadline_poll_excluded"),
]


@pytest.mark.parametrize("now,raw_items,expected", CASES)
def test_deadline_gw_rows_carry_newest_snapshot_at_or_before_min_T_deadline(archive, now, raw_items, expected):
    """Every GW row the model would read must carry snapshot_time == the newest archived
    snapshot <= min(T, deadline), and the asof_* values of THAT snapshot."""
    rows = archive(now, raw_items)
    assert len(rows) == 3, f"expected the 3 synthetic elements at GW{GW}, got {len(rows)}"
    got = set(pd.to_datetime(rows["snapshot_time"], utc=True))
    assert got == {expected}, (
        f"GW{GW} rows carry snapshot_time {sorted(got)} but the newest snapshot at or before "
        f"min(T={now:%Y-%m-%d %H:%M}Z, deadline={DEADLINE:%Y-%m-%d %H:%M}Z) is {expected:%Y-%m-%d %H:%M}Z "
        f"(sources seen: {sorted(rows['asof_source'].unique())})")
    want = {el: st for el, (st, _, _) in STATUSES[expected].items()}
    got_status = dict(zip(rows["element"].astype(int), rows["asof_status"]))
    assert got_status == want, f"asof_status {got_status} is not the {expected:%Y-%m-%d %H:%M}Z snapshot's {want}"


def test_poller_build_emits_the_live_gameweek(archive):
    """The narrow defect: poll_availability.build must build a gameweek whose deadline
    has NOT passed when pre-deadline polls exist, exactly as build_availability does
    for fplcache (its rule takes the last snapshot strictly before the deadline and
    never asks whether the deadline has passed)."""
    now = datetime(2026, 9, 18, 12, 0, tzinfo=UTC)
    archive(now, [T1, T2])
    poller = pd.read_parquet(archive.live / f"availability_{SEASON.replace('-', '_')}_live.parquet")
    gws = sorted(int(g) for g in poller["gw"].unique())
    assert GW in gws, (
        f"poll_availability.build wrote gameweeks {gws} only: it skipped GW{GW} because its deadline "
        f"{DEADLINE:%Y-%m-%d %H:%M}Z is after T={now:%Y-%m-%d %H:%M}Z, although polls at "
        f"{T1:%m-%d %H:%M}Z and {T2:%m-%d %H:%M}Z exist")
    g = poller[poller["gw"] == GW]
    assert set(pd.to_datetime(g["snapshot_time"], utc=True)) == {T2}
    # every later gameweek is built too, from the same newest snapshot (min(T, deadline) = T)
    later = poller[poller["gw"] > GW]
    assert set(later["gw"].astype(int)) == set(range(GW + 1, 39))
    assert set(pd.to_datetime(later["snapshot_time"], utc=True)) == {T2}


# ---- 2. provenance: a build fetch is its own origin, and it never overwrites ----

def test_build_fetch_rows_carry_their_own_provenance(archive):
    """Rows taken from a build-time snapshot say so (asof_source 'build_fetch'); rows
    from a poller poll keep 'live_snapshot'. The two are never confused."""
    now = T2 + timedelta(hours=1)
    rows = archive(now, [T1, (T2, pa.SOURCE_BUILD)])
    assert set(pd.to_datetime(rows["snapshot_time"], utc=True)) == {T2}
    assert set(rows["asof_source"]) == {"build_fetch"}, sorted(rows["asof_source"].unique())
    poller = pd.read_parquet(archive.live / f"availability_{SEASON.replace('-', '_')}_live.parquet")
    gw5 = poller[poller["gw"] == 5]                       # deadline 09-12: only the 09-10 poll precedes it
    assert set(pd.to_datetime(gw5["snapshot_time"], utc=True)) == {T1}
    assert set(gw5["asof_source"]) == {"live_snapshot"}


def test_store_raw_never_overwrites(tmp_path, monkeypatch):
    """A second store for the same second and origin returns the existing file
    byte-for-byte untouched; a different origin at the same second is a different file."""
    live = tmp_path / "live"
    monkeypatch.setattr(pa, "LIVE", live)
    ts = T2
    first = pa.store_raw(_payload(T1), SEASON, ts)
    before = first.read_bytes()
    again = pa.store_raw(_payload(T2), SEASON, ts)          # different content, same key
    assert again == first
    assert first.read_bytes() == before, "store_raw overwrote an existing archive file"
    other = pa.store_raw(_payload(T2), SEASON, ts, source=pa.SOURCE_BUILD)
    assert other != first and other.exists() and first.exists()
    assert pa.raw_source(first) == "poller" and pa.raw_source(other) == "build_fetch"
    listed = pa.list_raw(SEASON)
    assert [t for t, _ in listed] == [ts, ts]
    assert [pa.raw_source(p) for _, p in listed] == ["build_fetch", "poller"]
    assert [pa.raw_source(p) for _, p in pa.list_raw(SEASON, source="poller")] == ["poller"]


def test_poller_gate_and_change_detection_ignore_build_fetches(tmp_path, monkeypatch):
    """A build fetch one minute ago must not delay the poller: the due-gate sees the
    poller's own files only, and the archive's newest file is still what build() reads."""
    live = tmp_path / "live"
    monkeypatch.setattr(pa, "LIVE", live)
    deadline = datetime(2026, 9, 26, 17, 30, tzinfo=UTC)
    now = deadline - timedelta(hours=3)
    pa.store_raw(_payload(T1), SEASON, now - timedelta(minutes=40))                    # last poll
    pa.store_raw(_payload(T2), SEASON, now - timedelta(minutes=1), source=pa.SOURCE_BUILD)
    is_due, why = pa.due(SEASON, deadline, now)
    assert is_due, f"a build fetch 1 min ago shifted the poll schedule: {why!r}"
    assert pa.list_raw(SEASON)[-1][0] == now - timedelta(minutes=1)


# ---- 3. the fetch-failure path: logged, fallback, never fatal ----

class _FakeRunner:
    def __init__(self):
        self.lines, self.sections = [], []

    def log(self, text):
        self.lines.append(text)

    def section(self, title, text):
        self.sections.append((title, text))


def test_build_time_fetch_failure_logs_and_falls_back(archive, monkeypatch):
    """If the build-time fetch fails, snapshot_at_build must not raise: it logs the
    failure, names the newest archived snapshot, returns the build clock unchanged, and
    the derivation then runs on that archived snapshot. Whether that is fresh enough is
    the age guard's decision, not this step's."""
    def boom():
        raise ConnectionError("simulated: bootstrap-static unreachable")
    monkeypatch.setattr(pa, "fetch", boom)
    _write_raw(archive.live, T1)
    _write_raw(archive.live, T2)
    now = T2 + timedelta(hours=2)
    R = _FakeRunner()
    build_now, note = rld.snapshot_at_build(R, SEASON, now)
    assert build_now == now
    assert "FETCH FAILED" in note and "ConnectionError" in note, note
    assert f"{T2:%Y-%m-%d %H:%M:%S}Z" in note and "MAX_AVAILABILITY_AGE" in note, note
    assert any("FETCH FAILED" in l for l in R.lines)
    assert pa.list_raw(SEASON, source=pa.SOURCE_BUILD) == [], "a failed fetch stored a file"
    rows = archive(build_now, [])
    assert set(pd.to_datetime(rows["snapshot_time"], utc=True)) == {T2}
    assert set(rows["asof_source"]) == {"live_snapshot"}


def test_build_time_fetch_success_stores_and_is_used(archive, monkeypatch):
    """The success path end to end: the fetched document lands in the archive as a
    build fetch stamped at the fetch moment, and the deadline gameweek's rows come
    from it."""
    fetched_at = T2 + timedelta(hours=2)
    monkeypatch.setattr(pa, "fetch", lambda: _payload(T2))
    monkeypatch.setattr(pa, "_now", lambda: fetched_at)
    _write_raw(archive.live, T1)
    R = _FakeRunner()
    build_now, note = rld.snapshot_at_build(R, SEASON, T2 + timedelta(hours=1))
    assert build_now == fetched_at and "build_fetch" in note, note
    stored = pa.list_raw(SEASON, source=pa.SOURCE_BUILD)
    assert [t for t, _ in stored] == [fetched_at]
    rows = archive(build_now, [])
    assert set(pd.to_datetime(rows["snapshot_time"], utc=True)) == {fetched_at}
    assert set(rows["asof_source"]) == {"build_fetch"}


# ---- 4. the staleness guard: MAX_AVAILABILITY_AGE, the availability-specific raise ----

def test_max_availability_age_is_the_one_config_value():
    """The threshold has a NAME the strict preflight and /health both read, defined once
    in config_roles. The number is the user's (6 h on 2026-09-25); only its shape is pinned."""
    assert hasattr(ld, "MAX_AVAILABILITY_AGE"), (
        "live_deadline has no MAX_AVAILABILITY_AGE: nothing bounds how old the availability "
        "the model scores on may be")
    assert ld.MAX_AVAILABILITY_AGE is config_roles.MAX_AVAILABILITY_AGE
    assert isinstance(ld.MAX_AVAILABILITY_AGE, timedelta) and ld.MAX_AVAILABILITY_AGE > timedelta(0)


def _live_gw_and_clock():
    """A gameweek in the live file whose deadline is still ahead of the clock the test
    uses: the file's last gameweek, with `now` one second after its newest snapshot, so
    the measured age is 1 s whatever is on disk and however fresh it is."""
    av = pd.read_parquet(LIVE_FILE, columns=["gw", "snapshot_time", "deadline_time"])
    gw = int(av["gw"].max())
    g = av[av["gw"] == gw]
    asof = pd.to_datetime(g["snapshot_time"], utc=True).max().to_pydatetime()
    deadline = pd.to_datetime(g["deadline_time"], utc=True).max().to_pydatetime()
    now = asof + timedelta(seconds=1)
    assert deadline > now, "the file's last gameweek must still be ahead of its own snapshot"
    return gw, asof, now


@pytest.mark.skipif(not LIVE_FILE.exists(), reason="no live-season availability file on disk")
def test_strict_preflight_raises_the_availability_specific_message(monkeypatch):
    """Under strict, a live build whose newest availability for the deadline gameweek is
    older than MAX_AVAILABILITY_AGE must RAISE LiveStrictError, and the message must be
    the availability one: it names the season and gameweek, says STALE, quotes the newest
    snapshot_time and the threshold. A zero threshold makes a 1-second age 'too old'."""
    gw, asof, now = _live_gw_and_clock()
    monkeypatch.setattr(ld, "MAX_AVAILABILITY_AGE", timedelta(0))
    try:
        ld.preflight(SEASON, gw, strict=True, config="baseline", horizon=1, now=now)
    except ld.LiveStrictError as e:
        msg = str(e)
    else:
        pytest.fail("strict preflight did not raise although the newest availability for the "
                    "deadline gameweek is older than MAX_AVAILABILITY_AGE (= 0)")
    assert msg.startswith(f"availability for {SEASON} GW{gw} is STALE"), (
        f"strict preflight raised, but not the availability-age check: {msg[:220]}")
    assert f"newest snapshot_time {asof:%Y-%m-%d %H:%M}Z" in msg, msg
    assert "older than MAX_AVAILABILITY_AGE = 0 h" in msg, msg
    assert "the minutes model would score on out-of-date status/chance/news" in msg, msg


@pytest.mark.skipif(not LIVE_FILE.exists(), reason="no live-season availability file on disk")
def test_preflight_notes_the_age_when_within_threshold(monkeypatch):
    """Non-strict and within the threshold: no STALE finding, but a note that states the
    measured age and the threshold, so a status-file reader sees the number."""
    gw, asof, now = _live_gw_and_clock()
    monkeypatch.setattr(ld, "MAX_AVAILABILITY_AGE", timedelta(days=36500))
    findings = ld.preflight(SEASON, gw, strict=False, config="baseline", horizon=1, now=now)
    assert not [f for f in findings if "STALE" in f], findings
    notes = [f for f in findings if f.startswith(f"note: availability age at GW{gw}")]
    assert notes and f"newest snapshot_time {asof:%Y-%m-%d %H:%M}Z" in notes[0], findings


@pytest.mark.skipif(not LIVE_FILE.exists(), reason="no live-season availability file on disk")
def test_age_is_reported_not_enforced_once_the_deadline_has_passed(monkeypatch):
    """A gameweek whose deadline has passed (GW1 here, every backtest in general) has, by
    construction, the newest snapshot before its deadline: that gap is the data, and a
    zero threshold must NOT turn it into a STALE finding."""
    monkeypatch.setattr(ld, "MAX_AVAILABILITY_AGE", timedelta(0))
    findings = ld.preflight(SEASON, 1, strict=False, config="baseline", horizon=1)
    assert not [f for f in findings if "STALE" in f], findings
    notes = [f for f in findings if f.startswith("note: availability age at GW1")]
    assert notes and "deadline passed: reported, not enforced" in notes[0], findings


# ---- 5. the stamp and /health carry the measured time, not the merge's clock ----

def test_health_reports_availability_age_from_the_served_run(monkeypatch):
    """/health's availability block: asof from the run's knowledge, the age now, the
    sources and the threshold. A run stored before the fix (no sources) still reads."""
    import model_tools as mt
    asof = (datetime.now(UTC) - timedelta(hours=2, minutes=30)).replace(microsecond=0)
    run = {"knowledge": {"availability_asof": asof.isoformat(), "availability_sources": ["build_fetch"],
                         "availability_age_at_build_h": 0.01}}
    out = mt._availability_freshness(run)
    assert out["asof"] == asof.isoformat() and out["sources"] == ["build_fetch"]
    assert 2.4 <= out["age_hours"] <= 2.6, out
    assert out["max_age_hours"] == config_roles.MAX_AVAILABILITY_AGE.total_seconds() / 3600
    old = mt._availability_freshness({"knowledge": {"availability_asof": "2026-09-24T11:00:11.908177+00:00"}})
    assert old["sources"] is None and old["age_hours"] > 0


# ---- 6. /health DEGRADES on the age AT BUILD, never on the time since the build ----

def _run_with(age_at_build_h, sources=("build_fetch",), asof_hours_ago=48):
    """A latest-run row whose knowledge says how old the availability was AT BUILD. The
    asof itself is set far in the past so that the time-since-build (age_hours) is large:
    that number must never be the trigger."""
    asof = (datetime.now(UTC) - timedelta(hours=asof_hours_ago)).replace(microsecond=0)
    k = {"availability_asof": asof.isoformat(), "availability_age_at_build_h": age_at_build_h}
    if sources is not None:
        k["availability_sources"] = list(sources)
    return {"run_id": 21, "gw": 6, "kind": "nightly", "knowledge": k}


def test_health_degrades_when_the_build_scored_on_availability_older_than_the_threshold():
    """The served build scored on availability older than MAX_AVAILABILITY_AGE: one reason,
    naming the run, the measured age at build and the threshold."""
    import model_tools as mt
    limit_h = config_roles.MAX_AVAILABILITY_AGE.total_seconds() / 3600
    reasons = mt._availability_age_reasons(_run_with(limit_h + 1.5))
    assert len(reasons) == 1, reasons
    assert "run 21" in reasons[0] and f"{limit_h + 1.5:.1f} h" in reasons[0] and "MAX_AVAILABILITY_AGE" in reasons[0], reasons[0]
    assert mt._availability_age_reasons(_run_with(limit_h - 0.5)) == []
    assert mt._availability_age_reasons(_run_with(limit_h)) == [], "exactly at the threshold is not past it"


def test_health_never_degrades_on_time_since_build():
    """age_hours (now minus asof) grows every hour until the next run; it is reported, not a
    reason. A build that was fresh at build time stays green however long ago it ran."""
    import model_tools as mt
    assert mt._availability_age_reasons(_run_with(0.01, asof_hours_ago=24 * 30)) == []


def test_pre_change_runs_without_sources_are_exempt():
    """Runs stored before 2026-09-25 carry the merge clock under availability_asof and no
    availability_sources; their numbers mean something else and must not degrade health."""
    import model_tools as mt
    assert mt._availability_age_reasons(_run_with(500.0, sources=None)) == []
    assert mt._availability_age_reasons({"run_id": 19, "knowledge": {"availability_asof": "2026-09-24T11:00:11+00:00"}}) == []
    assert mt._availability_age_reasons({"run_id": 19, "knowledge": None}) == []
    assert mt._availability_age_reasons({"run_id": 19, "knowledge": "not json"}) == []
    # the JSONB may arrive as a string
    import json
    r = _run_with(500.0)
    r["knowledge"] = json.dumps(r["knowledge"])
    assert len(mt._availability_age_reasons(r)) == 1


def test_health_wires_the_availability_age_reason_on_the_latest_run():
    """health() must extend its reasons with the helper on the latest successful run, the
    way it does for the degraded-model detector; read the UNPATCHED source."""
    import inspect
    import model_tools as mt
    src = inspect.getsource(mt.health)
    assert "reasons.extend(_availability_age_reasons(last))" in src, (
        "health() does not add the availability-age reason for the served run")
