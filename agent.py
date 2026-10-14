# Tools over the MODEL's outputs (model_tools.py). Every prediction answer
# carries model_version and built_at; picks say when they were recovered
# post-deadline. Since 2026-09-12 the model runs several times a week and
# every answer also carries `built` (when it was built and what it knew) and
# `next_run_expected`: QUOTE the built line and tell the user when to check
# back ("as of Wednesday 11:00Z ...; check back after Friday 16:00Z when the
# deadline run lands"). config_roles.PRODUCTION_CONFIG ('baseline' since 2026-09-11) is
# what users get by default; a shadow squad exists only if config_roles.SHADOW_CONFIG is set.
tools_schema = [
    {
        "name": "resolve_player",
        "description": "Search for a player by name: accents, hyphens and FPL's own short name all work, and matching is on whole words. Returns `matches` (player_id, name, web_name, team, position, price, status), `total_matches`, `truncated` when more matched than are listed, `ambiguous` (more than one player answers to that name: the candidates then carry NO player_id, only name, club, position and price, and `action` says to ask the user which one -- you cannot call another tool for that player until they answer), `note` (for example that the player is at a different club from the one you named), and `suggestions` when nothing matched at all. available=false means the player cannot play for his club; lead with availability_note.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "The player's name or partial name"},
                "club": {"type": "string", "description": "Optional: narrow to one club when a name matches several players"}
            },
            "required": ["name"]
        }
    },
    {
        "name": "get_player_card",
        "description": "Full details for one player: identity, price, availability status, and the production model's predictions for the coming gameweeks. available=false means the player cannot play for his club; lead with availability_note.",
        "input_schema": {
            "type": "object",
            "properties": {
                "player_id": {"type": "integer", "description": "The player's FPL element id"}
            },
            "required": ["player_id"]
        }
    },
    {
        "name": "get_prediction",
        "description": "The production model's predicted points for a player: one target gameweek if gw is given, else the whole six-gameweek horizon of the latest run. Includes e_points, expected minutes, start probability, and the provenance: `built` says when the run was built and what it knew, `next_run_expected` when the next run lands -- quote both and tell the user when to check back. available=false means the player cannot play for his club; lead with availability_note. A gameweek outside the run's range comes back as an error with error_kind: already_played, too_far_ahead or invalid_gw.",
        "input_schema": {
            "type": "object",
            "properties": {
                "player_id": {"type": "integer", "description": "The player's FPL element id"},
                "gw": {"type": "integer", "description": "Optional target gameweek"}
            },
            "required": ["player_id"]
        }
    },
    {
        "name": "compare_players",
        "description": "Compare two players under the production model over the latest run's six-gameweek horizon: the horizon sum (the verdict's basis) and the figures for the run's FIRST gameweek (first_gw -- between deadlines that is the gameweek just played, not the next one; note_stale says so). For 'X or Y this week' prefer compare_predictions, which defaults to the next deadline's gameweek and names the terms behind the gap. Whatever you quote, name its gameweek. available=false means the player cannot play for his club; lead with availability_note.",
        "input_schema": {
            "type": "object",
            "properties": {
                "player_id_a": {"type": "integer"},
                "player_id_b": {"type": "integer"}
            },
            "required": ["player_id_a", "player_id_b"]
        }
    },
    {
        "name": "get_picks",
        "description": "The solved squad from the latest pipeline run: the fifteen, starting XI, captain, vice-captain, and bench in order. Use for 'who should I captain', 'what team should I field'. shadow=true returns the baseline config's squad (the tracked comparison), never shown as the recommendation. Optional gw asks for another gameweek of the run's horizon: the stored solve exists only for the next deadline's gameweek, so another one is computed with the same optimiser and comes back with computed=true and a planning-view note. A gameweek already played returns the PAST picks: the fifteen the model solved before that deadline, labelled past=true, with how they actually scored (points after autosubs and the captain doubled, per player too); a gameweek no run was built for is refused with error_kind no_run_for_gw naming the first that has one.",
        "input_schema": {
            "type": "object",
            "properties": {
                "gw": {"type": "integer", "description": "Optional gameweek (default: latest run)"},
                "shadow": {"type": "boolean", "description": "true for the shadow configuration's squad (none is run since 2026-09-11; returns an explicit error)"}
            },
            "required": []
        }
    },
    {
        "name": "best_squad_from_scratch",
        "description": "The best brand-new 15 from scratch with a full £100m, ignoring the user's squad. For the user's own squad use propose_transfers or get_my_xi. No gw argument: this is the NEXT DEADLINE's squad only. For 'the best squad for gameweek N' use build_squad_from_scratch with gw=N (or get_picks with gw=N): any gameweek inside the run's range can be solved, so never say a gameweek is out of range unless a tool returned error_kind too_far_ahead. Never call this when the user's own squad is the subject ('given what I already own', 'improve my team', 'the best I could get from here'), not even as a benchmark beside propose_transfers. At the default full budget this is the stored production solve (instant); a custom budget runs the real optimiser (takes seconds).",
        "input_schema": {
            "type": "object",
            "properties": {
                "budget": {"type": "number", "description": "Budget in millions, e.g. 95.5 (default 100.0)"}
            },
            "required": []
        }
    },
    {
        "name": "build_squad_from_scratch",
        "description": "Builds a brand-new 15 from scratch with a full £100m, ignoring the user's squad. Also the tool for 'the best squad for gameweek N' (pass gw=N; constraints are optional) and for any from-scratch request with a constraint -- 'ban player X from the squad', 'force X in', 'without Y' -- even when an id looks wrong: pass it and let the tool refuse, it names the problem. Constraints: force players in, ban players, or change the budget; a real MIP solve that takes seconds and returns the fifteen, the XI, the captain and the vice. For the user's own squad ('my team', 'my line-up', 'given what I own'), use propose_transfers or get_my_xi instead -- never this, and never as a benchmark beside them. Optional gw solves a chosen gameweek of the run's horizon instead of the next deadline's; that answer is a planning view and carries a note saying so. An id that matches no player is refused, and a player who cannot play for his club cannot be locked (ban him instead); an injured, suspended or doubtful player the user forces in IS built in, and the result then opens with forced_availability_warning -- quote it first, then the squad, and never say this build will refuse a player without calling it. start_player_ids must START: when the user forces players in they expect them in the line-up, so pass them here (not only as locks) unless the user says squad only; they are locked into the squad as well, and the same refusals apply.",
        "input_schema": {
            "type": "object",
            "properties": {
                "lock_player_ids": {"type": "array", "items": {"type": "integer"}, "description": "Element ids that MUST be in the squad"},
                "start_player_ids": {"type": "array", "items": {"type": "integer"}, "description": "Element ids that MUST be in the starting XI (and so in the squad)"},
                "ban_player_ids": {"type": "array", "items": {"type": "integer"}, "description": "Element ids that must NOT be in the squad"},
                "budget": {"type": "number", "description": "Budget in millions (default 100.0)"},
                "gw": {"type": "integer", "description": "Optional gameweek of the run's horizon to solve (default: the next deadline's)"}
            },
            "required": []
        }
    },
    {
        "name": "get_my_squad",
        "description": "The user's OWN fifteen -- the versioned squad state (a hypothetical entry seeded at GW4), NOT the model's free-pick solve. Returns the fifteen with purchase price, current price and what each would SELL for under FPL's rule, plus bank, total points and the version id. Free transfers: free_transfers_now is the count available for the next deadline (derived: one banked per gameweek, capped at 5); free_transfers_recorded is the stale count as of the version's own gameweek -- quote free_transfers_now. The roles it carries (recorded_captain, recorded_vice, recorded_xi, recorded_bench_in_order) are what was RECORDED when that version was written -- a record, NOT this week's advice; the `roles` block says whether they are STALE relative to the latest model run, and if so you must say so. Use for 'what is my team', 'what is my team worth' (its sell value and bank), 'what would X sell for', 'how much money do I have'. For 'who should I start / captain / bench this week' call get_my_xi instead. If it returns an error, no squad state is recorded: say exactly that and do NOT answer with get_picks instead. total_points is null with total_points_note when no gameweek has been scored yet -- that is not a total of zero.",
        "input_schema": {
            "type": "object",
            "properties": {
                "user_id": {"type": "integer", "description": "Defaults to 1, the only user"}
            },
            "required": []
        }
    },
    {
        "name": "get_my_xi",
        "description": "The NEXT DEADLINE's best starting XI, captain, vice-captain and bench order over the fifteen the user owns, solved by the production optimiser from the current model run's predictions (a real solve, about a second). Between deadlines the frame belongs to the previous deadline, so the predictions are labelled as of that cutoff (note_stale, stale_by_gameweeks) -- say so when present. Use for 'who should I start', 'who should I captain', 'what is my best XI', 'should X or Y start'. Optional gw solves the XI for another gameweek of the run's horizon; that answer is a planning view and carries a note saying so. It also reports how the recorded roles differ and the expected points they leave on the table (recorded_roles.expected_gain_vs_recorded). Nothing is written. For 'how is my line-up / my team doing / what is it costing me': give the gain, then END by asking the next_question the result carries, word for word, and stop; never offer to apply, set or record this XI. Only when the user themselves asks to adopt it, pass adopt_with to set_my_squad (it previews with confirm=false; confirm=true only after they confirm that preview).",
        "input_schema": {
            "type": "object",
            "properties": {
                "user_id": {"type": "integer", "description": "Defaults to 1, the only user"},
                "gw": {"type": "integer", "description": "Optional gameweek of the run's horizon to solve the XI for (default: the next deadline's)"}
            },
            "required": []
        }
    },
    {
        "name": "explain_prediction",
        "description": "Starts with summary_plain -- two to four plain sentences (the expected points, the biggest reasons in words, the likely range): answer from it; the technical breakdown sits under detail, for when the user asks for the maths or how the number is built. WHY the model gives a player its expected points for a gameweek: the nine lines the model actually sums (appearance, goals with a penalties sub-line, assists, clean sheet, defensive contribution, saves, goals conceded, cards, bonus), each with the inputs it was made from and one of three source words -- model (a fitted model for this player/fixture), constant (a fixed value standing in for a model the project has not built or has switched off), rule (FPL's scoring rule applied to a model output) -- plus the fixture line and one summary sentence. Quote the `summary` and the labelled lines as the tool gives them (the `rendered` block is quotable verbatim); the three words are the tool's, do not editorialise about the constants. If `reconciles` is false the result carries a `finding`: report the finding, do not present the breakdown. Between deadlines the frame is one gameweek stale (note_stale, stale_by_gameweeks) -- say so. Use for 'why is X predicted N', 'what is behind X's score', 'is that a model or a guess'. available=false means the player cannot play for his club; lead with availability_note. A gameweek outside the run's range comes back as an error with error_kind: already_played, too_far_ahead or invalid_gw.",
        "input_schema": {
            "type": "object",
            "properties": {
                "player_id": {"type": "integer", "description": "The player's element id (from resolve_player)"},
                "gw": {"type": "integer", "description": "Gameweek; defaults to the next deadline's"},
                "run_id": {"type": "integer", "description": "Explain a STORED run's prediction instead of the current frame (terms are recorded for runs from 2026-09-14; earlier runs answer with an error). gw is then required."}
            },
            "required": ["player_id"]
        }
    },
    {
        "name": "compare_runs",
        "description": "Starts with summary_plain -- the move in plain words (from what to what, between which updates, and the main reasons): answer from it; the two breakdowns and the per-term table sit under detail, for when the user asks for the maths. WHY one player's expected points for a gameweek MOVED between two runs ('Tuesday said 8.5, Friday says 6.2'): both stored breakdowns, the per-term difference (run a minus run b) ranked by size, one sentence naming the terms that account for at least 80% of the move, the constant-vs-model flags, and what each run knew (run_a.built / run_b.built -- quote both). The `rendered` block is quotable verbatim. Run ids come from get_prediction / health (the latest) or the user. Runs before 2026-09-14 have no stored terms and answer with an error: say so.",
        "input_schema": {
            "type": "object",
            "properties": {
                "player_id": {"type": "integer", "description": "The player's element id"},
                "gw": {"type": "integer", "description": "The target gameweek both runs predicted"},
                "run_id_a": {"type": "integer", "description": "The earlier (or first) run"},
                "run_id_b": {"type": "integer", "description": "The later (or second) run"}
            },
            "required": ["player_id", "gw", "run_id_a", "run_id_b"]
        }
    },
    {
        "name": "compare_predictions",
        "description": "Starts with summary_plain -- who is ahead, by how much, and the main reasons in words: answer from it; the two breakdowns and the per-term table sit under detail, for when the user asks for the maths. WHY two players' expected points differ for a gameweek: both breakdowns (see explain_prediction) on the same gameweek at the same cutoff, the per-term difference a minus b ranked by size, one sentence naming the terms that account for at least 80% of the gap, and flags where a term is a constant on one side against a model value on the other (say those out loud). The `rendered` block is quotable verbatim. Same stale-by-one labelling and identity checks. Use for 'why is X above Y', 'what separates X and Y', 'X or Y and why'. available=false means the player cannot play for his club; lead with availability_note. A gameweek outside the run's range comes back as an error with error_kind: already_played, too_far_ahead or invalid_gw.",
        "input_schema": {
            "type": "object",
            "properties": {
                "player_id_a": {"type": "integer", "description": "First player's element id"},
                "player_id_b": {"type": "integer", "description": "Second player's element id"},
                "gw": {"type": "integer", "description": "Gameweek; defaults to the next deadline's"}
            },
            "required": ["player_id_a", "player_id_b"]
        }
    },
    {
        "name": "propose_transfers",
        "description": "The six-week transfer plan for the user's OWN squad from the production model: what to sell and buy for the next deadline (with sell prices under FPL's rule, purchase prices, hits, bank after, and the XI/captain after the move), plus the following gameweeks' indicative moves. Two real optimiser solves (the move plan, and the HOLD BASELINE that says what doing nothing scores over the same horizon): it typically takes twenty to sixty seconds and occasionally longer: say in one clause that it takes a moment and call it in the same turn -- never ask the user's permission to run it. 'Should I roll my free transfer?' is answered by calling this tool. The result carries hold_comparison: report the hold total, the move total and the gap. If hold_comparison.refused is true, give its refusal instead of the gap and do not reconstruct the gap from the two objectives yourself -- it is withheld because it is biased, not because it is missing. Optional lock_player_ids (must be in the squad: kept if owned, bought if not) and ban_player_ids (must not be: sold if owned, never bought) answer 'best plan given I am keeping X and refusing Y'. Every proposal is checked through the same legality and money rules as set_my_squad and saved with a proposal_id. It is a PROPOSAL, not an application: to make it, pass apply_with to set_my_squad (confirm=false to preview, confirm=true only when the user explicitly says so). If the response carries bug=true, say so plainly and do not present the proposal as advice. An id that matches no player is refused, and a player who cannot play for his club cannot be locked (ban him instead).",
        "input_schema": {
            "type": "object",
            "properties": {
                "horizon": {"type": "integer", "description": "Gameweeks to plan over, 1 to 6 (default 6)"},
                "lock_player_ids": {"type": "array", "items": {"type": "integer"}, "description": "Element ids that must be in the squad"},
                "ban_player_ids": {"type": "array", "items": {"type": "integer"}, "description": "Element ids that must not be in the squad"}
            },
            "required": []
        }
    },
    {
        "name": "set_my_squad",
        "description": "Record a NEW version of the user's own squad: the full fifteen after any transfers, plus captain, vice-captain and the four bench players in order. Money is derived, never supplied: players sold are valued by FPL's sell rule (purchase price plus half any rise, rounded down; falls in full), players bought cost their current price, free transfers are used first and extra transfers cost 4 points each (reported as hits). Illegal or unaffordable squads are refused with the reason. ALWAYS call with confirm=false first and show the user the preview (transfers, proceeds, cost, bank after, hits); call again with confirm=true ONLY when the user explicitly says to make the change.",
        "input_schema": {
            "type": "object",
            "properties": {
                "player_ids": {"type": "array", "items": {"type": "integer"}, "description": "All fifteen element ids after the change (retained players included)"},
                "captain_id": {"type": "integer"},
                "vice_id": {"type": "integer"},
                "bench_order_ids": {"type": "array", "items": {"type": "integer"}, "description": "Exactly four element ids, bench order first to last"},
                "gw": {"type": "integer", "description": "Gameweek the squad is set for. Defaults to, and must equal, the next deadline's gameweek; any other is refused"},
                "note": {"type": "string", "description": "Optional short reason, recorded with the version"},
                "confirm": {"type": "boolean", "description": "false = preview only (default); true = write it"},
                "proposal_id": {"type": "integer", "description": "When applying a propose_transfers result, its proposal_id (recorded in the version's provenance)"}
            },
            "required": ["player_ids", "captain_id", "vice_id", "bench_order_ids"]
        }
    },
    {
        "name": "list_players",
        "description": "List players filtered by team and/or position (e.g. 'who plays for Chelsea', 'list all defenders'). Do NOT use resolve_player for these. Returns `players` with `total_matches`, `truncated` and a `note` that names the filter when nothing matched; the position takes GK, DEF, MID or FWD or a word like goalkeeper, keeper, goalie, defender, centre-back, full-back, midfielder, forward, striker or attacker, and the club takes aliases such as Tottenham for Spurs.",
        "input_schema": {
            "type": "object",
            "properties": {
                "team": {"type": "string", "description": "Team name, partial match"},
                "position": {"type": "string", "description": "GKP, DEF, MID or FWD (full words accepted)"}
            },
            "required": []
        }
    },
    {
        "name": "get_fixtures",
        "description": (
            "Fixtures with difficulty from OUR model, not FPL's FDR. Difficulty comes back as "
            "TWO numbers per fixture -- attacking (how easy it is to score) and defensive (how "
            "easy a clean sheet is) -- because they routinely disagree and that disagreement is "
            "the point. Never average them into one score. Each fixture also carries an attack "
            "score and a defence score from 1 (hardest) to 10 (easiest), ranked among every fixture "
            "the run has priced -- quote them as two scores, never one. Use for 'who does X play', 'how are "
            "Arsenal's next five fixtures', 'is this a good run'. Each fixture says whether it "
            "is market-priced or pure Dixon-Coles, and flags a runaway strength. A gameweek the calendar does not cover is an error with error_kind out_of_range naming the range it does cover, which is not the same thing as blank_gameweek; with no team the answer is compact rows (team, gw, opponent, home, attacking, defensive) and the two-numbers rule is stated once at the top. Fixtures beyond the gameweeks the model has rated are listed with a rating line 'scheduled but not rated yet' and their gameweek and date -- never call them not scheduled; for 'the next N gameweeks' pass horizon=N (up to 10). With a team, season_summary lists that club's known double and blank gameweeks across the whole loaded calendar (for triple captain or bench boost questions); an empty list means none are known yet."),
        "input_schema": {
            "type": "object",
            "properties": {
                "team": {"type": "string", "description": "Club name; omit for all 20 clubs"},
                "gw": {"type": "integer", "description": "One gameweek; omit to use horizon"},
                "horizon": {"type": "integer",
                            "description": "How many gameweeks from the current one (default 5)"}
            },
            "required": []
        }
    },
    {
        "name": "get_price_movements",
        "description": (
            "Risers and fallers from the stored price snapshots, and what each of the user's own "
            "players would SELL for now under the asymmetric rule (a rise is shared with FPL -- "
            "you get half rounded down; a fall is yours in full). Use for 'who is rising', 'can I afford X'; "
            "for what the user's squad is worth (its sell value and bank) use get_my_squad. It reports what HAS happened: it cannot say "
            "whether a price will change next, and a recent rise is not evidence of the next one."),
        "input_schema": {
            "type": "object",
            "properties": {
                "window_days": {"type": "integer",
                                "description": "Look back this many days (default 7)"},
                "include_squad": {"type": "boolean",
                                  "description": "Include the user's own selling prices (default true)"}
            },
            "required": []
        }
    },
    {
        "name": "get_league_table",
        "description": (
            "The league table and each club's form AS OF a cutoff -- by default the latest run's "
            "cutoff (the deadline gameweek's first kickoff), so it shows exactly the results the "
            "model knew and nothing later. Built from match results already on the volume. Use "
            "for 'how are Hull doing', 'who is top', 'what is Arsenal's form', 'home record', "
            "'have they kept clean sheets'. Returns position, played/won/drawn/lost, goals, goal "
            "difference, points, per-game rates, form (most recent LAST), home/away splits, "
            "streaks, and the market's odds-implied expected points for the matches ALREADY "
            "PLAYED (attributed to its source by season -- Bet365 for archive seasons, a "
            "de-margined multi-book consensus for the live season -- descriptive only, never a "
            "forecast). With `team`, that club's "
            "row plus its results grouped by gameweek. A club with no result yet comes back with "
            "nulls and a reason, not zeros. Says when the table is incomplete as of the cutoff."),
        "input_schema": {
            "type": "object",
            "properties": {
                "as_of": {"type": "string",
                          "description": "ISO timestamp cutoff (UTC); omit for the latest run's cutoff. as_of takes YYYY-MM-DD, or YYYY-MM-DDTHH:MM:SS for a moment inside a day, and nothing else: a slash date, a bare year or 'now' is refused rather than guessed at."},
                "team": {"type": "string", "description": "Club name; omit for the full table"},
                "form_last_n": {"type": "integer",
                                "description": "How many recent matches the form fields cover (default 5)"},
                "include_odds_xpts": {"type": "boolean",
                                      "description": "Include Bet365 odds-implied expected points for played matches (default true)"}
            },
            "required": []
        }
    },
    {
        "name": "get_match_stats",
        "description": (
            "Rich factual team stats from matches already played, as of the model's cutoff: "
            "head-to-head records and meetings, form windows, home/away splits, for and against. "
            "Use for 'how much possession has Liverpool had', 'last five Liverpool-Everton "
            "meetings', 'Arsenal's shots at home this season', 'corners for and against'. ONE "
            "stat, ONE source, named in the answer: goals/shots/shots on target/corners/fouls/cards "
            "per match from the odds archive; xG per match from Understat; possession, crosses, "
            "interceptions, tackles won, offsides and fouls drawn from FBref as SEASON AGGREGATES. "
            "The filter rule is by GRAIN, never by stat name: EVERY per-match stat (goals, shots, "
            "shots_on_target, corners, fouls, yellow_cards, red_cards, xg, npxg) accepts EVERY filter "
            "-- opponent, venue, last_n_matches, seasons -- so 'corners in the last 5 meetings with "
            "X' is opponent + last_n_matches + stats=['corners']; only the season-aggregate stats "
            "refuse opponent, venue and a window (the tool says so and returns the season figure "
            "labelled), and each stat's `filters` block states which apply. Each stat carries its grain and season "
            "coverage; a gap is stated, never filled. Big chances, woodwork, passing and aerials are "
            "held nowhere and are refused by name. Pass stat NAMES only -- never a query. A stats "
            "lookup, not advice: no price, no probability, no recommendation."),
        "input_schema": {
            "type": "object",
            "properties": {
                "team": {"type": "string", "description": "Club name (aliases like 'spurs' resolve)"},
                "opponent": {"type": "string", "description": "Restrict to meetings with this club (head-to-head). Works with every per-match stat -- goals, shots, corners, fouls, cards, xG -- and combines with venue, last_n_matches and seasons"},
                "stats": {"type": "array", "items": {"type": "string"},
                          "description": ("Stat names from the registry, e.g. goals, shots, shots_on_target, "
                                          "corners, fouls, yellow_cards, red_cards, xg, npxg, possession, "
                                          "crosses, interceptions, tackles_won, offsides, fouled; omit for "
                                          "the core set")},
                "seasons": {"type": "integer", "description": "Last N seasons ending at the current one; omit for the current season"},
                "last_n_matches": {"type": "integer", "description": "Form window over the most recent admitted matches (per-match stats only)"},
                "venue": {"type": "string", "enum": ["home", "away"], "description": "Restrict to home or away; omit for both"},
                "side": {"type": "string", "enum": ["for", "against", "both"], "description": "The team's own numbers, the opponents', or both (default for)"},
                "as_of": {"type": "string", "description": "ISO timestamp cutoff (UTC); omit for the latest run's cutoff. as_of takes YYYY-MM-DD, or YYYY-MM-DDTHH:MM:SS for a moment inside a day, and nothing else: a slash date, a bare year or 'now' is refused rather than guessed at."}
            },
            "required": ["team"]
        }
    },
    {
        "name": "get_actual_points",
        "description": "What a player ACTUALLY scored in a finished gameweek of THIS season, with FPL's own breakdown (minutes, goals, assists, clean sheet, bonus, bps, cards, saves, defensive contribution), when the data was fetched, and whether FPL had finished checking it. Pass gw for one gameweek; omit gw for every finished gameweek plus the season total. It also carries the model's own pre-deadline prediction for that gameweek when a run covered it (predicted, predicted_minus_actual) -- runs exist from a GW3 cutoff onward, so GW1 and GW2 have no prediction to compare and the tool says so. Use for 'how many points did X score', 'how did X do in GW3', 'was the model right about X'. A gameweek not played yet is refused with error_kind not_played_yet; for what the model expects, use get_prediction. This season only.",
        "input_schema": {
            "type": "object",
            "properties": {
                "player_id": {"type": "integer", "description": "FPL element id (resolve_player gives it)"},
                "gw": {"type": "integer", "description": "a finished gameweek; omit for all of them"}
            },
            "required": ["player_id"]
        }
    },
    {
        "name": "get_my_points",
        "description": "The user's OWN team score for a finished gameweek of THIS season: the squad version that was active at that gameweek's deadline, scored by FPL's rules as this project implements them -- the XI after automatic substitutions, the captain doubled (the vice instead if the captain did not play), minus 4 points per transfer beyond the free allowance. Returns points_net (what FPL would credit), points_raw, hit, captain_doubled_added (the extra points from doubling the captain's score -- not FPL bonus points; quote captain_note for it), who was doubled and whether it was the captain or the vice, the substitutions made, and bench points (reported, never scored). Pass gw for one gameweek; omit gw for every gameweek the squad existed for plus the total. Chips are not modelled, so a gameweek a chip was played in scores as an ordinary one -- say so if it matters. No squad recorded at that deadline is refused with error_kind no_squad_for_gw; a gameweek not played yet with not_played_yet. Use for 'how many points did I get', 'how did my team do in GW3', 'what is my season total'.",
        "input_schema": {
            "type": "object",
            "properties": {
                "gw": {"type": "integer", "description": "a finished gameweek; omit for all of them"}
            },
            "required": []
        }
    },
    {
        "name": "get_prediction_history",
        "description": "Every stored run's prediction for ONE player and ONE gameweek, oldest to newest -- each row says when that run was built and what kind it was (nightly, post_ingest, or the deadline-day t90 / t30 / t10) and gives its expected points, start probability and expected minutes -- plus the biggest move between consecutive runs with the two run ids compare_runs needs to explain it (biggest_move.explain_with). Use for 'what changed overnight', 'what changed since Tuesday', 'has his prediction moved', 'why did it drop': call this first, then compare_runs on the two runs it names. Never ask the user for a run id. A gameweek no run predicted is refused with error_kind no_predictions.",
        "input_schema": {
            "type": "object",
            "properties": {
                "player_id": {"type": "integer", "description": "The player's FPL element id (resolve_player gives it)"},
                "gw": {"type": "integer", "description": "The gameweek the predictions are for"}
            },
            "required": ["player_id", "gw"]
        }
    },
    {
        "name": "get_wildcard_gap",
        "description": "What a wildcard now would open up for the user's OWN squad, for the user to decide on: gameweek by gameweek over the run's range and in total, the expected points of the current squad's best XI against the best free-pick squad -- solved by the same six-gameweek planner propose_transfers uses, with transfers free this gameweek and the squad's own money -- plus how many transfers that squad is away, its XI, bench, captain, sells and buys. One real solve: twenty to sixty seconds, so say it will take a moment. Use for 'should I wildcard', 'is it time to wildcard', 'what would a wildcard get me'. Show the gap and let the user decide; never decide for them. If refused is true the gap is withheld (a runaway strength biases it) -- give the refusal, not a gap of your own. Nothing is written.",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": []
        }
    },
    {
        "name": "search_news",
        "description": ("Search the stored team news (FPL's official flags, BBC Sport, the clubs' own sites) for a player "
                        "or a club. Use it for injury, fitness, availability, suspension and team-news questions. Always pass "
                        "the player names in `players`; always also check the player's FPL status (get_player_card) and "
                        "answer in the order the AVAILABILITY ANSWERS rules give. Results carry an id (c<number>) to cite, "
                        "the source, the date and its basis, the age, whether the result is about a requested player, and "
                        "the text. `no_news_for` lists requested players with no news; `ambiguous_players` lists names that "
                        "match several players, with labels to ask the user about."),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "The question in plain words, e.g. 'Is Saka fit for the weekend?'"},
                "players": {"type": "array", "items": {"type": "string"},
                            "description": "The player names the question is about (web name or full name); always pass them"},
                "clubs": {"type": "array", "items": {"type": "string"},
                          "description": "Club names when the question is about a club's news rather than one player"}
            },
            "required": ["query"]
        }
    }
]

