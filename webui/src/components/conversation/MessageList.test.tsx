import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { sessionStore } from "../../core/stores";

const h = vi.hoisted(() => ({
  loadEarlierHistory: vi.fn(),
  useConversation: vi.fn(),
  setState: vi.fn(),
}));
vi.mock("../../core/conversation", () => ({
  conversationStore: { setState: h.setState },
  loadEarlierHistory: h.loadEarlierHistory,
  loadHistory: vi.fn(),
  useConversation: h.useConversation,
}));
vi.mock("./MessageItem", () => ({
  MessageItem: ({ msg }: { msg: { content: string } }) => <div>{msg.content}</div>,
  extractProducedPaths: () => [],
}));

import { MessageList } from "./MessageList";

describe("Web history pagination interaction", () => {
  beforeEach(() => {
    h.loadEarlierHistory.mockReset().mockResolvedValue(undefined);
    h.setState.mockReset();
    h.useConversation.mockReturnValue({
      messages: [{ role: "user", content: "old" }],
      hasMoreHistory: true,
      lastError: null,
    });
    sessionStore.setCurrentSession("s1");
  });
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
    sessionStore.setCurrentSession("");
  });

  it("disables duplicate clicks and preserves the viewport when older rows are prepended", async () => {
    let release!: () => void;
    h.loadEarlierHistory.mockImplementationOnce(() => new Promise<void>((resolve) => { release = resolve; }));
    let height = 200;
    vi.stubGlobal("requestAnimationFrame", (cb: FrameRequestCallback) => { cb(0); return 1; });
    render(<MessageList />);
    const list = screen.getByTestId("message-list");
    Object.defineProperty(list, "scrollHeight", { configurable: true, get: () => height });
    list.scrollTop = 25;
    const button = screen.getByRole("button", { name: /加载更早|更早消息/ });
    fireEvent.click(button);
    expect(h.loadEarlierHistory).toHaveBeenCalledTimes(1);
    expect(button).toBeDisabled();
    fireEvent.click(button);
    expect(h.loadEarlierHistory).toHaveBeenCalledTimes(1);
    height = 350;
    await act(async () => release());
    expect(list.scrollTop).toBe(175);
    expect(button).not.toBeDisabled();
  });

  it("does not override scrolling done by the user during the history fetch", async () => {
    let release!: () => void;
    h.loadEarlierHistory.mockImplementationOnce(() => new Promise<void>((resolve) => { release = resolve; }));
    let height = 200;
    vi.stubGlobal("requestAnimationFrame", (cb: FrameRequestCallback) => { cb(0); return 1; });
    render(<MessageList />);
    const list = screen.getByTestId("message-list");
    Object.defineProperty(list, "scrollHeight", { configurable: true, get: () => height });
    list.scrollTop = 25;
    fireEvent.click(screen.getByRole("button", { name: /加载更早|更早消息/ }));
    list.scrollTop = 60;
    fireEvent.scroll(list);
    height = 350;
    await act(async () => release());
    expect(list.scrollTop).toBe(60);
  });

  it("reports unexpected pagination errors and restores the button", async () => {
    h.loadEarlierHistory.mockRejectedValueOnce(new Error("broken transport"));
    vi.stubGlobal("requestAnimationFrame", (cb: FrameRequestCallback) => { cb(0); return 1; });
    render(<MessageList />);
    await act(async () => {
      fireEvent.click(screen.getByRole("button", { name: /加载更早|更早消息/ }));
    });
    expect(h.setState).toHaveBeenCalledWith({ lastError: "更早历史读取失败，请重试。" });
    expect(screen.getByRole("button", { name: /加载更早|更早消息/ })).not.toBeDisabled();
  });

  it("preserves persisted row identity across prepends, but not session switches", () => {
    const recent = { role: "user", content: "recent", sourceIndex: 50 };
    h.useConversation.mockReturnValue({ messages: [recent], hasMoreHistory: true, lastError: null });
    const view = render(<MessageList />);
    const existing = screen.getByText("recent");
    h.useConversation.mockReturnValue({ messages: [{ role: "user", content: "earlier", sourceIndex: 49 }, recent], hasMoreHistory: true, lastError: null });
    view.rerender(<MessageList />);
    expect(screen.getByText("recent")).toBe(existing);
    expect(screen.getByText("earlier")).toBeTruthy();
    h.useConversation.mockReturnValue({ messages: [{ ...recent, content: "[RETRACTED]" }], hasMoreHistory: true, lastError: null });
    view.rerender(<MessageList />);
    const replaced = screen.getByText("[RETRACTED]");
    expect(replaced).not.toBe(existing);
    sessionStore.setCurrentSession("s2");
    view.rerender(<MessageList />);
    expect(screen.getByText("[RETRACTED]")).not.toBe(replaced);
  });

  it("keeps all 500 existing DOM rows when loading 50 older messages", () => {
    const recent = Array.from({ length: 500 }, (_, i) => ({ role: "user", content: `row-${i + 50}`, sourceIndex: i + 50 }));
    h.useConversation.mockReturnValue({ messages: recent, hasMoreHistory: true, lastError: null });
    const view = render(<MessageList />);
    const before = Array.from(screen.getByTestId("message-list").children).filter(node => node.textContent?.startsWith("row-"));
    const earlier = Array.from({ length: 50 }, (_, i) => ({ role: "user", content: `row-${i}`, sourceIndex: i }));
    h.useConversation.mockReturnValue({ messages: [...earlier, ...recent], hasMoreHistory: false, lastError: null });
    view.rerender(<MessageList />);
    const after = Array.from(screen.getByTestId("message-list").children).filter(node => node.textContent?.startsWith("row-"));
    expect(before).toHaveLength(500);
    expect(after).toHaveLength(550);
    expect(after.slice(50).every((node, i) => node === before[i])).toBe(true);
  });
});
