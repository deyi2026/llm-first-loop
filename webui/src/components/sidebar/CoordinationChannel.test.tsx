import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { sidebarViewStore } from "../../core/stores";
import { CoordinationChannel } from "./CoordinationChannel";

afterEach(() => {
  cleanup();
  vi.clearAllTimers();
  vi.useRealTimers();
  vi.unstubAllGlobals();
  sidebarViewStore.setView("sessions");
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
});
