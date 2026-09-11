#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
cron.py — parse a cron expression, say what it means, and work out when it
next fires. Standard library only.

Supports the five standard fields and everything you would expect inside them:

    *            every value
    5            one value
    1-5          a range
    */15         a step over the whole field
    1-20/5       a step over a range
    1,15,30      a list of any of the above
    MON-FRI      day names (SUN..SAT, or 0-6 with 7 also Sunday)
    JAN,JUL      month names

Day-of-month and day-of-week follow the usual cron rule: when both are
restricted the job fires if EITHER matches, not both. That surprises people, so
describe() spells it out.

This exists so the UI and cron never disagree: the same expression that goes
into the crontab is the one the preview is computed from.
"""

import re
from datetime import datetime, timedelta

FIELDS = ("minute", "hour", "dom", "month", "dow")
BOUNDS = {"minute": (0, 59), "hour": (0, 23), "dom": (1, 31), "month": (1, 12), "dow": (0, 6)}

DAY_NAMES = ["SUN", "MON", "TUE", "WED", "THU", "FRI", "SAT"]
MONTH_NAMES = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN",
               "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]
DAY_FULL = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]
MONTH_FULL = ["January", "February", "March", "April", "May", "June",
              "July", "August", "September", "October", "November", "December"]

MAX_YEARS = 5          # how far ahead next_runs will look before giving up


class CronError(ValueError):
    """An expression a human needs to fix; the message is written for them."""


def _alias(token, field):
    token = token.upper()
    if field == "dow":
        for i, name in enumerate(DAY_NAMES):
            token = re.sub(r"\b%s\b" % name, str(i), token)
    elif field == "month":
        for i, name in enumerate(MONTH_NAMES, 1):
            token = re.sub(r"\b%s\b" % name, str(i), token)
    return token


def _parse_field(raw, field):
    low, high = BOUNDS[field]
    text = _alias(raw.strip(), field)
    if not text:
        raise CronError("the %s field is empty" % field)
    values = set()
    for part in text.split(","):
        part = part.strip()
        if not part:
            raise CronError("the %s field has an empty item" % field)
        step = 1
        if "/" in part:
            part, _, step_text = part.partition("/")
            if not step_text.isdigit() or int(step_text) < 1:
                raise CronError("%r is not a valid step in the %s field" % (step_text, field))
            step = int(step_text)
        part = part.strip()
        if part == "*":
            start, end = low, high
        elif "-" in part.lstrip("-"):
            a, _, b = part.partition("-")
            start, end = _one(a, field), _one(b, field)
            if start > end:
                raise CronError("%s range %s-%s runs backwards" % (field, a, b))
        else:
            start = end = _one(part, field)
            if step > 1:
                end = high
        values.update(range(start, end + 1, step))
    if not values:
        raise CronError("the %s field matches nothing" % field)
    return values


def _one(token, field):
    token = token.strip()
    low, high = BOUNDS[field]
    if not re.fullmatch(r"\d+", token):
        raise CronError("%r is not a number the %s field accepts" % (token, field))
    value = int(token)
    if field == "dow" and value == 7:
        value = 0                       # both 0 and 7 mean Sunday
    if not low <= value <= high:
        raise CronError("%s must be between %d and %d, got %d" % (field, low, high, value))
    return value


def parse(expression):
    """Returns {field: set(values), 'dom_restricted': bool, 'dow_restricted': bool}."""
    parts = str(expression or "").split()
    if len(parts) != 5:
        raise CronError("a cron expression needs 5 fields "
                        "(minute hour day-of-month month day-of-week), got %d" % len(parts))
    out = {f: _parse_field(p, f) for f, p in zip(FIELDS, parts)}
    out["dom_restricted"] = parts[2].strip() != "*"
    out["dow_restricted"] = parts[4].strip() != "*"
    return out


def matches(spec, when):
    if when.minute not in spec["minute"] or when.hour not in spec["hour"]:
        return False
    if when.month not in spec["month"]:
        return False
    dom_ok = when.day in spec["dom"]
    dow_ok = (when.weekday() + 1) % 7 in spec["dow"]      # Monday=0 -> cron Sunday=0
    if spec["dom_restricted"] and spec["dow_restricted"]:
        return dom_ok or dow_ok                            # cron's OR rule
    if spec["dom_restricted"]:
        return dom_ok
    if spec["dow_restricted"]:
        return dow_ok
    return True


def next_runs(expression, after=None, count=1):
    """
    The next `count` times this fires, strictly after `after`.

    Walks forward but skips whole months, days and hours that cannot match, so a
    once-a-year expression costs about the same as a daily one.
    """
    spec = parse(expression)
    cursor = (after or datetime.now()).replace(second=0, microsecond=0) + timedelta(minutes=1)
    limit = cursor + timedelta(days=366 * MAX_YEARS)
    found = []
    while len(found) < count and cursor < limit:
        if cursor.month not in spec["month"]:
            cursor = _start_of_next_month(cursor)
            continue
        dom_ok = cursor.day in spec["dom"]
        dow_ok = (cursor.weekday() + 1) % 7 in spec["dow"]
        day_ok = (dom_ok or dow_ok) if (spec["dom_restricted"] and spec["dow_restricted"]) \
            else (dom_ok if spec["dom_restricted"] else (dow_ok if spec["dow_restricted"] else True))
        if not day_ok:
            cursor = (cursor + timedelta(days=1)).replace(hour=0, minute=0)
            continue
        if cursor.hour not in spec["hour"]:
            cursor = (cursor + timedelta(hours=1)).replace(minute=0)
            continue
        if cursor.minute not in spec["minute"]:
            cursor += timedelta(minutes=1)
            continue
        found.append(cursor)
        cursor += timedelta(minutes=1)
    return found


def _start_of_next_month(when):
    year, month = (when.year + 1, 1) if when.month == 12 else (when.year, when.month + 1)
    return datetime(year, month, 1)


# ------------------------------------------------------------------- wording

def _field_words(raw, field):
    """A readable rendering of one field, or None when it is unrestricted."""
    text = raw.strip()
    if text == "*":
        return None
    spec = _parse_field(text, field)
    values = sorted(spec)
    if field == "dow":
        return _join([DAY_FULL[v] for v in values])
    if field == "month":
        return _join([MONTH_FULL[v - 1] for v in values])
    if field == "dom":
        return _join([_ordinal(v) for v in values])
    return _join([str(v) for v in values])


def _contiguous(values):
    values = sorted(values)
    return values == list(range(values[0], values[-1] + 1))


def _join(items):
    """Truncates honestly: the count is of what is actually left out."""
    items = list(items)
    if len(items) == 1:
        return items[0]
    if len(items) == 2:
        return "%s and %s" % tuple(items)
    if len(items) > 5:
        return "%s and %d more" % (", ".join(items[:4]), len(items) - 4)
    return "%s and %s" % (", ".join(items[:-1]), items[-1])


def _ordinal(n):
    if 10 <= n % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return "%d%s" % (n, suffix)


def describe(expression):
    """A sentence a person can check against what they meant."""
    parts = str(expression or "").split()
    if len(parts) != 5:
        raise CronError("a cron expression needs 5 fields, got %d" % len(parts))
    minute, hour, dom, month, dow = parts
    spec = parse(expression)

    # How often within a day.
    if minute.startswith("*/") and hour == "*":
        when = "every %s minutes" % minute[2:]
    elif minute == "*" and hour == "*":
        when = "every minute"
    elif hour == "*":
        when = "every hour at minute %s" % _field_words(minute, "minute")
    elif minute.startswith("*/") and _contiguous(spec["hour"]) and len(spec["hour"]) > 1:
        lo, hi = min(spec["hour"]), max(spec["hour"])
        when = "every %s minutes between %02d:00 and %02d:59" % (minute[2:], lo, hi)
    elif len(spec["minute"]) == 1 and _contiguous(spec["hour"]) and len(spec["hour"]) > 2:
        # An hour range reads as a window, not as a list of eleven times.
        lo, hi = min(spec["hour"]), max(spec["hour"])
        m = next(iter(spec["minute"]))
        when = ("every hour between %02d:%02d and %02d:%02d" % (lo, m, hi, m)) if m == 0 else \
               ("every hour between %02d:%02d and %02d:%02d" % (lo, m, hi, m))
    elif len(spec["hour"]) > 1 or len(spec["minute"]) > 1:
        when = "at %s" % _join(["%02d:%02d" % (h, m) for h in sorted(spec["hour"])
                                for m in sorted(spec["minute"])])
    else:
        when = "at %02d:%02d" % (next(iter(spec["hour"])), next(iter(spec["minute"])))

    days = []
    if dow.strip() != "*":
        days.append("on %s" % _field_words(dow, "dow"))
    if dom.strip() != "*":
        days.append("on the %s" % _field_words(dom, "dom"))
    if dow.strip() != "*" and dom.strip() != "*":
        joined = "%s — whichever comes first, which is how cron reads it" % " or ".join(days)
    elif days:
        joined = days[0]
    else:
        joined = "every day"

    months = ""
    if month.strip() != "*":
        months = " in %s" % _field_words(month, "month")

    return "%s, %s%s" % (when[0].upper() + when[1:], joined, months)
