"""The weekly ingest runner's contract (eval/run_weekly_ingest.py). No network:
the API is a fake, the step commands are fakes that write files into a tmp data
dir, and every assertion is on the status files / markers / manifests the
runner leaves behind -- the artefacts a maintainer actually reads."""
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "eval"))

import run_weekly_ingest as wi  # noqa: E402

SEASON = "2026-27"
TAG = "2026_27"
NOW = datetime(2026, 9, 15, 9, 0, tzinfo=timezone.utc)      # a Tuesday morning
DEADLINE = datetime(2026, 9, 18, 17, 30, tzinfo=timezone.utc)


def _events(final_through=4, next_gw=5, deadline=DEADLINE):
    ev = []
    for g in range(1, 8):
        ev.append(dict(id=g, finished=g <= final_through, data_checked=g <= final_through,
                       deadline_time=(deadline + timedelta(days=7 * (g - next_gw))).strftime("%Y-%m-%dT%H:%M:%SZ")))
    return ev


def _fixtures(in_play=False):
    fx = [dict(id=1, kickoff_time="2026-09-12T14:00:00Z", finished=True, finished_provisional=True,
               team_h_score=1, team_a_score=0)]
    if in_play:
        fx.append(dict(id=2, kickoff_time="2026-09-15T08:00:00Z", finished=False,
                       finished_provisional=False, team_h_score=None, team_a_score=None))
    return fx


def _seed(data_dir, gws=(1, 2, 3), priced_played=True, crosswalk_missing=()):
    """A tiny but schema-faithful live data dir."""
    h = data_dir / "history"
    h.mkdir(parents=True)
    (data_dir / "live").mkdir()
    rows = []
    for g in gws:
        for el, nm, tm in ((1, "Erling Haaland", "Man City"), (2, "Bruno Fernandes", "Man Utd"),
                           (403, "Savio Moreira de Oliveira", "Spurs")):
            rows.append(dict(season=SEASON, GW=g, element=el, fixture=10 * g + el, name=nm, team=tm,
                             position="MID", minutes=60 if el != 2 or g > 1 else 0,
                             # the FPL per-gameweek fields the understat fallback (Prompt R2) reads
                             kickoff_time=f"2026-09-{5 + g:02d}T14:00:00Z", opponent_team=7, was_home=el == 1,
                             expected_goals="0.40", expected_assists="0.15", goals_scored=0, assists=0, key_passes=1.0,
                             own_goals=0, yellow_cards=0, red_cards=0))
    pd.DataFrame(rows).to_parquet(h / f"fpl_api_{TAG}.parquet", index=False)
    (h / f"fpl_api_{TAG}.provenance.json").write_text(json.dumps(
        {str(g): dict(live_crosscheck_mismatches=0, data_checked=True) for g in gws}))
    pd.DataFrame(rows).to_parquet(h / f"all_seasons_with_{TAG}.parquet", index=False)
    cw = pd.DataFrame([dict(element=1, understat_id="8260"), dict(element=2, understat_id="1228"),
                       dict(element=403, understat_id="11735")])
    cw = cw[~cw["element"].isin(crosswalk_missing)]
    cw.to_csv(h / f"crosswalk_{TAG}.csv", index=False)
    pd.DataFrame([dict(id="8260", player_name="Erling Haaland", team_title="Manchester City", games="3",
                       time="270", understat_season="2026"),
                  dict(id="1228", player_name="Bruno Fernandes", team_title="Manchester United", games="3",
                       time="270", understat_season="2026"),
                  dict(id="11735", player_name="Savio", team_title="Tottenham", games="1",
                       time="62", understat_season="2026")]).to_parquet(
        h / f"understat_season_aggregates_with_{TAG}.parquet", index=False)
    pd.DataFrame([dict(gw=g, match_id=f"m{g}{i}") for g in gws for i in range(3)]).to_parquet(
        h / f"understat_matches_{TAG}.parquet", index=False)
    # odds slice: 3 played fixtures (priced or not) + 2 upcoming priced
    od = pd.DataFrame([
        dict(Date="12/09/2026", HomeTeam="Man City", AwayTeam="Man United", FTHG=1.0,
             B365H=1.5 if priced_played else None, B365D=4.0 if priced_played else None,
             B365A=6.0 if priced_played else None),
        dict(Date="19/09/2026", HomeTeam="Arsenal", AwayTeam="Chelsea", FTHG=None, B365H=2.0, B365D=3.4, B365A=3.6),
    ])
    od.to_parquet(h / f"odds_fixtures_{TAG}.parquet", index=False)
    (h / f"odds_fixtures_{TAG}.provenance.json").write_text(json.dumps(dict(
        prices_preserved_from_previous_slice=1, finished=1)))
    # skeleton: fixtures the master does NOT carry
    pd.DataFrame([dict(season=SEASON, fixture=900 + i) for i in range(3)]).to_parquet(
        h / f"forward_skeleton_{TAG}.parquet", index=False)
    (h / f"forward_skeleton_{TAG}.provenance.json").write_text(json.dumps(dict(
        rows=3, fixtures_forward=3, gws_covered=[max(gws) + 1, 38], postponed_excluded=[])))
    return h


