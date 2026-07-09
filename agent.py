tools_schema = [
    {
        "name": "resolve_player",
        "description": "Search for a player by name (partial matches allowed). Returns a list of candidate players with their IDs, since names can be ambiguous.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "The player's name or partial name to search for"}
            },
            "required": ["name"]
        }
    },
    {
        "name": "get_player_card",
        "description": "Get full details for one specific player, given their player_id.",
        "input_schema": {
            "type": "object",
            "properties": {
                "player_id": {"type": "integer", "description": "The player's unique ID"}
            },
            "required": ["player_id"]
        }
    },
    {
        "name": "predict_points",
        "description": "Get the predicted points for a specific player's next gameweek, given their player_id.",
        "input_schema": {
            "type": "object",
            "properties": {
                "player_id": {"type": "integer", "description": "The player's unique ID"}
            },
            "required": ["player_id"]
        }
    },
    {
        "name": "optimize_squad",
        "description": "Build and return the mathematically optimal 15-player FPL squad under budget (£100m), position, and club-limit constraints. Takes no arguments.",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": []
        }
    },
    {
        "name": "list_players",
        "description": "List players filtered by team and/or position. Use this for questions like 'who plays for Chelsea', 'list all defenders', or 'who is Arsenal's left back'. Do NOT use resolve_player for these kinds of queries.",
        "input_schema": {
            "type": "object",
            "properties": {
                "team": {"type": "string", "description": "Filter by team name (partial match allowed), e.g. 'Chelsea'"},
                "position": {"type": "string", "description": "Filter by position: Goalkeeper, Defender, Midfielder, or Forward"}
            },
            "required": []
        }
    }
]

import os
from dotenv import load_dotenv
import anthropic
from tools import list_players, resolve_player, get_player_card, predict_points, optimize_squad

load_dotenv()
client = anthropic.Anthropic()

# A lookup so we can call the right Python function by name,
# once Claude tells us which tool it wants
available_functions = {
    "resolve_player": resolve_player,
    "get_player_card": get_player_card,
    "predict_points": predict_points,
    "optimize_squad": optimize_squad,
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