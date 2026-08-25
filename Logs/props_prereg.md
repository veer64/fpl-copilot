# Player-prop odds — PRE-REGISTRATION (written 2026-08-24, before any scale pull)

Evidence base: `Logs/player_props_coverage_log.md` §1–§6 (steps 1–3). Timing
clean (a snapshot 4 min before the FPL deadline, 7/7 fixtures, 5-minute
cadence); boards full where they exist (26–43 players); historical coverage
runs from ~2024-25 GW8 (present 19 Oct 2024, absent 31 Aug 2024) through
2025-26; historical books are 1xBet (eu) and US books, the live books are UK
(Paddy Power / Sky Bet / William Hill); cross-region rank agreement
0.975–0.982 against a 0.997 within-UK floor, level agreement within 1–2.5 pp
per player.

Nothing in this document may be changed after a result is seen. Amendments
go in a dated addendum at the end, never in place.

## 1. Hypothesis

Market-implied P(player scores) beats the incumbent goals component at
predicting realised goals, on the starter band. The incumbent
(`squad/assembly.py`):

    E[goals] = npxg90 · minutes_frac · fixture_scale
             + penalty_share · team_pen_rate · minutes_frac

The market quantity is the anytime-goalscorer price, de-vigged (§4) and
converted to a per-fixture rate λ_mkt = −ln(1 − p) (Poisson: p = 1 − e^{−λ}).
The candidate is a blend on the rate scale, λ = w·λ_mkt + (1 − w)·λ_model,
with w a NEW tunable (§4). w = 0 is the incumbent; w = 1 is the market alone.

Population: single-fixture player-gameweeks in the starter band
(own-cutoff e_minutes ≥ 60), restricted to rows the market prices (the
common population — the incumbent is scored on the SAME rows). The share of
each partition the market covers is reported as a coverage metric; a
partition the market covers below 80% cannot pass.

## 2. Primary endpoint — sliced rank correlation, at step 0

Spearman(predicted E[goals], realised goals) pooled per season, on the two
decision-relevant partitions used in the horizon work, defined by the
incumbent's own view at the cutoff so both arms are scored on the same rows:

- **likely starters**: own-cutoff p_start ≥ 0.75;
- **squad-relevant**: top 30 by own-cutoff e_points within the gameweek.

Why these two and why in advance: horizon lever 1 improved Brier, AUC and
AGGREGATE Spearman and still failed, because rank fell exactly where
decisions are made (likely starters −7…−9%, squad-relevant −7…−21%) while
the aggregate gain lived in the written-off band. The partitions are named
now so that trap cannot be walked into again. The written-off band
(p_start < 0.25) and the uncertain band (0.25–0.75) are reported alongside
and are NOT decisive.

Step 0 only: props are a step-0 feature by construction — the market prices
a fixture 1–2 days out, and a fixture 12 days out had no market (coverage
log §3).

## 3. Pass condition (stated now)

At step 0, on the common population, pooled over the backtestable window
(2024-25 GW8 → GW38 and 2025-26 GW1 → GW38):

1. Spearman improves on **BOTH** partitions by **≥ +0.020** (pooled), and is
   **non-negative in each season separately** (2024-25 GW8+; 2025-26);
2. Spearman on the written-off band is not worse by more than 0.020 (no
   silent damage where the feature is not meant to act);
3. Brier on P(scores ≥ 1) is not worse on either decision partition.

The 0.020 margin is the cross-region book-disagreement floor (0.997 within
UK vs 0.975–0.982 UK-vs-backtest books): a gain smaller than the difference
between which book you read cannot be attributed to the market signal.
A gain that meets the bar on one partition only, or only in the written-off
band, however large, is a FAIL — that is precisely what killed lever 1.

## 4. Secondary endpoints (reported, not decisive)

Brier and log loss on P(scores ≥ 1) = 1 − e^{−E[goals]}; calibration
(mean predicted vs realised, and a reliability table in deciles of
predicted probability); the outcome-band decomposition of absolute error on
goals (0 / 1 / 2+); MAE and RMSE on E[goals]; the same set on the full
starter band and on the written-off band.

De-vig: anytime-scorer outcomes are not mutually exclusive, so implied
probabilities cannot be normalised to 1. The backtest uses the consensus of
the available historical books (1xBet + US) after the proportional margin
adjustment of coverage log §6 (each book scaled to the cross-book mean
total for the fixture), then a single multiplicative de-vig scalar m
(p_adj = p / m), tuned as below. Both m and w are tunables and are treated
by the same protocol.

## 5. Tuning protocol (mirrors rate_blend_log.md §2/§5, the k = 8 precedent)

- Tune on **2024-25 (GW8–38) only**. 2025-26 is sealed.
- Grid: w ∈ {0, 0.25, 0.5, 0.75, 1.0} × m ∈ {1.00, 1.10, 1.20, 1.30}.
- **Selection rule (fixed now):** the (w, m) maximising the MEAN of the
  primary Spearman over the two decision partitions on 2024-25; ties → lower
  w, then lower m (simpler first).
- The chosen (w, m) is written into a dated `## PRE-REGISTERED VALUE`
  section of THIS file before 2025-26 is touched. The measurement script
  refuses `--holdout` unless that exact `w = …, m = …` line is already
  present in this file, exactly as `eval/measure_rate_blend.py` refuses
  `--holdout K` without the `k = …` line in rate_blend_log.md.
- 2025-26 is run ONCE with the pre-registered pair and the result is
  appended whatever it shows.

## 6. Horizon design (both arms measured; decided on the endpoint)

Props reach step 0 only. Two arms:

- **(a)** props at step 0; steps 1–5 unchanged (the cutoff's model rate
  persists);
- **(b)** props propagated forward as a level shift on the player's rate:
  the step-0 ratio λ_blend / λ_model applied to the model's rate at steps
  1–5 for that player.

Arm (b) is scored at k = 1 … 5 on the same two partitions (stale p_start /
stale top 30, as in the horizon work) against the incumbent; it must not
worsen either. Team-news Arm A's −91 is the relevant precedent, but the
scoping log established that result was path noise rather than an
inconsistency mechanism, so it is not treated as a prior against (a).
Neither arm is chosen by season total.

## 7. Known limitations, written down now

1. **~1.7 backtestable seasons, none of 2023-24.** Every claim is a
   1.7-season claim and must be quoted as one. 2024-25 is the tuning season,
   so the sealed evidence is 2025-26 alone: one season.
2. **Backtest books are not the live books.** Historical = 1xBet + US;
   live = UK. Rank agreement 0.975–0.982, level agreement within 1–2.5 pp per
   player (coverage log §6). That is the floor on precision for anything this
   validates; any adopted feature would be read live from UK books it was
   never validated on.
3. **2024-25's baseline is a 97th-percentile draw** (why_2024_25_log).
   Nothing here is measured by season total; no policy simulation is part of
   this pre-registration.
4. **Name matching is a separate, risky step.** Book names are full legal
   forms and differ across books ("Eli Junior Kroupi", "MIguel Angel Brau");
   the crosswalk carries the silent-mismatch risk that produced
   Felipe/Morato and Beto (KNOWN_ISSUES #3, #12). Its precision is reported
   before any endpoint is computed; unmatched rows are counted, never
   filled.
5. **One snapshot per fixture** (the last strictly before the deadline).
   Agreement across books typically tightens toward kickoff; the deadline
   snapshot is the honest one for FPL and the only one used.

## 8. What is NOT part of this pre-registration

No season total. No policy simulation. No crosswalk or feature is built
before the pull is on disk and reported. The purchase decision was made on
the coverage evidence; this document governs what the data may be used to
claim.
