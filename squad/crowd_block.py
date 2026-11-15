# crowd_block.py
# Pre-deadline CROWD features (ownership and the week's transfer flow) as a block of the
# minutes model -- M3, model-upgrade plan step 3. GATED OFF: minutes.CROWD_FEATURES_ACTIVE
# rests False and minutes.py imports this module only when the gate is on, so no frame,
# payload or build changes until it is flipped. NOT ADOPTED -- a pre-registered test only
# (eval/reports/m3_crowd_build.md).
#
# WHAT THE BLOCK IS
# -----------------
# Five numbers per player, from the ONE bootstrap-static snapshot the availability block
# already names for each gameweek -- the last snapshot STRICTLY BEFORE that gameweek's
# deadline (data/availability_{tag}.parquet: `snapshot_path`). The formulas are M2's
# builder, eval/crowd_features.py (Probe A's, X2 review PR-6), imported -- not copied:
#     cs_own_pct, cs_out_ratio, cs_in_ratio, cs_net_log, cs_cost_change_event
# and two FORMS of them (minutes.CROWD_FORM):
#     "raw"   the five as they are
#     "rank"  cs_own_pct unchanged, the four flow features as their percentile rank within
#             the gameweek's snapshot -- a rank does not care how much of the week's
#             transfers the snapshot had seen (hours before the deadline vs days).
# A player the snapshot does not carry gets NaN (LightGBM's missing value), never a zero.
#
# LEAK RULE
# ---------
# Which snapshot is read comes from availability_features.load() -- the SAME loader the
# availability block uses -- and from nothing else. So the as-of guard
# (eval/asof_reconstruction.py), which cuts that loader to gameweeks <= the cutoff, cuts
# this block with it: a frame built at cutoff k cannot read a later gameweek's snapshot.
# The features are the raw fields of the named snapshot: never the asof_ late-news patch
# (reconstructed from a later snapshot) and never the history table's `selected` /
# `transfers_in` / `transfers_out` (the deadline-FINAL counts).
#
# The block is joined on (season, element, GW), exactly as the availability block is, so
# a forward-skeleton row (an unplayed gameweek, measurements NaN) carries the fields too.

import sys
from pathlib import Path

import pandas as pd

import availability_features as avf

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "eval"))
import crowd_features as cf  # noqa: E402  (M2's builder: the one definition of the five features)

FORMS = {"raw": list(cf.CROWD), "rank": ["cs_own_pct"] + list(cf.RANKED)}
# Seasons whose snapshots are read: the ones the minutes model trains or predicts on.
SEASONS = tuple(cf.AVAIL_TAG)

# Raw rows of a snapshot, keyed by (season, gameweek, snapshot path). A snapshot file never
# changes, so this is safe to keep for the life of the process; WHICH keys are used is
# decided afresh on every build() from the availability loader (see LEAK RULE).
_SNAPSHOT_ROWS = {}


def columns(form):
    """The model columns of a form."""
    if form not in FORMS:
        raise ValueError(f"unknown crowd form {form!r}; expected one of {sorted(FORMS)}")
    return list(FORMS[form])


def build(data_dir=None):
    """Crowd features for every (season, gameweek) the availability loader serves, keyed
    (season, GW, element): the five raw features and the four within-gameweek ranks."""
    av = avf.load(data_dir)
    av = av[av["season"].isin(SEASONS)]
    parts = []
    for season, a in av.groupby("season", sort=True):
        for r in cf.snapshot_table(a[cf.NAMING_COLUMNS]).itertuples():
            key = (season, int(r.gw), str(r.snapshot_path))
            if key not in _SNAPSHOT_ROWS:
                p = Path(r.snapshot_path)
                _SNAPSHOT_ROWS[key] = cf.rows_from_payload(
                    season, r.gw, cf.read_snapshot(p if p.is_absolute() else REPO / p), r.hours_before_deadline)
            parts.append(_SNAPSHOT_ROWS[key])
    d = cf.to_ranks(cf.features(pd.concat(parts, ignore_index=True)))
    assert not d.duplicated(["season", "GW", "element"]).any(), "one crowd row per (season, gameweek, player)"
    return d


def attach(col, form, data_dir=None):
    """Left-join the form's columns onto a collapsed player-gameweek frame. The row count
    is guarded (cf.attach raises if the join changes it); no snapshot row -> NaN."""
    return cf.attach(col, build(data_dir), cols=columns(form))
