# config_roles.py -- ONE place that says which configuration is PRODUCTION and
# which, if any, is the SHADOW. Read by the deadline runner
# (eval/run_live_deadline.py), the DB writer (db_write.py), the app's typed
# reads (model_tools.py) and the live builder's docs (squad/live_deadline.py).
#
# ADOPTED 2026-09-11 (Logs/baseline_adoption_log.md): production = baseline.
# A judgement call made after the leak fix (KNOWN_ISSUES #22/#23/#24) invalidated
# the comparison the 2026-08-28 "combined = production intent" choice rested on;
# NOT taken on season totals. No shadow: the shadow comparison had no statistical
# power (season_totals_index header) and its inputs are exactly the paid and
# weekly steps production no longer needs. Both levers are UNSETTLED, not
# settled; re-opening either is a NEW pre-registration on clean frames.
#
# Flipping SHADOW_CONFIG to "combined" re-enables, in the runner, the live props
# pull + crosswalk + consensus and the hmin delete-and-refit (LEVER_INPUTS_ACTIVE),
# the combined strict build, its solve and its DB rows. Nothing is deleted; the
# combined path stays code-complete and test-pinned behind this constant.
PRODUCTION_CONFIG = "baseline"
SHADOW_CONFIG = None
CONFIGS = tuple(c for c in (PRODUCTION_CONFIG, SHADOW_CONFIG) if c)
LEVER_INPUTS_ACTIVE = "combined" in CONFIGS

# MAX_AVAILABILITY_AGE -- how old the availability (FPL status / chance_of_playing / news)
# that a LIVE deadline build scores on may be: min(build time, deadline) minus the newest
# snapshot_time in the deadline gameweek's rows of data/availability_<season>.parquet. The
# strict preflight (squad/live_deadline.py) RAISES past it; /health (model_tools.health)
# reports the served build's age against it. USER DECISION 2026-09-25: 6 hours. ONE
# definition, read by the builder and the read side alike -- never copied.
from datetime import timedelta
MAX_AVAILABILITY_AGE = timedelta(hours=6)

# CLUB_DOMAINS -- the official-website allowlist for club team news (approved by the user
# 2026-09-25 after a one-GET verification of every site): FPL team name (bootstrap-static
# `teams[].name`) -> registrable domain, no "www." so subdomains match. ONE place; every
# fetcher, search filter and provenance check reads this and nothing else. Not verified by
# title on the seven JavaScript-rendered sites (avfc, afcb, ccfc, evertonfc, wearehullcity,
# nottinghamforest, safc): their served HTML carries no <title>; the domains are the clubs'.
CLUB_DOMAINS = {
    "Arsenal": "arsenal.com",
    "Aston Villa": "avfc.co.uk",
    "Bournemouth": "afcb.co.uk",
    "Brentford": "brentfordfc.com",
    "Brighton": "brightonandhovealbion.com",
    "Chelsea": "chelseafc.com",
    "Coventry City": "ccfc.co.uk",
    "Crystal Palace": "cpfc.co.uk",
    "Everton": "evertonfc.com",
    "Fulham": "fulhamfc.com",
    "Hull City": "wearehullcity.co.uk",
    "Ipswich Town": "itfc.co.uk",
    "Leeds": "leedsunited.com",
    "Liverpool": "liverpoolfc.com",
    "Man City": "mancity.com",
    "Man Utd": "manutd.com",
    "Newcastle": "newcastleunited.com",
    "Nott'm Forest": "nottinghamforest.co.uk",
    "Spurs": "tottenhamhotspur.com",
    "Sunderland": "safc.com",
}

# CLUB_NEWS_CLUBS -- the clubs whose official sites Tavily can actually read (measured
# 2026-09-25: basic search returned real availability text for these nine; the other eleven
# returned ~150-char stubs or nothing at any depth). club_news.py searches these only.
CLUB_NEWS_CLUBS = ("Arsenal", "Brentford", "Chelsea", "Crystal Palace", "Liverpool",
                   "Man City", "Man Utd", "Newcastle", "Spurs")
# TAVILY_MONTHLY_LIMIT -- credits per calendar month the club-news runner may spend, by
# Tavily's published rule (basic search 1, basic extract 1 per 5 URLs), counted from the
# tavily_calls table. The guard refuses a run whose worst-case plan would cross it.
# USER DECISION 2026-09-25: 800 (the Researcher plan holds 1,000).
TAVILY_MONTHLY_LIMIT = 800

