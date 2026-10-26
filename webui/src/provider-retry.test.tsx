import { afterEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, render, screen, waitFor } from "@testing-library/react";
import { MessageList } from "./components/conversation/MessageList";
import { checkBackgroundRun, conversationStore, sendMessage } from "./core/conversation";
import { sessionStore } from "./core/stores";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  conversationStore.setState({ messages: [], streaming: false, streamingIndex: -1, activeRunGeneration: null });
  sessionStore.setCurrentSession("s1");
});

describe("provider retry progress", () => {
  it.each([false, true])("shows retry facts for fresh/resumed run (resume=%s) without polluting output", async (resume) => {
    sessionStore.setCurrentSession("s1");
    sessionStore.setNewSessionPending(false);
    conversationStore.setState({ messages: [], streaming: false, streamingIndex: -1, activeRunGeneration: null });
    const encoder = new TextEncoder();
    let channel!: ReadableStreamDefaultController<Uint8Array>;
    const push = (type: string, data: unknown) => channel.enqueue(
      encoder.encode(`data: ${JSON.stringify({ type, data })}\n\n`)
    );
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      if (String(input).includes("/api/v1/chat/stream/status")) {
        return new Response(JSON.stringify({ running: true, run_generation: "g1" }));
      }
      if (String(input).includes("/api/v1/chat/stream")) {
        return new Response(new ReadableStream<Uint8Array>({ start(controller) { channel = controller; } }));
      }
      return new Response(JSON.stringify({ messages: [] }));
    }));
    render(<MessageList />);
    const run = resume ? checkBackgroundRun("s1") : sendMessage("检查", []);
    await waitFor(() => expect(channel).toBeDefined());
    act(() => {
      push("run_started", { session_id: "s1", run_generation: "g1" });
      push("reasoning_delta", { data: "earlier " });
      push("reasoning_delta", { data: "round" });
      push("provider_retry", { reason: "timeout", retry_index: 1, max_retries: 1 });
    });
    await waitFor(() => {
      const st = conversationStore.getState();
      expect(st.messages[st.streamingIndex]?.progressStage).toBe("retrying");
      expect(screen.getByTestId("progress-card").textContent).toContain("模型请求超时，正在重试（1/1）");
      expect(st.messages[st.streamingIndex]?.content).toBe("");
      expect(st.messages[st.streamingIndex]?.reasoningContent).toBe("earlier round");
    });
    // A pending 120ms reasoning patch must not overwrite the retry stage.
    await new Promise((resolve) => window.setTimeout(resolve, 160));
    expect(screen.getByTestId("progress-card").textContent).toContain("正在重试");
    act(() => {
      push("answer_delta", { data: "已" });
      push("answer_delta", { data: "恢复" });
    });
    await waitFor(() => {
      expect(screen.getByTestId("progress-card").textContent).not.toContain("正在重试");
    });
    act(() => {
      push("done", { session_id: "s1", final_answer: "已恢复" });
      channel.close();
    });
    await run;
    expect(conversationStore.getState().messages.at(-1)?.content).toBe("已恢复");
    await waitFor(() => expect(screen.queryByTestId("progress-card")).toBeNull());
    // A trailing patch from the completed request cannot write into the next run.
    act(() => conversationStore.setState({
      messages: [{ role: "assistant", content: "", streaming: true, progressStage: "tool" }],
      streaming: true, streamingIndex: 0,
    }));
    await new Promise((resolve) => window.setTimeout(resolve, 160));
    expect(conversationStore.getState().messages[0]?.progressStage).toBe("tool");
    expect(conversationStore.getState().messages[0]?.content).toBe("");
  });
});