import os
from dotenv import load_dotenv
import anthropic
from model_tools import (list_players, resolve_player, get_player_card,
                         get_prediction, compare_players, get_picks,
                         get_best_squad, optimise, get_my_squad, set_my_squad,
                         get_my_xi, propose_transfers, explain_prediction,
                         compare_predictions, compare_runs, get_fixtures,
                         get_price_movements, get_league_table, get_match_stats,
                         get_actual_points, get_my_points, get_prediction_history,
                         get_wildcard_gap)
import uuid
from news_search import search_news as _search_news, cited_ids, citation_violations, record_citation_check, render_citations
from numeric_grounding import check as numeric_check, record_numeric_check
from now_context import context_block
from db_write import record_chat_usage
from pricing import usd as _price_usd

load_dotenv()
client = anthropic.Anthropic()

# The system prompt (master plan 5.5): a reviewed, diffable file, not a
# string in code. Loaded once at import; a missing file is a startup error,
# not a silent run without grounding rules.
from pathlib import Path
PROMPT_PATH = Path(__file__).resolve().parent / "prompts" / "system_prompt.md"
SYSTEM_PROMPT = PROMPT_PATH.read_text(encoding="utf-8")

# The model every turn is sent to; one name, so the usage log (below) and the call agree.
AGENT_MODEL = "claude-sonnet-4-6"

