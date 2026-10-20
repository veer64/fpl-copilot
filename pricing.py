"""One price table for the agent's model (2026-10-10), with the prompt-cache rates since 2026-10-19.

The eval runner (eval/run_agent_evals.py) carried the claude-sonnet-4-6 rates as two constants for
its cost lines; the /chat usage log (agent.py -> db_write.record_chat_usage) needs the same figures,
so both read them from here. Anthropic first-party API rates per million tokens, as read from the
claude-api skill's model table 2026-10-02: $3.00 in / $15.00 out. A model with no row here prices
to None, which the log stores as NULL -- never a guess.

Prompt caching (the Claude docs, platform.claude.com/docs/en/build-with-claude/prompt-caching, read
19 Oct 2026): a cache write costs 1.25x the base input price; a cache read 0.1x, except 0.05x for
claude-opus-5-5 and claude-sonnet-5-5 and 0.025x for claude-fable-5-1 / claude-mythos-5-1. The
API's input_tokens are the UNCACHED input; cache_creation_input_tokens and cache_read_input_tokens
come beside them, so a turn costs
    uncached input + 1.25 x write + read multiplier x read + output.
"""

USD_PER_MTOK = {
    "claude-sonnet-4-6": {"input": 3.00, "output": 15.00},
}

CACHE_WRITE_MULT = 1.25
CACHE_READ_MULT_DEFAULT = 0.10
CACHE_READ_MULT = {
    "claude-opus-5-5": 0.05,
    "claude-sonnet-5-5": 0.05,
    "claude-fable-5-1": 0.025,
    "claude-mythos-5-1": 0.025,
}


def cache_read_multiplier(model):
    """The cache-read price as a multiple of the model's base input price."""
    return CACHE_READ_MULT.get(model, CACHE_READ_MULT_DEFAULT)


def turn_usd(model, input_tokens, output_tokens, cache_read=0, cache_write=0):
    """Dollars for one turn (or one call): uncached input, cache write, cache read and output at the model's
    rates, rounded to 6 places; None tokens count as 0; None when the model has no row."""
    p = USD_PER_MTOK.get(model)
    if p is None:
        return None
    base_in = p["input"]
    return round((input_tokens or 0) / 1e6 * base_in
                 + (cache_write or 0) / 1e6 * base_in * CACHE_WRITE_MULT
                 + (cache_read or 0) / 1e6 * base_in * cache_read_multiplier(model)
                 + (output_tokens or 0) / 1e6 * p["output"], 6)


def usd(model, input_tokens, output_tokens):
    """The pre-caching price (no cache tokens): kept for the callers that have none."""
    return turn_usd(model, input_tokens, output_tokens)
