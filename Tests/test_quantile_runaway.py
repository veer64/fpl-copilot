"""A runaway fixture must reach the QUANTILE answer, not just explain_prediction.

On 2026-09-18 quantiles.py imported explain's vocabulary -- CONSTANT_LABELS, CS_PTS, GOAL_PTS,
PEN_FALLBACK -- and none of its detection. explain_prediction flagged a runaway strength on a
row while the quantile block built from the SAME row said nothing, and the simulation sampled a
99.94% clean sheet as though it were real: Malick Thiaw at GW6 came out P10/P50/P90 = 5/6/12, a
manufactured near-certain floor. 338 of 3,954 rows carried the condition.

These tests hold two properties:
  1. The detection is SHARED. quantiles and model_tools must call explain.fixture_runaway, so a
     change to the bound can never make the two disagree again.
  2. The answer-level fidelity block comes from the rows that HAVE the condition. It used to
     come from the largest-sampling-residual row, which was arbitrary -- sampling noise is
     bounded and reported per row, so the noisiest row is not the most fragile one.
"""
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

import explain                                 # noqa: E402
import quantiles as qt                         # noqa: E402


def _row(gw=6, team="Newcastle", tl=1.9, ol=0.0006, pcs=0.9994, **kw):
    r = {"gw": gw, "position": "DEF", "team": team, "team_lambda": tl, "opp_lambda": ol,
         "p_cs": pcs, "exp_bonus": 0.0, "e_pen_goals": 0.0,
         "q_p10": 5.0, "q_p50": 6.0, "q_p90": 12.0, "q_sd": 2.4,
         "q_resid_sampling": 0.004, "q_resid_structural": -0.0155, "q_tolerance": 0.05,
         "q_method_version": "mc-1", "q_minutes_shape": "MS-1", "q_draws": 20000,
         "q_degenerate": False}
    r.update(kw)
    return r


CLEAN = dict(tl=1.9, ol=1.24, pcs=0.29)


# ---------------------------------------------------------------- 1. shared detection

def test_quantiles_uses_explains_detection_and_not_a_second_copy():
    src = (REPO / "quantiles.py").read_text(encoding="utf-8")
    assert "fixture_runaway" in src and "from explain import" in src
    fn = src.split("def fidelity")[1]
    assert "fixture_runaway(row)" in fn, "fidelity must CALL the shared check"
    for reimplemented in ("LAMBDA_MIN", "LAMBDA_MAX", "0.15", "6.0"):
        assert reimplemented not in fn, f"the bound is reimplemented here: {reimplemented}"


def test_model_tools_uses_explains_detection_too():
    src = (REPO / "model_tools.py").read_text(encoding="utf-8")
    fn = src.split("def _quantile_block")[1].split("\ndef ")[0]
    assert "from explain import fixture_runaway" in fn
    assert "fixture_runaway(r)" in fn
    for reimplemented in ("LAMBDA_MIN", "LAMBDA_MAX"):
        assert reimplemented not in fn, f"the bound is reimplemented here: {reimplemented}"


def test_moving_the_bound_moves_both(monkeypatch):
    """The point of sharing: widen explain's box and the quantile flag follows."""
    r = _row(ol=0.0006)
    assert qt.fidelity(r)["runaway_fixture"] is True
    monkeypatch.setattr(explain, "LAMBDA_MIN", 0.0001)
    assert qt.fidelity(r)["runaway_fixture"] is False, "quantiles kept its own copy of the bound"


# ---------------------------------------------------------------- 2. fidelity() says it

def test_a_runaway_row_is_flagged_in_fidelity():
    f = qt.fidelity(_row())
    assert f["runaway_fixture"] is True
    assert f["p10_is_unsafe_when_runaway"] is True
    assert "KNOWN_ISSUES #25" in f["runaway_note"]
    assert "0.0006" in f["runaway_note"], "the lambda must be named"


def test_the_words_are_explains_words_not_a_paraphrase():
    """Same condition, same sentence, wherever the reader meets it."""
    assert explain.RUNAWAY_NOTE in qt.fidelity(_row())["runaway_note"]
    assert explain.RUNAWAY_NOTE in qt.fidelity(_row())["p10_caveat"]


def test_it_is_the_fourth_fragility_and_the_other_three_stay():
    f = qt.fidelity(_row())
    assert len(f["fragilities"]) == 4
    assert [x["n"] for x in f["fragilities"]] == [1, 2, 3, 4]
    assert [x["affects"] for x in f["fragilities"]] == ["P90", "P90", "P90", "P10"]
    assert f["fragilities"][3]["term"] == "runaway fixture"
    assert {x["term"] for x in f["fragilities"][:3]} == {"bonus", "penalties", "minutes shape"}