class FakeSteps:
    """Fake step executor: records the commands, writes the files a real step would,
    and can be told to fail one step or to corrupt the price carry-forward."""

    def __init__(self, h, fail_at=None, drop_prices=False, collide=False, new_gw=4, fail_scoring_gw=None,
                 fail_output=None):
        self.h, self.fail_at, self.drop_prices, self.collide, self.new_gw = h, fail_at, drop_prices, collide, new_gw
        self.fail_scoring_gw = fail_scoring_gw
        self.fail_output = fail_output
        self.requested = None
        self.calls = []

    def __call__(self, args, timeout):
        name = Path(args[0]).stem + ("_combine" if "--combine" in args else "")
        self.calls.append(name)
        if self.fail_at and name == self.fail_at:
            return 3, self.fail_output or f"{name}: boom"
        if name == "fetch_fpl_history" and "--gw" in args:
            gw = int(args[args.index("--gw") + 1])
            api = pd.read_parquet(self.h / f"fpl_api_{TAG}.parquet")
            add = api[api["GW"] == api["GW"].max()].assign(GW=gw, fixture=lambda d: d["element"] + 10 * gw)
            api = pd.concat([api[api["GW"] != gw], add], ignore_index=True)
            api.to_parquet(self.h / f"fpl_api_{TAG}.parquet", index=False)
            prov = json.loads((self.h / f"fpl_api_{TAG}.provenance.json").read_text())
            prov[str(gw)] = dict(live_crosscheck_mismatches=0, data_checked=True)
            (self.h / f"fpl_api_{TAG}.provenance.json").write_text(json.dumps(prov))
        if name == "fetch_fpl_history_combine":
            pd.read_parquet(self.h / f"fpl_api_{TAG}.parquet").to_parquet(
                self.h / f"all_seasons_with_{TAG}.parquet", index=False)
        if name == "fetch_fixtures":
            od = pd.read_parquet(self.h / f"odds_fixtures_{TAG}.parquet")
            if self.drop_prices:
                od.loc[od["FTHG"].notna(), ["B365H", "B365D", "B365A"]] = None
            od.to_parquet(self.h / f"odds_fixtures_{TAG}.parquet", index=False)
        if name == "build_forward_skeleton":
            fx = [900 + i for i in range(3)]
            if self.collide:
                api = pd.read_parquet(self.h / f"fpl_api_{TAG}.parquet")
                fx = [int(api["fixture"].iloc[0])] + fx
            pd.DataFrame([dict(season=SEASON, fixture=f) for f in fx]).to_parquet(
                self.h / f"forward_skeleton_{TAG}.parquet", index=False)
            (self.h / f"forward_skeleton_{TAG}.provenance.json").write_text(json.dumps(dict(
                rows=len(fx), fixtures_forward=len(fx), gws_covered=[self.new_gw + 1, 38], postponed_excluded=[])))
        out = f"{name} ok"
        if name == "fetch_live_odds":
            out = "-> slice: 20/20 events priced (thin-panel unpriced: 0); credits remaining 19300"
        if name == "build_crosswalk":
            out = "  matched 3\n  pct_minutes_covered 100.0\n  audit_hard_disagreements 0"
        if name == "score_squads":
            req = json.loads(Path(args[args.index("--request") + 1]).read_text())
            self.requested = sorted(int(g) for g in req["deadlines"])
            if self.fail_scoring_gw is not None:
                return 1, (f"GW{self.fail_scoring_gw}: FAILED [inconsistent_versions] versions record 0 "
                           "paid transfer(s) but 3 transfers against an allowance of 2 implies 1")
            out = ("GW1: no squad at deadline 2026-08-15T17:30:00Z (first version 2026-09-12) -- nothing to score\n"
                   f"GW{self.new_gw}: scored 61 pts (raw 65, hit 4; armband captain Erling Haaland (411) +9; "
                   "autosubs none; bench 6) for version 1, transfers 2 vs allowance 1 -> score_id 1\n"
                   "score_squads: 1 row(s) written")
        return 0, out


