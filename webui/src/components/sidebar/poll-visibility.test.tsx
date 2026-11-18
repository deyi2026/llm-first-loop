import { act, cleanup, render } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { CoordinationChannel } from "./CoordinationChannel";
import { LaneBoard } from "./LaneBoard";

afterEach(() => {
  cleanup();
  vi.clearAllTimers();
  vi.useRealTimers();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("协同面板隐藏标签页轮询", () => {
  for (const [name, view] of [
    ["LaneBoard", <LaneBoard />],
    ["CoordinationChannel", <CoordinationChannel collapsed={false} />],
  ] as const) {
    it(name + " 隐藏时不请求，恢复可见立即同步", async () => {
      vi.useFakeTimers();
      const hidden = vi.spyOn(document, "hidden", "get").mockReturnValue(true);
      const fetchMock = vi.fn(async () =>
        new Response(JSON.stringify({ channel: null, lanes: [], overlaps: [], degraded: [], deployment: { in_sync: true, deployed_sha: "" }, main_head: "" }), { status: 200 })
      );
      vi.stubGlobal("fetch", fetchMock);
      const rendered = render(view);
      expect(fetchMock).not.toHaveBeenCalled();
      act(() => { vi.advanceTimersByTime(10_000); });
      expect(fetchMock).not.toHaveBeenCalled();

      hidden.mockReturnValue(false);
      await act(async () => {
        document.dispatchEvent(new Event("visibilitychange"));
        await Promise.resolve();
      });
      expect(fetchMock).toHaveBeenCalledTimes(1);
      act(() => { vi.advanceTimersByTime(10_000); });
      expect(fetchMock).toHaveBeenCalledTimes(2);

      hidden.mockReturnValue(true);
      act(() => { vi.advanceTimersByTime(10_000); });
      expect(fetchMock).toHaveBeenCalledTimes(2);
      rendered.unmount();
    });
  }
});
