"""The synchronous XCREENER client."""

from __future__ import annotations

import os
import random
import time
from typing import Any, Callable, Dict, Mapping, Optional, Union

import httpx

from ._version import __version__
from .errors import (
    AuthenticationError,
    QuotaExceeded,
    TransportError,
    UpstreamError,
    XcreenerError,
    XQLError,
)
from .models import (
    Explanation,
    Quota,
    RateLimit,
    ResultSet,
    ValidationResult,
    XQLErrorDetail,
)

__all__ = ["Xcreener", "DEFAULT_BASE_URL"]

DEFAULT_BASE_URL = "https://api.xcreener.com"
DEFAULT_TIMEOUT = 30.0
DEFAULT_MAX_RETRIES = 2
_USER_AGENT = f"xcreener-sdk-python/{__version__}"

#: The key itself, or a zero-argument callable returning one. The callable
#: form is resolved on every request, which is what makes rotation possible
#: without rebuilding the client: point it at your secret manager.
ApiKeyLike = Union[str, Callable[[], str]]

#: A query is either raw XQL text, or any object that renders itself to XQL.
#: The second case is what a future expression/builder layer plugs into: it
#: only has to grow a ``to_xql()`` method, and this client keeps working.
QueryLike = Union[str, Any]


def _normalize_api_key(value: str) -> str:
    """Trim and sanity-check a key before it reaches an HTTP header.

    The raw key is shown exactly once at generation time, so it is almost
    always pasted, and a pasted key routinely carries a trailing newline. Sent
    verbatim that produces an ordinary 401, which reads as "my key is wrong"
    and tempts the user to regenerate: that invalidates the working key
    everywhere it is in use, including their MCP config. Catching the
    whitespace here turns a costly misdiagnosis into an obvious message.
    """
    key = value.strip()
    if not key:
        raise ValueError("API key is empty")
    if any(not (32 < ord(ch) < 127) for ch in key):
        raise ValueError(
            "API key contains whitespace or non-printable characters. If you "
            "pasted it, check for a stray newline or space. This is a "
            "formatting problem, not a rejected key: you do not need to "
            "regenerate it."
        )
    return key


def _to_xql(query: QueryLike) -> str:
    if isinstance(query, str):
        text = query
    else:
        renderer: Optional[Callable[[], str]] = getattr(query, "to_xql", None)
        if not callable(renderer):
            raise TypeError(
                f"Expected XQL text or an object with .to_xql(), got "
                f"{type(query).__name__}"
            )
        text = renderer()
    text = text.strip()
    if not text:
        raise ValueError("Query is empty")
    return text


