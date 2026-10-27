from datetime import date, datetime, timezone


def now() -> datetime:
    """Naive UTC 'now'. All timestamps in the database use this."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def today() -> date:
    return now().date()
