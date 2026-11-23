import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { sessionStore } from "../../core/stores";

const h = vi.hoisted(() => ({
  loadHistory: vi.fn(),
  useConversation: vi.fn(),
}));

vi.mock("../../core/conversation", () => ({
  conversationStore: { setState: vi.fn() },
  loadHistory: h.loadHistory,
  useConversation: h.useConversation,
}));
vi.mock("./MessageList", () => ({ MessageList: () => <div>消息区</div> }));
vi.mock("./ChatQueue", () => ({ ChatQueue: () => null }));
vi.mock("./Composer", () => ({ Composer: () => null }));
vi.mock("./SessionStats", () => ({ SessionStats: () => <span>统计</span> }));
vi.mock("./ContinuityBanner", () => ({ ContinuityBanner: () => null }));
vi.mock("./ScheduleCatalog", () => ({ ScheduleCatalog: () => null }));
vi.mock("./JobsCatalog", () => ({ JobsCatalog: () => null }));
vi.mock("./SubagentLineage", () => ({ SubagentLineage: () => null }));

import { Conversation } from "./Conversation";

describe("Web history error recovery", () => {
  beforeEach(() => {
    h.loadHistory.mockReset().mockResolvedValue(undefined);
    h.useConversation.mockReturnValue({
      messages: [],
      backgroundRunning: false,
      lastError: "会话历史读取超时，请重试。",
    });
    sessionStore.setSessions([{
      session_id: "s1", title: "长会话", created_at: "t", updated_at: "t",
      message_count: 1, status: "active", pinned: false,
      channel: "web", last_message_preview: "hello",
    }]);
    sessionStore.setCurrentSession("s1");
  });

  afterEach(() => {
    cleanup();
    sessionStore.setCurrentSession("");
  });

  it("shows a read-only retry without suggesting a duplicate continue Run", async () => {
    render(<Conversation />);
    await waitFor(() => expect(h.loadHistory).toHaveBeenCalledTimes(1));
    expect(screen.getByRole("alert")).toHaveTextContent("会话历史读取超时");
    expect(screen.getByRole("alert")).toHaveTextContent("不会发送新的任务");
    expect(screen.getByRole("alert")).not.toHaveTextContent("输入「继续」");
    expect(screen.getByText("长会话")).toBeInTheDocument();
    expect(document.querySelector(".v2-conversation-header-actions")).not.toBeNull();

    let release!: () => void;
    h.loadHistory.mockImplementationOnce(() => new Promise<void>((resolve) => { release = resolve; }));
    fireEvent.click(screen.getByTestId("history-retry"));
    expect(h.loadHistory).toHaveBeenCalledTimes(2);
    expect(screen.getByTestId("history-retry")).toBeDisabled();
    expect(screen.getByTestId("history-retry")).toHaveTextContent("读取中");
    await act(async () => release());
    expect(screen.getByTestId("history-retry")).not.toBeDisabled();
  });

  it("distinguishes a still-running task from a failed history read", async () => {
    h.useConversation.mockReturnValue({
      messages: [],
      backgroundRunning: true,
      lastError: "会话历史读取超时，请重试。",
    });
    render(<Conversation />);
    await waitFor(() => expect(h.loadHistory).toHaveBeenCalledTimes(1));
    expect(screen.getByRole("alert")).toHaveTextContent("当前任务仍在运行");
    expect(screen.getByRole("alert")).toHaveTextContent("不会重复执行任务");
  });
});
