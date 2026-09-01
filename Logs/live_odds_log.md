# Live pre-deadline match odds — 2026-08-31

Closes the odds-prices input gap for the live deadline gameweek.
`eval/fetch_live_odds.py`: the-odds-api uk h2h -> the 2026-27 odds fixture slice's
B365H/D/A columns (the only price columns the model reads), combined file
regenerated. ~1 credit per pull.

## 1. Account resolution

The `.env` key is drawing a **500-credit allocation** (headers: used 3, remaining
497→496 across this session's calls) — it is NOT the paid 20,000/month pool the
dashboard shows (~6,000 remaining). Either the key belongs to a different (free)
account or the paid plan already lapsed on this key. **Consequence: the 2026-09-24
cancellation does not affect this key's operation**, and the free tier suffices for
h2h by ~40x (~2 pulls/gameweek ≈ 80 credits/season vs 500/month). Worth checking
the dashboard's key against `.env` at leisure; not blocking.

## 2. Bookmaker choice — de-margined MEDIAN CONSENSUS over a fixed 12-book panel

Bet365 is absent (0/20 events); the backtest's B365 closing prices cannot be
sourced here — the genuine input change, not parity-testable against 2025-26.
Chosen: median of per-book proportionally de-margined 1X2 probabilities across the
**panel present on every event at probe time**: betfair_ex_uk, betway, boylesports,
casumo, grosvenor, leovegas, livescorebet, skybet, sport888, unibet_uk, virginbet,
williamhill. Intermittent (NOT in the panel): betfred 19/20, smarkets 19/20,
betano 16, betvictor 16, coral 10, ladbrokes 10, matchbook 10, betfair_sb 9.
Reasoning: the model de-margins whatever it reads, so a single book's margin
structure is removed anyway; a single substitute book that vanished mid-season
would silently change the source, while the panel degrades GRACEFULLY AND
COUNTABLY — below MIN_BOOKS=5 panel members a fixture is left unpriced (pure DC,
counted), never thinly priced, and non-panel books never enter. Stamped:
dixon_coles' `odds_source` provenance now records both eras explicitly.

## 3. Club names (#14 class)

Explicit 20-entry map, odds-api long names -> the slice's spellings (incl.
Coventry City, Hull City, Ipswich Town verbatim; Brighton and Hove Albion ->
Brighton; Leeds United -> Leeds; Manchester United -> Man United; Nottingham
Forest -> Nott'm Forest; Tottenham Hotspur -> Tottenham). An unmapped club RAISES
(`ClubNameError`); a map target absent from the slice RAISES; an event matching no
fixture row RAISES (stale slice — refresh fixtures first). Verified live: 20/20
events priced, zero unmapped, zero thin-panel.

## 4. Lambda distribution — live consensus vs 2025-26 B365 closing

Same inversion (`_implied_lambdas`, 1X2 only — totals not needed, no code path):

| | n priced | total-goals λ mean | p10 / p50 / p90 | home λ mean | draw prob mean |
|---|---|---|---|---|---|
| 2025-26 B365 closing | 380 | 2.615 | 2.19 / 2.57 / 3.09 | 1.449 | 0.244 |
| 2026-27 consensus (GW3-4) | 20 | 2.621 | 2.35 / 2.48 / 3.13 | 1.445 | 0.243 |

**No systematic level difference** — means agree to ~0.006 goals; the tighter p10
is a 20-fixture sample, not a construction artefact. The input change is real but
its level lands where the backtest's did.

## 5. Timing and coverage

Pull at the pre-deadline build (with fetch_fixtures + build_forward_skeleton).
One pull prices everything the provider lists — **~2 gameweeks ahead** (probe:
GW3+GW4, Sep 4–14). Post-deadline movement is irrelevant to a committed decision;
later gameweeks re-price at the next deadline's pull. Steps 1+ of a horizon build
price at pure DC REGARDLESS: `ODDS_HORIZON_GWS = 0` means only step 0 reads market
prices — the same convention every backtest ran, so unpriced steps-1+ file rows
are inert; the earlier strict finding for that window mis-framed a non-regression
and is downgraded to a convention note (the DEADLINE-gw all-unpriced check stays
strict — step 0 is where prices matter). Per-fixture snapshot detail (n_books,
book last_update range, pulled_at) in the provenance sidecar — WHICH snapshot
produced a number matters. Honest note: pre-deadline snapshots for later-in-week
fixtures embed less team-news than the closing prices the backtest consumed.

## 6. Fallback (confirmed)

Unpriced fixture -> lam_w = 1.0 pure DC, `lambda_source="dc"`, counted per fixture
(360/380 slice rows today — future gws beyond the listing). Partial outage: the
build proceeds, affected fixtures pure DC with per-fixture notes; strict raises
only when the DEADLINE gameweek is entirely unpriced. Thin-panel (<5 books) joins
the same counted-unpriced path.

## 7. Parity (the gate) — PASS

Record DC source pinned, both configs, GW5/20/33: **BIT-IDENTICAL** in all six
cells. 2025-26 reads the archive verbatim (per-season file resolution); nothing
historical moved. Suite **220 passed**.

## 8. Strict preflight after the pull, 2026-27 horizon-6 combined

- **GW3 (the LIVE deadline): the odds finding is GONE.** Two remain: props book
  missing, hmin refit missing (+ the steps-1+ convention note). A baseline GW3
  strict preflight now PASSES end to end — 2026-27 graduated from "a season with
  no data" (that test's pin moved to 2027-28, with a new pin that combined-strict
  still raises on its two real gaps).
- GW1 keeps its odds finding: GW1–2 are PLAYED — a live puller cannot retro-price
  the past (historical odds are a paid feature), and no decision needs them.

## Tests (suite 220)

unmapped club raises; de-margin exact on a known example (margined and
margin-free books both -> (0.5, 0.25, 0.25) -> odds (2, 4, 4), probabilities sum
to 1); a missing panel book degrades countably (at the floor: priced with n_books
recorded; below: unpriced, and a non-panel book cannot rescue it); the
fixture-universe test now asserts the priced/unpriced SPLIT is counted per
fixture; parity unchanged both configs.

Weekly ops order gains: ... -> fetch_fixtures -> merge_live_availability ->
build_forward_skeleton -> **fetch_live_odds** (both at every deadline run).
