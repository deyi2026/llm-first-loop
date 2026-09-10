import { afterEach, describe, expect, it, vi } from "vitest";
import { enqueueQueueMessage } from "./core/chat";

describe("human turn queue frozen request facts", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("freezes reasoning_mode together with model and effort", async () => {
    const fetchMock = vi.fn(async (_url: string, _init?: RequestInit) =>
      new Response(JSON.stringify({ queue_id: "q1", position: 1 }), { status: 202 })
    );
    vi.stubGlobal("fetch", fetchMock);

    const result = await enqueueQueueMessage(
      "s1",
      "queued",
      [{ ref: "attachment://v1/a" }],
      "glm/glm-5.3",
      "high",
      "off"
    );
    expect(result.ok).toBe(true);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const init = fetchMock.mock.calls[0][1] as RequestInit;
    expect(JSON.parse(String(init.body))).toEqual({
      session_id: "s1",
      message: "queued",
      attachments: [{ ref: "attachment://v1/a" }],
      model: "glm/glm-5.3",
      reasoning_effort: "high",
      reasoning_mode: "off",
    });
  });
});
