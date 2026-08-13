"""Typed objects returned by the client.

Everything here is a plain frozen dataclass built from the API's JSON. Each one
keeps a ``raw`` copy of the payload it was parsed from, so a field this library
does not know about yet is never lost.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Iterator, List, Mapping, Optional, Sequence, Union

from .errors import XQLError, XQLPlanError, XQLSyntaxError

__all__ = [
    "Position",
    "XQLErrorDetail",
    "ValidationResult",
    "Source",
    "Plan",
    "Explanation",
    "Match",
    "ResultSet",
    "Quota",
    "RateLimit",
]


def _parse_timestamp(value: Any) -> Optional[datetime]:
    """Accept an ISO-8601 string or epoch seconds, return an aware datetime."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, tz=timezone.utc)
    if isinstance(value, str):
        text = value.strip()
        if text.isdigit():
            return datetime.fromtimestamp(int(text), tz=timezone.utc)
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    return None


@dataclass(frozen=True)
class Position:
    """1-based line and column, plus a 0-based character offset."""

    line: int
    column: int
    offset: int

    @classmethod
    def from_json(cls, data: Optional[Mapping[str, Any]]) -> Optional["Position"]:
        if not data:
            return None
        return cls(
            line=int(data.get("line", 0)),
            column=int(data.get("column", 0)),
            offset=int(data.get("offset", 0)),
        )


@dataclass(frozen=True)
class XQLErrorDetail:
    """The ``error`` object from a 400 response.

    ``position`` is present for ``type == "syntax"`` and absent for
    ``type == "plan"``.
    """

    type: str
    message: str
    position: Optional[Position] = None
    raw: Mapping[str, Any] = field(default_factory=dict, repr=False)

    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> "XQLErrorDetail":
        return cls(
            type=str(data.get("type", "unknown")),
            message=str(data.get("message", "")),
            position=Position.from_json(data.get("position")),
            raw=dict(data),
        )

    def to_exception(self, query: Optional[str] = None) -> XQLError:
        """Build the matching exception, without raising it."""
        if self.type == "syntax":
            pos = self.position
            return XQLSyntaxError(
                self.message,
                line=pos.line if pos else None,
                column=pos.column if pos else None,
                offset=pos.offset if pos else None,
                query=query,
                status_code=400,
            )
        if self.type == "plan":
            return XQLPlanError(self.message, query=query, status_code=400)
        return XQLError(self.message, query=query, status_code=400)


@dataclass(frozen=True)
class ValidationResult:
    """Outcome of ``/xql/validate``.

    A failed validation is a *normal outcome* here, not an exception: checking
    is the entire point of the call. The object is falsy when the query is
    invalid, so ``if not xc.validate(q): ...`` reads correctly. Call
    :meth:`raise_for_error` if you would rather have the exception.
    """

    valid: bool
    error: Optional[XQLErrorDetail] = None
    query: Optional[str] = field(default=None, repr=False)

    def __bool__(self) -> bool:
        return self.valid

    @property
    def message(self) -> Optional[str]:
        """The raw error message from the API, unparaphrased."""
        return self.error.message if self.error else None

    def raise_for_error(self) -> "ValidationResult":
        """Raise the matching :class:`XQLError` if invalid, else return self."""
        if not self.valid and self.error is not None:
            raise self.error.to_exception(self.query)
        return self


@dataclass(frozen=True)
class Source:
    """One timeframe's data requirement, as reported by the planner."""

    timeframe: str
    series: List[str]
    min_lookback: int

    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> "Source":
        return cls(
            timeframe=str(data.get("timeframe", "")),
            series=list(data.get("series", [])),
            min_lookback=int(data.get("minLookback", 0)),
        )


@dataclass(frozen=True)
class Plan:
    """The data-requirements manifest for a query."""

    market: str
    sources: List[Source]
    raw: Mapping[str, Any] = field(default_factory=dict, repr=False)

    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> "Plan":
        return cls(
            market=str(data.get("market", "")),
            sources=[Source.from_json(s) for s in data.get("sources", [])],
            raw=dict(data),
        )

    @property
    def timeframes(self) -> List[str]:
        return [s.timeframe for s in self.sources]

    @property
    def max_lookback(self) -> int:
        """Largest bar requirement across sources. The 300-bar ceiling applies
        per timeframe, so this is a headroom indicator, not the check itself."""
        return max((s.min_lookback for s in self.sources), default=0)


@dataclass(frozen=True)
class Explanation:
    """Outcome of ``/xql/explain``: the plan plus a mechanical description.

    ``explanation`` renders the query back in near-XQL prose (for example
    "Matches when rsi(14) < 30"). It is a sanity check on what the query does,
    not a trader-facing translation.
    """

    plan: Plan
    explanation: str
    raw: Mapping[str, Any] = field(default_factory=dict, repr=False)

    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> "Explanation":
        return cls(
            plan=Plan.from_json(data.get("plan", {})),
            explanation=str(data.get("explanation", "")),
            raw=dict(data),
        )

    def __str__(self) -> str:
        return self.explanation


#: Anything usable as a column key: the literal string the API returns, or a
#: future expression object that renders to it.
ColumnKey = Union[str, Any]