# Part 4b of the smoke fixes (2026-10-10): tool names reaching users. Section 9 of the prompt forbids
# them and the tools' own strings no longer carry them, but a model that has just called a tool can
# still write its name ("run it as a `build_squad_from_scratch`"). So the final text is rewritten,
# exact name -> short plain phrase, with or without backticks or "()", BEFORE the Sources list is
# added. The RAW text is what the canary scorer, the citation check and the numeric checker see, and
# what the conversation history keeps. Every tool in tools_schema must have a phrase
# (Tests/test_tool_names_plain.py), so a new tool cannot be missed.
import re
TOOL_PLAIN_PHRASES = {
    "resolve_player": "the player lookup",
    "get_player_card": "the player card",
    "get_prediction": "the prediction lookup",
    "compare_players": "the player comparison",
    "get_picks": "the model's picks",
    "best_squad_from_scratch": "the best squad from scratch",
    "build_squad_from_scratch": "a fresh squad build",
    "get_my_squad": "your squad record",
    "get_my_xi": "the line-up pick",
    "explain_prediction": "the prediction breakdown",
    "compare_runs": "the run-to-run comparison",
    "compare_predictions": "the head-to-head breakdown",
    "propose_transfers": "the transfer plan",
    "set_my_squad": "the squad change",
    "list_players": "the player list",
    "get_fixtures": "the fixture list",
    "get_price_movements": "the price movements",
    "get_league_table": "the league table",
    "get_match_stats": "the match stats",
    "get_actual_points": "the actual points lookup",
    "get_my_points": "your team's score",
    "get_prediction_history": "the prediction history",
    "get_wildcard_gap": "the wildcard comparison",
    "search_news": "the news search",
}
_TOOL_NAME_RE = re.compile(r"`?\b(" + "|".join(sorted(TOOL_PLAIN_PHRASES, key=len, reverse=True))
                           + r")\b(\(\))?`?")


