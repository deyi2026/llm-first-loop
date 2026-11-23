import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { LaneBoard } from "./LaneBoard";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
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
});
