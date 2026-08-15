// 阶段 3：侧栏管理（置顶/删除两步确认/分支/新会话）+ 右侧面板模型目录

import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { render, screen, fireEvent, cleanup, waitFor, within } from "@testing-library/react";
import { Sidebar } from "./components/sidebar/Sidebar";
import { RightPanel } from "./components/layout/RightPanel";
import { sessionStore } from "./core/stores";
import { conversationStore } from "./core/conversation";

const SESSIONS = [
  { session_id: "s1", title: "会话一", message_count: 3, channel: "web", pinned: false, last_message_preview: "预览1", updated_at: "2026-08-15T10:00:00Z", created_at: "", status: "active" },
  { session_id: "s2", title: "会话二", message_count: 8, channel: "feishu:p2p:ou_x", pinned: true, last_message_preview: "预览2", updated_at: "2026-08-15T11:00:00Z", created_at: "", status: "active" },
];

function mockApi() {
  const calls: string[] = [];
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    calls.push(`${init?.method ?? "GET"} ${url}`);
    if (url.includes("/api/v1/sessions")) {
      return new Response(JSON.stringify({ sessions: SESSIONS, count: 2 }), { status: 200 });
    }
    if (url.includes("/api/v1/models")) {
      return new Response(JSON.stringify({ models: ["kimi/k3", "deepseek/deepseek-v4-flash"], current: "kimi/k3" }), { status: 200 });
    }
    if (url.includes("/api/v1/session/current")) {
      return new Response(JSON.stringify({ current: "s1" }), { status: 200 });
    }
    return new Response(JSON.stringify({ status: "ok" }), { status: 200 });
  }));
  return calls;
}

describe("Sidebar 会话管理", () => {
  beforeEach(() => {
    sessionStore.setCurrentSession("s1");
    conversationStore.setState({ messages: [], streaming: false, streamingIndex: -1, lastError: null, streamStartedAt: null });
    mockApi();
  });
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
    sessionStore.setCurrentSession("");
    conversationStore.setState({ messages: [], streaming: false, streamingIndex: -1, lastError: null, streamStartedAt: null });
  });

  it("渲染会话列表：标题/预览/来源标签/消息数/置顶标记", async () => {
    render(<Sidebar collapsed={false} />);
    await waitFor(() => expect(screen.getByText("会话一")).toBeInTheDocument());
    expect(screen.getByText("📌 会话二")).toBeInTheDocument();
    expect(screen.getByText("飞书私聊")).toBeInTheDocument();
    expect(screen.getByText("Web")).toBeInTheDocument();
    expect(screen.getByText("8 条")).toBeInTheDocument();
  });

  it("置顶按钮 → POST pin 接口", async () => {
    const calls = mockApi();
    render(<Sidebar collapsed={false} />);
    await waitFor(() => expect(screen.getAllByTitle("置顶").length).toBeGreaterThan(0));
    fireEvent.click(screen.getAllByTitle("置顶")[0]);
    await waitFor(() => expect(calls.some((c) => c.includes("pin?pinned=true"))).toBe(true));
  });

  it("删除两步确认：首次点击不删，二次点击调 DELETE", async () => {
    const calls = mockApi();
    render(<Sidebar collapsed={false} />);
    await waitFor(() => expect(screen.getAllByTitle("删除会话").length).toBeGreaterThan(0));
    const delBtn = screen.getAllByTitle("删除会话")[0];
    fireEvent.click(delBtn);
    expect(calls.some((c) => c.startsWith("DELETE"))).toBe(false); // 首次不执行
    expect(screen.getByText("确认?")).toBeInTheDocument(); // 进入确认态
    fireEvent.click(screen.getByText("确认?"));
    await waitFor(() => expect(calls.some((c) => c.startsWith("DELETE"))).toBe(true));
  });

  it("分支按钮 → POST fork 接口并切换会话", async () => {
    const calls = mockApi();
    render(<Sidebar collapsed={false} />);
    await waitFor(() => expect(screen.getAllByTitle("在新会话中分支").length).toBeGreaterThan(0));
    fireEvent.click(screen.getAllByTitle("在新会话中分支")[0]);
    await waitFor(() => expect(calls.some((c) => c.includes("/fork"))).toBe(true));
  });

  it("新会话 → 清空当前会话（下条消息创建）", async () => {
    render(<Sidebar collapsed={false} />);
    fireEvent.click(screen.getByTestId("new-session"));
    expect(sessionStore.getState().currentSessionId).toBe("");
    expect(conversationStore.getState().messages).toEqual([]);
  });
});

describe("RightPanel 模型目录", () => {
  beforeEach(() => mockApi());
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it("设置页展示模型目录 + 当前标记", async () => {
    render(<RightPanel open={true} />);
    await waitFor(() => expect(screen.getByTestId("model-catalog")).toBeInTheDocument());
    await waitFor(() => expect(screen.getByText("kimi/k3")).toBeInTheDocument());
    expect(screen.getByText("当前")).toBeInTheDocument();
    expect(screen.getByText("deepseek/deepseek-v4-flash")).toBeInTheDocument();
  });
});
