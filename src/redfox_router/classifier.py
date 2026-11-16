"""Normalize upstream outcomes into a small failure enum for routing + logging."""
from __future__ import annotations

OK = "ok"
AUTH = "auth"
RATE_LIMIT = "rate_limit"
QUOTA_EXHAUSTED = "quota_exhausted"
TIMEOUT = "timeout"
CONNECTION_DROPPED = "connection_dropped"
MODEL_UNAVAILABLE = "model_unavailable"
UPSTREAM_5XX = "upstream_5xx"
INVALID_REQUEST = "invalid_request"
UNKNOWN = "unknown"

# Failure classes that should trigger a rotation to the next backend.
FAILOVER = frozenset({RATE_LIMIT, QUOTA_EXHAUSTED, TIMEOUT, CONNECTION_DROPPED,
                      UPSTREAM_5XX, MODEL_UNAVAILABLE})

_QUOTA_HINTS = ("insufficient_quota", "quota", "budget", "free_quota",
                "insufficient balance", "insufficient funds", "no active plan",
                "credit")


def classify_status(status: int, body: str = "") -> str:
    if status == 200:
        return OK
    if status in (401, 403):
        return AUTH
    if status == 429:
        return RATE_LIMIT
    if status == 404:
        return MODEL_UNAVAILABLE
    if status == 402:
        return QUOTA_EXHAUSTED
    if 500 <= status < 600:
        return UPSTREAM_5XX
    if 400 <= status < 500:
        low = body.lower()
        if any(h in low for h in _QUOTA_HINTS):
            return QUOTA_EXHAUSTED
        return INVALID_REQUEST
    return UNKNOWN


def classify_exception(exc: BaseException) -> str:
    name = type(exc).__name__.lower()
    if "timeout" in name:
        return TIMEOUT
    if "connect" in name or "read" in name or "protocol" in name:
        return CONNECTION_DROPPED
    return UNKNOWN


def should_failover(failure_class: str) -> bool:
    return failure_class in FAILOVER
