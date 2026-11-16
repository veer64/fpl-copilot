"""Prompt R3 item 3 (16 Nov 2026): get_prediction takes `horizon` and returns the sum for exactly that span, labelled with its
gameweeks; a normal turn's rows carry their figures ready to quote.

Measured before (eval/reports/r3_evidence_digest.md): the model added gameweeks up itself -- "22.5 expected points across the
five gameweeks" (W2), "17.1 pts" (W5), "18.2 pts" (W6) -- quoted a six-gameweek total under a five-gameweek heading (M20), and
re-rounded what it read: "a clean-sheet probability of around 40%" (W3), "roughly a coin flip to even start" for 37% (M13),
"(GW14 at P10 = 1 point)" (digest 7.6).

S1  horizon=N: only the N gameweeks from the next deadline's come back, and `span` holds their sum (a whole-pool query),
    labelled "GW11–13"; fewer than asked says so; a blank adds nothing and is named;
S2  without horizon the answer is what it always was: the same keys, the same rows, the same whole-range sum;
S3  every gameweek row of a normal turn carries `in_words`: the figure at 2 dp and each chance as a whole percentage;
S4  every likely range carries `range_words` in plain words (low end / middle / top); a manufactured low end is not given;
S5  gw and horizon together, or a horizon outside 1-8, is an error; a draft chat's result carries none of the new words.
Seeded pool (Tests/r3_seed.py); no model, no network."""
import sys
from decimal import Decimal
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
for p in (str(REPO), str(REPO / "squad"), str(Path(__file__).resolve().parent)):
    if p not in sys.path:
        sys.path.insert(0, p)

import model_tools as mt                                    # noqa: E402
import r3_seed as seed                                      # noqa: E402
from r3_seed import pool_db                                 # noqa: E402,F401  (the fixture)


def _sum(conn, e, gws):
    return seed.q(conn, "SELECT round(COALESCE(sum(e_points::float8), 0)::numeric, 2) FROM model_predictions WHERE run_id = 1 "
                        "AND config = 'baseline' AND element = %s AND gw = ANY(%s)", (e, list(gws)))[0][0]


@pytest.mark.parametrize("element,horizon", [(107, 1), (107, 3), (120, 5), (102, 6), (131, 2)])
def test_s1_the_span_is_the_sum_for_exactly_the_gameweeks_asked(pool_db, element, horizon):
    out = mt.get_prediction(element, horizon=horizon)
    gws = list(range(11, 11 + horizon))
    assert [r["gw"] for r in out["predictions"]] == gws
    want = _sum(pool_db, element, gws)
    label = "GW11" if horizon == 1 else f"GW11–{10 + horizon}"
    assert out["span"] == {"gameweeks": gws, "label": label, "predicted_points": float(want),
                           "words": f"{want:.2f} predicted points over {label} ({horizon} gameweek{'s' if horizon > 1 else ''})"}
    assert Decimal(str(out["span"]["predicted_points"])) == want
    assert "horizon_e_points_sum" not in out                              # one total in the answer, the one that was asked for


def test_s1b_fewer_than_asked_says_so_and_a_blank_adds_nothing(pool_db):
    out = mt.get_prediction(107, horizon=8)
    assert out["span"]["gameweeks"] == [11, 12, 13, 14, 15, 16] and out["span"]["label"] == "GW11–16"
    assert out["span"]["clipped"] == "Predictions exist for GW11–16 only, so this covers 6 gameweeks, not 8."
    blank = mt.get_prediction(110, horizon=3)                             # a Bravo player: no fixture in GW13
    want = _sum(pool_db, 110, [11, 12])
    assert [r["gw"] for r in blank["predictions"]] == [11, 12] and blank["span"]["no_prediction_row_for"] == [13]
    assert blank["span"]["words"] == f"{want:.2f} predicted points over GW11–13 (3 gameweeks) (GW13 has no prediction row and adds nothing)"
    double = mt.get_prediction(102, horizon=2)                            # an Alpha player: GW12 is a double, both fixtures in the row
    assert Decimal(str(double["span"]["predicted_points"])) == _sum(pool_db, 102, [11, 12])


