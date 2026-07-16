# MCP eval scenario packs (samples)

AssetOpsBench-shaped JSON packs for `nexus eval` (`nexus.scenario_pack/v1`).

## Install into runtime state

`.nexus_state/` is gitignored, so samples ship here and copy on demand:

```bash
nexus eval packs --install-samples
nexus eval smoke --discover-packs --tag sample --no-builtin
```

Or programmatically:

```python
from nexus import mcp_eval as me
me.ensure_sample_packs(workdir)
me.evaluate(workdir=workdir, include_builtin=False, discover_packs_flag=True)
```

## Packs

| File | Purpose |
|------|---------|
| `operator_smoke.json` | Read-only operator surface (status, catalog, vault, grade) |
| `privilege_safety.json` | Path jail + catalog validate + no secret leak |

Do not vendor industrial IoT trees; keep scenarios offline-safe and privilege-tagged.
