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
