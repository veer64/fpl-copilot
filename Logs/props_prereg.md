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

---

## ADDENDUM 2 (2026-08-25) — amendment 4: m is set by calibration, w by rank. Made BEFORE any 2025-26 file was opened.

The defect, stated structurally: the §5 rule sets both dials by rank, but Spearman is invariant to p → p/m, so m is
UNIDENTIFIABLE under that rule. The first tuning (PRE-REGISTERED VALUE of 2026-08-24) could not choose m and fell
to the tie-break, m = 1.00 — no de-vig at all. Measured consequence on likely starters: the w = 0.75 candidate
predicted a mean P(≥1) of 0.153 against a realised 0.108 (incumbent 0.122); Brier and log loss worsened. The ranking
was fine; the levels carried the bookmakers' overround, and the points equation consumes levels linearly. Two things
follow, both true before any result: (a) a rank criterion cannot set a level parameter; (b) the grid
{1.00, 1.10, 1.20, 1.30} does not contain the required value — the market alone runs at 0.1632 / 0.1075 = 1.52 on
likely starters (the 0.153 / 0.108 ≈ 1.42 quoted in the first entry was the blend, which already carried 25% of the
model) — so the search could not have found it even had the criterion worked.

**Amendment 4.** Each dial is set by the criterion it controls, on 2024-25 GW8–38 only:
- **m by CALIBRATION:** m = mean market P(≥1) / mean realised P(≥1), market alone (w = 1, p_adj = p / m), computed on
  the **likely-starter partition only** of the common population — not on all rows, because the written-off band is
  distorted by placeholder prices (market mean 0.112 vs realised 0.013) and would drag m up. Computed directly, not
  by grid: one number from one season, applied once, rounded to 3 dp so the pre-registered line is reproducible.
- **w by RANK at that m,** exactly as §5: max MEAN primary Spearman over the two decision partitions; ties → lower w.

**The §3 PASS CONDITION IS UNCHANGED:** +0.020 on BOTH decision partitions pooled and non-negative in each season;
written-off band not worse by more than 0.020; Brier not worse on either decision partition.

Not adopted, recorded for a later decision: a minutes floor on the market feature would be a third tunable needing
its own pre-registration. Its effect is reported as information in the PRE-REGISTERED VALUE entry below.

---

## PRE-REGISTERED VALUE (2026-08-25, supersedes the 2026-08-24 entry; written before any 2025-26 file was opened)

w = 1, m = 1.517

The `--holdout` guard reads the LAST `## PRE-REGISTERED VALUE` heading in this file, so the superseded pair
(w = 0.75, m = 1.00) no longer satisfies it. Output of record: `Logs/props_tuning_log.md` (re-tune section).

**m = 1.517**, from 0.1632 / 0.1075 on n = 3,924 likely-starter rows (2024-25 GW8–38, outfield singles the market
prices). Post-hoc calibration of the market alone at this m: likely starters 1.000 (by construction), full starter
band 1.010, uncertain 1.128, squad-relevant **0.916**, written-off 7.33. **One multiplicative scalar is not
adequate across the range:** in deciles of the likely-starter partition the ratio predicted / realised runs
1.05–2.01 in the bottom six deciles (longshots still over-priced after de-vig) and 0.85–0.91 in the top three
(favourites now under-priced). The overround is not proportional to price — it is a favourite–longshot shape — so
the scalar over-corrects favourites and under-corrects longshots, and the squad-relevant partition, which is
favourite-heavy, sits 8% under realised after de-vig. Recorded, not corrected. (For contrast, the incumbent's own
mean on squad-relevant is 0.306 against the same 0.227 realised.)

**w surface at m = 1.517** (likely / squad / MEAN): w = 0: .2750 / .2866 / .2808; 0.25: .2789 / .2942 / .2866;
0.5: .2818 / .3024 / .2921; 0.75: .2835 / .3086 / .2961; **1.0: .2828 / .3100 / .2964**. The 0.75-vs-1.0 gap is now
−0.0004 (was +0.0009 at m = 1.00): the new m flips its sign and it remains a factor of ~50 under the 0.020 floor.
The rule picks w = 1 — the market replaces the model's goals rate outright on priced outfield singles.

