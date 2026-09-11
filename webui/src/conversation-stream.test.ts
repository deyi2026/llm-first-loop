import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { StreamOutcome } from "./core/types";

const h = vi.hoisted(() => ({
  pending: [] as Array<{
    body: Record<string, unknown>;
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
      (body: Record<string, unknown>, _handlers: unknown, signal?: AbortSignal) =>
        new Promise<StreamOutcome>((resolve) => h.pending.push({ body, signal, resolve }))
    );
    h.fetchHistory.mockResolvedValue({ messages: [], has_more: false });
    h.fetchStreamStatus.mockResolvedValue(null);
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ status: "ok" }), { status: 200 })));
    sessionStore.setCurrentSession("s1");
    resetConversation();
  });

  afterEach(() => {
    for (const p of h.pending) p.resolve(stopped);
    sessionStore.setCurrentSession("");
    resetConversation();
    vi.unstubAllGlobals();
  });

  it("切 s1→s2 只 detach s1 SSE，不发送 cancel", async () => {
    const run = sendMessage("A", []);
    await nextTurn();
    expect(h.pending).toHaveLength(1);
    expect(h.pending[0].signal?.aborted).toBe(false);

    sessionStore.setCurrentSession("s2");
    await loadHistory("s2");
    expect(h.pending[0].signal?.aborted).toBe(true);
    expect(vi.mocked(fetch)).not.toHaveBeenCalledWith(
      "/api/v1/chat/cancel",
      expect.anything()
    );

    h.pending[0].resolve(stopped);
    await run;
  });

  it("用户 Stop 会 abort 当前 owner 并取消同一 session", async () => {
    const run = sendMessage("A", []);
    await nextTurn();
    expect(h.pending).toHaveLength(1);

    stopStreaming();
    expect(h.pending[0].signal?.aborted).toBe(true);
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
    expect(msg?.toolActivities?.[0]?.status).toBe("interrupted");
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
