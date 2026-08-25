# Player-prop de-vig and consensus — build log (2026-08-24)

Governed by `Logs/props_prereg.md` §1 and §4; crosswalk at commit a7c3fce. **No tuning of w or m, no endpoint, no 2025-26 outcome read** (2025-26 appears below only in outcome-free descriptives: coverage and distributions of the market quantity itself).

## Method (stated before the results)

1. **Raw implied**: per book, per fixture, p_raw = 1 / decimal price for every priced outcome. "No Scorer" pseudo-outcomes are dropped. Board total = Σ p_raw over the whole board (matched and unmatched names alike — the book's margin applies to its whole board).
2. **Margin adjustment** (coverage log §6): anytime-scorer outcomes are not mutually exclusive, so probabilities cannot be normalised to 1. Each book is scaled proportionally so its board total equals the cross-book mean total for that fixture: p_adj = p_raw × (mean_total / book_total). Adjusted p above 0.99 is clipped and counted.
3. **Consensus**: merged BY ELEMENT (crosswalk `element`), never by name string. Equal weight over the books that price the element after adjustment. Why equal weight: every book is a noisy read of the same quantity, no reliability evidence exists yet, and a weight would be a new tunable outside the pre-registration. Consequence stated: with ~4 US books to one 1xBet, the equal-weight consensus is US-dominated; a region-balanced variant is a legitimate alternative and is NOT built here. **Assert**: after the merge no element appears twice within a fixture — fail loudly (the 28 two-spelling events in 2025-26 are the case).
4. **Rate**: λ_mkt = −ln(1 − p_consensus) per fixture (Poisson, prereg §1).
5. **Attach to (element, gameweek)**: λ summed over the player's fixtures in the gameweek (double gameweeks), p_gw = 1 − e^{−Σλ}; `n_fixtures_priced` recorded. Verified on a known double below.

## 2024-25

- Fixtures 310; (fixture, element) rows 11,958; (gameweek, element) rows 11,794; adjusted p clipped at 0.99: 1; **merge-by-element assert passed (0 duplicates)**. Books per (fixture, element): 1 book(s): 976, 2 book(s): 426, 3 book(s): 598, 4 book(s): 2,108, 5 book(s): 4,668, 6 book(s): 3,182; 1xBet on 96% of rows.

**Board totals per book, raw → adjusted** (pooled over fixtures; the adjustment scales each book to the fixture's cross-book mean):

| book | fixtures | raw total mean ± sd [min, max] | scale factor mean [min, max] | adjusted total mean |
|---|---|---|---|---|
| betrivers | 309 | 4.21 ± 0.75 [0.55, 6.59] | 1.265 [1.00, 1.65] | 5.29 |
| draftkings | 252 | 5.23 ± 0.95 [0.71, 7.54] | 0.996 [0.84, 1.24] | 5.19 |
| betmgm | 160 | 5.26 ± 0.93 [0.71, 7.85] | 0.976 [0.88, 1.14] | 5.13 |
| fanduel | 304 | 5.35 ± 1.03 [0.66, 8.59] | 0.994 [0.87, 1.18] | 5.29 |
| bovada | 305 | 5.50 ± 1.04 [0.72, 8.39] | 0.967 [0.80, 1.29] | 5.30 |
| onexbet | 308 | 6.02 ± 1.11 [0.66, 8.74] | 0.883 [0.70, 1.11] | 5.29 |

**Double-gameweek verification:** 364 doubling (gameweek, element) rows in the walkforward; priced in both fixtures 164, in one 24, in none 176.
Example GW25 Mohamed Salah: fixture p 0.630, 0.416 → λ 0.995, 0.538 → Σλ 1.534 → p_gw 0.784 (a single-fixture read would have been 0.630).

**Consensus p_gw by position** (covered rows): DEF n=4684, mean 0.075, median 0.069, p90 0.111; FWD n=1164, mean 0.329, median 0.319, p90 0.456; GK n=0, mean nan, median nan, p90 nan; MID n=5946, mean 0.185, median 0.166, p90 0.309.
**By predicted-minutes band (own-cutoff e_minutes):** <15: n=3879, mean 0.128; 15-45: n=2291, mean 0.166; 45-60: n=1224, mean 0.172; 60+: n=4400, mean 0.170.

**Coverage per pre-registered partition — the 80% gate (prereg §1):**

| partition | covered / rows | outfield-only coverage | placeholder rows inside |
|---|---|---|---|
| likely starters (p_start >= .75) | 80.3% of 4,978 | 90.3% | 0 |
| uncertain (.25-.75) | 80.6% of 3,731 | 83.0% | 0 |
| written off (p_start < .25) | 35.0% of 13,669 **← BELOW THE 80% GATE** | 40.0% | 129 |
| squad-relevant (top 30 e_points in gw) | 77.4% of 930 **← BELOW THE 80% GATE** | 97.0% | 0 |

**Placeholder-price problem:** 129 covered (gameweek, element) rows / 25 players with < 90 season minutes and p_gw ≥ 0.25 (1.09% of covered rows). Not filtered. They sit almost entirely in the written-off band (table above). Distortion of OTHER players' consensus: none through the per-element merge; some through the margin adjustment, because every priced name — matched or not — enters a book's board total, and a book carrying academy names at 0.3–0.6 has a larger total and is scaled DOWN for everyone. Quantified below.

Share of each book's raw board total carried by unmatched names plus placeholder-priced fringe (mean / max over fixtures): betmgm 2.1% / 12.1%; betrivers 0.0% / 7.1%; bovada 2.6% / 18.2%; draftkings 2.1% / 11.9%; fanduel 2.7% / 18.7%; onexbet 3.7% / 22.4%. That share is the size of the scale-factor distortion those names impose on the rest of the board at that book.

Doubling rows with no consensus, by position: {'MID': 68, 'DEF': 51, 'GK': 42, 'FWD': 15} (goalkeepers are never priced; the rest are unpriced fringe). Rows priced in ONE of two fixtures (24) carry `n_fixtures_priced = 1 < n_fixtures = 2`; the feature step must not treat their Σλ as a full-gameweek rate.

**Sanity — top 20 by consensus p_gw, 2024-25 GW20:**

| # | player | team | pos | p_gw | books | e_points (model) |
|---|---|---|---|---|---|---|
| 1 | Erling Haaland | Man City | FWD | 0.697 | 5 | 9.25 |
| 2 | Ollie Watkins | Aston Villa | FWD | 0.604 | 5 | 6.22 |
| 3 | Alexander Isak | Newcastle | FWD | 0.601 | 5 | 5.09 |
| 4 | Mohamed Salah | Liverpool | MID | 0.579 | 4 | 11.12 |
| 5 | Darwin Núñez Ribeiro | Liverpool | FWD | 0.475 | 4 | 3.59 |
| 6 | Divin Mubama | Man City | FWD | 0.461 | 4 | 0.36 |
| 7 | Luis Díaz | Liverpool | MID | 0.445 | 4 | 5.87 |
| 8 | Diogo Teixeira da Silva | Liverpool | MID | 0.444 | 4 | 4.43 |
| 9 | Cole Palmer | Chelsea | MID | 0.431 | 5 | 5.75 |
| 10 | Raúl Jiménez | Fulham | FWD | 0.427 | 4 | 3.31 |
| 11 | Cody Gakpo | Liverpool | FWD | 0.419 | 4 | 5.21 |
| 12 | Rodrigo Muniz Carvalho | Fulham | FWD | 0.412 | 4 | 1.84 |
| 13 | William Osula | Newcastle | FWD | 0.407 | 4 | 0.48 |
| 14 | Nicolas Jackson | Chelsea | FWD | 0.395 | 5 | 4.02 |
| 15 | Phil Foden | Man City | MID | 0.391 | 5 | 5.77 |
| 16 | Anthony Gordon | Newcastle | MID | 0.384 | 5 | 4.12 |
| 17 | Harvey Barnes | Newcastle | MID | 0.378 | 5 | 2.18 |
| 18 | Gabriel Fernando de Jesus | Arsenal | FWD | 0.374 | 5 | 3.83 |
| 19 | Dominic Solanke-Mitchell | Spurs | FWD | 0.372 | 5 | 3.98 |
| 20 | Francisco Evanilson de Lima Barbosa | Bournemouth | FWD | 0.371 | 5 | 3.47 |

## 2025-26

- Fixtures 380; (fixture, element) rows 15,592; (gameweek, element) rows 15,423; adjusted p clipped at 0.99: 26; **merge-by-element assert passed (0 duplicates)**. Books per (fixture, element): 1 book(s): 439, 2 book(s): 859, 3 book(s): 720, 4 book(s): 2,636, 5 book(s): 5,957, 6 book(s): 4,816, 7 book(s): 165; 1xBet on 98% of rows.

**Board totals per book, raw → adjusted** (pooled over fixtures; the adjustment scales each book to the fixture's cross-book mean):

| book | fixtures | raw total mean ± sd [min, max] | scale factor mean [min, max] | adjusted total mean |
|---|---|---|---|---|
| pinnacle | 20 | 2.35 ± 0.82 [1.05, 4.18] | 2.435 [1.22, 4.83] | 5.02 |
| betrivers | 357 | 4.92 ± 0.98 [2.97, 9.48] | 1.195 [0.70, 1.61] | 5.77 |
| draftkings | 374 | 5.15 ± 0.60 [3.39, 6.63] | 1.126 [0.84, 1.37] | 5.79 |
| betmgm | 202 | 5.75 ± 0.66 [4.22, 7.53] | 1.008 [0.83, 1.17] | 5.78 |
| fanduel | 375 | 5.89 ± 0.71 [4.16, 8.17] | 0.987 [0.73, 1.21] | 5.79 |
| mybookieag | 53 | 6.08 ± 0.78 [4.58, 7.96] | 0.927 [0.78, 1.05] | 5.61 |
| bovada | 279 | 6.63 ± 0.78 [4.55, 8.55] | 0.891 [0.72, 1.11] | 5.88 |
| onexbet | 378 | 6.66 ± 0.91 [2.16, 8.97] | 0.875 [0.74, 1.76] | 5.78 |

**Double-gameweek verification:** 409 doubling (gameweek, element) rows in the walkforward; priced in both fixtures 169, in one 22, in none 218.
Example GW36 Erling Haaland: fixture p 0.709, 0.661 → λ 1.235, 1.082 → Σλ 2.317 → p_gw 0.901 (a single-fixture read would have been 0.709).

**Consensus p_gw by position** (covered rows): DEF n=6198, mean 0.077, median 0.071, p90 0.115; FWD n=1824, mean 0.319, median 0.305, p90 0.442; GK n=0, mean nan, median nan, p90 nan; MID n=7401, mean 0.181, median 0.167, p90 0.293.
**By predicted-minutes band (own-cutoff e_minutes):** <15: n=4436, mean 0.133; 15-45: n=3565, mean 0.164; 45-60: n=1751, mean 0.175; 60+: n=5671, mean 0.162.

**Coverage per pre-registered partition — the 80% gate (prereg §1):**

| partition | covered / rows | outfield-only coverage | placeholder rows inside |
|---|---|---|---|
| likely starters (p_start >= .75) | 86.5% of 6,042 | 97.3% | 0 |
| uncertain (.25-.75) | 91.9% of 4,748 | 94.5% | 9 |
| written off (p_start < .25) | 31.4% of 18,548 **← BELOW THE 80% GATE** | 36.5% | 154 |
| squad-relevant (top 30 e_points in gw) | 79.4% of 1,140 **← BELOW THE 80% GATE** | 96.6% | 0 |

**Placeholder-price problem:** 163 covered (gameweek, element) rows / 30 players with < 90 season minutes and p_gw ≥ 0.25 (1.06% of covered rows). Not filtered. They sit almost entirely in the written-off band (table above). Distortion of OTHER players' consensus: none through the per-element merge; some through the margin adjustment, because every priced name — matched or not — enters a book's board total, and a book carrying academy names at 0.3–0.6 has a larger total and is scaled DOWN for everyone. Quantified below.

Share of each book's raw board total carried by unmatched names plus placeholder-priced fringe (mean / max over fixtures): betmgm 2.4% / 14.3%; betrivers 0.4% / 17.3%; bovada 3.7% / 17.1%; draftkings 1.8% / 14.2%; fanduel 2.5% / 23.2%; mybookieag 3.0% / 10.3%; onexbet 3.6% / 20.3%; pinnacle 0.0% / 0.0%. That share is the size of the scale-factor distortion those names impose on the rest of the board at that book.

Doubling rows with no consensus, by position: {'MID': 101, 'DEF': 52, 'GK': 44, 'FWD': 21} (goalkeepers are never priced; the rest are unpriced fringe). Rows priced in ONE of two fixtures (22) carry `n_fixtures_priced = 1 < n_fixtures = 2`; the feature step must not treat their Σλ as a full-gameweek rate.

## Findings that need a decision BEFORE tuning (no method changed here; prereg §4 governs as written)

1. **The whole-board proportional margin adjustment is mis-specified when boards differ in size.** It reads a
   book's board total as its margin, but a book that prices fewer players has a smaller total for that reason
   alone. Measured board sizes (players priced, mean share of the fixture's largest board): 1xBet 37.7–40.9
   (0.99), FanDuel/DraftKings/BetMGM/Bovada 34–40 (0.90–0.95), **BetRivers 26–30 (0.69–0.73)**, **Pinnacle
   (2025-26, 20 fixtures) 4.5 (0.12)** — a favourites-only board. Consequences, measured: Pinnacle is scaled
   ×2.43 on average (max ×4.83) and produced 45 of the raw clipped probabilities; on its 20 fixtures the
   consensus with Pinnacle differs from the consensus without it by up to **0.116**, with **33% of elements
   moved by more than 0.02** — larger than the cross-region floor in the pass condition. BetRivers' ×1.20–1.27
   scaling is partly the same artefact. Proposed amendment (for a dated addendum to props_prereg.md, not
   applied): (a) exclude a book from a fixture when its board is below 50% of the fixture's largest board
   (this removes Pinnacle only); (b) compute the margin scale on the SHARED element set — the elements priced
   by every retained book on that fixture — so board size cannot masquerade as margin.
2. **The 80% coverage gate (prereg §1) fails on the squad-relevant partition in both seasons as written**:
   77.4% (2024-25) and 79.4% (2025-26), and likely starters sits at 80.3% in 2024-25. Outfield-only the same
   partitions are 97.0% / 96.6% and 90.3% / 97.3%. The shortfall is entirely goalkeepers, whom no book prices
   in any fixture (0 covered GK rows in either season) and whose goals term is ~0 by rule. Proposed amendment
   (for the same addendum): the props feature and its endpoints are defined on OUTFIELD players; goalkeepers
   keep the model's rate. Recorded as a pre-registration change, not decided here.
3. **Double gameweeks are only partly priced at the deadline.** Of doubling (gameweek, element) rows in the
   walkforward, priced in both fixtures 164 / 169, in one fixture 24 / 22, in none 176 / 218 (2024-25 /
   2025-26; the "none" rows are 42 / 44 goalkeepers plus unpriced fringe). Rows priced in one fixture carry
   `n_fixtures_priced = 1 < n_fixtures = 2`; the feature must not read their Σλ as a full-gameweek rate (use the
   model's rate for the unpriced fixture, or leave the row uncovered — to be decided in the feature step).
4. **Placeholder prices are visible at the top of the board.** The GW20 2024-25 sanity list is headed by
   Haaland 0.70, Watkins 0.60, Isak 0.60, Salah 0.58 — as expected — but also carries Divin Mubama (Man City,
   < 90 season minutes) at 0.46 and William Osula at 0.41. Placeholder rows are 1.1% of covered rows and sit
   entirely in the written-off band (0 in the likely-starter and squad-relevant partitions), so they do not
   touch the pass-condition partitions directly; they distort other players only through the margin
   adjustment (unmatched + placeholder names carry 2–4% of a book's board total on average, up to 20–23% on
   the worst boards). Not filtered, per instruction.
5. **The market's view of low-predicted-minutes players is not the model's.** Covered rows with own-cutoff
   e_minutes < 15 carry a mean consensus p of 0.13 (n ≈ 3.9k / 4.4k) against 0.16–0.17 for the 60+ band. An
   anytime-scorer price folds in appearance probability; the model's step-0 e_minutes and the market disagree
   about who plays. That is the information the feature is supposed to bring, and also where a wrong
   crosswalk or a placeholder price would look identical to signal — the sliced endpoint is what separates them.

Nothing above has been applied. Tuning of (w, m) has not started; no endpoint has been computed; no 2025-26
outcome has been read.

