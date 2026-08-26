# Bonus term rebuild — PRE-REGISTRATION (written 2026-08-26, before any code was changed)

Companions: `Logs/headroom_diagnosis.md` §0 item 2 (the diagnosis), `Logs/Bonus model log.md` (the incumbent's
build), `Logs/topend_calibration_prereg.md` and `Logs/horizon_minutes_log.md` (the two negatives whose lesson —
the sliced rank endpoint decides, nothing else — this document applies). Nothing here may be changed after a
result is seen; amendments go in dated addenda. At the time of writing no code has changed and no candidate has
been built or scored.

## 1. The defect (from the diagnosis; verified in code)

`squad/bonus.py` trains a LightGBM regressor for BPS on REALISED per-match components — `goals_scored`,
`assists`, `clean_sheets` (integers), `minutes`, position dummies, `saves`, cards, `goals_conceded`, penalties
missed, own goals — and maps predicted BPS to expected bonus through an empirical curve (bucketed realised BPS →
mean realised bonus). `squad/assembly.py::_finish_equation` (lines ~584–596) then feeds that tree EXPECTATIONS:
`goals_scored = e_goals` (mean 0.10–0.12 among starters, p90 0.27), `assists = e_assists`, `clean_sheets =
p_cs × p_60plus`, `goals_conceded = opp_lambda × minutes_frac`, and so on. A tree evaluated at 0.1 goals lands
in the leaf it learned for "0 goals"; it cannot represent E[bonus] = Σ P(outcome)·bonus(outcome), because bonus
is a convex function of the discrete outcome (a goal is worth ~+19 BPS and the curve is steep through 20–40).
The output is then rescaled per gameweek to the historical mean bonus, which repairs the aggregate level and
nothing else.

Measured on the canonical files, realised starters (minutes ≥ 60), 2023-24 / 2024-25 / 2025-26 **[read-only,
diagnosis]**: ρ(exp_bonus, realised bonus) = −0.016 / −0.025 / −0.025; on the squad-relevant top 30 −0.09 /
−0.18 / −0.09; pred_bps mean 33–39 vs realised 13–19. Top-30 mean exp_bonus vs realised bonus by position: FWD
0.28 / 0.23 / 0.27 vs 0.68 / 0.90 / 0.83; MID 0.31 / 0.28 / 0.28 vs 0.65 / 0.74 / 0.58; DEF 0.41 / 0.35 / 0.36 vs
0.44 / 0.41 / 0.41; GK 0.38 / 0.33 / 0.36 vs 0.32 / 0.19 / 0.22. The rest of the equation predicts bonus better
than the bonus term does (ρ(pts_goals + pts_assists + pts_cs, bonus) +0.16 / +0.17 / +0.13). Deleting the term
raised e_points rank on likely starters in all three seasons (+0.008 / +0.003 / +0.004).

## 2. Three arms, one population

All three are scored on the SAME rows: single-fixture (`n_fixtures == 1`) step-0 rows of the canonical files,
joined to vaastav realised points and bonus by `(element, gw)`; partitions defined on the INCUMBENT's own view
(likely starters = own-cutoff `p_start ≥ 0.75`; squad-relevant = top 30 by incumbent `e_points` within gameweek).
Penalty gate OFF and calibration gate OFF in every arm (both rest False; both failed their own bars).

1. **Incumbent**: the canonical `e_points` (`e_points_core + exp_bonus` as built today).
2. **DELETE**: `exp_bonus = 0` everywhere, i.e. `e_points = e_points_core` — read directly off the canonical file
   (that identity holds exactly by construction: `e_points = e_points_core + exp_bonus`, `assembly.py` line ~625),
   so no rebuild is needed and the arm is bit-exactly what deleting the term would produce.
3. **REBUILD**: outcome-weighted evaluation of the SAME trained BPS tree and the SAME BPS→bonus curve (§3), built
   as `walkforward_h6_{season}_bonusow.parquet` with the gate flipped in-process; canonicals untouched.

**The delete arm is decisive, not a formality.** Stated now: if the rebuild does not beat DELETE on the decision
partitions (§5), the recommendation is to delete the term. A bonus term that ranks worse than nothing has no
claim to stay in the equation because it is "a real FPL rule"; the rule is real, the estimate of it is what is on
trial.

## 3. The rebuild, specified before building

