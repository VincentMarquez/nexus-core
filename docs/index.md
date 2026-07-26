<!-- Landing = dashboard-style documentation front door (see stylesheets/nexus.css) -->

<div class="nx-console" markdown="0">

  <div class="nx-hero">
    <h1>NEXUS Core</h1>
    <p class="nx-sub">
      Durable, evidence-gated multi-agent execution for repository work.<br>
      Start with an offline proof, then opt into the bus, model clients, or repository execution.
    </p>
    <div class="nx-pills">
      <span class="nx-pill on">durable</span>
      <span class="nx-pill on">checkpointed</span>
      <span class="nx-pill on">evidence-gated</span>
      <span class="nx-pill">local · provider-optional</span>
    </div>
    <div class="nx-cmd">
      <code id="nx-start-cmd" data-cmd="git clone https://github.com/VincentMarquez/nexus-core.git
cd nexus-core
make install
source .venv/bin/activate
make demo-all-quick">git clone https://github.com/VincentMarquez/nexus-core.git
cd nexus-core
make install
source .venv/bin/activate
make demo-all-quick</code>
      <button type="button" class="nx-btn primary" data-nx-copy="#nx-start-cmd">Copy</button>
    </div>
    <span class="nx-status" id="nx-start-status"></span>
    <div class="nx-actions">
      <a class="nx-btn primary" href="https://github.com/VincentMarquez/nexus-core">GitHub</a>
      <a class="nx-btn" href="getting-started/">Docs · Get started</a>
      <a class="nx-btn ghost" href="ARCHITECTURE/">Architecture</a>
      <a class="nx-btn ghost" href="SECURITY/">Safety</a>
      <a class="nx-btn ghost" id="nx-open-dash" href="http://127.0.0.1:3099/dashboard" style="display:none" target="_blank" rel="noopener">Open local dashboard</a>
    </div>
  </div>

  <div class="nx-grid">
    <section class="nx-card">
      <h2>1 · Run the offline proof</h2>
      <ol class="nx-steps">
        <li>Need <b>Python 3.10+</b>, Git, Make, and a POSIX shell</li>
        <li><code>make install</code> creates the virtual environment</li>
        <li><code>make demo-all-quick</code> runs the local reproducible checks</li>
      </ol>
      <div class="nx-cmd">
        <code id="nx-cmd-run" data-cmd="make install &amp;&amp; source .venv/bin/activate &amp;&amp; make demo-all-quick">make install &amp;&amp; source .venv/bin/activate &amp;&amp; make demo-all-quick</code>
        <button type="button" class="nx-btn" data-nx-copy="#nx-cmd-run">Copy</button>
      </div>
      <div class="nx-cmd">
        <code id="nx-cmd-demo" data-cmd="make demo">make demo</code>
        <button type="button" class="nx-btn" data-nx-copy="#nx-cmd-demo">Copy</button>
      </div>
    </section>

    <section class="nx-card">
      <h2>2 · Optional local bus</h2>
      <p class="nx-status" id="nx-local-status">checking…</p>
      <div id="nx-local-agents" class="nx-pills" style="margin-top:0.75rem"></div>
      <p style="color:var(--nx-muted);font-size:0.85rem;margin:0.75rem 0 0">
        With Node.js 18+, run <code>./run --no-pull</code> to start the bus and
        dashboard without downloading an Ollama model. This page can only
        <em>detect</em> a bus that is already running on localhost.
      </p>
      <div class="nx-cmd">
        <code id="nx-cmd-stack" data-cmd="./run --no-pull">./run --no-pull</code>
        <button type="button" class="nx-btn" data-nx-copy="#nx-cmd-stack">Copy</button>
      </div>
    </section>
  </div>

  <div class="nx-grid" style="margin-top:1rem">
    <section class="nx-card">
      <h2>3 · Run a trusted repository task</h2>
      <label class="nx-label" for="nx-repo">owner/repo or https://github.com/…</label>
      <input class="nx-input" id="nx-repo" type="text" placeholder="psf/requests" autocomplete="off" />
      <label class="nx-label" for="nx-goal">goal (optional)</label>
      <input class="nx-input" id="nx-goal" type="text" placeholder="make the tests pass and fix failures" autocomplete="off" />
      <div class="nx-cmd">
        <code id="nx-do-cmd">./run owner/repo</code>
        <button type="button" class="nx-btn primary" id="nx-do-copy">Copy</button>
      </div>
      <span class="nx-status" id="nx-do-status"></span>
      <p style="color:var(--nx-muted);font-size:0.85rem;margin:0.75rem 0 0">
        Installers and tests execute repository-controlled code. Use a trusted
        commit or an isolated, credential-free environment.
        <a href="cookbook/06_github_do/#safety">Read the safety notes.</a>
      </p>
    </section>

    <section class="nx-card">
      <h2>4 · Inspect durable evidence</h2>
      <div class="nx-cmd">
        <code id="nx-cmd-list" data-cmd="nexus task list">nexus task list</code>
        <button type="button" class="nx-btn" data-nx-copy="#nx-cmd-list">Copy</button>
      </div>
      <div class="nx-cmd">
        <code id="nx-cmd-replay" data-cmd="nexus task replay &lt;task_id&gt;">nexus task replay &lt;task_id&gt;</code>
        <button type="button" class="nx-btn" data-nx-copy="#nx-cmd-replay">Copy</button>
      </div>
      <div class="nx-cmd">
        <code id="nx-cmd-verify" data-cmd="nexus task verify &lt;task_id&gt;">nexus task verify &lt;task_id&gt;</code>
        <button type="button" class="nx-btn" data-nx-copy="#nx-cmd-verify">Copy</button>
      </div>
      <div class="nx-cmd">
        <code id="nx-cmd-evidence" data-cmd="nexus task evidence &lt;task_id&gt; --out evidence.json">nexus task evidence &lt;task_id&gt; --out evidence.json</code>
        <button type="button" class="nx-btn" data-nx-copy="#nx-cmd-evidence">Copy</button>
      </div>
      <p class="nx-links" style="margin:0.85rem 0 0">
        <a href="cookbook/12_task_operator/">Operator guide</a>
        <a href="evidence/">Evidence format</a>
      </p>
    </section>
  </div>

  <div class="nx-grid" style="margin-top:1rem">
    <section class="nx-card">
      <h2>5 · Domain workflows</h2>
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
    </section>

    <section class="nx-card">
      <h2>6 · Click into the details</h2>
      <p style="margin:0 0 0.75rem;color:var(--nx-muted);font-size:0.9rem">
        The README is the overview. These guides contain the setup, contracts,
        command details, limitations, and operational boundaries.
      </p>
      <p class="nx-links" style="margin:0.85rem 0 0">
        <a href="getting-started/">Getting started</a>
        <a href="DEMO/">Demo proof</a>
        <a href="ARCHITECTURE/">Architecture</a>
        <a href="PIPELINE/">10-step pipeline</a>
        <a href="PLATFORMS/">Model platforms</a>
        <a href="CONNECTORS/">Connectors &amp; MCP</a>
        <a href="GITHUB_COMMUNITY/">GitHub automation</a>
        <a href="ALIVE/">Self-improvement</a>
        <a href="SECURITY/">Security boundaries</a>
        <a href="COMPARE/">Fit and tradeoffs</a>
      </p>
    </section>
  </div>

</div>

![NEXUS task engine, agents, judge, memory, and evidence](assets/arch-overview.svg)
