from __future__ import annotations

import httpx
import pytest

from xcreener import (
    AuthenticationError,
    Explanation,
    Match,
    QuotaExceeded,
    ResultSet,
    TransportError,
    UpstreamError,
    Xcreener,
    XcreenerError,
    XQLError,
    XQLPlanError,
    XQLSyntaxError,
)

from .conftest import (
    BAD_OFFSET_QUERY,
    GOOD_QUERY,
    LOOKBACK_QUERY,
    PLAN_ERROR,
    RESET_HEADER,
    SYNTAX_ERROR,
    responder,
)

# ----------------------------------------------------------------- transport


def test_query_is_sent_as_raw_text_not_json(client, recorder):
    client.run(GOOD_QUERY)
    request = recorder.requests[-1]
    assert request.content.decode() == GOOD_QUERY
    assert request.headers["content-type"].startswith("text/plain")
    assert request.headers["authorization"] == "Bearer test-key"


def test_api_key_falls_back_to_environment(monkeypatch):
    monkeypatch.setenv("XCREENER_API_KEY", "from-env")
    assert Xcreener()._resolve_key() == "from-env"


def test_pasted_key_whitespace_is_trimmed(make_client, recorder):
    """A trailing newline from a paste must not reach the wire as a bad 401."""
    client = make_client(responder(200, {"valid": True}))
    client._api_key_provider = lambda: "  padded-key\n"
    client.validate(GOOD_QUERY)
    assert recorder.requests[-1].headers["authorization"] == "Bearer padded-key"


@pytest.mark.parametrize("bad", ["key with space", "key\twith\ttab", "k\x00ey"])
def test_malformed_key_names_the_real_problem(bad):
    with pytest.raises(ValueError, match="do not need to regenerate"):
        Xcreener(bad)


def test_api_key_never_appears_in_client_repr(make_client):
    """Clients land in notebook output cells and Sentry breadcrumbs."""
    client = make_client(responder(200, {"valid": True}), api_key="SUPERSECRETKEY")
    assert "SUPERSECRETKEY" not in repr(client)


def test_missing_api_key_is_rejected_at_construction(monkeypatch):
    monkeypatch.delenv("XCREENER_API_KEY", raising=False)
    with pytest.raises(ValueError, match="XCREENER_API_KEY"):
        Xcreener()


def test_accepts_any_object_with_to_xql(client):
    """Forward compatibility with a future expression or builder layer."""

    class FakeQuery:
        def to_xql(self) -> str:
            return GOOD_QUERY

    assert client.run(FakeQuery()).symbols == ["SOLUSDT", "ADAUSDT"]


@pytest.mark.parametrize("bad", [123, None, object()])
def test_rejects_non_query_objects(client, bad):
    with pytest.raises(TypeError, match="to_xql"):
        client.run(bad)


def test_rejects_empty_query(client):
    with pytest.raises(ValueError, match="empty"):
        client.run("   \n  ")


# ------------------------------------------------------------------ validate


def test_validate_success_is_truthy(client):
    result = client.validate(GOOD_QUERY)
    assert result and result.valid and result.error is None


def test_invalid_query_returns_falsy_result_rather_than_raising(make_client):
    client = make_client(responder(400, SYNTAX_ERROR))
    result = client.validate(BAD_OFFSET_QUERY)
    assert not result
    assert result.valid is False


def test_validate_surfaces_the_raw_api_message(make_client):
    client = make_client(responder(400, SYNTAX_ERROR))
    assert client.validate(BAD_OFFSET_QUERY).message == SYNTAX_ERROR["error"]["message"]


def test_raise_for_error_raises_with_position(make_client):
    client = make_client(responder(400, SYNTAX_ERROR))
    with pytest.raises(XQLSyntaxError) as excinfo:
        client.validate(BAD_OFFSET_QUERY).raise_for_error()
    error = excinfo.value
    assert (error.line, error.column, error.offset) == (3, 9, 41)


