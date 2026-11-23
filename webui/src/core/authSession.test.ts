import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "./api";
import { fetchHistory } from "./chat";
import { clearAuthRequired, isAuthRequired, reportUnauthorized } from "./authSession";

beforeEach(() => clearAuthRequired());
afterEach(() => {
  clearAuthRequired();
  vi.unstubAllGlobals();
});

describe("browser authentication recovery", () => {
  it("HTTP 401 pauses passive API polling without suppressing explicit writes or auth status", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ detail: "Unauthorized" }), { status: 401 }))
      .mockResolvedValue(new Response(JSON.stringify({ authenticated: true }), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    const failed = await api("/api/v1/sessions");
    expect(failed.status).toBe(401);
    expect(isAuthRequired()).toBe(true);
    expect((await api("/api/v1/sessions")).status).toBe(401);
    expect(fetchMock).toHaveBeenCalledTimes(1); // no repeated GET storm
    expect((await api("/auth/status")).status).toBe(200);
    expect((await api("/api/v1/chat/queue", { method: "POST" })).status).toBe(200);
    expect(fetchMock).toHaveBeenCalledTimes(3);
  });

  it("history HTTP 401 gives a login action instead of a misleading timeout, and stops retry reads", async () => {
    const fetchMock = vi.fn(async () => new Response("{}", { status: 401 }));
    vi.stubGlobal("fetch", fetchMock);
    const first = await fetchHistory("s1", 100, 0);
    expect(first.ok).toBe(false);
    expect(first.error).toContain("重新登录");
    expect(isAuthRequired()).toBe(true);
    const second = await fetchHistory("s1", 100, 0);
    expect(second.error).toContain("重新登录");
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("HTTP 403 is a permission denial, not a browser session expiry", () => {
    reportUnauthorized(403);
    expect(isAuthRequired()).toBe(false);
  });
});