def replace_tool_names(text):
    """(text with every exact tool name replaced by its plain phrase, how many were replaced).
    Whole-word only: list_players_v2 or get_picksy are left alone; `name`, name() and (name) are caught."""
    return _TOOL_NAME_RE.subn(lambda m: TOOL_PLAIN_PHRASES[m.group(1)], text)


# Batch 3 F6 (2026-10-14): plain words at the reply, the same lock as tool names. Measured on the 166 replies of
# 2026-10-13: "xPts" in 20+ replies (mostly table headers), "horizon" in 5, the squad builder's own words
# ("optimiser", "a real solve", "solved in 1.2 seconds") in 4; FPL's status letters must never reach a reader
# either. Only these forms are rewritten -- a status letter only right after "status:" / "flag:" or as "status d."
# -- so "the flag cites a hamstring" or "this won't solve it" are left alone. The RAW text stays what the checks see.
STATUS_LETTER_WORDS = {"a": "available", "d": "doubtful", "i": "injured", "s": "suspended", "u": "unavailable",
                       "n": "not in squad"}
_STATUS_COLON_RE = re.compile(r"\b(status|flag)(\s*[:=]\s*)([`'\"]?)([adisun])\3(?![\w%'`\"])", re.I)
_STATUS_SPACE_RE = re.compile(r"\b(status)(\s+)([`'\"]?)([adisun])\3(?=\s*(?:[(),.;:|]|$))", re.I | re.M)
_HORIZON_RE = re.compile(r"\b((?:[A-Za-z]+|\d+)-gameweek\s+)?horizons?\b", re.I)
_XPTS_RE = re.compile(r"\bxpts\b", re.I)
_SOLVE_NOUN_RE = re.compile(r"\b(a|the|this|that|real|fresh|new|second|full|same|one|chip-optimal|optimal)\s+solve(s?)\b", re.I)
_SOLVED_RE = re.compile(r"\b(re-)?solved(?=\s+(?:in|for|with|using|at|on)\b)", re.I)
_BUILDER_RE = re.compile(r"\b(optimi[sz]er|solver)(s?)\b", re.I)


