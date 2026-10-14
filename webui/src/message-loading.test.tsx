import { afterEach, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { Conversation } from "./components/conversation/Conversation";
import { sessionStore } from "./core/stores";
import { conversationStore } from "./core/conversation";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  sessionStore.setCurrentSession("");
  conversationStore.setState({ messages: [], lastError: null });
});

it("shows a loading state instead of a false new-chat hero while an existing session loads", async () => {
  sessionStore.setSessions([{
    session_id: "history-delayed", title: "已存在的会话",
    created_at: "", updated_at: "", channel: "web", message_count: 1,
    status: "active", pinned: false, last_message_preview: "",
  }]);
  sessionStore.setCurrentSession("history-delayed");
  let release!: (response: Response) => void;
  const pending = new Promise<Response>((resolve) => { release = resolve; });
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    if (String(input).includes("/api/v1/sessions/history-delayed/messages")) return pending;
    return new Response(JSON.stringify({}), { status: 200 });
  }));

  render(<Conversation />);
  expect(screen.getByText("正在加载会话历史…")).toBeInTheDocument();
  expect(screen.queryByTestId("empty-state")).toBeNull();

  await act(async () => {
    release(new Response(JSON.stringify({
      session_id: "history-delayed", total: 1, has_more: false,
      messages: [{ role: "user", content: "历史已恢复" }],
    }), { status: 200 }));
    await pending;
  });
  expect(await screen.findByText("历史已恢复")).toBeInTheDocument();
  expect(screen.queryByText("正在加载会话历史…")).toBeNull();
});

it("failed history read offers a retry without resending the chat message", async () => {
  sessionStore.setSessions([{
    session_id: "retry-history", title: "需要恢复的会话",
    created_at: "", updated_at: "", channel: "web", message_count: 1,
    status: "active", pinned: false, last_message_preview: "",
  }]);
  sessionStore.setCurrentSession("retry-history");
  let reads = 0;
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    if (String(input).includes("/api/v1/sessions/retry-history/messages")) {
      reads++;
      if (reads === 1) return new Response(JSON.stringify({ detail: "read unavailable" }), { status: 503 });
      return new Response(JSON.stringify({
        session_id: "retry-history", total: 1, has_more: false,
        messages: [{ role: "user", content: "原始历史成功恢复" }],
      }), { status: 200 });
    }
    return new Response(JSON.stringify({}), { status: 200 });
  }));
  render(<Conversation />);
  expect(await screen.findByTestId("history-error")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "重新加载会话" }));
  expect(await screen.findByText("原始历史成功恢复")).toBeInTheDocument();
  expect(reads).toBe(2);
});
