# season_stack.py
# ONE resolver for the cross-season player-fixture stack.
#
# The frozen archive (all_seasons_fixed.parquet, vaastav-sourced, 2016-17..
# 2025-26) is never modified; live seasons are appended by
# eval/fetch_fpl_history.py --combine as all_seasons_with_{tag}.parquet
# (archive rows byte-identical, order- and dtype-preserved -- proven by the
# 2025-26 live-parity suite staying bit-identical through the repointing).
# Every vaastav-shaped consumer (minutes, bonus, the walk-forward skeleton and
# penalty-rate path, live_deadline's detectors) resolves the file through
# stack_path() so a new season lands in ONE place.
#
# Resolution: the newest all_seasons_with_*.parquet if any exists (lexically
# newest -- season tags sort chronologically), else the frozen archive.
# Repo-relative, portable (no drive-letter constants; this code also runs on
# the Linux droplet).

from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
HISTORY = REPO / "data" / "history"


def stack_path():
    combined = sorted(HISTORY.glob("all_seasons_with_*.parquet"))
    return combined[-1] if combined else HISTORY / "all_seasons_fixed.parquet"