def _cap_like(word, model):
    return word[:1].upper() + word[1:] if model[:1].isupper() else word


def plain_words(text):
    """(text with FPL's status letters, "horizon", "xPts" and the squad builder's internal words in plain words,
    how many replacements). Pure."""
    n = 0

    def status(m):
        return f"{m.group(1)}{m.group(2)}{m.group(3)}{STATUS_LETTER_WORDS[m.group(4).lower()]}{m.group(3)}"
    text, k = _STATUS_COLON_RE.subn(status, text)
    n += k
    text, k = _STATUS_SPACE_RE.subn(status, text)
    n += k

    def horizon(m):
        if m.group(1):
            return m.group(1) + "plan"
        return _cap_like("six-gameweek plan", m.group(0))
    text, k = _HORIZON_RE.subn(horizon, text)
    n += k

    def xpts(m):
        before = text_ref[0][:m.start()].rstrip(" *_")
        return "Expected points" if (not before or before.endswith(("|", "\n"))) else "expected points"
    text_ref = [text]
    text, k = _XPTS_RE.subn(xpts, text)
    n += k
    text, k = _SOLVE_NOUN_RE.subn(lambda m: f"{m.group(1)} build{m.group(2)}", text)
    n += k
    text, k = _SOLVED_RE.subn(lambda m: _cap_like("rebuilt" if m.group(1) else "built", m.group(0)), text)
    n += k
    text, k = _BUILDER_RE.subn(lambda m: _cap_like("squad builder", m.group(1)) + m.group(2), text)
    n += k
    return text, n