def _column_key(key: ColumnKey) -> str:
    """Normalise a column key.

    The API keys ``columns`` by the literal expression text (``"rsi(14)"``), so
    an expression object only has to render canonically for ``match[rsi(14)]``
    to resolve. That is what makes a DSL layer worth building later.
    """
    if isinstance(key, str):
        return key
    to_xql = getattr(key, "to_xql", None)
    if callable(to_xql):
        return str(to_xql())
    return str(key)


@dataclass(frozen=True)
class Match:
    """One instrument that satisfied the query."""

    symbol: str
    columns: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> "Match":
        return cls(
            symbol=str(data.get("symbol", "")),
            columns=dict(data.get("columns", {}) or {}),
        )

    def __getitem__(self, key: ColumnKey) -> Any:
        name = _column_key(key)
        try:
            return self.columns[name]
        except KeyError:
            available = ", ".join(sorted(self.columns)) or "none"
            raise KeyError(
                f"{name!r} was not returned for {self.symbol}. "
                f"Columns present: {available}. "
                f"Remember that a condition's own inputs are not surfaced "
                f"automatically: add the expression to the query's `columns` "
                f"pragma to get it back."
            ) from None

    def get(self, key: ColumnKey, default: Any = None) -> Any:
        return self.columns.get(_column_key(key), default)

    def __contains__(self, key: ColumnKey) -> bool:
        return _column_key(key) in self.columns


class ResultSet(Sequence[Match]):
    """Outcome of ``/xql/run``: an ordered sequence of matches.

    Order is meaningful. It reflects the query's own ``sort`` and ``limit``, or
    scan order when the query omits ``sort``. An empty result set means the
    query is valid and nothing currently matches, which is not an error.
    """

    __slots__ = ("_matches", "raw")

    def __init__(
        self,
        matches: Sequence[Match],
        raw: Optional[Mapping[str, Any]] = None,
    ) -> None:
        self._matches: List[Match] = list(matches)
        self.raw: Mapping[str, Any] = raw or {}

    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> "ResultSet":
        return cls(
            [Match.from_json(m) for m in data.get("results", []) or []],
            raw=dict(data),
        )

    def __len__(self) -> int:
        return len(self._matches)

    def __getitem__(self, index: Union[int, slice]) -> Any:
        if isinstance(index, slice):
            return ResultSet(self._matches[index], raw=self.raw)
        return self._matches[index]

    def __iter__(self) -> Iterator[Match]:
        return iter(self._matches)

    def __repr__(self) -> str:
        return f"ResultSet({len(self)} matches: {', '.join(self.symbols[:5])})"

    @property
    def symbols(self) -> List[str]:
        return [m.symbol for m in self._matches]

    @property
    def column_names(self) -> List[str]:
        """Column keys present, in first-match order."""
        return list(self._matches[0].columns) if self._matches else []

    def column(self, key: ColumnKey) -> List[Any]:
        """One column's values across every match, in result order."""
        name = _column_key(key)
        return [m.columns.get(name) for m in self._matches]

    def to_dicts(self) -> List[Dict[str, Any]]:
        return [{"symbol": m.symbol, **m.columns} for m in self._matches]

    def to_pandas(self) -> Any:
        """Return a DataFrame indexed by symbol. Requires the ``pandas`` extra."""
        try:
            import pandas as pd
        except ImportError as exc:  # pragma: no cover
            raise ImportError(
                "to_pandas() needs pandas: pip install 'xcreener[pandas]'"
            ) from exc
        frame = pd.DataFrame(self.to_dicts())
        return frame.set_index("symbol") if not frame.empty else frame


@dataclass(frozen=True)
class Quota:
    """Outcome of ``GET /usage``. Free to call, and works at 429."""

    tier: str
    limit: int
    used: int
    remaining: int
    reset_at: Optional[datetime] = None
    raw: Mapping[str, Any] = field(default_factory=dict, repr=False)

    @classmethod
    def from_json(cls, data: Mapping[str, Any]) -> "Quota":
        return cls(
            tier=str(data.get("tier", "")),
            limit=int(data.get("limit", 0)),
            used=int(data.get("used", 0)),
            remaining=int(data.get("remaining", 0)),
            reset_at=_parse_timestamp(data.get("resetAt")),
            raw=dict(data),
        )

    @property
    def exhausted(self) -> bool:
        return self.remaining <= 0

    @property
    def fraction_used(self) -> float:
        return self.used / self.limit if self.limit else 0.0


@dataclass(frozen=True)
class RateLimit:
    """Quota state scraped from the headers on the last ``/xql/run`` response.

    Cheaper than a ``/usage`` call, because every run already carries it.
    """

    remaining: Optional[int] = None
    reset_at: Optional[datetime] = None

    @classmethod
    def from_headers(cls, headers: Mapping[str, str]) -> Optional["RateLimit"]:
        lookup = {k.lower(): v for k, v in headers.items()}
        remaining = lookup.get("x-ratelimit-remaining")
        reset = lookup.get("x-ratelimit-reset")
        if remaining is None and reset is None:
            return None
        parsed_remaining: Optional[int]
        try:
            parsed_remaining = int(remaining) if remaining is not None else None
        except ValueError:
            parsed_remaining = None
        return cls(remaining=parsed_remaining, reset_at=_parse_timestamp(reset))
