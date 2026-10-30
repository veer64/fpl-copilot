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

Three rows added 2026-10-24 from platform.claude.com/docs/en/about-claude/pricing.md (fetched 2026-10-24 23:28Z):
claude-sonnet-5 (the relevance filter and the extraction; "Claude Sonnet 5": $2 in, $2.50 5-minute cache write,
$0.20 cache hit, $10 out -- the launch price is now the standard price, footnote 3), claude-opus-5-5 (the judge and
the shadow judge: $4 / $5 / $0.20 / $20, hit 0.05x) and claude-haiku-4-5-20251001 ("Claude Haiku 4.5", the dated
id the relevance tables carry: $1 / $1.25 / $0.10 / $5). Until then every call on those models priced to None.
The 1-hour cache write (2x) is not modelled: nothing here sends a ttl, so every write is the 5-minute one.
"""

USD_PER_MTOK = {
    "claude-sonnet-4-6": {"input": 3.00, "output": 15.00},
    "claude-sonnet-5": {"input": 2.00, "output": 10.00},
    "claude-opus-5-5": {"input": 4.00, "output": 20.00},
    "claude-haiku-4-5-20251001": {"input": 1.00, "output": 5.00},
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


def cost_details(model, input_tokens, output_tokens, cache_read=0, cache_write=0):
    """The same price as turn_usd, per bucket and NOT rounded, for the Langfuse trace (tracing.py, Prompt L 2026-10-30):
    {input, cache_creation_input_tokens, cache_read_input_tokens, output, total} in dollars, where total is the four
    terms summed in turn_usd's order, so round(total, 6) == turn_usd(...) exactly and a turn's per-call totals add up to
    its chat_usage usd to within that rounding. None when the model has no row (the trace then carries no cost: never 0)."""
    p = USD_PER_MTOK.get(model)
    if p is None:
        return None
    base_in = p["input"]
    parts = {"input": (input_tokens or 0) / 1e6 * base_in,
             "cache_creation_input_tokens": (cache_write or 0) / 1e6 * base_in * CACHE_WRITE_MULT,
             "cache_read_input_tokens": (cache_read or 0) / 1e6 * base_in * cache_read_multiplier(model),
             "output": (output_tokens or 0) / 1e6 * p["output"]}
    parts["total"] = (parts["input"] + parts["cache_creation_input_tokens"] + parts["cache_read_input_tokens"]
                      + parts["output"])
    return parts


def usd(model, input_tokens, output_tokens):
    """The pre-caching price (no cache tokens): kept for the callers that have none."""
    return turn_usd(model, input_tokens, output_tokens)
