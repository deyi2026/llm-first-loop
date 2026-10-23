import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { useRealtimeVoice } from "./useRealtimeVoice";

class Socket {
  static instances: Socket[] = [];
  binaryType = "blob";
  onopen: (() => void) | null = null;
  onclose: ((event: { code: number }) => void) | null = null;
  onmessage: ((event: { data: string | ArrayBuffer }) => void) | null = null;
  onerror = null;
  sent: (string | ArrayBuffer)[] = [];
  constructor() { Socket.instances.push(this); }
  send(data: string | ArrayBuffer) { this.sent.push(data); }
  close() { this.onclose?.({ code: 1000 }); }
}

function setup() {
  Socket.instances = [];
  const track = { stop: vi.fn() };
  const stream = { getTracks: () => [track] };
  const source = { connect: vi.fn(), disconnect: vi.fn() };
  const node = { port: { onmessage: null as ((event: { data: unknown }) => void) | null, close: vi.fn() }, connect: vi.fn(), disconnect: vi.fn() };
  const context = {
    audioWorklet: { addModule: vi.fn(async () => undefined) },
    createMediaStreamSource: vi.fn(() => source),
    destination: {}, resume: vi.fn(async () => undefined), close: vi.fn(async () => undefined),
    decodeAudioData: vi.fn(async () => ({})),
    createBufferSource: vi.fn(() => ({ connect: vi.fn(), start: vi.fn(), stop: vi.fn(), onended: null })),
  };
  vi.stubGlobal("WebSocket", Socket);
  vi.stubGlobal("AudioContext", function () { return context; });
  vi.stubGlobal("AudioWorkletNode", function () { return node; });
  const getUserMedia = vi.fn(async () => stream);
  Object.defineProperty(navigator, "mediaDevices", { configurable: true, value: { getUserMedia } });
  const fetcher = vi.fn(async (_url: unknown, init?: RequestInit) => ({
    ok: true,
    json: async () => init?.method === "POST" ? { media_session_id: "media-1", connection_epoch: 1 } : {},
  }));
  vi.stubGlobal("fetch", fetcher);
  return { track, source, node, context, getUserMedia, stream, fetcher };
}

afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); });

it("uses the browser graph, reaches ready, commits flushed audio, and delivers final through the existing chat callback", async () => {
  const deps = setup();
  const onFinal = vi.fn(async () => "真实回复");
  const hook = renderHook(() => useRealtimeVoice("session-1", onFinal));
  await act(async () => { await hook.result.current.enable(); });
  const socket = Socket.instances[0];
  act(() => socket.onopen?.());
  expect(hook.result.current.connectionState).toBe("ready");
  expect(socket.binaryType).toBe("arraybuffer");
  await act(async () => { hook.result.current.press(); });
  await waitFor(() => expect(deps.source.connect).toHaveBeenCalled());
  act(() => deps.node.port.onmessage?.({ data: { samples: new Float32Array(400), sampleRate: 16000 } }));
  act(() => hook.result.current.release());
  expect(socket.sent.filter((item) => item instanceof ArrayBuffer)).toHaveLength(2);
  expect(JSON.parse(socket.sent.at(-1) as string)).toMatchObject({ type: "input.commit", session_id: "session-1", media_session_id: "media-1" });
  const final = { version: 1, type: "input.final", event_id: "event-1", seq: 1, connection_epoch: 1, session_id: "session-1", media_session_id: "media-1", turn_id: "turn-1", text: "你好" };
  await act(async () => { socket.onmessage?.({ data: JSON.stringify(final) }); });
  expect(onFinal).toHaveBeenCalledWith("你好");
  expect(socket.sent.some((item) => typeof item === "string" && JSON.parse(item).type === "tts.request")).toBe(true);
  await act(async () => { socket.onmessage?.({ data: JSON.stringify(final) }); });
  expect(onFinal).toHaveBeenCalledTimes(1);
  hook.unmount();
  await waitFor(() => expect(deps.fetcher).toHaveBeenCalledWith("/api/v1/realtime/sessions/media-1", expect.objectContaining({ method: "DELETE" })));
  expect(deps.context.close).toHaveBeenCalled();
});

it("discards a permission result arriving after release and stops its tracks", async () => {
  const deps = setup();
  let grant!: (value: typeof deps.stream) => void;
  deps.getUserMedia.mockImplementation(() => new Promise((resolve) => { grant = resolve; }));
  const hook = renderHook(() => useRealtimeVoice("session-1"));
  await act(async () => { await hook.result.current.enable(); });
  act(() => Socket.instances[0].onopen?.());
  act(() => { hook.result.current.press(); hook.result.current.release(); });
  await act(async () => { grant(deps.stream); });
  expect(deps.track.stop).toHaveBeenCalled();
  expect(hook.result.current.micEnabled).toBe(false);
  expect(deps.source.connect).not.toHaveBeenCalled();
  hook.unmount();
});

it("closes the old media writer on a session switch and never sends its late final", async () => {
  const deps = setup(); const onFinal = vi.fn(async () => null);
  const hook = renderHook(({ sid }) => useRealtimeVoice(sid, onFinal), { initialProps: { sid: "session-1" } });
  await act(async () => { await hook.result.current.enable(); });
  const old = Socket.instances[0]; act(() => old.onopen?.());
  hook.rerender({ sid: "session-2" });
  expect(hook.result.current.enabled).toBe(false);
  expect(deps.fetcher).toHaveBeenCalledWith("/api/v1/realtime/sessions/media-1", expect.objectContaining({ method: "DELETE" }));
  act(() => old.onmessage?.({ data: JSON.stringify({ version: 1, type: "input.final", event_id: "late", seq: 2, connection_epoch: 1, session_id: "session-1", media_session_id: "media-1", turn_id: "late-turn", text: "旧输入" }) }));
  expect(onFinal).not.toHaveBeenCalled(); hook.unmount();
});
