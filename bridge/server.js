/**
 * NEXUS-style event bus — PUBLIC STUB
 *
 * - No API keys / personal paths
 * - File-drop agent protocol
 * - SSE /api/events for dashboards
 * - Optional task registry for minimal UI
 *
 * Env: NEXUS_BUS_PORT, NEXUS_BRIDGE_DIR, NEXUS_AGENTS, NEXUS_STATE_DIR
 */

import { createServer } from "http";
import {
  existsSync,
  mkdirSync,
  readFileSync,
  writeFileSync,
  unlinkSync,
  readdirSync,
} from "fs";
import { join } from "path";
import { tmpdir } from "os";
import { randomUUID } from "crypto";

const PORT = Number(process.env.NEXUS_BUS_PORT || 3099);
const BRIDGE_DIR = process.env.NEXUS_BRIDGE_DIR || join(tmpdir(), "nexus-bridges");
const STATE_DIR = process.env.NEXUS_STATE_DIR || join(process.cwd(), "..", ".nexus_state");
const AGENTS = (process.env.NEXUS_AGENTS || "claude,gpt,gemini,local")
  .split(",")
  .map((s) => s.trim())
  .filter(Boolean);
// Real CLIs (Claude / Codex / Grok) often need several minutes per step.
// 120s caused mass 504s and failed multi-vendor demos for end users.
const DEFAULT_TIMEOUT_MS = Number(process.env.NEXUS_MSG_TIMEOUT_MS || 360_000);

if (!existsSync(BRIDGE_DIR)) mkdirSync(BRIDGE_DIR, { recursive: true });

/** @type {Set<import('http').ServerResponse>} */
const sseClients = new Set();
const recentEvents = [];
const MAX_EVENTS = 200;

function emit(event, data = {}) {
  const payload = {
    event,
    ts: Date.now(),
    ...data,
  };
  recentEvents.push(payload);
  if (recentEvents.length > MAX_EVENTS) recentEvents.shift();
  const line = `event: ${event}\ndata: ${JSON.stringify(payload)}\n\n`;
  for (const res of sseClients) {
    try {
      res.write(line);
    } catch {
      sseClients.delete(res);
    }
  }
}

function paths(agent) {
  const base = join(BRIDGE_DIR, agent);
  return {
    prompt: `${base}-prompt.json`,
    response: `${base}-response.json`,
    status: `${base}-status.json`,
  };
}

function readJson(path) {
  try {
    if (!existsSync(path)) return null;
    return JSON.parse(readFileSync(path, "utf8"));
  } catch {
    return null;
  }
}

function writeJson(path, obj) {
  writeFileSync(path, JSON.stringify(obj, null, 2));
}

function agentStatus(agent) {
  const st = readJson(paths(agent).status);
  if (!st) return { agent, status: "offline", ts: null };
  return { agent, status: st.status || "offline", ts: st.ts || null, detail: st.detail || null };
}

function sleep(ms) {
  return new Promise((r) => setTimeout(r, ms));
}

function listTasks() {
  const dir = join(STATE_DIR, "tasks");
  if (!existsSync(dir)) return [];
  const out = [];
  for (const f of readdirSync(dir)) {
    if (!f.endsWith(".json")) continue;
    const t = readJson(join(dir, f));
    if (t) out.push({
      task_id: t.task_id,
      status: t.status,
      current_step: t.current_step,
      objective: (t.objective || "").slice(0, 120),
      error: t.meta?.error || null,
    });
  }
  return out.sort((a, b) => String(a.task_id).localeCompare(String(b.task_id)));
}

async function callAgent(agent, prompt, timeoutMs = DEFAULT_TIMEOUT_MS) {
  if (!AGENTS.includes(agent)) {
    const err = new Error(`unknown agent: ${agent}`);
    err.statusCode = 400;
    throw err;
  }
  const p = paths(agent);
  const st = agentStatus(agent);
  if (st.status === "offline" || st.status === "unknown") {
    // offline if no status file or explicit offline
    if (!st.ts || st.status === "offline") {
      const err = new Error(`agent offline: ${agent}`);
      err.statusCode = 503;
      throw err;
    }
  }

  const id = randomUUID();
  // Clear stale prompt/response so we never match an old turn
  try {
    if (existsSync(p.response)) unlinkSync(p.response);
  } catch {}
  try {
    if (existsSync(p.prompt)) unlinkSync(p.prompt);
  } catch {}

  writeJson(p.prompt, { id, prompt, ts: Date.now() });
  emit("message_queued", { agent, id });

  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    const resp = readJson(p.response);
    if (resp && typeof resp.text === "string" && resp.text.length > 0) {
      // Exact id match is preferred; also accept when prompt is gone (bridge done)
      // and response is fresher than this request start (avoids stale reuse).
      const idOk = resp.id === id;
      const promptGone = !existsSync(p.prompt);
      const fresh =
        typeof resp.ts === "number" ? resp.ts * 1000 >= start - 1000 : promptGone;
      if (idOk || (promptGone && fresh)) {
        try {
          unlinkSync(p.response);
        } catch {}
        emit("message_done", {
          agent,
          id,
          ms: Date.now() - start,
          matched: resp.id,
        });
        return { id, agent, text: resp.text, ms: Date.now() - start };
      }
    }
    await sleep(150);
  }
  emit("message_timeout", { agent, id });
  const err = new Error(`timeout waiting for agent ${agent}`);
  err.statusCode = 504;
  throw err;
}

