/**
 * NEXUS-style event bus — PUBLIC STUB
 *
 * - No API keys
 * - No personal filesystem paths
 * - Talks to agents only via file-drop protocol under BRIDGE_DIR
 *
 * Usage:  node server.js
 * Env:    NEXUS_BUS_PORT (default 3099)
 *         NEXUS_BRIDGE_DIR (default OS temp + /nexus-bridges)
 */

import { createServer } from "http";
import {
  existsSync,
  mkdirSync,
  readFileSync,
  writeFileSync,
  unlinkSync,
} from "fs";
import { join } from "path";
import { tmpdir } from "os";
import { randomUUID } from "crypto";

const PORT = Number(process.env.NEXUS_BUS_PORT || 3099);
const BRIDGE_DIR = process.env.NEXUS_BRIDGE_DIR || join(tmpdir(), "nexus-bridges");
const AGENTS = (process.env.NEXUS_AGENTS || "claude,gpt,gemini,local")
  .split(",")
  .map((s) => s.trim())
  .filter(Boolean);
const DEFAULT_TIMEOUT_MS = Number(process.env.NEXUS_MSG_TIMEOUT_MS || 120_000);

if (!existsSync(BRIDGE_DIR)) mkdirSync(BRIDGE_DIR, { recursive: true });

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

/**
 * File-drop RPC: write prompt, wait for matching response id.
 */
async function callAgent(agent, prompt, timeoutMs = DEFAULT_TIMEOUT_MS) {
  if (!AGENTS.includes(agent)) {
    const err = new Error(`unknown agent: ${agent}`);
    err.statusCode = 400;
    throw err;
  }
  const p = paths(agent);
  const st = agentStatus(agent);
  if (st.status === "offline") {
    const err = new Error(`agent offline: ${agent}`);
    err.statusCode = 503;
    throw err;
  }

  const id = randomUUID();
  // clear stale response
  try {
    if (existsSync(p.response)) unlinkSync(p.response);
  } catch {}

  writeJson(p.prompt, { id, prompt, ts: Date.now() });

  const start = Date.now();
  while (Date.now() - start < timeoutMs) {
    const resp = readJson(p.response);
    if (resp && resp.id === id && typeof resp.text === "string") {
      try {
        unlinkSync(p.response);
      } catch {}
      return { id, agent, text: resp.text, ms: Date.now() - start };
    }
    await sleep(200);
  }
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
    if (req.method === "GET" && url.pathname === "/health") {
      return send(res, 200, { ok: true, bridge_dir: BRIDGE_DIR, agents: AGENTS });
    }

    if (req.method === "GET" && url.pathname === "/api/status") {
      return send(res, 200, {
        agents: AGENTS.map(agentStatus),
        bridge_dir: BRIDGE_DIR,
      });
    }

    if (req.method === "POST" && url.pathname === "/api/message") {
      const body = await readBody(req);
      const agent = body.agent || "claude";
      const prompt = body.prompt || "";
      if (!prompt) return send(res, 400, { error: "prompt required" });
      const out = await callAgent(agent, prompt, Number(body.timeout_ms) || DEFAULT_TIMEOUT_MS);
      return send(res, 200, out);
    }

    send(res, 404, { error: "not found", paths: ["/health", "/api/status", "/api/message"] });
  } catch (e) {
    send(res, e.statusCode || 500, { error: String(e.message || e) });
  }
});

server.listen(PORT, () => {
  console.log(`[nexus-bus] listening on http://127.0.0.1:${PORT}`);
  console.log(`[nexus-bus] BRIDGE_DIR=${BRIDGE_DIR}`);
  console.log(`[nexus-bus] agents=${AGENTS.join(",")}`);
  console.log(`[nexus-bus] start a bridge: ./bridges/mock-bridge.sh claude`);
});
