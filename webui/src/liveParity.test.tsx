import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { DictationButton } from "./components/conversation/DictationButton";
import { SessionHeaderActions } from "./components/layout/SessionHeaderActions";
import { refreshSessionsAndCurrent } from "./core/events";
import { sessionStore } from "./core/stores";
import {
  buildSessionShareUrl,
  readSessionIdFromLocation,
  syncSessionIdInLocation,
} from "./core/sessionUrl";

const session = {
  session_id: "s-test",
  title: "Parity test",
  created_at: "2026-09-09T00:00:00Z",
  updated_at: "2026-09-09T00:00:00Z",
  message_count: 1,
  status: "active",
  last_message_preview: "hello",
  pinned: false,
  channel: "web",
};

function resetSessionState(): void {
  sessionStore.setSessions([]);
  sessionStore.setCurrentSession("");
  sessionStore.setNewSessionPending(false);
}

describe("live parity session links", () => {
  beforeEach(() => {
    resetSessionState();
    history.replaceState({}, "", "/?foo=1");
  });

  afterEach(() => {
    cleanup();
    resetSessionState();
    history.replaceState({}, "", "/");
    vi.unstubAllGlobals();
  });

  it("round-trips an explicit session id without dropping other URL state", () => {
    const shareUrl = buildSessionShareUrl("abc", "https://example.test/chat?foo=1#tail");
    expect(shareUrl).toContain("foo=1");
    expect(shareUrl).toContain("session=abc");
    expect(shareUrl).toContain("#tail");

    syncSessionIdInLocation("abc");
    expect(readSessionIdFromLocation()).toBe("abc");
    expect(location.search).toContain("foo=1");
    syncSessionIdInLocation(null);
    expect(readSessionIdFromLocation()).toBeNull();
    expect(location.search).toBe("?foo=1");
  });

  it("uses a valid deep link before shared-current fallback", async () => {
    history.replaceState({}, "", "/?session=s-test");
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      if (String(input) === "/api/v1/sessions") {
        return new Response(JSON.stringify({ sessions: [session], count: 1 }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      }
      throw new Error(`unexpected fetch: ${String(input)}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    await refreshSessionsAndCurrent();

    expect(sessionStore.getState().currentSessionId).toBe("s-test");
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});

describe("live parity header actions", () => {
  beforeEach(() => {
    resetSessionState();
    sessionStore.setSessions([session]);
    sessionStore.setCurrentSession("s-test");
    history.replaceState({}, "", "/");
  });

  afterEach(() => {
    cleanup();
    resetSessionState();
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it("copies a deployment-local deep link and opens the real files view action", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: { writeText },
    });
    const onShowFiles = vi.fn();
    render(<SessionHeaderActions onShowFiles={onShowFiles} />);

    fireEvent.click(screen.getByRole("button", { name: "复制会话链接" }));
    await waitFor(() => expect(writeText).toHaveBeenCalledTimes(1));
    expect(String(writeText.mock.calls[0][0])).toContain("session=s-test");

    fireEvent.click(screen.getByRole("button", { name: "更多" }));
    fireEvent.click(screen.getByRole("menuitem", { name: /查看聊天中的文件/ }));
    expect(onShowFiles).toHaveBeenCalledTimes(1);
  });

  it("requires a second click before issuing the destructive delete", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.includes("/api/v1/sessions/s-test") && init?.method === "DELETE") {
        return new Response(JSON.stringify({ status: "ok" }), { status: 200 });
      }
      if (url === "/api/v1/sessions") {
        return new Response(JSON.stringify({ sessions: [], count: 0 }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      }
      if (url === "/api/v1/session/current") {
        return new Response(JSON.stringify({ current: null }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      }
      throw new Error(`unexpected fetch: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<SessionHeaderActions />);

    fireEvent.click(screen.getByRole("button", { name: "更多" }));
    fireEvent.click(screen.getByRole("menuitem", { name: /删除/ }));
    expect(fetchMock).not.toHaveBeenCalled();
    expect(screen.getByRole("menuitem", { name: /再次点击确认删除/ })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("menuitem", { name: /再次点击确认删除/ }));
    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        "/api/v1/sessions/s-test?confirm=true",
        { method: "DELETE" }
      )
    );
  });
});

describe("browser-native dictation", () => {
  afterEach(() => {
    cleanup();
    Reflect.deleteProperty(window, "webkitSpeechRecognition");
  });

  it("exposes dictation only through a real SpeechRecognition implementation", () => {
    class FakeRecognition {
      static latest: FakeRecognition | null = null;
      lang = "";
      interimResults = true;
      continuous = true;
      start = vi.fn();
      stop = vi.fn();
      abort = vi.fn();
      onresult: ((event: any) => void) | null = null;
      onerror: ((event: any) => void) | null = null;
      onend: (() => void) | null = null;

      constructor() {
        FakeRecognition.latest = this;
      }
    }
    Object.defineProperty(window, "webkitSpeechRecognition", {
      configurable: true,
      value: FakeRecognition,
    });
    const onTranscript = vi.fn();
    render(<DictationButton onTranscript={onTranscript} />);

    fireEvent.click(screen.getByRole("button", { name: "开始浏览器听写" }));
    const recognition = FakeRecognition.latest;
    expect(recognition).not.toBeNull();
    expect(recognition?.start).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("button", { name: "停止浏览器听写" })).toBeInTheDocument();

    act(() => {
      recognition?.onresult?.({
        results: Object.assign([{ isFinal: true, 0: { transcript: "继续对齐" }, length: 1 }], { length: 1 }),
      });
    });
    expect(onTranscript).toHaveBeenCalledWith("继续对齐");
  });
});
