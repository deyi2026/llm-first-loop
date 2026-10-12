import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { SessionStats } from "./components/conversation/SessionStats";

afterEach(() => {
  cleanup();
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
