# Publishing to PyPI

**Distribution name:** `nexus-multi-agent`  
*(PyPI already has an unrelated package named `nexus-core` — do not use that name.)*

**Import / CLI:**

```bash
pip install nexus-multi-agent
nexus doctor
nexus start -y
```

Python import path remains `import nexus` (package under `src/nexus`).

## Build (any machine)

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -U build twine
python -m build
twine check dist/*
```

## Option A — Trusted publishing (recommended)

One-time setup on [pypi.org](https://pypi.org):

1. Create project **`nexus-multi-agent`** (or let the first upload create it).
2. **Publishing → Add a new pending publisher** with:
   - Owner: `VincentMarquez`
   - Repository: `nexus-core`
   - Workflow: `publish.yml`
   - Environment name: `pypi`
3. On GitHub: create Environment **`pypi`** under repo Settings → Environments (optional protection rules).
4. Publish a GitHub Release (or re-run the **Publish to PyPI** workflow).

The workflow is `.github/workflows/publish.yml` (OIDC, no long-lived token in the repo).

## Option B — API token

Never commit the token.

```bash
export TWINE_USERNAME=__token__
export TWINE_PASSWORD=pypi-...your-token...
twine upload dist/*
```

Test PyPI first:

```bash
twine upload --repository testpypi dist/*
pip install -i https://test.pypi.org/simple/ nexus-multi-agent
```

## After publish

```bash
pip install nexus-multi-agent
nexus doctor
nexus start -y
nexus mcp --http
```

## Version policy

Tag releases as `vMAJOR.MINOR.PATCH` matching `pyproject.toml` version.
Current target: **0.4.1**.
