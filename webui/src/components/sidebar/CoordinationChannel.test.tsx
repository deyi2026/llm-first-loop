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
