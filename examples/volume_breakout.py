"""Volume breakout screen, with results as a DataFrame.

Shows `let` bindings, ranking with `sort`/`limit`, and reading columns back
off each match.

    pip install xcreener          # or: pip install -e . from the repo root
    export XCREENER_API_KEY=...
    python examples/volume_breakout.py
"""

from xcreener import Xcreener

# `let` names an intermediate expression so it can be reused in the body.
# Note that `columns` is what decides which values come back: the condition's
# own inputs are not surfaced automatically, so `volume` and `avgv` are listed
# explicitly even though the body already references both.
QUERY = """
market = "CRYPTO"
timeframe = h4
let avgv = avg(volume, 20)
columns = [volume, avgv, rsi(14)]
sort = volume desc
limit = 10
volume > avgv * 2 and close > highest(high, 20)
"""


def main() -> None:
    with Xcreener() as xc:
        matches = xc.run(QUERY)

        if not matches:
            print("No breakouts on this bar.")
            return

        for match in matches:
            ratio = match["volume"] / match["avgv"]
            print(
                f"{match.symbol:12} {ratio:5.1f}x avg volume"
                f"   rsi {match['rsi(14)']:5.1f}"
            )

        # Column keys are the literal expression text, so this works for any
        # expression you put in `columns`, arithmetic included.
        print("\nvolume column:", matches.column("volume"))

        # Optional extra: pip install 'xcreener[pandas]'
        try:
            frame = matches.to_pandas()
        except ImportError:
            return
        print()
        print(frame.sort_values("rsi(14)").head())


if __name__ == "__main__":
    main()
