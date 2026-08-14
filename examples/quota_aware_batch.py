"""Run a batch of screens without blowing the daily quota.

Only `run` is metered. `validate`, `explain` and `usage` are free, so this
checks every query for free first and stops before it runs out of runs.

    pip install xcreener          # or: pip install -e . from the repo root
    export XCREENER_API_KEY=...
    python examples/quota_aware_batch.py
"""

from xcreener import QuotaExceeded, Xcreener

SCREENS = {
    "oversold in uptrend": """
        market = "CRYPTO"
        timeframe = h1
        columns = [rsi(14), volume]
        sort = volume desc
        limit = 5
        rsi(14) < 30 and close > d::sma(200)
    """,
    "golden cross this week": """
        market = "CRYPTO"
        timeframe = d
        let x = crossover(ema(50), ema(200))
        columns = [close, rsi(14), x]
        sort = rsi(14) desc
        limit = 20
        x or x[-1] or x[-2]
    """,
    "bollinger squeeze": """
        market = "FOREX"
        timeframe = h1
        columns = [bb_upper(20, 2), bb_lower(20, 2), atr(14)]
        sort = atr(14) asc
        limit = 10
        (bb_upper(20, 2) - bb_lower(20, 2)) / bb_mid(20, 2) < 0.01
    """,
}

# Leave a few runs in the tank for ad-hoc work later in the day.
RESERVE = 5


def main() -> None:
    with Xcreener() as xc:
        # Free: reject bad queries before any of them costs a run.
        runnable = {}
        for name, query in SCREENS.items():
            result = xc.validate(query)
            if result:
                runnable[name] = query
            else:
                print(f"skipping {name!r}: {result.message}")

        quota = xc.usage()
        budget = max(quota.remaining - RESERVE, 0)
        print(
            f"\n{quota.remaining}/{quota.limit} runs left on {quota.tier}, "
            f"spending at most {budget}"
        )

        if budget < len(runnable):
            print(f"Only running the first {budget} of {len(runnable)} screens.")

        for name, query in list(runnable.items())[:budget]:
            try:
                matches = xc.run(query)
            except QuotaExceeded as exc:
                # The reserve is a guess, the header is the truth.
                print(f"\nStopped early: {exc}")
                break

            symbols = ", ".join(matches.symbols) if matches else "nothing"
            print(f"\n{name}: {symbols}")

        # Scraped from the last run's headers, so this costs no extra request.
        if xc.rate_limit:
            print(f"\n{xc.rate_limit.remaining} runs left.")


if __name__ == "__main__":
    main()
