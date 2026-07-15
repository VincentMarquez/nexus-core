/**
 * NEXUS start console — GitHub Pages interactive helpers.
 * Does not start local processes (browser sandbox); builds copy-ready commands
 * and probes localhost bus if the user already ran ./run.
 */
(function () {
  "use strict";

  function $(id) {
    return document.getElementById(id);
  }

  function copyText(text, statusEl) {
    if (!text) return;
    const done = () => {
      if (statusEl) {
        statusEl.textContent = "copied";
        statusEl.className = "nx-status ok";
        setTimeout(() => {
          statusEl.textContent = "";
          statusEl.className = "nx-status";
        }, 1500);
      }
    };
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(done).catch(() => fallback());
    } else {
      fallback();
    }
    function fallback() {
      const ta = document.createElement("textarea");
      ta.value = text;
      document.body.appendChild(ta);
      ta.select();
      try {
        document.execCommand("copy");
        done();
      } catch (e) {
        if (statusEl) {
          statusEl.textContent = "select & copy manually";
          statusEl.className = "nx-status err";
        }
      }
      document.body.removeChild(ta);
    }
  }

  function wireCopyButtons() {
    document.querySelectorAll("[data-nx-copy]").forEach((btn) => {
      btn.addEventListener("click", () => {
        const sel = btn.getAttribute("data-nx-copy");
        const el = sel ? document.querySelector(sel) : null;
        const text = (el && (el.dataset.cmd || el.textContent)) || btn.dataset.cmd || "";
        const status = btn.parentElement && btn.parentElement.querySelector(".nx-status");
        copyText(text.trim(), status);
      });
    });
  }

  function wireCommandBuilder() {
    const repo = $("nx-repo");
    const goal = $("nx-goal");
    const out = $("nx-do-cmd");
    const status = $("nx-do-status");
    if (!repo || !out) return;

    function rebuild() {
      const r = (repo.value || "owner/repo").trim() || "owner/repo";
      const g = (goal.value || "").trim();
      let cmd =
        "git clone https://github.com/VincentMarquez/nexus-core && cd nexus-core && ./run " +
        shellQuote(r);
      if (g) cmd += " --goal " + shellQuote(g);
      out.textContent = cmd;
      out.dataset.cmd = cmd;
    }

    function shellQuote(s) {
      if (/^[A-Za-z0-9_./:@-]+$/.test(s)) return s;
      return "'" + s.replace(/'/g, "'\\''") + "'";
    }

    repo.addEventListener("input", rebuild);
    if (goal) goal.addEventListener("input", rebuild);
    rebuild();

    const copyBtn = $("nx-do-copy");
    if (copyBtn) {
      copyBtn.addEventListener("click", () => copyText(out.dataset.cmd || out.textContent, status));
    }
  }

  async function probeLocalBus() {
    const el = $("nx-local-status");
    const agents = $("nx-local-agents");
    const openBtn = $("nx-open-dash");
    if (!el) return;

    const ports = [3099, 3109, 3110, 3111, 3112];
    el.textContent = "probing localhost…";
    el.className = "nx-status";

    for (const port of ports) {
      try {
        const ctrl = new AbortController();
        const t = setTimeout(() => ctrl.abort(), 600);
        const res = await fetch("http://127.0.0.1:" + port + "/api/status", {
          signal: ctrl.signal,
          mode: "cors",
        });
        clearTimeout(t);
        if (!res.ok) continue;
        const st = await res.json();
        el.textContent = "bus online on :" + port;
        el.className = "nx-status ok";
        if (agents) {
          const list = st.agents || [];
          agents.innerHTML = list.length
            ? list
                .map((a) => {
                  const name = a.agent || a.name || "?";
                  const s = a.status || "unknown";
                  const cls = s === "online" ? "on" : s === "busy" ? "busy" : "off";
                  return '<span class="nx-pill ' + cls + '">' + name + ": " + s + "</span>";
                })
                .join(" ")
            : '<span class="nx-pill off">no agents yet</span>';
        }
        if (openBtn) {
          openBtn.href = "http://127.0.0.1:" + port + "/dashboard";
          openBtn.style.display = "";
        }
        return;
      } catch (_) {
        /* try next port */
      }
    }
    el.textContent = "no local bus (run ./run on your machine)";
    el.className = "nx-status";
    if (agents) {
      agents.innerHTML =
        '<span class="nx-pill off">claude: —</span> ' +
        '<span class="nx-pill off">gpt: —</span> ' +
        '<span class="nx-pill off">gemini: —</span> ' +
        '<span class="nx-pill off">local: —</span>';
    }
    if (openBtn) openBtn.style.display = "none";
  }

  function init() {
    if (!document.querySelector(".nx-console")) return;
    wireCopyButtons();
    wireCommandBuilder();
    probeLocalBus();
    setInterval(probeLocalBus, 5000);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
