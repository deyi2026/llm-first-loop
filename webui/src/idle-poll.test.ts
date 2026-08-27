// 空闲增量轮询单测（飞书桥外部写入 → Web 自动刷新）
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const h = vi.hoisted(() => ({
  fetchHistory: vi.fn(),
  fetchStreamStatus: vi.fn(),
}));

vi.mock("./core/chat", async (importOriginal) => {
  const actual = await importOriginal<typeof import("./core/chat")>();
  return { ...actual, fetchHistory: h.fetchHistory, fetchStreamStatus: h.fetchStreamStatus };
});

import { conversationStore, ensureIdlePoll, loadHistory } from "./core/conversation";
import { sessionStore } from "./core/stores";

const msgA = { role: "assistant", content: "旧回答" };
const msgB = { role: "user", content: "新飞书消息" };

function resetState(): void {
  conversationStore.setState({
    messages: [],
    hasMoreHistory: false,
    loadedHistoryCount: 0,
    streaming: false,
    backgroundRunning: false,
    streamingIndex: -1,
    lastError: null,
    streamStartedAt: null,
  });
}

async function flush(): Promise<void> {
  await Promise.resolve();
  await Promise.resolve();
  await Promise.resolve();
}

describe("idle poll（空闲增量刷新）", () => {
  beforeEach(() => {
    resetState();
    h.fetchHistory.mockReset();
    h.fetchStreamStatus.mockReset();
    h.fetchStreamStatus.mockResolvedValue(null); // 无后台 run
    sessionStore.setCurrentSession("s1");
    vi.useFakeTimers(); // 先装假时钟，loadHistory 内注册的 interval 才可被推进
  });

  afterEach(() => {
    sessionStore.setCurrentSession("s-other"); // 切走 → stopIdlePoll
    vi.useRealTimers();
  });

  it("指纹未变 → 只探针不重载；变化 → 触发整窗重载", async () => {
    // 基线：loadHistory 建立会话视图 + 指纹 + 启动轮询
    h.fetchHistory.mockResolvedValueOnce({ messages: [msgA], has_more: false });
    await loadHistory("s1");
    await flush();
    expect(conversationStore.getState().messages).toHaveLength(1);
    h.fetchHistory.mockClear();

    // 跳1：服务端最新消息仍是最旧回答 → 仅探针更新基线
    h.fetchHistory.mockResolvedValueOnce({ messages: [msgA], has_more: false });
    await vi.advanceTimersByTimeAsync(20_000);
    expect(h.fetchHistory).toHaveBeenCalledTimes(1);
    expect(h.fetchHistory).toHaveBeenLastCalledWith("s1", 1, 0); // limit=1 探针
    expect(conversationStore.getState().messages).toHaveLength(1);

    // 跳2：飞书写入新消息 → 指纹变化 → 整窗重载
    h.fetchHistory.mockReset();
    h.fetchStreamStatus.mockResolvedValue(null);
    h.fetchHistory.mockResolvedValueOnce({ messages: [msgB], has_more: false }); // 探针
    h.fetchHistory.mockResolvedValue({ messages: [msgA, msgB], has_more: false }); // 重载
    await vi.advanceTimersByTimeAsync(20_000);
    await flush();
    const msgs = conversationStore.getState().messages;
    expect(msgs).toHaveLength(2);
    expect(msgs[msgs.length - 1].content).toBe("新飞书消息");
  });

  it("幂等：同会话重复 ensure 不重启；空会话不探针", async () => {
    h.fetchHistory.mockResolvedValueOnce({ messages: [msgA], has_more: false });
    await loadHistory("s1");
    await flush();
    const si = vi.spyOn(globalThis, "setInterval");
    ensureIdlePoll("s1"); // 同会话幂等
    expect(si).not.toHaveBeenCalled();
    si.mockRestore();

    // 空会话：loadedHistoryCount=0 → tick 直接退出
    sessionStore.setCurrentSession("s2");
    h.fetchHistory.mockClear().mockResolvedValue({ messages: [], has_more: false });
    await loadHistory("s2");
    await flush();
    h.fetchHistory.mockClear();
    await vi.advanceTimersByTimeAsync(60_000);
    expect(h.fetchHistory).not.toHaveBeenCalled();
  });

  it("流式进行中 → tick 让路不探针", async () => {
    h.fetchHistory.mockResolvedValueOnce({ messages: [msgA], has_more: false });
    await loadHistory("s1");
    await flush();
    conversationStore.setState({ streaming: true, streamingIndex: 0 });
    h.fetchHistory.mockClear();
    await vi.advanceTimersByTimeAsync(60_000);
    expect(h.fetchHistory).not.toHaveBeenCalled();
  });
});
