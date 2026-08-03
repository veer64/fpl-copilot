# LEAKAGE.md — Known and Suspected Data Leakage Traps

This file is a living, standing checklist. Every time we discover (or even suspect)
a way that future information could leak into a feature, it gets logged here —
before it's forgotten, and before it can silently poison a model.

**Rule of thumb:** for every feature, ask — "could I have known this value on the
actual Friday before the deadline, using only data available at that moment?"
If the answer is no, or "sometimes," it belongs in this file.

---

## Confirmed traps

### 1. `xP` column (vaastav merged_gw.csv, seasons 2020-21 onward)
- **What:** FPL's own "expected points" prediction for that gameweek.
- **Why it's risky:** Per the source repo's own documented investigation, `xP` is
  scraped from FPL's `ep_this` API field *after* each gameweek ends. FPL's update
  cadence for this field is undocumented, and empirical analysis found xP's
  rolling-3 correlation with same-gameweek `total_points` is unusually high
  (~0.40) for something that's supposed to be a pre-match estimate — suggesting
  it sometimes reflects post-match information.
- **What we'll do:** Do not use `xP` as a model feature. If ever revisited, only
  use with an explicit `shift(1)` per player (i.e., last gameweek's xP, never
  the current one) — never unshifted.
- **What it IS useful for:** `xP` is FPL's own competing prediction system, not
  ground truth — `total_points` remains our actual target. But since `xP` is a
  free, pre-built "expected points" estimate, it makes a good baseline to beat
  in the model ladder (§3.5 of the master plan): once we build real models,
  we compare their accuracy against xP's accuracy (both vs. real total_points)
  to prove ours adds value, not just against naive rolling-mean baselines.

---

## Known assumptions / provenance caveats (not leakage, but same "don't forget this" spirit)

### 2. Reconstructed team-ID mappings for 2016-17 and 2017-18
- **What:** These two seasons' `merged_gw.csv` files store `team` as a numeric ID,
  not a name, and no `teams.csv` or `raw.json` exists in the source repo for
  either season to look up the real mapping.
- **What we did:** Reconstructed the ID→name mapping ourselves, using (a) the
  verified 20-club roster for each season from independent sources, and (b) the
  alphabetical-by-official-club-name ID convention confirmed real in 3 other
  seasons (2018-19, 2019-20, and a third-party FPL API reference).
- **Confidence:** High, not certain. Spot-checked against 2 real data points
  (Ospina→Arsenal in both seasons). Not independently verified against an
  archived record of the exact 2016-17/2017-18 ID list.
- **Action if this ever looks wrong:** If any downstream analysis shows
  suspicious team-level patterns for 2016-17/2017-18 specifically, revisit this
  mapping first before trusting the anomaly as real.

---

## Traps to actively watch for (seeded from the master plan, not yet hit — update as found)

### 3. Season-aggregate columns snapshotted late
- **What:** Any column that represents a full-season total/rate rather than a
  single-gameweek fact.
- **Why it's risky:** If such a column was pulled/updated after the season (or
  after the gameweek in question), using it to predict an earlier gameweek
  leaks the future into the past.
- **Status:** Not yet confirmed present in our data — watch for this specifically
  when we bring in Core-Insights and Understat next.

### 4. `chance_of_playing` fields in historical dumps
- **What:** Injury/playing-chance flags bundled into historical CSVs.
- **Why it's risky:** May reflect updates made *after* the relevant deadline,
  not the value known to managers at the time.
- **What we'll do:** Trust only our own timestamped live pulls going forward;
  treat historical injury flags as approximate, not gospel.

### 5. Cross-validation-fitted objects (calibrators, shrinkage priors, meta-learners)
- **What:** Any statistical object fit on the full dataset rather than
  walk-forward.
- **Why it's risky:** Fitting on future gameweeks and then "predicting" past
  ones with that fit is leakage, even if no individual feature looks leaky.
- **What we'll do:** Every such object must be fit walk-forward when we get to
  modeling (Week 5 onward) — no exceptions.

---

*Last updated: [fill in date when you save this] — Phase 2, Week 4*