def test_syntax_error_renders_a_caret_under_the_column(make_client):
    client = make_client(responder(400, SYNTAX_ERROR))
    with pytest.raises(XQLSyntaxError) as excinfo:
        client.validate(BAD_OFFSET_QUERY).raise_for_error()
    rendered = str(excinfo.value)
    assert "rsi(14)[1] < 30" in rendered
    caret_line = rendered.splitlines()[-1]
    assert caret_line.strip() == "^"
    assert caret_line.index("^") == len("    rsi(14)[")


# ------------------------------------------------------------------- explain


def test_explain_returns_plan_and_description(client):
    result = client.explain(GOOD_QUERY)
    assert isinstance(result, Explanation)
    assert result.plan.market == "CRYPTO"
    assert result.plan.timeframes == ["h1", "d"]
    assert result.plan.max_lookback == 200
    assert str(result).startswith("Matches when")


def test_explain_raises_on_invalid_query(make_client):
    """Unlike validate, a 400 here is a bug, so it raises."""
    client = make_client(responder(400, SYNTAX_ERROR))
    with pytest.raises(XQLSyntaxError):
        client.explain(BAD_OFFSET_QUERY)


# ----------------------------------------------------------------------- run


def test_run_returns_matches_in_query_order(client):
    results = client.run(GOOD_QUERY)
    assert isinstance(results, ResultSet)
    assert results.symbols == ["SOLUSDT", "ADAUSDT"]
    assert len(results) == 2


def test_empty_results_are_not_an_error(make_client):
    client = make_client(responder(200, {"results": []}))
    results = client.run(GOOD_QUERY)
    assert len(results) == 0
    assert list(results) == []


def test_columns_are_keyed_by_expression_text(client):
    match = client.run(GOOD_QUERY)[0]
    assert match["rsi(14)"] == 24.8
    assert "volume" in match
    assert match.get("missing", "fallback") == "fallback"


def test_column_key_accepts_an_object_that_renders_to_xql(client):
    class Rsi:
        def to_xql(self) -> str:
            return "rsi(14)"

    assert client.run(GOOD_QUERY)[0][Rsi()] == 24.8


def test_missing_column_error_points_at_the_columns_pragma(client):
    with pytest.raises(KeyError, match="columns"):
        client.run(GOOD_QUERY)[0]["sma(50)"]


def test_result_set_slicing_and_projection(client):
    results = client.run(GOOD_QUERY)
    assert isinstance(results[:1], ResultSet)
    assert results.column("volume") == [512044.2, 118642.0]
    assert results.column_names == ["rsi(14)", "volume"]
    assert results.to_dicts()[0] == {
        "symbol": "SOLUSDT",
        "rsi(14)": 24.8,
        "volume": 512044.2,
    }
    assert all(isinstance(m, Match) for m in results)


# -------------------------------------------------------------------- errors


def test_plan_error_parses_the_lookback_ceiling(make_client):
    client = make_client(responder(400, PLAN_ERROR))
    with pytest.raises(XQLPlanError) as excinfo:
        client.run(LOOKBACK_QUERY)
    error = excinfo.value
    assert error.is_lookback_ceiling
    assert (error.required_bars, error.max_bars, error.timeframe) == (366, 300, "d")


def test_plan_error_degrades_gracefully_on_an_unknown_message(make_client):
    payload = {"valid": False, "error": {"type": "plan", "message": "something else"}}
    client = make_client(responder(400, payload))
    with pytest.raises(XQLPlanError) as excinfo:
        client.run(GOOD_QUERY)
    assert excinfo.value.is_lookback_ceiling is False
    assert excinfo.value.required_bars is None


def test_401_raises_authentication_error(make_client):
    client = make_client(responder(401, {"error": "Unauthorized"}))
    with pytest.raises(AuthenticationError):
        client.run(GOOD_QUERY)


