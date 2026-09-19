"""get_fixtures -- difficulty as TWO numbers, with provenance, through the agent's own entry.

Master plan 5.4 specifies "difficulty from your model, not just FPL's FDR". The whole value is
that our model has two quantities where FDR has one, so the tests hold the separation as hard
as they hold the arithmetic: anything that lets the two collapse into a single score, or that
presents a fixture-level product as an opponent rating, is a defect.

The section-14 rule, three entries deep: these drive agent.call_tool("get_fixtures", ...) --
the registered dispatch the model reaches -- not the helpers underneath it.
"""
import sys
from pathlib import Path

import pandas as pd
import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "squad"))

import explain                                     # noqa: E402
import fixtures_tool as ft                         # noqa: E402


# ------------------------------------------------------------------ fixtures

def _skel(rows):
    return pd.DataFrame(rows, columns=ft.SKELETON_COLS)


SINGLE = [
    # two clubs, one fixture each, GW6 -- the reverse side of the same match
    (1, 6, "Newcastle", 7, True, "2026-10-10T14:00:00Z"),
    (2, 6, "Coventry City", 14, False, "2026-10-10T14:00:00Z"),
    (1, 7, "Newcastle", 3, False, "2026-10-17T14:00:00Z"),
]
NAMES = {7: "Coventry City", 14: "Newcastle", 3: "Arsenal"}


@pytest.fixture()
def cal(monkeypatch):
    monkeypatch.setattr(ft, "_team_names", lambda: NAMES)
    return ft.calendar(df=_skel(SINGLE))


def _row(team, gw, tl=1.6, ol=1.2, pcs=0.30, step=0, oh=1, nfix=1):
    return {"team": team, "gw": gw, "team_lambda": tl, "opp_lambda": ol, "p_cs": pcs,
            "horizon_step": step, "odds_horizon_gws": oh, "n_fixtures": nfix}


def test_the_calendar_names_the_opponent_and_the_side(cal):
    mapping, n = cal
    assert n == 3
    assert mapping[("Newcastle", 6)][0]["opponent"] == "Coventry City"
    assert mapping[("Newcastle", 6)][0]["home"] is True
    assert mapping[("Coventry City", 6)][0]["opponent"] == "Newcastle"
    assert mapping[("Coventry City", 6)][0]["home"] is False


def test_a_double_gameweek_is_two_fixtures_not_one():
    """drop_duplicates(["team","GW"]) would hide the second leg. A fixture tool that shows
    half a double is worse than none -- the whole point of a double is that it is two."""
    rows = SINGLE + [(1, 6, "Newcastle", 9, False, "2026-10-13T19:00:00Z")]
    mapping, _ = ft.calendar(df=_skel(rows))
    assert len(mapping[("Newcastle", 6)]) == 2
    out = ft.build([_row("Newcastle", 6)], mapping, 3, team="Newcastle", gw=6)
    entry = out["fixtures"][0]
    assert entry["double_gameweek"] is True and entry["n_fixtures"] == 2


def test_a_blank_gameweek_says_so_rather_than_vanishing(cal):
    mapping, n = cal
    out = ft.build([_row("Newcastle", 6)], mapping, n, team="Newcastle", gw=9)
    e = out["fixtures"][0]
    assert e["blank_gameweek"] is True and e["fixtures"] == []


def test_difficulty_is_two_quantities_and_neither_is_a_composite(cal):
    mapping, n = cal
    out = ft.build([_row("Newcastle", 6, tl=2.24, ol=0.0006, pcs=0.9995)],
                   mapping, n, team="Newcastle", gw=6)
    d = out["fixtures"][0]["fixtures"][0]["difficulty"]
    assert set(d) >= {"attacking", "defensive"}
    assert d["attacking"]["value"] == 2.24
    assert d["defensive"]["value"] == 0.9995
    assert d["defensive"]["opp_lambda"] == 0.0006
    # and no single composite anywhere for the agent to grab
    assert not any(k in d for k in ("score", "fdr", "difficulty", "overall", "composite"))
    assert "higher is EASIER to score" in d["attacking"]["reading"]
    assert "higher is EASIER to keep a clean sheet" in d["defensive"]["reading"]


