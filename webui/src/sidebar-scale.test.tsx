import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { Sidebar } from "./components/sidebar/Sidebar";
import { sessionStore, sidebarViewStore } from "./core/stores";

const sessions = Array.from({ length: 110 }, (_, i) => ({
  session_id: `many-${i}`,
  title: i === 103 ? "搜索目标会话" : `长会话-${i}`,
  channel: "web",
  message_count: i + 1,
  pinned: false,
  status: "active",
  created_at: "2026-10-13T00:00:00Z",
  updated_at: "2026-10-13T00:00:00Z",
  last_message_preview: `内容${i}`,
}));

describe("大型会话树按需展示", () => {
  let otherReads: number;
  let otherFail: boolean;
  beforeEach(() => {
    otherReads = 0;
    otherFail = false;
    sessionStore.setCurrentSession("many-103");
    sessionStore.setSessions([]);
    sidebarViewStore.setView("sessions");
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      const json = (data: unknown, status = 200) => new Response(JSON.stringify(data), { status });
      if (url.includes("/api/v1/workspaces/secondary/sessions")) {
        otherReads += 1;
        return otherFail ? json({ detail: "temporarily unavailable" }, 503) : json({ sessions: [
          { ...sessions[0], session_id: "other-1", title: "其他工作区会话" },
        ] });
      }
      if (url.includes("/api/v1/workspaces") && !url.includes("/sessions")) return json({
        current: "primary", workspaces: [
          { id: "primary", path: "/project/primary" },
          { id: "secondary", path: "/project/secondary" },
        ],
      });
      if (url.includes("/api/v1/session/current")) return json({ current: "many-103" });
      if (url.includes("/api/v1/sessions")) return json({ sessions, count: sessions.length });
      if (url.includes("/api/v1/agents/tree")) return json({ agents: [] });
      return json({});
    }));
  });
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
    sessionStore.setCurrentSession("");
  });

  it("limits initial DOM nodes but keeps the active conversation and full-data search accessible", async () => {
    render(<Sidebar collapsed={false} />);
    await screen.findByText("长会话-0");
    await screen.findByText("primary");
    // The active item is beyond the initial chunk, but may not disappear.
    expect(screen.getByText("搜索目标会话")).toBeInTheDocument();
    expect(screen.getAllByTestId("session-item").length).toBeLessThan(70);
    expect(screen.getByTestId("session-show-more")).toBeInTheDocument();
    expect(otherReads).toBe(0);

    fireEvent.change(screen.getByPlaceholderText("搜索会话…"), { target: { value: "长会话-91" } });
    expect(screen.getByText("长会话-91")).toBeInTheDocument();
    fireEvent.change(screen.getByPlaceholderText("搜索会话…"), { target: { value: "" } });
    fireEvent.click(screen.getByTestId("session-show-more"));
    expect(screen.getAllByTestId("session-item").length).toBeGreaterThan(50);
  });

  it("fetches other workspace sessions only when explicitly expanded and reports retryable failure", async () => {
    otherFail = true;
    render(<Sidebar collapsed={false} />);
    await screen.findByText("secondary");
    expect(otherReads).toBe(0);
    fireEvent.click(screen.getByTestId("ws-show-sessions"));
    await waitFor(() => expect(otherReads).toBe(1));
    expect(await screen.findByText(/工作区会话加载失败/)).toBeInTheDocument();
    expect(screen.queryByText("暂无会话")).not.toBeInTheDocument();
    otherFail = false;
    fireEvent.click(screen.getByTestId("ws-retry-sessions"));
    expect(await screen.findByText("其他工作区会话")).toBeInTheDocument();
    expect(otherReads).toBe(2);
  });

  it("leaf conversations do not offer an expand action that only reveals an empty placeholder", async () => {
    render(<Sidebar collapsed={false} />);
    await screen.findByText("长会话-0");
    expect(screen.queryByTitle("展开")).toBeNull();
  });
});
