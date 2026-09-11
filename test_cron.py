#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_cron.py — the cron parser, its wording, and when it says things fire.

This is the piece the whole schedule rests on: if next_runs lies, the UI shows a
time that never happens. So it is tested on its own, hard.

    python3 test_cron.py
"""

import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cron                                                      # noqa: E402

failures = []


def check(name, condition, detail=""):
    print("  %s %s%s" % ("PASS" if condition else "FAIL", name,
                         "" if condition else "  <- " + str(detail)[:200]))
    if not condition:
        failures.append(name)


def nxt(expr, when, count=1):
    return [d.strftime("%Y-%m-%d %H:%M") for d in cron.next_runs(expr, when, count)]


def main():
    now = datetime(2026, 9, 11, 12, 30)          # a Friday

    print("\n[1] Field syntax")
    cases = [
        ("* * * * *", True), ("40 7 * * *", True), ("*/15 * * * *", True),
        ("0 9-19 * * *", True), ("0 9,13,17 * * *", True), ("0 9 * * MON-FRI", True),
        ("0 0 1 JAN *", True), ("0 0 * * 7", True), ("10-50/10 * * * *", True),
        ("", False), ("* * * *", False), ("* * * * * *", False),
        ("60 * * * *", False), ("* 24 * * *", False), ("0 0 32 * *", False),
        ("0 0 * 13 *", False), ("0 0 * * 8", False), ("abc * * * *", False),
        ("*/0 * * * *", False), ("5-1 * * * *", False),
    ]
    for expr, valid in cases:
        try:
            cron.parse(expr)
            ok = valid
            why = ""
        except cron.CronError as ex:
            ok = not valid
            why = str(ex)
        check("%s %r" % ("accepts" if valid else "rejects", expr), ok, why)

    print("\n[2] Sunday is both 0 and 7")
    check("0 and 7 parse to the same set",
          cron.parse("0 0 * * 0")["dow"] == cron.parse("0 0 * * 7")["dow"])

    print("\n[3] Next run times")
    check("daily, later today", nxt("40 13 * * *", now) == ["2026-09-11 13:40"])
    check("daily, already passed today rolls over",
          nxt("40 7 * * *", now) == ["2026-09-12 07:40"])
    check("step within the hour", nxt("*/15 * * * *", now, 3) ==
          ["2026-09-11 12:45", "2026-09-11 13:00", "2026-09-11 13:15"])
    check("hour window picks the next hour",
          nxt("0 9-19 * * *", now) == ["2026-09-11 13:00"])
    check("hour window before it opens",
          nxt("0 9-19 * * *", datetime(2026, 9, 11, 6, 5)) == ["2026-09-11 09:00"])
    check("hour window after it closes",
          nxt("0 9-19 * * *", datetime(2026, 9, 11, 21, 5)) == ["2026-09-12 09:00"])
    check("weekly on named days", nxt("0 9 * * MON,THU", now, 2) ==
          ["2026-09-14 09:00", "2026-09-17 09:00"])
    check("weekdays only skips the weekend",
          nxt("0 9 * * MON-FRI", datetime(2026, 9, 11, 10, 0)) == ["2026-09-14 09:00"])
    check("monthly on a day of month", nxt("30 6 1 * *", now, 2) ==
          ["2026-10-01 06:30", "2026-11-01 06:30"])
    check("yearly", nxt("0 0 1 1 *", now) == ["2027-01-01 00:00"])
    check("quarterly", nxt("0 0 1 */3 *", now, 2) == ["2026-10-01 00:00", "2027-01-01 00:00"])
    check("a month that is months away",
          nxt("0 8 * JUL *", now) == ["2027-07-01 08:00"])

    print("\n[4] Strictly in the future")
    check("a run happening exactly now is not 'next'",
          nxt("30 12 * * *", datetime(2026, 9, 11, 12, 30)) == ["2026-09-12 12:30"])
    check("one minute before, it is next",
          nxt("30 12 * * *", datetime(2026, 9, 11, 12, 29)) == ["2026-09-11 12:30"])
    check("seconds are ignored",
          nxt("30 12 * * *", datetime(2026, 9, 11, 12, 29, 59)) == ["2026-09-11 12:30"])

    print("\n[5] The day-of-month / day-of-week OR rule")
    # Sep 2026: the 1st is a Tuesday. Wednesdays are 2, 9, 16...
    both = nxt("0 0 1 * WED", datetime(2026, 9, 1, 12, 0), 3)
    check("fires on either, not both", both == ["2026-09-02 00:00", "2026-09-09 00:00",
                                                "2026-09-16 00:00"], both)
    check("and the 1st of next month is in there",
          "2026-10-01 00:00" in nxt("0 0 1 * WED", datetime(2026, 9, 20, 0, 0), 4))
    only_dom = nxt("0 0 1 * *", datetime(2026, 9, 2, 0, 0))
    check("day-of-month alone means only that day", only_dom == ["2026-10-01 00:00"], only_dom)

    print("\n[6] Leap day, month ends, and year rollover")
    check("Feb 29 skips to the next leap year",
          nxt("0 0 29 2 *", datetime(2026, 3, 1, 0, 0)) == ["2028-02-29 00:00"])
    check("the 31st skips short months", nxt("0 0 31 * *", datetime(2026, 9, 30, 0, 0), 2) ==
          ["2026-10-31 00:00", "2026-12-31 00:00"])
    check("new year rollover",
          nxt("0 0 * * *", datetime(2026, 12, 31, 12, 0)) == ["2027-01-01 00:00"])

    print("\n[7] Wording a person can check")
    wording = [
        ("40 7 * * *", "At 07:40, every day"),
        ("*/15 * * * *", "Every 15 minutes, every day"),
        ("0 9-19 * * *", "Every hour between 09:00 and 19:00, every day"),
        ("0 9 * * MON,THU", "At 09:00, on Monday and Thursday"),
        ("30 6 1 * *", "At 06:30, on the 1st"),
        ("0 0 1 1 *", "At 00:00, on the 1st in January"),
        ("30 8,17 * * *", "At 08:30 and 17:30, every day"),
    ]
    for expr, expected in wording:
        got = cron.describe(expr)
        check("%r reads as expected" % expr, got == expected, got)
    check("the OR rule is spelled out, not hidden",
          "whichever comes first" in cron.describe("0 0 1 * WED"),
          cron.describe("0 0 1 * WED"))
    check("a step inside a window reads as a window",
          cron.describe("*/30 9-17 * * *")
          == "Every 30 minutes between 09:00 and 17:59, every day",
          cron.describe("*/30 9-17 * * *"))
    # Six scattered hours can only be listed, and the count must be honest.
    listed = cron.describe("0 1,3,5,7,9,11 * * *")
    check("a truncated list counts what it left out honestly",
          "and 2 more" in listed and listed.count(":00") == 4, listed)

    print("\n[8] Errors say what to fix")
    for expr, needle in [("* * * *", "5 fields"), ("60 * * * *", "minute"),
                         ("0 0 32 * *", "dom"), ("0 0 * * 8", "dow"),
                         ("5-1 * * * *", "backwards")]:
        try:
            cron.parse(expr)
            check("%r explains itself" % expr, False, "no error raised")
        except cron.CronError as ex:
            check("%r explains itself" % expr, needle in str(ex), str(ex))

    print("\n%s" % ("ALL CRON TESTS PASSED" if not failures
                    else "FAILED: " + ", ".join(failures)))
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