def test_the_two_can_disagree_and_both_are_reported(cal):
    """The case FDR cannot express: easy to score in, hard to keep a clean sheet."""
    mapping, n = cal
    out = ft.build([_row("Newcastle", 6, tl=2.3, ol=2.1, pcs=0.12)], mapping, n,
                   team="Newcastle", gw=6)
    d = out["fixtures"][0]["fixtures"][0]["difficulty"]
    assert d["attacking"]["band"] == "easy"
    assert d["defensive"]["band"] == "hard"


def test_the_lambdas_are_labelled_as_products_not_opponent_ratings(cal):
    mapping, n = cal
    out = ft.build([_row("Newcastle", 6)], mapping, n, team="Newcastle", gw=6)
    d = out["fixtures"][0]["fixtures"][0]["difficulty"]
    t = d["these_are_products"].lower()
    assert "product" in t or "attack_ours x defence_theirs" in t
    assert "not the opponent" in t
    assert "conflates the attacker" in t


def test_raw_lambdas_travel_alongside_so_nothing_is_hidden(cal):
    mapping, n = cal
    out = ft.build([_row("Newcastle", 6, tl=2.2366, ol=0.0006)], mapping, n,
                   team="Newcastle", gw=6)
    lam = out["fixtures"][0]["fixtures"][0]["lambdas"]
    assert lam["team_lambda"] == 2.2366 and lam["opp_lambda"] == 0.0006
    assert lam["league_average_lambda"] == explain.LEAGUE_AVG_LAMBDA


# ------------------------------------------------------------------ provenance

def test_market_priced_versus_pure_dixon_coles_is_stated(cal):
    mapping, n = cal
    step0 = ft.build([_row("Newcastle", 6, step=0, oh=1)], mapping, n, team="Newcastle", gw=6)
    p0 = step0["fixtures"][0]["fixtures"][0]["provenance"]
    assert p0["market_priced"] is True and "market odds" in p0["priced_off"]

    step3 = ft.build([_row("Newcastle", 6, step=3, oh=0)], mapping, n, team="Newcastle", gw=6)
    p3 = step3["fixtures"][0]["fixtures"][0]["provenance"]
    assert p3["market_priced"] is False
    assert "Dixon-Coles" in p3["priced_off"] and "LOWER QUALITY" in p3["priced_off"]


def test_provenance_reuses_explains_function_and_vocabulary(cal):
    mapping, n = cal
    out = ft.build([_row("Newcastle", 6, step=3, oh=0)], mapping, n, team="Newcastle", gw=6)
    p = out["fixtures"][0]["fixtures"][0]["provenance"]
    assert p["source"] in ("model", "constant")          # explain's fixed vocabulary
    assert any("fitted Dixon-Coles strengths, not the market" in x for x in p["notes"])
    src = (REPO / "fixtures_tool.py").read_text(encoding="utf-8")
    assert "from explain import" in src and "fixture_provenance" in src
    for reimplemented in ("LAMBDA_MIN", "LAMBDA_MAX", "0.15", "6.0", "x0_fixture"):
        assert reimplemented not in src, f"reimplemented rather than reused: {reimplemented}"


def test_a_neutral_fixture_is_named_as_a_constant(cal):
    mapping, n = cal
    out = ft.build([_row("Newcastle", 6, tl=explain.LEAGUE_AVG_LAMBDA,
                         ol=explain.LEAGUE_AVG_LAMBDA)], mapping, n, team="Newcastle", gw=6)
    p = out["fixtures"][0]["fixtures"][0]["provenance"]
    assert p["source"] == "constant"
    assert p["constant"] == explain.CONSTANT_LABELS["neutral_fixture"]


def test_a_runaway_fixture_is_flagged_with_explains_own_words(cal):
    mapping, n = cal
    out = ft.build([_row("Newcastle", 6, ol=0.0006, pcs=0.9995)], mapping, n,
                   team="Newcastle", gw=6)
    e = out["fixtures"][0]["fixtures"][0]
    assert e["runaway"] is True
    assert e["runaway_sides"] and e["runaway_sides"][0]["side"] == "opponent"
    assert explain.RUNAWAY_NOTE in " ".join(e["provenance"]["notes"])
    assert "KNOWN_ISSUES #25" in e["runaway_warning"]
    assert "NOT trustworthy" in e["runaway_warning"]


def test_a_clean_fixture_carries_no_runaway_text(cal):
    mapping, n = cal
    e = ft.build([_row("Newcastle", 6)], mapping, n, team="Newcastle",
                 gw=6)["fixtures"][0]["fixtures"][0]
    assert e["runaway"] is False and e["runaway_sides"] == []
    assert "runaway_warning" not in e


