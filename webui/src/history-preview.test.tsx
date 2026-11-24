import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { MessageItem } from "./components/conversation/MessageItem";
import { sessionStore } from "./core/stores";
import { fetchHistory, toChatMessage } from "./core/chat";
import { projectToolActivityMessages } from "./core/toolActivity";

const ref = { offset: 2, sha256: "a".repeat(64), bytes: 32000, revision: "r1" };
const preview = toChatMessage({ role: "user", content: "预览", history_preview: ref });

describe("bounded history preview", () => {
  afterEach(() => { cleanup(); vi.unstubAllGlobals(); sessionStore.setCurrentSession(""); });

  it("only reads exact original on explicit expansion and can collapse", async () => {
    sessionStore.setCurrentSession("s1");
    const fetchMock = vi.fn(async (url: RequestInfo | URL) => new Response(JSON.stringify(String(url).includes("/messages?") ? {
      messages: [{ role: "user", content: "完整原文" }], revision: "r1", verified_sha256: ref.sha256,
    } : {}), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    render(<MessageItem msg={preview} sessionId="s1" />);
    expect(screen.getByText("预览")).toBeTruthy();
    expect(fetchMock.mock.calls.filter(([url]) => String(url).includes("/messages?"))).toHaveLength(0);
    fireEvent.click(screen.getByText("展开完整原文"));
    await screen.findByText("完整原文");
    expect(fetchMock.mock.calls.filter(([url]) => String(url).includes("/messages?"))).toHaveLength(1);
    expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining(`limit=1&offset=2&snapshot_revision=r1&expected_sha256=${ref.sha256}`), expect.anything());
    fireEvent.click(screen.getByText("查看完整结构化原文（含工具参数、附件等）"));
    expect(screen.getByText(/"content": "完整原文"/)).toBeTruthy();
    fireEvent.click(screen.getByText("收起原文"));
    expect(screen.getByText("预览")).toBeTruthy();
  });

  it("does not display an unverified or stale original", async () => {
    sessionStore.setCurrentSession("s1");
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({
      messages: [{ role: "user", content: "wrong row" }], revision: "r1",
    }), { status: 200 })));
    render(<MessageItem msg={preview} sessionId="s1" />);
    fireEvent.click(screen.getByText("展开完整原文"));
    await screen.findByRole("alert");
    expect(screen.queryByText("wrong row")).toBeNull();
    expect(screen.getByText("预览")).toBeTruthy();
  });

  it("aborts an original read on unmount", async () => {
    sessionStore.setCurrentSession("s1");
    let signal: AbortSignal | null | undefined;
    vi.stubGlobal("fetch", vi.fn((url: RequestInfo | URL, options: RequestInit) => {
      if (!String(url).includes("/messages?")) return Promise.resolve(new Response("{}", { status: 200 }));
      signal = options.signal;
      return new Promise<Response>((_resolve, reject) => signal?.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError"))));
    }));
    const view = render(<MessageItem msg={preview} sessionId="s1" />);
    fireEvent.click(screen.getByText("展开完整原文"));
    await waitFor(() => expect(signal).toBeTruthy());
    view.unmount();
    expect(signal?.aborted).toBe(true);
  });

  it("keeps deferred tool rows visible and defaults history reads to compact", async () => {
    const tool = toChatMessage({ role: "tool", content: "tool preview", history_preview: ref });
    const rows = projectToolActivityMessages([{ role: "assistant", content: "", toolCalls: [{ id: "c", name: "tool", arguments: {} }] }, tool]);
    expect(rows.some(row => row.msg === tool)).toBe(true);
    const fetchMock = vi.fn(async () => new Response(JSON.stringify({ messages: [], has_more: false }), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    await fetchHistory("s1", 50, 0);
    expect(fetchMock).toHaveBeenCalledWith(expect.stringContaining("limit=50&offset=0&compact=true"), expect.anything());
  });
});
