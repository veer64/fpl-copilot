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
