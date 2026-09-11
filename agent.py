# Tools over the MODEL's outputs (model_tools.py). Every prediction answer
# carries model_version and built_at; picks say when they were recovered
# post-deadline. config_roles.PRODUCTION_CONFIG ('baseline' since 2026-09-11) is
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
        "description": "The production model's predicted points for a player: one target gameweek if gw is given, else the whole six-gameweek horizon of the latest run. Includes e_points, expected minutes, start probability, and the model_version/built_at provenance.",
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
        "description": "Compare two players under the production model: next-gameweek expected points, start probability, and the six-gameweek horizon sum, with a verdict.",
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
    }
]

import os
from dotenv import load_dotenv
import anthropic
from model_tools import (list_players, resolve_player, get_player_card,
                         get_prediction, compare_players, get_picks,
                         get_best_squad, optimise)

load_dotenv()
client = anthropic.Anthropic()

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
    "list_players": list_players
}

def run_agent(user_message: str, messages: list = None):
    if messages is None:
        messages = []

    messages.append({"role": "user", "content": user_message})

    while True:
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1024,
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

                function_to_call = available_functions[tool_name]
                result = function_to_call(**tool_input)

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