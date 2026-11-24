import { afterEach, describe, expect, it, vi } from "vitest";
import { refreshQueue, conversationStore } from "./conversation";
import { sessionStore } from "./stores";
import { clearAuthRequired, reportUnauthorized } from "./authSession";

const response = (id: string) => new Response(JSON.stringify({
  items: [{ queue_id: id, session_id: "s1", status: "queued" }],
}), { status: 200 });

afterEach(() => {
  clearAuthRequired();
  sessionStore.setCurrentSession("");
  conversationStore.setState({ queueItems: [] });
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

describe("queue read sharing", () => {
  it("coalesces concurrent reads and invalidates a pre-mutation response", async () => {
    sessionStore.setCurrentSession("s1");
    let resolve!: (value: Response) => void;
    const fetchMock = vi.fn()
      .mockImplementationOnce(() => new Promise<Response>(done => { resolve = done; }))
      .mockResolvedValueOnce(response("new"));
    vi.stubGlobal("fetch", fetchMock);
    const old = refreshQueue("s1");
    const same = refreshQueue("s1");
    expect(fetchMock).toHaveBeenCalledTimes(1);
    await refreshQueue("s1", true);
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(fetchMock.mock.calls[0][1].signal.aborted).toBe(true);
    resolve(response("old"));
    await Promise.all([old, same]);
    expect(conversationStore.getState().queueItems.map(x => x.queue_id)).toEqual(["new"]);
  });

  it("discards late results across session switch and auth invalidation", async () => {
    sessionStore.setCurrentSession("s1");
    let resolve!: (value: Response) => void;
    vi.stubGlobal("fetch", vi.fn()
      .mockImplementationOnce(() => new Promise<Response>(done => { resolve = done; }))
      .mockResolvedValueOnce(response("fresh")));
    const old = refreshQueue("s1");
    sessionStore.setCurrentSession("s2");
    sessionStore.setCurrentSession("s1");
    await refreshQueue("s1");
    resolve(response("old"));
    await old;
    expect(conversationStore.getState().queueItems.map(x => x.queue_id)).toEqual(["fresh"]);
    reportUnauthorized(401);
    expect(conversationStore.getState().queueItems).toEqual([]);
  });
});