# What the latest reply cost and did, for the process that served it (the eval runner reads it).
LAST_TURN = {}


def _system_for_turn():
    """The system prompt for one turn: the "now" context block (today, the gameweek state, the run
    schedule, the 20 clubs -- now_context.py, from local data) prepended to the reviewed prompt. Built
    once per user turn so every API call inside the turn reads the same facts. If the block cannot be
    built at all the prompt goes alone: a turn must never die for want of a date line."""
    try:
        block = context_block()
    except Exception as e:                           # noqa: BLE001 -- the block is help, not a dependency
        print(f"  [context block not built: {type(e).__name__}: {str(e)[:200]}]")
        return SYSTEM_PROMPT
    return f"{block}\n\n{SYSTEM_PROMPT}" if block else SYSTEM_PROMPT


def call_tool(tool_name, tool_input):
    """One tool call under the failure contract: an unknown tool or an
    exception inside a tool becomes an {"error": ...} result naming the tool
    and the condition, so the model reports it (system prompt section 8)
    instead of the chat request dying with a 500. Tools' own {"error": ...}
    dicts pass through untouched."""
    fn = available_functions.get(tool_name)
    if fn is None:
        return {"error": f"tool {tool_name} is not available"}
    try:
        return fn(**(tool_input or {}))
    except Exception as e:  # noqa: BLE001 -- the contract: surface, never 500
        return {"error": f"tool {tool_name} failed: {type(e).__name__}: {_exc_text(e)}",
                "tool": tool_name, "input": tool_input}


