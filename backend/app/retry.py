"""Bounded retries with exponential backoff for transient failures."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import TypeVar

from .errors import AppError, ErrorCode

log = logging.getLogger(__name__)
T = TypeVar("T")

TRANSIENT = frozenset({ErrorCode.NETWORK_ERROR, ErrorCode.TIMEOUT})


def with_retries(
    fn: Callable[[], T],
    *,
    what: str,
    attempts: int = 3,
    base_delay: float = 1.0,
    retry_on: frozenset[ErrorCode] = TRANSIENT,
    sleep: Callable[[float], None] = time.sleep,
) -> T:
    """Call ``fn``; retry only ``retry_on`` errors, at most ``attempts`` times in total.

    Delays are ``base_delay``, ``2*base_delay``, ... The final error is re-raised
    unchanged (original cause preserved), never swallowed or replaced.
    """
    for attempt in range(1, attempts + 1):
        try:
            return fn()
        except AppError as exc:
            if exc.code not in retry_on or attempt == attempts:
                raise
            delay = base_delay * (2 ** (attempt - 1))
            log.info("%s failed (%s: %s); retry %d/%d in %.1fs", what, exc.code.value, exc.message,
                     attempt, attempts - 1, delay)
            sleep(delay)
    raise AssertionError("unreachable")  # pragma: no cover
