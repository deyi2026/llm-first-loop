import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { Sidebar } from "./components/sidebar/Sidebar";
import { sessionStore, sidebarViewStore } from "./core/stores";

const record = {
  session_id: "restored-history",
  title: "已恢复的历史会话",
  message_count: 8,
  channel: "web",
  pinned: false,
  last_message_preview: "消息内容保留",
  updated_at: "2026-10-14T00:00:00Z",
  created_at: "",
  status: "active",
};

beforeEach(() => {
  sessionStore.setSessions([]);
  sessionStore.setCurrentSession("");
  sidebarViewStore.setView("sessions");
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

function baseResponse(url: string): Response {
  if (url.includes("/api/v1/workspaces")) {
    return new Response(JSON.stringify({ current: "one", workspaces: [{ id: "one", path: "/project/one" }] }), { status: 200 });
  }
  if (url.includes("/api/v1/agents/tree")) {
    return new Response(JSON.stringify({ agents: [] }), { status: 200 });
  }
  if (url.includes("/api/v1/session/current")) {
    return new Response(JSON.stringify({ current: null }), { status: 200 });
  }
  return new Response(JSON.stringify({}), { status: 200 });
}

it("does not report no sessions while the authoritative list request remains pending", async () => {
  let release!: (value: Response) => void;
  const pending = new Promise<Response>((resolve) => { release = resolve; });
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    if (url.includes("/api/v1/sessions") && !url.includes("/messages")) return pending;
    return baseResponse(url);
  }));
  render(<Sidebar collapsed={false} />);
  expect(screen.getByTestId("sessions-loading")).toHaveTextContent("正在加载会话列表");
  expect(screen.queryByText("暂无会话")).toBeNull();
  release(new Response(JSON.stringify({ sessions: [record], count: 1 }), { status: 200 }));
  await waitFor(() => expect(screen.getByText("已恢复的历史会话")).toBeInTheDocument());
  expect(screen.queryByTestId("sessions-loading")).toBeNull();
});

it("reports failed list read and offers explicit non-mutating retry", async () => {
  let calls = 0;
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    if (url.includes("/api/v1/sessions") && !url.includes("/messages")) {
      calls++;
      return calls === 1
        ? new Response(JSON.stringify({ detail: "temporarily unavailable" }), { status: 503 })
        : new Response(JSON.stringify({ sessions: [record], count: 1 }), { status: 200 });
    }
    return baseResponse(url);
  }));
  render(<Sidebar collapsed={false} />);
  await waitFor(() => expect(screen.getByTestId("sessions-load-error")).toHaveTextContent("会话列表加载失败"));
  expect(screen.queryByText("暂无会话")).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "重试加载会话" }));
  await waitFor(() => expect(screen.getByText("已恢复的历史会话")).toBeInTheDocument());
  expect(calls).toBe(2);
});