def _runner(tmp_path, steps, events=None, fixtures=None):
    api = {"/bootstrap-static/": {"events": events or _events()}, "/fixtures/": fixtures or _fixtures()}
    return wi.Runner(SEASON, data_dir=tmp_path, run_cmd=steps, fetch_json=lambda p: api[p])


# ---------------------------------------------------------------- the plan
def test_nothing_new_when_every_final_gw_is_ingested(tmp_path):
    _seed(tmp_path, gws=(1, 2, 3, 4))
    R = _runner(tmp_path, FakeSteps(tmp_path / "history"))
    assert R.decide(now=NOW) == "NOTHING-NEW"
    assert R.todo == []


def test_final_uningested_gw_is_todo(tmp_path):
    _seed(tmp_path, gws=(1, 2, 3))
    R = _runner(tmp_path, FakeSteps(tmp_path / "history"))
    assert R.decide(now=NOW) == "RUN"
    assert R.todo == [4]


def test_not_yet_data_checked_gw_is_not_todo(tmp_path):
    """The data_checked gate, applied before any step runs: GW4 finished but not
    checked -> nothing to do, no fetch attempted."""
    _seed(tmp_path, gws=(1, 2, 3))
    ev = _events(final_through=3)
    ev[3]["finished"] = True                      # finished, data_checked False
    steps = FakeSteps(tmp_path / "history")
    R = _runner(tmp_path, steps, events=ev)
    assert R.decide(now=NOW) == "NOTHING-NEW"
    assert steps.calls == []


def test_deadline_window_defers_the_work(tmp_path):
    _seed(tmp_path, gws=(1, 2, 3))
    R = _runner(tmp_path, FakeSteps(tmp_path / "history"))
    assert R.decide(now=DEADLINE - timedelta(minutes=95)) == "DEFERRED"     # T-95: inside deadline-3h
    assert "deadline window" in R.detail["reason"]
    assert R.decide(now=DEADLINE + timedelta(minutes=30)) == "DEFERRED"     # +30: the build/Postgres write
    assert R.decide(now=DEADLINE + timedelta(hours=2)) == "RUN"             # clear of it


def test_in_play_match_defers(tmp_path):
    _seed(tmp_path, gws=(1, 2, 3))
    R = _runner(tmp_path, FakeSteps(tmp_path / "history"), fixtures=_fixtures(in_play=True))
    assert R.decide(now=NOW) == "DEFERRED"
    assert "past kickoff without a score" in R.detail["reason"]


# ---------------------------------------------------------------- the chain
def test_success_runs_the_runbook_order_and_writes_status(tmp_path):
    h = _seed(tmp_path, gws=(1, 2, 3))
    steps = FakeSteps(h)
    R = _runner(tmp_path, steps)
    assert R.decide(now=NOW) == "RUN"
    R.run_chain()
    first = R.write_status()
    assert first == "SUCCESS"
    assert steps.calls == ["fetch_fpl_history", "fetch_fpl_history_combine", "understat_matches",
                           "build_understat_aggregates", "build_understat_aggregates_combine",
                           "build_crosswalk", "fetch_fixtures", "fetch_fixtures_combine",
                           "fetch_live_odds", "build_forward_skeleton", "score_squads"]
    txt = (tmp_path / "live" / "INGEST_STATUS.txt").read_text()
    assert txt.splitlines()[0] == "SUCCESS"
    assert "SQUAD SCORES (hypothetical squad; operational evidence only -- rule 1)" in txt
    assert "GW4: scored 61 pts" in txt
    assert steps.requested == [1, 2, 3, 4]                  # every ingested gw, with its deadline
    assert not (tmp_path / "live" / "scoring_attempts.json").exists()
    assert "PRICES (preserved across the rebuild)" in txt
    assert "played fixtures priced before 1 / after 1, all 1 identical" in txt
    assert "credits remaining 19300" in txt
    assert "collision check vs master: OK" in txt
    assert "INPUT HASHES" in txt
    assert (tmp_path / "live" / "INGEST_GW4_STATUS.txt").exists()
    assert not (tmp_path / "live" / "ingest_gw4.partial.json").exists()


