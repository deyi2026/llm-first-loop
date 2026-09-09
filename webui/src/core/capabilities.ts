// Web V2：后端能力探测（capability probing）
// 同一份 webui 部署在两类后端上：完整内部后端（含会话运维/任务面板/续跑/
// 附件/文件树等接口）与开源精简后端（只有核心对话/会话/工作区/演进接口）。
// 为避免在精简后端上渲染"死入口"，启动时对每个能力端点做一次 GET 探测：
// FastAPI/Starlette 路由层对"路径存在但方法受限"返回 405，对"路径不存在"
// 返回 404——因此 GET 探测 POST-only 路由：405=存在，404=缺失。
// 缺失的能力在 UI 上隐藏入口，而不是让用户点击后收到 404。
// 诚实性约束：探测只反映"端点是否存在"；网络失败不降级（保持乐观默认），
// 只有明确 404 才隐藏功能；默认值 = 完整后端视角（全开）。
import { useEffect, useSyncExternalStore } from "react";

export type CapabilityKey =
  | "attachments"
  | "fsTree"
  | "pin"
  | "archive"
  | "delete"
  | "fork"
  | "feedback"
  | "jobs"
  | "continuity";

export type Capabilities = Readonly<Record<CapabilityKey, boolean>>;

// 全局能力（无会话依赖）：用哑 session id 探测会话级 POST-only 路由。
// 405 语义由路由层在 handler 之前产生，哑 id 不会触碰任何真实会话。
const GLOBAL_PROBES: ReadonlyArray<readonly [CapabilityKey, string]> = [
  ["attachments", "/api/v1/attachments/recent?limit=1"],
  ["fsTree", "/api/v1/fs/tree?path=."],
  ["pin", "/api/v1/sessions/__capability_probe__/pin"],
  ["archive", "/api/v1/sessions/__capability_probe__/archive"],
  ["delete", "/api/v1/sessions/__capability_probe__"],
  ["fork", "/api/v1/sessions/__capability_probe__/fork"],
  ["feedback", "/api/v1/sessions/__capability_probe__/feedback"],
];

// 会话级能力（jobs/continuity 的 handler 对不存在的 session 返回 404，
// 会与"路由缺失"混淆），因此只在拿到真实会话 id 后再探测。
const SESSION_PROBE_KEYS = ["jobs", "continuity"] as const;

let state: Capabilities = {
  attachments: true,
  fsTree: true,
  pin: true,
  archive: true,
  delete: true,
  fork: true,
  feedback: true,
  jobs: true,
  continuity: true,
};
let globalStarted = false;
const probedSessions = new Set<string>();
const listeners = new Set<() => void>();
const emit = () => listeners.forEach((l) => l());
const subscribe = (listener: () => void): (() => void) => {
  listeners.add(listener);
  return () => listeners.delete(listener);
};
const getSnapshot = (): Capabilities => state;

async function endpointExists(url: string): Promise<boolean | null> {
  try {
    const res = await fetch(url, { method: "GET", cache: "no-store" });
    if (res.status === 404) return false; // 路由不存在 → 明确降级
    return true; // 200/405/其他 → 端点存在（或无需判断）
  } catch {
    return null; // 网络失败 → 不降级
  }
}

async function runProbe(key: CapabilityKey, url: string): Promise<void> {
  const exists = await endpointExists(url);
  if (exists === false && state[key]) {
    state = { ...state, [key]: false };
    emit();
  }
}

export function ensureProbesStarted(): void {
  if (globalStarted) return;
  globalStarted = true;
  for (const [key, url] of GLOBAL_PROBES) void runProbe(key, url);
}

export function probeSessionCapabilities(sessionId: string | null | undefined): void {
  if (!sessionId || probedSessions.has(sessionId)) return;
  probedSessions.add(sessionId);
  for (const key of SESSION_PROBE_KEYS) {
    void runProbe(key, `/api/v1/sessions/${encodeURIComponent(sessionId)}/${key}`);
  }
}

export function useCapabilities(): Capabilities {
  useEffect(() => {
    ensureProbesStarted();
  }, []);
  return useSyncExternalStore(subscribe, getSnapshot, getSnapshot);
}

// ---- 测试钩子（仅测试使用；生产代码不得调用）----
export function __setCapabilitiesForTest(next: Partial<Record<CapabilityKey, boolean>>): void {
  state = { ...state, ...next };
  emit();
}

export function __resetCapabilitiesForTest(): void {
  state = {
    attachments: true,
    fsTree: true,
    pin: true,
    archive: true,
    delete: true,
    fork: true,
    feedback: true,
    jobs: true,
    continuity: true,
  };
  globalStarted = false;
  probedSessions.clear();
}
