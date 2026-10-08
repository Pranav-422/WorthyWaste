"""Single source of 'now' so seeding and tests can pin time. All timestamps are UTC 'YYYY-MM-DD HH:MM:SS'."""
from datetime import datetime, timedelta, timezone

FMT = "%Y-%m-%d %H:%M:%S"
_frozen: datetime | None = None


def now() -> datetime:
    return _frozen or datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)


def freeze(at: datetime | None) -> None:
    global _frozen
    _frozen = at


def ts(dt: datetime | None = None) -> str:
    return (dt or now()).strftime(FMT)


def parse(s: str) -> datetime:
    return datetime.strptime(s, FMT)


def ago(**kw) -> str:
    return ts(now() - timedelta(**kw))


IST = timedelta(hours=5, minutes=30)


def ist_day(dt: datetime | None = None) -> str:
    """The India calendar date of a UTC moment: what "one pickup per door per day" counts by."""
    return ((dt or now()) + IST).strftime("%Y-%m-%d")
