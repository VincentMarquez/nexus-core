# NEXUS Core

![NEXUS Core banner](assets/banner.svg)

**Multi-agent tasks that resume after a crash — with a judge that checks real success criteria, not “the model said OK.”**

## 60-second start

```bash
git clone https://github.com/VincentMarquez/nexus-core
cd nexus-core
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
nexus start -y          # bus + dashboard + local LLM
nexus demo              # crash → resume
nexus stop
```

Or: `make install && make start && make demo`

## What you get

| Capability | Docs |
|------------|------|
| Durable 10-step pipeline | [Pipeline](PIPELINE.md) |
| Rubric judge | [Architecture](ARCHITECTURE.md) |
| Local LLM + CLI bridges | [Bridges](BRIDGES_AND_BUS.md) |
| MCP for ChatGPT / Claude / Grok / phone | [Connectors](CONNECTORS.md) |
| GLM-5.2 / colibrì | [GLM-5.2](GLM52.md) |
| Cookbooks | [Cookbooks](cookbooks.md) |

## Figures

See [FIGURES.md](FIGURES.md) for all architecture diagrams.

## License

MIT · [GitHub](https://github.com/VincentMarquez/nexus-core)