def test_step_failure_stops_the_chain_and_leaves_the_gw_eligible(tmp_path):
    """Exit code is law: the crosswalk step fails -> nothing after it runs, FAILED status,
    the attempt is counted, and the partial marker keeps GW4 eligible on the next
    tick even though its rows are already in the season file. (Until Prompt R2 this test
    failed the understat step; that step alone now falls back to FPL xG -- see
    test_understat_failure_falls_back_to_fpl_rows_and_the_chain_completes_degraded -- so the
    same contract is asserted on the next step whose exit code is still law.)"""
    h = _seed(tmp_path, gws=(1, 2, 3))
    steps = FakeSteps(h, fail_at="build_crosswalk")
    R = _runner(tmp_path, steps)
    R.decide(now=NOW)
    first = R.execute()
    assert first == "FAILED"
    assert steps.calls == ["fetch_fpl_history", "fetch_fpl_history_combine", "understat_matches",
                           "build_understat_aggregates", "build_understat_aggregates_combine", "build_crosswalk"]
    txt = (tmp_path / "live" / "INGEST_STATUS.txt").read_text()
    assert txt.startswith("FAILED\n")
    assert "step 'build_crosswalk' exited 3" in txt
    assert "skeleton may be STALE" in txt
    assert json.loads((tmp_path / "live" / "ingest_gw4.attempts.json").read_text())["attempts"] == 1
    assert (tmp_path / "live" / "ingest_gw4.partial.json").exists()
    # next tick: GW4 is in the season file now, but the partial marker keeps it todo
    R2 = _runner(tmp_path, FakeSteps(h))
    assert R2.decide(now=NOW) == "RUN"
    assert R2.todo == [4]


def test_attempt_budget_gives_up_loudly(tmp_path):
    h = _seed(tmp_path, gws=(1, 2, 3))
    (tmp_path / "live" / "ingest_gw4.attempts.json").write_text(json.dumps(dict(attempts=wi.MAX_ATTEMPTS)))
    steps = FakeSteps(h)
    R = _runner(tmp_path, steps)
    R.decide(now=NOW)
    assert R.execute() == "FAILED"
    assert steps.calls == []
    assert "giving up" in (tmp_path / "live" / "INGEST_STATUS.txt").read_text()


def test_prices_lost_is_a_strict_stop(tmp_path):
    """The 2026-09-11 finding: a rebuild that nulls a played gameweek's prices
    must FAIL the run, never be patched around."""
    h = _seed(tmp_path, gws=(1, 2, 3))
    R = _runner(tmp_path, FakeSteps(h, drop_prices=True))
    R.decide(now=NOW)
    assert R.execute() == "FAILED"
    assert "PRICES LOST" in (tmp_path / "live" / "INGEST_STATUS.txt").read_text()


def test_skeleton_collision_is_a_strict_stop(tmp_path):
    h = _seed(tmp_path, gws=(1, 2, 3))
    R = _runner(tmp_path, FakeSteps(h, collide=True))
    R.decide(now=NOW)
    assert R.execute() == "FAILED"
    assert "SKELETON STALE" in (tmp_path / "live" / "INGEST_STATUS.txt").read_text()


# ---------------------------------------------------------------- what a human must see
def test_unmatched_with_minutes_is_an_action_required_block_first(tmp_path):
    """Savio's case: real minutes, no id -> named in the status file ABOVE every
    other section, with his Understat candidate and the MANUAL prompt."""
    h = _seed(tmp_path, gws=(1, 2, 3), crosswalk_missing=(403,))
    R = _runner(tmp_path, FakeSteps(h))
    R.decide(now=NOW)
    first = R.execute()
    assert first.startswith("SUCCESS -- ACTION REQUIRED (1 item")
    txt = (tmp_path / "live" / "INGEST_STATUS.txt").read_text()
    act = txt.index("== ACTION REQUIRED: crosswalk")
    assert act < txt.index("== PRICES")          # before every ordinary section
    assert "element 403" in txt and "Savio Moreira de Oliveira" in txt
    assert "candidate  11735 Savio" in txt and "Tottenham" in txt
    assert "MANUAL entry" in txt


