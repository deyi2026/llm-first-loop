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
