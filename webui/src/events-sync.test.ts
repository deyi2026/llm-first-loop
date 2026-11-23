import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const h = vi.hoisted(() => ({
  fetchSessionsResult: vi.fn(),
  refreshCurrentSessionMessages: vi.fn(),
}));

vi.mock("./core/api", () => ({
  fetchSessionsResult: h.fetchSessionsResult,
  fetchSharedCurrent: vi.fn(),
  notifyProvidersUpdated: vi.fn(),
}));
vi.mock("./core/conversation", () => ({
  refreshCurrentSessionMessages: h.refreshCurrentSessionMessages,
}));
vi.mock("./core/chat", () => ({ notifyModelCatalogChanged: vi.fn() }));
vi.mock("./core/sessionUrl", () => ({ readSessionIdFromLocation: () => null }));

import { initEventStream, stopEventStream } from "./core/events";
import { sessionStore } from "./core/stores";
import { clearAuthRequired, reportUnauthorized } from "./core/authSession";

const s1 = {
  session_id: "s1", title: "当前", created_at: "t0", updated_at: "t1",
  message_count: 2, last_message_preview: "old", status: "active",
  pinned: false, channel: "web",
};
const s2 = { ...s1, session_id: "s2", title: "其他" };
let source: EventTarget;
let closedSources = 0;

class FakeEventSource {
  constructor(_url: string) {}
  addEventListener(type: string, cb: EventListenerOrEventListenerObject): void {
    source.addEventListener(type, cb);
  }
  close(): void { closedSources += 1; }
}

async function settle(): Promise<void> {
  for (let i = 0; i < 12; i++) await Promise.resolve();
}

describe("SSE 会话更新去重", () => {
  beforeEach(() => {
    clearAuthRequired();
    vi.useFakeTimers();
    source = new EventTarget();
    closedSources = 0;
    vi.stubGlobal("EventSource", FakeEventSource);
    h.fetchSessionsResult.mockReset();
    h.refreshCurrentSessionMessages.mockReset().mockResolvedValue(undefined);
    sessionStore.setSessions([s1, s2]);
    sessionStore.setCurrentSession("s1");
  });

  afterEach(() => {
    stopEventStream();
    clearAuthRequired();
    vi.clearAllTimers();
    vi.useRealTimers();
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
    sessionStore.setCurrentSession("");
    sessionStore.setSessions([]);
  });

  it("401 登录失效后关闭 SSE，停止看门狗和历史同步，不重复订阅", async () => {
    initEventStream();
    reportUnauthorized(401);
    expect(closedSources).toBe(1);
    source.dispatchEvent(new Event("sessions_updated"));
    await settle();
    expect(h.fetchSessionsResult).not.toHaveBeenCalled();
    initEventStream(); // login is still expired
    expect(closedSources).toBe(1);
  });

  it("其他会话变化只更新列表，不全量重载当前会话；当前变化仍立即刷新", async () => {
    initEventStream();
    h.fetchSessionsResult.mockResolvedValueOnce({
      ok: true, status: 200, sessions: [s1, { ...s2, updated_at: "t2", message_count: 3 }],
    });
    source.dispatchEvent(new Event("sessions_updated"));
    await settle();
    expect(h.refreshCurrentSessionMessages).not.toHaveBeenCalled();

    h.fetchSessionsResult.mockResolvedValueOnce({
      ok: true, status: 200,
      sessions: [{ ...s1, updated_at: "t3", message_count: 3, last_message_preview: "new" }, s2],
    });
    source.dispatchEvent(new Event("sessions_updated"));
    await settle();
    expect(h.refreshCurrentSessionMessages).toHaveBeenCalledTimes(1);
  });

  it("并发事件合并为最多一次补读，不丢失在途期间的会话变化", async () => {
    initEventStream();
    let finish!: (value: unknown) => void;
    h.fetchSessionsResult.mockImplementationOnce(
      () => new Promise((resolve) => { finish = resolve; })
    );
    h.fetchSessionsResult.mockResolvedValueOnce({
      ok: true, status: 200, sessions: [{ ...s1, updated_at: "t2" }, s2],
    });
    source.dispatchEvent(new Event("sessions_updated"));
    source.dispatchEvent(new Event("sessions_updated"));
    source.dispatchEvent(new Event("sessions_updated"));
    expect(h.fetchSessionsResult).toHaveBeenCalledTimes(1);
    finish({ ok: true, status: 200, sessions: [{ ...s1, updated_at: "t2" }, s2] });
    await settle();
    expect(h.fetchSessionsResult).toHaveBeenCalledTimes(2);
    expect(h.refreshCurrentSessionMessages).toHaveBeenCalledTimes(1);
  });

  it("隐藏标签页跳过 SSE 列表与历史读取，恢复可见后立即补读", async () => {
    const hidden = vi.spyOn(document, "hidden", "get").mockReturnValue(true);
    initEventStream();
    source.dispatchEvent(new Event("sessions_updated"));
    await settle();
    expect(h.fetchSessionsResult).not.toHaveBeenCalled();

    h.fetchSessionsResult.mockResolvedValueOnce({
      ok: true, status: 200, sessions: [{ ...s1, updated_at: "t2" }, s2],
    });
    hidden.mockReturnValue(false);
    document.dispatchEvent(new Event("visibilitychange"));
    await settle();
    expect(h.fetchSessionsResult).toHaveBeenCalledTimes(1);
    expect(h.refreshCurrentSessionMessages).toHaveBeenCalledTimes(1);
    hidden.mockRestore();
  });

  it("列表读取失败时保留现有消息，不将失败当成会话清空", async () => {
    initEventStream();
    h.fetchSessionsResult.mockResolvedValueOnce({ ok: false, status: 503, sessions: [] });
    source.dispatchEvent(new Event("sessions_updated"));
    await settle();
    expect(h.refreshCurrentSessionMessages).not.toHaveBeenCalled();
    expect(sessionStore.getState().sessions).toHaveLength(2);
  });
});
