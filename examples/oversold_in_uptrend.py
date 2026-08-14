"""Screen crypto for oversold names still in a daily uptrend.

    pip install xcreener          # or: pip install -e . from the repo root
    export XCREENER_API_KEY=...
    python examples/oversold_in_uptrend.py

Validate and explain are unmetered, so this script checks and inspects the
query for free and only then spends a single metered run call.
"""

from xcreener import QuotaExceeded, Xcreener, XQLError

QUERY = """
market = "CRYPTO"
timeframe = h1
columns = [rsi(14), volume]
sort = volume desc
limit = 5
rsi(14) < 30 and close > d::sma(200)
"""


def main() -> None:
    with Xcreener() as xc:
        check = xc.validate(QUERY)
        if not check:
            print(f"Invalid query: {check.message}")
            return

        plan = xc.explain(QUERY)
        print(plan.explanation)
        for source in plan.plan.sources:
            print(f"  {source.timeframe}: {source.min_lookback} bars of history")

        try:
            matches = xc.run(QUERY)
        except QuotaExceeded as exc:
            print(exc)
            return
        except XQLError as exc:
            print(exc)
            return

        if not matches:
            print("\nNothing matches right now.")
            return

        print(f"\n{len(matches)} matches:")
        for match in matches:
            print(
                f"  {match.symbol:12} rsi {match['rsi(14)']:.1f}"
                f"  vol {match['volume']:,.0f}"
            )

        remaining = xc.rate_limit.remaining if xc.rate_limit else None
        if remaining is not None:
            print(f"\n{remaining} runs left today.")


if __name__ == "__main__":
    main()