def test_s1c_between_deadlines_the_span_starts_at_the_next_deadline(pool_db, monkeypatch):
    monkeypatch.setattr(mt, "_current_gw", lambda: 13)
    out = mt.get_prediction(107, horizon=2)
    assert out["span"]["gameweeks"] == [13, 14] and Decimal(str(out["span"]["predicted_points"])) == _sum(pool_db, 107, [13, 14])


def test_s2_without_horizon_the_answer_is_what_it_was(pool_db):
    out = mt.get_prediction(107)
    assert "span" not in out and [r["gw"] for r in out["predictions"]] == seed.GWS
    assert out["horizon_e_points_sum"] == round(sum(float(r["e_points"]) for r in out["predictions"]), 2)
    assert Decimal(str(out["horizon_e_points_sum"])) == _sum(pool_db, 107, seed.GWS)
    one = mt.get_prediction(107, gw=12)
    assert "span" not in one and [r["gw"] for r in one["predictions"]] == [12] and "horizon_e_points_sum" in one
    for key in ("run_id", "gw", "model_version", "built", "next_run_expected", "player_id", "name", "team", "predictions", "quantiles"):
        assert key in out, key


def test_s3_each_row_carries_its_figures_ready_to_quote(pool_db):
    out = mt.get_prediction(107, horizon=2)
    for r in out["predictions"]:
        pts = Decimal(repr(float(r["e_points"]))).quantize(Decimal("0.01"), rounding="ROUND_HALF_UP")
        start = int(Decimal(repr(float(r["p_start"]) * 100)).quantize(Decimal(1), rounding="ROUND_HALF_UP"))
        assert r["in_words"].startswith(f"GW{r['gw']}: {pts:.2f} predicted points; {start}% chance of starting")
        assert "around" not in r["in_words"] and "roughly" not in r["in_words"]
    with pool_db.cursor() as cur:                                          # a clean-sheet chance and a 60-minute chance, as production rows have
        cur.execute("UPDATE model_predictions SET p_cs = 0.3962, p_60plus = 0.8849 WHERE element = 107 AND gw = 11")
    row = mt.get_prediction(107, gw=11)["predictions"][0]
    assert row["in_words"].endswith("88% chance of playing 60 minutes or more; 40% chance of a clean sheet")   # 39.62 -> "40%", once


def test_s4_each_likely_range_is_in_plain_words(pool_db):
    with pool_db.cursor() as cur:
        cur.execute("UPDATE model_predictions SET q_p10 = 1, q_p50 = 3, q_p90 = 8, q_sd = 2.5, q_resid_sampling = 0, "
                    "q_resid_structural = 0, q_tolerance = 0.1 WHERE element = 107")
        cur.execute("UPDATE model_predictions SET q_p10 = 0, q_p50 = 0, q_p90 = 2.5, q_degenerate = TRUE WHERE element = 107 AND gw = 12")
    per = mt.get_prediction(107, horizon=2)["quantiles"]["per_gw"]
    assert per[0]["range_words"] == "GW11: low end 1, middle 3, top 8"     # was "(GW14 at P10 = 1 point)"
    assert per[1]["range_words"] == "GW12: the low end and the middle are both 0; only the top of the range, 2.50, carries a signal"
    flagged = {"predictions": [], "quantiles": {"per_gw": [{"gw": 14, "p10": 2.0, "p50": 4.0, "p90": 9.0, "p10_unusable": True}]}}
    assert mt._with_prediction_words(flagged)["quantiles"]["per_gw"][0]["range_words"] == \
        "GW14: middle 4, top 9; the low end cannot be trusted for this fixture"
    none = mt.get_prediction(120, horizon=1)                               # a build that computed no ranges: nothing invented
    assert none["quantiles"]["computed"] is False and none["quantiles"]["per_gw"] == []


def test_s5_errors_and_the_draft_chat(pool_db):
    assert "not both" in mt.get_prediction(107, gw=11, horizon=2)["error"]
    for bad in (0, 9, "three"):
        assert "the number of gameweeks must be a whole number from 1 to 8" in mt.get_prediction(107, horizon=bad)["error"]
    import turn_context
    turn_context.begin("s" * 32, thread_id="th_draft", draft={"user_id": 10001, "draft_key": 800_000_001})
    try:
        out = mt.get_prediction(107)
    finally:
        turn_context.end()
    assert all("in_words" not in r for r in out["predictions"])            # a draft chat's results are what they were