# ------------------------------------------------------------------ refusals

def test_past_the_model_horizon_is_null_with_a_reason_never_omitted(cal):
    mapping, n = cal
    out = ft.build([_row("Newcastle", 6)], mapping, n, team="Newcastle", gw=7)
    e = out["fixtures"][0]["fixtures"][0]
    assert e["opponent"] == "Arsenal", "the FIXTURE is still reported"
    assert e["difficulty"] is None
    assert "missing CALCULATION" in e["difficulty_unavailable"]
    assert "not" in e["difficulty_unavailable"] and "easy fixture" in e["difficulty_unavailable"]


def test_the_calendar_age_is_stamped_on_every_answer(cal):
    mapping, n = cal
    out = ft.build([_row("Newcastle", 6)], mapping, n, skeleton_age_hours=71.4)
    src = out["calendar_source"]
    assert src["age_hours"] == 71.4
    assert "WEEKLY" in src["refresh"] and "rescheduled" in src["caveat"]


def test_the_answer_says_the_two_numbers_must_not_be_averaged(cal):
    mapping, n = cal
    out = ft.build([_row("Newcastle", 6)], mapping, n)
    assert "must not be averaged" in out["difficulty_is_two_numbers"]


# ------------------------------------------------------------------ the agent's entry

@pytest.fixture()
def mt(monkeypatch):
    monkeypatch.setenv("APP_API_KEY", "x" * 48)
    import model_tools
    return model_tools


def test_team_resolution_declines_rather_than_guessing(mt):
    known = ["Newcastle", "Man Utd", "Spurs", "Nott'm Forest"]
    assert mt._resolve_team("newcastle", known) == ("Newcastle", None)
    assert mt._resolve_team("Tottenham", known) == ("Spurs", None)
    assert mt._resolve_team("Man United", known) == ("Man Utd", None)
    name, err = mt._resolve_team("Wigan", known)
    assert name is None and "not a club" in err


def test_the_agent_entry_point_is_registered_and_dispatches(monkeypatch):
    """The section-14 rule: drive what the MODEL reaches, not the helper beneath it."""
    monkeypatch.setenv("APP_API_KEY", "x" * 48)
    import agent
    names = [t["name"] for t in agent.tools_schema]
    assert "get_fixtures" in names and "get_price_movements" in names
    assert set(names) == set(agent.available_functions), "schema and dispatch map disagree"
    # Identity would be the obvious assertion and it is WRONG here: other test modules call
    # importlib.reload on `agent` and on `model_tools`, so by the time this runs the dispatch
    # map can hold a function object from an earlier incarnation of the module. Same function,
    # different object. The property worth pinning is that the map points at the REAL tool in
    # model_tools rather than a stub or a lambda, and module+qualname says that across reloads.
    fn = agent.available_functions["get_fixtures"]
    assert (fn.__module__, fn.__qualname__) == ("model_tools", "get_fixtures")

    monkeypatch.setitem(agent.available_functions, "get_fixtures",
                        lambda **k: {"ok": True, "got": k})
    out = agent.call_tool("get_fixtures", {"team": "Newcastle", "horizon": 3})
    assert out == {"ok": True, "got": {"team": "Newcastle", "horizon": 3}}


def test_a_tool_exception_becomes_an_error_result_not_a_500(monkeypatch):
    monkeypatch.setenv("APP_API_KEY", "x" * 48)
    import agent

    def boom(**k):
        raise RuntimeError("calendar gone")
    monkeypatch.setitem(agent.available_functions, "get_fixtures", boom)
    out = agent.call_tool("get_fixtures", {})
    assert "error" in out and "calendar gone" in out["error"]


def test_a_missing_calendar_is_an_error_not_an_empty_schedule(mt, monkeypatch):
    """An empty fixture list reads as 'no games'. A missing FILE must not look like that."""
    monkeypatch.setattr(mt, "_latest_run", lambda gw=None, any_status=False: {"run_id": 9})
    monkeypatch.setattr(ft, "SKELETON", REPO / "does_not_exist.parquet")
    out = mt.get_fixtures()
    assert "error" in out and "missing FILE" in out["error"]


def test_no_run_is_an_error_before_anything_else(mt, monkeypatch):
    monkeypatch.setattr(mt, "_latest_run", lambda gw=None, any_status=False: None)
    assert "error" in mt.get_fixtures()
