import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { StreamOutcome } from "./core/types";

const h = vi.hoisted(() => ({
  pending: [] as Array<{
    body: Record<string, unknown>;
    handlers: any;
    signal?: AbortSignal;
    resolve: (value: StreamOutcome) => void;
  }>,
  streamChatRequest: vi.fn(),
  fetchHistory: vi.fn(),
  fetchStreamStatus: vi.fn(),
}));

vi.mock("./core/chat", async (importOriginal) => {
  const actual = await importOriginal<typeof import("./core/chat")>();
  return {
    ...actual,
    streamChatRequest: h.streamChatRequest,
    fetchHistory: h.fetchHistory,
    fetchStreamStatus: h.fetchStreamStatus,
  };
});

import {
  conversationStore,
  checkBackgroundRun,
  loadEarlierHistory,
  loadHistory,
  sendMessage,
  stopStreaming,
} from "./core/conversation";
import { sessionStore } from "./core/stores";

const stopped: StreamOutcome = {
  ok: false,
  errorType: "network",
  error: { detail: "已停止" },
  data: null,
};

function resetConversation(): void {
  conversationStore.setState({
    messages: [],
    hasMoreHistory: false,
    loadedHistoryCount: 0,
    streaming: false,
    backgroundRunning: false,
    activeRunGeneration: null,
    streamingIndex: -1,
    lastError: null,
    streamStartedAt: null,
  });
}

async function nextTurn(): Promise<void> {
  await Promise.resolve();
  await Promise.resolve();
}

