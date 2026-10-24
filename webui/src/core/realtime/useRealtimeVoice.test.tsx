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
  closed = false;
  sent: (string | ArrayBuffer)[] = [];
  constructor() { Socket.instances.push(this); }
  send(data: string | ArrayBuffer) { this.sent.push(data); }
  close() { this.closed = true; this.onclose?.({ code: 1000 }); }
}

function setup() {
  Socket.instances = [];
  const track = { stop: vi.fn() };
  const stream = { getTracks: () => [track] };
  const source = { connect: vi.fn(), disconnect: vi.fn() };
  const audioSource = {
    buffer: null as unknown,
    connect: vi.fn(),
    start: vi.fn(),
    stop: vi.fn(),
    onended: null as null | (() => void),
  };
  const node = { port: { onmessage: null as ((event: { data: unknown }) => void) | null, close: vi.fn() }, connect: vi.fn(), disconnect: vi.fn() };
  const context = {
    state: "running",
    audioWorklet: { addModule: vi.fn(async () => undefined) },
    createMediaStreamSource: vi.fn(() => source),
    destination: {}, resume: vi.fn(async () => undefined), close: vi.fn(async () => undefined),
    decodeAudioData: vi.fn(async () => ({})),
    createBufferSource: vi.fn(() => audioSource),
  };
  context.resume.mockImplementation(async () => { context.state = "running"; });
  vi.stubGlobal("WebSocket", Socket);
  vi.stubGlobal("AudioContext", function () { return context; });
  vi.stubGlobal("AudioWorkletNode", function () { return node; });
  const getUserMedia = vi.fn(async () => stream);
  Object.defineProperty(navigator, "mediaDevices", { configurable: true, value: { getUserMedia } });
  const fetcher = vi.fn(async (_url: unknown, init?: RequestInit) => ({
    ok: true,
    status: init?.method === "POST" ? 201 : 200,
    json: async () => init?.method === "POST" ? { media_session_id: "media-1", connection_epoch: 1 } : {},
  }));
  vi.stubGlobal("fetch", fetcher);
  return { track, source, audioSource, node, context, getUserMedia, stream, fetcher };
}

afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); });

it("explains HTTP 401 as an expired login instead of an audio-provider failure", async () => {
  const deps = setup();
  deps.fetcher.mockResolvedValueOnce({ ok: false, status: 401, json: async () => ({}) });
  const hook = renderHook(() => useRealtimeVoice("session-1"));
  await act(async () => { expect(await hook.result.current.enable()).toBe(false); });
  expect(hook.result.current.error).toContain("HTTP 401");
  expect(hook.result.current.error).toContain("重新登录");
  expect(hook.result.current.enabled).toBe(true); // Always retain visible close/retry controls.
  expect(hook.result.current.connectionState).toBe("failed");
  expect(Socket.instances).toHaveLength(0);
  expect(deps.getUserMedia).not.toHaveBeenCalled();
  hook.unmount();
});

it("allows realtime voice to start from a brand-new chat with no chat session id", async () => {
  const deps = setup();
  const hook = renderHook(() => useRealtimeVoice(""));
  await act(async () => { expect(await hook.result.current.enable()).toBe(true); });
  const request = deps.fetcher.mock.calls.find(([url, init]) =>
    url === "/api/v1/realtime/sessions" && init?.method === "POST",
  );
  expect(request).toBeDefined();
  const body = JSON.parse(String(request?.[1]?.body)) as { session_id: string };
  expect(body.session_id).toMatch(/^voice-pending-/);
  expect(body.session_id).not.toBe("");
  expect(Socket.instances).toHaveLength(1);
  act(() => Socket.instances[0].onopen?.());
  await waitFor(() => expect(deps.getUserMedia).toHaveBeenCalledOnce());
  await waitFor(() => expect(hook.result.current.micEnabled).toBe(true));
  hook.unmount();
});

it("keeps voice connected when the first spoken turn creates its real chat session", async () => {
  const deps = setup();
  const hook = renderHook(({ sessionId }: { sessionId: string }) => useRealtimeVoice(sessionId), {
    initialProps: { sessionId: "" },
  });
  await act(async () => { expect(await hook.result.current.enable()).toBe(true); });
  const socket = Socket.instances[0];
  act(() => socket.onopen?.());
  await waitFor(() => expect(hook.result.current.micEnabled).toBe(true));
  hook.rerender({ sessionId: "created-by-first-voice-turn" });
  expect(hook.result.current.enabled).toBe(true);
  expect(hook.result.current.connectionState).toBe("ready");
  expect(hook.result.current.micEnabled).toBe(true);
  expect(socket.closed).toBe(false);
  expect(Socket.instances).toHaveLength(1);
  expect(deps.fetcher).not.toHaveBeenCalledWith(
    "/api/v1/realtime/sessions/media-1", expect.objectContaining({ method: "DELETE" }),
  );
  hook.unmount();
});

