"""The ONE formatter for every date or time an agent tool hands the model (Prompt G, 2026-10-29).

    when_words(x) -> "Fri 23 Oct 2026 17:21 UTC"      day_words(x) -> "Fri 23 Oct 2026"

The weekday is computed from the instant itself, so it can never disagree with the calendar -- the agent used to type
weekdays from memory next to ISO stamps ("Thursday 23 Oct" for a Friday). `x` may be a datetime (naive = UTC, the
project's rule), a date, a pandas Timestamp, or an ISO string ("2026-10-23T17:21:24Z", "2026-10-23 17:21:24+00:00",
with or without fractional seconds); None or anything unreadable gives None, never an exception, so a missing stamp
costs one field and not the tool. ISO fields that code reads stay as they were: the words are ADDED beside them
(frame_built beside frame_built_at, date_words beside date, ...), or replace text the model alone reads.
The freshness sentence (eval/dispatch_policy._fmt, "built Sat 12 Sep 11:01Z") already carried its weekday and is pinned
by its own tests; it is left as it is."""
from datetime import date, datetime, timezone

UTC = timezone.utc


def to_datetime(x):
    """A UTC-aware datetime from the shapes above, or None."""
    if x is None or x == "" or isinstance(x, bool):
        return None
    try:
        if hasattr(x, "to_pydatetime"):                 # pandas Timestamp
            x = x.to_pydatetime()
        if isinstance(x, datetime):
            t = x
        elif isinstance(x, date):
            t = datetime(x.year, x.month, x.day)
        elif isinstance(x, str):
            s = x.strip().replace("Z", "+00:00")
            t = datetime.fromisoformat(s)
        else:
            return None
    except (TypeError, ValueError, OverflowError):
        return None
    if t.tzinfo is None:
        t = t.replace(tzinfo=UTC)
    return t.astimezone(UTC)


def when_words(x):
    """'Fri 23 Oct 2026 17:21 UTC' or None."""
    t = to_datetime(x)
    if t is None:
        return None
    return f"{t:%a} {t.day} {t:%b %Y} {t:%H:%M} UTC"


def day_words(x):
    """'Fri 23 Oct 2026' or None."""
    t = to_datetime(x)
    if t is None:
        return None
    return f"{t:%a} {t.day} {t:%b %Y}"
