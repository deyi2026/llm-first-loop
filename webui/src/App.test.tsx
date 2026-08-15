// Web V2 冒烟测试（阶段 1 验收：布局壳渲染 / 主题切换 / 状态链路）

import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { render, screen, fireEvent, cleanup } from "@testing-library/react";
import { App } from "./App";

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
    vi.unstubAllGlobals();
    document.body.removeAttribute("data-ds-dark-theme");
    localStorage.clear();
  });

  it("渲染三栏壳与核心元素", async () => {
    render(<App />);
    expect(screen.getByTestId("app-shell")).toBeInTheDocument();
    expect(screen.getByTestId("sidebar")).toBeInTheDocument();
    expect(screen.getByTestId("topbar")).toBeInTheDocument();
    expect(screen.getByTestId("conversation")).toBeInTheDocument();
    expect(screen.getByTestId("right-panel")).toBeInTheDocument();
    expect(screen.getByText("LLM-First Loop")).toBeInTheDocument();
    // 空状态 hero（对齐 DSH 文案风格）
    expect(screen.getByText("描述你想要构建的内容")).toBeInTheDocument();
  });

  it("主题切换：暗色 → body 属性生效，偏好持久化", () => {
    render(<App />);
    expect(document.body.hasAttribute("data-ds-dark-theme")).toBe(false);
    fireEvent.click(screen.getByRole("button", { name: "暗色" }));
    expect(document.body.hasAttribute("data-ds-dark-theme")).toBe(true);
    expect(localStorage.getItem("dsw-theme-preference")).toBe("dark");
    fireEvent.click(screen.getByRole("button", { name: "亮色" }));
    expect(document.body.hasAttribute("data-ds-dark-theme")).toBe(false);
    expect(localStorage.getItem("dsw-theme-preference")).toBe("light");
  });

  it("侧栏折叠/展开与右侧面板开关", () => {
    render(<App />);
    const sidebar = screen.getByTestId("sidebar");
    expect(sidebar).not.toHaveClass("collapsed");
    fireEvent.click(screen.getByTitle("收起侧边栏"));
    expect(sidebar).toHaveClass("collapsed");
    fireEvent.click(screen.getByTitle("右侧面板"));
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

    render(<App />);
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
