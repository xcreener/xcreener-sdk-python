"""Shared fixtures.

Every test runs against an ``httpx.MockTransport``, so the suite never needs an
API key, never touches the network, and never spends quota.
"""

from __future__ import annotations

import httpx
import pytest

from xcreener import Xcreener

GOOD_QUERY = """market = "CRYPTO"
timeframe = h1
columns = [rsi(14), volume]
sort = volume desc
limit = 5
rsi(14) < 30 and close > d::sma(200)"""

BAD_OFFSET_QUERY = 'market = "CRYPTO"\ntimeframe = h1\nrsi(14)[1] < 30'

LOOKBACK_QUERY = 'market = "CRYPTO"\ntimeframe = h1\nclose > d::highest(high, 365)'

SYNTAX_ERROR = {
    "valid": False,
    "error": {
        "type": "syntax",
        "message": (
            "Expected '-' (offset indexing uses the form [-N], e.g. [-1]) but found '1'"
        ),
        "position": {"line": 3, "column": 9, "offset": 41},
    },
}

PLAN_ERROR = {
    "valid": False,
    "error": {
        "type": "plan",
        "message": (
            "Query requires 366 bars of history for d, exceeding the maximum of 300"
        ),
    },
}

RUN_PAYLOAD = {
    "results": [
        {"symbol": "SOLUSDT", "columns": {"rsi(14)": 24.8, "volume": 512044.2}},
        {"symbol": "ADAUSDT", "columns": {"rsi(14)": 27.1, "volume": 118642.0}},
    ]
}

EXPLAIN_PAYLOAD = {
    "plan": {
        "market": "CRYPTO",
        "sources": [
            {"timeframe": "h1", "series": ["close", "volume"], "minLookback": 15},
            {"timeframe": "d", "series": ["close"], "minLookback": 200},
        ],
    },
    "explanation": "Matches when rsi(14) < 30 and close > d::sma(200).",
}

USAGE_PAYLOAD = {
    "tier": "essential",
    "limit": 1500,
    "used": 812,
    "remaining": 688,
    "resetAt": "2026-07-30T00:00:00.000Z",
}

RESET_HEADER = "2026-08-13T00:00:00.000Z"

RUN_HEADERS = {
    "X-RateLimit-Remaining": "687",
    "X-RateLimit-Reset": RESET_HEADER,
    "X-RateLimit-Limit": "1500",
}


class Recorder:
    """Captures every request the client makes, so tests can assert on what
    was (and was not) called: the precheck test depends on it."""

    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []

    @property
    def paths(self) -> list[str]:
        return [r.url.path for r in self.requests]

    @property
    def bodies(self) -> list[str]:
        return [r.content.decode() for r in self.requests]


@pytest.fixture
def recorder() -> Recorder:
    return Recorder()


@pytest.fixture
def make_client(recorder: Recorder):
    """Build a client whose transport is driven by a per-test handler."""

    def factory(handler, **kwargs) -> Xcreener:
        def wrapped(request: httpx.Request) -> httpx.Response:
            recorder.requests.append(request)
            return handler(request)

        transport = httpx.Client(transport=httpx.MockTransport(wrapped))
        kwargs.setdefault("max_retries", 1)
        kwargs.setdefault("api_key", "test-key")
        return Xcreener(transport=transport, **kwargs)

    return factory


@pytest.fixture
def client(make_client):
    """A client wired to the documented happy-path responses."""

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/usage":
            return httpx.Response(200, json=USAGE_PAYLOAD)
        if path == "/xql/validate":
            return httpx.Response(200, json={"valid": True})
        if path == "/xql/explain":
            return httpx.Response(200, json=EXPLAIN_PAYLOAD)
        if path == "/xql/run":
            return httpx.Response(200, headers=RUN_HEADERS, json=RUN_PAYLOAD)
        raise AssertionError(f"unexpected path {path}")

    return make_client(handler)


def responder(status: int, payload, headers=None):
    """A handler that answers everything the same way."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json=payload, headers=headers or {})

    return handler
