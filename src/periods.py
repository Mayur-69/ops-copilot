from __future__ import annotations

import calendar
import re
from dataclasses import dataclass
from datetime import date, timedelta

PERIOD_CHOICES = [
    "last_7_days",
    "last_30_days",
    "last_90_days",
    "last_12_months",
    "this_month",
    "last_month",
    "ytd",
    "all_time",
]
MONTH_PATTERN = re.compile(r"^(\d{4})-(0[1-9]|1[0-2])$")


class PeriodError(ValueError):
    pass


@dataclass(frozen=True)
class Period:
    label: str
    start: date | None
    end: date


def resolve_period(period: str, as_of: date) -> Period:
    value = (period or "").strip().lower()
    if value == "last_7_days":
        return Period(value, as_of - timedelta(days=6), as_of)
    if value == "last_30_days":
        return Period(value, as_of - timedelta(days=29), as_of)
    if value == "last_90_days":
        return Period(value, as_of - timedelta(days=89), as_of)
    if value == "last_12_months":
        return Period(value, as_of - timedelta(days=364), as_of)
    if value == "this_month":
        return Period(value, as_of.replace(day=1), as_of)
    if value == "last_month":
        first_this_month = as_of.replace(day=1)
        last_month_end = first_this_month - timedelta(days=1)
        return Period(value, last_month_end.replace(day=1), last_month_end)
    if value == "ytd":
        return Period(value, date(as_of.year, 1, 1), as_of)
    if value == "all_time":
        return Period(value, None, as_of)
    month_match = MONTH_PATTERN.match(value)
    if month_match:
        year = int(month_match.group(1))
        month = int(month_match.group(2))
        last_day = calendar.monthrange(year, month)[1]
        start = date(year, month, 1)
        end = min(as_of, date(year, month, last_day))
        if start > as_of:
            raise PeriodError(f"Period {value} is after the data as-of date {as_of.isoformat()}.")
        return Period(value, start, end)
    raise PeriodError(
        "Invalid period. Use one of "
        + ", ".join(PERIOD_CHOICES)
        + ", or a calendar month in YYYY-MM format."
    )
