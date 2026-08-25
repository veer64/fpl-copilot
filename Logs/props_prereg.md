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

---

## ADDENDUM 1 (2026-08-24) — three amendments made BEFORE any 2025-26 outcome was read

Written after the de-vig build (`Logs/props_devig_log.md`, commit 41e8b8e) and before the tuning grid was run.
Each amendment is justified STRUCTURALLY — by a property of the data or the method that can be stated without
reference to any result — and each is made before a single 2025-26 outcome has been read in any form. That is
what makes them legitimate rather than result-driven: the horizon MAE argument failed precisely that test
(the endpoint was questioned only after the result was seen), and these are not the same move. The original
sections above are unchanged.

**Amendment 1 — the margin adjustment is computed on the SHARED element set, and thin boards are dropped.**
Defect in the §4 method as written: the whole-board proportional adjustment reads a book's board total as its
margin, but a book that prices fewer players has a smaller total for that reason alone. Measured: Pinnacle
prices 4.5 players per board (12% of the fixture's largest) — favourites only — so its low total is
incompleteness, not vig; scaled ×2.43 (max ×4.83) it produced 45 of the raw clipped probabilities and moved the
consensus by up to 0.116 on its 20 fixtures, shifting a third of elements by more than the entire 0.02 pass
margin. BetRivers (26–30 players, ~70% of the largest board) is partly the same artefact. Corrected method:
(a) a book is dropped from a fixture when its board is below 50% of that fixture's largest board; (b) each
retained book's scale factor is mean_total / book_total computed over the elements priced by EVERY retained
book on that fixture (the shared set), so board size cannot masquerade as margin; if fewer than 5 elements are
shared the fixture falls back to whole-board totals and is counted. Recorded as a defect in the method, not a
preference.

**Amendment 2 — the feature and every endpoint are defined on OUTFIELD players.** The §1 coverage gate fails on
the squad-relevant partition in both seasons as written (77.4% / 79.4%) and likely starters sits at 80.3% in
2024-25; the entire shortfall is goalkeepers, whom no book prices in any fixture (0 covered goalkeeper rows in
either season) and whose goals term is ~0 by rule. Outfield-only the same partitions are 97.0% / 96.6% and
90.3% / 97.3%. This is a LIMITATION, not merely a scope decision: **the props feature cannot inform
goalkeeper selection at all**, and it sits alongside the open goalkeeper margin-beta question in
`Logs/gk_investigation_log.md` §9–§10 — the position where the model is weakest is the position the market
does not price. Goalkeepers keep the model's rate everywhere.

**Amendment 3 — partly-priced doubles are EXCLUDED from the endpoint, not caveated.** 24 (2024-25) and 22
(2025-26) doubling (gameweek, element) rows have one fixture priced of two at the deadline. A half-priced
double understates the market systematically in exactly the weeks the planner cares most about. Those rows are
flagged `partial_double` in the consensus file and excluded from every endpoint; the excluded count is
reported alongside every result.

**Standing caveat carried forward (not an amendment):** the equal-weight consensus is US-dominated (~4 US books
to one 1xBet) while a live system would read UK books. Cross-region rank agreement is 0.975–0.982 against a
0.997 within-UK floor, so the gap is bounded — but every validated number in this workstream is a
US-consensus number and must be quoted as one.

Selection rule, grid, endpoints and pass condition (§2–§5) are unchanged.

---

## PRE-REGISTERED VALUE (2026-08-24, written before any 2025-26 file was opened by the measurement script)

w = 0.75, m = 1.00

Selected on 2024-25 GW8–38 by the §5 rule exactly as written (max MEAN primary Spearman over likely starters
and squad-relevant; ties → lower w, then lower m): mean 0.2973 (likely starters 0.2837, squad-relevant 0.3108)
against the incumbent's 0.2808 (0.2750 / 0.2866). Full surface, robustness checks and secondary endpoints:
`Logs/props_tuning_log.md`. Consensus input: the ADDENDUM 1 build (`method = addendum1_shared_set`).

Recorded alongside the value, so that the sealed run is read with them in view:

1. **Salah guard (requested before the run) passed** — with Salah's 27 rows excluded the argmax is the same
   pair (mean 0.2761). His share of ρ is 6.5% (likely starters) and 17.7% (squad-relevant), but his share of
   Δρ is ≈ 0: he does not tilt the choice.
2. **The surface is flat between w = 0.75 and w = 1.0** (0.2973 vs 0.2964, a gap of 0.0009 — under the 0.020
   book-disagreement floor by a factor of 20). Leave-one-out of Yoane Wissa (29 likely-starter rows, 14 goals)
   flips the argmax to w = 1.0, m = 1.00; every other listed player leaves it unchanged. The rule stands and
   picks 0.75 (the lower w); the sealed season must be read knowing that 0.75 and 1.0 are not distinguished by
   the tuning data.
3. **m = 1.00 means no de-vig at all.** Spearman cannot see calibration (w = 1 rows are identical across m), so
   the rule selects the pair with the overround left in: on likely starters the candidate predicts a mean
   P(≥1 goal) of 0.153 against a realised 0.108 (incumbent 0.122) and Brier worsens 0.0879 → 0.0884, log loss
   0.3032 → 0.3068. This is a property of the pre-registered rule, noted here, not corrected here.
4. **On the tuning season itself the selected pair does not meet §3:** condition 1 is met on squad-relevant
   (+0.0243) but not on likely starters (+0.0087 < +0.020); condition 2 (written-off band, defined with no
   e_minutes floor because the starter band contains none) is breached (−0.0298, mean market P 0.112 against a
   realised 0.013 — the placeholder-price band); condition 3 (Brier) is breached on likely starters. 2024-25 is
   the tuning season and is NOT evidence, but the pooled window of §3 includes it, so the sealed season would
   need to be strong enough on its own to carry the pooled result over the bar.

The sealed season is run ONCE: `uv run python eval/measure_props_endpoint.py --holdout 0.75 1.00`. It has not
been run as of this entry.

