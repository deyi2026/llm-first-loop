#!/usr/bin/env node
// dsh_plugin_bridge.mjs — LFL 复用 DSH 插件生态的 Node 桥（EVO-20260819-f9e7ce23）
// cordis Context 按清单装配目标插件（dsh-base 兜底 ctx 服务）→ MCP stdio 暴露。
// 支持 SIGHUP / stdin "reload" 重载清单（data/dsh-bridge/plugins.json）。
import { createRequire } from "node:module";
import { readFileSync, existsSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { randomUUID } from "node:crypto";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const PROFILES_NM = process.env.DSH_BRIDGE_NODE_MODULES || join(ROOT, "data/dsh-home/profiles/node_modules");
const MANIFEST = process.env.DSH_BRIDGE_MANIFEST || join(ROOT, "data/dsh-bridge/plugins.json");
const requireFromPool = createRequire(join(PROFILES_NM, "_bridge_resolver.js"));

// 解析模块：包入口走 require.resolve（尊重 exports/main）；子路径直取绝对路径。
async function loadPluginModule(pkg) {
  let resolved;
  try {
    resolved = requireFromPool.resolve(pkg);
  } catch {
    resolved = join(PROFILES_NM, pkg);
  }
  const mod = await import(pathToFileURL(resolved));
  return mod.default ?? mod;
}

// dsh-base 兜底装配的 ctx 基础服务（工具插件 inject 依赖的最小集合，按依赖序）
const BASE_SERVICES = [
  "@deepseek-ai/dsh-system-prompt",
  "@deepseek-ai/dsh-tools",
  "@deepseek-ai/dsh-sandbox-policy",
  "@deepseek-ai/dsh-fs-sandbox",
];

const { Context } = await loadPluginModule("@deepseek-ai/cordis");
const { Server } = await loadPluginModule("@modelcontextprotocol/sdk/dist/esm/server/index.js");
const { StdioServerTransport } = await loadPluginModule(
  "@modelcontextprotocol/sdk/dist/esm/server/stdio.js"
);
const { ListToolsRequestSchema, CallToolRequestSchema } = await loadPluginModule(
  "@modelcontextprotocol/sdk/dist/esm/types.js"
);

let ctx = new Context();
const mounted = new Map(); // name -> disposer

async function mountPlugin(name, config) {
  if (mounted.has(name)) return;
  const mod = await loadPluginModule(name);
  const handle = await ctx.plugin(mod, config);
  mounted.set(name, handle);
  console.error(`[bridge] mounted ${name}`);
}

async function reload() {
  const manifest = existsSync(MANIFEST)
    ? JSON.parse(readFileSync(MANIFEST, "utf8"))
    : { plugins: [] };
  const wanted = [...BASE_SERVICES, ...(manifest.plugins || [])];
  const wantedNames = wanted.map((w) => (typeof w === "string" ? w : w.name));
  for (const item of wanted) {
    const name = typeof item === "string" ? item : item.name;
    const config = typeof item === "string" ? undefined : item.config;
    try {
      await mountPlugin(name, config);
    } catch (e) {
      console.error(`[bridge] mount failed ${name}: ${e.message}`);
    }
  }
  for (const [name, handle] of [...mounted]) {
    if (BASE_SERVICES.includes(name)) continue;
    if (!wantedNames.includes(name)) {
      try {
        await handle?.dispose?.();
        mounted.delete(name);
        console.error(`[bridge] unmounted ${name}`);
      } catch (e) {
        console.error(`[bridge] unmount failed ${name}: ${e.message}`);
      }
    }
  }
}

await reload();

const server = new Server(
  { name: "dsh-plugin-bridge", version: "0.1.0" },
  { capabilities: { tools: {} } }
);

server.setRequestHandler(ListToolsRequestSchema, async () => {
  const schemas = ctx.tools ? ctx.tools.schemas() : [];
  return {
    tools: schemas.map((s) => ({
      name: s.name,
      description: s.description || "",
      inputSchema: s.parameters || { type: "object", properties: {} },
    })),
  };
});

server.setRequestHandler(CallToolRequestSchema, async (req) => {
  const { name, arguments: args } = req.params;
  try {
    const result = await ctx.tools.execute({
      name,
      arguments: args ?? {},
      callId: randomUUID(),
      signal: AbortSignal.timeout(120_000),
    });
    return {
      content: result?.content ?? [{ type: "text", text: JSON.stringify(result) }],
      isError: !!result?.isError,
    };
  } catch (e) {
    return { content: [{ type: "text", text: `Error: ${e.message}` }], isError: true };
  }
});

process.on("SIGHUP", () => reload().catch((e) => console.error("[bridge] reload failed", e)));
process.stdin.on("data", (chunk) => {
  if (String(chunk).trim() === "reload") reload().catch((e) => console.error("[bridge] reload failed", e));
});

const transport = new StdioServerTransport();
await server.connect(transport);
