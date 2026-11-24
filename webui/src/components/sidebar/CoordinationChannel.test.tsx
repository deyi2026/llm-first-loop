import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { mainViewStore, sessionStore, sidebarViewStore } from "../../core/stores";
import { CoordinationChannel } from "./CoordinationChannel";

afterEach(() => {
  cleanup();
  vi.clearAllTimers();
  vi.useRealTimers();
  vi.unstubAllGlobals();
  sidebarViewStore.setView("sessions");
  mainViewStore.setView("chat");
  sessionStore.setCurrentSession("");
  sessionStore.setNewSessionPending(false);
});

describe("Coordination Channel live updates", () => {
  it("renders the real channel projection and refreshes counts without clearing it", async () => {
    vi.useFakeTimers();
    let active = 1;
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({
      channel: {
        active_lanes: active, pending_help: 0, blocking_help: 0,
        needs_decision: 0, sessions: [],
      },
    }), { status: 200 })));
    render(<CoordinationChannel collapsed={false} />);
    await act(async () => { await Promise.resolve(); await Promise.resolve(); });
    expect(screen.getByTestId("coordination-channel-row")).toHaveTextContent("协调 1 活跃");
    active = 2;
    await act(async () => {
      vi.advanceTimersByTime(10_000);
      await Promise.resolve();
      await Promise.resolve();
    });
    expect(screen.getByTestId("coordination-channel-row")).toHaveTextContent("协调 2 活跃");
  });

  it("keeps an expanded coordination list independently scrollable", async () => {
    sidebarViewStore.setView("lanes");
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({
      channel: {
        active_lanes: 35, pending_help: 0, blocking_help: 0, needs_decision: 0,
        sessions: Array.from({ length: 35 }, (_, i) => ({
          session_id: `session-${i}`, lane_id: `lane-${i}`, goal_id: `goal-${i}`,
          branch: `feature-${i}`, status: "active", last_activity: "",
        })),
      },
    }), { status: 200 })));
    render(<CoordinationChannel collapsed={false} />);
    const row = await screen.findByTestId("coordination-channel-row");
    fireEvent.click(row);
    const list = screen.getByTestId("coordination-channel-sessions");
    expect(list).toHaveStyle({ overflowY: "auto" });
    expect(list).toHaveAttribute("tabindex", "0");
    expect(screen.getAllByTestId("coordination-channel-session")).toHaveLength(35);
  });
  it("opens the exact bound Goal session without starting a Run and closes mobile navigation", async () => {
    const onNavigate = vi.fn();
    const fetchMock = vi.fn(async () => new Response(JSON.stringify({
      channel: {
        active_lanes: 1, pending_help: 0, blocking_help: 0, needs_decision: 0,
        sessions: [{ session_id: "session-bound", lane_id: "lane-a", goal_id: "GOAL-a",
          branch: "feature-a", status: "active", last_activity: "" }],
      },
    }), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    sidebarViewStore.setView("sessions");
    mainViewStore.setView("learning");
    sessionStore.setNewSessionPending(true);
    render(<CoordinationChannel collapsed={false} onNavigate={onNavigate} />);
    fireEvent.click(await screen.findByTestId("coordination-channel-row"));
    expect(sidebarViewStore.getState().view).toBe("lanes");
    expect(screen.getByTestId("coordination-channel-sessions")).toBeInTheDocument();
    const open = screen.getByRole("button", { name: "打开 Goal GOAL-a 的会话" });
    expect(open).toHaveStyle({ minHeight: "44px" });
    fireEvent.click(open);
    expect(sessionStore.getState().currentSessionId).toBe("session-bound");
    expect(sessionStore.getState().newSessionPending).toBe(false);
    expect(mainViewStore.getState().view).toBe("chat");
    expect(onNavigate).toHaveBeenCalledOnce();
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("shows an unbound Goal as non-clickable instead of guessing a session", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({
      channel: { active_lanes: 1, pending_help: 0, blocking_help: 0, needs_decision: 0,
        sessions: [
          { session_id: "", lane_id: "lane-missing", goal_id: "GOAL-missing",
            branch: "feature-missing", status: "open", last_activity: "" },
          { session_id: "session-no-goal", lane_id: "lane-no-goal", goal_id: "",
            branch: "feature-no-goal", status: "active", last_activity: "" },
        ] },
    }), { status: 200 })));
    sidebarViewStore.setView("lanes");
    render(<CoordinationChannel collapsed={false} />);
    fireEvent.click(await screen.findByTestId("coordination-channel-row"));
    expect(screen.getAllByTestId("coordination-channel-session-unbound")).toHaveLength(2);
    expect(screen.getAllByTestId("coordination-channel-session-unbound")[0]).toHaveTextContent("未绑定会话");
    expect(screen.queryByRole("button", { name: /未关联 Goal/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /打开 Goal GOAL-missing/ })).not.toBeInTheDocument();
  });
});


