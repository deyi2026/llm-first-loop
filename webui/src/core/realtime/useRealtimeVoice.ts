import { useCallback, useEffect, useRef, useState } from "react";
import { MediaSessionClient, type ConnectionState, type SocketLike } from "./mediaSessionClient";
import { MicCapture, type MediaDevicesLike } from "./micCapture";
import { createBrowserCapturePort } from "./browserCapture";
import { PlaybackOutput, type AudioContextLike } from "./audioPlayback";
import { CapturePipeline } from "./capturePipeline";
import { PlaybackQueue } from "./playbackQueue";
import { RealtimeSessionController } from "./sessionController";
import { chainDisclosure, resolveModality, type ModalityMode } from "./modality";

export interface RealtimeVoiceWiring {
  enabled: boolean;
  connectionState: ConnectionState;
  micEnabled: boolean;
  micStarting: boolean;
  playbackState: PlaybackState;
  modality: ModalityMode;
  chainLabel: string;
  transcript: string;
  error: string;
  enable: () => Promise<boolean>;
  disable: () => void;
  press: () => void;
  release: () => void;
  interrupt: () => void;
  retryPlayback: () => void;
}
export type PlaybackState = "idle" | "synthesizing" | "playing" | "failed";
interface ActiveVoice {
  controller: RealtimeSessionController;
  client: MediaSessionClient;
  context: AudioContext;
  mediaId: string;
  generation: number;
}
function closeWriter(mediaId: string): void {
  void fetch(`/api/v1/realtime/sessions/${encodeURIComponent(mediaId)}`, { method: "DELETE", keepalive: true }).catch(() => undefined);
}

