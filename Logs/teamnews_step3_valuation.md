# Team-news investigation — step 3: adjudication + honest valuation
# (2026-08-22)

Case list fixed (52). Inputs: step-2 passages (guardian_passages.parquet),
exact replay of the baseline weeks (52/52 fidelity vs logged
raw_points/bench_points/n_subs). Values: data/teamnews/case_values.parquet.
NO simulation was run.

## Part A — hand adjudication of the 14 unverified auto-positives

Verdicts (passages printed and read; verbatim text in the parquet):

| case | verdict |
|---|---|
| 23-24 GW2 Aké | match commentary (Super Cup cross) |
| 23-24 GW31 Haaland | commentary pre; GENUINE news only post (team sheet) |
| 23-24 GW32 Gusto | ambiguous — genuine presser mention, but signals RETURN ("back in training"), not absence |
| 23-24 GW35 Neto | ALIAS COLLISION (Wolves' Pedro Neto) |
| 24-25 GW5 Rico Lewis | collision (Lewis-Potter) pre; genuine only post |
| 24-25 GW14 Jackson | commentary (his own goals) |
| 24-25 GW22 Solanke | commentary pre; genuine injury news only post |
| 24-25 GW25 Bernardo | different player's injury (González) |
| 24-25 GW31 Savinho | commentary ("cleverness was absent") |
| 24-25 GW35 Díaz | commentary (VAR) |
| 25-26 GW29 Roefs | commentary pre; the hamstring quote is post-deadline |
| 25-26 GW38 Haaland / Trossard / Guéhi | commentary/noise (finale previews) |

**Zero upgrades. Verified count stays 10 of 52; auto-classifier precision
10/24 ≈ 0.42.** Several cases (Haaland 31, Lewis 5, Solanke 22, Roefs 29)
had genuine news that surfaced only at team-sheet time — real information,
but not pre-deadline.

## Part B — bench-bounded value of the verified 10

Definition (stated, not a headline): points an informed manager recovers by
starting the best formation-legal bench alternative, NET of what autosubs
already recovered; captaincy counts only when the armband could not
self-correct (FPL auto-passes to the vice — the same next-best-predicted
pick an informed manager would make). Excludes transfer-out recovery
(upside, modest); uses realized best-bench points (optimistic selection
within its own frame). Not "recoverable points" in the naive sense — a
different XI is a different week.

| case | value | what actually happened |
|---|---|---|
| 23-24 GW16 Haaland (C) | 2.0 | autosub Schär 0; armband → vice |
| 23-24 GW34 Gusto | 0.0 | was on the bench — no XI cost |
| 24-25 GW5 De Bruyne | 0.0 | autosub Havertz 2 (best alt no better) |
| 24-25 GW11 Akanji | 1.0 | autosub Rico Lewis 0 |
| 24-25 GW14 Gabriel | 0.0 | autosub Dunk 0 (no better alt) |
| 24-25 GW19 Havertz | 0.0 | autosub Milenković 6 |
| 24-25 GW28 Martínez | 0.0 | on the bench |
| 24-25 GW29 Palmer | 0.0 | on the bench |
| 25-26 GW28 Haaland (C) | 4.0 | autosub Richarlison 5; armband → vice |
| 25-26 GW30 Konaté | 0.0 | autosub Thiaw 9 |

**Floor total: 7.0 points over three seasons (~2.3/season).**

## Part C — the three tiers (bench-bounded, per season / pooled)

| tier | 23-24 | 24-25 | 25-26 | pooled | ~/season |
|---|---|---|---|---|---|
| floor (10 verified) | 2.0 | 1.0 | 4.0 | 7.0 | 2.3 |
| middle (24 auto-pre × 0.42) | 3.3 | 3.3 | 7.5 | 14.2 | 4.7 |
| ceiling (all 52 — perfect team news, the step-4 oracle bound) | 27.0 | 11.0 | 18.0 | 56.0 | 18.7 |

## The finding

**The 52-case channel is worth far less than the ~29 pts/season the old
analysis implied — because FPL's own machinery self-heals most of it.**
Autosubs fired in 6 of the 10 verified cases (recovering 0–9 points each),
three cases had the player on the bench anyway, and BOTH captained cases
auto-passed the armband to the vice — exactly the pick an informed manager
would have made. The old ~29 counted the absent player's gross foregone
prediction; the bench-bounded NET of what the rules already recover is
~2–19/season depending on tier.

**Realistic figure for a lineup subscription, this channel only: ~5–15
pts/season** — above the middle (Guardian is one outlet; a service
aggregates pressers, beat reporters and predicted XIs, so signalled
fraction > 42%×24/52) but below the ceiling (the genuinely unsignalled
in-warmup/team-sheet class is real: 4 of the 14 adjudicated cases had news
only at team-sheet time). Two channels sit OUTSIDE this frame and are the
honest reason a service could still matter more: avoiding transfers INTO
soon-to-be-absent players, and squad-wide bench-order/captaincy hygiene —
neither is measured by the 52-case list. Step 4 (the oracle re-run) prices
the ceiling properly, path effects included.
