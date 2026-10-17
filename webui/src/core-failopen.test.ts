import { afterEach, describe, expect, it, vi } from "vitest";
import { api, fetchSessionsResult } from "./core/api";
import { fetchHistory, fetchModels, streamChatRequest } from "./core/chat";

describe("core fetch fail-open", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("deduplicates simultaneous sidebar session list reads", async () => {
    let release!: (r: Response) => void;
    const pending = new Promise<Response>((resolve) => { release = resolve; });
    const fetchMock = vi.fn(() => pending);
    vi.stubGlobal("fetch", fetchMock);
    const a = fetchSessionsResult();
    const b = fetchSessionsResult();
    expect(fetchMock).toHaveBeenCalledTimes(1);
    release(new Response(JSON.stringify({ sessions: [], count: 0 }), { status: 200 }));
    expect((await a).ok).toBe(true);
    expect((await b).ok).toBe(true);
  });

  it("stops waiting for an unresponsive session index without deleting saved sessions", async () => {
    vi.useFakeTimers();
    let release!: (response: Response) => void;
    let requestSignal: AbortSignal | undefined;
    vi.stubGlobal("fetch", vi.fn((_url: RequestInfo | URL, options?: RequestInit) => {
      requestSignal = options?.signal ?? undefined;
      return new Promise<Response>((resolve) => { release = resolve; });
    }));
    const pending = fetchSessionsResult();
    try {
      await vi.advanceTimersByTimeAsync(21000);
      expect(requestSignal?.aborted).toBe(true);
    } finally {
      release(new Response(JSON.stringify({ sessions: [], count: 0 }), { status: 200 }));
      await pending;
      vi.useRealTimers();
    }
  });

  it("times out an unresponsive history request rather than hanging indefinitely", async () => {
    vi.useFakeTimers();
    try {
      vi.stubGlobal("fetch", vi.fn((_url: RequestInfo | URL, options?: RequestInit) =>
        new Promise<Response>((_resolve, reject) => {
          options?.signal?.addEventListener("abort", () =>
            reject(new DOMException("aborted", "AbortError"))
          );
        })
      ));
      const result = fetchHistory("slow", 100, 0);
      await vi.advanceTimersByTimeAsync(15000);
      expect((await result).error).toContain("超时");
    } finally {
      vi.useRealTimers();
    }
  });

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
    await expect(fetchHistory("s1", 100, 0)).resolves.toMatchObject({
      ok: false,
      messages: [],
      has_more: false,
    });
  });

  it("fetchHistory distinguishes network failure from a real empty history", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => { throw new TypeError("offline"); }));
    const out = await fetchHistory("s1", 100, 0);
    expect(out.ok).toBe(false);
    expect(out.error).toContain("历史");
  });
});
