"""Every model the code names has a price row (2026-10-24). pricing.turn_usd prices a model with no row to None,
which the chat_usage log stores as NULL and every report then shows as NOT DETERMINED; claude-sonnet-5 (the relevance
filter and the extraction) and claude-opus-5-5 (the judge and the shadow judge) had no row, so every llm_calls cost
line for them was NOT DETERMINED. Rates from platform.claude.com/docs/en/about-claude/pricing.md, fetched
2026-10-24 23:28Z: Sonnet 5 $2 in / $10 out, 5-minute cache write $2.50, cache hit $0.20 (0.10x); Opus 5.5 $4 / $20,
write $5, hit $0.20 (0.05x); Haiku 4.5 $1 / $5, write $1.25, hit $0.10."""
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
for p in (str(REPO), str(REPO / "eval")):
    if p not in sys.path:
        sys.path.insert(0, p)

import config_roles                                        # noqa: E402
import pricing                                             # noqa: E402


def models_named_in_config():
    """Every model id the configuration and the two call sites name: the agent, the relevance filter (also the
    extraction's model), the shadow judge, the judge, and every key of the per-model tables."""
    import agent
    import run_agent_evals as rae
    names = {agent.AGENT_MODEL, config_roles.RELEVANCE_MODEL, config_roles.SHADOW_JUDGE_MODEL, rae.JUDGE_MODEL}
    names |= set(config_roles.MODELS_WITHOUT_TEMPERATURE)
    names |= set(config_roles.RELEVANCE_MAX_TOKENS_BY_MODEL) | set(config_roles.EXTRACT_MAX_TOKENS_BY_MODEL)
    names |= set(config_roles.MODEL_PRICES_USD_PER_MTOK)
    return sorted(names)


def test_every_model_named_in_config_has_a_pricing_row():
    missing = [m for m in models_named_in_config() if m not in pricing.USD_PER_MTOK]
    assert missing == [], f"no price row for {missing}"


def test_claude_sonnet_5_turn_usd_with_cache_write_and_read():
    # $2 in / $10 out; write 1.25x = $2.50 / MTok; read 0.10x = $0.20 / MTok (the official page's figures)
    assert pricing.USD_PER_MTOK["claude-sonnet-5"] == {"input": 2.00, "output": 10.00}
    assert pricing.cache_read_multiplier("claude-sonnet-5") == 0.10
    # 1000 uncached in (0.002) + 2000 written (0.005) + 10000 read (0.002) + 100 out (0.001)
    assert pricing.turn_usd("claude-sonnet-5", 1000, 100, cache_read=10000, cache_write=2000) == pytest.approx(0.010)
    assert pricing.turn_usd("claude-sonnet-5", 1000, 100) == pytest.approx(0.003)
    assert pricing.usd("claude-sonnet-5", 1_000_000, 0) == pytest.approx(2.00)
    assert pricing.usd("claude-sonnet-5", 0, 1_000_000) == pytest.approx(10.00)


def test_the_other_two_rows_match_the_official_page():
    assert pricing.USD_PER_MTOK["claude-opus-5-5"] == {"input": 4.00, "output": 20.00}
    # Opus 5.5: cache hit 0.05x = $0.20 / MTok; 1000 in (0.004) + 10000 read (0.002) + 100 out (0.002)
    assert pricing.turn_usd("claude-opus-5-5", 1000, 100, cache_read=10000) == pytest.approx(0.008)
    assert pricing.USD_PER_MTOK["claude-haiku-4-5-20251001"] == {"input": 1.00, "output": 5.00}
    assert pricing.turn_usd("claude-haiku-4-5-20251001", 1000, 100, cache_write=2000) == pytest.approx(0.001 + 0.0025 + 0.0005)


def test_the_config_report_table_agrees_with_pricing_py():
    """config_roles.MODEL_PRICES_USD_PER_MTOK (the reports' cost lines) and pricing.py must not drift apart."""
    for model, (i, o) in config_roles.MODEL_PRICES_USD_PER_MTOK.items():
        assert pricing.USD_PER_MTOK[model] == {"input": i, "output": o}, model


def test_a_model_with_no_row_still_prices_to_none():
    assert pricing.turn_usd("claude-test-unpriced", 1000, 100, cache_read=10) is None
    assert pricing.usd("claude-test-unpriced", 1000, 100) is None
