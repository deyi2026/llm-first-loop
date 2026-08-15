// 阶段 4：消息反馈 / 会话导出 / 子代理标签 / 移动端抽屉

import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { render, screen, fireEvent, cleanup, waitFor } from "@testing-library/react";
import { MessageItem } from "./components/conversation/MessageItem";
import { Conversation } from "./components/conversation/Conversation";
import { Sidebar } from "./components/sidebar/Sidebar";
import { sessionStore } from "./core/stores";
import { conversationStore } from "./core/conversation";

describe("消息反馈", () => {
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it("👍 点击 → POST feedback（含 index/up）", async () => {
    const calls: string[] = [];
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      calls.push(`${init?.method ?? "GET"} ${String(input)} ${String(init?.body ?? "")}`);
      return new Response(JSON.stringify({ status: "ok" }), { status: 200 });
    }));
    render(
      <MessageItem
        msg={{ role: "assistant", content: "回答" }}
        index={3}
        sessionId="s1"
      />
    );
    fireEvent.click(screen.getByTitle("回答有帮助"));
    await waitFor(() => {
      expect(calls.some((c) => c.includes("feedback") && c.includes('"up"'))).toBe(true);
    });
    expect(calls.some((c) => c.includes('"message_index":3'))).toBe(true);
    // 点击后出现常显确认态（不再随 hover 消失）
    await waitFor(() => {
      expect(screen.getByText("👍 已记录（有帮助）")).toBeInTheDocument();
    });
  });
});

describe("会话导出", () => {
  beforeEach(() => {
    sessionStore.setCurrentSession("s1");
    sessionStore.setSessions([
      { session_id: "s1", title: "导出测试", message_count: 1, channel: "web", last_message_preview: "", updated_at: "", created_at: "", status: "active", pinned: false },
    ]);
    conversationStore.setState({ messages: [], streaming: false, streamingIndex: -1, lastError: null, streamStartedAt: null });
  });
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
    sessionStore.setCurrentSession("");
    sessionStore.setSessions([]);
    conversationStore.setState({ messages: [], streaming: false, streamingIndex: -1, lastError: null, streamStartedAt: null });
  });

  it("导出 → 全量拉取 + Markdown 下载", async () => {
    const msgs = Array.from({ length: 120 }, (_, i) => ({
      role: i % 2 === 0 ? "user" : "assistant",
      content: `消息${i}`,
    }));
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/api/v1/sessions/s1/messages")) {
        const offset = Number(new URL(url, "http://x").searchParams.get("offset") ?? 0);
        const page = msgs.slice(offset, offset + 100);
        return new Response(
          JSON.stringify({ messages: page, has_more: offset + page.length < msgs.length }),
          { status: 200 }
        );
      }
      if (url.includes("/api/v1/sessions")) {
        return new Response(
          JSON.stringify({ sessions: [{ session_id: "s1", title: "导出测试", message_count: 1 }], count: 1 }),
          { status: 200 }
        );
      }
      return new Response(JSON.stringify({}), { status: 200 });
    }));
    const downloads: string[] = [];
    // 保留 URL 构造能力（mock 内 new URL 需要），仅替换静态方法
    class FakeURL extends URL {
      static createObjectURL(b: Blob): string {
        downloads.push(b.type);
        return "blob:x";
      }
      static revokeObjectURL(): void {}
    }
    vi.stubGlobal("URL", FakeURL);
    const clickSpy = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
    render(<Conversation />);
    await waitFor(() => expect(screen.getByTestId("export-btn")).toBeInTheDocument());
    fireEvent.click(screen.getByTestId("export-btn"));
    await waitFor(() => {
      expect(downloads.length).toBeGreaterThan(0);
      expect(clickSpy).toHaveBeenCalled();
    });
    expect(downloads[0]).toContain("markdown");
  });
});

describe("子代理标签", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn(async () => {
      return new Response(
        JSON.stringify({
          sessions: [
            { session_id: "subagent_abc123", title: "子任务", message_count: 2, channel: "web", last_message_preview: "p", updated_at: "", created_at: "", status: "active", pinned: false },
          ],
          count: 1,
        }),
        { status: 200 }
      );
    }));
  });
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it("subagent_ 前缀会话显示子代理标签", async () => {
    render(<Sidebar collapsed={false} />);
    await waitFor(() => expect(screen.getByText("子代理")).toBeInTheDocument());
  });
});