describe("conversation stream ownership", () => {
  beforeEach(() => {
    h.pending.length = 0;
    h.streamChatRequest.mockReset();
    h.fetchHistory.mockReset();
    h.fetchStreamStatus.mockReset();
    h.streamChatRequest.mockImplementation(
      (body: Record<string, unknown>, handlers: any, signal?: AbortSignal) =>
        new Promise<StreamOutcome>((resolve) => h.pending.push({ body, handlers, signal, resolve }))
    );
    h.fetchHistory.mockResolvedValue({ messages: [], has_more: false });
    h.fetchStreamStatus.mockResolvedValue(null);
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ status: "ok" }), { status: 200 })));
    sessionStore.setCurrentSession("s1");
    sessionStore.setNewSessionPending(false);
    resetConversation();
  });

  afterEach(() => {
    for (const p of h.pending) p.resolve(stopped);
    sessionStore.setCurrentSession("");
    sessionStore.setNewSessionPending(false);
    resetConversation();
    vi.unstubAllGlobals();
  });

  it("new-session guard stays armed until run_started binds the exact new session", async () => {
    sessionStore.setCurrentSession("");
    sessionStore.setNewSessionPending(true);

    const run = sendMessage("fresh", []);
    await nextTurn();
    expect(h.pending).toHaveLength(1);
    const pending = h.pending[0];
    expect(pending.body).toMatchObject({ new_session: true });
    const optimisticCount = conversationStore.getState().messages.length;
    expect(optimisticCount).toBeGreaterThan(0);
    expect(sessionStore.getState().currentSessionId).toBe("");
    expect(sessionStore.getState().newSessionPending).toBe(true);
    expect(pending.signal?.aborted).toBe(false);

    pending.handlers.onRunStarted?.({ session_id: "s-new", run_generation: "g-new" });
    expect(sessionStore.getState().currentSessionId).toBe("s-new");
    expect(sessionStore.getState().newSessionPending).toBe(false);
    expect(pending.signal?.aborted).toBe(false);
    expect(conversationStore.getState().activeRunGeneration).toBe("g-new");
    expect(conversationStore.getState().messages).toHaveLength(optimisticCount);

    pending.resolve({
      ok: true,
      errorType: null,
      error: null,
      data: { session_id: "s-new", final_answer: "ok" },
    } satisfies StreamOutcome);
    await run;
    expect(conversationStore.getState().activeRunGeneration).toBeNull();
  });

  // 2026-10-13 newSessionPending 卡死回归：newSessionPending 与残留 currentSessionId
  // 并存时（前端状态异常组合），请求同传 session_id + new_session；schema 契约下服务端
  // 必然分配全新 sid，旧 owner guard（新sid ≠ 发送前 owner）会拦掉 onRunStarted 剩余
  // 逻辑——若清 pending 在 guard 之后将永久卡 true（SSE/看门狗回填被 events.ts 挡死）。
  it("clears newSessionPending even when run_started sid mismatches stale owner (session_id+new_session combo)", async () => {
    sessionStore.setCurrentSession("s-stale");
    sessionStore.setNewSessionPending(true);

    const run = sendMessage("fresh", []);
    await nextTurn();
    expect(h.pending).toHaveLength(1);
    const pending = h.pending[0];
    expect(pending.body).toMatchObject({ session_id: "s-stale", new_session: true });
    expect(sessionStore.getState().newSessionPending).toBe(true);

    pending.handlers.onRunStarted?.({ session_id: "s-new", run_generation: "g-new" });
    // 核心断言：pending 已清除，不被 owner guard 卡死
    expect(sessionStore.getState().newSessionPending).toBe(false);
    // 最小修法边界：视图绑定规则不变——既有会话（sessionId 非空）的 run_started
    // 新 sid 不得把视图拽走，currentSessionId 保持发送前值
    expect(sessionStore.getState().currentSessionId).toBe("s-stale");

    pending.resolve({
      ok: true,
      errorType: null,
      error: null,
      data: { session_id: "s-new", final_answer: "ok" },
    } satisfies StreamOutcome);
    await run;
  });

  it("fresh run 网络断流后只用 run_started 的 exact generation 续联，不猜 latest", async () => {
    h.streamChatRequest
      .mockImplementationOnce(async (_body: Record<string, unknown>, handlers: any) => {
        handlers.onRunStarted?.({ session_id: "s1", run_generation: "gen-fresh-1" });
        handlers.onReasoningDelta?.("断流前推理");
        return {
          ok: false,
          errorType: "network",
          error: { detail: "连接中断，已保留已生成内容" },
          data: null,
        } satisfies StreamOutcome;
      })
      .mockResolvedValueOnce({
        ok: true,
        errorType: null,
        error: null,
        data: { session_id: "s1", final_answer: "done", reasoning_content: "完整推理" },
      } satisfies StreamOutcome);

    await sendMessage("A", []);
    expect(h.streamChatRequest).toHaveBeenCalledTimes(2);
    expect(h.streamChatRequest.mock.calls[1]?.[0]).toMatchObject({
      message: "resume",
      session_id: "s1",
      resume: true,
      run_generation: "gen-fresh-1",
    });
  });

  it("delivers voice answers for consecutive turns even when the second stream reconnects", async () => {
    const onSuccess = vi.fn();
    h.streamChatRequest.mockResolvedValueOnce({
      ok: true, errorType: null, error: null,
      data: { session_id: "s1", final_answer: "第一轮回答" },
    } satisfies StreamOutcome);
    await sendMessage("第一轮", [], undefined, onSuccess);
    h.streamChatRequest.mockImplementationOnce(async (_body: Record<string, unknown>, handlers: any) => {
      handlers.onRunStarted?.({ session_id: "s1", run_generation: "voice-turn-2" });
      return { ok: false, errorType: "network", error: { detail: "连接中断" }, data: null } satisfies StreamOutcome;
    }).mockResolvedValueOnce({
      ok: true, errorType: null, error: null,
      data: { session_id: "s1", final_answer: "第二轮完整回答" },
    } satisfies StreamOutcome);
    await sendMessage("第二轮", [], undefined, onSuccess);
    expect(onSuccess.mock.calls).toEqual([["第一轮回答"], ["第二轮完整回答"]]);
    expect(h.streamChatRequest.mock.calls[2]?.[0]).toMatchObject({ resume: true, run_generation: "voice-turn-2" });
  });

  it("does not speak a recovered answer after the user stops that run", async () => {
    const onSuccess = vi.fn();
    h.streamChatRequest.mockImplementationOnce(async (_body: Record<string, unknown>, handlers: any) => {
      handlers.onRunStarted?.({ session_id: "s1", run_generation: "voice-stopped" });
      return { ok: false, errorType: "network", error: { detail: "连接中断" }, data: null } satisfies StreamOutcome;
    });
    const running = sendMessage("语音请求", [], undefined, onSuccess);
    await nextTurn();
    expect(h.pending).toHaveLength(1);
    stopStreaming();
    expect(h.pending[0].signal?.aborted).toBe(true);
    h.pending[0].resolve({ ok: true, errorType: null, error: null, data: { session_id: "s1", final_answer: "过时回复" } });
    await running;
    expect(onSuccess).not.toHaveBeenCalled();
  });

  it("刷新/切回后台 run 时 resume 必须精确携带 status 的 run_generation", async () => {
    h.fetchStreamStatus.mockResolvedValueOnce({ running: true, run_generation: "gen-live-1" });
    h.streamChatRequest.mockResolvedValueOnce({
      ok: true,
      errorType: null,
      error: null,
      data: { session_id: "s1", final_answer: "done", reasoning_content: "实时推理" },
    } satisfies StreamOutcome);

    await checkBackgroundRun("s1");
    expect(h.streamChatRequest).toHaveBeenCalledTimes(1);
    expect(h.streamChatRequest.mock.calls[0]?.[0]).toMatchObject({
      message: "resume",
      session_id: "s1",
      resume: true,
      run_generation: "gen-live-1",
    });
  });

  it("非 Web ingress 会话被 409 拒绝后，下一条机械进入新 Web session，不重复撞旧会话", async () => {
    sessionStore.setNewSessionPending(false);
    h.streamChatRequest.mockResolvedValueOnce({
      ok: false,
      errorType: "http",
      error: { error: "session_ingress_mismatch", detail: "该会话来自其他入口" },
      data: null,
    } satisfies StreamOutcome);

    await sendMessage("A", []);
    expect(sessionStore.getState().currentSessionId).toBe("s1");
    expect(sessionStore.getState().newSessionPending).toBe(true);
    expect(conversationStore.getState().lastError).toContain("该会话来自其他入口");

    h.streamChatRequest.mockResolvedValueOnce({
      ok: true, errorType: null, error: null,
      data: { session_id: "s-new", final_answer: "ok" },
    } satisfies StreamOutcome);
    await sendMessage("B", []);
    expect(h.streamChatRequest.mock.calls[1]?.[0]).toMatchObject({
      session_id: "s1",
      new_session: true,
    });
  });

  it("切 s1→s2 只 detach s1 SSE，不发送 cancel", async () => {
    const run = sendMessage("A", []);
    await nextTurn();
    expect(h.pending).toHaveLength(1);
    expect(h.pending[0].signal?.aborted).toBe(false);
    h.pending[0].handlers.onRunStarted?.({ session_id: "s1", run_generation: "gen-s1-live" });
    expect(conversationStore.getState().activeRunGeneration).toBe("gen-s1-live");

    sessionStore.setCurrentSession("s2");
    await loadHistory("s2");
    expect(h.pending[0].signal?.aborted).toBe(true);
    expect(conversationStore.getState().activeRunGeneration).toBeNull();
    expect(vi.mocked(fetch)).not.toHaveBeenCalledWith(
      "/api/v1/chat/cancel",
      expect.anything()
    );

    h.pending[0].resolve(stopped);
    await run;
  });

  it("用户切会话时立即清掉旧消息/队列/错误，不能在新 header 下短暂展示旧会话事实", () => {
    conversationStore.setState({
      messages: [{ role: "assistant", content: "s1 私有内容" }],
      queueItems: [{
        queue_id: "q-s1",
        session_id: "s1",
        message: "旧排队",
        attachments: [],
        attachment_facts: [],
        model: null,
        reasoning_effort: null,
        reasoning_mode: "auto",
        status: "queued",
        created_at: 1,
      }],
      loadedHistoryCount: 1,
      hasMoreHistory: true,
      lastError: "s1 error",
    });
    sessionStore.setCurrentSession("s2");
    const next = conversationStore.getState();
    expect(next.messages).toEqual([]);
    expect(next.queueItems).toEqual([]);
    expect(next.loadedHistoryCount).toBe(0);
    expect(next.hasMoreHistory).toBe(false);
    expect(next.lastError).toBeNull();
  });

  it("history 读取失败保留当前已知消息并显示错误，不伪装成空会话", async () => {
    conversationStore.setState({
      messages: [{ role: "assistant", content: "已知回答" }],
      loadedHistoryCount: 1,
      lastError: null,
    });
    h.fetchHistory.mockResolvedValueOnce({
      ok: false,
      error: "会话历史读取失败（HTTP 503）",
      messages: [],
      has_more: false,
    });
    await loadHistory("s1");
    expect(conversationStore.getState().messages).toEqual([{ role: "assistant", content: "已知回答" }]);
    expect(conversationStore.getState().lastError).toContain("HTTP 503");
  });

  it("加载更早的旧会话迟到响应不得污染已经切换的新会话", async () => {
    let resolveHistory!: (value: { messages: Array<{ role: string; content: string }>; has_more: boolean }) => void;
    h.fetchHistory.mockImplementationOnce(() => new Promise((resolve) => { resolveHistory = resolve; }));
    conversationStore.setState({
      messages: [{ role: "assistant", content: "s1 当前" }],
      loadedHistoryCount: 1,
      hasMoreHistory: true,
    });
    const pending = loadEarlierHistory("s1");
    sessionStore.setCurrentSession("s2");
    conversationStore.setState({
      messages: [{ role: "assistant", content: "s2 当前" }],
      loadedHistoryCount: 1,
      hasMoreHistory: false,
    });
    resolveHistory({ messages: [{ role: "user", content: "s1 更早" }], has_more: false });
    await pending;
    expect(conversationStore.getState().messages).toEqual([{ role: "assistant", content: "s2 当前" }]);
  });

  it("用户 Stop 会 abort 当前 owner 并取消同一 session", async () => {
    const run = sendMessage("A", []);
    await nextTurn();
    expect(h.pending).toHaveLength(1);
    h.pending[0].handlers.onRunStarted?.({ session_id: "s1", run_generation: "gen-stop-1" });
    expect(conversationStore.getState().activeRunGeneration).toBe("gen-stop-1");

    stopStreaming();
    expect(h.pending[0].signal?.aborted).toBe(true);
    expect(conversationStore.getState().activeRunGeneration).toBeNull();
    expect(vi.mocked(fetch)).toHaveBeenCalledWith(
      "/api/v1/chat/cancel",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ session_id: "s1" }),
      })
    );

    h.pending[0].resolve(stopped);
    await run;
  });

  it("旧 s1 异步收尾不得清掉 s2 的新 controller", async () => {
    const run1 = sendMessage("A", []);
    await nextTurn();
    const first = h.pending[0];

    sessionStore.setCurrentSession("s2");
    await loadHistory("s2");
    const run2 = sendMessage("B", []);
    await nextTurn();
    const second = h.pending[1];
    expect(first.signal?.aborted).toBe(true);
    expect(second.signal?.aborted).toBe(false);

    first.resolve(stopped);
    await run1;
    expect(second.signal?.aborted).toBe(false);

    stopStreaming();
    expect(second.signal?.aborted).toBe(true);
    expect(vi.mocked(fetch)).toHaveBeenCalledWith(
      "/api/v1/chat/cancel",
      expect.objectContaining({ body: JSON.stringify({ session_id: "s2" }) })
    );
    second.resolve(stopped);
    await run2;
  });


  it("tool_round 只表示运行中；模型分片不猜成功，exact tool_result 才收敛终态", async () => {
    h.streamChatRequest.mockImplementationOnce(async (_body, handlers: any) => {
      handlers.onToolRound?.({
        tool_call_id: "c1",
        tool_name: "read_file",
        round_index: 1,
        args_summary: '{"path":"README.md"}',
      });
      let msg = conversationStore.getState().messages.at(-1);
      expect(msg?.toolActivities?.[0]).toMatchObject({ id: "c1", name: "read_file", status: "running" });

      handlers.onReasoningDelta?.("继续判断");
      msg = conversationStore.getState().messages.at(-1);
      expect(msg?.toolActivities?.[0]?.status).toBe("running");

      handlers.onToolResult?.({
        tool_call_id: "c1",
        tool_name: "read_file",
        status: "failure",
        duration_ms: 12.5,
      });
      msg = conversationStore.getState().messages.at(-1);
      expect(msg?.toolActivities?.[0]).toMatchObject({ status: "failure", durationMs: 12.5 });

      // Later provider text and a replayed start event cannot rewrite an exact terminal fact.
      handlers.onAnswerDelta?.("继续");
      handlers.onToolRound?.({
        tool_call_id: "c1",
        tool_name: "read_file",
        round_index: 1,
        args_summary: '{"path":"README.md"}',
      });
      msg = conversationStore.getState().messages.at(-1);
      expect(msg?.toolActivities?.[0]?.status).toBe("failure");

      handlers.onToolRound?.({
        tool_call_id: "c2",
        tool_name: "search_text",
        round_index: 2,
        args_summary: '{"query":"needle"}',
      });
      return {
        ok: true,
        errorType: null,
        error: null,
        data: {
          session_id: "s1",
          final_answer: "done",
          tool_calls: [
            { id: "c1", name: "read_file", arguments: { path: "README.md" }, status: "failure" },
            { id: "c2", name: "search_text", arguments: { query: "needle" }, status: "failure" },
          ],
        },
      } satisfies StreamOutcome;
    });

    await sendMessage("A", []);
    const msg = conversationStore.getState().messages.at(-1);
    expect(msg?.toolActivities).toHaveLength(2);
    expect(msg?.toolActivities?.[0]?.status).toBe("failure");
    expect(msg?.toolActivities?.[1]?.status).toBe("failure");
  });

  it("同一 round 的多个工具在执行前都保持 running，不把前一个误判为完成", async () => {
    h.streamChatRequest.mockImplementationOnce(async (_body, handlers: any) => {
      handlers.onToolRound?.({ tool_call_id: "c1", tool_name: "read_file", round_index: 1, args_summary: '{"path":"a"}' });
      handlers.onToolRound?.({ tool_call_id: "c2", tool_name: "read_file", round_index: 1, args_summary: '{"path":"b"}' });
      const live = conversationStore.getState().messages.at(-1)?.toolActivities;
      expect(live?.map((item) => item.status)).toEqual(["running", "running"]);
      return {
        ok: true, errorType: null, error: null,
        data: { final_answer: "done", tool_calls: [
          { id: "c1", name: "read_file", arguments: { path: "a" }, status: "success" },
          { id: "c2", name: "read_file", arguments: { path: "b" }, status: "success" },
        ] },
      } satisfies StreamOutcome;
    });
    await sendMessage("A", []);
  });

  it("旧后端只有 tool_round + done 且无status时只收敛为中性completed，不伪装success", async () => {
    h.streamChatRequest.mockImplementationOnce(async (_body, handlers: any) => {
      handlers.onToolRound?.({ tool_call_id: "legacy-c1", tool_name: "read_file", round_index: 1 });
      return {
        ok: true, errorType: null, error: null,
        data: { final_answer: "done", tool_calls: [
          { id: "legacy-c1", name: "read_file", arguments: { path: "legacy" } },
        ] },
      } satisfies StreamOutcome;
    });
    await sendMessage("legacy", []);
    expect(conversationStore.getState().messages.at(-1)?.toolActivities?.[0]?.status).toBe("completed");
  });

  it("流中断时仍在 running 的工具如实标成 interrupted", async () => {
    h.streamChatRequest.mockImplementationOnce(async (_body, handlers: any) => {
      handlers.onToolRound?.({ tool_call_id: "c1", tool_name: "execute_command", round_index: 1 });
      return {
        ok: false,
        errorType: "network",
        error: { detail: "连接中断，已保留已生成内容" },
        data: null,
      } satisfies StreamOutcome;
    });

    await sendMessage("A", []);
    const msg = conversationStore.getState().messages.at(-1);
    expect(msg?.toolActivities?.[0]?.status).toBe("unknown");
    expect(msg?.note).toContain("不代表 LFL 已停止");
  });

  it("空正文 done 保留已流式 reasoning，并展示 fallback/推理实际状态", async () => {
    h.streamChatRequest.mockImplementationOnce(async (_body, handlers: any) => {
      handlers.onReasoningDelta?.("已收到推理");
      return {
        ok: true,
        errorType: null,
        error: null,
        data: {
          session_id: "s1",
          final_answer: "",
          tool_calls: [],
          reasoning_content: null,
          fallback_receipt: { from: "p/a", to: "p/b", reason: "unavailable" },
          reasoning_mode: "on",
          reasoning_capable: true,
          reasoning_control: "chat_template",
          reasoning_supported: true,
          reasoning_effective: true,
          reasoning_tokens: 12,
        },
      } satisfies StreamOutcome;
    });

    await sendMessage("A", []);

    const msg = conversationStore.getState().messages.at(-1);
    expect(msg?.content).toBe("（无文字回答）");
    expect(msg?.reasoningContent).toBe("已收到推理");
    expect(msg?.note).toContain("模型回退：p/a → p/b（unavailable）");
    expect(msg?.note).toContain("mode=on");
    expect(msg?.note).toContain("control=chat_template");
    expect(msg?.note).toContain("effective=true");
    expect(msg?.note).toContain("tokens=12");
  });
});
