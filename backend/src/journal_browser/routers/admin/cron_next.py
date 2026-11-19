"""Smallest useful cron "next fire time" for the ops status endpoint.

Understands the 5-field crontab subset the deployment schedules use
(minute hour dom month dow): numbers, ranges, steps, comma lists, and
"*". Day-of-week accepts 0-7 with both 0 and 7 meaning Sunday. The
standard Vixie rule applies: when both day-of-month and day-of-week are
restricted, a day matching either one fires.

next_fire returns None when nothing matches within LOOKAHEAD_DAYS; a
malformed expression raises ValueError with a message the endpoint can
show verbatim.
"""

from datetime import UTC, datetime, timedelta

LOOKAHEAD_DAYS = 366

_FIELD_RANGES = ((0, 59), (0, 23), (1, 31), (1, 12), (0, 7))


def _parse_field(raw: str, lo: int, hi: int) -> set[int]:
    values: set[int] = set()
    for part in raw.split(","):
        part = part.strip()
        step = 1
        if "/" in part:
            part, step_raw = part.split("/", 1)
            step = int(step_raw)
            if step <= 0:
                raise ValueError(f"step must be positive: {step_raw!r}")
        if part == "*":
            values.update(range(lo, hi + 1, step))
            continue
        if "-" in part:
            first, last = (int(v) for v in part.split("-", 1))
            if first > last:
                raise ValueError(f"range must be ascending: {part!r}")
            values.update(range(first, last + 1, step))
        else:
            first = int(part)
            if first < lo or first > hi:
                raise ValueError(f"value {first} out of range {lo}-{hi}")
            if step == 1:
                values.add(first)
            else:
                # Vixie extension "5/10": from 5 to the field max, every 10.
                values.update(range(first, hi + 1, step))
    if not values:
        raise ValueError("empty field")
    return values


def next_fire(expr: str, after: datetime) -> datetime | None:
    """First fire time of `expr` strictly after `after` (UTC), or None."""
    fields = expr.split()
    if len(fields) != 5:
        raise ValueError(f"expected 5 space-separated fields, got {len(fields)}")
    minutes = _parse_field(fields[0], *_FIELD_RANGES[0])
    hours = _parse_field(fields[1], *_FIELD_RANGES[1])
    doms = _parse_field(fields[2], *_FIELD_RANGES[2])
    months = _parse_field(fields[3], *_FIELD_RANGES[3])
    dows = _parse_field(fields[4], *_FIELD_RANGES[4])
    # Cron day-of-week: 0 and 7 are Sunday; Python isoweekday is Mon=1..Sun=7.
    dows = {0 if d == 7 else d for d in dows}
    dom_any = fields[2] == "*"
    dow_any = fields[4] == "*"

    cur = after.astimezone(UTC).replace(second=0, microsecond=0) + timedelta(minutes=1)
    limit = cur + timedelta(days=LOOKAHEAD_DAYS)
    while cur <= limit:
        if cur.month not in months:
            # Nothing this month: jump to the 1st of the next one.
            year, month = (cur.year + 1, 1) if cur.month == 12 else (cur.year, cur.month + 1)
            cur = datetime(year, month, 1, tzinfo=UTC)
            continue
        dom_ok = cur.day in doms
        dow_ok = cur.isoweekday() % 7 in dows
        if dom_any and dow_any:
            day_ok = True
        elif dom_any:
            day_ok = dow_ok
        elif dow_any:
            day_ok = dom_ok
        else:
            day_ok = dom_ok or dow_ok
        if not day_ok:
            cur = (cur + timedelta(days=1)).replace(hour=0, minute=0)
            continue
        if cur.hour not in hours:
            cur = (cur + timedelta(hours=1)).replace(minute=0)
            continue
        if cur.minute in minutes:
            return cur
        cur += timedelta(minutes=1)
    return None
