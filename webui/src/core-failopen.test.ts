import { afterEach, describe, expect, it, vi } from "vitest";
import { api } from "./core/api";
import { fetchHistory, fetchModels, streamChatRequest } from "./core/chat";

describe("core fetch fail-open", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("generic api converts network rejection to status=0", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => { throw new TypeError("offline"); }));
    await expect(api<{ value: string }>("/api/v1/test")).resolves.toEqual({ status: 0, data: {} });
  });

  it("fetchModels returns empty catalog when fetch rejects", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => { throw new TypeError("offline"); }));
    await expect(fetchModels()).resolves.toEqual({ models: [], current: null, catalog: [] });
  });

  it("streamChatRequest exposes run_started exact generation before later deltas", async () => {
    const enc = new TextEncoder();
    const frames = [
      'data: {"type":"run_started","data":{"session_id":"s1","run_generation":"gen-parser-1"}}\n\n',
      'data: {"type":"reasoning_delta","data":{"data":"thinking"}}\n\n',
      'data: {"type":"done","data":{"session_id":"s1","final_answer":"done"}}\n\n',
    ];
    vi.stubGlobal("fetch", vi.fn(async () => new Response(new ReadableStream<Uint8Array>({
      start(controller) {
        for (const frame of frames) controller.enqueue(enc.encode(frame));
        controller.close();
      },
    }), { status: 200 })));
    const onRunStarted = vi.fn();
    const onReasoningDelta = vi.fn();
    const out = await streamChatRequest(
      { message: "x", session_id: "s1" },
      { onRunStarted, onReasoningDelta }
    );
    expect(out.ok).toBe(true);
    expect(onRunStarted).toHaveBeenCalledWith({ session_id: "s1", run_generation: "gen-parser-1" });
    expect(onReasoningDelta).toHaveBeenCalledWith("thinking");
  });

  it("fetchHistory validates a 200 response shape before consumers map it", async () => {
    vi.stubGlobal("fetch", vi.fn(async () =>
      new Response(JSON.stringify({ sessions: [{ session_id: "wrong-shape" }] }), { status: 200 })
    ));
    await expect(fetchHistory("s1", 100, 0)).resolves.toEqual({ messages: [], has_more: false });
  });
});