def test_a_clean_row_has_three_fragilities_and_no_runaway_text():
    f = qt.fidelity(_row(**CLEAN))
    assert f["runaway_fixture"] is False
    assert len(f["fragilities"]) == 3
    assert f["runaway_note"] is None and f["runaway_sides"] == []
    assert "#25" not in f["p10_caveat"] and "manufactured" not in f["summary"]


def test_the_p10_caveat_says_a_floor_is_more_dangerous_than_a_ceiling():
    """The ranking is the point, not decoration: a reader trusts a floor when judging SAFE."""
    c = qt.fidelity(_row())["p10_caveat"].lower()
    assert "not a floor you can rely on" in c
    assert "safe" in c and "ceiling" in c
    assert "unusable" in c


def test_the_club_is_named_when_the_frame_carries_it_and_never_guessed():
    own = qt.fidelity(_row(team="Coventry City", tl=0.0006, ol=1.7, pcs=0.18))
    assert "Coventry City (own team) at lambda 0.0006" in own["runaway_note"]
    opp = qt.fidelity(_row())
    assert "the opponent at lambda 0.0006" in opp["runaway_note"]
    assert "Newcastle" not in opp["runaway_note"], "the player's own club is not the opponent"
    assert opp["runaway_sides"][0]["club"] is None, "the opponent's name is not in the frame"


def test_both_sides_running_off_are_both_reported():
    f = qt.fidelity(_row(team="Coventry City", tl=0.0006, ol=0.0006, pcs=0.99))
    assert len(f["runaway_sides"]) == 2
    assert "Coventry City (own team)" in f["runaway_note"] and "the opponent" in f["runaway_note"]


def test_a_lambda_above_the_box_counts_too():
    assert qt.fidelity(_row(tl=7.4, ol=1.1, pcs=0.3))["runaway_fixture"] is True


# ---------------------------------------------------------------- 3. the answer-level block

@pytest.fixture()
def mt():
    import model_tools
    return model_tools


def _mixed():
    """GW6 and GW8 face the runaway club; GW7 and GW9 do not. GW9 is the noisiest row --
    under the old rule IT would have spoken for the answer, and it is clean."""
    return [_row(gw=6, ol=0.0006, pcs=0.9994, q_resid_sampling=0.001),
            _row(gw=7, q_resid_sampling=0.002, **CLEAN),
            _row(gw=8, ol=0.0006, pcs=0.9991, q_resid_sampling=0.003),
            _row(gw=9, q_resid_sampling=0.049, **CLEAN)]


def test_every_per_gw_entry_carries_the_flag(mt):
    per = mt._quantile_block(_mixed())["per_gw"]
    assert [p["gw"] for p in per] == [6, 7, 8, 9]
    assert [p["runaway"] for p in per] == [True, False, True, False]
    assert [p["p10_unusable"] for p in per] == [True, False, True, False]
    assert per[0]["runaway_sides"] and per[1]["runaway_sides"] == []


def test_the_answer_block_comes_from_an_affected_row_not_the_noisiest(mt):
    q = mt._quantile_block(_mixed())
    f = q["fidelity"]
    assert f["source_gw"] == 6, "the earliest AFFECTED gameweek, not GW9's largest residual"
    assert f["runaway_in_horizon"] is True
    assert f["runaway_gws"] == [6, 8]
    assert f["p10_unusable_gws"] == [6, 8]
    assert len(f["fragilities"]) == 4


def test_the_caveat_is_scoped_to_the_affected_gameweeks(mt):
    c = mt._quantile_block(_mixed())["fidelity"]["p10_caveat"]
    assert c.startswith("Applies to GW6, GW8 only, not the whole horizon.")


def test_an_all_runaway_horizon_is_not_scoped_down(mt):
    rows = [_row(gw=g, ol=0.0006) for g in (6, 7)]
    f = mt._quantile_block(rows)["fidelity"]
    assert f["runaway_gws"] == [6, 7]
    assert not f["p10_caveat"].startswith("Applies to"), "nothing to scope: every row is affected"


def test_a_clean_horizon_falls_back_to_the_earliest_gameweek_deterministically(mt):
    rows = [_row(gw=g, q_resid_sampling=s, **CLEAN)
            for g, s in ((6, 0.001), (7, 0.048), (8, 0.002))]
    f = mt._quantile_block(rows)["fidelity"]
    assert f["runaway_in_horizon"] is False and f["runaway_gws"] == []
    assert f["source_gw"] == 6, "deterministic, not whichever row happened to be noisiest"
    assert "none is affected" in f["source_rule"]


def test_row_order_does_not_change_the_answer(mt):
    rows = _mixed()
    a = mt._quantile_block(rows)["fidelity"]
    b = mt._quantile_block(list(reversed(rows)))["fidelity"]
    assert (a["source_gw"], a["runaway_gws"]) == (b["source_gw"], b["runaway_gws"])


