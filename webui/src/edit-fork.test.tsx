import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { Composer } from "./components/conversation/Composer";
import { MessageItem } from "./components/conversation/MessageItem";
import { MessageList } from "./components/conversation/MessageList";
import { conversationStore } from "./core/conversation";
import { sessionStore } from "./core/stores";
import type { ChatMessage } from "./core/types";

const REF = "attachment://aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";

beforeEach(() => {
  localStorage.clear();
  sessionStore.setCurrentSession("source-session");
  sessionStore.setModel(null);
  conversationStore.setState({
    messages: [],
    composerPrefill: null,
    hasMoreHistory: false,
    loadedHistoryCount: 0,
    streaming: false,
    backgroundRunning: false,
    streamingIndex: -1,
    lastError: null,
    streamStartedAt: null,
  });
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("immutable user edit via fork", () => {
  it("uses the server absolute index, keeps source history unchanged, and prefills the new branch without auto-send", async () => {
    let forkUrl = "";
    let chatCalls = 0;
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/api/v1/capabilities")) {
        return new Response(JSON.stringify({ capabilities: {} }), { status: 200 });
      }
      if (url.includes("/api/v1/models")) {
        return new Response(JSON.stringify({ models: ["glm/glm-5.3"], current: "glm/glm-5.3", catalog: [] }), { status: 200 });
      }
      if (url.includes("/fork")) {
        forkUrl = url;
        return new Response(JSON.stringify({ status: "ok", new_session_id: "branch-session", fork_point: 137 }), { status: 200 });
      }
      if (url.includes("/api/v1/sessions/branch-session/messages")) {
        return new Response(JSON.stringify({ session_id: "branch-session", messages: [], has_more: false, total: 0 }), { status: 200 });
      }
      if (url.includes("/api/v1/chat/stream/status")) {
        return new Response(JSON.stringify({ status: "idle" }), { status: 200 });
      }
      if (url.includes("/api/v1/chat/stream")) chatCalls += 1;
      return new Response(JSON.stringify({}), { status: 200 });
    }));

    const original: ChatMessage = {
      role: "user",
      sourceIndex: 137,
      content: "原始问题",
      attachments: [{ ref: REF, filename: "evidence.pdf", size_bytes: 1024 }],
    };
    render(
      <>
        <MessageItem msg={original} sessionId="source-session" index={137} />
        <Composer />
      </>
    );

    fireEvent.click(screen.getByRole("button", { name: "编辑并分支" }));
    const editor = screen.getByRole("textbox", { name: "编辑消息内容" });
    fireEvent.change(editor, { target: { value: "修改后的问题" } });
    fireEvent.click(screen.getByRole("button", { name: "创建分支并填入" }));

    await waitFor(() => expect(sessionStore.getState().currentSessionId).toBe("branch-session"));
    expect(forkUrl).toContain("fork_point=137");
    await waitFor(() => expect((screen.getByTestId("composer-input") as HTMLTextAreaElement).value).toBe("修改后的问题"));
    expect(screen.getByText("原始问题")).toBeInTheDocument();
    expect(screen.getAllByText("evidence.pdf")).toHaveLength(2);
    expect(chatCalls).toBe(0);
  });

  it("messages without a persisted absolute index never expose edit/fork or feedback actions", () => {
    render(<MessageItem msg={{ role: "user", content: "optimistic" }} sessionId="s1" />);
    expect(screen.queryByRole("button", { name: "编辑并分支" })).toBeNull();
  });

  it("assistant feedback uses persisted absolute index rather than rendered list position", async () => {
    let feedbackBody = "";
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.includes("/feedback")) {
        feedbackBody = String(init?.body ?? "");
        return new Response(JSON.stringify({ status: "ok" }), { status: 200 });
      }
      return new Response(JSON.stringify({}), { status: 200 });
    }));
    conversationStore.setState({
      messages: [{ role: "assistant", sourceIndex: 42, content: "answer" }],
      loadedHistoryCount: 1,
    });
    sessionStore.setCurrentSession("s1");
    render(<MessageList />);
    fireEvent.click(screen.getByTitle("回答有帮助"));
    await waitFor(() => expect(feedbackBody).not.toBe(""));
    expect(JSON.parse(feedbackBody).message_index).toBe(42);
  });
});