def test_unmatched_is_relisted_on_a_no_work_tick(tmp_path):
    """The prompt stays visible on every tick until a human closes it."""
    _seed(tmp_path, gws=(1, 2, 3, 4), crosswalk_missing=(403,))
    R = _runner(tmp_path, FakeSteps(tmp_path / "history"))
    assert R.decide(now=NOW) == "NOTHING-NEW"
    items = R.outstanding_actions()
    assert [i["element"] for i in items] == [403]
    assert items[0]["candidates"][0]["id"] == "11735"


def test_changed_id_is_the_alarm(tmp_path):
    h = _seed(tmp_path, gws=(1, 2, 3))

    class Swap(FakeSteps):
        def __call__(self, args, timeout):
            code, out = super().__call__(args, timeout)
            if Path(args[0]).stem == "build_crosswalk":
                cw = pd.read_csv(self.h / f"crosswalk_{TAG}.csv", dtype={"understat_id": str})
                cw.loc[cw["element"] == 2, "understat_id"] = "9999"
                cw.to_csv(self.h / f"crosswalk_{TAG}.csv", index=False)
            return code, out
    R = _runner(tmp_path, Swap(h))
    R.decide(now=NOW)
    assert R.execute().startswith("SUCCESS -- ACTION REQUIRED")
    txt = (tmp_path / "live" / "INGEST_STATUS.txt").read_text()
    assert "id CHANGED or LOST" in txt and "CHANGED element 2: 1228 -> 9999" in txt


# ---------------------------------------------------------------- hashes
def test_manifest_hashes_every_live_input_before_and_after(tmp_path):
    h = _seed(tmp_path, gws=(1, 2, 3))
    R = _runner(tmp_path, FakeSteps(h))
    R.decide(now=NOW)
    R.execute()
    man = json.loads((tmp_path / "live" / "ingest_manifest_latest.json").read_text())
    assert man["gws_ingested"] == [4]
    assert set(man) >= {"before", "after", "changed", "git", "host"}
    a = man["after"][f"history/fpl_api_{TAG}.parquet"]
    assert len(a["sha256"]) == 64 and a["content"]["rows"] == 12
    assert f"history/fpl_api_{TAG}.parquet" in man["changed"]
    assert man["before"][f"history/crosswalk_{TAG}.csv"]["content"]["digest"] == \
        man["after"][f"history/crosswalk_{TAG}.csv"]["content"]["digest"]   # untouched -> identical


def test_content_digest_is_order_independent_and_byte_independent(tmp_path):
    df = pd.DataFrame(dict(a=[1, 2, 3], b=["x", "y", "z"]))
    p1, p2 = tmp_path / "one.parquet", tmp_path / "two.parquet"
    df.to_parquet(p1, index=False)
    df.iloc[::-1][["b", "a"]].to_parquet(p2, index=False)          # rows and columns reordered
    assert wi.content_digest(p1)["digest"] == wi.content_digest(p2)["digest"]
    assert wi.compare_manifests({"f": dict(sha256="1", content=wi.content_digest(p1))},
                                {"f": dict(sha256="2", content=wi.content_digest(p2))}) == \
        [("f", "bytes differ, content identical")]
    df.assign(a=[1, 2, 4]).to_parquet(p2, index=False)
    assert wi.content_digest(p1)["digest"] != wi.content_digest(p2)["digest"]


def test_status_first_line_contract():
    """The first token is machine-readable: SUCCESS / FAILED / NOTHING-NEW / DEFERRED."""
    assert wi.plan(_events(final_through=3), _fixtures(), {1, 2, 3}, set(), NOW)[0] == "NOTHING-NEW"
    assert wi.plan(_events(final_through=4), _fixtures(), {1, 2, 3}, set(), NOW)[0] == "RUN"
    assert wi.plan(_events(final_through=4), _fixtures(), {1, 2, 3, 4}, {4}, NOW)[0] == "RUN"   # partial
    assert wi.plan(_events(final_through=4), _fixtures(), {1, 2, 3}, set(),
                   DEADLINE - timedelta(hours=1))[0] == "DEFERRED"


