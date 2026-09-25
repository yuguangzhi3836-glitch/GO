"""Strict wire timestamps: UTC seconds, never local-time interpretation."""
import datetime as dt
import re

from acceptance_gate import Refusal


def utc_epoch(value, reason):
    if type(value) is not str or not re.fullmatch(
            r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z", value):
        raise Refusal(reason)
    try:
        return int(dt.datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
                   .replace(tzinfo=dt.timezone.utc).timestamp())
    except (ValueError, OverflowError, OSError) as exc:
        raise Refusal(reason) from exc