class Xcreener:
    """Client for the XCREENER HTTP API.

    All three XQL endpoints read the query from the raw request body as plain
    text, so this client never JSON-wraps it.

    ``validate`` and ``explain`` are unmetered and only ``run`` counts against
    the daily quota. That asymmetry shows up in the API here: ``validate`` and
    ``explain`` are cheap enough to call in a loop while iterating, and
    ``run(precheck=True)`` converts a doomed metered call into a free one.

        >>> xc = Xcreener()                      # reads XCREENER_API_KEY
        >>> xc.validate('market = "CRYPTO"\\ntimeframe = h1\\nrsi(14) < 30')
        ValidationResult(valid=True, error=None)

    :param api_key: The key, or a zero-argument callable returning one.
        Falls back to ``$XCREENER_API_KEY``. Nothing is written to disk: where
        the key lives is your call, not this library's.
    :param base_url: Override for testing or a self-hosted proxy.
    :param timeout: Per-request timeout in seconds.
    :param max_retries: Retries for 5xx and transport failures only. Never for
        400, 401 or 429, which will not change on a retry.
    :param precheck: Default for :meth:`run`. When true, every run is preceded
        by a free ``validate`` call so a malformed query raises before any
        quota is spent. Costs a round trip, spends nothing.
    :param transport: An ``httpx.Client`` to use instead of the built-in one.
    """

    def __init__(
        self,
        api_key: Optional[ApiKeyLike] = None,
        *,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = DEFAULT_TIMEOUT,
        max_retries: int = DEFAULT_MAX_RETRIES,
        precheck: bool = False,
        transport: Optional[httpx.Client] = None,
    ) -> None:
        if callable(api_key):
            # Resolved per request, so a rotated key is picked up without
            # rebuilding the client. Deliberately not called here: a provider
            # backed by a secret manager should not be hit an extra time at
            # construction, and it may not be ready yet.
            self._api_key_provider: Callable[[], str] = api_key
        else:
            key = api_key or os.environ.get("XCREENER_API_KEY")
            if not key:
                raise ValueError(
                    "No API key. Pass api_key= or set XCREENER_API_KEY. "
                    "Generate one at https://xcreener.com/account/api-key "
                    "(the raw key is shown only once)."
                )
            checked = _normalize_api_key(key)
            self._api_key_provider = lambda k=checked: k  # type: ignore[misc]
        self.base_url = base_url.rstrip("/")
        self.max_retries = max_retries
        self.precheck = precheck
        self._rate_limit: Optional[RateLimit] = None
        self._owns_transport = transport is None
        self._http = transport or httpx.Client(timeout=timeout)

    # ------------------------------------------------------------------
    # Endpoints
    # ------------------------------------------------------------------

    def validate(self, query: QueryLike) -> ValidationResult:
        """``POST /xql/validate``. Parse and plan without touching data.

        Unmetered, and works on any recognized key including free tier. An
        invalid query comes back as a falsy :class:`ValidationResult` rather
        than an exception, since checking is the point of the call.
        """
        text = _to_xql(query)
        response = self._request("POST", "/xql/validate", body=text)

        if response.status_code == 400:
            detail = self._error_detail(response)
            if detail is not None:
                return ValidationResult(valid=False, error=detail, query=text)

        self._raise_for_status(response, query=text)
        payload = self._json(response)
        return ValidationResult(
            valid=bool(payload.get("valid", True)), error=None, query=text
        )

    def explain(self, query: QueryLike) -> Explanation:
        """``POST /xql/explain``. Return the data plan and a description.

        Unmetered. Useful for reading ``minLookback`` per timeframe before
        committing a metered run.
        """
        text = _to_xql(query)
        response = self._request("POST", "/xql/explain", body=text)
        self._raise_for_status(response, query=text)
        return Explanation.from_json(self._json(response))

    def run(self, query: QueryLike, *, precheck: Optional[bool] = None) -> ResultSet:
        """``POST /xql/run``. Execute against live market data.

        This is the only metered endpoint. An empty :class:`ResultSet` means
        the query is valid and nothing matches right now, which is not an
        error.

        :param precheck: Overrides the client-level default. When true, a free
            ``validate`` runs first and raises on failure, so a malformed query
            costs zero quota instead of one call.
        """
        text = _to_xql(query)
        if self.precheck if precheck is None else precheck:
            self.validate(text).raise_for_error()

        response = self._request("POST", "/xql/run", body=text)
        self._capture_rate_limit(response)
        self._raise_for_status(response, query=text)
        return ResultSet.from_json(self._json(response))

    def usage(self) -> Quota:
        """``GET /usage``. Report quota state without consuming any of it.

        Safe to call as often as you like, and it still answers at 429.
        """
        response = self._request("GET", "/usage")
        self._raise_for_status(response)
        return Quota.from_json(self._json(response))

    # ------------------------------------------------------------------
    # Convenience
    # ------------------------------------------------------------------

    @property
    def rate_limit(self) -> Optional[RateLimit]:
        """Quota state from the headers of the most recent :meth:`run`.

        ``None`` until the first run. Reading this is free; polling
        :meth:`usage` for the same information is not necessary between runs.
        """
        return self._rate_limit

    def close(self) -> None:
        if self._owns_transport:
            self._http.close()

    def __enter__(self) -> "Xcreener":
        return self

    def __exit__(self, *exc_info: Any) -> None:
        self.close()

    @property
    def key_hint(self) -> str:
        """A masked form of the key, safe to log or print in a support thread.

        The full key is never exposed by this class: not through ``repr``, not
        through any exception it raises. If you need the raw value you already
        have it, because you passed it in.
        """
        key = self._resolve_key()
        return f"...{key[-4:]}" if len(key) > 8 else "..."

    def __repr__(self) -> str:
        # Deliberately excludes the key: client objects end up in tracebacks,
        # notebook output cells, and Sentry breadcrumbs.
        return f"Xcreener(base_url={self.base_url!r})"

    # ------------------------------------------------------------------
    # Transport
    # ------------------------------------------------------------------

    def _resolve_key(self) -> str:
        key = self._api_key_provider()
        if not key:
            raise ValueError("api_key provider returned an empty key")
        return _normalize_api_key(key)

    def _headers(self, *, body: bool) -> Dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self._resolve_key()}",
            "Accept": "application/json",
            "User-Agent": _USER_AGENT,
        }
        if body:
            # The endpoints read raw text, not a JSON-wrapped field.
            headers["Content-Type"] = "text/plain; charset=utf-8"
        return headers

    def _request(
        self, method: str, path: str, *, body: Optional[str] = None
    ) -> httpx.Response:
        url = f"{self.base_url}{path}"
        headers = self._headers(body=body is not None)
        last_error: Optional[Exception] = None

        for attempt in range(self.max_retries + 1):
            try:
                response = self._http.request(
                    method,
                    url,
                    headers=headers,
                    content=body.encode("utf-8") if body is not None else None,
                )
            except httpx.HTTPError as exc:
                last_error = exc
                if attempt == self.max_retries:
                    raise TransportError(f"Request to {url} failed: {exc}") from exc
                self._sleep(attempt)
                continue

            # Only server-side failures are worth retrying. A 400 will parse
            # exactly the same way next time, and a 429 will not have refilled.
            if response.status_code >= 500 and attempt < self.max_retries:
                self._sleep(attempt)
                continue
            return response

        raise TransportError(f"Request to {url} failed: {last_error}")

    @staticmethod
    def _sleep(attempt: int) -> None:
        time.sleep((2**attempt) * 0.5 + random.uniform(0, 0.25))

    def _capture_rate_limit(self, response: httpx.Response) -> None:
        parsed = RateLimit.from_headers(response.headers)
        if parsed is not None:
            self._rate_limit = parsed

    @staticmethod
    def _json(response: httpx.Response) -> Mapping[str, Any]:
        try:
            payload = response.json()
        except ValueError as exc:
            raise XcreenerError(
                f"Expected JSON, got {response.text[:200]!r}",
                status_code=response.status_code,
            ) from exc
        if not isinstance(payload, Mapping):
            raise XcreenerError(
                f"Expected a JSON object, got {type(payload).__name__}",
                status_code=response.status_code,
            )
        return payload

    @staticmethod
    def _error_detail(response: httpx.Response) -> Optional[XQLErrorDetail]:
        """Pull the ``error`` object out of a 400 body, if it is one.

        Not every error body is an object: 429 returns ``{"error": "..."}``
        with a bare string, so this returns None in that case rather than
        pretending it is an XQL error.
        """
        try:
            payload = response.json()
        except ValueError:
            return None
        if not isinstance(payload, Mapping):
            return None
        error = payload.get("error")
        return XQLErrorDetail.from_json(error) if isinstance(error, Mapping) else None

    @staticmethod
    def _error_message(response: httpx.Response, fallback: str) -> str:
        try:
            payload = response.json()
        except ValueError:
            return response.text.strip()[:200] or fallback
        if isinstance(payload, Mapping):
            error = payload.get("error")
            if isinstance(error, str):
                return error
            if isinstance(error, Mapping) and "message" in error:
                return str(error["message"])
            if isinstance(payload.get("message"), str):
                return str(payload["message"])
        return fallback

    def _raise_for_status(
        self, response: httpx.Response, *, query: Optional[str] = None
    ) -> None:
        status = response.status_code
        if status < 400:
            return

        if status == 401:
            raise AuthenticationError(
                self._error_message(
                    response,
                    "API key missing or unrecognized. Check XCREENER_API_KEY, "
                    "and note that regenerating a key invalidates the old one.",
                ),
                status_code=401,
            )

        if status == 429:
            limit = self._rate_limit
            raise QuotaExceeded(
                self._error_message(response, "Daily API rate limit exceeded"),
                status_code=429,
                reset_at=limit.reset_at if limit else None,
            )

        if status == 400:
            detail = self._error_detail(response)
            if detail is not None:
                raise detail.to_exception(query)
            raise XQLError(
                self._error_message(response, "Query rejected"),
                query=query,
                status_code=400,
            )

        if status >= 500:
            raise UpstreamError(
                self._error_message(
                    response,
                    "The query planned successfully but the server could not serve it.",
                ),
                status_code=status,
            )

        raise XcreenerError(
            self._error_message(response, f"Unexpected status {status}"),
            status_code=status,
        )
