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
    if (url.includes("/api/v1/workspaces") && url.includes("/sessions")) {
      return new Response(
        JSON.stringify({
          sessions: [
            { session_id: "b1", title: "b 的会话", updated_at: "2026-08-16T10:00:00Z", message_count: 2, status: "active", last_message_preview: "预览", pinned: false, channel: "web" },
          ],
          count: 1,
        }),
        { status: 200 }
      );
    }
    if (url.includes("/api/v1/workspaces")) {
      return new Response(
        JSON.stringify({
          workspaces: [
            { id: "--srv-llm-first-loop--", path: "/srv/llm-first-loop" },
            { id: "--srv-b--", path: "/srv/b" },
          ],
          current: "--srv-llm-first-loop--",
        }),
        { status: 200 }
      );
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

  it("工作区分组：常驻显示所有工作区（不折叠）+ 其他工作区会话", async () => {
    mockApi();
    render(<Sidebar collapsed={false} />);
    await waitFor(() => expect(screen.getByTestId("ws-groups")).toBeInTheDocument());
    // 两个工作区名常驻显示（不折叠）
    expect(screen.getByText("llm-first-loop")).toBeInTheDocument();
    expect(screen.getByText("b")).toBeInTheDocument();
    // 其他工作区会话列表（只读紧凑项）
    expect(screen.getByTestId("ws-other-sessions")).toBeInTheDocument();
    expect(screen.getByText("＋ 打开新工作区")).toBeInTheDocument();
  });

  it("点击其他工作区会话 → 切换工作区（POST switch）", async () => {
    const calls = mockApi();
    render(<Sidebar collapsed={false} />);
    await waitFor(() => expect(screen.getByTestId("ws-groups")).toBeInTheDocument());
    const items = screen.getAllByTestId("other-session-item");
    expect(items.length).toBeGreaterThan(0);
    fireEvent.click(items[0]);
    await waitFor(() =>
      expect(calls.some((c) => c.startsWith("POST") && c.includes("/api/v1/workspaces/switch"))).toBe(true)
    );
  });

  it("点击其他工作区分组头 → 切换工作区（无会话的工作区也可切）", async () => {
    const calls = mockApi();
    render(<Sidebar collapsed={false} />);
    await waitFor(() => expect(screen.getByTestId("ws-groups")).toBeInTheDocument());
    // 其他工作区分组头（b）可点击切换
    const heads = screen.getAllByTestId("ws-tree-head");
    const otherHead = heads.find((h) => h.textContent?.includes("b"));
    expect(otherHead).toBeTruthy();
    fireEvent.click(otherHead!);
    await waitFor(() =>
      expect(calls.some((c) => c.startsWith("POST") && c.includes("/api/v1/workspaces/switch"))).toBe(true)
    );
  });

  it("打开新工作区：目录浏览器选择 → POST /workspaces + 模态关闭", async () => {
    mockApi();
    vi.mocked(fetch).mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.includes("/api/v1/fs/dirs")) {
        return new Response(
          JSON.stringify({ path: "/srv/new", parent: "/srv", dirs: ["sub1", "sub2"] }),
          { status: 200 }
        );
      }
      if (url.includes("/api/v1/workspaces") && init?.method === "POST") {
        return new Response(
          JSON.stringify({ id: "--srv-new--", path: "/srv/new", current: true }),
          { status: 200 }
        );
      }
      if (url.includes("/api/v1/workspaces")) {
        return new Response(
          JSON.stringify({
            workspaces: [{ id: "--srv-llm-first-loop--", path: "/srv/llm-first-loop" }],
            current: "--srv-llm-first-loop--",
          }),
          { status: 200 }
        );
      }
      return new Response(JSON.stringify({ status: "ok" }), { status: 200 });
    });
    render(<Sidebar collapsed={false} />);
    await waitFor(() => expect(screen.getByText("llm-first-loop")).toBeInTheDocument());
    fireEvent.click(screen.getByTestId("ws-add-btn"));
    // 目录浏览器模态出现 + 目录列表渲染（异步加载；📂 前缀 → 正则匹配）
    await waitFor(() => expect(screen.getByTestId("dir-browser")).toBeInTheDocument());
    await waitFor(() => expect(screen.getByText(/sub1/)).toBeInTheDocument());
    // 点目录进入（fetchDirs 带新 path）
    fireEvent.click(screen.getByText(/sub1/));
    // 打开此目录 → POST /workspaces
    fireEvent.click(screen.getByTestId("dir-open"));
    await waitFor(() =>
      expect(vi.mocked(fetch)).toHaveBeenCalledWith(
        expect.stringContaining("/api/v1/workspaces"),
        expect.objectContaining({ method: "POST" })
      )
    );
    // 成功后模态关闭
    await waitFor(() => expect(screen.queryByTestId("dir-browser")).not.toBeInTheDocument());
    // 新工作区无旧会话上下文：当前会话清空（不再显示旧工作区内容）
    expect(sessionStore.getState().currentSessionId).toBe("");
  });

  it("打开新工作区后：分组立即切换到新工作区（含路径名称）", async () => {
    mockApi();
    // 有状态 mock：POST 注册后 GET /workspaces 返回新 current（模拟服务端已切换）
    let registered = false;
    vi.mocked(fetch).mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.includes("/api/v1/fs/dirs")) {
        return new Response(
          JSON.stringify({ path: "/srv/new", parent: "/srv", dirs: ["sub1"] }),
          { status: 200 }
        );
      }
      if (url.includes("/api/v1/workspaces") && init?.method === "POST") {
        registered = true;
        return new Response(
          JSON.stringify({ id: "--srv-new--", path: "/srv/new", current: true }),
          { status: 200 }
        );
      }
      if (url.includes("/api/v1/workspaces") && url.includes("/sessions")) {
        return new Response(JSON.stringify({ sessions: [], count: 0 }), { status: 200 });
      }
      if (url.includes("/api/v1/workspaces")) {
        return new Response(
          JSON.stringify({
            workspaces: [
              { id: "--srv-llm-first-loop--", path: "/srv/llm-first-loop" },
              { id: "--srv-new--", path: "/srv/new" },
            ],
            current: registered
              ? "--srv-new--"
              : "--srv-llm-first-loop--",
          }),
          { status: 200 }
        );
      }
      return new Response(JSON.stringify({ status: "ok" }), { status: 200 });
    });
    render(<Sidebar collapsed={false} />);
    await waitFor(() => expect(screen.getByText("llm-first-loop")).toBeInTheDocument());
    fireEvent.click(screen.getByTestId("ws-add-btn"));
    await waitFor(() => expect(screen.getByTestId("dir-browser")).toBeInTheDocument());
    fireEvent.click(screen.getByTestId("dir-open"));
    // 注册后：新工作区分组出现、置顶且为当前（📁），旧工作区变为其他分组（📂）
    await waitFor(() => expect(screen.getByText("new")).toBeInTheDocument());
    const groups = screen.getAllByTestId("ws-group");
    expect(groups.length).toBe(2);
    // 当前工作区置顶（新工作区不被堆叠挤到最下面）
    expect(groups[0].className).toContain("current");
    expect(within(groups[0]).getByText("new")).toBeInTheDocument();
    const otherGroup = groups.find((g) => !g.className.includes("current"));
    expect(within(otherGroup!).getByText("llm-first-loop")).toBeInTheDocument();
  });

  it("打开新工作区：注册失败 → 模态内错误提示", async () => {
    mockApi();
    vi.mocked(fetch).mockImplementation(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.includes("/api/v1/fs/dirs")) {
        return new Response(
          JSON.stringify({ path: "/no/such/dir", parent: "/", dirs: [] }),
          { status: 200 }
        );
      }
      if (url.includes("/api/v1/workspaces") && init?.method === "POST") {
        return new Response(JSON.stringify({ error: "invalid_workspace", detail: "目录不存在" }), { status: 400 });
      }
      if (url.includes("/api/v1/workspaces")) {
        return new Response(
          JSON.stringify({
            workspaces: [{ id: "--srv-llm-first-loop--", path: "/srv/llm-first-loop" }],
            current: "--srv-llm-first-loop--",
          }),
          { status: 200 }
        );
      }
      return new Response(JSON.stringify({ status: "ok" }), { status: 200 });
    });
    render(<Sidebar collapsed={false} />);
    await waitFor(() => expect(screen.getByText("llm-first-loop")).toBeInTheDocument());
    fireEvent.click(screen.getByTestId("ws-add-btn"));
    await waitFor(() => expect(screen.getByTestId("dir-browser")).toBeInTheDocument());
    fireEvent.click(screen.getByTestId("dir-open"));
    await waitFor(() => expect(screen.getByText("打开失败（路径不存在或服务不可用）")).toBeInTheDocument());
    expect(vi.mocked(fetch)).toHaveBeenCalledWith(
      expect.stringContaining("/api/v1/workspaces"),
      expect.objectContaining({ method: "POST" })
    );
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
