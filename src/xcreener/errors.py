"""Exception hierarchy for the XCREENER client.

Two families live here, and they are deliberately different animals:

* ``XQLError`` and subclasses mean *your query is wrong*. Never retryable.
* ``QuotaExceeded`` / ``AuthenticationError`` mean *your account is wrong*.
  Never retryable either, but for entirely different reasons.
* ``UpstreamError`` / ``TransportError`` mean *we are wrong*. Retryable, and
  the client already retried before raising.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Optional

__all__ = [
    "XcreenerError",
    "AuthenticationError",
    "QuotaExceeded",
    "XQLError",
    "XQLSyntaxError",
    "XQLPlanError",
    "UpstreamError",
    "TransportError",
]


class XcreenerError(Exception):
    """Base class for everything this library raises."""

    def __init__(self, message: str, *, status_code: Optional[int] = None) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


class AuthenticationError(XcreenerError):
    """401. Missing, malformed, or unrecognized API key.

    Rejected before parse/plan logic runs, so this says nothing about whether
    your query is valid. Note that regenerating a key invalidates the old one
    everywhere it is in use.
    """


class QuotaExceeded(XcreenerError):
    """429. The daily ``/xql/run`` quota for this subscription tier is spent.

    ``validate`` and ``explain`` keep working: they are never metered. So a
    reasonable reaction to this is to keep iterating on the query for free and
    schedule the run for after :attr:`reset_at`.
    """

    def __init__(
        self,
        message: str,
        *,
        status_code: Optional[int] = None,
        tier: Optional[str] = None,
        limit: Optional[int] = None,
        reset_at: Optional[datetime] = None,
    ) -> None:
        super().__init__(message, status_code=status_code)
        self.tier = tier
        self.limit = limit
        self.reset_at = reset_at

    def __str__(self) -> str:
        if self.reset_at is not None:
            return f"{self.message} (quota resets at {self.reset_at.isoformat()})"
        return self.message


class XQLError(XcreenerError):
    """400. The query did not parse or did not plan. No data was fetched."""

    #: ``"syntax"`` or ``"plan"``, straight from the API.
    error_type = "unknown"

    def __init__(
        self,
        message: str,
        *,
        query: Optional[str] = None,
        status_code: Optional[int] = None,
    ) -> None:
        super().__init__(message, status_code=status_code)
        self.query = query


class XQLSyntaxError(XQLError):
    """A parse-time failure. Carries a 1-based line/column and a byte offset."""

    error_type = "syntax"

    def __init__(
        self,
        message: str,
        *,
        line: Optional[int] = None,
        column: Optional[int] = None,
        offset: Optional[int] = None,
        query: Optional[str] = None,
        status_code: Optional[int] = None,
    ) -> None:
        super().__init__(message, query=query, status_code=status_code)
        self.line = line
        self.column = column
        self.offset = offset

    def __str__(self) -> str:
        if self.line is None:
            return self.message
        head = f"line {self.line}, column {self.column}: {self.message}"
        excerpt = self._excerpt()
        return f"{head}\n\n{excerpt}" if excerpt else head

    def _excerpt(self) -> Optional[str]:
        """Render the offending line with a caret under the reported column."""
        if not self.query or self.line is None or self.column is None:
            return None
        lines = self.query.splitlines()
        if not (1 <= self.line <= len(lines)):
            return None
        source = lines[self.line - 1]
        # Tabs would desynchronise the caret, so normalise them first.
        source = source.replace("\t", "    ")
        caret_col = max(self.column - 1, 0)
        return f"    {source}\n    {' ' * caret_col}^"


class XQLPlanError(XQLError):
    """A plan-time failure. The query parsed but cannot be executed as written.

    The common case by far is the 300-bar lookback ceiling, in which case
    :attr:`required_bars`, :attr:`max_bars` and :attr:`timeframe` are populated
    so callers can react programmatically instead of matching on the message.
    """

    error_type = "plan"

    _LOOKBACK_RE = re.compile(
        r"requires (?P<required>\d+) bars? of history for (?P<timeframe>\w+), "
        r"exceeding the maximum of (?P<maximum>\d+)"
    )

    def __init__(
        self,
        message: str,
        *,
        query: Optional[str] = None,
        status_code: Optional[int] = None,
    ) -> None:
        super().__init__(message, query=query, status_code=status_code)
        self.required_bars: Optional[int] = None
        self.max_bars: Optional[int] = None
        self.timeframe: Optional[str] = None

        match = self._LOOKBACK_RE.search(message)
        if match:
            self.required_bars = int(match.group("required"))
            self.max_bars = int(match.group("maximum"))
            self.timeframe = match.group("timeframe")

    @property
    def is_lookback_ceiling(self) -> bool:
        """True when this is specifically the 300-bar ceiling rejection."""
        return self.required_bars is not None


class UpstreamError(XcreenerError):
    """5xx. The query parsed and planned, but the server could not serve it.

    Typically a database connection failure behind ``/xql/run``. The client
    retries these before raising, so seeing one means the retries ran out.
    """


class TransportError(XcreenerError):
    """The request never completed: DNS, TLS, connection reset, timeout."""
