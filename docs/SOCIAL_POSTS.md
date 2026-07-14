# Social posts (copy/paste)

## X / Twitter

**Post 1 — demo**

```
Multi-agent pipelines die mid-run and lose work.

NEXUS Core checkpoints every step and resumes after a crash.
Judge checks real success criteria — not “the model said OK.”

make install && make demo

https://github.com/VincentMarquez/nexus-core
```

**Post 2 — judge**

```
Presence validator: agent returned JSON → “pass”
Even when the artifact is wrong.

Rubric judge: does the file satisfy success_criteria?

make demo-judge
https://github.com/VincentMarquez/nexus-core
```

## LinkedIn

```
I open-sourced NEXUS Core — a small system for multi-agent research/dev workflows.

The problems I kept hitting:
• jobs dying mid-pipeline
• validators that only check that someone replied
• unattended loops burning tokens

What it does:
• durable 10-step pipeline with resume
• rubric-style judge on success criteria + evidence
• event bus for CLI agents and local LLMs (Ollama)
• autonomy off by default

Try: make install && make demo
https://github.com/VincentMarquez/nexus-core
MIT
```

## Reddit (LocalLLaMA-style — soft, not spam)

```
Title: Local multi-agent task runner with crash resume + Ollama bridge (MIT)

Body:
I built a small open-source core for multi-step agent tasks that checkpoint to disk and resume after a kill, plus a simple bus to attach Ollama/CLIs.

Quick demo (mocks, no keys):
git clone https://github.com/VincentMarquez/nexus-core
cd nexus-core && make install && make demo

Ollama notes: examples/ollama_local.md

Feedback welcome, especially on the judge/resume design.
```
