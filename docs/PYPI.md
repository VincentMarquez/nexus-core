# Publishing to PyPI

Package name: **`nexus-core`**  
Entry point: **`nexus`**

## Build (any machine)

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -U build twine
python -m build
twine check dist/*
```

## Upload

Needs a PyPI API token (never commit it):

```bash
export TWINE_USERNAME=__token__
export TWINE_PASSWORD=pypi-...your-token...
twine upload dist/*
```

Test PyPI first:

```bash
twine upload --repository testpypi dist/*
pip install -i https://test.pypi.org/simple/ nexus-core
```

## After publish

```bash
pip install nexus-core
nexus doctor
nexus start -y
```

GitHub Actions can automate this on tag push once `PYPI_API_TOKEN` is set in repo secrets.
