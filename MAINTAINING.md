# Maintaining

For maintainers with PyPI publishing rights. The per-release steps live in
[CONTRIBUTING.md](CONTRIBUTING.md#releasing); this file covers the setup you
only do once.

## One-time setup

The project does not exist on PyPI until the first upload, so there is nothing
to attach a publisher to yet. Register a *pending* publisher at
<https://pypi.org/manage/account/publishing/> with owner `xcreener`,
repository `xcreener-sdk-python`, workflow `publish.yml`, and environment
`pypi`. Then create a GitHub environment of the same name under Settings,
Environments. PyPI requires 2FA on the account either way.

For the rehearsal path, repeat both at
<https://test.pypi.org/manage/account/publishing/>, but with environment
`testpypi` — the workflow uses a separate environment per index, so the names
have to differ. The publisher will not match if you register `pypi` there.

## Rehearsing

Run the Publish workflow manually from the Actions tab. Manual runs stop at
TestPyPI and can never reach the real index; only a `v*` tag push publishes to
PyPI.
