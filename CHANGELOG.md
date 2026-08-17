# Changelog

Notable changes to this package, newest first. Versions follow
[semantic versioning](https://semver.org/spec/v2.0.0.html): while the major is
`0`, a minor bump is where a breaking change is allowed to land.

The scope here is the *client library*, not the XQL language or the API behind
it. A server-side change earns an entry only when it changes something this
package exposes.

## 0.1.0 — 2026-08-17

First public release.

### Added

- `Xcreener`, the synchronous client, covering all four endpoints:
  `validate()`, `explain()`, `run()` and `usage()`. Queries are sent as raw
  request bodies, never JSON-wrapped.
- Typed results as frozen dataclasses — `ValidationResult`, `Explanation`,
  `ResultSet`, `Match`, `Quota`, `RateLimit` — each keeping a `raw` copy of the
  payload it was parsed from, so an unrecognised field is never dropped.
- An exception hierarchy under `XcreenerError` that separates a wrong query
  (`XQLError`, `XQLSyntaxError`, `XQLPlanError`) from a wrong account
  (`AuthenticationError`, `QuotaExceeded`) from a wrong server
  (`UpstreamError`, `TransportError`).
- `XQLSyntaxError` renders a caret excerpt under the reported column, and
  `XQLPlanError` exposes `required_bars` / `max_bars` / `timeframe` so the
  lookback ceiling can be handled without matching on message text.
- Invalid queries come back from `validate()` as a falsy `ValidationResult`
  rather than an exception, since checking is the point of the call.
  `raise_for_error()` converts it when an exception is what you wanted.
- `run(precheck=True)`, and the client-level `precheck` default, spend a free
  `validate()` first so a malformed query costs no quota.
- `rate_limit` reads quota state from the last run's response headers, with no
  extra request.
- API keys accepted as a string or as a zero-argument callable, the latter
  resolved per request so rotation needs no new client. The key is never
  exposed through `repr()` or through any exception this package raises;
  `key_hint` gives a masked form that is safe to paste into a support thread.
- Pasted keys are trimmed and checked for stray whitespace, which turns a
  misleading 401 into a message saying the key does not need regenerating.
- `ResultSet.to_dicts()` and `ResultSet.to_pandas()`, the latter behind the
  `pandas` extra and shaped consistently even when there are no matches.
- `SupportsXQL`, a structural protocol, so anything with a `to_xql()` method
  works as a query or a column key without importing from this package.
- Retries for 5xx and transport failures only, with exponential backoff and
  jitter. A 400 parses identically on a retry and a 429 has not refilled, so
  neither is retried.
- `py.typed`: the package ships its own types and is checked under
  `mypy --strict`.
