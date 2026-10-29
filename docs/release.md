# Releasing to PyPI

The distribution name is **`veriq-quantum`**, because `veriq` on PyPI belongs to an unrelated project. The
import package and the CLI are still `veriq`:

```bash
pip install veriq-quantum
veriq check my_circuit.qasm
python -c "import veriq"
```

Releases are published by `.github/workflows/release.yml` with PyPI **Trusted Publishing** (OIDC), so no API
token is stored anywhere.

## One-time setup (maintainer, on pypi.org)

1. Log in to https://pypi.org (turn on 2FA).
2. Go to *Your account → Publishing → Add a new pending publisher → GitHub*:
   - PyPI project name: `veriq-quantum`
   - Owner: `Yosefnoorani`
   - Repository name: `veriq`
   - Workflow name: `release.yml`
   - Environment name: `pypi`
3. On GitHub: *Settings → Environments → New environment* `pypi`. Optionally require a reviewer.

## Cutting a release

```bash
# bump __version__ in src/veriq/__init__.py, commit, then:
git tag v0.1.0
git push origin v0.1.0
```

The workflow checks that the tag matches `__version__`, builds the sdist and wheel, runs `twine check
--strict`, smoke-tests the wheel in a clean venv, and publishes it.

## Local dry run

```bash
python -m pip install build twine
python -m build
python -m twine check --strict dist/*
```
