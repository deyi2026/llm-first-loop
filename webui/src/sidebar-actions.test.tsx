import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { Sidebar } from "./components/sidebar/Sidebar";
import { conversationStore } from "./core/conversation";
import { sessionStore } from "./core/stores";

const SESSION = {
  session_id: "s1",
  title: "会话一",
  message_count: 3,
  channel: "web",
  pinned: false,
  last_message_preview: "预览",
  updated_at: "2026-09-09T00:00:00Z",
  created_at: "",
  status: "active",
};

function baseResponse(url: string): Response {
  if (url.includes("/api/v1/sessions")) {
    return new Response(JSON.stringify({ sessions: [SESSION], count: 1 }), { status: 200 });
  }
  if (url.includes("/api/v1/session/current")) {
    return new Response(JSON.stringify({ current: "s1" }), { status: 200 });
  }
  if (url.includes("/api/v1/workspaces") && !url.includes("/sessions")) {
    return new Response(JSON.stringify({ workspaces: [{ id: "ws", path: "/ws" }], current: "ws" }), { status: 200 });
  }
  if (url.includes("/api/v1/workspaces/ws/sessions")) {
    return new Response(JSON.stringify({ sessions: [SESSION], count: 1 }), { status: 200 });
  }
  if (url.includes("/api/v1/agents/tree")) {
    return new Response(JSON.stringify({ agents: [] }), { status: 200 });
  }
  return new Response(JSON.stringify({ status: "ok" }), { status: 200 });
}

beforeEach(() => {
  sessionStore.setCurrentSession("s1");
  conversationStore.setState({ messages: [], streaming: false, streamingIndex: -1, lastError: null });
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("sidebar mutation controls", () => {
  it("mutation in flight disables actions so a fast double click cannot issue duplicate pin requests", async () => {
    let pinCalls = 0;
    let resolvePin: ((value: Response) => void) | undefined;
    const pending = new Promise<Response>((resolve) => { resolvePin = resolve; });
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/pin?pinned=true")) {
        pinCalls += 1;
        return pending;
      }
      return baseResponse(url);
    }));

    render(<Sidebar collapsed={false} />);
    await waitFor(() => expect(screen.getByText("会话一")).toBeInTheDocument());
    const pin = screen.getByTitle("置顶") as HTMLButtonElement;
    fireEvent.click(pin);
    await waitFor(() => expect(pin.disabled).toBe(true));
    fireEvent.click(pin);
    expect(pinCalls).toBe(1);
    resolvePin?.(new Response(JSON.stringify({ status: "ok" }), { status: 200 }));
    await waitFor(() => expect(pin.disabled).toBe(false));
  });

  it("failed archive is visibly reported and does not pretend the session changed", async () => {
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/archive?archived=true")) {
        return new Response(JSON.stringify({ error: "busy" }), { status: 409 });
      }
      return baseResponse(url);
    }));

    render(<Sidebar collapsed={false} />);
    await waitFor(() => expect(screen.getByText("会话一")).toBeInTheDocument());
    fireEvent.click(screen.getByTitle("归档到归档文件夹（防误操作）"));
    await waitFor(() => expect(screen.getByTestId("sidebar-action-error")).toHaveTextContent("归档失败"));
    expect(screen.getByText("会话一")).toBeInTheDocument();
  });

  it("failed delete keeps current session and reports the failure", async () => {
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (init?.method === "DELETE" && url.includes("/api/v1/sessions/s1")) {
        return new Response(JSON.stringify({ error: "resource_busy" }), { status: 409 });
      }
      return baseResponse(url);
    }));

    render(<Sidebar collapsed={false} />);
    await waitFor(() => expect(screen.getByText("会话一")).toBeInTheDocument());
    fireEvent.click(screen.getByTitle("删除会话"));
    fireEvent.click(screen.getByText("确认?"));
    await waitFor(() => expect(screen.getByTestId("sidebar-action-error")).toHaveTextContent("删除失败"));
    expect(sessionStore.getState().currentSessionId).toBe("s1");
  });
});

describe("workspace switch controls", () => {
  it("failed workspace switch is visible and does not open the target session", async () => {
    const other = { ...SESSION, session_id: "other-s", title: "其他会话" };
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.includes("/api/v1/workspaces/switch") && init?.method === "POST") {
        return new Response(JSON.stringify({ error: "busy" }), { status: 409 });
      }
      if (url.includes("/api/v1/workspaces/ws-other/sessions")) {
        return new Response(JSON.stringify({ sessions: [other], count: 1 }), { status: 200 });
      }
      if (url.includes("/api/v1/workspaces") && !url.includes("/sessions")) {
        return new Response(JSON.stringify({ workspaces: [
          { id: "ws", path: "/ws" },
          { id: "ws-other", path: "/other" },
        ], current: "ws" }), { status: 200 });
      }
      return baseResponse(url);
    }));

    render(<Sidebar collapsed={false} />);
    await waitFor(() => expect(screen.getByText("其他会话")).toBeInTheDocument());
    fireEvent.click(screen.getByText("其他会话"));
    await waitFor(() => expect(screen.getByText(/工作区切换失败/)).toBeInTheDocument());
    expect(sessionStore.getState().currentSessionId).toBe("s1");
  });
});
