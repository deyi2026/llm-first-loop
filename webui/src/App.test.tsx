// Web V2 冒烟测试（阶段 1 验收：布局壳渲染 / 主题切换 / 状态链路）

import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { render, screen, fireEvent, cleanup, act, within } from "@testing-library/react";
import { App, PANEL_WIDTH_DEFAULT, PANEL_WIDTH_KEY } from "./App";
import { learningPageStore, mainViewStore } from "./core/stores";

async function renderAppSettled(): Promise<void> {
  await act(async () => {
    render(<App />);
    // App mounts several independent async effect trees. Keep their first immediate
    // fetch/store settlements inside React's test boundary instead of racing assertions.
    await new Promise((resolve) => window.setTimeout(resolve, 0));
  });
}

describe("App 布局壳", () => {
  beforeEach(() => {
    // 隔离 SSE/轮询：mock fetch 返回空会话
    vi.stubGlobal("fetch", vi.fn(async () => {
      return new Response(JSON.stringify({ sessions: [], count: 0 }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    }));
  });
  afterEach(() => {
    cleanup();
    mainViewStore.setView("chat");
    vi.unstubAllGlobals();
    document.body.removeAttribute("data-ds-dark-theme");
    localStorage.clear();
  });

  it("首次访问右面板使用默认宽度，而不是意外夹到最小宽度", async () => {
    localStorage.removeItem(PANEL_WIDTH_KEY);
    await renderAppSettled();
    expect(screen.getByTestId("right-panel")).toHaveStyle({ width: `${PANEL_WIDTH_DEFAULT}px` });
  });

  it("指针取消拖拽后不再继续调整面板", async () => {
    await renderAppSettled();
    const handle = screen.getByTestId("panel-resize-handle");
    const panel = screen.getByTestId("right-panel");
    fireEvent.pointerDown(handle, { button: 0, pointerId: 1, clientX: 800 });
    fireEvent.pointerMove(window, { clientX: 700 });
    const previousWidth = panel.style.width;
    fireEvent.pointerCancel(window);
    fireEvent.pointerMove(window, { clientX: 400 });
    expect(panel.style.width).toBe(previousWidth);
  });

  it("渲染三栏壳与核心元素", async () => {
    await renderAppSettled();
    expect(screen.getByTestId("app-shell")).toBeInTheDocument();
    expect(screen.getByTestId("sidebar")).toBeInTheDocument();
    expect(screen.getByTestId("topbar")).toBeInTheDocument();
    expect(screen.getByTestId("conversation")).toBeInTheDocument();
    expect(screen.getByTestId("right-panel")).toBeInTheDocument();
    expect(screen.getByText("LLM-First Loop")).toBeInTheDocument();
    // 空状态 hero（对齐 DSH 文案风格）
    expect(screen.getByText("描述你想要构建的内容")).toBeInTheDocument();
  });

  it("顶栏标题跟随知识/学习/服务视图变化", async () => {
    await renderAppSettled();
    const topbar = screen.getByTestId("topbar");
    act(() => {
      mainViewStore.setView("learning");
      learningPageStore.setPage("knowledge");
    });
    expect(within(topbar).getByText("知识管理")).toBeInTheDocument();
    act(() => learningPageStore.setPage("learning"));
    expect(within(topbar).getByText("学习通道")).toBeInTheDocument();
    act(() => mainViewStore.setView("services"));
    expect(within(topbar).getByText("服务身份")).toBeInTheDocument();
  });

  it("服务身份使用专用服务网格和主区滚动容器，不能继承学习详情双列样式", async () => {
    await renderAppSettled();
    act(() => mainViewStore.setView("services"));
    const panel = screen.getByTestId("services-panel");
    expect(panel).toHaveClass("v2-services-view");
    expect(within(panel).getByTestId("services-grid")).toHaveClass("v2-services-grid");
    expect(within(panel).getByTestId("services-grid")).not.toHaveClass("v2-learning-grid");
  });

  it("移动端使用与 PC 相同的右侧箭头，固定于主区外且可反复开合", async () => {
    vi.stubGlobal("matchMedia", vi.fn(() => ({
      matches: true, media: "(max-width: 900px)", onchange: null,
      addEventListener: vi.fn(), removeEventListener: vi.fn(),
      addListener: vi.fn(), removeListener: vi.fn(), dispatchEvent: vi.fn(),
    })));
    await renderAppSettled();
    const toggle = screen.getByTestId("right-panel-toggle");
    expect(toggle).toHaveClass("v2-panel-edge-toggle", "mobile");
    expect(toggle).toHaveTextContent("◂");
    expect(toggle).not.toHaveAttribute("aria-controls");
    expect(within(screen.getByTestId("topbar")).queryByRole("button", { name: "右侧面板" })).toBeNull();
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(toggle).toHaveAttribute("aria-controls", "lfl-right-panel");
    expect(toggle).toHaveTextContent("▸");
    expect(screen.getByTestId("panel-scrim")).toBeInTheDocument();
    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(toggle).not.toHaveAttribute("aria-controls");
    expect(toggle).toHaveTextContent("◂");
    expect(screen.queryByTestId("right-panel")).toBeNull();
  });

  it("手机抽屉支持 Escape 关闭并提供屏幕阅读器遮罩按钮", async () => {
    vi.stubGlobal("matchMedia", vi.fn(() => ({
      matches: true, media: "(max-width: 900px)", onchange: null,
      addEventListener: vi.fn(), removeEventListener: vi.fn(),
      addListener: vi.fn(), removeListener: vi.fn(), dispatchEvent: vi.fn(),
    })));
    await renderAppSettled();
    const shell = screen.getByTestId("app-shell");
    const topbar = screen.getByTestId("topbar");
    fireEvent.click(within(topbar).getAllByRole("button")[0]);
    expect(shell).toHaveClass("mobile-sidebar-open");
    expect(screen.getByRole("button", { name: "关闭会话侧栏" })).toBeInTheDocument();
    fireEvent.keyDown(window, { key: "Escape" });
    expect(shell).not.toHaveClass("mobile-sidebar-open");
    fireEvent.click(screen.getByTestId("right-panel-toggle"));
    expect(shell).toHaveClass("mobile-panel-open");
    expect(screen.getByRole("button", { name: "关闭右侧面板" })).toBeInTheDocument();
    fireEvent.keyDown(window, { key: "Escape" });
    expect(shell).not.toHaveClass("mobile-panel-open");
  });

  it("移动端从侧栏进入服务身份、学习通道或新会话时，关闭覆盖主视图的抽屉", async () => {
    vi.stubGlobal("matchMedia", vi.fn(() => ({
      matches: true, media: "(max-width: 900px)", onchange: null,
      addEventListener: vi.fn(), removeEventListener: vi.fn(),
      addListener: vi.fn(), removeListener: vi.fn(), dispatchEvent: vi.fn(),
    })));
    await renderAppSettled();
    const shell = screen.getByTestId("app-shell");
    const menu = within(screen.getByTestId("topbar")).getAllByRole("button")[0];

    fireEvent.click(menu);
    expect(shell).toHaveClass("mobile-sidebar-open");
    fireEvent.click(screen.getByTestId("services-entry"));
    expect(shell).not.toHaveClass("mobile-sidebar-open");
    expect(screen.getByTestId("services-panel")).toBeInTheDocument();

    fireEvent.click(menu);
    fireEvent.click(screen.getByTestId("learning-entry"));
    expect(shell).not.toHaveClass("mobile-sidebar-open");

    fireEvent.click(menu);
    fireEvent.click(screen.getByTestId("new-session"));
    expect(shell).not.toHaveClass("mobile-sidebar-open");
  });

  it("固定学习通道入口打开独立 Learning Plane 观察页", async () => {
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/api/v1/learning/status")) {
        return new Response(JSON.stringify({
          enabled: true,
          producer_only: true,
          worker: { running: true, model_ref: "glm/glm-5.3" },
          counts: { queued: 1, started: 0, saved: 2, failed: 0 },
          jobs: [{
            job_id: "learn:abc",
            source_episode_ref: "episode:s1:1:x",
            source_session_id: "s1",
            source_model: "glm/glm-5.3",
            state: "saved",
            attempt: 1,
            candidate_ref: "method:probe",
            created_at: 1,
            updated_at: 2,
            finished_at: 2,
            trigger_facts: { rounds: 8 },
          }],
        }), { status: 200, headers: { "Content-Type": "application/json" } });
      }
      return new Response(JSON.stringify({ sessions: [], count: 0 }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    }));

    await renderAppSettled();
    expect(screen.getByTestId("learning-entry")).toBeInTheDocument();
    fireEvent.click(screen.getByTestId("learning-entry"));
    expect(await screen.findByTestId("learning-panel")).toBeInTheDocument();
    expect(screen.getByText("● Worker 运行中")).toBeInTheDocument();
    expect(screen.getByText("method:probe")).toBeInTheDocument();
    expect(screen.queryByTestId("conversation")).toBeNull();
  });

  it("主题切换：暗色 → body 属性生效，偏好持久化", async () => {
    await renderAppSettled();
    expect(document.body.hasAttribute("data-ds-dark-theme")).toBe(false);
    fireEvent.click(screen.getByRole("button", { name: "暗色" }));
    expect(document.body.hasAttribute("data-ds-dark-theme")).toBe(true);
    expect(localStorage.getItem("dsw-theme-preference")).toBe("dark");
    fireEvent.click(screen.getByRole("button", { name: "亮色" }));
    expect(document.body.hasAttribute("data-ds-dark-theme")).toBe(false);
    expect(localStorage.getItem("dsw-theme-preference")).toBe("light");
  });

  it("侧栏折叠/展开与右侧面板开关", async () => {
    await renderAppSettled();
    const sidebar = screen.getByTestId("sidebar");
    expect(sidebar).not.toHaveClass("collapsed");
    fireEvent.click(screen.getByTitle("收起侧边栏"));
    expect(sidebar).toHaveClass("collapsed");
    fireEvent.click(screen.getByTitle("右侧面板"));
    expect(screen.queryByTestId("right-panel")).not.toBeInTheDocument();
    expect(screen.getByTestId("right-panel-toggle")).toHaveClass("desktop");
    expect(screen.getByTestId("right-panel-toggle")).toHaveTextContent("◂");
  });

  it("移动端侧栏使用完整抽屉而不是 collapsed 空壳", async () => {
    vi.stubGlobal(
      "matchMedia",
      vi.fn(() => ({
        matches: true,
        media: "(max-width: 900px)",
        onchange: null,
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
        addListener: vi.fn(),
        removeListener: vi.fn(),
        dispatchEvent: vi.fn(),
      }))
    );

    await renderAppSettled();
    const shell = screen.getByTestId("app-shell");
    const sidebar = screen.getByTestId("sidebar");
    expect(sidebar).not.toHaveClass("collapsed");
    expect(shell).not.toHaveClass("mobile-sidebar-open");

    fireEvent.click(screen.getByTitle("收起侧边栏"));
    expect(shell).toHaveClass("mobile-sidebar-open");
    expect(sidebar).not.toHaveClass("collapsed");
    expect(screen.getByTestId("sidebar-scrim")).toBeInTheDocument();

    fireEvent.click(screen.getByTestId("sidebar-scrim"));
    expect(shell).not.toHaveClass("mobile-sidebar-open");
    expect(screen.queryByTestId("sidebar-scrim")).toBeNull();
  });

  it("移动端右侧面板：class 与 DOM 挂载同步开合，不出现挂载但移出屏幕的状态", async () => {
    vi.stubGlobal(
      "matchMedia",
      vi.fn(() => ({
        matches: true,
        media: "(max-width: 900px)",
        onchange: null,
        addEventListener: vi.fn(),
        removeEventListener: vi.fn(),
        addListener: vi.fn(),
        removeListener: vi.fn(),
        dispatchEvent: vi.fn(),
      }))
    );

    await renderAppSettled();
    const shell = screen.getByTestId("app-shell");

    // 初始：移动端抽屉收起 → 无 class、RightPanel 未挂载（确实隐藏）
    expect(shell).not.toHaveClass("mobile-panel-open");
    expect(screen.queryByTestId("right-panel")).not.toBeInTheDocument();

    // 点击右侧面板按钮：class 与 RightPanel 同时进入 open
    fireEvent.click(screen.getByTitle("右侧面板"));
    expect(shell).toHaveClass("mobile-panel-open");
    expect(screen.getByTestId("right-panel")).toBeInTheDocument();
    expect(screen.getByTestId("panel-scrim")).toBeInTheDocument();
    // 机械一致不变量：RightPanel 挂载 ⇔ mobile-panel-open 存在
    // （否则 CSS translateX(100%) 会把已挂载面板永久移出屏幕）
    expect(shell.classList.contains("mobile-panel-open")).toBe(
      screen.queryByTestId("right-panel") !== null
    );

    // 点击抽屉外遮罩：同时关闭，移动端不留背景可误触
    fireEvent.click(screen.getByTestId("panel-scrim"));
    expect(shell).not.toHaveClass("mobile-panel-open");
    expect(screen.queryByTestId("right-panel")).not.toBeInTheDocument();
    expect(screen.queryByTestId("panel-scrim")).not.toBeInTheDocument();
  });

  it("桌面缩到移动断点时自动收起已打开右侧面板，不让抽屉突然覆盖内容", async () => {
    let mobile = false;
    const listeners = new Set<() => void>();
    vi.stubGlobal(
      "matchMedia",
      vi.fn(() => ({
        get matches() { return mobile; },
        media: "(max-width: 900px)",
        onchange: null,
        addEventListener: (_type: string, cb: () => void) => listeners.add(cb),
        removeEventListener: (_type: string, cb: () => void) => listeners.delete(cb),
        addListener: vi.fn(),
        removeListener: vi.fn(),
        dispatchEvent: vi.fn(),
      }))
    );

    await renderAppSettled();
    expect(screen.getByTestId("right-panel")).toBeInTheDocument();

    act(() => {
      mobile = true;
      listeners.forEach((cb) => cb());
    });

    expect(screen.getByTestId("app-shell")).not.toHaveClass("mobile-panel-open");
    expect(screen.queryByTestId("right-panel")).not.toBeInTheDocument();
  });

  it("SSE 事件驱动：sessions_updated → 会话列表刷新", async () => {
    // jsdom 无 EventSource → 注入桩（对齐后端 event: sessions_updated 命名帧）
    const eventTarget = new EventTarget();
    class FakeEventSource {
      constructor(_url: string) {}
      addEventListener(t: string, cb: EventListener) {
        eventTarget.addEventListener(t, cb);
      }
      close() {}
    }
    vi.stubGlobal("EventSource", FakeEventSource);

    // 会话列表：首次空 → 事件触发后返回带会话
    const sessions = [{ session_id: "s1", title: "测试会话", message_count: 2, channel: "web" }];
    const sessionsResp = () =>
      new Response(JSON.stringify({ sessions, count: 1 }), { status: 200 });
    vi.mocked(fetch).mockImplementation(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/api/v1/sessions")) return sessionsResp();
      if (url.includes("/api/v1/session/current"))
        return new Response(JSON.stringify({ current: "s1" }), { status: 200 });
      return new Response(JSON.stringify({ status: "ok", version: "9.9.9" }), { status: 200 });
    });

    await renderAppSettled();
    await vi.waitFor(() => {
      expect(screen.getAllByText("测试会话").length).toBeGreaterThan(0);
    });
    // 事件驱动刷新（命名事件）
    eventTarget.dispatchEvent(new Event("sessions_updated"));
    await vi.waitFor(() => {
      expect(screen.getByTestId("session-list").children.length).toBeGreaterThan(0);
    });
  });
});
