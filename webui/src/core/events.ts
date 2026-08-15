// Web V2 核心：SSE 会话事件订阅（复用后端 /api/v1/events 命名事件；
// 对齐 v0.5.6 前端加固：失联自愈看门狗 + 标签页聚焦即刷）

import { fetchSessions, fetchSharedCurrent } from "./api";
import { sessionStore } from "./stores";

let lastSyncEvent = Date.now();
let es: EventSource | null = null;
const watchdogMs = 20000;
const staleThresholdMs = 25000;

function refreshFromSync(): void {
  void refreshSessionsAndCurrent();
}

export async function refreshSessionsAndCurrent(): Promise<void> {
  const sessions = await fetchSessions();
  sessionStore.setSessions(sessions);
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
}

export function initEventStream(): void {
  if (typeof EventSource === "undefined") return; // 老旧浏览器降级为手动刷新
  if (es) return;
  es = new EventSource("/api/v1/events");
  es.addEventListener("connected", () => {
    lastSyncEvent = Date.now();
    void refreshSessionsAndCurrent();
  });
  es.addEventListener("sessions_updated", () => {
    lastSyncEvent = Date.now();
    refreshFromSync();
  });
  // 看门狗：事件流静默失联（>25s 无事件且页面可见）→ 自愈刷新（SSE 健康时不触发）
  window.setInterval(() => {
    if (document.visibilityState === "visible" && Date.now() - lastSyncEvent > staleThresholdMs) {
      lastSyncEvent = Date.now();
      refreshFromSync();
    }
  }, watchdogMs);
  // 标签页重新聚焦 → 立即同步（后台标签页的 SSE/定时器会被浏览器节流）
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden && Date.now() - lastSyncEvent > 5000) {
      lastSyncEvent = Date.now();
      refreshFromSync();
    }
  });
}

export function stopEventStream(): void {
  if (es) {
    es.close();
    es = null;
  }
}
