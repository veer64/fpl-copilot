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
        "description": "Search for a player by name (partial matches allowed). Returns candidates with player_id, team, position, price.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "The player's name or partial name"}
            },
            "required": ["name"]
        }
    },
    {
        "name": "get_player_card",
        "description": "Full details for one player: identity, price, availability status, and the production model's predictions for the coming gameweeks.",
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
        "description": "The production model's predicted points for a player: one target gameweek if gw is given, else the whole six-gameweek horizon of the latest run. Includes e_points, expected minutes, start probability, and the provenance: `built` says when the run was built and what it knew, `next_run_expected` when the next run lands -- quote both and tell the user when to check back.",
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
        "description": "Compare two players under the production model over the latest run's six-gameweek horizon: the horizon sum (the verdict's basis) and the figures for the run's FIRST gameweek (first_gw -- between deadlines that is the gameweek just played, not the next one; note_stale says so). For 'X or Y this week' prefer compare_predictions, which defaults to the next deadline's gameweek and names the terms behind the gap. Whatever you quote, name its gameweek.",
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
        "description": "The solved squad from the latest pipeline run: the fifteen, starting XI, captain, vice-captain, and bench in order. Use for 'who should I captain', 'what team should I field'. shadow=true returns the baseline config's squad (the tracked comparison), never shown as the recommendation.",
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
        "name": "get_best_squad",
        "description": "The optimal fifteen. At the default full budget this is the stored production solve (instant); a custom budget runs the real optimiser (takes seconds).",
        "input_schema": {
            "type": "object",
            "properties": {
                "budget": {"type": "number", "description": "Budget in millions, e.g. 95.5 (default 100.0)"}
            },
            "required": []
        }
    },
    {
        "name": "optimise",
        "description": "Run the production optimiser on the latest model frame with constraints: force players in, ban players, or change the budget. A real MIP solve -- takes seconds. Returns fifteen + XI + captain + vice.",
        "input_schema": {
            "type": "object",
            "properties": {
                "lock_player_ids": {"type": "array", "items": {"type": "integer"}, "description": "Element ids that MUST be in the squad"},
                "ban_player_ids": {"type": "array", "items": {"type": "integer"}, "description": "Element ids that must NOT be in the squad"},
                "budget": {"type": "number", "description": "Budget in millions (default 100.0)"}
            },
            "required": []
        }
    },
    {
        "name": "get_my_squad",
        "description": "The user's OWN fifteen -- the versioned squad state (a hypothetical entry seeded at GW4), NOT the model's free-pick solve. Returns the fifteen with purchase price, current price and what each would SELL for under FPL's rule, plus bank, total points and the version id. Free transfers: free_transfers_now is the count available for the next deadline (derived: one banked per gameweek, capped at 5); free_transfers_recorded is the stale count as of the version's own gameweek -- quote free_transfers_now. The roles it carries (recorded_captain, recorded_vice, recorded_xi, recorded_bench_in_order) are what was RECORDED when that version was written -- a record, NOT this week's advice; the `roles` block says whether they are STALE relative to the latest model run, and if so you must say so. Use for 'what is my team', 'what would X sell for', 'how much money do I have'. For 'who should I start / captain / bench this week' call get_my_xi instead. If it returns an error, no squad state is recorded: say exactly that and do NOT answer with get_picks instead.",
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
        "description": "The NEXT DEADLINE's best starting XI, captain, vice-captain and bench order over the fifteen the user owns, solved by the production optimiser from the current model run's predictions (a real solve, about a second). Between deadlines the frame belongs to the previous deadline, so the predictions are labelled as of that cutoff (note_stale, stale_by_gameweeks) -- say so when present. Use for 'who should I start', 'who should I captain', 'what is my best XI', 'should X or Y start'. It also reports how the recorded roles differ and the expected points they leave on the table (recorded_roles.expected_gain_vs_recorded). Nothing is written: to record this XI, pass adopt_with to set_my_squad (preview first, then confirm=true when the user says so).",
        "input_schema": {
            "type": "object",
            "properties": {
                "user_id": {"type": "integer", "description": "Defaults to 1, the only user"}
            },
            "required": []
        }
    },
    {
        "name": "explain_prediction",
        "description": "WHY the model gives a player its expected points for a gameweek: the nine lines the model actually sums (appearance, goals with a penalties sub-line, assists, clean sheet, defensive contribution, saves, goals conceded, cards, bonus), each with the inputs it was made from and one of three source words -- model (a fitted model for this player/fixture), constant (a fixed value standing in for a model the project has not built or has switched off), rule (FPL's scoring rule applied to a model output) -- plus the fixture line and one summary sentence. Quote the `summary` and the labelled lines as the tool gives them (the `rendered` block is quotable verbatim); the three words are the tool's, do not editorialise about the constants. If `reconciles` is false the result carries a `finding`: report the finding, do not present the breakdown. Between deadlines the frame is one gameweek stale (note_stale, stale_by_gameweeks) -- say so. Use for 'why is X predicted N', 'what is behind X's score', 'is that a model or a guess'.",
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
        "description": "WHY one player's expected points for a gameweek MOVED between two runs ('Tuesday said 8.5, Friday says 6.2'): both stored breakdowns, the per-term difference (run a minus run b) ranked by size, one sentence naming the terms that account for at least 80% of the move, the constant-vs-model flags, and what each run knew (run_a.built / run_b.built -- quote both). The `rendered` block is quotable verbatim. Run ids come from get_prediction / health (the latest) or the user. Runs before 2026-09-14 have no stored terms and answer with an error: say so.",
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
        "description": "WHY two players' expected points differ for a gameweek: both breakdowns (see explain_prediction) on the same gameweek at the same cutoff, the per-term difference a minus b ranked by size, one sentence naming the terms that account for at least 80% of the gap, and flags where a term is a constant on one side against a model value on the other (say those out loud). The `rendered` block is quotable verbatim. Same stale-by-one labelling and identity checks. Use for 'why is X above Y', 'what separates X and Y', 'X or Y and why'.",
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
        "description": "The six-week transfer plan for the user's OWN squad from the production model: what to sell and buy for the next deadline (with sell prices under FPL's rule, purchase prices, hits, bank after, and the XI/captain after the move), plus the following gameweeks' indicative moves. Two real optimiser solves (the move plan, and the HOLD BASELINE that says what doing nothing scores over the same horizon): it typically takes twenty to sixty seconds and occasionally longer, so tell the user it will take a moment before calling it. The result carries hold_comparison: report the hold total, the move total and the gap. If hold_comparison.refused is true, give its refusal instead of the gap and do not reconstruct the gap from the two objectives yourself -- it is withheld because it is biased, not because it is missing. Optional lock_player_ids (must be in the squad: kept if owned, bought if not) and ban_player_ids (must not be: sold if owned, never bought) answer 'best plan given I am keeping X and refusing Y'. Every proposal is checked through the same legality and money rules as set_my_squad and saved with a proposal_id. It is a PROPOSAL, not an application: to make it, pass apply_with to set_my_squad (confirm=false to preview, confirm=true only when the user explicitly says so). If the response carries bug=true, say so plainly and do not present the proposal as advice.",
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
        "description": "List players filtered by team and/or position (e.g. 'who plays for Chelsea', 'list all defenders'). Do NOT use resolve_player for these.",
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
            "the point. Never average them into one score. Use for 'who does X play', 'how are "
            "Arsenal's next five fixtures', 'is this a good run'. Each fixture says whether it "
            "is market-priced or pure Dixon-Coles, and flags a runaway strength."),
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
            "you get half rounded down; a fall is yours in full). Use for 'who is rising', 'what "
            "is my squad worth', 'can I afford X'. It reports what HAS happened: it cannot say "
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
                          "description": "ISO timestamp cutoff (UTC); omit for the latest run's cutoff"},
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
                "as_of": {"type": "string", "description": "ISO timestamp cutoff (UTC); omit for the latest run's cutoff"}
            },
            "required": ["team"]
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
                         get_price_movements, get_league_table, get_match_stats)

