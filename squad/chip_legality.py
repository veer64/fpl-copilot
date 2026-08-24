# chip_legality.py
# One-chip-per-gameweek legality for a FULL effective chip schedule.
#
# WHY THIS EXISTS (2026-08-24). The simulator enforces chip clashes for the
# chips it schedules in-sim (wildcard, free hit, bench boost:
# simulator._chip_weeks). Triple Captain -- and the Bench Boost POINTS -- are
# exogenous reads applied after the fact by the measure scripts, and that
# layer had no legality check. The P4 convention read TC2's captain bonus on
# the biggest-DGW week, which is BB2's week in all three backtest seasons, so
# every chip-inclusive headline (2299/2301/2219) priced a play FPL does not
# allow: two chips in one gameweek. Nothing fired because the only guard was
# a total-vs-total drift assert, which is circular for a convention error.
#
# This module is the structural guard: it takes the EFFECTIVE schedule --
# in-sim chip weeks plus every read week the accounting actually used -- and
# refuses if it is not a legal FPL play. It is independent of any total.
#
# Chip set: the 2025-26 rules (two of each chip, one per half, at most one
# chip per gameweek), applied to every backtest season by project convention
# (P4 designs the policy for the current rules and backtests it on older
# seasons). Halves split at DEFAULT_SECOND_HALF_START, as in the simulator.

DEFAULT_SECOND_HALF_START = 20
CHIP_TYPES = ("wildcard", "free_hit", "bench_boost", "triple_captain")


class ChipLegalityError(ValueError):
    """The effective chip schedule is not a legal FPL play."""


def _norm(value):
    if value is None:
        return []
    if isinstance(value, (int, float)):
        return [int(value)]
    return [int(g) for g in value if g is not None]


def check_chip_schedule(schedule, played_gws=None,
                        second_half_start=DEFAULT_SECOND_HALF_START,
                        source=""):
    """Validate an effective chip schedule; return it normalised or raise.

    schedule : {chip_type: gameweeks} for chip types in CHIP_TYPES. Missing
               types mean "none". Include EVERY week the accounting used --
               in-sim chips AND exogenous reads (BB bench weeks, TC weeks).
    played_gws : optional set of gameweeks the squad actually played; every
               chip week must be in it (a read on a week with no row is a
               read of nothing).
    Rules:
      (i)   all chip weeks pairwise distinct (one chip per gameweek);
      (ii)  at most one of each chip type per half;
      (iii) reads only on played weeks (when played_gws is given).
    """
    unknown = set(schedule) - set(CHIP_TYPES)
    if unknown:
        raise ChipLegalityError(f"{source}: unknown chip type(s) {sorted(unknown)}")
    sched = {c: sorted(_norm(schedule.get(c))) for c in CHIP_TYPES}
    tag = f"{source}: " if source else ""

    # (i) one chip per gameweek, across all chip types
    owners = {}
    for chip, weeks in sched.items():
        for g in weeks:
            owners.setdefault(g, []).append(chip)
    clashes = {g: c for g, c in owners.items() if len(c) > 1}
    if clashes:
        desc = "; ".join(f"GW{g}: {' + '.join(c)}" for g, c in sorted(clashes.items()))
        raise ChipLegalityError(
            f"{tag}one chip per gameweek violated -- {desc}")

    # (ii) at most one of each chip type per half
    for chip, weeks in sched.items():
        first = [g for g in weeks if g < second_half_start]
        second = [g for g in weeks if g >= second_half_start]
        if len(first) > 1 or len(second) > 1:
            raise ChipLegalityError(
                f"{tag}more than one {chip} in a half (split at "
                f"GW{second_half_start}): first {first}, second {second}")

    # (iii) reads only on weeks the squad played
    if played_gws is not None:
        played = {int(g) for g in played_gws}
        missing = {chip: [g for g in weeks if g not in played]
                   for chip, weeks in sched.items()}
        missing = {c: w for c, w in missing.items() if w}
        if missing:
            raise ChipLegalityError(
                f"{tag}chip read on a gameweek the squad did not play: {missing}")
    return sched
