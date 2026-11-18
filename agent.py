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
        "description": "Search for a player by name: accents, hyphens and FPL's own short name all work, and matching is on whole words. Returns `matches` (player_id, name, web_name, team, position, price, status), `total_matches`, `truncated` when more matched than are listed, `ambiguous` (more than one player answers to that name: the candidates then carry NO player_id, only name, club, position and price, and `action` says to ask the user which one -- you cannot call another tool for that player until they answer), `note` (for example that the player is at a different club from the one you named), and `suggestions` when nothing matched at all. available=false means the player cannot play for his club; lead with availability_note. When some of the names the user gives resolve and others are ambiguous, answer for every player that resolved and, in the same reply, ask only which of the ambiguous ones the user means.",
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
        "description": "Full details for one player: identity, price, availability status, and the production model's predictions for the coming gameweeks. For a question about whether ONE named player can play -- is he available, fit, injured or suspended -- call this FIRST, right after resolve_player: it is FPL's official flag (status, chance of playing with the gameweek it is for, FPL's note) with the time FPL took it, and resolve_player's `status` is not FPL's flag. Search the news after it, for context. A comparison (\"X or Y\", \"who should I pick\") is not that question: it keeps its compare route (compare_predictions for one gameweek, compare_players over the coming weeks), whose sides carry each player's FPL status. available=false means the player cannot play for his club; lead with availability_note. For two or more named players use compare_players: it writes the comparison, and a second player card in the same turn is not run.",
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
        "description": "The production model's predicted points for a player: one target gameweek if gw is given, else every gameweek the latest run covers. For 'the next N gameweeks' pass horizon=N: the answer's `span` is then the total for exactly those gameweeks, counted from the next deadline's gameweek and labelled with them -- quote it, never add gameweeks up yourself. Each gameweek's row carries `in_words` (its figures and percentages ready to quote) and each likely range `range_words`. Includes e_points, expected minutes, start probability, and the provenance: `built` says when the run was built and what it knew, `next_run_expected` when the next run lands -- quote both and tell the user when to check back. available=false means the player cannot play for his club; lead with availability_note. A gameweek outside the run's range comes back as an error with error_kind: already_played, too_far_ahead or invalid_gw. For a list or ranking of players use rank_players, never this tool once per player.",
        "input_schema": {
            "type": "object",
            "properties": {
                "player_id": {"type": "integer", "description": "The player's FPL element id"},
                "gw": {"type": "integer", "description": "Optional target gameweek"},
                "horizon": {"type": "integer", "description": "Optional: how many gameweeks to total, counted from the next deadline's gameweek, 1 to 8 ('the next 3 gameweeks' is 3). Omit for every gameweek the run covers"}
            },
            "required": ["player_id"]
        }
    },
    {
        "name": "compare_players",
        "description": "THE tool for any question comparing two or more named players -- 'X or Y', 'who is the better pick', 'how do they stack up', 'X vs Y over the next N gameweeks' -- injured, doubtful or flagged players included: its answer shows FPL's flag first and each player's own figures, so never answer such a question from player cards. Not for the armband: any captain or vice-captain question -- 'X or Y for captain', 'who should I captain', 'is X the right captain' -- goes to captain_pick, whose answer is written by code. It compares the players under the production model, written by code: a table with each player's predicted points and fixture gameweek by gameweek, each total, who is ahead and by how much, how the gap moves across the span, the price difference in £m, each player's chance of starting and FPL's flags. Its text is shown to the user as the reply, so write nothing of your own. Pass every player's id in player_ids (two to six, from resolve_player) and, when the user names a number of gameweeks, horizon ('over the next 3 gameweeks' is 3); with no horizon it covers every gameweek the latest update covers from the next deadline's -- the six-gameweek horizon. This is the route for comparing two players over the coming weeks ('who's better over the next six weeks', 'how do X and Y compare'): it carries each player's FPL flag, so the comparison needs no player card. For 'X or Y this week' prefer compare_predictions, which defaults to the next deadline's gameweek and names the terms behind the gap. A result that is an error or carries no code-built text is yours to answer from: whatever you quote, name its gameweek; available=false means the player cannot play for his club; lead with availability_note.",
        "input_schema": {
            "type": "object",
            "properties": {
                "player_ids": {"type": "array", "items": {"type": "integer"}, "description": "The players' FPL element ids, two to six, in the order the user named them"},
                "horizon": {"type": "integer", "description": "Optional: how many gameweeks to compare over, counted from the next deadline's gameweek, 1 to 8 ('the next 3 gameweeks' is 3). Omit for every gameweek the latest update covers"}
            },
            "required": ["player_ids"]
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
        "description": "The best brand-new 15 from scratch with a full £100m, ignoring the user's squad. For the user's own squad use propose_transfers or get_my_xi. No gw argument: this is the NEXT DEADLINE's squad only. For 'the best squad for gameweek N' use build_squad_from_scratch with gw=N (or get_picks with gw=N): any gameweek inside the run's range can be solved, so never say a gameweek is out of range unless a tool returned error_kind too_far_ahead. Never call this when the user's own squad is the subject ('given what I already own', 'improve my team', 'the best I could get from here'), not even as a benchmark beside propose_transfers. At the default full budget this is the stored production solve (instant); a custom budget runs the real optimiser (takes seconds). Its answer is written by code -- the fifteen by position with each player's price, predicted points, fixture and FPL flag, the captain, the vice-captain and the bench in order, the starting XI's total both ways, and the spend for the XI, the fifteen and the bank -- and that text is shown to the user as the reply, so write nothing of your own. A refusal or an error carries no such text: report it yourself.",
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
        "description": "Builds a brand-new 15 from scratch with a full £100m, ignoring the user's squad. Also the tool for 'the best squad for gameweek N' (pass gw=N; constraints are optional) and for any from-scratch request with a constraint -- 'ban player X from the squad', 'force X in', 'without Y' -- even when an id looks wrong: pass it and let the tool refuse, it names the problem. Constraints: force players in, ban players, or change the budget; a real MIP solve that takes seconds and returns the fifteen, the XI, the captain and the vice. For the user's own squad ('my team', 'my line-up', 'given what I own'), use propose_transfers or get_my_xi instead -- never this, and never as a benchmark beside them. Optional gw solves a chosen gameweek of the run's horizon instead of the next deadline's; that answer is a planning view and carries a note saying so. An id that matches no player is refused, and only a player FPL lists as unavailable or not in the squad (status u or n, `available: false` on his card: he has left the club) cannot be locked (ban him instead); an injured -- even at 0% -- suspended or doubtful player the user forces in IS built in, and the result then opens with forced_availability_warning -- quote it first, then the squad, and never say this build will refuse a player without calling it. start_player_ids must START: when the user forces players in they expect them in the line-up, so pass them here (not only as locks) unless the user says squad only; they are locked into the squad as well, and the same refusals apply. Its answer is written by code -- the fifteen by position with each player's price, predicted points, fixture and FPL flag, the captain, the vice-captain and the bench in order, the starting XI's total both ways, and the spend for the XI, the fifteen and the bank -- and that text is shown to the user as the reply, so write nothing of your own. A refusal or an error carries no such text: report it yourself.",
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
        "description": "The NEXT DEADLINE's best starting XI, captain, vice-captain and bench order over the fifteen the user owns, solved by the production optimiser from the current model run's predictions (a real solve, about a second). Between deadlines the frame belongs to the previous deadline, so the predictions are labelled as of that cutoff (note_stale, stale_by_gameweeks) -- say so when present. Use for 'who should I start', 'what is my best XI', 'should X or Y start'. For a captain or vice-captain question ('who should I captain', 'X or Y as captain') call captain_pick instead: its answer is written by code. Optional gw solves the XI for another gameweek of the run's horizon; that answer is a planning view and carries a note saying so. It also reports how the recorded roles differ and the expected points they leave on the table (recorded_roles.expected_gain_vs_recorded). Nothing is written. For 'how is my line-up / my team doing / what is it costing me': give the gain, then END by asking the next_question the result carries, word for word, and stop; never offer to apply, set or record this XI. Only when the user themselves asks to adopt it, pass adopt_with to set_my_squad (it previews with confirm=false; confirm=true only after they confirm that preview).",
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
        "description": "Not for the armband: any captain or vice-captain question -- 'X or Y for captain', 'who should I captain', 'is X the right captain' -- goes to captain_pick, whose answer is written by code. Starts with summary_plain -- who is ahead, by how much, and the main reasons in words: answer from it; the two breakdowns and the per-term table sit under detail, for when the user asks for the maths. WHY two players' expected points differ for a gameweek: both breakdowns (see explain_prediction) on the same gameweek at the same cutoff, the per-term difference a minus b ranked by size, one sentence naming the terms that account for at least 80% of the gap, and flags where a term is a constant on one side against a model value on the other (say those out loud). The `rendered` block is quotable verbatim. Same stale-by-one labelling and identity checks. Use for 'why is X above Y', 'what separates X and Y', 'X or Y and why'. This is the route for comparing players for one gameweek ('X or Y this week', 'who should I pick'): each side carries the player's FPL status word and chance of playing with the gameweek it is for, so the comparison needs no player card. available=false means the player cannot play for his club; lead with availability_note. A gameweek outside the run's range comes back as an error with error_kind: already_played, too_far_ahead or invalid_gw.",
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
        "description": "The transfer plan for the user's OWN squad, written by code: the moves for the next deadline (what each player sells for and costs, free transfers used and left, hits, the bank after, the line-up's total after the moves), the moves pencilled in for the following gameweeks, each move's predicted gain, and the comparison with making no transfer this gameweek. Its text is shown to the user as the reply, so write nothing of your own. Use it for 'what transfers should I make', 'the best I can get from what I own', 'plan my next 3 gameweeks'. It takes twenty to sixty seconds and occasionally longer: call it in the same turn -- never ask the user's permission to run it. 'Should I roll my free transfer?' is answered by calling this tool. Optional max_transfers is the most transfers the whole plan may make, across all its gameweeks: pass it whenever the user names a number of transfers ('with two transfers', 'using one transfer', 'no more than three moves') and omit it otherwise; the plan then states the limit in its first lines. A number of gameweeks is not a number of transfers ('the next three gameweeks' is horizon=3, never max_transfers=3), and the app checks the user's own words: a limit they did not state is ignored. Optional lock_player_ids (must be in the squad: kept if owned, bought if not) and ban_player_ids (must not be: sold if owned, never bought) answer 'best plan given I am keeping X and refusing Y'. Every plan is checked through the same legality and money rules as set_my_squad and saved with a proposal_id. It is a PROPOSAL, nothing is written: when the user then asks to make the moves, pass that result's apply_with to set_my_squad (confirm=false to preview). If the response carries bug=true or an error there is no code-built text: say so plainly and do not present the proposal as advice. An id that matches no player is refused, and only a player FPL lists as unavailable or not in the squad (status u or n, `available: false` on his card: he has left the club) cannot be locked (ban him instead); an injured, suspended or doubtful player the user names IS locked in, and the plan then opens with the forced_availability_warning.",
        "input_schema": {
            "type": "object",
            "properties": {
                "horizon": {"type": "integer", "description": "Gameweeks to plan over, counted from the next deadline's gameweek: 1 to 6 (default 6). 'The next 3 gameweeks' is 3"},
                "lock_player_ids": {"type": "array", "items": {"type": "integer"}, "description": "Element ids that must be in the squad"},
                "ban_player_ids": {"type": "array", "items": {"type": "integer"}, "description": "Element ids that must not be in the squad"},
                "max_transfers": {"type": "integer", "description": "Optional: the most transfers the whole plan may make, across all its gameweeks -- the number the user names ('with two transfers' is 2). Omit when the user names none"}
            },
            "required": []
        }
    },
    {
        "name": "set_my_squad",
        "description": "Record a NEW version of the user's own squad: the full fifteen after any transfers, plus captain, vice-captain and the four bench players in order. Money is derived, never supplied: players sold are valued by FPL's sell rule (purchase price plus half any rise, rounded down; falls in full), players bought cost their current price, free transfers are used first and extra transfers cost 4 points each (reported as hits). Illegal or unaffordable squads are refused with the reason. Any message naming a player to take out and a player to bring in ('sell X and buy Y', 'swap X for Y', 'replace X with Y', 'X out, Y in', 'bring in Y for X') is an instruction: resolve both, then preview it at once with confirm=false -- never argue or ask first; the preview shows the predicted gain, so a poor move is visible there. ALWAYS call with confirm=false first and show the user the preview (transfers, proceeds, cost, bank after, hits); call again with confirm=true ONLY when the user explicitly says to make the change. On the user's own team a preview that moves players comes back with its text written by code -- who goes out and in, the money, the free transfers, the predicted gain, then the Yes / No question -- and that text is shown to the user with the preview card as the reply, so write nothing of your own. A preview issues a ticket: confirm=true needs preview_ticket from a preview shown in an EARLIER turn for the same change, else nothing is written.",
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
                "proposal_id": {"type": "integer", "description": "When applying a propose_transfers result, its proposal_id (recorded in the version's provenance)"},
                "preview_ticket": {"type": "string", "description": "The preview ticket from the earlier confirm=false call for this same change (required with confirm=true)"}
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
            "is market-priced or pure Dixon-Coles, and flags a runaway strength. A gameweek the calendar does not cover is an error with error_kind out_of_range naming the range it does cover, which is not the same thing as blank_gameweek. For EVERY club (no team), for a list of more than five clubs (teams) or for the clubs of the user's own players (my_players=true -- 'who do my players face') the answer is a table written by code: one row a club, one column a gameweek, each cell the opponent, home or away, and the fixture's two ratings in words, with each club's ratings added up over the span and the next deadline; its text is shown to the user as the reply, so write nothing of your own. Never call this once per club for more than five clubs -- ask for them in ONE call. The table for every club ends with the loaded calendar's double and blank gameweeks, so 'which clubs have a double gameweek coming up' is a call with no team. A list of five clubs or fewer comes back as compact rows (team, gw, opponent, home, attacking, defensive) for you to answer from, the two-numbers rule stated once at the top. Fixtures beyond the gameweeks the model has rated are listed with a rating line 'scheduled but not rated yet' and their gameweek and date -- never call them not scheduled; for 'the next N gameweeks' pass horizon=N (up to 10). With a team, season_summary lists that club's known double and blank gameweeks across the whole loaded calendar (for triple captain or bench boost questions); an empty list means none are known yet."),
        "input_schema": {
            "type": "object",
            "properties": {
                "team": {"type": "string", "description": "Club name; omit for all 20 clubs"},
                "teams": {"type": "array", "items": {"type": "string"}, "description": "Several club names in ONE call (instead of team): more than five gives the code-built table"},
                "my_players": {"type": "boolean", "description": "true: the clubs of the user's own fifteen, with their players named, as the code-built table ('who do my players face'). It covers their next fixture unless gw or horizon is given. Needs a saved squad"},
                "gw": {"type": "integer", "description": "One gameweek; omit to use horizon"},
                "horizon": {"type": "integer",
                            "description": "How many fixtures still to come to list, counted from the clock (default 5): a kicked-off match is not among them"}
            },
            "required": []
        }
    },
    {
        "name": "get_price_movements",
        "description": (
            "Price moves from the stored price snapshots. With the user's squad saved and include_squad true (the default), "
            "the answer is about THEIR 15 and is written by code: for each player FPL's own price-change progress figure in words "
            "(toward a rise / toward a fall), what was paid, the price now, what he sells for under FPL's rule (a rise is shared "
            "with FPL: half, rounded down; a fall is yours in full), and what one more rise or one fall would change. Its text is "
            "shown to the user as the reply, so write nothing of your own. Use that for 'are any of my players close to a price "
            "change', 'price rises and falls in my squad', 'what do my players sell for'. For the wider market ('who is rising', "
            "'the biggest fallers this week') pass include_squad=false and answer from the risers and fallers it returns. For "
            "'can I afford X', preview the swap with set_my_squad; for what the squad is worth (its sell value and bank) use "
            "get_my_squad. It reports what HAS happened: it cannot say "
            "whether a price will change next, and a recent rise is not evidence of the next one."),
        "input_schema": {
            "type": "object",
            "properties": {
                "window_days": {"type": "integer",
                                "description": "Look back this many days (default 7)"},
                "include_squad": {"type": "boolean",
                                  "description": "true (default): the code-built answer about the user's own 15. false: the market's risers and fallers only, for you to answer from"}
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
            "nulls and a reason, not zeros. Says when the table is incomplete as of the cutoff. For 'the table after gameweek N' "
            "pass after_gw=N (every result before gameweek N+1's first kickoff) instead of a date. Without `team` the whole "
            "table's text is written by code -- the rows, the as-of line, nothing else -- and shown to the user as the reply, so "
            "write nothing of your own."),
        "input_schema": {
            "type": "object",
            "properties": {
                "as_of": {"type": "string",
                          "description": "ISO timestamp cutoff (UTC); omit for the latest run's cutoff. as_of takes YYYY-MM-DD, or YYYY-MM-DDTHH:MM:SS for a moment inside a day, and nothing else: a slash date, a bare year or 'now' is refused rather than guessed at."},
                "team": {"type": "string", "description": "Club name; omit for the full table"},
                "form_last_n": {"type": "integer",
                                "description": "How many recent matches the form fields cover (default 5)"},
                "include_odds_xpts": {"type": "boolean",
                                      "description": "Include Bet365 odds-implied expected points for played matches (default true)"},
                "after_gw": {"type": "integer", "description": "Optional: the table after this gameweek's matches ('after gameweek 10' is 10); not with as_of"}
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
    # Prompt R3 (2026-11-16): two answers written by code and delivered as the reply (DIRECT_TOOLS). Normal turns only: a draft
    # chat's turn sends the frozen 24 tools (DRAFT_BASE_TOOLS). search_news stays the last tool.
    {
        "name": "rank_players",
        "description": "The ranked list for ANY question that asks for the best, top, highest-scoring or best-value players: the true top N over the WHOLE player pool by predicted points, or by predicted points per £1m, for a position, a price range, a club and a span of gameweeks. Use it for 'top 8 forwards', 'best defenders under £5.0m', 'best-value midfielders', 'who are the best picks this week', 'rank the Arsenal players'. Code reads every player's predictions, adds each one up over the span, sorts them and writes the answer; its text is shown to the user as the reply, so write nothing of your own. Never build a ranking yourself from list_players and get_prediction: they cannot see the whole pool in order.",
        "input_schema": {
            "type": "object",
            "properties": {
                "position": {"type": "string", "enum": ["GK", "DEF", "MID", "FWD", "any"], "description": "The position to rank; 'any' ranks all positions together (default any)"},
                "min_price": {"type": "number", "description": "Lowest price INCLUDED, in £m: '£6.0m or more' is 6.0. Omit for no lower limit"},
                "max_price": {"type": "number", "description": "Highest price INCLUDED, in £m: '£5.0m or less' is 5.0; 'under £5.0m' is 4.9. Omit for no upper limit"},
                "horizon": {"type": "integer", "description": "How many gameweeks to add up, counted from the next deadline's gameweek: 1 to 8 (default 1 = this gameweek only). 'The next 4 gameweeks' is 4"},
                "sort": {"type": "string", "enum": ["points", "value"], "description": "points = total predicted points over the span (default); value = those points per £1m of today's price ('best value', 'value for money')"},
                "n": {"type": "integer", "description": "How many players to list, 1 to 20 (default 10)"},
                "club": {"type": "string", "description": "Optional: rank one club's players only"}
            },
            "required": []
        }
    },
    {
        "name": "review_my_squad",
        "description": "The review of the user's OWN fifteen, written by code: every player grouped by position with his price, what he sells for, his predicted points over the span, his chance of starting, his fixtures and any FPL flag; the best line-up's total; the bank and free transfers; and the three players who rank lowest for their price. Use it for any request to go through, review, assess or rate the whole squad ('review my team', 'go through my squad', 'who is worth keeping and who is a worry', 'how does my squad look for the next 3 gameweeks'). Its text is shown to the user as the reply, so write nothing of your own. Never write a whole-squad review yourself from single-player lookups. For one player, a line-up question or a transfer question, use the other tools.",
        "input_schema": {
            "type": "object",
            "properties": {
                "horizon": {"type": "integer", "description": "How many gameweeks to add up, counted from the next deadline's gameweek: 1 to 8 (default 3)"}
            },
            "required": []
        }
    },
    {
        "name": "captain_pick",
        "description": "The captain answer for the user's OWN line-up, written by code: the pick and his predicted points for the gameweek with and without the armband, the line-up's top five captain options (predicted points, likely range, chance of starting, chance of playing 60+ minutes, fixture, FPL's flag), what captaining the pick over the next option is worth, the vice-captain, and the biggest part of the pick's prediction. Its text is shown to the user as the reply, so write nothing of your own. Use it for EVERY captain or vice-captain question about the user's team: 'who should I captain', 'who gets the armband', 'X or Y as captain', 'X or Y for captain', 'should I captain X or Y', 'is Haaland the right captain' -- never compare_predictions or compare_players for these. Pass the players the user names in player_ids (ids from resolve_player; up to three of their own fifteen). Optional gw for another gameweek of the run's horizon (a planning view). A result that is an error or the no-squad note carries no code-built text: answer it yourself.",
        "input_schema": {
            "type": "object",
            "properties": {
                "player_ids": {"type": "array", "items": {"type": "integer"}, "description": "Optional: the players the user named for the armband (element ids, at most three)"},
                "gw": {"type": "integer", "description": "Optional gameweek of the run's horizon (default: the next deadline's)"}
            },
            "required": []
        }
    },
    {
        "name": "search_news",
        "description": ("Search the stored team news (FPL's official flags, BBC Sport, the clubs' own sites) for a player "
                        "or a club. Use it for injury, fitness, availability, suspension and team-news questions, and for "
                        "what a club's manager or head coach said (press conferences, programme notes), AFTER "
                        "get_player_card: for whether one named player can play, get_player_card comes first (the player's FPL status: FPL's "
                        "official flag with its time; resolve_player's `status` is not FPL's flag) and the news second, "
                        "for context. Always pass "
                        "the player names in `players` when the question names players; pass the club in `clubs` when it "
                        "names a club; when the person named is not a player (a manager, a coach) and the club is not "
                        "stated, search with the query alone: never guess the club and never ask first, the search is "
                        "the answer. Not for prediction, comparison, who-to-pick or transfer questions: those have their "
                        "own tools. Answer in the order the AVAILABILITY ANSWERS rules give. "
                        "Results carry an id (c<number>) to cite, "
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

import json
import os
import sys
from dotenv import load_dotenv
import llm
import turn_context                                     # Prompt E (2026-10-27): the loop's turn channel (the write lock reads it)
from model_tools import explain_my_draft                       # Prompt W11g G1: draft turns only (DRAFT_FUNCTIONS)
from model_tools import (list_players, resolve_player, get_player_card,
                         get_prediction, compare_players, get_picks,
                         get_best_squad, optimise, get_my_squad, set_my_squad,
                         get_my_xi, propose_transfers, explain_prediction,
                         compare_predictions, compare_runs, get_fixtures,
                         get_price_movements, get_league_table, get_match_stats,
                         get_actual_points, get_my_points, get_prediction_history,
                         get_wildcard_gap)
from model_tools import rank_players, review_my_squad         # Prompt R3: answers written by code (normal turns only)
from model_tools import captain_pick                          # Prompt R3c: the captain answer, written by code (normal turns only)
import uuid
from news_search import search_news as _search_news, cited_ids, citation_violations, record_citation_check, render_citations
from numeric_grounding import check as numeric_check, record_numeric_check
import fact_check                                       # Prompt H M1 (2026-10-30): the final answer vs this turn's tool rows
import tracing                                          # Prompt L (2026-10-30): Langfuse traces, recorded by hand, off by default
import time
import now_context
import config_roles                                     # Prompt P7: the signed-in user of a turn (clerk mode)
from now_context import context_block, now_line
from db_write import record_chat_usage
from pricing import turn_usd as _price_usd

load_dotenv()
# The client every turn goes out on, built by llm.py since 2026-10-19 (the SDK's own retries off: llm.chat
# retries a 429, a 5xx or a timeout itself, and fails fast on anything else). timeout_s=None keeps the SDK's
# default timeout (600 s read, 5 s connect), the value the agent always had. The eval runner and the canaries
# replace this attribute with a counting wrapper, so the call below must read it from the module at call
# time, never bind it.
client = llm.default_client(timeout_s=None)
# Prompt L (2026-10-30): the Langfuse client (~1 s to build) is built here, at import, when LANGFUSE_ENABLED=1 -- never
# inside a turn. Off (the default) it is never built. The Anthropic client above is not wrapped, patched or proxied: the
# loop records its own request / response through tracing.py (tracing never changes, blocks or breaks a turn).
tracing.init()

# The system prompt (master plan 5.5): a reviewed, diffable file, not a
# string in code. Loaded once at import; a missing file is a startup error,
# not a silent run without grounding rules.
from pathlib import Path
PROMPT_PATH = Path(__file__).resolve().parent / "prompts" / "system_prompt.md"
SYSTEM_PROMPT = PROMPT_PATH.read_text(encoding="utf-8")
# Prompt W11 (2026-11-12): the draft chat's wording -- appended to the turn's first text block (beside the Now line) in a draft
# chat ONLY; never in the system prompt, the tools or the stored history, so every other turn sends the same bytes (payload v5).
DRAFT_MODE_PATH = Path(__file__).resolve().parent / "prompts" / "draft_mode.md"
DRAFT_MODE_TEXT = DRAFT_MODE_PATH.read_text(encoding="utf-8").strip()
# Prompt R3 (2026-11-16): a draft chat's turn sends EXACTLY what it sent before R3 -- the system prompt and the 24 tool
# definitions of 8f61ff7, frozen as files and pinned by their sha256 (Tests/test_draft_payload.py). The prompt above
# (SYSTEM_PROMPT) and tools_schema are the NORMAL turn's: they route rankings, squad reviews, transfer plans and a squad's price
# moves to answers written by code, which a draft chat does not have.
DRAFT_FROZEN_DIR = Path(__file__).resolve().parent / "prompts" / "draft_frozen"
DRAFT_SYSTEM_PROMPT = (DRAFT_FROZEN_DIR / "system_prompt.md").read_text(encoding="utf-8")
DRAFT_BASE_TOOLS = json.loads((DRAFT_FROZEN_DIR / "tools.json").read_text(encoding="utf-8"))

# The model every turn is sent to; one name, so the usage log (below) and the call agree.
AGENT_MODEL = "claude-sonnet-4-6"

# Prompt W11g G1 (2026-11-13): ONE extra tool on a draft chat's turns only, after the 24 tools of v5 (R3: DRAFT_BASE_TOOLS).
# explain_my_draft's text is written by code and IS the reply (DIRECT_TOOLS): the model routes to it and writes nothing.
DRAFT_TOOLS = [
    {
        "name": "explain_my_draft",
        "description": "The draft's explanation, written by code from the build's own facts: how the 15 were picked, the "
                       "budget split, and for each player his club, price, predicted points, biggest breakdown parts, what "
                       "the best legal alternative would cost the build's score, his value facts and his pick rank. Call it "
                       "for ANY request to explain, talk through or justify the draft or a player in it, and (detail "
                       "'captain') for any captain or vice-captain question about the draft. Its text is shown to the user "
                       "as the reply: write no explanation of your own.",
        "input_schema": {
            "type": "object",
            "properties": {
                "detail": {"type": "string", "enum": ["summary", "each_player", "captain"],
                           "description": "'each_player' when the user asks about every / each player or player by player; "
                                          "'captain' for a captain or vice-captain question; otherwise 'summary'."},
                "player": {"type": "string", "description": "Optional: one draft player's name, for a question about him only."}
            },
            "required": ["detail"]
        }
    },
]
# Prompt R3: on a normal turn four more answers are written by code -- the ranking, the whole-squad review, the transfer plan
# and a squad's price moves. A tool's result ends the turn only when it carries "direct_reply" (an error, a bug, General mode's
# market movers and every draft-chat result do not), so each of these still answers the model when it has no text.
# Prompt R3b (2026-11-16): three more -- the best squad from scratch (both build tools), the comparison of players, and the
# fixture grid for every club or more than five. One club's fixtures, five clubs or fewer, a refusal and every draft-chat
# result carry no text, so they still go to the model.
DIRECT_TOOLS = frozenset({"explain_my_draft", "rank_players", "review_my_squad", "propose_transfers", "get_price_movements",
                          "best_squad_from_scratch", "build_squad_from_scratch", "compare_players", "get_fixtures",
                          "captain_pick", "set_my_squad", "get_league_table"})       # Prompt R3c: three more (a preview's text; normal turns)


def _draft_turn_now():
    return (turn_context.current() or {}).get("draft") is not None


def _turn_tools():
    """The turn's tool list: tools_schema on a normal turn; on a draft chat's turn the frozen 24 tools plus DRAFT_TOOLS
    (W11g G1; R3: the draft request is byte-identical to before)."""
    return DRAFT_BASE_TOOLS + DRAFT_TOOLS if _draft_turn_now() else tools_schema


def _say(text):
    """Prompt W11g G6: a log line that can never crash a turn -- a console that cannot encode a character (Windows cp1252 and
    "Vušković": the W11f eval's case 7) gets it replaced, never an exception."""
    try:
        print(text)
    except UnicodeEncodeError:
        enc = getattr(sys.stdout, "encoding", None) or "ascii"
        print(str(text).encode(enc, errors="replace").decode(enc, errors="replace"))

# Prompt W11f V2 (2026-11-13): the reply cap. A draft chat's fifteen-player walkthrough needs ~1,000-1,200 tokens and was cut
# off at 1,024, so a draft turn's requests (the call and the send-back) get 2,048.
# Prompt R1 / R3 (2026-11-16): normal turns were cut off at 1,024 too (W11f: 21 of 1,290 saved non-draft replies ended
# mid-sentence -- squads, plans, lists, tables), so EVERY turn gets 2,048 (payload v6); a reply that still stops at the cap is
# trimmed to complete markdown and ends with CUT_OFF_LINE (_fact_check_start, _finish).
MAX_TOKENS = 2048
DRAFT_MAX_TOKENS = 2048


def _max_tokens():
    """The reply cap of THIS turn's requests: DRAFT_MAX_TOKENS on a draft chat's turn, MAX_TOKENS on every other."""
    return DRAFT_MAX_TOKENS if (turn_context.current() or {}).get("draft") is not None else MAX_TOKENS

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
    "captain_pick": "the captain pick",
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
    "explain_my_draft": "the draft explanation",
    "rank_players": "the player ranking",
    "review_my_squad": "the squad review",
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
_HORIZON_RE = re.compile(r"\b((?:[A-Za-z]+|\d+)-(?:game)?week\s+)?horizons?\b", re.I)   # R3: "six-week horizon" keeps its own count
_XPTS_RE = re.compile(r"\bxpts\b", re.I)
_SOLVE_NOUN_RE = re.compile(r"\b(a|the|this|that|real|fresh|new|second|full|same|one|chip-optimal|optimal)\s+solve(s?)\b", re.I)
_SOLVED_RE = re.compile(r"\b(re-)?solved(?=\s+(?:in|for|with|using|at|on)\b)", re.I)
_BUILDER_RE = re.compile(r"\b(optimi[sz]er|solver)(s?)\b", re.I)
# Batch 3 F8 follow-up (2026-10-14): the eval of dc34992 found the bonus sentence personalised -- "top-ranked players like
# Haaland tend to pick up a few extra points" (get_picks:1, explain_prediction:5, routing:12, get_prediction:10), a
# player-specific bonus claim the judge fails (M3a). The name inserted into the sentence is removed at the reply.
_BONUS_NAMED_RE = re.compile(
    r"\b(top-ranked players)\s*(?:\(\s*(?:like|such as|e\.g\.?|including)\s+[^)]{1,80}\)|,?\s*(?:like|such as|including)\s+"
    r"[A-Z][\w'’.\-]+(?:\s+[A-Z][\w'’.\-]+)?(?:\s*(?:,|and|or|&)\s*[A-Z][\w'’.\-]+(?:\s+[A-Z][\w'’.\-]+)?)*,?)\s+(tend to)\b",
    re.I)


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
        return _cap_like("plan", m.group(0))            # R3: was "six-gameweek plan", whatever the plan's length
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
    text, k = _BONUS_NAMED_RE.subn(lambda m: f"{m.group(1)} {m.group(2)}", text)
    n += k
    return text, n


# What the latest reply cost and did, for the process that served it (the eval runner reads it).
LAST_TURN = {}
# Prompt H M1 (2026-10-30): the last turn's fact check -- {facts_checked, mismatches, sent_back, outcome, note,
# rewrite_mismatches, extra_usd, extra_seconds, error, original, delivered}; the eval runner stores it per turn.
LAST_FACT_CHECK = {}
FACT_CHECK_TOOL_CHOICE = {"type": "none"}            # the send-back: the tools stay in the request (cache), tool use is off

# Prompt E loop guard (2026-10-27). A response with no text block and no tool_use block -- measured on the sonnet-5
# gate (eval/reports/agent_sonnet5_gate_v1.md): stop_reason max_tokens with a lone thinking block -- used to become
# an EMPTY tool_results user message and an HTTP 400 on the next call. Now the turn ends with this fixed reply.
GUARD_REPLY = "I couldn't finish that answer. Please ask again."

# Prompt P6 round cap (2026-11-01). The loop had no limit on model calls per turn -- its guard is "no text and no tool call".
# MAX_TOOL_ROUNDS = max(12, 2 x the most model calls one turn made in the Langfuse traces of production + eval, 30 Oct -
# 1 Nov: 6; production's most was 4) = 12. When a turn has made MAX_TOOL_ROUNDS model calls and the latest response still
# asks for a tool, the turn ends with ROUND_CAP_REPLY: no further model call, the response's tool calls are not run (no call
# would read their results), the history ends on the reply, [round cap: ...] is logged, the usage row is written, the trace's
# metadata says round_cap=true, and there is no fact check -- as with the loop guard. The send-back after a final answer is
# not a round. Both engines (agent_graph routes call_model -> round_cap).
MAX_TOOL_ROUNDS = 12
ROUND_CAP_REPLY = "I couldn't finish that answer within the step limit. Please ask a narrower question."

# Prompt R1 (2026-11-14), brought over by R3: a reply that stops at the reply cap (stop_reason max_tokens) -- the final answer
# or the send-back's rewrite -- is trimmed to its last complete paragraph / list item / table row (trim_cut_reply) and ends with
# this line on its own; the history keeps exactly what the user was shown. The trace carries stop_reason / truncated.
CUT_OFF_LINE = '(I had to stop there. Reply "continue" for the rest.)'
_FENCE_RE = re.compile(r"(?m)^[ \t]*```")
_TABLE_SEP_RE = re.compile(r"^\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)*\|?\s*$")
_SENTENCE_END_RE = re.compile(r"[.!?](?:[*_)\"'\u2019\u201d]*)(?=\s|$)")

# Prompt R3 (2026-11-16): a tool round the model cannot have. (1) A response the reply cap stopped INSIDE a tool round (R1's
# eval: a fan-out of 32-45 single-player lookups, cut): none of its calls is run -- a cut call is never run -- and the turn does
# NOT end there (R1's rule ended it with the step-limit reply: a non-answer). (2) A response asking for more than
# MAX_PREDICTION_CALLS get_prediction calls (a ranking by hand): none is run. Either way ONE app note goes back in place of the
# results and the model continues; the round counts toward MAX_TOOL_ROUNDS like any other. The fan-out guard and the note's
# pointer to rank_players are a normal turn's; a draft chat has no rank_players, so its cut round gets the note without it.
CUT_ROUND_NOTE = "Your last request was cut off — ask for fewer players at once, or use rank_players"
CUT_ROUND_NOTE_DRAFT = "Your last request was cut off — ask for fewer players at once"
TOOL_NOT_RUN = "Not run."
# Prompt R3d (2026-11-16): R3c's case 6 answered an injured player's comparison from two player cards (one run with an estimate
# of its own); a second get_player_card in the same normal turn is not run and gets this note -- the comparison tool writes it.
SECOND_CARD_NOTE = "For two or more players, use compare_players — it writes the comparison."
# Prompt R3e (2026-11-16): R3d's case 6 run 3 answered "is Doku or Semenyo the better pick?" from ONE player card -- the
# guard above stops only a second. On a normal turn whose user message reads as a comparison and names two or more
# different players (comparison_guard.fires: the message's own names against the player list, or two players resolved in
# the turn), a single-player lookup is not run until compare_players has run, and gets this note; the round counts toward
# the round cap like any other. A draft chat's turn is never guarded.
COMPARISON_NOTE = "This compares named players: call compare_players with every player's id — it writes the comparison, flags included."
SINGLE_PLAYER_LOOKUPS = ("get_player_card", "get_prediction")
# Prompt F1 C (2026-11-18): the 17 Nov deploy smoke's item 7, "Is Ekitike or Havertz the better pick?" -- the guard read the
# comparison (both players resolved), but the model called compare_predictions, which it did not hold, and wrote the answer
# itself. On a comparison of named players compare_predictions is held too, unless the message is about the armband (captain_pick
# is its route, and compare_predictions sends it there).
COMPARISON_HELD = SINGLE_PLAYER_LOOKUPS + ("compare_predictions",)
_ARMBAND_RE = re.compile(r"\b(?:captain\w*|captaincy|armband|vice|skipper)\b")
# Prompt F1 B (2026-11-18): while the turn holds a name unsettled (model_tools.resolve_player: an ambiguous lookup of a name the
# user wrote), a call carrying one of its candidates' ids -- or an id no tool result has given -- is not run; its result names
# the candidates and says to ask (model_tools.unsettled_note). set_my_squad checks its incoming players itself.
PLAYER_ID_FIELDS = ("player_id", "player_ids", "player_id_a", "player_id_b", "lock_player_ids", "start_player_ids", "ban_player_ids")
UNSETTLED_EXEMPT = ("resolve_player", "set_my_squad", "captain_pick")
# Prompt F2 F (2026-11-18): F1's L8, laptop and production -- after the user's "Cole" the model's FIRST call was
# get_player_card(328), Pascal Struijk, before any lookup (R3g's run 2 guessed 448 the same way). Once the chat has used lookups
# (resolve_player has run in it), a call carrying a player id runs only when that id came back in an earlier tool result of
# the chat or is in the user's own fifteen; otherwise it is not run and gets this note. A chat with no lookup yet is left as
# before (the measured literal rule held 49 existing tests' scripted calls). captain_pick checks its players against the
# squad itself. Draft turns: never.
UNKNOWN_ID_NOTE = ("Not run: no tool in this chat has returned that player id. Look the player up with resolve_player first, "
                   "then use the id it returns.")
KNOWN_ID_FIELDS = PLAYER_ID_FIELDS + ("captain_id", "vice_id", "bench_order_ids")
# set_my_squad: its kept players are the active squad, which the tool reads -- the agent hands it the chat's ids instead and the
# tool refuses an INCOMING player no tool gave (model_tools._unknown_incoming)
UNKNOWN_ID_EXEMPT = ("resolve_player", "search_news", "captain_pick", "set_my_squad")
_KNOWN_ID_RE = re.compile(r"'(?:\w*_)?(?:player_id|element|id)(?:_\w+)?': (\d+)")
_KNOWN_IDS_RE = re.compile(r"'\w*(?:player_ids|elements|_ids)': \[([0-9, ]*)\]")
GUARD_NAMES_TTL_S = 300.0
_GUARD_NAMES = {"at": 0.0, "value": None}
MAX_PREDICTION_CALLS = 10
# Prompt R3b (2026-11-16): one response asking for more than MAX_FIXTURE_CLUBS clubs' fixtures one call at a time (R3's eval:
# twelve single-club calls for "who do my players face", then a 1,700-token table written by hand): none is run, ONE app note
# says to ask once -- the several-club request is answered by the code-built grid. A normal turn's guard, like the one above.
FIXTURE_FAN_OUT_NOTE = ("That is more than five clubs — ask for them in ONE get_fixtures call: no team for every club, "
                        "teams=[...] for a list of clubs, or my_players=true for the user's own players")
MAX_FIXTURE_CLUBS = 5


def _cut_off(response):
    """True when this response stopped at the reply cap."""
    return getattr(response, "stop_reason", None) == "max_tokens"


def trim_cut_reply(text):
    """The text of a reply stopped at the reply cap, trimmed to complete markdown (Prompt R1). Pure:
    - an unclosed code fence goes, with everything after it;
    - the last line -- the one being written when the cap hit -- goes (a cut exactly at a line end loses nothing);
    - then, from the end: blank lines, headings, a table header + separator with no row under them, a lead-in line ending
      in ":" whose content was lost, and a bare rule or bullet;
    - nothing complete left: the text up to its last complete sentence; no sentence either: "".
    """
    t = str(text or "")
    fences = [m.start() for m in _FENCE_RE.finditer(t)]
    if len(fences) % 2 == 1:
        t = t[:fences[-1]]
    lines = t.split("\n")
    if not t.endswith("\n"):
        lines = lines[:-1]
    while lines:
        s = lines[-1].strip()
        if not s or s.startswith("#") or s in ("---", "***", "___", "-", "*", "+", "|") or s.rstrip("*_ ").endswith(":"):
            lines.pop()
            continue
        if _TABLE_SEP_RE.match(s):
            lines.pop()
            if lines:
                lines.pop()
            continue
        break
    kept = "\n".join(lines).strip()
    if kept:
        return kept
    ends = list(_SENTENCE_END_RE.finditer(t))
    return t[:ends[-1].end()].strip() if ends else ""


# Prompt R3 (digest M2): the send-back's rewrite sometimes opens by answering the automatic check -- "Here is the corrected
# version with only those two fixes applied:" -- words for a reader who saw a first version; the user never did. A FIRST line
# of the rewrite that is not a line of the original answer, speaks of a correction and is a short lead-in is dropped by code
# (with a rule line right under it); everything else of the rewrite is delivered as written.
_REWRITE_LEAD_RE = re.compile(r"\b(correct(?:ed|ion|ions)?|fix(?:es|ed)?|revis(?:ed|ion)|updated?|amended|rewritten|rewrite)\b", re.I)


def drop_rewrite_lead_in(rewrite, original):
    """(the rewrite without a lead-in that answers the automatic check, whether one was dropped). Pure."""
    lines = str(rewrite or "").split("\n")
    first = lines[0].strip() if lines else ""
    was = {ln.strip() for ln in str(original or "").split("\n")}
    if (not first or first in was or len(first) > 200 or first.startswith(("#", "|", "-", "*", ">"))
            or not first.endswith((":", ".")) or not _REWRITE_LEAD_RE.search(first)):
        return rewrite, False
    rest = lines[1:]
    while rest and rest[0].strip() in ("", "---", "***", "___"):
        rest.pop(0)
    return ("\n".join(rest), True) if rest else (rewrite, False)


def _system_for_turn(now=None):
    """The system prompt for one turn: the "now" context block (the gameweek state, the run schedule,
    the 20 clubs -- now_context.py, from local data, computed at `now`) prepended to the reviewed prompt.
    Built once per user turn so every API call inside the turn reads the same facts. Since 2026-10-24 the
    block carries no "- Now:" line: that line rides on the turn's user message (_messages_for_request), so
    this text is byte-identical from one minute to the next and the cache serves it. If the block cannot
    be built at all the prompt goes alone: a turn must never die for want of a date line."""
    prompt = DRAFT_SYSTEM_PROMPT if _draft_turn_now() else SYSTEM_PROMPT    # R3: a draft turn keeps the prompt it had
    try:
        block = context_block(now)
    except Exception as e:                           # noqa: BLE001 -- the block is help, not a dependency
        _say(f"  [context block not built: {type(e).__name__}: {str(e)[:200]}]")
        return prompt
    return f"{block}\n\n{prompt}" if block else prompt


# Prompt caching (2026-10-19). Three breakpoints per request, in the order the API caches a prefix: the last tool
# definition (the schema never changes between calls), the whole system prompt (the context block and the reviewed
# prompt, one text block, built once per turn), and the last block of the messages (so every later call of a turn
# reads the earlier calls' prefix instead of paying for it again). The markers go on REQUEST-TIME COPIES only:
# tools_schema, the system string and the conversation history are left exactly as they were, so the history never
# accumulates markers (the API allows four) and every other reader of those objects sees the old shapes.
# Since 2026-10-24 the clock line ("- Now: ...") is not in the system prompt but the first text block of the turn's
# question message, also a request-time copy: measured on the server, the system block (~12.5k tokens) was written
# to the cache fresh on most turns because its second line changed every minute.
CACHE_CONTROL = {"type": "ephemeral"}


def _tools_for_request(tools):
    """The tool list with a breakpoint on its last definition."""
    return list(tools[:-1]) + [{**tools[-1], "cache_control": dict(CACHE_CONTROL)}]


def _system_for_request(system):
    """The system prompt as one text block carrying a breakpoint."""
    return [{"type": "text", "text": system, "cache_control": dict(CACHE_CONTROL)}]


def _messages_for_request(messages, now_text=None, question_index=None):
    """The messages as sent: the turn's question message (messages[question_index], the user's string) gains the clock
    line `now_text` as its FIRST text block, on every call of the turn (2026-10-24: the line left the system block so
    the system prompt caches; the question message carries it instead, and the stored history never does -- this is a
    request-time copy, like the markers); then a breakpoint goes on the last block of the last message. That message
    is always the user's (the question on the first call, the tool results afterwards); a string becomes the single
    text block it is to the API. Earlier messages are passed through as they are."""
    if not messages:
        return []
    out = list(messages)
    if now_text is not None and question_index is not None and 0 <= question_index < len(out):
        q = out[question_index]
        content = q["content"]
        blocks = [{"type": "text", "text": content}] if isinstance(content, str) else list(content)
        out[question_index] = {**q, "content": [{"type": "text", "text": now_text}] + blocks}
    last = out[-1]
    content = last["content"]
    if isinstance(content, str):
        marked = [{"type": "text", "text": content, "cache_control": dict(CACHE_CONTROL)}]
    else:
        marked = list(content)
        if marked and isinstance(marked[-1], dict):
            marked[-1] = {**marked[-1], "cache_control": dict(CACHE_CONTROL)}
    return list(out[:-1]) + [{**last, "content": marked}]


def system_text(system):
    """The text of a system prompt as sent: the string itself, or the concatenated text of its blocks."""
    if isinstance(system, str):
        return system
    return "".join(b.get("text", "") for b in system)


def call_tool(tool_name, tool_input):
    """One tool call under the failure contract: an unknown tool or an
    exception inside a tool becomes an {"error": ...} result naming the tool
    and the condition, so the model reports it (system prompt section 8)
    instead of the chat request dying with a 500. Tools' own {"error": ...}
    dicts pass through untouched."""
    fn = available_functions.get(tool_name)
    if fn is None and _draft_turn_now():                    # Prompt W11g G1: the draft tool exists on draft turns only
        fn = DRAFT_FUNCTIONS.get(tool_name)
    if fn is None:
        return {"error": f"tool {tool_name} is not available"}
    acting = config_roles.acting_user_id()               # Prompt P7: a signed-in user's turn (clerk mode only)
    if acting is not None and isinstance(tool_input, dict) and "user_id" in tool_input and tool_input["user_id"] != acting:
        _say(f"  [{tool_name}: user_id {tool_input['user_id']!r} from the model replaced by the signed-in user]")
        tool_input = {**tool_input, "user_id": acting}  # the user is the token's, never the model's
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
    """The agent-facing search (news_search.py): the server sets as_of = now; no other parameter is exposed. Prompt F2 E: for a
    requested player FPL flags, the result also carries his availability line -- FPL's words and day, and the first result's own
    sentence about him with its date (availability_lines)."""
    out = _search_news(query, players or [], clubs or [])
    return _with_availability_lines(out, players or [])


AVAILABILITY_LINES_NOTE = ("the source's own words and dates for each flagged player: quote them; a reported duration is not a "
                           "return date")


def _with_availability_lines(out, players):
    """Prompt F2 E: search_news' result with availability_lines {requested name: line} for the requested players FPL flags (a
    normal turn only; a name several players share, or one that cannot be read, gets none)."""
    if not isinstance(out, dict) or not players or _draft_turn_now():
        return out
    try:
        import comparison_guard
        import player_names as pn
        forms = _guard_names()
        results = [r for r in (out.get("results") or []) if isinstance(r, dict)]
        lines = {}
        for name in players:
            spans = comparison_guard._spans_words(str(name), forms)
            ids = {i for _w, s in spans for i in s} if len(spans) == 1 else set()
            if len(ids) != 1:
                continue
            element = next(iter(ids))
            f = _player_flags().get(element) or {}
            words = _name_words(f)
            about = [str(r.get("id")) for r in results if words & set(pn.norm(f"{r.get('headline')} {r.get('text')}").split())]
            line = availability_line_for(element, results, prefer=about)
            if line:
                lines[str(name)] = line
        if lines:
            out = {**out, "availability_lines": lines, "availability_lines_note": AVAILABILITY_LINES_NOTE}
    except Exception as e:                              # noqa: BLE001 -- the supply never takes the search down
        _say(f"  [availability lines not added: {type(e).__name__}: {str(e)[:200]}]")
    return out


def _citation_check(turn_id, text, returned_ids):
    """Part 5 (log only, 2026-09-30): every c<id> the reply cites must be an id search_news returned in
    THIS turn. Logged to citation_checks; the reply is never altered; a logging failure is printed."""
    cited = cited_ids(text)
    violations = citation_violations(cited, returned_ids)
    try:
        record_citation_check(turn_id, cited, returned_ids, violations)
    except Exception as e:  # noqa: BLE001 -- the check must never take the reply down
        _say(f"  [citation check not logged: {type(e).__name__}: {str(e)[:200]}]")
    if violations:
        _say(f"  [citation check: {len(violations)} cited id(s) not returned this turn: {violations}]")


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
        _say(f"  [numeric check not logged: {type(e).__name__}: {str(e)[:200]}]")
    if error:
        _say(f"  [numeric check failed: {error}]")
    elif result and result["ungrounded"]:
        _say(f"  [numeric check: {len(result['ungrounded'])} of {result['numbers_found']} numbers ungrounded: "
              f"{[u['text'] for u in result['ungrounded']]}]")


def _fact_check_log(turn_id, info):
    """M1: one fact_checks row per checked reply (fact_check.record). A logging failure is printed; the reply never
    depends on it."""
    try:
        fact_check.record(turn_id, info)
    except Exception as e:  # noqa: BLE001 -- the log must never take the reply down
        _say(f"  [fact check not logged: {type(e).__name__}: {str(e)[:200]}]")


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
        cost = (_price_usd(model, toks["input"], toks["output"], cache_read=toks["cache_read"], cache_write=toks["cache_write"])
                if seen else None)                                               # the cache rates since 2026-10-19
        acting = config_roles.acting_user_id()           # Prompt P7: a signed-in user's turn -> the cap's ledger
        record_chat_usage(turn_id, model, usage["calls"], toks["input"], toks["output"],
                          toks["cache_read"], toks["cache_write"], cost, tool_names_replaced,
                          **({} if acting is None else {"user_id": acting}))
    except Exception as e:  # noqa: BLE001 -- the log must never take the reply down
        _say(f"  [usage not logged: {type(e).__name__}: {str(e)[:200]}]")


available_functions = {
    "rank_players": rank_players,
    "review_my_squad": review_my_squad,
    "captain_pick": captain_pick,
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
DRAFT_FUNCTIONS = {"explain_my_draft": explain_my_draft}       # Prompt W11g G1: callable on a draft chat's turn only

def run_agent(user_message: str, messages: list = None, *, thread=None):
    """One turn: the user's message in, the rendered reply and the updated history out. The turn is open on
    turn_context for its whole duration (Prompt E, 2026-10-27: the squad-write lock reads which turn a tool runs
    in) and closed on every exit, a raised exception included. `thread` (Prompt B, 2026-10-31): {"thread_id",
    "user_id", "max_turns"} when the turn belongs to a stored thread (agent_graph.run_thread_turn, i.e. /chat); None
    for a caller's own list (the eval runner, the tests), exactly as before. Prompt X1 (2026-11-13): a message that
    answers the thread's open squad-change preview (yes / no / unclear) is answered by code first (confirm_gate), with no
    model call; otherwise nothing changes."""
    try:
        import confirm_gate
        scripted = confirm_gate.answer_turn(user_message, messages, thread)
        if scripted is not None:
            return scripted
        return _run_turn(user_message, messages, thread=thread)
    finally:
        tracing.close_open()                         # Prompt L: a turn that raised closes its trace at ERROR level
        turn_context.end()


# ---- the turn's steps (Prompt A, 2026-10-31) ----------------------------------------------------------------------------
# _run_turn's steps as named functions over ONE dict, the turn's state: the variables the loop has always used
# (messages, question_index, turn_id, trace, now, system, now_text, returned_ids, returned_results, usage, turn_calls; the
# latest response and tool_results; the fact check's raw / info / res / fc_span / delivered / sb / t0 / text2 / reply; the
# rendered reply). The loop below calls them in the order it always ran them. Each step mutates the turn's lists and dicts
# in place, exactly as the loop always did, and returns the keys it set (the caller merges them).

def _begin_turn(user_message, messages=None, engine="loop", thread=None):
    """The turn's state, set up as _run_turn always did: the question appended, the turn opened on turn_context and in
    tracing (its metadata naming the engine), ONE clock instant, the system prompt and the clock line built. A stored
    thread's turn (Prompt B) also carries its thread id (on the turn channel -- the preview tickets are bound to it --
    and as the trace's session), its user, and the request trim (max_turns)."""
    thread = thread or {}
    if messages is None:
        messages = []

    messages.append({"role": "user", "content": user_message})
    question_index = len(messages) - 1               # the turn's question: the clock line rides on it at send time
    turn_id = thread.get("turn_id") or uuid.uuid4().hex   # Piece 7: one id per reply, for citation_checks (W7b: a stored
                                                     # thread's turn brings the id its pending chat_messages row was written under)
    view, view_q = trim_turns(messages, question_index, thread.get("max_turns"))   # Prompt F1: the questions the request carries
    earlier = [m["content"] for m in view[:view_q] if m.get("role") == "user" and isinstance(m.get("content"), str)]
    turn_context.begin(turn_id, thread_id=thread.get("thread_id"),    # Prompt E: the loop's channel; tools read it, the model cannot set it
                       draft=thread.get("draft"),                      # Prompt W11: the draft chat's turn (None otherwise)
                       user_message=user_message,                      # Prompt R3d: code checks the model's reading of these words
                       earlier_messages=earlier)                       # Prompt F1: and the user's words earlier in the chat
    trace = tracing.start_turn(turn_id, user_message, engine=engine,  # Prompt L: one Langfuse trace per turn (no-op when off)
                               session_id=thread.get("thread_id"), user_id=thread.get("user_id"))
    now = now_context.clock()                        # ONE instant per turn: the block's lines and the Now line agree
    system = _system_for_turn(now)                   # the "now" block, rebuilt once per turn (2026-10-08), clock line apart
    now_text = now_line(now)                         # "- Now: <weekday> <date> <HH:MM> UTC." -> the user message (2026-10-24)
    countdown = now_context.countdown_line(now)      # "Next deadline: GW9, Sat 31 Oct 2026 11:00 UTC — in 5 d 20 h 30 m" (2026-10-26)
    if countdown:
        now_text = f"{now_text}\n{countdown}"        # computed by code, beside the Now line, never in the block or the history
    if thread.get("draft") is not None:              # Prompt W11: a draft chat's turn -- the reviewed draft wording, request-time only
        now_text = f"{now_text}\n{DRAFT_MODE_TEXT}"
    return {"messages": messages, "question_index": question_index, "turn_id": turn_id, "trace": trace, "now": now,
            "system": system, "now_text": now_text,
            "returned_ids": [],                      # every result id search_news returned in THIS turn
            "returned_results": [],                  # the result dicts themselves, for the rendered citations (Part C)
            "usage": {"calls": 0, "input": 0, "output": 0, "cache_read": 0, "cache_write": 0,
                      "model": None, "seen_usage": False},   # Part 7c: this turn's API usage, logged with the reply
            "turn_calls": [],                        # M1: (tool, input, result) of THIS turn, what the fact check reads
            "rounds": 0,                             # Prompt P6: the tool loop's model calls so far (the round cap)
            "response": None, "tool_results": None, "direct_text": None,
            "raw": None, "info": None, "res": None, "fc_span": None, "delivered": None, "sb": None, "t0": None,
            "text2": None, "reply": None, "rendered": None,
            "cut": None, "rewrite_cut": None,       # Prompt R1: {"note": bool} when the delivered text was cut at the reply cap
            "skipped_rounds": [],                    # Prompt R3: tool rounds answered with the app note instead of being run
            "thread_id": thread.get("thread_id"), "max_turns": thread.get("max_turns")}


def trim_turns(messages, question_index, max_turns):
    """(the messages a request carries, the question's index in them): a stored thread's last `max_turns` turns
    (Prompt B; USER DECISION: keep the last 10 turns per thread). A turn starts at a user message whose content is a
    string -- the question; tool results are lists -- so a cut there never separates a tool_use from its tool_result.
    No trim (max_turns None, or a thread of max_turns turns or fewer): the list itself and the same index."""
    if not max_turns:
        return messages, question_index
    starts = [i for i, m in enumerate(messages) if m.get("role") == "user" and isinstance(m.get("content"), str)]
    if len(starts) <= max_turns:
        return messages, question_index
    cut = starts[-max_turns]
    return messages[cut:], question_index - cut


def _call_model(st):
    """One model call with the agent's parameters, unchanged: traced, tallied, the assistant's content appended."""
    request = {"model": AGENT_MODEL, "max_tokens": _max_tokens(),            # the agent's parameters (W11f V2: a draft turn 2,048)
               "system": _system_for_request(st["system"]),
               "tools": _tools_for_request(_turn_tools()),
               "messages": _messages_for_request(*_request_view(st, st["now_text"]))}
    trace = st["trace"]
    gen = trace.generation(request)
    response = llm.chat("agent", request, client=client)                      # conn=None: chat_usage is the ledger
    trace.generation_done(gen, response)
    _tally_usage(st["usage"], response)

    st["messages"].append({"role": "assistant", "content": response.content})
    return {"response": response, "rounds": st["rounds"] + 1}


def _request_view(st, now_text, note=None):
    """_messages_for_request's arguments: the turn's messages (a stored thread's last max_turns turns), the send-back's
    note after them when there is one, the clock line, the question's index."""
    messages, qi = trim_turns(st["messages"], st["question_index"], st.get("max_turns"))
    if note is not None:
        messages = messages + [{"role": "user", "content": note}]
    return messages, now_text, qi


def _final_text_block(st):
    """The reply's text block when the model stopped for anything but tool use and wrote text (the first text block),
    else None: the response's tool calls, if any, run next."""
    response = st["response"]
    if response.stop_reason != "tool_use":
        if _cut_off(response) and any(getattr(b, "type", None) == "tool_use" for b in response.content):
            return None                                 # Prompt R3: a cut tool round is not an answer -- the app note, then on
        for block in response.content:
            if block.type == "text":
                return block
    return None


def _skipped_round(st):
    """Prompt R3: why NONE of this response's tool calls is run -- "cut" (the reply cap stopped the response inside a tool
    round) or "fan_out" (more than MAX_PREDICTION_CALLS get_prediction calls in one response; a normal turn's guard) -- or
    None when they run."""
    response = st["response"]
    uses = [b for b in response.content if getattr(b, "type", None) == "tool_use"]
    if not uses:
        return None
    if _cut_off(response):
        return "cut"
    if not _draft_turn_now() and sum(1 for b in uses if getattr(b, "name", None) == "get_prediction") > MAX_PREDICTION_CALLS:
        return "fan_out"
    if not _draft_turn_now():                            # Prompt R3b: more than five clubs' fixtures, one call a club
        clubs = {str((getattr(b, "input", None) or {}).get("team")).strip().lower() for b in uses
                 if getattr(b, "name", None) == "get_fixtures" and isinstance(getattr(b, "input", None), dict) and b.input.get("team")}
        if len(clubs) > MAX_FIXTURE_CLUBS:
            return "fixtures_fan_out"
    return None


def _join_direct(texts):
    """One reply from the code-built texts of one response: a single text as it is; several joined in order, an earlier
    text's closing question dropped when the last text ends with the same one."""
    if len(texts) == 1:
        return texts[0]
    last = texts[-1].rstrip().split("\n")[-1]
    out = []
    for t in texts[:-1]:
        lines = t.rstrip().split("\n")
        if lines and lines[-1] == last:
            lines = lines[:-1]
        out.append("\n".join(lines).rstrip())
    return "\n\n".join(out + [texts[-1]])


def _guard_names():
    """{folded name form: frozenset(element ids)} for every current player (players_live and FPL's web names, as
    resolve_player reads them), for the comparison guard. Cached for five minutes, like resolve_player's web names."""
    if _GUARD_NAMES["value"] is not None and time.time() - _GUARD_NAMES["at"] < GUARD_NAMES_TTL_S:
        return _GUARD_NAMES["value"]
    import comparison_guard
    import model_tools
    rows = model_tools._q("SELECT element, name FROM players_live")
    web = model_tools._web_names()
    value = comparison_guard.name_forms([(r["element"], r["name"], web.get(r["element"], "")) for r in rows])
    _GUARD_NAMES.update(at=time.time(), value=value)
    return value


# ---- Prompt F2 E (2026-11-18): return dates -- supply the fact, then check the reply (availability_check.py) -----------------
AVAILABILITY_FLAGGED = ("d", "i", "s", "u", "n")         # = model_tools.FLAG_STATUSES: FPL reports an absence
_PLAYER_FLAGS = {"at": 0.0, "value": None}


def _player_flags():
    """{element: {name, web_name, status, chance, news, updated_at}} for every current player (players_live and FPL's web names),
    cached for five minutes like the guard's player list."""
    if _PLAYER_FLAGS["value"] is not None and time.time() - _PLAYER_FLAGS["at"] < GUARD_NAMES_TTL_S:
        return _PLAYER_FLAGS["value"]
    import model_tools
    rows = model_tools._q("SELECT element, name, status, chance, news, updated_at FROM players_live")
    web = model_tools._web_names()
    value = {int(r["element"]): {"name": r["name"], "web_name": web.get(r["element"], ""), "status": r.get("status"),
                                 "chance": r.get("chance"), "news": (r.get("news") or "").strip(), "updated_at": r.get("updated_at")}
             for r in rows}
    _PLAYER_FLAGS.update(at=time.time(), value=value)
    return value


def _name_words(flag):
    import player_names as pn
    return set(pn.norm(flag.get("name")).split()) | set(pn.norm(flag.get("web_name")).split())


def _report_for(flag, results, prefer=()):
    """A news report about the player the reply used: the first of `results` (search_news results of the turn) whose words name
    him -- one cited in `prefer` first -- with its own sentence about him and its date; None when there is none."""
    import availability_check as av
    words = _name_words(flag)
    by_id = {str(r.get("id")): r for r in results if isinstance(r, dict)}
    used = [by_id[str(rid)] for rid in prefer if str(rid) in by_id]
    used = [r for r in used if "fpl" not in str(r.get("source") or "").lower()]     # FPL's own words are the line's first half
    for allow_headline in (False, True):                 # a sentence about his absence first, a headline only after
        for r in used:
            said = av.report_sentence(r.get("text"), r.get("headline") if allow_headline else None, words)
            if said:
                return {"source": r.get("source"), "date_words": r.get("date_words") or r.get("date"), "words": said,
                        "id": r.get("id")}
    return None


def availability_line_for(element, results=(), prefer=()):
    """The code-built availability line of one player FPL flags (None for a player it does not): FPL's words and day, and the
    report the reply used (`prefer`: the result ids it cited), in that report's words and with its date."""
    import availability_check as av
    import datewords
    import model_tools
    f = _player_flags().get(int(element))
    if not f or f.get("status") not in AVAILABILITY_FLAGGED:
        return None
    return av.availability_line(f["name"], model_tools.STATUS_WORDS.get(f["status"], f["status"]), f.get("news"),
                                datewords.day_words(f.get("updated_at")), _report_for(f, list(results), prefer))


def _source_words(turn_calls, extra=()):
    """The source's own words in the turn's tool results: every FPL news text and every news headline and text."""
    out = list(extra)

    def walk(x):
        if isinstance(x, dict):
            for k, v in x.items():
                if k in ("news", "headline", "text", "availability_note") and isinstance(v, str):
                    out.append(v)
                else:
                    walk(v)
        elif isinstance(x, (list, tuple)):
            for v in x:
                walk(v)
    for _n, _i, r in turn_calls:
        walk(r)
    return out


def _availability_checked(st, raw):
    """Prompt F2 E: (the text to send, the replacements). A normal turn's model-written reply: a sentence about a player FPL
    flags that gives a return timing the turn's sources do not carry is replaced by his availability line (no model call). A
    check that fails leaves the reply as it is."""
    if _draft_turn_now() or not raw:
        return raw, []
    try:
        import availability_check as av
        import comparison_guard
        flags = _player_flags()
        absent = {e for e, f in flags.items() if f.get("status") in AVAILABILITY_FLAGGED}
        forms = _guard_names()
        seen = _known_player_ids(st)

        def names(sentence):
            out = set()
            for _w, ids in comparison_guard._spans_words(sentence, forms):
                if len(ids) == 1:
                    out |= set(ids)
                elif len(set(ids) & seen) == 1:
                    out |= set(ids) & seen
            return out
        named_absent = {e for e in names(raw) if e in absent}
        if not named_absent:                            # no flagged player named: nothing for a pronoun to point back to
            return raw, []
        results = list(st.get("returned_results") or [])
        cited = av.markers(raw)
        c = av.corpus(" ".join(str(r) for _n, _i, r in st["turn_calls"]),
                      _source_words(st["turn_calls"], [flags[e]["news"] for e in named_absent if flags[e].get("news")]))

        def lines(element, sentence):
            mine = av.markers(sentence)
            return availability_line_for(element, results, prefer=list(mine) + [x for x in cited if x not in mine])
        return av.check(raw, names, absent, c, lines)
    except Exception as e:                              # noqa: BLE001 -- the check never takes the reply down
        _say(f"  [availability check skipped: {type(e).__name__}: {str(e)[:200]}]")
        return raw, []


def _comparison_turn(st):
    """Prompt R3e: (a) the turn's own user message reads as a comparison, (b) it names two or more different players --
    the message's own names, or two players resolved in the turn -- and (c) compare_players has not run in this turn. The
    player list is read only when (a) holds and fewer than two players are resolved; if it cannot be read, (b) rests on the
    resolved players alone -- the turn never fails on the guard."""
    import comparison_guard
    if any(n == "compare_players" for n, _i, _r in st["turn_calls"]):
        return False
    message = turn_context.user_message()
    if not comparison_guard.reads_as_comparison(message):
        return False
    resolved = comparison_guard.resolved_players(st["turn_calls"])
    if len(resolved) >= 2:
        return True
    try:
        forms = _guard_names()
    except Exception:                                   # noqa: BLE001
        forms = {}
    return comparison_guard.fires(message, forms, resolved=resolved)


def _armband_turn():
    """Prompt F1 C: the turn's own user message is about the captain's armband."""
    import player_names as pn
    return bool(_ARMBAND_RE.search(pn.norm(turn_context.user_message() or "")))


def _input_player_ids(tool_input, fields=PLAYER_ID_FIELDS):
    ids = set()
    for k in fields:
        v = tool_input.get(k)
        for x in (v if isinstance(v, (list, tuple)) else [v]):
            if (isinstance(x, int) and not isinstance(x, bool)) or (isinstance(x, str) and x.strip().isdigit()):
                ids.add(int(x))
    return ids


def _known_player_ids(st):
    """Every player id a tool result has given: this turn's results and the tool results the chat's history carries."""
    texts = [str(r) for _n, _i, r in st["turn_calls"]]
    for m in st["messages"]:
        if m.get("role") == "user" and isinstance(m.get("content"), list):
            texts += [b["content"] for b in m["content"]
                      if isinstance(b, dict) and b.get("type") == "tool_result" and isinstance(b.get("content"), str)]
    ids = set()
    for t in texts:
        ids |= {int(x) for x in _KNOWN_ID_RE.findall(t)}
        for group in _KNOWN_IDS_RE.findall(t):
            ids |= {int(x) for x in group.replace(" ", "").split(",") if x}
    return ids


def _chat_used_lookups(st):
    """Prompt F2 F: resolve_player has run in this chat -- this turn, or an earlier one the history carries."""
    if any(n == "resolve_player" for n, _i, _r in st["turn_calls"]):
        return True
    for m in st["messages"]:
        if m.get("role") == "assistant" and isinstance(m.get("content"), list):
            for b in m["content"]:
                kind = b.get("type") if isinstance(b, dict) else getattr(b, "type", None)
                name = b.get("name") if isinstance(b, dict) else getattr(b, "name", None)
                if kind == "tool_use" and name == "resolve_player":
                    return True
    return False


def _unknown_ids(st, tool_name, tool_input):
    """Prompt F2 F: the player ids of this call that no tool result in this chat has given and that are not in the user's own
    fifteen (the squad context code reads) -- once the chat has used lookups. Empty: the call runs. set_my_squad with no
    readable squad is left to the tool (it refuses without one)."""
    if tool_name in UNKNOWN_ID_EXEMPT or not isinstance(tool_input, dict):
        return set()
    ids = _input_player_ids(tool_input, KNOWN_ID_FIELDS)
    if not ids or not _chat_used_lookups(st):
        return set()
    unknown = ids - _known_player_ids(st)
    if unknown:
        import model_tools
        squad = model_tools.squad_ids_for_guard()
        if squad is None:
            return set() if tool_name == "set_my_squad" else unknown
        unknown -= squad
    return unknown


def _unsettled_call(st, tool_name, tool_input):
    """Prompt F1 B: the unsettled name this call is held for, or None. Normal turns only (the caller checks). resolve_player
    is checked inside the lookup; set_my_squad checks its incoming players itself; captain_pick takes only players of the user's
    own fifteen (it refuses any other), so the squad says which one is meant."""
    held = turn_context.unsettled()
    if not held or not isinstance(tool_input, dict) or tool_name in UNSETTLED_EXEMPT:
        return None
    if tool_name == "search_news":
        import model_tools
        import player_names as pn
        words = model_tools._users_words() or set()
        for text in list(tool_input.get("players") or []) + [tool_input.get("query") or ""]:
            toks = pn.norm(text).split()
            new = {t for t in toks if t not in words}
            for entry in held.values():
                if new & entry["name_words"] or (set(toks) & entry["own_words"] and new & entry["team_words"]):
                    return entry
        return None
    ids = _input_player_ids(tool_input)
    if not ids:
        return None
    for entry in held.values():
        if ids & entry["ids"]:
            return entry
    if ids - _known_player_ids(st):                      # an id no tool has given, while a name is unsettled: a guess
        return next(iter(held.values()))
    return None


def _run_tools(st):
    """Every tool_use block of the response, in order, under the failure contract; traced; kept for the fact check;
    search results kept for the citations. Returns the tool_result blocks (empty: no tool call in this response)."""
    trace = st["trace"]
    tool_results = []
    direct = None
    skip = _skipped_round(st)
    if skip:                                            # Prompt R3: run none of it; ONE app note; the model continues
        note = CUT_ROUND_NOTE_DRAFT if _draft_turn_now() else (FIXTURE_FAN_OUT_NOTE if skip == "fixtures_fan_out" else CUT_ROUND_NOTE)
        names = []
        for block in st["response"].content:
            if block.type == "tool_use":
                names.append(str(getattr(block, "name", "?")))
                tool_results.append({"type": "tool_result", "tool_use_id": block.id,
                                     "content": note if len(tool_results) == 0 else TOOL_NOT_RUN})
        _say(f"  [tool round not run ({skip}): {len(names)} call(s) answered with the app note; turn {st['turn_id']} continues]")
        st["skipped_rounds"].append({"why": skip, "calls": len(names), "tools": sorted(set(names))})
        return {"tool_results": tool_results, "direct_text": None}
    directs = []
    for block in st["response"].content:
        if block.type == "tool_use":
            tool_name = block.name
            tool_input = block.input
            tool_id = block.id
            held = None if _draft_turn_now() else _unsettled_call(st, tool_name, tool_input)
            if held is not None:
                # Prompt F1 B: the user has not said which player the name means; the call is not run, the note says ask
                import model_tools
                _say(f"  [{tool_name} not run: {tool_input}; {held['name']!r} is unsettled -- the app note says to ask the user]")
                tool_results.append({"type": "tool_result", "tool_use_id": tool_id, "content": model_tools.unsettled_note(held)})
                st["skipped_rounds"].append({"why": "unsettled", "calls": 1, "tools": [tool_name]})
                continue
            if (tool_name in COMPARISON_HELD and not _draft_turn_now()
                    and not (tool_name == "compare_predictions" and _armband_turn()) and _comparison_turn(st)):
                # Prompt R3e: a comparison of named players is compare_players'; its single-player lookups are not run
                _say(f"  [{tool_name} not run: {tool_input}; the turn compares named players -- the app note points at compare_players]")
                tool_results.append({"type": "tool_result", "tool_use_id": tool_id, "content": COMPARISON_NOTE})
                st["skipped_rounds"].append({"why": "comparison", "calls": 1, "tools": [tool_name]})
                continue
            if (tool_name == "get_player_card" and not _draft_turn_now()
                    and any(n == "get_player_card" for n, _i, _r in st["turn_calls"])):
                # Prompt R3d: one player card a turn; a second is not run and gets ONE app note (normal turns only)
                _say(f"  [second player card not run: {tool_input}; the app note points at the comparison tool]")
                tool_results.append({"type": "tool_result", "tool_use_id": tool_id, "content": SECOND_CARD_NOTE})
                st["skipped_rounds"].append({"why": "second_card", "calls": 1, "tools": ["get_player_card"]})
                continue

            unknown = set() if _draft_turn_now() else _unknown_ids(st, tool_name, tool_input)
            if unknown:
                # Prompt F2 F: an id no tool has given in this chat is a guess (F1 L8: get_player_card(328) after "Cole")
                _say(f"  [{tool_name} not run: {tool_input}; id(s) {sorted(unknown)} came from no tool -- the app note says look up first]")
                tool_results.append({"type": "tool_result", "tool_use_id": tool_id, "content": UNKNOWN_ID_NOTE})
                st["skipped_rounds"].append({"why": "unknown_id", "calls": 1, "tools": [tool_name]})
                continue
            _say(f"  [calling tool: {tool_name}({tool_input})]")

            span = trace.tool(tool_name, tool_input)
            if tool_name == "set_my_squad" and not _draft_turn_now():      # Prompt F2 F: the chat's ids, for its incoming players
                turn_context.set_known_ids(_known_player_ids(st) if _chat_used_lookups(st) else None)
            try:
                result = call_tool(tool_name, tool_input)
            finally:
                turn_context.set_known_ids(None)
            trace.tool_done(span, tool_name, result)
            st["turn_calls"].append((tool_name, tool_input, result))
            if tool_name == "search_news" and isinstance(result, dict):
                hits = [r for r in (result.get("results") or []) if isinstance(r, dict) and r.get("id")]
                st["returned_ids"].extend(str(r.get("id")) for r in hits)
                st["returned_results"].extend(hits)
            if isinstance(result, dict) and "error" in result:
                _say(f"  [tool error: {tool_name}: {str(result['error'])[:200]}]")
            if tool_name in DIRECT_TOOLS and isinstance(result, dict) and isinstance(result.get("direct_reply"), str):
                direct = result["direct_reply"]                         # W11g G1: this text IS the reply
                directs.append(direct)

            tool_results.append({
                "type": "tool_result",
                "tool_use_id": tool_id,
                "content": str(result)
            })
    if len(directs) > 1 and not _draft_turn_now():      # Prompt R3: several code-built answers in one response -> all of them
        direct = _join_direct(directs)
    return {"tool_results": tool_results, "direct_text": direct}


def _direct(st):
    """Prompt W11g G1: a DIRECT_TOOLS result ends the turn with its code-built text as the reply -- no further model call
    and no fact check (the model wrote none of it). The text is stored as the assistant's message after the tool results,
    so the next turn's history is valid; the logs (citations, numbers, usage) and the trace run as for any reply."""
    text, turn_id, usage = st["direct_text"], st["turn_id"], st["usage"]
    st["messages"].append({"role": "assistant", "content": [{"type": "text", "text": text}]})
    _citation_check(turn_id, text, st["returned_ids"])
    _numeric_check(turn_id, text, st["messages"])
    LAST_FACT_CHECK.clear()
    LAST_FACT_CHECK.update(outcome="direct", facts_checked=0, mismatches=[], sent_back=False, original=text, delivered=text)
    stop = str(getattr(st.get("response"), "stop_reason", None))
    LAST_TURN.clear()
    LAST_TURN.update(turn_id=turn_id, tool_names_replaced=0, plain_words_replaced=0, direct=True, stop_reason=stop,
                     truncated=False, skipped_rounds=list(st.get("skipped_rounds") or []), **usage)
    _usage_log(turn_id, usage, 0)
    st["trace"].end(text, stop_reason=stop, truncated=False)
    _note_turn(st, text)
    return {"rendered": text}


def _round_capped(st):
    """Prompt P6: True when the turn has made MAX_TOOL_ROUNDS model calls and the latest response asks for a tool."""
    return st["rounds"] >= MAX_TOOL_ROUNDS and any(getattr(b, "type", None) == "tool_use" for b in st["response"].content)


def _round_cap(st):
    """Prompt P6 round cap: the turn ends with the fixed reply in place of the response that asked for more tools (never
    an unanswered tool call in the history); its tool calls are not run; usage row, trace metadata, no fact check."""
    response, turn_id, usage = st["response"], st["turn_id"], st["usage"]
    pending = [str(getattr(b, "name", "?")) for b in response.content if getattr(b, "type", None) == "tool_use"]
    _say(f"  [round cap: {st['rounds']} model calls (MAX_TOOL_ROUNDS {MAX_TOOL_ROUNDS}); turn {turn_id} ends with the "
          f"fixed reply; tool calls not run: {pending}]")
    st["messages"][-1] = {"role": "assistant", "content": [{"type": "text", "text": ROUND_CAP_REPLY}]}
    cap = {"rounds": st["rounds"], "pending_tools": pending}
    stop = str(getattr(response, "stop_reason", None))
    LAST_TURN.clear()
    LAST_TURN.update(turn_id=turn_id, tool_names_replaced=0, plain_words_replaced=0, round_cap=cap, stop_reason=stop,
                     truncated=_cut_off(response), skipped_rounds=list(st.get("skipped_rounds") or []), **usage)
    _usage_log(turn_id, usage, 0)
    st["trace"].end(ROUND_CAP_REPLY, round_cap=cap, stop_reason=stop, truncated=_cut_off(response))
    _note_turn(st)
    return {"rendered": ROUND_CAP_REPLY}


def _guard_text_block(st):
    """Prompt E loop guard, no tool call in this response: its text block, if any, is the reply (stop_reason tool_use
    without a call). None -> the fixed guard reply."""
    return next((b for b in st["response"].content if getattr(b, "type", None) == "text"), None)


def _append_tool_results(st):
    """The response's tool results go back as ONE user message."""
    st["messages"].append({"role": "user", "content": st["tool_results"]})
    return {}


def _loop_guard(st):
    """Prompt E loop guard: no text and no tool_use in the response -> the turn ends with the fixed reply (never an empty
    message in the history)."""
    response, turn_id, usage = st["response"], st["turn_id"], st["usage"]
    block_types = [str(getattr(b, "type", "?")) for b in (response.content or [])]
    _say(f"  [loop guard: no text and no tool_use (stop_reason={response.stop_reason}); turn {turn_id} "
          f"ends with the fixed reply; blocks {block_types}]")
    st["messages"][-1] = {"role": "assistant", "content": [{"type": "text", "text": GUARD_REPLY}]}   # never an empty message
    LAST_TURN.clear()
    LAST_TURN.update(turn_id=turn_id, tool_names_replaced=0, plain_words_replaced=0,
                     guard={"stop_reason": response.stop_reason, "block_types": block_types}, **usage)
    _usage_log(turn_id, usage, 0)
    st["trace"].end(GUARD_REPLY, guard={"stop_reason": response.stop_reason, "block_types": block_types})
    _note_turn(st)
    return {"rendered": GUARD_REPLY}


# M1 (Prompt H, 2026-10-30; USER DECISION H1): the final answer against this turn's tool rows. On a mismatch, ONE
# send-back: the code-built note as an automatic-check message after the answer, the same model, system and tools (the
# cache holds) with tool use off; the rewrite is checked again and delivered either way (flagged when still wrong); a tool
# call in the rewrite, an empty rewrite or a failed call delivers the original. Never a second send-back. The stored
# history keeps only the delivered answer, never the note. Logged to fact_checks. Steps: _fact_check_start ->
# [_send_back -> [_recheck] -> _send_back_done] -> _fact_check_end.

def _fact_check_start(st, raw):
    """The first check of `raw` against this turn's tool rows (a crash in the check never takes the reply down).
    Prompt R1: a reply stopped at the reply cap is trimmed first (trim_cut_reply; nothing complete left -> the round-cap
    reply) and the history's last message becomes that text alone."""
    cut = None
    if _cut_off(st["response"]):
        kept = trim_cut_reply(raw)
        cut = {"note": bool(kept)}
        raw = kept or ROUND_CAP_REPLY
        st["messages"][-1] = {"role": "assistant", "content": [{"type": "text", "text": raw}]}
        _say(f"  [cut off: the reply stopped at the reply cap ({_max_tokens()} tokens); trimmed to {len(raw)} characters]")
    info = {"facts_checked": 0, "mismatches": [], "sent_back": False, "outcome": "clean", "note": None,
            "rewrite_mismatches": None, "extra_usd": None, "extra_seconds": None, "error": None}
    delivered = raw
    fc_span = st["trace"].fact_check()                               # Prompt L: the check's span (+ its score below)
    try:
        res = fact_check.check(raw, st["turn_calls"])
        info.update(facts_checked=res["facts_checked"], mismatches=res["mismatches"])
    except Exception as e:  # noqa: BLE001 -- the check must never take the reply down
        res = None
        info.update(outcome="check_error", error=f"{type(e).__name__}: {str(e)[:200]}")
    return {"raw": raw, "info": info, "res": res, "fc_span": fc_span, "delivered": delivered, "cut": cut}


def _needs_send_back(st):
    """True when the first check found mismatches."""
    res = st["res"]
    return bool(res and res["mismatches"])


def _send_back(st):
    """The one send-back. Sets text2 / reply when the rewrite is text to re-check; otherwise the outcome is final here
    (tool_call_in_rewrite, no_text, sendback_failed). The eval runner's budget stop is re-raised."""
    info, res, trace = st["info"], st["res"], st["trace"]
    note = fact_check.note(res["mismatches"])
    info.update(sent_back=True, note=note)
    sb = {"calls": 0, "input": 0, "output": 0, "cache_read": 0, "cache_write": 0, "model": None, "seen_usage": False}
    t0 = time.time()
    text2, reply = None, None
    rewrite_cut, rewrite_edited = False, False
    try:
        request = {"model": AGENT_MODEL, "max_tokens": _max_tokens(),
                   "system": _system_for_request(st["system"]),
                   "tools": _tools_for_request(_turn_tools()),
                   "tool_choice": dict(FACT_CHECK_TOOL_CHOICE),
                   "messages": _messages_for_request(*_request_view(st, st["now_text"], note))}
        gen = trace.generation(request, send_back=True, parent=st["fc_span"])
        reply = llm.chat("agent", request, client=client)
        trace.generation_done(gen, reply)
        _tally_usage(sb, reply)
        _tally_usage(st["usage"], reply)
        blocks = list(getattr(reply, "content", None) or [])
        text2 = next((b.text for b in blocks if getattr(b, "type", None) == "text" and getattr(b, "text", "")), None)
        if text2 and _cut_off(reply):                               # Prompt R1: the rewrite stopped at the reply cap
            text2 = trim_cut_reply(text2) or None
            rewrite_cut = rewrite_edited = True
        if text2:                                                   # Prompt R3 (M2): a lead-in that answers the check goes
            text2, dropped = drop_rewrite_lead_in(text2, st["raw"])
            rewrite_edited = rewrite_edited or dropped
        if any(getattr(b, "type", None) == "tool_use" for b in blocks):
            info["outcome"] = "tool_call_in_rewrite"
            text2 = None
        elif not text2:
            info["outcome"] = "no_text"
            text2 = None
    except Exception as e:  # noqa: BLE001 -- a failed send-back delivers the original
        if type(e).__name__ == "BudgetExceeded":
            raise                                        # the eval runner's cap must reach the runner
        info.update(outcome="sendback_failed", error=f"{type(e).__name__}: {str(e)[:200]}")
        text2 = None
    return {"sb": sb, "t0": t0, "text2": text2, "reply": reply, "rewrite_cut": rewrite_cut, "rewrite_edited": rewrite_edited}


def _has_rewrite(st):
    """True when the send-back returned text to re-check."""
    return st["text2"] is not None


def _recheck(st):
    """The rewrite checked again and delivered either way (still_wrong / fixed); it replaces the answer in the history."""
    info, text2, reply = st["info"], st["text2"], st["reply"]
    delivered = st["delivered"]
    try:
        res2 = fact_check.check(text2, st["turn_calls"])
        info.update(rewrite_mismatches=res2["mismatches"], outcome="still_wrong" if res2["mismatches"] else "fixed")
        delivered = text2
        if st.get("rewrite_edited"):                                # R1 / R3: the trimmed or lead-in-free rewrite, as delivered
            st["messages"][-1] = {"role": "assistant", "content": [{"type": "text", "text": text2}]}
        else:
            st["messages"][-1] = {"role": "assistant", "content": reply.content}
        cut = {"note": True} if st.get("rewrite_cut") else None
    except Exception as e:  # noqa: BLE001 -- a failed send-back delivers the original
        if type(e).__name__ == "BudgetExceeded":
            raise
        info.update(outcome="sendback_failed", error=f"{type(e).__name__}: {str(e)[:200]}")
        return {"delivered": delivered}
    return {"delivered": delivered, "cut": cut}


def _send_back_done(st):
    """The send-back's time (from its start to here, the re-check included) and cost, and its log line."""
    info, sb, res = st["info"], st["sb"], st["res"]
    info["extra_seconds"] = round(time.time() - st["t0"], 2)
    if sb["seen_usage"]:
        try:
            info["extra_usd"] = _price_usd(sb["model"] or AGENT_MODEL, sb["input"], sb["output"],
                                           cache_read=sb["cache_read"], cache_write=sb["cache_write"])
        except Exception:  # noqa: BLE001
            info["extra_usd"] = None
    _say(f"  [fact check: {len(res['mismatches'])} mismatch(es), sent back once -> {info['outcome']}]")
    return {}


def _fact_check_end(st):
    """The fact_checks row, the trace's check span + scores, LAST_FACT_CHECK for the eval runner."""
    info = st["info"]
    _fact_check_log(st["turn_id"], info)
    st["trace"].fact_check_done(st["fc_span"], info)
    LAST_FACT_CHECK.clear()
    LAST_FACT_CHECK.update(info, original=st["raw"], delivered=st["delivered"])
    return {}


def _fact_checked(st, raw):
    """The fact check of the final answer, its steps in order; returns the text to deliver."""
    st.update(_fact_check_start(st, raw))
    if _needs_send_back(st):
        st.update(_send_back(st))
        if _has_rewrite(st):
            st.update(_recheck(st))
        st.update(_send_back_done(st))
    st.update(_fact_check_end(st))
    return st["delivered"]


def _finish(st, raw):
    """The reply path: the checks (log only), the plain-words locks, the citations, the usage row. Prompt R1: a reply cut at
    the reply cap ends with CUT_OFF_LINE on its own line, and the history keeps exactly that text."""
    turn_id, usage = st["turn_id"], st["usage"]
    raw, swaps = _availability_checked(st, raw)                    # Prompt F2 E: a return timing its sources do not give
    if swaps:
        st["messages"][-1] = {"role": "assistant", "content": [{"type": "text", "text": raw}]}   # the history keeps what is sent
        _say(f"  [availability check: {len(swaps)} sentence(s) replaced by the code-built availability line: {swaps}]")
    cut = st.get("cut")
    shown = f"{raw.rstrip()}\n\n{CUT_OFF_LINE}" if cut and cut.get("note") else raw
    if cut:
        st["messages"][-1] = {"role": "assistant", "content": [{"type": "text", "text": shown}]}
    from_rewrite = st.get("text2") is not None and st.get("delivered") == st.get("text2")
    stop = str(getattr(st.get("reply") if from_rewrite else st.get("response"), "stop_reason", None))
    _citation_check(turn_id, raw, st["returned_ids"])
    seen = st["messages"]
    if (turn_context.current() or {}).get("draft") is not None:   # Prompt W11: the draft wording rides on the request (the
        seen = seen + [{"role": "user", "content": DRAFT_MODE_TEXT}]   # first text block); the check sees what the model saw
    _numeric_check(turn_id, raw, seen)                             # log only; never alters the reply
    plain, n_names = replace_tool_names(shown)                     # Part 4b lock: tool names -> plain phrases
    plain, n_words = plain_words(plain)                            # batch 3 F6: status letters, horizon, xPts
    rendered = render_citations(plain, st["returned_results"])     # Part C: [1], [2] + Sources
    if rendered != raw:
        _say(f"  [raw reply: {raw}]")                             # the raw reply stays in the logs
    LAST_TURN.clear()
    LAST_TURN.update(turn_id=turn_id, tool_names_replaced=n_names, plain_words_replaced=n_words, stop_reason=stop,
                     truncated=bool(cut), skipped_rounds=list(st.get("skipped_rounds") or []),
                     availability_replacements=swaps, **usage)
    _usage_log(turn_id, usage, n_names)
    st["trace"].end(rendered, stop_reason=stop, truncated=bool(cut), **({"availability_replacements": swaps} if swaps else {}))
    _note_turn(st, raw)                                            # Prompt W4: the Chat page's structured fields
    return {"rendered": rendered}


def _note_turn(st, raw=None):
    """Prompt W4 (2026-11-06): the turn's record for the Chat page -- message_id (= the turn id) and, for a delivered reply,
    sources / squad_preview / squad_applied derived from the tool calls (turn_extras; never the model, never the network).
    Noted on the turn channel after the trace has ended: nothing here touches the request or the reply."""
    import turn_extras
    try:
        extras = turn_extras.record_for({**st, "raw": raw}) if raw is not None else {}
        turn_context.note(message_id=st["turn_id"], **extras)
    except Exception as e:  # noqa: BLE001 -- the reply never depends on this
        _say(f"  [turn record not noted: {type(e).__name__}: {str(e)[:200]}]")
        turn_context.note(message_id=st["turn_id"])


def _engine():
    """AGENT_ENGINE, read per turn. Prompt B (2026-10-31; the user accepted it): the graph (agent_graph.py, the SAME step
    functions) is the default; "loop" runs the loop below, the single-user fallback."""
    return "loop" if os.environ.get("AGENT_ENGINE", "").strip().lower() == "loop" else "graph"


def _run_turn(user_message: str, messages: list = None, *, thread=None):
    if _engine() == "graph":
        import agent_graph
        return agent_graph.run_turn(user_message, messages, thread=thread)
    st = _begin_turn(user_message, messages, thread=thread)
    while True:
        st.update(_call_model(st))

        block = _final_text_block(st)
        if block is not None:
            st.update(_finish(st, _fact_checked(st, block.text)))
            return st["rendered"], st["messages"]

        if _round_capped(st):                                           # Prompt P6: no further model call
            st.update(_round_cap(st))
            return st["rendered"], st["messages"]

        st.update(_run_tools(st))

        if st.get("direct_text") is not None:                         # Prompt W11g G1: the tool's text is the reply
            st.update(_append_tool_results(st))
            st.update(_direct(st))
            return st["rendered"], st["messages"]

        if not st["tool_results"]:                                      # Prompt E loop guard: no tool call this response
            text_block = _guard_text_block(st)
            if text_block is not None:                                  # stop_reason tool_use without a call: the text is the reply
                st.update(_finish(st, _fact_checked(st, text_block.text)))
                return st["rendered"], st["messages"]
            st.update(_loop_guard(st))
            return st["rendered"], st["messages"]

        st.update(_append_tool_results(st))

if __name__ == "__main__":
    question = input("Ask about FPL: ")
    answer, _ = run_agent(question)
    print("\n" + answer)