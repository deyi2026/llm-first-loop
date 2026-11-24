import { afterEach, describe, expect, it, vi } from "vitest";
import { clearAuthRequired, isAuthRequired, reportUnauthorized } from "./authSession";
import { fetchCoordinationBoard, refreshCoordinationBoard, subscribeCoordinationBoard } from "./coordinationBoard";

afterEach(() => {
  clearAuthRequired();
  vi.unstubAllGlobals();
  vi.useRealTimers();
  vi.restoreAllMocks();
});

describe("shared coordination board polling", () => {
  it("coalesces concurrent Channel and Lane Board GETs and releases on completion", async () => {
    let resolve!: (response: Response) => void;
    const fetchMock = vi.fn()
      .mockImplementationOnce(() => new Promise<Response>((done) => { resolve = done; }))
      .mockResolvedValue(new Response(JSON.stringify({ channel: { active_lanes: 3 } }), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    const a = fetchCoordinationBoard<{ channel: { active_lanes: number } }>();
    const b = fetchCoordinationBoard<{ channel: { active_lanes: number } }>();
    expect(fetchMock).toHaveBeenCalledTimes(1);
    resolve(new Response(JSON.stringify({ channel: { active_lanes: 2 } }), { status: 200 }));
    expect((await a)?.channel.active_lanes).toBe(2);
    expect((await b)?.channel.active_lanes).toBe(2);
    const next = await fetchCoordinationBoard();
    expect(next).not.toBeNull();
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("an unauthorized board read sets login-required and prevents another network request", async () => {
    const fetchMock = vi.fn(async () => new Response("{}", { status: 401 }));
    vi.stubGlobal("fetch", fetchMock);
    expect(await fetchCoordinationBoard()).toBeNull();
    expect(isAuthRequired()).toBe(true);
    expect(await fetchCoordinationBoard()).toBeNull();
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("shares one timer across staggered subscribers, refreshes on visibility, and stops on unmount", async () => {
    vi.useFakeTimers();
    const hidden = vi.spyOn(document, "hidden", "get").mockReturnValue(false);
    let count = 0;
    const fetchMock = vi.fn(async () => new Response(JSON.stringify({ sequence: ++count }), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    const a = vi.fn(), b = vi.fn();
    const offA = subscribeCoordinationBoard(a);
    let offB: (() => void) | undefined;
    try {
      await refreshCoordinationBoard();
      expect(a).toHaveBeenLastCalledWith({ sequence: 1 });
      await vi.advanceTimersByTimeAsync(5000);
      offB = subscribeCoordinationBoard(b);
      expect(b).toHaveBeenLastCalledWith({ sequence: 1 });
      expect(fetchMock).toHaveBeenCalledTimes(1);
      await vi.advanceTimersByTimeAsync(5000);
      expect(fetchMock).toHaveBeenCalledTimes(2);
      expect(a).toHaveBeenLastCalledWith({ sequence: 2 });
      expect(b).toHaveBeenLastCalledWith({ sequence: 2 });
      hidden.mockReturnValue(true);
      await vi.advanceTimersByTimeAsync(20000);
      expect(fetchMock).toHaveBeenCalledTimes(2);
      hidden.mockReturnValue(false);
      document.dispatchEvent(new Event("visibilitychange"));
      await refreshCoordinationBoard();
      expect(fetchMock).toHaveBeenCalledTimes(3);
      offA(); offB(); offB = undefined;
      await vi.advanceTimersByTimeAsync(20000);
      expect(fetchMock).toHaveBeenCalledTimes(3);
    } finally { offA(); offB?.(); }
  });

  it("discards late responses after the last subscriber leaves", async () => {
    vi.spyOn(document, "hidden", "get").mockReturnValue(false);
    let resolve!: (response: Response) => void;
    vi.stubGlobal("fetch", vi.fn(() => new Promise<Response>(done => { resolve = done; })));
    const listener = vi.fn();
    const off = subscribeCoordinationBoard(listener);
    const pending = refreshCoordinationBoard();
    off();
    resolve(new Response(JSON.stringify({ sequence: 1 }), { status: 200 }));
    await pending;
    expect(listener).not.toHaveBeenCalled();
  });

  it("does not publish an old in-flight snapshot after login state changes", async () => {
    vi.spyOn(document, "hidden", "get").mockReturnValue(false);
    let resolve!: (response: Response) => void;
    const fetchMock = vi.fn()
      .mockImplementationOnce(() => new Promise<Response>(done => { resolve = done; }))
      .mockResolvedValue(new Response(JSON.stringify({ sequence: 2 }), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    const listener = vi.fn();
    const off = subscribeCoordinationBoard(listener);
    try {
      const old = refreshCoordinationBoard();
      reportUnauthorized(401);
      expect(listener).toHaveBeenLastCalledWith(null);
      clearAuthRequired();
      await refreshCoordinationBoard();
      expect(listener).toHaveBeenLastCalledWith({ sequence: 2 });
      resolve(new Response(JSON.stringify({ sequence: 1 }), { status: 200 }));
      await old;
      expect(listener).toHaveBeenLastCalledWith({ sequence: 2 });
      expect(listener).not.toHaveBeenCalledWith({ sequence: 1 });
    } finally { off(); }
  });
});