def test_content_digest_ignores_writer_timestamps(tmp_path):
    """understat_matches stamps pulled_at into every row: two pulls of the same
    matches must digest identically, or every run 'changes' the file."""
    p1, p2 = tmp_path / "a.parquet", tmp_path / "b.parquet"
    pd.DataFrame(dict(gw=[1, 2], pulled_at=["2026-09-11T22:00", "2026-09-11T22:00"])).to_parquet(p1, index=False)
    pd.DataFrame(dict(gw=[1, 2], pulled_at=["2026-09-12T04:00", "2026-09-12T04:00"])).to_parquet(p2, index=False)
    assert wi.content_digest(p1)["digest"] == wi.content_digest(p2)["digest"]
    assert wi.content_digest(p1)["cols"] == 1


# ----------------------------------------------------------------------------- Prompt R2: the understat fallback
MAINTENANCE_OUT = ("Traceback (most recent call last):\n  File \"/app/eval/understat_matches.py\", line 77, in _fetch_json\n"
                   "    return json.loads(raw.decode(\"utf-8\"))\njson.decoder.JSONDecodeError: Expecting value: line 1 column 1 (char 0)")
TIMEOUT_OUT = ("Traceback (most recent call last):\n  File \"/app/eval/understat_matches.py\", line 74, in _fetch_json\n"
               "urllib.error.URLError: <urlopen error timed out>")


def _api(p):
    return {"/bootstrap-static/": {"events": _events()}, "/fixtures/": _fixtures()}[p]


@pytest.mark.parametrize("out", [MAINTENANCE_OUT, TIMEOUT_OUT], ids=["maintenance-html", "timeout"])
def test_understat_failure_falls_back_to_fpl_rows_and_the_chain_completes_degraded(tmp_path, out):
    """2026-11-03: understat.com answered a maintenance page (and, before the DNS caught up, timed out); the chain
    died at step 2 and every strict build after it died on the stale skeleton. Now: the understat step's failure
    writes GW4's per-match rows from the FPL season file (C1: npxG := FPL xG, xA := FPL xA), the aggregates steps
    are skipped (they need understat too), the rest of the runbook runs, the run is SUCCESS -- DEGRADED, the markers
    are cleared, and the manifest names the fallback gameweeks for the build's knowledge block."""
    import understat_fallback as usf
    h = _seed(tmp_path, gws=(1, 2, 3))
    steps = FakeSteps(h, fail_at="understat_matches", fail_output=out)
    R = _runner(tmp_path, steps)
    assert R.decide(now=NOW) == "RUN"
    first = R.execute()
    assert first == "SUCCESS -- DEGRADED (understat fallback for GW[4])"
    assert steps.calls == ["fetch_fpl_history", "fetch_fpl_history_combine", "understat_matches",
                           "build_crosswalk", "fetch_fixtures", "fetch_fixtures_combine",
                           "fetch_live_odds", "build_forward_skeleton", "score_squads"]
    us = pd.read_parquet(h / f"understat_matches_{TAG}.parquet")
    assert sorted(us["gw"].unique().tolist()) == [1, 2, 3, 4]
    assert (us[us["gw"] == 4]["match_id"].str.startswith("fpl")).all() and len(us[us["gw"] == 4]) == 3
    assert us[us["gw"] == 4]["npxG"].tolist() == pytest.approx([0.40, 0.40, 0.40])
    assert usf.fallback_gws(tmp_path, SEASON) == [4]
    txt = (tmp_path / "live" / "INGEST_STATUS.txt").read_text()
    assert txt.splitlines()[0] == first
    assert "DEGRADED" in txt and "fpl_fallback" in txt and "step 'understat_matches' exited 3" in txt
    assert "collision check vs master: OK" in txt
    assert not (tmp_path / "live" / "ingest_gw4.partial.json").exists()
    assert not (tmp_path / "live" / "ingest_gw4.attempts.json").exists()
    man = json.loads((tmp_path / "live" / "ingest_manifest_latest.json").read_text())
    assert man["understat_fallback_gws"] == [4]
    # the next tick has nothing to do: GW4 counts as ingested
    R2 = _runner(tmp_path, FakeSteps(h))
    assert R2.decide(now=NOW) == "NOTHING-NEW"


