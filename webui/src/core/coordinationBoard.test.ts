import { afterEach, describe, expect, it, vi } from "vitest";
import { clearAuthRequired, isAuthRequired } from "./authSession";
import { fetchCoordinationBoard } from "./coordinationBoard";

afterEach(() => {
  clearAuthRequired();
  vi.unstubAllGlobals();
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
});