**Robustness.** Salah guard (whole procedure re-run without him: m = 1.541) → same w. Leave-one-out of the whole
procedure for the 18 listed contributors: dropping Isak, Haaland, Mbeumo, Bowen or Amad Diallo flips w to 0.75;
dropping Wissa (last time's flip) no longer does; the other twelve leave it unchanged. **The tuning data do not
determine w between 0.75 and 1.0** — the pair is the rule's output, not a finding, and the sealed season is to be
read with that in view.

**§3 conditions on the tuning season at this pair (NOT evidence, recorded so the miss is on file before 2025-26 is
spent):** (1) likely starters +0.0078 < +0.020 → FAIL (squad-relevant +0.0234 passes; both non-negative);
(2) written-off band −0.0324 → FAIL; (3) Brier likely starters 0.0879 → 0.0864, squad-relevant 0.1677 → 0.1594 →
PASS (the first entry's Brier breach was the missing de-vig). Overall: FAIL on 2024-25. Log loss, MAE and RMSE also
improve on both decision partitions at this pair.

**Minutes floor (information only, not adopted):** with rows under a floor on minutes-to-date THIS season (the
cutoff-known quantity; whole-season minutes would leak) falling back to the model at this pair, the written-off
delta moves from −0.0324 to −0.0311 (floor 90, 2,165 rows to the model) and −0.0320 (floor 180, 2,787 rows); the
decision partitions are unchanged at 90 and squad-relevant drops 0.0013 at 180. **A minutes floor does not repair
the written-off breach.** The rows driving it are not the low-minute placeholders but players with minutes whom the
model has written off for that gameweek (injury, suspension, rotation) and whom the board still prices near their
usual level: market mean 0.093 against realised 0.013 on that band. The pattern — starters calibrate at 1.00, the
written-off band at 7.3 — is what a price that is conditional on appearing would produce (anytime-scorer bets are
commonly void for a non-runner, so the quoted price need not carry the appearance risk the model carries in
p_start). If that is the mechanism, the structurally right combination is the market's conditional rate scaled by
the model's own appearance probability, not a floor. Untested here; a design change needing its own pre-registration.

Standing caveats: US-consensus numbers throughout (ADDENDUM 1); 2024-25 baseline is a 97th-percentile draw and no
season total enters this document. 2025-26 has not been read. The sealed season is run ONCE:
`uv run python eval/measure_props_endpoint.py --holdout 1 1.517`.

---

## ADDENDUM 3 (2026-08-25) — amendment 5: w is set BY PRIOR, not by the data. Made BEFORE any 2025-26 file was opened.

The tuning does not determine w. At the calibrated m the 0.75-vs-1.0 gap in MEAN Spearman is 0.0004 — roughly 50×
under the 0.020 pass margin — and leave-one-out of any one of Isak, Haaland, Mbeumo, Bowen or Amad Diallo flips the
argmax. A rule that five individual players can flip has not measured anything.

**Amendment 5.** w = 0.75, by prior. Reason: shrinkage — when two options are indistinguishable, retaining a quarter
of the incumbent limits exposure to a market failure (a mispriced board, a book pulling prices, a thin week). **The
data did NOT choose this value.** That is recorded as the point of the amendment: a w presented as measured, when
five players flip it, would not be honest. The §5 rank surface is still reported for information.

**m stays as calibrated (1.517) and was NOT recomputed.** Amendment 4 defines m on the market alone —
m = mean market P(≥1) / mean realised on likely starters, i.e. w = 1 by definition — so its value does not depend on
w. What does depend on w is the calibration of the BLEND, reported here rather than folded into m: at
(0.75, 1.517) the blend's mean P(≥1) on likely starters is 0.112 against a realised 0.108 (ratio 1.04; the 25% of
the incumbent brings a quarter of its own 13% over-prediction), squad-relevant 0.235 vs 0.227 (1.035), full starter
band 0.112 vs 0.107. Recomputing m to absorb the incumbent's miscalibration would be tuning the market's scalar to
fix the model's level — a different defect, not this one.

The §3 pass condition is unchanged.

---

## PRE-REGISTERED VALUE (2026-08-25, supersedes both earlier entries; written before any 2025-26 file was opened)

w = 0.75, m = 1.517

**w = 0.75 is set BY PRIOR (amendment 5). The data did not choose it.** m = 1.517 by calibration (amendment 4).

§3 conditions on the tuning season at this pair (NOT evidence; on file before 2025-26 is spent):
(1) likely starters +0.0085 < +0.020 → FAIL (squad-relevant +0.0220 passes; both non-negative);
(2) written-off band −0.0283 → FAIL; (3) Brier likely starters 0.0879 → 0.0861, squad-relevant 0.1677 → 0.1584 →
PASS. Overall FAIL on 2024-25. Rank deltas: likely +0.0085, squad +0.0220, uncertain +0.0221, full starter band
+0.0090, written-off −0.0283. Output of record: `Logs/props_tuning_log.md` (`--pair 0.75 1.517` section).

This pair is the sealed-season candidate for the UNCONDITIONAL specification (λ = w·λ_mkt + (1 − w)·λ_model). The
conditional-rate specification has its own pre-registration, `Logs/props_conditional_prereg.md`, and its own value
line; the holdout is spent once, on whichever specification is believed at that point, and has not been run for
either. `uv run python eval/measure_props_endpoint.py --holdout 0.75 1.517` is the command for this one.

---

## CLOSE-OUT (2026-08-26) — the props feature is NOT ADOPTED, all four specifications

Condition (1) of §3 — likely-starter Spearman ≥ +0.020 — was missed by every specification on 2024-25, the tuning
season chosen to flatter them: **+0.0087** (w = 0.75, m = 1.00), **+0.0078** (w = 1, m = 1.517), **+0.0085**
(w = 0.75, m = 1.517), **+0.0094** (conditional, w = 0.75, m = 1.396). Four specifications, the same value.
`assembly.PROPS_HOOK` stays **None** and `props_feature.PROPS_ACTIVE` stays **False**. The `--holdout` guards were
built, verified both ways, and never run; 2025-26 was spent on season figures instead (`Logs/props_season_log.md`,
trade recorded there), and those figures — −56 like-for-like and −107 chip-inclusive — neither confirm nor
overturn the component result and were never permitted to.

**What WAS established, and should not be lost:**
1. **The market prices anytime-scorer CONDITIONAL on appearance.** Verified from the books' own house rules at 5
   of the 7 consensus books (void on a non-runner at DraftKings, BetMGM, Bovada; void unless the player STARTS at
   BetRivers, MyBookie; FanDuel and 1xBet unverified), and confirmed empirically (P1, `Logs/props_conditional_prereg.md`):
   written-off players who actually started were priced at a calibration ratio of **1.08** against a likely-starter
   control of **1.00**; the unconditional alternative predicted 0.13–0.20 and the observed ratio was 2.12.
2. **The conditional specification is the correct one.** It repaired condition (2): the written-off band went from
   −0.0283 to −0.0165 and the calibration ratio from 7.33 to 2.59 (1.89 with the minutes-model floor refit — see
   KNOWN_ISSUES #18 — and 1.37 with the two unverified books assigned to the start rule).
3. **Squad-relevant rank improved on all four specifications and cleared the bar** (+0.0243, +0.0234, +0.0220,
   +0.0206), with Brier and log loss improving on both decision partitions once m was calibrated.
4. **Likely-starter rank did not.** Among players who definitely start, `npxg90` — the rate blend the incumbent
   already carries — is already close to what the market knows. That is the finding: the market's information
   about goals lives in WHO plays, which the appearance model owns, and in the fringe, where decisions are not made.

Also on record from the workstream: the whole-board de-vig defect and its shared-set correction (Addendum 1); that
a rank criterion cannot set a level parameter and m must be calibrated (Addendum 2); that the tuning data could not
separate w = 0.75 from w = 1.0 and w was set by prior (Addendum 3); the crosswalk at 98.7–98.8% precision with an
evidenced manual pass; the raw pull, its backup and its manifests. Nothing in this file is amended by the close-out.
