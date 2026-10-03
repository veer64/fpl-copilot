# Tool bugs found by the v1 eval questions

Measured 2026-10-02 against the **laptop** database (`DB_HOST` unset, so
`db_write.connect()` used `localhost`; database `fpl`, runs 3-24, latest
SUCCESS run 24 = GW6, frame GW6-11, `players_live.updated_at`
2026-09-29 11:01:51Z). Confirmations are direct Python calls to the tool
functions in `model_tools.py` and to pure helpers in `squad_store.py` /
`squad/squad_state.py`. `set_my_squad`, `propose_transfers` and `search_news`
were never called; nothing was written. Tools that need the FPL bootstrap
(`get_my_xi`, `health`, and the no-gameweek defaults of `explain_prediction` /
`compare_predictions`) were not called either, so anything that depends on
them is marked `no` in the confirmation column with the reason in the fix line.

"Confirmed by direct call" means the stated behaviour was reproduced in this
session. `not callable` means the only path to it writes to the database.

## Table 1 - BUGS

| id | tool | what's wrong | file:line | confirmed by direct call | question ids | severity | fix | status |
|---|---|---|---|---|---|---|---|---|
| B1 | list_players | `position="GKP"` matches nothing: the column holds `GK` | model_tools.py:206 | yes (GKP 0 rows, GK 25) | list_players #1 | wrong answer | map GKP to GK before the ILIKE | fixed 38cf5e7 |
| B2 | list_players | `position[:3]` truncation kills "Goalkeeper" and "Forward" | model_tools.py:207 | yes (both 0 rows; Defender 25) | list_players #2 | wrong answer | map the four full words to the four codes | fixed 38cf5e7 |
| B3 | list_players, resolve_player | `team` is an unaliased substring: "Tottenham" matches nothing, "Man" merges two clubs | model_tools.py:189-191, 203-204 | yes (Tottenham 0; Man 25 rows over Man City + Man Utd) | list_players #4, #5; resolve_player #8 | wrong answer | resolve the club through `_resolve_team` first | fixed 38cf5e7 (resolve_player d318cc5, list_players 38cf5e7) |
| B4 | list_players | silent `LIMIT 25`: no total, no truncation flag | model_tools.py:208 | yes (Hull City 25 of 43; no filters 25 of 667) | list_players #3, #6 | misleading | return the match count and a `truncated` flag | fixed 38cf5e7 |
| B5 | list_players | every empty case returns a bare `[]` with no reason | model_tools.py:211 | yes (Everton+GKP 0, Everton+GK 3) | list_players #5 | misleading | return an explicit error naming the filter that matched nothing | fixed 38cf5e7 |
| B6 | list_players | ordered by price descending only; "cheapest" cannot be asked | model_tools.py:208 | yes | list_players #7 | misleading | accept an order argument | open |
| B7 | resolve_player | substring matches mid-word: "Son" returns 6 of 44, none of them named Son | model_tools.py:187 | yes (Alisson, Robertson, Patterson, Robinson, Johnson) | resolve_player #1 | wrong answer | match on token boundaries and rank exact hits first | fixed d318cc5 |
| B8 | resolve_player | no accent folding in either direction | model_tools.py:185-192 | yes ("Odegaard" 0; "Ødegaard" 1) | resolve_player #4 | wrong answer | unaccent both the query and the column | fixed d318cc5 |
| B9 | resolve_player | only the stored full name is searched, so FPL's web name misses | model_tools.py:185-187 | yes ("Bruno Fernandes" 0; stored "Bruno Borges Fernandes") | resolve_player #3 | wrong answer | also match when every query token is a name token | fixed d318cc5 |
| B10 | resolve_player | `LIMIT 6` drops matches silently | model_tools.py:192 | yes ("James" 6 of 12; Reece James absent) | resolve_player #5 | wrong answer | return the total and flag the truncation | fixed d318cc5 |
| B11 | resolve_player | `club` is a hard AND, so a wrong club erases a single good hit | model_tools.py:189-191 | yes (Semenyo+Bournemouth error; Semenyo is Man City) | resolve_player #6 | misleading | narrow only when several hits remain, keep hits when none do | fixed d318cc5 |
| B12 | resolve_player | one wording for a typo, a non-league player and a departed player | model_tools.py:195 | yes ("Mbappe" and "halaand" identical) | resolve_player #9 | misleading | separate "no match" from "not in this league" | fixed d318cc5 |
| B13 | resolve_player | several matches carry no ambiguity flag | model_tools.py:194-195 | yes (Palmer returns 2 rows, no flag) | resolve_player #2; compare_players #7 | misleading | return an `ambiguous` block with labels | fixed d318cc5 |
| B14 | resolve_player, get_player_card, get_prediction | departed players stay in the pool with a price and a full six-gameweek forecast | model_tools.py:182-231; db_write.py:448 | yes (Watkins status u, "Has joined Al Hilal permanently", price 7.8, horizon 1.8) | resolve_player #7; get_player_card #3; compare_players #3 | misleading | mark `status='u'` candidates as unavailable before any number | open |
| B15 | get_player_card | a non-integer id raises and the error text leaks the SQL statement | model_tools.py:215; agent.py:362 | yes (InvalidTextRepresentation plus the SELECT text) | get_player_card #2 | crash | validate the id and return a clean error | fixed edc4a89 |
| B16 | get_player_card | the availability block has no age; the 6-hour rule never reaches a card | model_tools.py:224-227; config_roles.py:30 | yes (as-of 2026-09-29, measured 2026-10-02, no age field) | get_player_card #1 | misleading | add `age_hours` and a stale marker | open |
| B17 | get_player_card | `as_of` is the build's write clock, not when the bootstrap was fetched | model_tools.py:226; db_write.py:472 | yes (as-of 11:01:51Z vs run built_at 11:01:48Z) | get_player_card #1 | misleading | store the fetch time and surface that | open |
| B18 | get_player_card, get_prediction | no stale-by-one label, unlike every other prediction tool | model_tools.py:228-230, 324-332 | yes (no `note_stale` / cutoff key) | get_player_card #6; get_prediction #1 | misleading | add `predictions_as_of_cutoff_gw` and `note_stale` | open |
| B19 | get_player_card | `get_prediction`'s error is swallowed; the card is simply missing a prediction | model_tools.py:228-230 | no (0 such players in this data) | get_player_card #3 | misleading | carry the reason onto the card | open |
| B20 | get_prediction | a gameweek outside the run's horizon is reported as "not in the pool at that cutoff" | model_tools.py:309-310 | yes (gw 1 and gw 20 give the same text) | get_prediction #3, #4 | misleading | name the gameweeks the run covers | open |
| B21 | get_fixtures | a past or uncovered gameweek is reported as a blank gameweek | fixtures_tool.py:163-166 | yes (gw 3 returns `blank_gameweek: true`) | get_fixtures #2, #3 | wrong answer | separate out-of-range and postponed from a real blank | open |
| B22 | get_fixtures | horizon clamped to 1-10 silently; the request is never echoed | fixtures_tool.py:148 | yes (99 returned GW6-15; 0 returned GW6) | get_fixtures #4 | misleading | echo `horizon_requested` and say it clamped | open |
| B23 | get_fixtures, get_league_table, get_match_stats | club resolution refuses official names and last season's clubs | model_tools.py:1735-1752 | yes ("Tottenham Hotspur" and "Wolves" both refused) | get_fixtures #5; get_league_table #9; get_match_stats #7 | wrong answer | widen the alias table and match on tokens | open |
| B24 | get_fixtures | each difficulty carries an easy/average/hard band from hardcoded thresholds, which invites one composite | fixtures_tool.py:94-121 | yes (attacking "easy", defensive "easy") | get_fixtures #1, #7 | misleading | drop the band or document how the thresholds were derived | open |
| B25 | get_fixtures | no cap when `team` is omitted | fixtures_tool.py:138-156 | yes (100 entries, 190,162 characters, against a 1024-token reply) | get_fixtures #8 | wrong answer | cap the payload and summarise | open |
| B26 | get_price_movements | `window_days=0` collapses the window and reports nothing moved | prices_tool.py:95-107 | yes (`window_hours_actual` 0.0, 1 snapshot) | get_price_movements #2 | misleading | refuse under one day or state the collapse | open |
| B27 | get_price_movements | a window shorter than the sampling gap is widened silently | prices_tool.py:95-107 | yes (1 day requested, 153.8 hours observed) | get_price_movements #2 | wrong answer | say the window was widened, in the same block | open |
| B28 | get_price_movements | both lists cut at 25 with no per-direction count or flag | prices_tool.py:52, 163-165 | yes (304 moved, 25 risers + 25 fallers returned) | get_price_movements #7 | misleading | return counts per direction and a flag | open |
| B29 | get_price_movements | mover rows carry no club and no position | prices_tool.py:150-162 | yes | get_price_movements #5 | misleading | add team and position to each row | open |
| B30 | get_price_movements | "now" is the newest snapshot, so a dead poller looks current | prices_tool.py:95-103, 128-140 | yes (newest snapshot 2026-09-25, measured 2026-10-02, no age field) | get_price_movements #6 | misleading | compare to the clock and report the archive's age | open |
| B31 | get_price_movements | `season_total_falls` is negative for a riser although the name says falls | prices_tool.py:150-162 | yes (net +0.4 beside falls -0.4) | get_price_movements #4 | misleading | rename it or carry a magnitude | open |
| B32 | get_league_table | `form_last_n` clamped to 1-38 silently; a non-numeric value raises | model_tools.py:2001; league_table.py:44 | yes (0 to 1, 100 to 38, "five" raises ValueError) | get_league_table #5 | misleading | echo the clamp and validate the type | open |
| B33 | get_league_table | `as_of` takes anything pandas parses and reads slash dates month-first while the archive is day-first | league_table.py:131-143 | yes ("01/02/2026" became 2026-01-02) | get_league_table #8 | wrong answer | require ISO, or parse day-first like the archive | open |
| B34 | get_league_table | a future `as_of` is accepted with no check | model_tools.py:1920-2067 | yes ("2030-01-01" accepted) | get_league_table #2 | misleading | refuse a cutoff after now | open |
| B35 | get_match_stats | an empty row set plus an opponent crashes | model_tools.py:2196; match_stats.py:119-199 | yes (KeyError 'result') | get_match_stats #9; routing #17 | crash | build the empty frame with every column the readers use | fixed edc4a89 |
| B36 | get_match_stats | a club whose spelling changed between seasons loses its earlier meetings and reports a stated zero | match_stats.py:119-199; squad/dixon_coles.py ARCHIVE_NAME_ALIAS | yes (Ipswich Town v Arsenal over 3 seasons: 0 meetings) | get_match_stats #8 | wrong answer | normalise club names across seasons before the join | open |
| B37 | get_match_stats | `stats` passed as a string is iterated character by character | match_stats.py:86-103 | yes (`['c','o','r','n','e','r','s']`) | get_match_stats #5 | misleading | coerce a string to a one-element list | open |
| B38 | get_match_stats | the unknown-stat error advertises four stats that are then refused by name | match_stats.py:86-103 | yes (aerials, big_chances, passing, woodwork listed as valid) | get_match_stats #5, #6 | misleading | list only the stats actually held | open |
| B39 | explain_prediction | the constants census counts the penalties sub-line, so it says 4 of 9 when 3 of the 9 lines are constants | explain.py:311-312 | yes (Nicolas Jackson: "4 of 9", constant lines cards/DC/bonus) | explain_prediction #1, #3 | wrong answer | count lines only and report the sub-line separately | open |
| B40 | set_my_squad | the unaffordable refusal prints tenths with no units | squad/squad_state.py:208-210 | yes, via `SquadState.make_transfers` ("bank 4 + 54 - 119 = -61"); the tool itself writes | set_my_squad #6 | misleading | format money in millions in the refusal | open |
| B41 | get_my_xi | `predicted_xi_points` includes the captain twice and is not labelled as such, so it never matches the rows beside it | squad_store.py:835-844 | yes, via `_xi_points` (XI of 15.0 reported as 25.0); `get_my_xi` itself needs the FPL bootstrap | get_my_xi #3 | misleading | rename it to the ranking objective, or return the plain XI sum too | open |
| B42 | optimise | unknown locked or banned ids are accepted with no feedback | model_tools.py:1318-1340 | yes (ban 999999 solved and echoed the constraint) | optimise #6 | misleading | validate ids against the pool and say which matched nobody | open |
| B43 | get_best_squad | a budget above the FPL maximum is accepted | model_tools.py:487-493 | yes (100.1 solved and returned a squad) | get_best_squad #3 | misleading | cap at 100.0 or label the answer hypothetical | open |
| B44 | get_best_squad | the default budget silently returns the stored solve; nothing can force a fresh one | model_tools.py:487-493 | yes (default payload is `get_picks`'s, including `config`) | get_best_squad #1, #5 | misleading | say which path answered and add a force flag | open |
| B45 | get_my_squad | an unscored season is reported as a hard total of 0, indistinguishable from having scored nothing | squad_store.py:554-558; model_tools.py:531 | no (needs a seeded squad and the FPL bootstrap) | get_my_squad #5 | misleading | pass None when `squad_scores` is empty | open |

## Table 2 - BY DESIGN (not bugs; the agent must say them)

| id | tool | limit | question ids |
|---|---|---|---|
| D1 | get_prediction, explain_prediction | Bonus is fixed at zero (`bonus_mode = delete`), so every expected-points figure is a no-bonus number, about 0.3 a week light for a regular starter | get_prediction #5; explain_prediction #2 |
| D2 | all squad tools | Chips are not modelled at all: wildcard, bench boost, triple captain and free hit have no tool and no arithmetic | get_my_squad #6; limits #1, #2 |
| D3 | get_picks | No shadow configuration has run since 2026-09-11, so the shadow request is an explicit error | get_picks #2 |
| D4 | explain_prediction | Cards and defensive contribution are constants standing in for models, and the appearance line uses a flat 0.30 sub chance | explain_prediction #1, #7 |
| D5 | explain_prediction | The penalty term is about 50 times undersized (built from penalties missed, KNOWN_ISSUES #19) | explain_prediction #3 |
| D6 | compare_predictions, explain_prediction | The frame holds only the cutoff gameweek and five ahead, so a past gameweek cannot be explained or compared from it | explain_prediction #5; compare_predictions #3 |
| D7 | compare_runs | Runs before 2026-09-14 stored no terms and are never backfilled (confirmed: run 5 returns that error) | compare_runs #5 |
| D8 | get_league_table | The table is cut at a cutoff and shows exactly what the model knew; later results are absent on purpose | get_league_table #1, #2 |
| D9 | get_league_table | Odds-implied expected points are descriptive only, and for 2026-27 they are a de-margined 12-book consensus, not Bet365 | get_league_table #6, #7 |
| D10 | get_price_movements | It reports what has happened and cannot say whether a price will change next | get_price_movements #1 |
| D11 | get_match_stats | Season aggregates refuse opponent, venue and a window; big chances, woodwork, passing and aerials are held nowhere | get_match_stats #1, #2, #6 |
| D12 | get_match_stats | There is no single-season argument: `seasons` means the last N ending at the current one | get_match_stats #4 |
| D13 | set_my_squad | A write is two turns: preview with `confirm=false`, then `confirm=true` only on an explicit yes, per action | set_my_squad #1, #2; propose_transfers #5 |
| D14 | propose_transfers | The hold-versus-move gap is withheld while the model-degraded condition holds, because it is biased towards holding | propose_transfers #2 |
| D15 | get_prediction | The pre-deadline t10 run skips quantiles deliberately: a missing calculation, not an absence of uncertainty | get_prediction #7 |
| D16 | get_fixtures | Two difficulties per fixture, attacking and defensive, never averaged into one score | get_fixtures #1 |
| D17 | get_my_squad | The squad is hypothetical, seeded at GW4, and is not a real FPL entry | get_my_squad #7 |
| D18 | none | No live scores, no mini-league or rank data, no wages or contracts, no transfer-market news: there is no tool and no data | limits #2, #3, #4, #5, #6 |
| D19 | get_league_table, get_match_stats | `as_of` selects the season it falls in; a pre-season cutoff returns the previous season and says so in `season_note` | get_league_table #8 |
| D20 | get_player_card | Only FPL's next-round chance of playing is stored; "this round" is not held anywhere | get_player_card #4 |
| D21 | optimise | There is no gameweek argument: it solves the frame's cutoff gameweek only | optimise #4 |
| D22 | get_my_squad, get_price_movements | The sell rule halves a rise and rounds down, so a one-tenth rise returns nothing | get_price_movements #8; get_my_squad #4 |

## Appendix - measured evidence for the headline items

```
list_players(position="GKP")      -> 0 rows      list_players(position="GK")      -> 25
list_players(position="Forward")  -> 0 rows      list_players(position="FWD")     -> 25
list_players(team="Tottenham")    -> 0 rows      list_players(team="Spurs")       -> 25
list_players(team="Man")          -> 25 rows spanning ['Man City', 'Man Utd']
list_players(team="Hull City")    -> 25 returned of 43 matching
list_players()                    -> 25 returned of 667
resolve_player("Son")             -> 6 of 44: Alisson Becker, Alysson ..., Andrew Robertson, ...
resolve_player("James")           -> 6 of 12 (Reece James not among them)
resolve_player("Bruno Fernandes") -> error: no current player matches 'Bruno Fernandes'
resolve_player("Odegaard")        -> error;  resolve_player("Ødegaard") -> 1 hit
get_player_card("Saka")           -> raises InvalidTextRepresentation and echoes the SELECT
get_prediction(411, gw=20)        -> "not in the pool at that cutoff"  (same text for gw=1)
get_fixtures(team="Arsenal", gw=3)-> blank_gameweek: true, "no fixture for this team ... (a blank)"
get_fixtures(horizon=99)          -> gameweeks [6..15];  get_fixtures()  -> 100 entries, 190,162 chars
get_price_movements(window_days=1)-> window_days_requested 1, window_hours_actual 153.8
get_price_movements(365)          -> n_moved 304, risers 25, fallers 25
get_league_table(form_last_n=0)   -> form.last_n 1;  (=100) -> 38;  (="five") -> ValueError
get_league_table(as_of="01/02/2026") -> cutoff 2026-01-02 (month-first), season 2025-26
get_match_stats(team="Arsenal", opponent="Chelsea", as_of="2026-08-01") -> KeyError: 'result'
get_match_stats(team="Ipswich Town", opponent="Arsenal", seasons=3) -> 0 meetings, "a stated zero"
explain_prediction(166, gw=6)     -> "4 of 9 lines are constants"; constant lines are 3
squad_state.make_transfers(...)   -> "transfer set unaffordable: bank 4 + 54 - 119 = -61"
squad_state.sell_price(50, 51)    -> 50 (a one-tenth rise returns nothing)
squad_store._xi_points            -> 25.0 for an XI summing 15.0
explain_prediction(411, gw=6, run_id=5) -> "run 5 has no recorded terms ... never backfilled"
```
