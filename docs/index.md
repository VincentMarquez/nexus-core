<!-- Landing = dashboard-style start console (see stylesheets/nexus.css) -->

<div class="nx-console" markdown="0">

  <div class="nx-hero">
    <h1>NEXUS Core</h1>
    <p class="nx-sub">
      Many LLMs talk and reason together on hard problems — then finish only when evidence holds.<br>
      Clean start: one command. Dashboard when the bus is up.
    </p>
    <div class="nx-pills">
      <span class="nx-pill on">durable</span>
      <span class="nx-pill on">multi-LLM panel</span>
      <span class="nx-pill on">rubric judge</span>
      <span class="nx-pill">GitHub · arXiv · procurement</span>
    </div>
    <div class="nx-cmd">
      <code id="nx-start-cmd" data-cmd="git clone https://github.com/VincentMarquez/nexus-core
cd nexus-core
./run">git clone https://github.com/VincentMarquez/nexus-core
cd nexus-core
./run</code>
      <button type="button" class="nx-btn primary" data-nx-copy="#nx-start-cmd">Copy</button>
    </div>
    <span class="nx-status" id="nx-start-status"></span>
    <div class="nx-actions">
      <a class="nx-btn primary" href="https://github.com/VincentMarquez/nexus-core">GitHub</a>
      <a class="nx-btn" href="getting-started/">Docs · Get started</a>
      <a class="nx-btn ghost" href="COMPARE/">vs other tools</a>
      <a class="nx-btn ghost" id="nx-open-dash" href="http://127.0.0.1:3099/dashboard" style="display:none" target="_blank" rel="noopener">Open local dashboard</a>
    </div>
  </div>

  <div class="nx-grid">
    <section class="nx-card">
      <h2>1 · Start the stack</h2>
      <ol class="nx-steps">
        <li>Need <b>Python 3.10+</b> and <b>Node 18+</b></li>
        <li>Run <code>./run</code> (creates venv, installs, starts bus + agents)</li>
        <li>Browser opens the live dashboard — or use the button when bus is detected</li>
      </ol>
      <div class="nx-cmd">
        <code id="nx-cmd-run" data-cmd="./run">./run</code>
        <button type="button" class="nx-btn" data-nx-copy="#nx-cmd-run">Copy</button>
      </div>
      <div class="nx-cmd">
        <code id="nx-cmd-demo" data-cmd="make demo">make demo</code>
        <button type="button" class="nx-btn" data-nx-copy="#nx-cmd-demo">Copy</button>
      </div>
    </section>

    <section class="nx-card">
      <h2>2 · Local bus (this machine)</h2>
      <p class="nx-status" id="nx-local-status">checking…</p>
      <div id="nx-local-agents" class="nx-pills" style="margin-top:0.75rem"></div>
      <p style="color:var(--nx-muted);font-size:0.85rem;margin:0.75rem 0 0">
        This page can only <em>detect</em> a bus on localhost. Starting agents always happens in your terminal via <code>./run</code>.
      </p>
    </section>
  </div>

  <div class="nx-grid" style="margin-top:1rem">
    <section class="nx-card">
      <h2>3 · Paste a GitHub repo</h2>
      <label class="nx-label" for="nx-repo">owner/repo or https://github.com/…</label>
      <input class="nx-input" id="nx-repo" type="text" placeholder="psf/requests" autocomplete="off" />
      <label class="nx-label" for="nx-goal">goal (optional)</label>
      <input class="nx-input" id="nx-goal" type="text" placeholder="make the tests pass and fix failures" autocomplete="off" />
      <div class="nx-cmd">
        <code id="nx-do-cmd">./run owner/repo</code>
        <button type="button" class="nx-btn primary" id="nx-do-copy">Copy</button>
      </div>
      <span class="nx-status" id="nx-do-status"></span>
    </section>

    <section class="nx-card">
      <h2>4 · Other one-liners</h2>
      <div class="nx-cmd">
        <code id="nx-cmd-research" data-cmd='nexus research "multi agent orchestration" --heuristic-only'>nexus research "multi agent orchestration" --heuristic-only</code>
        <button type="button" class="nx-btn" data-nx-copy="#nx-cmd-research">Copy</button>
      </div>
      <div class="nx-cmd">
        <code id="nx-cmd-procure" data-cmd="nexus procure demo">nexus procure demo</code>
        <button type="button" class="nx-btn" data-nx-copy="#nx-cmd-procure">Copy</button>
      </div>
      <div class="nx-cmd">
        <code id="nx-cmd-arxiv" data-cmd="nexus arxiv get 1706.03762">nexus arxiv get 1706.03762</code>
        <button type="button" class="nx-btn" data-nx-copy="#nx-cmd-arxiv">Copy</button>
      </div>
      <div class="nx-cmd">
        <code id="nx-cmd-stop" data-cmd="nexus stop">nexus stop</code>
        <button type="button" class="nx-btn" data-nx-copy="#nx-cmd-stop">Copy</button>
      </div>
    </section>
  </div>

  <section class="nx-card" style="margin-top:1rem">
    <h2>Many LLMs · one hard problem</h2>
    <p style="margin:0 0 0.75rem;color:var(--nx-muted);font-size:0.9rem">
      After <code>./run</code>, installed CLIs (Claude, Codex, Gemini) and Ollama attach automatically.
      Map roles for a panel debate:
    </p>
    <div class="nx-cmd">
      <code id="nx-cmd-map" data-cmd="python examples/run_with_bus.py --map planner=claude,implementer=gpt,tester=local,adversary=local">python examples/run_with_bus.py --map planner=claude,implementer=gpt,tester=local,adversary=local</code>
      <button type="button" class="nx-btn" data-nx-copy="#nx-cmd-map">Copy</button>
    </div>
    <p class="nx-links" style="margin:0.85rem 0 0">
      <a href="FIGURES/">Figures</a>
      <a href="cookbook/06_github_do/">GitHub jobs</a>
      <a href="cookbook/07_procurement/">Procurement</a>
      <a href="cookbook/08_arxiv_research/">arXiv</a>
      <a href="agents/PROCUREMENT/">Agent personas</a>
      <a href="ARCHITECTURE/">Architecture</a>
    </p>
  </section>

</div>

![LLMs reason together](assets/arch-llms-reason-together.svg)
