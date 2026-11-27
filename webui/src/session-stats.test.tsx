import { afterEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, render, screen, waitFor } from "@testing-library/react";
import { SessionStats } from "./components/conversation/SessionStats";

afterEach(() => {
  cleanup();
  vi.clearAllTimers();
  vi.useRealTimers();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("SessionStats runtime projection", () => {
  it("partial/older stats response never renders NaN or undefined telemetry", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        new Response(JSON.stringify({ turns: 2, steps: 3, tokens_in: null, tok_s: "unknown" }), {
          status: 200,
        })
      )
    );
    render(<SessionStats sessionId="s1" />);
    const stats = await screen.findByTestId("session-stats");
    expect(stats).toHaveTextContent("2 轮 · 3 步");
    expect(stats.textContent).not.toMatch(/NaN|undefined/);
    expect(stats).toHaveTextContent("输入 0 tok · 输出 0 tok");
    expect(stats).toHaveTextContent("缓存命中 未上报（累计）");
  });

  it("subagent keeps unknown Provider cache as unknown, not a false 0% miss", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => new Response(JSON.stringify({
        turns: 1, steps: 1, tokens_in: 400, cache_hit: 0,
        cache_hit_rate: null,
        usage_source: "provider.transport.settled",
        agent_scope: { kind: "subagent", parent_session_id: "parent" },
      }), { status: 200 }))
    );
    render(<SessionStats sessionId="subagent_abc" />);
    const stats = await screen.findByTestId("session-stats");
    expect(stats).toHaveTextContent("子代理 · 1 轮 · 1 步");
    expect(stats).toHaveTextContent("缓存命中 未上报（累计）");
    expect(stats).not.toHaveTextContent("缓存命中 0%");
  });

  it("non-object response is treated as unavailable rather than fabricated stats", async () => {
    const fetchMock = vi.fn(async () => new Response(JSON.stringify(null), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    render(<SessionStats sessionId="s1" />);
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    await Promise.resolve();
    expect(screen.queryByTestId("session-stats")).toBeNull();
  });
});


describe("SessionStats polling load", () => {
  it("hidden tabs do not poll and visibility restores one request", async () => {
    vi.useFakeTimers();
    const hidden = vi.spyOn(document, "hidden", "get").mockReturnValue(true);
    const fetchMock = vi.fn(async () => new Response(JSON.stringify({ turns: 1, steps: 1 })));
    vi.stubGlobal("fetch", fetchMock);
    render(<SessionStats sessionId="s1" />);
    act(() => { vi.advanceTimersByTime(120_000); });
    expect(fetchMock).not.toHaveBeenCalled();
    hidden.mockReturnValue(false);
    await act(async () => { document.dispatchEvent(new Event("visibilitychange")); });
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("never overlaps a slow request and aborts it when switching sessions", async () => {
    vi.useFakeTimers();
    const fetchMock = vi.fn((_url: string, _init: RequestInit) => new Promise<Response>(() => {}));
    vi.stubGlobal("fetch", fetchMock);
    const view = render(<SessionStats sessionId="s1" />);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const firstSignal = fetchMock.mock.calls[0][1].signal;
    act(() => { vi.advanceTimersByTime(120_000); });
    expect(firstSignal?.aborted).toBe(true);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    view.rerender(<SessionStats sessionId="s2" />);
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(fetchMock.mock.calls[1][0]).toContain("/s2/stats");
    view.unmount();
    expect(fetchMock.mock.calls[1][1].signal?.aborted).toBe(true);
  });
});