function send(res, code, obj) {
  const body = JSON.stringify(obj, null, 2);
  res.writeHead(code, {
    "content-type": "application/json",
    "access-control-allow-origin": "*",
  });
  res.end(body);
}

async function readBody(req) {
  const chunks = [];
  for await (const c of req) chunks.push(c);
  if (!chunks.length) return {};
  try {
    return JSON.parse(Buffer.concat(chunks).toString("utf8"));
  } catch {
    return {};
  }
}

function serveDashboard(res) {
  const htmlPath = join(process.cwd(), "dashboard", "index.html");
  if (!existsSync(htmlPath)) {
    return send(res, 404, { error: "dashboard/index.html not found — run from bridge/" });
  }
  const html = readFileSync(htmlPath, "utf8");
  res.writeHead(200, {
    "content-type": "text/html; charset=utf-8",
    "access-control-allow-origin": "*",
  });
  res.end(html);
}

const server = createServer(async (req, res) => {
  const url = new URL(req.url || "/", `http://${req.headers.host || "localhost"}`);

  if (req.method === "OPTIONS") {
    res.writeHead(204, {
      "access-control-allow-origin": "*",
      "access-control-allow-methods": "GET,POST,OPTIONS",
      "access-control-allow-headers": "content-type",
    });
    return res.end();
  }

  try {
    if (req.method === "GET" && (url.pathname === "/" || url.pathname === "/dashboard")) {
      return serveDashboard(res);
    }

    if (req.method === "GET" && url.pathname === "/health") {
      return send(res, 200, {
        ok: true,
        bridge_dir: BRIDGE_DIR,
        state_dir: STATE_DIR,
        agents: AGENTS,
        sse_clients: sseClients.size,
      });
    }

    if (req.method === "GET" && url.pathname === "/api/status") {
      return send(res, 200, {
        agents: AGENTS.map(agentStatus),
        bridge_dir: BRIDGE_DIR,
        tasks: listTasks().length,
      });
    }

    if (req.method === "GET" && url.pathname === "/api/tasks") {
      return send(res, 200, { tasks: listTasks() });
    }

    if (req.method === "GET" && url.pathname.startsWith("/api/tasks/")) {
      const id = decodeURIComponent(url.pathname.slice("/api/tasks/".length));
      const path = join(STATE_DIR, "tasks", `${id}.json`);
      const t = readJson(path);
      if (!t) return send(res, 404, { error: "task not found" });
      return send(res, 200, t);
    }

    if (req.method === "GET" && url.pathname === "/api/events") {
      // SSE
      res.writeHead(200, {
        "content-type": "text/event-stream",
        "cache-control": "no-cache",
        connection: "keep-alive",
        "access-control-allow-origin": "*",
      });
      res.write(`event: hello\ndata: ${JSON.stringify({ ts: Date.now(), recent: recentEvents.slice(-20) })}\n\n`);
      sseClients.add(res);
      const ping = setInterval(() => {
        try {
          res.write(`event: ping\ndata: ${JSON.stringify({ ts: Date.now() })}\n\n`);
        } catch {
          clearInterval(ping);
          sseClients.delete(res);
        }
      }, 15000);
      req.on("close", () => {
        clearInterval(ping);
        sseClients.delete(res);
      });
      return;
    }

    if (req.method === "POST" && url.pathname === "/api/message") {
      const body = await readBody(req);
      const agent = body.agent || "claude";
      const prompt = body.prompt || "";
      if (!prompt) return send(res, 400, { error: "prompt required" });
      const out = await callAgent(agent, prompt, Number(body.timeout_ms) || DEFAULT_TIMEOUT_MS);
      return send(res, 200, out);
    }

    if (req.method === "POST" && url.pathname === "/api/events/publish") {
      const body = await readBody(req);
      emit(body.event || "custom", body.data || body);
      return send(res, 200, { ok: true });
    }

    send(res, 404, {
      error: "not found",
      paths: [
        "/health",
        "/api/status",
        "/api/tasks",
        "/api/tasks/:id",
        "/api/events",
        "/api/message",
        "/dashboard",
      ],
    });
  } catch (e) {
    emit("error", { message: String(e.message || e) });
    send(res, e.statusCode || 500, { error: String(e.message || e) });
  }
});

server.listen(PORT, () => {
  console.log(`[nexus-bus] http://127.0.0.1:${PORT}`);
  console.log(`[nexus-bus] dashboard http://127.0.0.1:${PORT}/dashboard`);
  console.log(`[nexus-bus] SSE     http://127.0.0.1:${PORT}/api/events`);
  console.log(`[nexus-bus] BRIDGE_DIR=${BRIDGE_DIR}`);
  console.log(`[nexus-bus] STATE_DIR=${STATE_DIR}`);
  emit("bus_started", { port: PORT });
});