load_dotenv()
client = anthropic.Anthropic()

# The system prompt (master plan 5.5): a reviewed, diffable file, not a
# string in code. Loaded once at import; a missing file is a startup error,
# not a silent run without grounding rules.
from pathlib import Path
PROMPT_PATH = Path(__file__).resolve().parent / "prompts" / "system_prompt.md"
SYSTEM_PROMPT = PROMPT_PATH.read_text(encoding="utf-8")


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
        return {"error": f"tool {tool_name} failed: {type(e).__name__}: {str(e)[:600]}",
                "tool": tool_name, "input": tool_input}

# A lookup so we can call the right Python function by name,
# once Claude tells us which tool it wants
available_functions = {
    "resolve_player": resolve_player,
    "get_player_card": get_player_card,
    "get_prediction": get_prediction,
    "compare_players": compare_players,
    "get_picks": get_picks,
    "get_best_squad": get_best_squad,
    "optimise": optimise,
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
}

def run_agent(user_message: str, messages: list = None):
    if messages is None:
        messages = []

    messages.append({"role": "user", "content": user_message})

    while True:
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1024,
            system=SYSTEM_PROMPT,
            tools=tools_schema,
            messages=messages
        )

        messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason != "tool_use":
            for block in response.content:
                if block.type == "text":
                    return block.text, messages

        tool_results = []
        for block in response.content:
            if block.type == "tool_use":
                tool_name = block.name
                tool_input = block.input
                tool_id = block.id

                print(f"  [calling tool: {tool_name}({tool_input})]")

                result = call_tool(tool_name, tool_input)
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