function newPendingVoiceScopeId(): string {
  const random = globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random().toString(16).slice(2)}`;
  return `voice-pending-${random}`;
}

export function useRealtimeVoice(
  sessionId: string,
  onFinal?: (text: string) => Promise<string | null>,
): RealtimeVoiceWiring {
  const [enabled, setEnabled] = useState(false);
  const [connectionState, setConnectionState] = useState<ConnectionState>("closed");
  const [micEnabled, setMicEnabled] = useState(false);
  const [micStarting, setMicStarting] = useState(false);
  const [playbackState, setPlaybackState] = useState<PlaybackState>("idle");
  const [transcript, setTranscript] = useState("");
  const [error, setError] = useState("");
  const activeRef = useRef<ActiveVoice | null>(null);
  const pendingContext = useRef<AudioContext | null>(null);
  // A new chat has no server session ID until the first human turn. Realtime
  // media still needs an isolated scope, so use a unique temporary scope and
  // promote to the real chat session without tearing down the live voice turn.
  const mediaScopeId = useRef(sessionId || newPendingVoiceScopeId());
  const previousSessionId = useRef(sessionId);
  const generation = useRef(0);
  const pressEpoch = useRef(0);
  const autoStartMic = useRef<number | null>(null);
  const lastTtsRequest = useRef<{ text: string; response_id: string } | null>(null);
  const enabling = useRef(false);
  const finalRef = useRef(onFinal);
  finalRef.current = onFinal;
  const caps = typeof navigator === "undefined" ? null : navigator.mediaDevices;
  const modality = resolveModality({ mic: Boolean(caps?.getUserMedia), screenShare: Boolean(caps?.getDisplayMedia) });

  const dispose = useCallback(() => {
    generation.current++;
    pressEpoch.current++;
    autoStartMic.current = null;
    lastTtsRequest.current = null;
    enabling.current = false;
    const active = activeRef.current;
    activeRef.current = null;
    const pending = pendingContext.current;
    pendingContext.current = null;
    if (pending) void pending.close();
    if (active) {
      active.controller.close();
      void active.context.close();
      closeWriter(active.mediaId);
    }
  }, []);
  const disable = useCallback(() => {
    dispose();
    mediaScopeId.current = sessionId || newPendingVoiceScopeId();
    setEnabled(false); setMicEnabled(false); setMicStarting(false);
    setPlaybackState("idle");
    setConnectionState("closed"); setError(""); setTranscript("");
  }, [dispose, sessionId]);
  useEffect(() => {
    const previous = previousSessionId.current;
    previousSessionId.current = sessionId;
    if (!previous && sessionId && activeRef.current) {
      // The first spoken turn created its real chat session. Keep this voice
      // connection alive so the answer can still be spoken back through TTS.
      return;
    }
    if (previous && previous !== sessionId) dispose();
    mediaScopeId.current = sessionId || newPendingVoiceScopeId();
    setEnabled(false); setMicEnabled(false); setMicStarting(false);
    setPlaybackState("idle");
    setConnectionState("closed"); setTranscript(""); setError("");
  }, [sessionId, dispose]);
  // One unconditional owner cleanup handles real unmounts, including after
  // an empty-chat -> real-session promotion. The promotion effect above only
  // suppresses the *session-change* disposal, never component-unmount cleanup.
  useEffect(() => () => dispose(), [dispose]);

  const press = useCallback(() => {
    const active = activeRef.current;
    if (!active || active.client.connectionState !== "ready" || active.controller.pressedDown) return;
    const epoch = ++pressEpoch.current;
    active.controller.interrupt();
    setTranscript(""); setError(""); setMicStarting(true); setPlaybackState("idle");
    void active.controller.press().then((started) => {
      if (activeRef.current === active && pressEpoch.current === epoch) {
        setMicStarting(false);
        setMicEnabled(started);
        if (!started) setError("无法启动麦克风，请检查浏览器权限或 HTTPS 安全连接");
      }
    });
  }, []);

  const enable = useCallback(async (): Promise<boolean> => {
    if (activeRef.current?.client.connectionState === "failed") {
      dispose();
      setMicEnabled(false);
      setMicStarting(false);
    } else if (activeRef.current) return true;
    if (enabling.current) return false;
    // Show an always-dismissable status surface before awaiting REST or browser audio.
    setEnabled(true); setConnectionState("opening"); setError(""); setTranscript("");
    if (!navigator.mediaDevices?.getUserMedia) {
      setConnectionState("failed");
      setError("此浏览器无法使用麦克风；手机请使用 HTTPS 站点，并允许麦克风权限");
      return false;
    }
    enabling.current = true;
    const owner = ++generation.current;
    const scopeId = sessionId || mediaScopeId.current || newPendingVoiceScopeId();
    mediaScopeId.current = scopeId;
    autoStartMic.current = owner;
    setMicStarting(false);
    let mediaId: string | null = null;
    let context: AudioContext | null = null;
    try {
      // Safari/iOS needs AudioContext.resume() to begin on the actual button
      // gesture. Resuming after an awaited REST call can silently stall audio.
      context = new AudioContext();
      pendingContext.current = context;
      await context.resume();
      if (owner !== generation.current) return false;
      const response = await fetch("/api/v1/realtime/sessions", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: scopeId }),
      });
      if (response.status === 401) {
        throw new Error("语音连接失败（HTTP 401）：登录状态已失效，请重新登录后重试");
      }
      if (!response.ok) throw new Error(`语音连接失败（HTTP ${response.status}）`);
      const body = await response.json() as { media_session_id: string; connection_epoch: number };
      mediaId = body.media_session_id;
      if (owner !== generation.current) { closeWriter(mediaId); return false; }
      const queue = new PlaybackQueue(() => body.connection_epoch);
      const playback = new PlaybackOutput({
        playback: queue,
        audioContext: context as unknown as AudioContextLike,
        callbacks: {
          onPlaybackStart: () => {
            if (owner === generation.current) setPlaybackState("playing");
          },
          onPlaybackEnd: () => {
            if (owner === generation.current) setPlaybackState("idle");
          },
          onPlaybackError: () => {
            if (owner !== generation.current) return;
            setPlaybackState("failed");
            setError("文字回复已生成，但浏览器无法播放语音。请检查设备音量后重试语音回复。");
          },
        },
      });
      const scheme = window.location.protocol === "https:" ? "wss" : "ws";
      const client = new MediaSessionClient({
        url: `${scheme}://${window.location.host}/api/v1/realtime/sessions/${encodeURIComponent(mediaId)}/events`,
        sessionId: scopeId, mediaSessionId: mediaId, playback: queue,
        // A disconnected voice segment is never automatically replayed.
        backoffMs: [],
        createSocket: (target) => {
          const socket = new WebSocket(target); socket.binaryType = "arraybuffer";
          return socket as unknown as SocketLike;
        },
        onStateChange: (state) => {
          if (owner !== generation.current) return;
          setConnectionState(state);
          if (state === "ready" && autoStartMic.current === owner) {
            // The user's "实时语音" click opts into recording. Connect first,
            // then begin capture automatically so mobile needs only one tap.
            autoStartMic.current = null;
            press();
          }
          if (state === "failed") {
            if (autoStartMic.current === owner) autoStartMic.current = null;
            setError("语音连接已中断，请关闭后重试");
            activeRef.current?.controller.cancel();
            pressEpoch.current++;
            setMicEnabled(false); setMicStarting(false);
          }
        },
        onAudio: () => { void playback.playNext(); },
      });
      const capture = new MicCapture({
        mediaDevices: navigator.mediaDevices as unknown as MediaDevicesLike,
        pipeline: new CapturePipeline({}),
        onFrame: (frame) => { client.sendAudioFrame(frame); },
        createPort: createBrowserCapturePort,
      });
      const controller = new RealtimeSessionController({
        client, capture, playback, onCommit: () => { client.sendControl("input.commit"); },
        onCancel: () => { client.sendControl("input.clear"); },
      });
      const seen = new Set<string>();
      let submitting = false;
      client.onEvent((event) => {
        if (owner !== generation.current) return;
        if (event.type === "audio.playback_unavailable") {
          setPlaybackState("failed");
          setError("文字回复已生成，但本地 TTS 合成失败。请确认本地语音服务正常后重试。");
          return;
        }
        if (event.type === "audio.playback") {
          setPlaybackState("synthesizing");
          return;
        }
        const text = typeof event.text === "string" ? event.text : "";
        if (event.type === "input.delta") { setTranscript((old) => old + text); return; }
        if (event.type === "input.streaming_unavailable") { setError("增量字幕不可用，松开后仍会生成终稿"); return; }
        if (event.type !== "input.final" || !text.trim() || !event.turn_id) return;
        const responseId = event.turn_id;
        const key = `${event.media_session_id}:${event.connection_epoch}:${responseId}`;
        if (seen.has(key)) return;
        seen.add(key); setTranscript(text);
        if (submitting) { setError("上一条语音仍在处理，请使用文字输入"); return; }
        submitting = true;
        void (async () => {
          try {
            const answer = await finalRef.current?.(text);
            if (owner !== generation.current) return;
            if (!answer?.trim()) {
              setPlaybackState("failed");
              setError("语音文字已发送，但模型没有返回可朗读的文字内容。");
              return;
            }
            const request = { text: answer, response_id: responseId };
            lastTtsRequest.current = request;
            if (!client.sendControl("tts.request", request)) {
              setPlaybackState("failed");
              setError("文字回复已生成，但语音通道已断开，语音回复未发送。请重新连接语音后再试。");
              return;
            }
            setPlaybackState("synthesizing");
          } catch { if (owner === generation.current) setError("语音发送失败，识别文字已保留"); }
          finally { submitting = false; }
        })();
      });
      activeRef.current = { controller, client, context, mediaId, generation: owner };
      client.connect(body.connection_epoch);
      pendingContext.current = null;
      setError(""); return true;
    } catch (failure) {
      if (pendingContext.current === context) {
        pendingContext.current = null;
        if (context) void context.close();
      }
      if (activeRef.current?.generation === owner) {
        activeRef.current.controller.close();
        activeRef.current = null;
      }
      if (mediaId) closeWriter(mediaId);
      if (owner === generation.current) {
        if (autoStartMic.current === owner) autoStartMic.current = null;
        setConnectionState("failed"); setError(failure instanceof Error ? failure.message : "语音连接失败");
      }
      return false;
    } finally { if (owner === generation.current) enabling.current = false; }
  }, [dispose, press, sessionId]);
  const release = useCallback(() => {
    pressEpoch.current++;
    const controller = activeRef.current?.controller;
    // A tap while the permission prompt is pending is cancellation, not a
    // zero-length voice turn. Commit only audio that was actually recording.
    if (controller?.micEnabled) controller.release();
    else controller?.cancel();
    setMicStarting(false); setMicEnabled(false);
  }, []);
  const interrupt = useCallback(() => { activeRef.current?.controller.interrupt(); }, []);
  const retryPlayback = useCallback(() => {
    const active = activeRef.current;
    const request = lastTtsRequest.current;
    if (!active || !request || active.client.connectionState !== "ready") {
      setPlaybackState("failed");
      setError("语音通道未连接，无法重试语音回复。请重新连接后再试。");
      return;
    }
    setError("");
    setPlaybackState("synthesizing");
    if (!active.client.sendControl("tts.request", request)) {
      setPlaybackState("failed");
      setError("语音回复请求未发送，连接可能已断开。请重新连接后再试。");
    }
  }, []);
  return { enabled, connectionState, micEnabled, micStarting, playbackState, modality, chainLabel: chainDisclosure({ cascade: true }).label, transcript, error, enable, disable, press, release, interrupt, retryPlayback };
}