def _exc_text(e):
    """The exception's message, trimmed. A psycopg2 error keeps only its FIRST line:
    the lines after it are the statement and a caret -- "LINE 1: SELECT * FROM
    players_live WHERE element = 'Saka'" -- and the schema has no business in the
    conversation (B15, measured 2026-10-03). Every other exception keeps its message,
    because a tool's own multi-line explanation is information the model needs."""
    msg = str(e)
    if type(e).__module__.split(".")[0] == "psycopg2":
        msg = msg.splitlines()[0] if msg.splitlines() else msg
    return msg[:600].strip()

# A lookup so we can call the right Python function by name,
# once Claude tells us which tool it wants
def search_news(query, players=None, clubs=None):
    """The agent-facing search (news_search.py): the server sets as_of = now; no other parameter is exposed."""
    return _search_news(query, players or [], clubs or [])


def _citation_check(turn_id, text, returned_ids):
    """Part 5 (log only, 2026-09-30): every c<id> the reply cites must be an id search_news returned in
    THIS turn. Logged to citation_checks; the reply is never altered; a logging failure is printed."""
    cited = cited_ids(text)
    violations = citation_violations(cited, returned_ids)
    try:
        record_citation_check(turn_id, cited, returned_ids, violations)
    except Exception as e:  # noqa: BLE001 -- the check must never take the reply down
        print(f"  [citation check not logged: {type(e).__name__}: {str(e)[:200]}]")
    if violations:
        print(f"  [citation check: {len(violations)} cited id(s) not returned this turn: {violations}]")


def _numeric_check(turn_id, text, messages):
    """Numeric grounding (log only, 2026-10-02): which numbers the raw reply states and whether each is found among
    the numbers the model could see this turn (numeric_grounding.check over `messages`). Logged to numeric_checks
    under the reply's turn id; the reply is never altered; a checker exception is caught and logged as the row's
    error; a logging failure is printed."""
    result, error = None, None
    try:
        result = numeric_check(text, messages)
    except Exception as e:  # noqa: BLE001 -- the check must never take the reply down
        error = f"{type(e).__name__}: {str(e)[:200]}"
    try:
        record_numeric_check(turn_id, result, error)
    except Exception as e:  # noqa: BLE001
        print(f"  [numeric check not logged: {type(e).__name__}: {str(e)[:200]}]")
    if error:
        print(f"  [numeric check failed: {error}]")
    elif result and result["ungrounded"]:
        print(f"  [numeric check: {len(result['ungrounded'])} of {result['numbers_found']} numbers ungrounded: "
              f"{[u['text'] for u in result['ungrounded']]}]")