def test_success_path_is_unchanged_when_understat_works(tmp_path):
    """The fallback never runs when the understat step succeeds: the per-match file's bytes are what the step left,
    no sidecar is written, the manifest's fallback list is empty, and the status is plain SUCCESS."""
    import understat_fallback as usf
    h = _seed(tmp_path, gws=(1, 2, 3))
    before = (h / f"understat_matches_{TAG}.parquet").read_bytes()
    R = _runner(tmp_path, FakeSteps(h))
    R.decide(now=NOW)
    assert R.execute() == "SUCCESS"
    assert (h / f"understat_matches_{TAG}.parquet").read_bytes() == before
    assert not usf.sidecar_path(tmp_path, SEASON).exists()
    assert json.loads((tmp_path / "live" / "ingest_manifest_latest.json").read_text())["understat_fallback_gws"] == []
    assert "DEGRADED" not in (tmp_path / "live" / "INGEST_STATUS.txt").read_text()


def test_a_failure_after_the_fallback_is_still_a_failure(tmp_path):
    """The fallback covers understat only; a later step's exit code is still law (FAILED, markers kept)."""
    h = _seed(tmp_path, gws=(1, 2, 3))
    inner = FakeSteps(h, fail_at="fetch_live_odds")

    def both(args, timeout):
        if Path(args[0]).stem == "understat_matches":
            return 1, MAINTENANCE_OUT
        return inner(args, timeout)
    R = wi.Runner(SEASON, data_dir=tmp_path, run_cmd=both, fetch_json=_api)
    R.decide(now=NOW)
    assert R.execute() == "FAILED"
    assert (tmp_path / "live" / "ingest_gw4.partial.json").exists()


# ---------------------------------------------------------------- Prompt U1: the not-listed allowance
def test_not_listed_allowance_suppresses_the_action_until_it_expires(tmp_path, monkeypatch):
    """An element Understat has not listed yet, evidenced in build_crosswalk.NOT_LISTED, is NOT an ACTION
    REQUIRED item while understat is down (fallback rows on file) and the date has not passed; the status
    carries a CROSSWALK note instead. The item returns when the date passes or understat is restored."""
    import build_crosswalk as bc
    h = _seed(tmp_path, gws=(1, 2, 3, 4), crosswalk_missing=(403,))
    um = pd.read_parquet(h / f"understat_matches_{TAG}.parquet")
    pd.concat([um, pd.DataFrame([dict(gw=4, match_id="fpl41")])]).to_parquet(
        h / f"understat_matches_{TAG}.parquet", index=False)              # a fallback row: understat is down
    later = (NOW + timedelta(days=30)).date().isoformat()
    monkeypatch.setitem(bc.NOT_LISTED, SEASON,
                        {403: ("Savio Moreira de Oliveira; Spurs MID; not listed yet (test evidence)", later)})
    R = _runner(tmp_path, FakeSteps(h))
    assert R.decide(now=NOW) == "NOTHING-NEW"
    assert R.outstanding_actions() == []
    assert R.actions == []
    assert any(t.startswith("CROSSWALK -- not listed") and "element 403" in x and later in x
               for t, x in R.sections)
    # the date has passed -> the item is back
    monkeypatch.setitem(bc.NOT_LISTED, SEASON,
                        {403: ("Savio (test)", (NOW - timedelta(days=1)).date().isoformat())})
    R2 = _runner(tmp_path, FakeSteps(h))
    R2.decide(now=NOW)
    assert [i["element"] for i in R2.outstanding_actions()] == [403]
    assert len(R2.actions) == 1
    # understat restored (no fallback rows left) -> the item is back
    monkeypatch.setitem(bc.NOT_LISTED, SEASON, {403: ("Savio (test)", later)})
    um.to_parquet(h / f"understat_matches_{TAG}.parquet", index=False)
    R3 = _runner(tmp_path, FakeSteps(h))
    R3.decide(now=NOW)
    assert [i["element"] for i in R3.outstanding_actions()] == [403]
