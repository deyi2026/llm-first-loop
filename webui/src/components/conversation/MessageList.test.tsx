import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { sessionStore } from "../../core/stores";

const h = vi.hoisted(() => ({
  loadEarlierHistory: vi.fn(),
  useConversation: vi.fn(),
}));
vi.mock("../../core/conversation", () => ({
  loadEarlierHistory: h.loadEarlierHistory,
  loadHistory: vi.fn(),
  useConversation: h.useConversation,
}));
vi.mock("./MessageItem", () => ({
  MessageItem: () => <div>历史消息</div>,
  extractProducedPaths: () => [],
}));

import { MessageList } from "./MessageList";

describe("Web history pagination interaction", () => {
  beforeEach(() => {
    h.loadEarlierHistory.mockReset().mockResolvedValue(undefined);
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
});