def test_a_run_without_quantiles_still_says_nothing_about_runaways(mt):
    """`computed: false` is a missing CALCULATION; it must not grow a silent flag."""
    q = mt._quantile_block([{"gw": 6, "q_p50": None}])
    assert q["computed"] is False and q["per_gw"] == []


# ---------------------------------------------------------------- 4. the prompt

def test_the_prompt_tells_the_agent_to_lead_with_it():
    p = (REPO / "prompts" / "system_prompt.md").read_text(encoding="utf-8")
    line = [l for l in p.splitlines() if "`runaway`" in l]
    assert len(line) == 1, "exactly one rule, in the quantiles section"
    line = line[0]
    for needed in ("P10 is unusable", "KNOWN_ISSUES #25", "runaway_gws", "manufactured", "SAFE"):
        assert needed in line, needed


# ------------------------------------------- 5. the wiring: the flag needs its INPUTS selected

def test_the_read_selects_the_lambdas_or_the_flag_is_dead_on_arrival(mt):
    """Caught before deploy, not after: fidelity() and _quantile_block() were correct while
    get_prediction's SELECT named neither lambda, so fixture_runaway() would have seen no
    lambdas and answered False on all 338 affected rows. A flag that cannot see its input is
    worse than no flag -- it reads as 'checked, and fine'."""
    for c in ("team_lambda", "opp_lambda"):
        assert c in mt.PRED_OPTIONAL_COLS, c
        assert c in mt.PRED_INTERNAL_COLS, f"{c} is an input to a flag, not a prediction"
    cols = mt._prediction_columns({"gw", "e_points", "team_lambda", "opp_lambda"})
    assert "team_lambda" in cols and "opp_lambda" in cols


def test_the_lambdas_are_stripped_from_the_predictions_payload(monkeypatch, mt):
    """They are selected to be tested, not to be read: a raw strength parameter presented
    beside e_points invites the agent to quote it as a prediction."""
    row = _row(gw=6, ol=0.0006, horizon_step=1, e_points=4.2, e_minutes=80.0, p_start=0.9,
               p_60plus=0.85, e_assists=0.1, e_goals=0.05, q_distinct=40)
    monkeypatch.setattr(mt, "_latest_run", lambda gw=None, any_status=False: {"run_id": 9})
    monkeypatch.setattr(mt, "_run_meta", lambda run: {"run_id": 9})
    monkeypatch.setattr(mt, "_table_columns", lambda t, ttl=None: set(row) | {"team_lambda"})
    monkeypatch.setattr(mt, "_q", lambda sql, params=(): (
        [{"team": "Newcastle"}] if "players_live" in sql else [dict(row)]))
    out = mt.get_prediction(411)
    p0 = out["predictions"][0]
    assert "team_lambda" not in p0 and "opp_lambda" not in p0 and "team" not in p0
    assert out["team"] == "Newcastle", "the club is named once, at the top of the answer"
    assert out["quantiles"]["per_gw"][0]["runaway"] is True, "the flag still sees the lambdas"


def test_a_failed_club_lookup_cannot_break_the_prediction(monkeypatch, mt):
    """A cosmetic lookup must never be able to take a prediction down -- the 2026-09-18
    lesson, applied forward rather than after."""
    row = _row(gw=6, tl=0.0006, ol=1.7, pcs=0.18, horizon_step=1, e_points=4.2,
               e_minutes=80.0, p_start=0.9, p_60plus=0.85, e_goals=0.05, e_assists=0.1)

    def q(sql, params=()):
        if "players_live" in sql:
            raise RuntimeError("players_live is gone")
        return [dict(row)]
    monkeypatch.setattr(mt, "_latest_run", lambda gw=None, any_status=False: {"run_id": 9})
    monkeypatch.setattr(mt, "_run_meta", lambda run: {"run_id": 9})
    monkeypatch.setattr(mt, "_table_columns", lambda t, ttl=None: set(row) | {"team_lambda"})
    monkeypatch.setattr(mt, "_q", q)
    out = mt.get_prediction(411)                      # must NOT raise
    assert out["team"] is None
    f = out["quantiles"]["fidelity"]
    assert f["runaway_fixture"] is True, "the flag does not depend on the club being named"
    assert "this player's own club" in f["runaway_note"], "described, never guessed"


def test_the_flag_survives_a_schema_without_the_lambda_columns(mt):
    """Pre-migration or a trimmed read: absent lambdas must read as 'not checkable', which
    fixture_runaway reports as False -- and no exception."""
    cols = mt._prediction_columns({"gw", "e_points"})
    assert "team_lambda" not in cols
    bare = {"gw": 6, "q_p50": 6.0, "q_p10": 5.0, "q_p90": 12.0, "q_sd": 2.0,
            "q_resid_sampling": 0.0, "q_resid_structural": 0.0, "q_tolerance": 0.05}
    q = mt._quantile_block([bare])
    assert q["per_gw"][0]["runaway"] is False
    assert q["fidelity"]["runaway_in_horizon"] is False
