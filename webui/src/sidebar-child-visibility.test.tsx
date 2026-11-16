import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { Sidebar } from "./components/sidebar/Sidebar";
import { sessionStore, sidebarViewStore } from "./core/stores";

const parent = {
  session_id: "main-parent",
  title: "共同任务主会话",
  channel: "web",
  message_count: 10,
  pinned: true,
  status: "active",
  created_at: "2026-11-16T00:00:00Z",
  updated_at: "2026-11-16T00:00:00Z",
  last_message_preview: "主会话",
};
const child = {
  ...parent,
  session_id: "w1-child",
  title: "共同任务 W1 接力",
  pinned: false,
  last_message_preview: "W1 Reviewer 继续",
};

describe("子会话在侧栏可发现", () => {
  beforeEach(() => {
    sessionStore.setSessions([]);
    sessionStore.setCurrentSession("");
    sessionStore.setNewSessionPending(false);
    sidebarViewStore.setView("sessions");
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      const json = (data: unknown) => new Response(JSON.stringify(data), { status: 200 });
      if (url.includes("/api/v1/agents/tree")) {
        return json({ nodes: [
          { id: parent.session_id, parent_id: null },
          { id: child.session_id, parent_id: parent.session_id },
        ] });
      }
      if (url.includes("/api/v1/workspaces")) {
        return json({ current: "primary", workspaces: [{ id: "primary", path: "/project/primary" }] });
      }
      if (url.includes("/api/v1/sessions")) return json({ sessions: [parent, child], count: 2 });
      if (url.includes("/api/v1/session/current")) return json({ current: parent.session_id });
      return json({});
    }));
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
    sessionStore.setCurrentSession("");
  });

  it("automatically expands the parent of a deep-linked active child after the tree loads", async () => {
    sessionStore.setCurrentSession(child.session_id);
    render(<Sidebar collapsed={false} />);
    await screen.findByTitle("折叠");
    expect(screen.getByText(/共同任务 W1 接力/)).toBeInTheDocument();
  });

  it("expands a parent when switching to its child but respects a subsequent manual collapse", async () => {
    sessionStore.setCurrentSession(parent.session_id);
    render(<Sidebar collapsed={false} />);
    await screen.findByTitle("展开");
    expect(screen.queryByText(/共同任务 W1 接力/)).toBeNull();

    act(() => sessionStore.setCurrentSession(child.session_id));
    await waitFor(() => expect(screen.getByText(/共同任务 W1 接力/)).toBeInTheDocument());
    fireEvent.click(screen.getByTitle("折叠"));
    expect(screen.queryByText(/共同任务 W1 接力/)).toBeNull();
  });

  it("shows matching children as flat search results even when their parent matches and is collapsed", async () => {
    sessionStore.setCurrentSession(parent.session_id);
    render(<Sidebar collapsed={false} />);
    await screen.findByTitle("展开");
    expect(screen.queryByText(/共同任务 W1 接力/)).toBeNull();

    const search = screen.getByPlaceholderText("搜索会话…");
    fireEvent.change(search, { target: { value: "共同任务" } });
    expect(screen.getByText(/共同任务主会话/)).toBeInTheDocument();
    expect(screen.getByText(/共同任务 W1 接力/)).toBeInTheDocument();

    fireEvent.change(search, { target: { value: "" } });
    expect(screen.queryByText(/共同任务 W1 接力/)).toBeNull();

    fireEvent.change(search, { target: { value: child.session_id } });
    expect(screen.getByText(/共同任务 W1 接力/)).toBeInTheDocument();
    fireEvent.click(screen.getByText(/共同任务 W1 接力/));
    fireEvent.change(search, { target: { value: "" } });
    await waitFor(() => expect(screen.getByText(/共同任务 W1 接力/)).toBeInTheDocument());
  });
});
