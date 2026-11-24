import { afterEach, describe, expect, it, vi } from "vitest";
import { clearAuthRequired, reportUnauthorized } from "./authSession";
import { createSessionListPoller } from "./sessionListPoll";

const ok = (item: string) => ({ ok: true, items: [item], status: 200 });
const fail = { ok: false, items: [], status: 503 };

afterEach(() => {
  clearAuthRequired();
  vi.useRealTimers();
  vi.restoreAllMocks();
});

describe("shared session list reads", () => {
  it("uses one timer and the fastest mounted cadence; hidden and unmounted tabs do not poll", async () => {
    vi.useFakeTimers();
    const hidden = vi.spyOn(document, "hidden", "get").mockReturnValue(false);
    let count = 0;
    const read = vi.fn(async () => ok(String(++count)));
    const poller = createSessionListPoller(read);
    const a = vi.fn(), b = vi.fn();
    const first = poller.subscribe("s1", a, 5000);
    let second: ReturnType<typeof poller.subscribe> | undefined;
    try {
      second = poller.subscribe("s1", b, 2000);
      await poller.refresh("s1");
      expect(read).toHaveBeenCalledTimes(1);
      expect(a).toHaveBeenLastCalledWith({ items: ["1"], stale: false });
      expect(b).toHaveBeenLastCalledWith({ items: ["1"], stale: false });
      await vi.advanceTimersByTimeAsync(10000);
      expect(read).toHaveBeenCalledTimes(6);
      second.unsubscribe(); second = undefined;
      first.setIntervalMs(20000);
      await vi.advanceTimersByTimeAsync(19000);
      expect(read).toHaveBeenCalledTimes(6);
      await vi.advanceTimersByTimeAsync(1000);
      expect(read).toHaveBeenCalledTimes(7);
      hidden.mockReturnValue(true);
      await vi.advanceTimersByTimeAsync(40000);
      expect(read).toHaveBeenCalledTimes(7);
      hidden.mockReturnValue(false);
      document.dispatchEvent(new Event("visibilitychange"));
      await poller.refresh("s1");
      expect(read).toHaveBeenCalledTimes(8);
      first.unsubscribe();
      await vi.advanceTimersByTimeAsync(40000);
      expect(read).toHaveBeenCalledTimes(8);
    } finally { first.unsubscribe(); second?.unsubscribe(); }
  });

  it("shares a slow read, aborts at timeout, preserves the last good snapshot and recovers", async () => {
    vi.useFakeTimers();
    vi.spyOn(document, "hidden", "get").mockReturnValue(false);
    const read = vi.fn<(sid: string, signal: AbortSignal) => Promise<ReturnType<typeof ok>>>()
      .mockResolvedValueOnce(ok("good"))
      .mockImplementationOnce((_sid, signal) => new Promise(resolve => {
        signal.addEventListener("abort", () => resolve(fail), { once: true });
      }))
      .mockResolvedValue(ok("recovered"));
    const poller = createSessionListPoller(read);
    const listener = vi.fn();
    const sub = poller.subscribe("s1", listener, 2000);
    try {
      await poller.refresh("s1");
      const slow = poller.refresh("s1");
      await vi.advanceTimersByTimeAsync(8000);
      expect(read).toHaveBeenCalledTimes(2);
      await vi.advanceTimersByTimeAsync(2000);
      await slow;
      expect(listener).toHaveBeenLastCalledWith({ items: ["good"], stale: true });
      await poller.refresh("s1");
      expect(listener).toHaveBeenLastCalledWith({ items: ["recovered"], stale: false });
      expect(read).toHaveBeenCalledTimes(3);
    } finally { sub.unsubscribe(); }
  });

  it("invalidates a pre-mutation read and ignores its late response", async () => {
    vi.spyOn(document, "hidden", "get").mockReturnValue(false);
    let resolve!: (value: ReturnType<typeof ok>) => void;
    const read = vi.fn<(sid: string, signal: AbortSignal) => Promise<ReturnType<typeof ok>>>()
      .mockImplementationOnce(() => new Promise(done => { resolve = done; }))
      .mockResolvedValue(ok("after"));
    const poller = createSessionListPoller(read);
    const listener = vi.fn();
    const sub = poller.subscribe("s1", listener, 5000);
    try {
      const old = poller.refresh("s1");
      await Promise.resolve();
      await poller.refresh("s1", true);
      expect(read.mock.calls[0][1].aborted).toBe(true);
      resolve(ok("before"));
      await old;
      expect(listener).toHaveBeenLastCalledWith({ items: ["after"], stale: false });
      expect(read).toHaveBeenCalledTimes(2);
    } finally { sub.unsubscribe(); }
  });

  it("clears data on auth boundaries and ignores old results after logout or session removal", async () => {
    vi.spyOn(document, "hidden", "get").mockReturnValue(false);
    let resolve!: (value: ReturnType<typeof ok>) => void;
    const read = vi.fn<(sid: string, signal: AbortSignal) => Promise<ReturnType<typeof ok>>>()
      .mockResolvedValueOnce(ok("private"))
      .mockImplementationOnce(() => new Promise(done => { resolve = done; }))
      .mockImplementation(async sid => ok(sid));
    const poller = createSessionListPoller(read);
    const a = vi.fn(), b = vi.fn();
    const first = poller.subscribe("s1", a, 5000);
    let second: ReturnType<typeof poller.subscribe> | undefined;
    try {
      await poller.refresh("s1");
      const old = poller.refresh("s1");
      await Promise.resolve();
      reportUnauthorized(401);
      expect(a).toHaveBeenLastCalledWith({ items: [], stale: false });
      await poller.refresh("s1");
      expect(read).toHaveBeenCalledTimes(2);
      first.unsubscribe();
      second = poller.subscribe("s2", b, 5000);
      clearAuthRequired();
      await poller.refresh("s2");
      resolve(ok("old"));
      await old;
      expect(a).toHaveBeenLastCalledWith({ items: [], stale: false });
      expect(b).toHaveBeenLastCalledWith({ items: ["s2"], stale: false });
      expect(read).toHaveBeenCalledTimes(3);
    } finally { first.unsubscribe(); second?.unsubscribe(); }
  });
});
