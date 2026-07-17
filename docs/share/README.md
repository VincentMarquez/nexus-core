# Sharing NEXUS

Assets and short copy you can use when writing about the project. All paths under `docs/assets/` are meant for public screenshots and embeds.

| Asset | Path |
|-------|------|
| Demo video | [docs/assets/nexus-demo-reel.mp4](../assets/nexus-demo-reel.mp4) |
| Demo GIF | [docs/assets/nexus-demo-reel.gif](../assets/nexus-demo-reel.gif) |
| Architecture | [docs/assets/arch-governed-self-improve-capability-factory.png](../assets/arch-governed-self-improve-capability-factory.png) |
| Public stills | [docs/assets/screenshots/public-shots/](../assets/screenshots/public-shots/) |
| Status badge | [docs/assets/last-real-badge.svg](../assets/last-real-badge.svg) |
| Social post draft | [SOCIAL.md](SOCIAL.md) |
| Image carousel captions | [CAROUSEL.md](CAROUSEL.md) |
| Show HN draft | [SHOW_HN.md](SHOW_HN.md) |
| Latest self-improve snapshot | [LAST_REAL.md](LAST_REAL.md) |

## Reproduce the demo

```bash
git clone https://github.com/VincentMarquez/nexus-core.git
cd nexus-core
make install && make start && make demo-all-quick
```

Optional API keys enable live CLIs; without them, mocks and local Ollama (if installed) still exercise the bus.

After a self-improve cycle, refresh the status badge:

```bash
python3 scripts/last_real_badge.py --runtime "~XhYm"
```
