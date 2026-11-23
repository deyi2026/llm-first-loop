import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { LaneBoard } from "./LaneBoard";
import { mainViewStore, sessionStore } from "../../core/stores";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  mainViewStore.setView("chat");
  sessionStore.setCurrentSession("");
  sessionStore.setNewSessionPending(false);
});

describe("Lane Board scroll surface", () => {
  it("keeps a keyboard-focusable scroll region around a wide, populated board", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({
      generated_at: "2026-11-23T00:00:00Z",
      main_head: "a".repeat(40),
      deployment: { in_sync: true, deployed_sha: "a".repeat(40) },
      lanes: Array.from({ length: 35 }, (_, i) => ({
        lane_id: `lane-${i}`, branch: `feature/test-long-branch-${i}`,
        goal_id: `GOAL-${i}`, lane_role: "main", status: "active",
        head_sha: "a".repeat(40), base_main_sha: "a".repeat(40),
        verify_ref: "", priority: "normal", paths: [], last_activity: "",
      })),
      overlaps: [], degraded: [],
    }), { status: 200 })));
    render(<LaneBoard />);
    const table = await screen.findByTestId("lane-table");
    const scroll = screen.getByTestId("lane-board-scroll");
    expect(scroll).toContainElement(table);
    expect(scroll).toHaveClass("v2-evo-body", "v2-lane-board-scroll");
    expect(scroll).toHaveAttribute("tabindex", "0");
    expect(scroll).toHaveAttribute("aria-label", "协同看板内容");
    expect(screen.getAllByTestId("lane-row")).toHaveLength(35);
  });
  it("opens each Goal's exact Lane session and never guesses missing or mismatched owners", async () => {
    const onNavigate = vi.fn();
    const fetchMock = vi.fn(async () => new Response(JSON.stringify({
      generated_at: "2026-11-23T00:00:00Z", main_head: "a".repeat(40),
      deployment: { in_sync: true, deployed_sha: "a".repeat(40) },
      lanes: [
        { lane_id: "lane-a", goal_id: "GOAL-shared", branch: "feature-a", status: "active" },
        { lane_id: "lane-b", goal_id: "GOAL-shared", branch: "feature-b", status: "active" },
        { lane_id: "lane-c", goal_id: "GOAL-c", branch: "feature-c", status: "open" },
        { lane_id: "lane-d", goal_id: "GOAL-d", branch: "feature-d", status: "active" },
        { lane_id: "lane-e", goal_id: "GOAL-e", branch: "feature-e", status: "active" },
      ],
      channel: { sessions: [
        { lane_id: "lane-a", goal_id: "GOAL-shared", session_id: "session-a" },
        { lane_id: "lane-b", goal_id: "GOAL-shared", session_id: "session-b" },
        { lane_id: "lane-c", goal_id: "GOAL-wrong", session_id: "session-wrong" },
        { lane_id: "lane-d", goal_id: "GOAL-d", session_id: "" },
        { lane_id: "lane-e", goal_id: "GOAL-e", session_id: "session-first" },
        { lane_id: "lane-e", goal_id: "GOAL-e", session_id: "session-conflicting" },
      ] },
      overlaps: [], degraded: [],
    }), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    mainViewStore.setView("learning");
    sessionStore.setNewSessionPending(true);
    render(<LaneBoard onNavigate={onNavigate} />);
    const buttons = await screen.findAllByTestId("lane-goal-open-session");
    expect(buttons).toHaveLength(2);
    expect(buttons[0]).toHaveStyle({ minHeight: "44px" });
    expect(screen.getAllByTestId("lane-goal-unbound")).toHaveLength(3);
    fireEvent.click(buttons[1]);
    expect(sessionStore.getState().currentSessionId).toBe("session-b");
    expect(sessionStore.getState().newSessionPending).toBe(false);
    expect(mainViewStore.getState().view).toBe("chat");
    expect(onNavigate).toHaveBeenCalledOnce();
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});
