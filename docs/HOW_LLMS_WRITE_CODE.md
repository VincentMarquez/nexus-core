# How LLMs “write code” (and why agents still run tests)

## They don’t use a special code compiler inside the model

A transformer language model predicts **tokens** (pieces of text) one after another:

```text
context (prompt + files + tool results)
    → neural net
    → next-token probabilities
    → sample/greedy pick
    → append token
    → repeat until done
```

So “writing a function” is the same mechanism as writing English: **next-token generation**, guided by training on huge amounts of code + instructions.

There is **no** separate internal “AST builder” or “Python interpreter” inside the base model (unless you add tools).

## What *does* make coding work well

| Layer | What it is |
|-------|------------|
| **Weights** | Patterns: syntax, APIs, common bugs, styles |
| **Prompt / context** | Issue text, repo snippets, errors, your rules |
| **Tools** | Shell, edit, grep, pytest, git — **run real code** |
| **Agent loop** | Generate → run tests → read failure → edit → repeat |
| **Multi-agent** | Other models review / challenge / research |

**Method = agent workflow + tools + tests.**  
Tokens alone = a guess. **Running the code** is how the guess becomes engineering.

## “Spawn agents”

Spawning means **extra processes or bus slots** that each:

1. Get a role-specific prompt (implementer, reviewer, researcher)  
2. Call a strong model (Grok / Claude / Codex / Gemini)  
3. Return structured findings into the workspace  
4. Feed the next stage  

That is **not** one model magically forking brains inside one forward pass — it’s **orchestration** (NEXUS bus, subprocesses, `run_task`).

## SWE-bench Pro implication

```text
LLM proposes patch (tokens)
  → agent RUNS tests in sandbox   ← required for good results
  → multi-AI review
  → final patch file
  → official Pro Docker harness grades again
```

Pre-checks (pytest, linters) **are allowed and expected**.  
The official harness is still the **score**.