# TEAM_ALIASES -- hand-written names a club is called in prose, keyed by FPL team name. The
# full alias map (club_news.team_aliases) is this list PLUS the FPL team data from the newest
# raw snapshot (name, short_name). Kept to forms that identify ONE club: bare "United" or
# "City" would match three clubs each and are deliberately absent.
TEAM_ALIASES = {
    "Arsenal": ["Gunners"],
    "Aston Villa": ["Villa", "AVFC"],
    "Bournemouth": ["AFC Bournemouth", "Cherries"],
    "Brentford": ["Bees"],
    "Brighton": ["Brighton & Hove Albion", "Brighton and Hove Albion", "Seagulls", "Albion"],
    "Chelsea": ["Blues"],
    "Coventry City": ["Coventry", "Sky Blues"],
    "Crystal Palace": ["Palace", "Eagles", "CPFC"],
    "Everton": ["Toffees"],
    "Fulham": ["Cottagers"],
    "Hull City": ["Hull", "Tigers"],
    "Ipswich Town": ["Ipswich", "Tractor Boys"],
    "Leeds": ["Leeds United", "LUFC", "Whites"],
    "Liverpool": ["LFC"],
    "Man City": ["Manchester City", "Man City", "MCFC", "Citizens"],
    "Man Utd": ["Manchester United", "Man United", "Man Utd", "MUFC", "Red Devils"],
    "Newcastle": ["Newcastle United", "NUFC", "Magpies"],
    "Nott'm Forest": ["Nottingham Forest", "Nottm Forest", "Forest", "NFFC"],
    "Spurs": ["Tottenham", "Tottenham Hotspur", "THFC"],
    "Sunderland": ["SAFC", "Black Cats"],
}

# ---- the news relevance filter (relevance.py, 2026-09-26) -------------------------------------
# RELEVANCE_MODEL -- the PRODUCTION stage-2 classifier (verdicts of other models sit beside it in
# news_relevance; only this one feeds news_to_embed). USER DECISION 2026-09-28: Sonnet 5 on prompt
# v3, chosen on keep recall 4/5 vs Haiku 1/5 and relevant agreement 37/40 vs 26/40 against the
# 40-item gold set (n = 40, so 1-2 items is noise); the prompt was revised on those same 40 items,
# so the GW6-9 shadow data (SHADOW_JUDGE_*) is the unbiased check. Output budget 1024
# (RELEVANCE_MAX_TOKENS_BY_MODEL), no temperature parameter (MODELS_WITHOUT_TEMPERATURE).
RELEVANCE_MODEL = "claude-sonnet-5"
# PROMPT_VERSION -- the production prompt, stamped on every verdict; bump it when the prompt or
# the stage-1 rules change and every item is judged again (old verdicts are kept; news_to_embed
# reads only this version under RELEVANCE_MODEL). v2 (2026-09-26) grounds the model in FPL data:
# the players named and the club squad as of the item's fetch time. v3 (2026-09-28) adds three
# recency rules to point 2 (cup matches are not in the fixture list; 7-day news is current;
# long-term injuries stay current) after the 40-item gold calibration. NOTE: v3 was written with
# those 40 items in view, so its gold scores are optimistic; the GW6-9 shadow data is the check.
PROMPT_VERSION = "relevance_v3"
# MODELS_WITHOUT_TEMPERATURE -- models that reject the temperature parameter (HTTP 400 "temperature is
# deprecated for this model", measured 2026-09-27 on both). llm.py omits it for these and sends
# temperature=0 to every other model. Explicit list; add a model only when confirmed. There is no
# retry-without-temperature on error (USER RULING 2026-09-27).
MODELS_WITHOUT_TEMPERATURE = ("claude-sonnet-5", "claude-opus-5-5")
# RELEVANCE_MAX_TOKENS_BY_MODEL -- output budget per model, overriding the prompt profile's value
# (200 for relevance_*, 500 for reference_*). USER RULING 2026-09-27 after Sonnet 5 hit 200 on 17 of
# 71 replies (its default reasoning block and its tokenizer both cost output): Haiku unchanged so
# its requests stay byte-identical; thinking settings are never touched, each model runs as it
# would in production. A model not listed keeps the profile value.
RELEVANCE_MAX_TOKENS_BY_MODEL = {"claude-haiku-4-5-20251001": 200, "claude-sonnet-5": 1024, "claude-opus-5-5": 2048}
# AMBIGUOUS_NAMES -- web_names that are also ordinary words or shared by several players; alone
# they never make an item a keyword YES (stage 1 sends it to the LLM as BORDERLINE instead).
# Names shared by 2+ current players are added from the bootstrap at run time.
AMBIGUOUS_NAMES = ("Wood", "Son", "James", "Mason", "Gabriel", "Palmer", "King", "Hill", "White",
                   "Young", "Rice", "Little")
# RELEVANCE_SIGNALS -- availability words; whole-word, case- and accent-insensitive.
RELEVANCE_SIGNALS = (
    "injury", "injured", "hamstring", "knee", "ankle", "calf", "groin", "thigh", "knock", "illness",
    "doubt", "doubtful", "ruled out", "sidelined", "fitness", "fit again", "back in training",
    "returned to training", "recovery", "suspended", "suspension", "ban", "red card", "team news",
    "available", "unavailable", "miss", "absent", "scan", "surgery", "operation",
)