it("always releases the media writer when unmounted after chat-session promotion", async () => {
  const deps = setup();
  const hook = renderHook(({ sessionId }: { sessionId: string }) => useRealtimeVoice(sessionId), {
    initialProps: { sessionId: "" },
  });
  await act(async () => { expect(await hook.result.current.enable()).toBe(true); });
  const socket = Socket.instances[0];
  act(() => socket.onopen?.());
  await waitFor(() => expect(hook.result.current.micEnabled).toBe(true));
  hook.rerender({ sessionId: "created-by-first-voice-turn" });
  expect(socket.closed).toBe(false);
  hook.unmount();
  expect(socket.closed).toBe(true);
  expect(deps.context.close).toHaveBeenCalled();
  expect(deps.fetcher).toHaveBeenCalledWith(
    "/api/v1/realtime/sessions/media-1", expect.objectContaining({ method: "DELETE", keepalive: true }),
  );
});

it("shows the voice panel while connecting and lets close cancel an in-flight setup", async () => {
  const deps = setup();
  type FetchReply = Awaited<ReturnType<typeof deps.fetcher>>;
  let respond!: (value: FetchReply) => void;
  deps.fetcher.mockImplementationOnce(() => new Promise<FetchReply>((resolve) => { respond = resolve; }));
  const hook = renderHook(() => useRealtimeVoice("session-1"));
  let enabling!: Promise<boolean>;
  act(() => { enabling = hook.result.current.enable(); });
  expect(hook.result.current.enabled).toBe(true);
  expect(hook.result.current.connectionState).toBe("opening");
  await act(async () => { await Promise.resolve(); }); // Browser audio activation settles first.
  act(() => hook.result.current.disable());
  await act(async () => {
    respond({ ok: true, status: 201, json: async () => ({ media_session_id: "media-1", connection_epoch: 1 }) });
    expect(await enabling).toBe(false);
  });
  expect(Socket.instances).toHaveLength(0);
  expect(hook.result.current.enabled).toBe(false);
  expect(deps.fetcher).toHaveBeenCalledWith(
    "/api/v1/realtime/sessions/media-1", expect.objectContaining({ method: "DELETE" }),
  );
  hook.unmount();
});

it("unlocks mobile audio on the original click before the network request settles", async () => {
  const deps = setup();
  type FetchReply = Awaited<ReturnType<typeof deps.fetcher>>;
  let respond!: (value: FetchReply) => void;
  deps.fetcher.mockImplementationOnce(() => new Promise<FetchReply>((resolve) => { respond = resolve; }));
  const hook = renderHook(() => useRealtimeVoice("session-1"));
  let enabling!: Promise<boolean>;
  act(() => { enabling = hook.result.current.enable(); });
  expect(deps.context.resume).toHaveBeenCalledOnce();
  await act(async () => { await Promise.resolve(); });
  await act(async () => {
    respond({ ok: true, status: 201, json: async () => ({ media_session_id: "media-1", connection_epoch: 1 }) });
    expect(await enabling).toBe(true);
  });
  hook.unmount();
});

it("closing during delayed mobile audio activation immediately releases the context", async () => {
  const deps = setup();
  let resume!: () => void;
  deps.context.resume.mockImplementationOnce(
    () => new Promise<undefined>((resolve) => { resume = () => resolve(undefined); }),
  );
  const hook = renderHook(() => useRealtimeVoice("session-1"));
  let enabling!: Promise<boolean>;
  act(() => { enabling = hook.result.current.enable(); });
  expect(hook.result.current.enabled).toBe(true);
  act(() => hook.result.current.disable());
  expect(deps.context.close).toHaveBeenCalledOnce();
  await act(async () => { resume(); expect(await enabling).toBe(false); });
  expect(deps.fetcher).not.toHaveBeenCalledWith(
    "/api/v1/realtime/sessions", expect.objectContaining({ method: "POST" }),
  );
  hook.unmount();
});

it("reports microphone permission pending and records until explicitly released", async () => {
  const deps = setup();
  let allow!: (stream: typeof deps.stream) => void;
  deps.getUserMedia.mockImplementation(() => new Promise((resolve) => { allow = resolve; }));
  const hook = renderHook(() => useRealtimeVoice("session-1"));
  await act(async () => { await hook.result.current.enable(); });
  act(() => Socket.instances[0].onopen?.());
  act(() => hook.result.current.press());
  expect(hook.result.current.micStarting).toBe(true);
  expect(hook.result.current.micEnabled).toBe(false);
  await act(async () => { allow(deps.stream); });
  await waitFor(() => expect(hook.result.current.micEnabled).toBe(true));
  expect(hook.result.current.micStarting).toBe(false);
  expect(deps.track.stop).not.toHaveBeenCalled();
  act(() => hook.result.current.release());
  expect(hook.result.current.micEnabled).toBe(false);
  expect(deps.track.stop).toHaveBeenCalledOnce();
  hook.unmount();
});

