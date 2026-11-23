// Web V2 核心：SSE 会话事件订阅（复用后端 /api/v1/events 命名事件；
// 对齐 v0.5.6 前端加固：失联自愈看门狗 + 标签页聚焦即刷）

import { fetchSessionsResult, fetchSharedCurrent, notifyProvidersUpdated } from "./api";
import type { ProvidersUpdatedFact } from "./api";
import { refreshCurrentSessionMessages } from "./conversation";
import { sessionStore } from "./stores";
import { notifyModelCatalogChanged } from "./chat";
import { readSessionIdFromLocation } from "./sessionUrl";
import { isAuthRequired, subscribeAuthRequired } from "./authSession";

let lastSyncEvent = Date.now();
let es: EventSource | null = null;
let watchdogTimer: number | null = null;
let onVisibilityChange: (() => void) | null = null;
let hiddenSyncPending = false;
let unsubscribeAuth: (() => void) | null = null;
const watchdogMs = 20000;
const staleThresholdMs = 25000;

// 多个标签页与密集 sessions_updated 事件不应让每个无关会话写入都触发
// 当前会话的 100 条历史重载。会话列表的持久元数据可判定当前会话是否变化。
let syncRunning = false;
let syncAgain = false;

function refreshFromSync(): void {
  if (isAuthRequired()) return;
  if (document.hidden) {
    hiddenSyncPending = true; // 后台标签页不刷新；恢复可见时补一次
    return;
  }
  if (syncRunning) {
    syncAgain = true; // 在途事件最多合并为下一轮；不丢掉并发期间的更新
    return;
  }
  syncRunning = true;
  void (async () => {
    try {
      do {
        syncAgain = false;
        const before = sessionStore.getState();
        const sessionId = before.currentSessionId;
        const previous = before.sessions.find((s) => s.session_id === sessionId);
        const ok = await refreshSessionsAndCurrent();
        if (!ok || !sessionId) continue; // 失败不能伪装成空列表或清空消息
        const after = sessionStore.getState();
        if (after.currentSessionId !== sessionId) continue; // 切会话由新视图自行加载
        const current = after.sessions.find((s) => s.session_id === sessionId);
        if (
          !previous || !current ||
          previous.updated_at !== current.updated_at ||
          previous.message_count !== current.message_count ||
          previous.last_message_preview !== current.last_message_preview
        ) {
          // 仍保留飞书等外部写入的推送级可见性；仅对实际变化的当前会话重载。
          await refreshCurrentSessionMessages();
        }
      } while (syncAgain);
    } finally {
      syncRunning = false;
    }
  })();
}

/** Boolean result distinguishes a successful empty list from a failed read. */
export async function refreshSessionsAndCurrent(): Promise<boolean> {
  const result = await fetchSessionsResult();
  // Session discovery is authoritative only on a valid response. A transient 5xx/offline
  // result must not mechanically rewrite a known non-empty sidebar into "zero sessions".
  if (!result.ok) return false;
  const sessions = result.sessions;
  sessionStore.setSessions(sessions);
  // 2026-08-19 修复跳回旧会话: 用户主动"新建/清除上下文"（newSessionPending=true）时，
  // 空 currentSessionId 是新会话语义——SSE 同步（sessions_updated/看门狗/聚焦）不得
  // 回填为最近/共享会话；首条消息发送时由 conversation.ts 消费标记（new_session=true）
  // 并切换到服务端新建的会话。发送前若有其他路径需要会话 id，由发起方自行处理。
  if (sessionStore.getState().newSessionPending) return true;
  // Deep links are navigation metadata only: honor them only after validating
  // the requested id against the current server-provided session list.
  const requested = readSessionIdFromLocation();
  if (
    !sessionStore.getState().currentSessionId &&
    requested &&
    sessions.some((s) => s.session_id === requested)
  ) {
    sessionStore.setCurrentSession(requested);
    return true;
  }
  if (!sessionStore.getState().currentSessionId) {
    const shared = await fetchSharedCurrent();
    if (shared) {
      const target = sessions.find((s) => s.session_id === shared);
      if (target) sessionStore.setCurrentSession(shared);
    }
    if (!sessionStore.getState().currentSessionId && sessions.length > 0) {
      sessionStore.setCurrentSession(sessions[0].session_id);
    }
  }
  return true;
}

export function initEventStream(): void {
  if (typeof EventSource === "undefined" || isAuthRequired()) return;
  if (es) return;
  es = new EventSource("/api/v1/events");
  unsubscribeAuth = subscribeAuthRequired(() => {
    if (isAuthRequired()) stopEventStream(); // stop EventSource automatic 401 reconnects
  });
  es.addEventListener("connected", () => {
    lastSyncEvent = Date.now();
    void refreshSessionsAndCurrent();
  });
  es.addEventListener("sessions_updated", () => {
    lastSyncEvent = Date.now();
    refreshFromSync();
  });
  // §5.6/§6.2.5 providers_updated（data: type/config_version/catalog_version/default_model）：
  // 配置热变更后刷新模型目录（Composer 经 MODEL_CATALOG_CHANGED_EVENT 重拉 /api/v1/models）
  // 与打开中的 Provider 快照（api.ts 订阅 → ProviderManager；有 draft 只提示冲突不覆盖）。
  es.addEventListener("providers_updated", (event: Event) => {
    lastSyncEvent = Date.now();
    let fact: ProvidersUpdatedFact = {};
    const data = (event as MessageEvent).data;
    if (typeof data === "string" && data) {
      try {
        const parsed = JSON.parse(data) as Record<string, unknown>;
        fact = {
          type: typeof parsed.type === "string" ? parsed.type : undefined,
          config_version: typeof parsed.config_version === "string" ? parsed.config_version : undefined,
          catalog_version: typeof parsed.catalog_version === "string" ? parsed.catalog_version : undefined,
          default_model: typeof parsed.default_model === "string" ? parsed.default_model : undefined,
        };
      } catch {
        fact = {};
      }
    }
    notifyModelCatalogChanged();
    notifyProvidersUpdated(fact);
  });
  // 看门狗：事件流静默失联（>25s 无事件且页面可见）→ 自愈刷新（SSE 健康时不触发）
  watchdogTimer = window.setInterval(() => {
    if (document.visibilityState === "visible" && Date.now() - lastSyncEvent > staleThresholdMs) {
      lastSyncEvent = Date.now();
      refreshFromSync();
    }
  }, watchdogMs);
  // 后台 SSE 只记更新事实；重新可见时立即补读，不依赖 5s 静默阈值。
  onVisibilityChange = () => {
    if (!document.hidden && (hiddenSyncPending || Date.now() - lastSyncEvent > 5000)) {
      hiddenSyncPending = false;
      lastSyncEvent = Date.now();
      refreshFromSync();
    }
  };
  document.addEventListener("visibilitychange", onVisibilityChange);
}

export function stopEventStream(): void {
  unsubscribeAuth?.();
  unsubscribeAuth = null;
  if (es) {
    es.close();
    es = null;
  }
  if (watchdogTimer !== null) {
    window.clearInterval(watchdogTimer);
    watchdogTimer = null;
  }
  if (onVisibilityChange) {
    document.removeEventListener("visibilitychange", onVisibilityChange);
    onVisibilityChange = null;
  }
  hiddenSyncPending = false;
}
