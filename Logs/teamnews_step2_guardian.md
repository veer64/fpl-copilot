# Team-news investigation — step 2: Guardian pre-deadline signal (2026-08-21)

Against the FIXED 52-case list (step 1, unchanged). Guardian Open Platform,
one query stream per (team, season, gw) window (deadline−10d..+3d,
section=football, full text via show-fields=body), 90 raw pages under
`data/teamnews/guardian_raw/` (raw-first; API key read from gitignored
.env, verified absent from every stored file). Passage extraction local:
per-player alias regexes (Guardian common names) + absence language with
leading word boundaries + a 140-char proximity rule — two earlier matcher
iterations are the record of why ("ill" inside Colwill/still, "rest"
inside Forest, "missed" inside dismissed, bare "misses" in live
commentary). Case-level output: `data/teamnews/guardian_passages.parquet`
(classification, earliest hit, up to 5 verbatim passages each).

## Automatic classification (an UPPER BOUND on signal — see precision note)

| | n | injury_emerging | tactical_bench | rotation_congested | post_break | flagged | unclear |
|---|---|---|---|---|---|---|---|
| pre_deadline_signal | 24 | 7 | 6 | 5 | 0 | 2 | 4 |
| post_deadline_only | 13 | 5 | 3 | 4 | 1 | 0 | 0 |
| no_coverage | 15 | 3 | 7 | 3 | 1 | 0 | 1 |

Pre-deadline lead time on auto-classified signals: median ~148h, min 38.5h.

**Precision note (manual read of all 24 pre-deadline cases):** roughly half
are genuine absence signals about the right player; the rest are residual
match-commentary noise plus one alias collision (Bournemouth's Neto vs
Wolves' Pedro Neto). The AUTOMATIC figure is therefore an upper bound;
the MANUALLY VERIFIED floor is the ten cases below. Step 3 should
re-adjudicate the remaining 14 by hand before any points valuation.

## The ten clearest verified examples (verbatim in the parquet, with URLs)

1. **De Bruyne, 2024-25 GW5** (61h pre): "Kevin De Bruyne is an injury
   doubt for Manchester City's showdown with Arsenal on Sunday after
   suffering what appeared to be a groin injury in the Champions League…"
   (FPL also flagged d/75 — partially priced.)
2. **Gabriel, 2024-25 GW14** (164h pre): "The only real blot was a late
   injury to Gabriel, who appeared to have aggravated a hamstring" +
   "Gabriel Magalhães an uncertainty". (Also d/75.)
3. **Akanji, 2024-25 GW11** (231h pre): "City, having lost Manuel Akanji
   in the warm-up…" (previous midweek cup tie).
4. **Haaland, 2023-24 GW16 — A CAPTAINED CASE** (136h pre): "Erling
   Haaland was missing, hobbling around in a plastic boot with what
   Guardiola called a 'bone stress reaction'…"
5. **E. Martínez, 2024-25 GW28** (181h pre): Emery verbatim: "Pau not,
   Tyrone Mings doubt, Emiliano Martinez doubt…"
6. **Gusto, 2023-24 GW34** (111h pre): "Cole Palmer is ill and Malo Gusto
   is injured, while Chalobah and Thiago Silva drop to the bench."
7. **Palmer, 2024-25 GW29** (38.5h pre): "…Cole Palmer and Reece James,
   the latter pair having been ill all week."
8. **Havertz, 2024-25 GW19** (185h pre): "Kai Havertz was not even part of
   the match-day squad because of a sickness bug in the camp…"
9. **Konaté, 2025-26 GW30** (183h pre): cup lineup — "…Ibrahima Konaté,
   Hugo Ekitike, Milos Kerkez and Jeremie Frimpong drop to the bench"
   (rotation pattern that repeated at the league deadline).
10. **Haaland, 2025-26 GW28 — A CAPTAINED CASE** (186h pre): "Finding
    opportunities to rest Erling Haaland has not always been easy for Pep
    Guardiola" (a rotation warning; the explicit knock report surfaced
    only on matchday).

## Reading

- The verified floor alone (10/52, incl. 2 of the 4 captained cases) says
  public pre-deadline signal EXISTS for a material minority; the
  auto-classified ceiling (24/52) says it could be near half. Steps 2's
  grouping prediction held only loosely: signals appear across ALL groups,
  including 7 auto / ~4 verified in injury_emerging — the class step 1
  thought least catchable.
- Guardian is ONE outlet with no dedicated team-news feed; a lineup
  service aggregates precisely this material plus press conferences, so
  Guardian coverage is a LOWER bound on what a service carries.
  no_coverage (15) is genuinely ambiguous — absence of Guardian evidence,
  not evidence of absence.
- Step 3: hand-adjudicate the 14 unverified pre-deadline cases, then value
  the verified set (points lost, captaincy counterfactual) — not done here.