describe("Coordination delivery", () => {
  function installDelivery(running: boolean, insertStatus = 202) {
    return vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const reply = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });
      if (url.includes("/coordination/board")) return reply({ channel: {
        active_lanes: 1, pending_help: 9, blocking_help: 1, needs_decision: 1,
        sessions: [{ session_id: "target", lane_id: "lane", goal_id: "GOAL-target", branch: "fix", status: "active", last_activity: "" }],
        help_items: Array.from({ length: 9 }, (_, i) => ({
          id: "help-" + i, topic: "topic-" + i, from_session: "requester-" + i,
          to_session: "target", need: "block", lane_id: "lane", since: "",
        })),
      } });
      if (url.includes("/chat/stream/status")) return reply({ running, run_generation: running ? "gen-A" : undefined });
      if (url.includes("/chat/queue/interject")) return reply(
        insertStatus === 202 ? { state: "interject_pending" } : { detail: "当前任务已变化；消息仍保留在普通排队中" }, insertStatus);
      if (url === "/api/v1/chat/queue" && init?.method === "POST") return reply({ queue_id: "q-1", position: 1 }, 202);
      return reply({ items: [], count: 0 });
    });
  }

  it("queues an idle requester's reply without switching the current session or hiding later requests", async () => {
    const fetchMock = installDelivery(false);
    vi.stubGlobal("fetch", fetchMock);
    sessionStore.setCurrentSession("source");
    render(<CoordinationChannel collapsed={false} />);
    fireEvent.click(await screen.findByTestId("coordination-channel-row"));
    expect(screen.getAllByTestId("coordination-channel-help-item")).toHaveLength(9);
    fireEvent.click(screen.getAllByRole("button", { name: "回复请求方" })[8]);
    const wake = await screen.findByRole("button", { name: "唤醒执行（排队）" });
    fireEvent.change(screen.getByRole("textbox", { name: "协助指令" }), { target: { value: "请继续核验" } });
    fireEvent.click(wake);
    await screen.findByText(/已加入目标会话队列/);
    const post = fetchMock.mock.calls.find(([url, init]) => url === "/api/v1/chat/queue" && init?.method === "POST");
    expect(JSON.parse(String(post?.[1]?.body))).toMatchObject({ session_id: "requester-8", message: "请继续核验" });
    expect(sessionStore.getState().currentSessionId).toBe("source");
    expect(fetchMock.mock.calls.some(([url]) => String(url).includes("/interject"))).toBe(false);
  });

  it("binds urgent delivery to the displayed target generation and never resubmits after a conflict", async () => {
    const fetchMock = installDelivery(true, 409);
    vi.stubGlobal("fetch", fetchMock);
    render(<CoordinationChannel collapsed={false} />);
    fireEvent.click(await screen.findByTestId("coordination-channel-row"));
    fireEvent.click(screen.getByRole("button", { name: "协助 Goal GOAL-target" }));
    await screen.findByText("当前 Run 运行中");
    fireEvent.change(screen.getByRole("textbox", { name: "协助指令" }), { target: { value: "暂停下一步" } });
    fireEvent.click(screen.getByRole("button", { name: "紧急插入" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("消息仍保留在普通排队中");
    const post = fetchMock.mock.calls.find(([url]) => String(url).includes("/chat/queue/interject"));
    expect(JSON.parse(String(post?.[1]?.body))).toEqual({ session_id: "target", queue_id: "q-1", run_generation: "gen-A" });
    expect(fetchMock.mock.calls.filter(([url, init]) => url === "/api/v1/chat/queue" && init?.method === "POST")).toHaveLength(1);
    expect(screen.getByRole("textbox", { name: "协助指令" })).toHaveValue("");
  });

  it("reports urgent admission as pending, not as already received or executed", async () => {
    const fetchMock = installDelivery(true);
    vi.stubGlobal("fetch", fetchMock);
    render(<CoordinationChannel collapsed={false} />);
    fireEvent.click(await screen.findByTestId("coordination-channel-row"));
    fireEvent.click(screen.getByRole("button", { name: "协助 Goal GOAL-target" }));
    await screen.findByText("当前 Run 运行中");
    fireEvent.change(screen.getByRole("textbox", { name: "协助指令" }), { target: { value: "核对证据" } });
    fireEvent.click(screen.getByRole("button", { name: "紧急插入" }));
    expect(await screen.findByText(/插入请求已受理，等待当前 Run 安全接收/)).toHaveTextContent("q-1");
  });

});
