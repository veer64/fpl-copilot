"""One price table for the agent's model (2026-10-10).

The eval runner (eval/run_agent_evals.py) carried the claude-sonnet-4-6 rates as two constants for
its cost lines; the /chat usage log (agent.py -> db_write.record_chat_usage) needs the same figures,
so both read them from here. Anthropic first-party API rates per million tokens, as read from the
claude-api skill's model table 2026-10-02: $3.00 in / $15.00 out. Cache-read and cache-write tokens
are recorded but NOT priced, exactly as the runner never priced them; the agent sends no
cache_control, so they are zero in practice. A model with no row here prices to None, which the
log stores as NULL -- never a guess.
"""

USD_PER_MTOK = {
    "claude-sonnet-4-6": {"input": 3.00, "output": 15.00},
}


def usd(model, input_tokens, output_tokens):
    """Dollars for the tokens at the model's rates, rounded to 6 places; None when the model has no row."""
    p = USD_PER_MTOK.get(model)
    if p is None:
        return None
    return round((input_tokens or 0) / 1e6 * p["input"] + (output_tokens or 0) / 1e6 * p["output"], 6)