it("explains denied microphone permission without falsely showing recording", async () => {
  const deps = setup();
  deps.getUserMedia.mockRejectedValueOnce(new Error("NotAllowedError"));
  const hook = renderHook(() => useRealtimeVoice("session-1"));
  await act(async () => { await hook.result.current.enable(); });
  act(() => Socket.instances[0].onopen?.());
  await act(async () => { hook.result.current.press(); });
  await waitFor(() => expect(hook.result.current.error).toContain("麦克风"));
  expect(hook.result.current.micStarting).toBe(false);
  expect(hook.result.current.micEnabled).toBe(false);
  expect(hook.result.current.enabled).toBe(true);
  hook.unmount();
});

it("starts listening after the first voice click, commits audio, and delivers final through the existing chat callback", async () => {
  const deps = setup();
  const onFinal = vi.fn(async () => "真实回复");
  const hook = renderHook(() => useRealtimeVoice("session-1", onFinal));
  await act(async () => { await hook.result.current.enable(); });
  const socket = Socket.instances[0];
  act(() => socket.onopen?.());
  expect(hook.result.current.connectionState).toBe("ready");
  expect(hook.result.current.micStarting).toBe(true);
  expect(socket.binaryType).toBe("arraybuffer");
  await waitFor(() => expect(deps.getUserMedia).toHaveBeenCalledOnce());
  await waitFor(() => expect(deps.source.connect).toHaveBeenCalled());
  expect(hook.result.current.micEnabled).toBe(true);
  act(() => deps.node.port.onmessage?.({ data: { samples: new Float32Array(400), sampleRate: 16000 } }));
  act(() => hook.result.current.release());
  expect(socket.sent.filter((item) => item instanceof ArrayBuffer)).toHaveLength(2);
  expect(JSON.parse(socket.sent.at(-1) as string)).toMatchObject({ type: "input.commit", session_id: "session-1", media_session_id: "media-1" });
  const final = { version: 1, type: "input.final", event_id: "event-1", seq: 1, connection_epoch: 1, session_id: "session-1", media_session_id: "media-1", turn_id: "turn-1", text: "你好" };
  await act(async () => { socket.onmessage?.({ data: JSON.stringify(final) }); });
  expect(onFinal).toHaveBeenCalledWith("你好");
  expect(socket.sent.some((item) => typeof item === "string" && JSON.parse(item).type === "tts.request")).toBe(true);
  const resumesBeforePlayback = deps.context.resume.mock.calls.length;
  (deps.context as { state: string }).state = "suspended";
  const playbackEvent = {
    version: 1, type: "audio.playback", event_id: "playback-event", seq: 2,
    connection_epoch: 1, session_id: "session-1", media_session_id: "media-1", response_id: "turn-1",
  };
  act(() => socket.onmessage?.({ data: JSON.stringify(playbackEvent) }));
  await act(async () => {
    socket.onmessage?.({ data: new Uint8Array([82, 73, 70, 70, 1, 2, 3, 4]).buffer });
    await waitFor(() => expect(deps.audioSource.start).toHaveBeenCalledOnce());
  });
  expect(deps.context.resume).toHaveBeenCalledTimes(resumesBeforePlayback + 1);
  expect(deps.context.decodeAudioData).toHaveBeenCalledOnce();
  expect(hook.result.current.playbackState).toBe("playing");
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
  const controls = Socket.instances[0].sent.filter((value): value is string => typeof value === "string").map((value) => JSON.parse(value) as { type: string });
  expect(controls.some((event) => event.type === "input.clear")).toBe(true);
  expect(controls.some((event) => event.type === "input.commit")).toBe(false);
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

it("surfaces TTS synthesis failure and allows retrying the last spoken answer", async () => {
  setup();
  const onFinal = vi.fn(async () => "可朗读的回答");
  const hook = renderHook(() => useRealtimeVoice("session-1", onFinal));
  await act(async () => { await hook.result.current.enable(); });
  const socket = Socket.instances[0];
  act(() => socket.onopen?.());
  await waitFor(() => expect(hook.result.current.micEnabled).toBe(true));
  act(() => hook.result.current.release());
  const final = {
    version: 1, type: "input.final", event_id: "input-final", seq: 1,
    connection_epoch: 1, session_id: "session-1", media_session_id: "media-1",
    turn_id: "turn-tts-fail", text: "请回答",
  };
  await act(async () => { socket.onmessage?.({ data: JSON.stringify(final) }); });
  await waitFor(() => expect(socket.sent.some((value) => typeof value === "string" && JSON.parse(value).type === "tts.request")).toBe(true));
  const unavailable = {
    version: 1, type: "audio.playback_unavailable", event_id: "tts-failed", seq: 2,
    connection_epoch: 1, session_id: "session-1", media_session_id: "media-1", response_id: "turn-tts-fail",
  };
  act(() => socket.onmessage?.({ data: JSON.stringify(unavailable) }));
  expect(hook.result.current.playbackState).toBe("failed");
  expect(hook.result.current.error).toContain("本地 TTS 合成失败");
  act(() => hook.result.current.retryPlayback());
  expect(socket.sent.filter((value) => typeof value === "string" && JSON.parse(value).type === "tts.request")).toHaveLength(2);
  expect(hook.result.current.playbackState).toBe("synthesizing");
  hook.unmount();
});