def _tally_usage(acc, response):
    """Add one API response to the turn's usage tally. A response without a usage block (an older
    fake, a provider hiccup) counts as a call but leaves the token totals undetermined."""
    acc["calls"] += 1
    u = getattr(response, "usage", None)
    if u is not None:
        acc["seen_usage"] = True
        for key, attr in (("input", "input_tokens"), ("output", "output_tokens"),
                          ("cache_read", "cache_read_input_tokens"), ("cache_write", "cache_creation_input_tokens")):
            try:
                acc[key] += int(getattr(u, attr, 0) or 0)
            except (TypeError, ValueError):
                pass
    m = getattr(response, "model", None)
    if isinstance(m, str) and m:
        acc["model"] = m


def _usage_log(turn_id, usage, tool_names_replaced):
    """Part 7c (log only, 2026-10-10): one chat_usage row per reply -- the turn id numeric_checks and
    citation_checks carry, the model, the API calls, the tokens, the usd at pricing.py's rates (NULL
    when the model has no price or no usage was reported) and how many tool names the lock replaced.
    Any exception is caught and printed; the reply is never affected."""
    try:
        model = usage.get("model") or AGENT_MODEL
        seen = bool(usage.get("seen_usage"))
        toks = {k: (usage[k] if seen else None) for k in ("input", "output", "cache_read", "cache_write")}
        cost = _price_usd(model, toks["input"], toks["output"]) if seen else None
        record_chat_usage(turn_id, model, usage["calls"], toks["input"], toks["output"],
                          toks["cache_read"], toks["cache_write"], cost, tool_names_replaced)
    except Exception as e:  # noqa: BLE001 -- the log must never take the reply down
        print(f"  [usage not logged: {type(e).__name__}: {str(e)[:200]}]")


available_functions = {
    "resolve_player": resolve_player,
    "get_player_card": get_player_card,
    "get_prediction": get_prediction,
    "compare_players": compare_players,
    "get_picks": get_picks,
    "best_squad_from_scratch": get_best_squad,
    "build_squad_from_scratch": optimise,
    "list_players": list_players,
    "get_my_squad": get_my_squad,
    "set_my_squad": set_my_squad,
    "get_my_xi": get_my_xi,
    "propose_transfers": propose_transfers,
    "explain_prediction": explain_prediction,
    "compare_predictions": compare_predictions,
    "compare_runs": compare_runs,
    "get_fixtures": get_fixtures,
    "get_price_movements": get_price_movements,
    "get_league_table": get_league_table,
    "get_match_stats": get_match_stats,
    "get_actual_points": get_actual_points,
    "get_my_points": get_my_points,
    "get_prediction_history": get_prediction_history,
    "get_wildcard_gap": get_wildcard_gap,
    "search_news": search_news,
}

def run_agent(user_message: str, messages: list = None):
    if messages is None:
        messages = []

    messages.append({"role": "user", "content": user_message})
    turn_id = uuid.uuid4().hex                       # Piece 7: one id per reply, for citation_checks
    system = _system_for_turn()                      # the "now" block, rebuilt once per turn (2026-10-08)
    returned_ids = []                                # every result id search_news returned in THIS turn
    returned_results = []                            # the result dicts themselves, for the rendered citations (Part C)
    usage = {"calls": 0, "input": 0, "output": 0, "cache_read": 0, "cache_write": 0,
             "model": None, "seen_usage": False}     # Part 7c: this turn's API usage, logged with the reply

    while True:
        response = client.messages.create(
            model=AGENT_MODEL,
            max_tokens=1024,
            system=system,
            tools=tools_schema,
            messages=messages
        )
        _tally_usage(usage, response)

        messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason != "tool_use":
            for block in response.content:
                if block.type == "text":
                    raw = block.text
                    _citation_check(turn_id, raw, returned_ids)
                    _numeric_check(turn_id, raw, messages)                         # log only; never alters the reply
                    plain, n_names = replace_tool_names(raw)                       # Part 4b lock: tool names -> plain phrases
                    plain, n_words = plain_words(plain)                            # batch 3 F6: status letters, horizon, xPts
                    rendered = render_citations(plain, returned_results)           # Part C: [1], [2] + Sources
                    if rendered != raw:
                        print(f"  [raw reply: {raw}]")                             # the raw reply stays in the logs
                    LAST_TURN.clear()
                    LAST_TURN.update(turn_id=turn_id, tool_names_replaced=n_names, plain_words_replaced=n_words, **usage)
                    _usage_log(turn_id, usage, n_names)
                    return rendered, messages

        tool_results = []
        for block in response.content:
            if block.type == "tool_use":
                tool_name = block.name
                tool_input = block.input
                tool_id = block.id

                print(f"  [calling tool: {tool_name}({tool_input})]")

                result = call_tool(tool_name, tool_input)
                if tool_name == "search_news" and isinstance(result, dict):
                    hits = [r for r in (result.get("results") or []) if isinstance(r, dict) and r.get("id")]
                    returned_ids.extend(str(r.get("id")) for r in hits)
                    returned_results.extend(hits)
                if isinstance(result, dict) and "error" in result:
                    print(f"  [tool error: {tool_name}: {str(result['error'])[:200]}]")

                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tool_id,
                    "content": str(result)
                })

        messages.append({"role": "user", "content": tool_results})

if __name__ == "__main__":
    question = input("Ask about FPL: ")
    answer, _ = run_agent(question)
    print("\n" + answer)