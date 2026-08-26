import { afterEach, describe, expect, it, vi } from "vitest";
import { api } from "./core/api";
import { fetchHistory, fetchModels } from "./core/chat";

describe("core fetch fail-open", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("generic api converts network rejection to status=0", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => { throw new TypeError("offline"); }));
    await expect(api<{ value: string }>("/api/v1/test")).resolves.toEqual({ status: 0, data: {} });
  });

  it("fetchModels returns empty catalog when fetch rejects", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => { throw new TypeError("offline"); }));
    await expect(fetchModels()).resolves.toEqual({ models: [], current: null });
  });

  it("fetchHistory validates a 200 response shape before consumers map it", async () => {
    vi.stubGlobal("fetch", vi.fn(async () =>
      new Response(JSON.stringify({ sessions: [{ session_id: "wrong-shape" }] }), { status: 200 })
    ));
    await expect(fetchHistory("s1", 100, 0)).resolves.toEqual({ messages: [], has_more: false });
  });
});
