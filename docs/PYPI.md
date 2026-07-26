# Publishing to PyPI

**Distribution name:** `nexus-multi-agent`

PyPI already contains an unrelated distribution named `nexus-core`; do not
publish this project under that name. The Python import path and CLI remain
`nexus`.

## Current installation status

The source checkout is the canonical runtime installation:

```bash
git clone https://github.com/VincentMarquez/nexus-core.git
cd nexus-core
make install
source .venv/bin/activate
nexus doctor
```

Do not advertise `pip install nexus-multi-agent` as generally available until a
release has been uploaded and verified from the public index.

The current wheel packages the Python modules and selected data files, but the
Node.js `bridge/` runtime used by `nexus start` is source-tree infrastructure.
Before presenting the wheel as a complete runtime install, either package those
assets and resolve them from installed package data or document the wheel as a
Python-core-only distribution.

## Build and inspect

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -U build twine
python -m build
twine check dist/*
python -m zipfile --list dist/*.whl
```

Create a clean environment and install the exact wheel before publishing:

```bash
python3 -m venv /tmp/nexus-wheel-smoke
source /tmp/nexus-wheel-smoke/bin/activate
pip install dist/*.whl
nexus --help
nexus doctor
```

Test every command claimed to work from a wheel. In particular, do not add
`nexus start` to public wheel instructions until the bridge assets are present
and the clean-environment smoke test passes.

## Option A — trusted publishing

One-time setup on [pypi.org](https://pypi.org):

1. Create the `nexus-multi-agent` project, or let the first upload create it.
2. Add a pending trusted publisher with:
   - Owner: `VincentMarquez`
   - Repository: `nexus-core`
   - Workflow: `publish.yml`
   - Environment: `pypi`
3. Create the `pypi` GitHub Environment and add suitable protection rules.
4. Publish a GitHub Release or explicitly run the publishing workflow.

The repository workflow is `.github/workflows/publish.yml` and uses OIDC, so it
does not require a long-lived PyPI token in the repository.

## Option B — API token

Prefer trusted publishing. If a token is required, store it outside the
repository and never print or commit it:

```bash
export TWINE_USERNAME=__token__
export TWINE_PASSWORD="<your-pypi-token>"
twine upload dist/*
```

Use TestPyPI first:

```bash
twine upload --repository testpypi dist/*
python3 -m venv /tmp/nexus-testpypi-smoke
source /tmp/nexus-testpypi-smoke/bin/activate
pip install --index-url https://test.pypi.org/simple/ \
  --extra-index-url https://pypi.org/simple/ nexus-multi-agent
nexus --help
nexus doctor
```

## Release gate

Before publishing:

```bash
make release-check
```

Then confirm:

- the version in `pyproject.toml` matches the intended `vMAJOR.MINOR.PATCH` tag;
- `CHANGELOG.md` contains that version;
- the clean wheel smoke test passes;
- every README installation claim matches what the wheel actually contains;
- the public project page exists after upload; and
- a fresh install from the public index resolves the uploaded version.

After those checks pass, update the README and documentation to make the PyPI
installation visible.