def test_429_raises_quota_exceeded_with_reset(make_client):
    """The 429 body carries a bare string, not the object shape a 400 uses."""
    client = make_client(
        responder(
            429,
            {"error": "Daily API rate limit exceeded"},
            headers={"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "1755043200"},
        )
    )
    with pytest.raises(QuotaExceeded) as excinfo:
        client.run(GOOD_QUERY)
    assert excinfo.value.reset_at is not None
    assert "resets at" in str(excinfo.value)


def test_500_is_retried_then_raised(make_client, recorder):
    client = make_client(responder(500, {"error": "database connection failed"}))
    with pytest.raises(UpstreamError):
        client.run(GOOD_QUERY)
    assert len(recorder.requests) == 2  # initial attempt plus one retry


@pytest.mark.parametrize(
    "status,payload",
    [(400, SYNTAX_ERROR), (401, {"error": "no"}), (429, {"error": "no"})],
)
def test_client_errors_are_never_retried(make_client, recorder, status, payload):
    client = make_client(responder(status, payload))
    with pytest.raises(XcreenerError):
        client.run(GOOD_QUERY)
    assert len(recorder.requests) == 1


def test_transport_failure_is_wrapped(make_client, recorder):
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no route to host")

    client = make_client(handler)
    with pytest.raises(TransportError):
        client.run(GOOD_QUERY)
    assert len(recorder.requests) == 2


def test_non_json_body_is_reported_clearly(make_client):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>gateway</html>")

    client = make_client(handler)
    with pytest.raises(XcreenerError, match="Expected JSON"):
        client.run(GOOD_QUERY)


# --------------------------------------------------------------------- quota


def test_precheck_spends_no_run_call_on_a_bad_query(make_client, recorder):
    client = make_client(responder(400, SYNTAX_ERROR), precheck=True)
    with pytest.raises(XQLSyntaxError):
        client.run(BAD_OFFSET_QUERY)
    assert recorder.paths == ["/xql/validate"]


def test_precheck_can_be_overridden_per_call(client, recorder):
    client.run(GOOD_QUERY, precheck=True)
    assert recorder.paths == ["/xql/validate", "/xql/run"]


def test_invalid_without_an_error_object_still_raises(make_client):
    """A bare ``{"valid": false}`` carries nothing to build a specific
    exception from, but staying silent would make the result falsy *and*
    non-raising."""
    client = make_client(responder(200, {"valid": False}))
    result = client.validate(GOOD_QUERY)

    assert not result
    with pytest.raises(XQLError):
        result.raise_for_error()


def test_precheck_spends_no_run_call_when_the_api_omits_error_detail(
    make_client, recorder
):
    """The whole point of precheck is not spending quota on a query the API
    already called invalid, detail or no detail."""
    client = make_client(responder(200, {"valid": False}), precheck=True)
    with pytest.raises(XQLError):
        client.run(GOOD_QUERY)
    assert recorder.paths == ["/xql/validate"]


def test_rate_limit_is_scraped_from_run_headers(client):
    assert client.rate_limit is None
    client.run(GOOD_QUERY)
    assert client.rate_limit.remaining == 687
    assert client.rate_limit.reset_at.year == 2026


def test_usage_reports_quota_state(client):
    quota = client.usage()
    assert (quota.tier, quota.limit, quota.remaining) == ("essential", 1500, 688)
    assert quota.exhausted is False
    assert round(quota.fraction_used, 3) == 0.541


def test_client_works_as_a_context_manager(make_client):
    with make_client(responder(200, {"valid": True})) as client:
        assert client.validate(GOOD_QUERY)


def test_quota_exceeded_reads_the_headers_of_the_429_itself(make_client):
    """usage() never populates client.rate_limit, so sourcing the reset from
    the last run would report an unrelated time here, or nothing."""
    headers = {
        "X-RateLimit-Remaining": "0",
        "X-RateLimit-Reset": RESET_HEADER,
        "X-RateLimit-Limit": "1500",
    }
    client = make_client(responder(429, {"error": "limit"}, headers=headers))

    with pytest.raises(QuotaExceeded) as exc_info:
        client.usage()

    assert client.rate_limit is None  # nothing cached to fall back on
    assert exc_info.value.reset_at.year == 2026
    assert exc_info.value.limit == 1500


def test_negative_max_retries_is_rejected_at_construction(make_client):
    with pytest.raises(ValueError, match="max_retries must be >= 0"):
        make_client(responder(200, {"valid": True}), max_retries=-1)


# ------------------------------------------------------------------- pandas


def test_to_pandas_is_indexed_by_symbol(client):
    pd = pytest.importorskip("pandas")

    frame = client.run(GOOD_QUERY).to_pandas()

    assert frame.index.name == "symbol"
    assert list(frame.index) == ["SOLUSDT", "ADAUSDT"]
    assert frame.loc["SOLUSDT", "rsi(14)"] == 24.8
    assert isinstance(frame, pd.DataFrame)


def test_empty_to_pandas_keeps_the_result_shape(make_client):
    """No matches is a normal outcome, so it must not hand back a frame that
    callers have to special-case before indexing."""
    pytest.importorskip("pandas")
    client = make_client(responder(200, {"results": []}))

    frame = client.run(GOOD_QUERY).to_pandas()

    assert frame.empty
    assert frame.index.name == "symbol"


# ------------------------------------------------------------- key handling


SECRET = "xcr_live_supersecret_abcd1234"


def test_key_is_sent_only_as_a_bearer_header(client, recorder):
    client.run(GOOD_QUERY)
    request = recorder.requests[-1]
    assert request.headers["authorization"] == "Bearer test-key"
    # Never in the URL: query strings end up in access logs and proxy caches.
    assert "test-key" not in str(request.url)
    assert "test-key" not in request.content.decode()


def test_repr_never_exposes_the_key(make_client):
    client = make_client(responder(200, {"valid": True}))
    client._api_key_provider = lambda: SECRET
    assert SECRET not in repr(client)
    assert SECRET not in str(client)


@pytest.mark.parametrize(
    "status,payload",
    [
        (400, SYNTAX_ERROR),
        (401, {"error": "Unauthorized"}),
        (429, {"error": "Daily API rate limit exceeded"}),
        (500, {"error": "database connection failed"}),
    ],
)
def test_key_never_leaks_into_raised_errors(make_client, status, payload):
    """Exceptions get logged and shipped to error trackers verbatim."""
    client = make_client(responder(status, payload))
    client._api_key_provider = lambda: SECRET
    with pytest.raises(XcreenerError) as excinfo:
        client.run(GOOD_QUERY)
    assert SECRET not in str(excinfo.value)
    assert SECRET not in repr(excinfo.value)


def test_key_hint_masks_all_but_the_last_four(make_client):
    client = make_client(responder(200, {"valid": True}))
    client._api_key_provider = lambda: SECRET
    assert client.key_hint == "...1234"


def test_callable_key_is_resolved_on_every_request(make_client, recorder):
    """Supports rotation: regenerating a key invalidates the old one, so a
    long-running process must be able to pick up the new one."""
    keys = iter(["first-key", "second-key"])
    client = make_client(responder(200, {"valid": True}), api_key=lambda: next(keys))
    client.validate(GOOD_QUERY)
    client.validate(GOOD_QUERY)
    sent = [r.headers["authorization"] for r in recorder.requests]
    assert sent == ["Bearer first-key", "Bearer second-key"]


def test_key_provider_is_not_called_at_construction(make_client):
    """A provider backed by a secret manager should be hit once per request,
    not an extra time just because a client was built."""
    calls = []
    client = make_client(
        responder(200, {"valid": True}),
        api_key=lambda: calls.append(1) or "k",
    )
    assert calls == []
    client.validate(GOOD_QUERY)
    assert len(calls) == 1


def test_empty_key_from_provider_is_rejected(make_client):
    client = make_client(responder(200, {"valid": True}), api_key=lambda: "")
    with pytest.raises(ValueError, match="empty key"):
        client.validate(GOOD_QUERY)
