# xcreener-sdk-python

Python client for the [XCREENER](https://xcreener.com) XQL HTTP API. Strings in,
typed objects out.

```bash
pip install xcreener          # pip install 'xcreener[pandas]' for to_pandas()
```

## Quickstart

```python
from xcreener import Xcreener

xc = Xcreener()  # reads XCREENER_API_KEY

query = """
market = "CRYPTO"   # CRYPTO, FOREX, INDICES, COMMODITIES, METALS
timeframe = h1
let rsi14 = rsi(14)
columns = [rsi14, volume]
sort = volume desc
limit = 5

rsi14 < 30 and close > d::sma(200)
"""

for match in xc.run(query):
    print(match.symbol, match["rsi14"], match["volume"])
```

Generate a key at [xcreener.com/account/api-key](https://xcreener.com/account/api-key).
The raw key is shown once, and generating a new one invalidates the old one
everywhere it is in use.

## The API key

The client takes it from the constructor, or falls back to
`$XCREENER_API_KEY`.

```python
Xcreener()                        # $XCREENER_API_KEY
Xcreener(api_key="...")           # explicit, wins over the environment
```

## The four calls

| Method           | Endpoint             | Metered | Returns            |
| ---------------- | -------------------- | ------- | ------------------ |
| `xc.validate(q)` | `POST /xql/validate` | no      | `ValidationResult` |
| `xc.explain(q)`  | `POST /xql/explain`  | no      | `Explanation`      |
| `xc.run(q)`      | `POST /xql/run`      | **yes** | `ResultSet`        |
| `xc.usage()`     | `GET /usage`         | no      | `Quota`            |

## Validation is a result, not an exception

Checking a query is the entire point of `validate`, so a failure comes back as a
falsy object rather than something you have to catch. `run` and `explain` raise
on the same 400, because there it really is a bug.

```python
result = xc.validate('market = "CRYPTO"\ntimeframe = h1\nrsi(14)[1] < 30')

if not result:
    print(result.message)
    # Expected '-' (offset indexing uses the form [-N], e.g. [-1]) but found '1'

result.raise_for_error()
# xcreener.errors.XQLSyntaxError: line 3, column 9: Expected '-' (offset
# indexing uses the form [-N], e.g. [-1]) but found '1'
#
#     rsi(14)[1] < 30
#             ^
```

## Errors

```
XcreenerError
├── AuthenticationError   401  key missing or unrecognized
├── QuotaExceeded         429  .reset_at
├── XQLError              400  no data was fetched
│   ├── XQLSyntaxError         .line .column .offset, caret excerpt in str()
│   └── XQLPlanError           .required_bars .max_bars .timeframe
├── UpstreamError         5xx  retried before raising
└── TransportError             the request never completed
```

Plan errors parse themselves so you do not have to match on message text:

```python
try:
    xc.run('market = "CRYPTO"\ntimeframe = h1\nclose > d::highest(high, 365)')
except XQLPlanError as exc:
    if exc.is_lookback_ceiling:
        print(exc.required_bars, exc.max_bars, exc.timeframe)  # 366 300 d
```

Only 5xx and transport failures are retried. A 400 parses identically on a
retry, and a 429 has not refilled.

## Results

`ResultSet` is an ordered `Sequence[Match]`. The order is meaningful: it
reflects the query's own `sort` and `limit`. An empty result set means the query
is valid and nothing matches right now, which is not an error.

```python
rs = xc.run(query)

rs.symbols            # ['SOLUSDT', 'ADAUSDT']
rs.column("volume")   # [512044.2, 118642.0]
rs.column_names       # ['rsi14', 'volume']
rs[0]["rsi14"]        # 24.8
rs.to_dicts()
rs.to_pandas()        # indexed by symbol, needs the pandas extra
```

Columns are keyed by exactly what you wrote in the `columns` pragma: `rsi14`
for the `let` binding above, `rsi(14)` had you listed the expression itself. A
condition's own inputs are not surfaced automatically, so if `match["rsi14"]`
raises a `KeyError`, the fix is almost always adding it to `columns`. The error
message says so.

## Quota

`validate` and `explain` are never metered. Only `run` counts against the daily
quota, so iterate for free and spend a run once the query does what you want.

```python
xc.run(query, precheck=True)   # free validate first; a bad query costs 0 quota
xc.rate_limit                  # from the last run's headers, no extra request
xc.usage()                     # free, and still answers at 429
```

Set `Xcreener(precheck=True)` to make that the default in development.

A query's syntax does not drift once it checks out, so there is nothing to
re-validate for a query that is fixed in your source — go straight to `run`.
It still raises `XQLSyntaxError` if the query is bad. All you trade away is the
guarantee that a malformed one costs zero quota, and you save a round trip.

## Options

```python
Xcreener(
    api_key=None,                          # or $XCREENER_API_KEY
    base_url="https://api.xcreener.com",
    timeout=30.0,                          # seconds, per request
    max_retries=2,                         # 5xx and transport only
    precheck=False,
    transport=None,                        # inject your own httpx.Client
)
```

The client is a context manager, and accepts anything with a `to_xql()` method
as well as a raw string, so a future expression or builder layer drops in
without changing the transport.

## Contributing

Working on the SDK itself — running the test suite, or cutting a release? See
[CONTRIBUTING.md](CONTRIBUTING.md).

## License

MIT
