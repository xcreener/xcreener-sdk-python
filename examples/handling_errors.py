"""Every failure mode the client can raise, and what to do about each.

pip install xcreener          # or: pip install -e . from the repo root
export XCREENER_API_KEY=...
python examples/handling_errors.py
"""

from xcreener import (
    AuthenticationError,
    QuotaExceeded,
    TransportError,
    UpstreamError,
    Xcreener,
    XQLPlanError,
    XQLSyntaxError,
)

# `[1]` is a parse error: offsets need a literal minus, as in `[-1]`.
BAD_SYNTAX = """
market = "CRYPTO"
timeframe = h1
rsi(14)[1] < 30
"""

# Parses fine, but 365 daily bars exceeds the 300-bar lookback ceiling.
# The weekly form, `w::highest(high, 52)`, is the one that plans.
BAD_PLAN = """
market = "CRYPTO"
timeframe = h1
close > d::highest(high, 365)
"""

GOOD = """
market = "METALS"
timeframe = d
symbols = ["XAUUSD", "XAGUSD"]
columns = [close, rsi(14)]
sort = rsi(14) desc
close >= w::highest(high, 52)
"""


def check_first(xc: Xcreener, query: str) -> None:
    """validate() reports rather than raises: checking is the point of it."""
    result = xc.validate(query)
    if result:
        print("valid")
        return
    print(f"invalid: {result.message}")


def run_and_report(xc: Xcreener, query: str) -> None:
    try:
        matches = xc.run(query)

    except XQLSyntaxError as exc:
        # str() renders the offending line with a caret under the column.
        print(f"Could not parse the query:\n{exc}")

    except XQLPlanError as exc:
        if exc.is_lookback_ceiling:
            print(
                f"Needs {exc.required_bars} bars of {exc.timeframe}, "
                f"the ceiling is {exc.max_bars}. Use a coarser timeframe."
            )
        else:
            print(f"Could not plan the query: {exc}")

    except QuotaExceeded as exc:
        # validate() and explain() keep working while run() is exhausted,
        # so iterating on the query is still free until the reset.
        print(f"Out of runs for today. Resets at {exc.reset_at}.")

    except AuthenticationError:
        print(
            "Key rejected. Check XCREENER_API_KEY. A key that was working "
            "yesterday usually means it was regenerated somewhere else."
        )

    except UpstreamError:
        # Already retried before reaching here, so this is a real outage.
        print("The query planned but the server could not serve it.")

    except TransportError as exc:
        print(f"Never reached the API: {exc}")

    else:
        print(f"{len(matches)} matches: {', '.join(matches.symbols) or 'none'}")


def main() -> None:
    with Xcreener() as xc:
        for label, query in [
            ("syntax error", BAD_SYNTAX),
            ("plan error", BAD_PLAN),
            ("valid query", GOOD),
        ]:
            print(f"\n--- {label} ---")
            check_first(xc, query)
            run_and_report(xc, query)


if __name__ == "__main__":
    main()
