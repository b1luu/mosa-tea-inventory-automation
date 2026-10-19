"""Shop-day boundaries in California time.

The shop's day runs midnight to midnight in ``America/Los_Angeles``, which
switches between PST and PDT on its own. Square and the usage log store UTC
timestamps such as ``2026-10-18T05:30:00.123Z``, so windows are converted to
UTC strings with milliseconds, which compare correctly as plain strings.
"""

from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

SHOP_TIMEZONE = "America/Los_Angeles"
SHOP_TZ = ZoneInfo(SHOP_TIMEZONE)


def utc_bound(local_day, tz=SHOP_TZ):
    """Local midnight starting ``local_day`` as a UTC string, e.g. ``2026-10-17T07:00:00.000Z``."""
    midnight = datetime.combine(local_day, time.min, tzinfo=tz)
    return midnight.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def day_window(local_day, tz=SHOP_TZ):
    """(UTC start, UTC end) covering one local day, end exclusive."""
    return utc_bound(local_day, tz), utc_bound(local_day + timedelta(days=1), tz)


def local_day_window(days, tz=SHOP_TZ, today=None):
    """The last ``days`` local days ending today: (UTC start, UTC end, [day strings])."""
    today = today or datetime.now(tz).date()
    first = today - timedelta(days=days - 1)
    local_days = [first + timedelta(days=offset) for offset in range(days)]
    return (
        utc_bound(first, tz),
        utc_bound(today + timedelta(days=1), tz),
        [day.isoformat() for day in local_days],
    )


def local_day_of(timestamp, tz=SHOP_TZ):
    """The local calendar day of a UTC timestamp."""
    return to_local(timestamp, tz).date().isoformat()


def to_local(timestamp, tz=SHOP_TZ):
    return datetime.fromisoformat(timestamp.replace("Z", "+00:00")).astimezone(tz)


def shop_today(tz=SHOP_TZ):
    return datetime.now(tz).date()
