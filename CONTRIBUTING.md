# Contributing

## Development

```bash
git clone https://github.com/xcreener/xcreener-sdk-python
cd xcreener-sdk-python
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev,pandas]"

pytest              # no API key and no network needed
ruff check src tests
mypy src/xcreener
```

The test suite runs entirely against `httpx.MockTransport`, so it never spends
quota and never needs a key.

## Releasing

The version lives in one place, `__version__` in `src/xcreener/_version.py`,
and `pyproject.toml` reads it from there.

1. Bump `__version__`.
2. In [CHANGELOG.md](CHANGELOG.md), retitle the top section to the new version
   and today's date, and open a fresh `## Unreleased` above it.
3. Commit, then `git tag v0.1.0 && git push origin v0.1.0`.

The workflow refuses to continue if the tag does not match `__version__`,
builds an sdist and a wheel, checks the metadata renders, installs the wheel
into a clean environment to prove it imports, and uploads via trusted
publishing. There is no API token anywhere in the process.

Publishing rights, the trusted-publisher setup, and the TestPyPI rehearsal
path are in [MAINTAINING.md](MAINTAINING.md).