For each player-fixture row, with the equation's own quantities already computed at that point of
`_finish_equation` (e_goals, e_assists, opp_lambda, minutes_frac, e_minutes, saves_per_90, cards, penalty share):

    goals     G ~ Poisson(e_goals),              enumerated g ∈ {0, 1, 2, 3};  P(G ≥ 3) folded into g = 3
    assists   A ~ Poisson(e_assists),            enumerated a ∈ {0, 1, 2};     P(A ≥ 2) folded into a = 2
    conceded  C ~ Poisson(opp_lambda × mf),      enumerated c ∈ {0, …, 4};     P(C ≥ 4) folded into c = 4
    clean sheet = 1{c = 0}                       (the tree's `clean_sheets` feature, set per conceded outcome)
    saves (GK only) S ~ Poisson(saves_per_90 × mf), enumerated s ∈ {0, …, 8}; P(S ≥ 8) folded into s = 8;
                                                 outfield rows keep saves at the incumbent's expectation (≈ 0)
    G, A, C, S independent.

    E[bonus] = Σ_{g,a,c,(s)} P(g)P(a)P(c)P(s) · curve( tree(g, a, 1{c=0}, minutes, position, s, cards, c, pens, og) )
    exp_bonus = E[bonus] × minutes_frac                       (the incumbent's playing-time gate, unchanged)

Every quantity the tree sees for goals, assists, clean sheets, conceded and saves is then an integer from the
training support. Truncation points: goals at 3 because P(G ≥ 4) is 1.9% at λ = 1 and 0.03% at the starter mean
λ = 0.3 (the largest e_goals on the files is ~1.0); assists at 2 for the same reason at smaller rates; conceded at
4 (P(C ≥ 5) < 1% at μ = 1.5); saves at 8 (GK mean ~3 per 90). Folding the tail into the cap slightly UNDER-states
the bonus of the very best outcomes, which is the conservative direction. Grid size: 60 tree evaluations per
outfield row, 540 per goalkeeper row.

**What is deliberately kept identical to the incumbent, so the change is isolated:** the trained tree and the
curve (no refit); `minutes = e_minutes` as the tree's minutes input and the `× minutes_frac` gate afterwards;
cards, penalties missed and own goals at their expectations (rare events, ≤ 0.2 per match); the two unverified
inputs the incumbent already carries. **What is dropped:** the per-gameweek renormalisation `exp_bonus ×
bonus_mean / gw_mean` — it existed to repair the level of a term that could not produce one; the rebuild's level
is a REPORTED check (mean predicted vs realised bonus per season and by position), not a dial. If the level is
off, that is a finding about the tree or the curve and is recorded, not corrected here.

**No free parameter.** Truncation points are fixed above by the stated tail probabilities and are not swept.
Nothing is fitted, so there is nothing to tune and nothing to seal; all three seasons are measured. Any future
variant with a fitted component (a refit tree on expected inputs, a shrink on E[bonus], a per-position scalar)
is a separate pre-registration — named now so it cannot be added quietly if the rebuild lands short.

**Known limitation, recorded now — bonus is competitive.** Bonus goes to the top three BPS in a MATCH, not to
anyone crossing a threshold. The curve bakes in the historical competition (the average bonus earned at a given
BPS), so a per-player outcome-weighted estimate is an expectation against the average match, not against the 21
other players actually on the pitch. What this gets systematically wrong: (i) a good outcome in a match where a
team-mate has an even better one (two goals for the striker, one for the winger) is over-credited, because the
curve does not know the team-mate scored; (ii) correlation between a player's outcome and his team-mates' (a
3–0 win lifts every defender's CS and the keeper's BPS at once) means high-BPS matches are crowded and low-BPS
matches are not — the curve averages over that, so it over-credits strong teams' fifth-best performer and
under-credits the standout in a dull match; (iii) the tail folding under-credits hat-tricks. The match-level
joint version (sample all 22 players' outcomes jointly, rank BPS within the match) would fix (i)–(ii) and is a
larger build that is NOT attempted here. The position table in §5 is where (i)–(ii) would show up if they are
large: defenders and keepers on strong teams are the crowded case.

## 4. Endpoints

Primary — on the common population, per season, all three arms:
- Spearman(e_points, realised points) on likely starters and on squad-relevant (the decision partitions), with
  uncertain, written-off, full starter band and realised starters reported alongside;
- ρ(exp_bonus, realised bonus) on realised starters and on the top 30 (incumbent and rebuild; DELETE is 0 by
  construction and reported as such).

Secondary (reported, not decisive): mean predicted vs realised bonus overall and by position on likely starters
and on the top 30 (the bias table); ρ(pred_bps, realised bps); Brier of e_points-implied P(bonus ≥ 1) is not
defined for a mean, so calibration is reported as level ratios by decile of exp_bonus; MAE/RMSE of e_points.

## 5. Pass condition — stated now

The bars, applied to the REBUILD, per season, all three seasons:

1. **The term must carry signal**: ρ(exp_bonus, realised bonus) ≥ **+0.10** on realised starters AND ≥ **+0.10**
   on the top 30, in every season. Floor rationale: the crude proxy (goals + assists + CS points) reaches
   +0.13–0.20 / +0.14–0.20; a rebuilt term below +0.10 knows less about bonus than the rest of the equation
   already does and is dead weight.
2. **Rank must not fall on either decision partition, in any season, against BOTH the incumbent AND DELETE**:
   Δ Spearman(e_points, points) ≥ −0.003 on likely starters and on squad-relevant, rebuild − incumbent and
   rebuild − delete. Additionally the three-season mean of (rebuild − delete) must be ≥ 0 on both partitions —
   the rebuild has to be at least as good as removing the term, not merely not-worse within noise on each cell.
3. **The position bias must close**: on the top 30, mean predicted / realised bonus by position must lie within
   **[0.6, 1.5]** for FWD, MID and DEF in every season, and the FWD ratio must move at least HALF of the way from
   its incumbent value toward 1.0 (e.g. 2024-25: 0.23/0.90 = 0.26 → ≥ 0.63). GK is reported (small n at the
   top) and not gated.
4. Level and Brier-type reads are secondary and count for nothing either way.

**Decision rule, in advance.**
- Rebuild passes 1–3 → recommend adoption of the rebuild (gate flip, canonical promotion, fingerprint update as
  a separate step; the earlier canonicals preserved).
- Rebuild fails any of 1–3, and DELETE is ≥ −0.003 vs the incumbent on both decision partitions in every season
  with a positive three-season mean on both → **recommend DELETE** (set `BONUS_MODE = "delete"`), plainly.
- Rebuild fails and DELETE also fails against the incumbent → keep the incumbent, record both negatives.
No amendment to these bars after seeing a number; a rebuild variant with a fitted component is a new
pre-registration.

## 6. Build, provenance, sequence

- `assembly.BONUS_MODE ∈ {"incumbent", "delete", "outcome"}` (rests `"incumbent"`), stamped per row as
  `bonus_mode` by all three walk-forward writers. `"incumbent"` reproduces the current equation bit-exactly
  (checked at one cutoff); `"delete"` sets `exp_bonus = 0`; `"outcome"` is §3. Unit test pins all three.
- Builds: `walkforward_h6_{season}_bonusow.parquet` (outcome mode) for all three seasons via
  `eval/run_bonus_rebuild.py`, gate flipped in-process, canonicals untouched. The DELETE arm's frame for the
  season figures is the canonical file with `e_points := e_points_core`, `exp_bonus := 0`, `bonus_mode :=
  "delete"` — written by the same script, no rebuild.
- Measurement: `eval/measure_bonus_rebuild.py` — the three-arm table, the bias table, the §5 verdict.
- Season figures LAST: `eval/run_arms_full_system.py --arm bonusow / bonusdel`, reference config, reference cells
  not re-run, standing framing, 2024-25 Salah-held count next to the total.

## 7. What is expected, stated now (not a pass condition)

ρ(exp_bonus, bonus) on starters should land around +0.15–0.25 (the outcome weighting lets goals drive the term,
and goals are 30% of starter variance); FWD/MID top-30 bonus should rise toward 0.6–0.9 and GK/DEF fall; the level
overall should come out near the realised 0.25–0.35 per starter without renormalisation if the curve is honest,
and above it if the competitive limitation (§3) bites — which would show as DEF/GK still over. Rank on
squad-relevant could move either way: the incumbent's tilt against forwards is removed, which should help, but a
term with real within-starter signal also adds variance to e_points; DELETE is the control that says whether
signal or noise won. If the rebuild only matches DELETE, delete.

---

## RESULTS (2026-08-26; `eval/measure_bonus_rebuild.py`; builds `walkforward_h6_{season}_bonusow.parquet` (outcome mode, in-process), `_bonusdel.parquet` (canonical with exp_bonus := 0); output of record `data/penfix_logs/measure_bonus_rebuild.txt`). VERDICT UNDER §5: **REBUILD FAILS; DELETE beats the incumbent → recommend `BONUS_MODE = "delete"`.**

Incumbent-mode reproduction at 2024-25 cutoff 20: bit-exact (max |Δ| = 0.0 incl. `exp_bonus`, `pred_bps`). Tests
137 passed. Same rows in all three arms (27,759 / 26,555 / 28,929 single-fixture step-0 rows).

**Three-arm rank, decision partitions (Spearman(e_points, realised points)):**

| season | partition | incumbent | DELETE | REBUILD | reb − inc | reb − del | del − inc |
|---|---|---|---|---|---|---|---|
| 2023-24 | likely starters | 0.2983 | 0.3060 | 0.3043 | +0.0059 | −0.0017 | **+0.0077** |
| 2023-24 | squad-relevant | 0.1639 | 0.1762 | 0.1734 | +0.0095 | −0.0029 | **+0.0124** |
| 2024-25 | likely starters | 0.2855 | 0.2889 | 0.2888 | +0.0033 | −0.0001 | **+0.0034** |
| 2024-25 | squad-relevant | 0.1428 | 0.1497 | 0.1520 | +0.0091 | +0.0023 | **+0.0068** |
| 2025-26 | likely starters | 0.2032 | 0.2072 | 0.2060 | +0.0028 | −0.0012 | **+0.0040** |
| 2025-26 | squad-relevant | 0.0854 | 0.0826 | 0.0709 | **−0.0145** | **−0.0117** | −0.0028 |

Three-season means: rebuild − DELETE likely −0.0010, squad −0.0041; DELETE − incumbent likely **+0.0050**, squad
**+0.0055**. Realised-starter rank: DELETE +0.016 / +0.011 / +0.007 over the incumbent. Written-off band moves
−0.002 (the term's only within-membership information was there). MAE of e_points on starters: DELETE best in
every season (2.223 / 2.158 / 2.327 vs incumbent 2.283 / 2.202 / 2.342).

**Bonus signal:** ρ(exp_bonus, realised bonus) on started rows −0.026 / −0.034 / −0.031 → **+0.140 / +0.173 /
+0.132**; on the top 30 −0.093 / −0.186 / −0.096 → +0.066 / **+0.173** / +0.096. Condition 1 (≥ +0.10 on both)
passes in 2024-25 only. ρ(pred_bps, bps) on starters +0.10 / −0.13 / −0.04 → +0.17 / +0.08 / +0.08.

**Position bias, top 30 (mean predicted / realised bonus; ratio incumbent → rebuild):**

| | FWD | MID | DEF | GK |
|---|---|---|---|---|
| 2023-24 | 0.25 / 0.55 vs 0.53: 0.48 → **1.04** | 0.27 / 0.29 vs 0.59: 0.46 → 0.49 | 0.37 / 0.20 vs 0.41: 0.90 → 0.50 | 0.35 / 0.07 vs 0.30: 1.19 → 0.23 |
| 2024-25 | 0.22 / 0.51 vs 0.75: 0.30 → **0.69** | 0.25 / 0.34 vs 0.56: 0.44 → 0.60 | 0.31 / 0.21 vs 0.36: 0.87 → 0.58 | 0.32 / 0.11 vs 0.15: 2.13 → 0.77 |
| 2025-26 | 0.24 / 0.51 vs 0.77: 0.32 → **0.66** | 0.27 / 0.23 vs 0.47: 0.57 → 0.50 | 0.34 / 0.12 vs 0.36: 0.95 → 0.34 | 0.35 / 0.10 vs 0.20: 1.77 → 0.52 |

FWD moved at least halfway to 1 in every season (condition 3's first clause passes); MID and DEF fall OUTSIDE
[0.6, 1.5] (condition 3 fails in every season).

**Level (the finding that explains the rest):** mean exp_bonus on started rows, incumbent 0.27 / 0.24 / 0.26,
rebuild **0.07 / 0.08 / 0.06**, realised 0.29 / 0.29 / 0.29. The outcome-weighted term is about one quarter of
the realised level — right in ORDER (it now correlates with bonus at +0.13–0.17 and lifts forwards above
defenders, which the incumbent inverted) and wrong in SCALE. The incumbent's level was manufactured by the
per-gameweek renormalisation; the rebuild dropped it as pre-registered and the honest level of tree + curve at
integer outcomes turned out to be a quarter of reality (the reliability deciles run 0.00 → 0.33 predicted against
0.18 → 0.56 realised: a slope near 1 on a floor of ~0.15 — the curve's "everyone else gets ~0.15 on average"
baseline is missing, because the bucketed curve was built on per-fixture BPS rows and at the integer-zero
outcome the tree's BPS lands in the flat ~0 region). At a quarter of the level the term barely moves e_points, so
the rebuild's rank sits within ±0.003 of DELETE in five of six decision cells and below it in the sixth.

**Reading, written after the numbers and changing nothing above.**
1. Condition 1 fails in two seasons (top-30 +0.066 / +0.096 against +0.10), condition 3 fails in all three
   (MID/DEF under-credited), condition 2 fails in 2025-26 (squad-relevant −0.012 vs DELETE). The rebuild does
   not pass and is not adopted.
2. DELETE is not worse than the incumbent in any decision cell (worst −0.003, exactly at the floor) and beats it
   by +0.005 / +0.006 on the three-season means, +0.007–0.016 on realised starters, and on MAE in every season.
   **By the decision rule fixed in §5, the recommendation is to delete the term.** The bonus rule is real; the
   incumbent's estimate of it ranks worse than nothing on the rows the optimizer picks from, and a term that
   ranks worse than nothing has no claim to stay.
3. What would make a rebuild adoptable, named but NOT done (a fitted component = a new pre-registration): a
   level scalar or an additive floor on the outcome-weighted term (the deciles show the signal is there with a
   slope of ~1 and an intercept of ~−0.15), or a curve rebuilt on the same integer-outcome grid the term is
   evaluated on. Either is a tunable and was excluded in advance; the honest state now is DELETE, with the
   outcome-weighted machinery retained behind `BONUS_MODE = "outcome"` as the starting point for that work.
4. The competitive limitation (§3) shows where predicted: keepers and defenders — the crowded case — are the
   positions the rebuild under-credits most (GK 0.23–0.77, DEF 0.34–0.58 on the top 30).

Adoption of DELETE is a separate, user-triggered step: set `assembly.BONUS_MODE = "delete"`, rebuild + stamp the
canonicals (or promote the `_bonusdel` frames, which are the canonicals with the identity applied), update the
provenance fingerprint deliberately, and re-read every figure that depends on e_points at the top.

Season figures for `bonusow` and `bonusdel` are appended below when complete — standing framing, never evidence,
2024-25 Salah-held count alongside.

### Season figures (2026-08-26; `--arm bonusow` and `--arm bonusdel`, reference config, each arm's own chip reads, TC2 scored ZERO, legality PASS, reference cells not re-run; `eval/measure_arms_full_system.py`)

> *Note added 2026-08-26 (later): the reference 2296 / 2294 / 2206 quoted in this table is the OLD convention (TC2 scored zero, incumbent bonus term). The figures of record are now 2251 / 2306 / 2268 (`bonus_mode=delete` + TC2 in-sim; p4 log §15). This table stands as the comparison that was made at the time.*

| season | reference (path / chip-incl) | REBUILD bonusow (path / chip-incl, Δ) | DELETE bonusdel (path / chip-incl, Δ) |
|---|---|---|---|
| 2023-24 | 2278 / 2296 | 2243 / **2280** (−16) | 2216 / **2241** (−55) |
| 2024-25 | 2255 / 2294 | 2268 / **2312** (+18) | 2220 / **2277** (−17) |
| 2025-26 | 2156 / 2206 | 2044 / **2094** (−112) | 2213 / **2261** (+55) |

Rebuild reads BB1/BB2/TC1: +16/+15/+6, +5/+30/+9, +8/+26/+16; chip weeks identical to the reference in every arm.
2024-25 Salah held / captained: rebuild 34 / 26, delete 34 / 25 (reference 34 / 26). Standing framing: single
draws, sd ~60 (paired ~85); the −112 and +55 are noise of the size the record documents; the component verdict
(rebuild fails; delete adopted under `Logs/bonus_delete_prereg.md`) is unaffected and was never permitted to be.
