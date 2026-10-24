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
  modality: ModalityMode;
  chainLabel: string;
  transcript: string;
  error: string;
  enable: () => Promise<boolean>;
  disable: () => void;
  press: () => void;
  release: () => void;
  interrupt: () => void;
}
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

export function useRealtimeVoice(
  sessionId: string,
  onFinal?: (text: string) => Promise<string | null>,
): RealtimeVoiceWiring {
  const [enabled, setEnabled] = useState(false);
  const [connectionState, setConnectionState] = useState<ConnectionState>("closed");
  const [micEnabled, setMicEnabled] = useState(false);
  const [micStarting, setMicStarting] = useState(false);
  const [transcript, setTranscript] = useState("");
  const [error, setError] = useState("");
  const activeRef = useRef<ActiveVoice | null>(null);
  const pendingContext = useRef<AudioContext | null>(null);
  const generation = useRef(0);
  const pressEpoch = useRef(0);
  const autoStartMic = useRef<number | null>(null);
  const enabling = useRef(false);
  const finalRef = useRef(onFinal);
  finalRef.current = onFinal;
  const caps = typeof navigator === "undefined" ? null : navigator.mediaDevices;
  const modality = resolveModality({ mic: Boolean(caps?.getUserMedia), screenShare: Boolean(caps?.getDisplayMedia) });

  const dispose = useCallback(() => {
    generation.current++;
    pressEpoch.current++;
    autoStartMic.current = null;
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
    setEnabled(false); setMicEnabled(false); setMicStarting(false);
    setConnectionState("closed"); setError(""); setTranscript("");
  }, [dispose]);
  useEffect(() => {
    setEnabled(false); setMicEnabled(false); setMicStarting(false);
    setConnectionState("closed"); setTranscript(""); setError("");
    return dispose;
  }, [sessionId, dispose]);

  const press = useCallback(() => {
    const active = activeRef.current;
    if (!active || active.client.connectionState !== "ready" || active.controller.pressedDown) return;
    const epoch = ++pressEpoch.current;
    active.controller.interrupt();
    setTranscript(""); setError(""); setMicStarting(true);
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
    if (!sessionId) {
      setConnectionState("failed"); setError("请先选择会话或发送一条文字消息建立会话");
      return false;
    }
    if (!navigator.mediaDevices?.getUserMedia) {
      setConnectionState("failed");
      setError("此浏览器无法使用麦克风；手机请使用 HTTPS 站点，并允许麦克风权限");
      return false;
    }
    enabling.current = true;
    const owner = ++generation.current;
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
        body: JSON.stringify({ session_id: sessionId }),
      });
      if (response.status === 401) {
        throw new Error("语音连接失败（HTTP 401）：登录状态已失效，请重新登录后重试");
      }
      if (!response.ok) throw new Error(`语音连接失败（HTTP ${response.status}）`);
      const body = await response.json() as { media_session_id: string; connection_epoch: number };
      mediaId = body.media_session_id;
      if (owner !== generation.current) { closeWriter(mediaId); return false; }
      const queue = new PlaybackQueue(() => body.connection_epoch);
      const playback = new PlaybackOutput({ playback: queue, audioContext: context as unknown as AudioContextLike });
      const scheme = window.location.protocol === "https:" ? "wss" : "ws";
      const client = new MediaSessionClient({
        url: `${scheme}://${window.location.host}/api/v1/realtime/sessions/${encodeURIComponent(mediaId)}/events`,
        sessionId, mediaSessionId: mediaId, playback: queue,
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
        const text = typeof event.text === "string" ? event.text : "";
        if (event.type === "input.delta") { setTranscript((old) => old + text); return; }
        if (event.type === "input.streaming_unavailable") { setError("增量字幕不可用，松开后仍会生成终稿"); return; }
        if (event.type !== "input.final" || !text.trim() || !event.turn_id) return;
        const key = `${event.media_session_id}:${event.connection_epoch}:${event.turn_id}`;
        if (seen.has(key)) return;
        seen.add(key); setTranscript(text);
        if (submitting) { setError("上一条语音仍在处理，请使用文字输入"); return; }
        submitting = true;
        void (async () => {
          try {
            const answer = await finalRef.current?.(text);
            if (owner === generation.current && answer) client.sendControl("tts.request", { text: answer, response_id: event.turn_id });
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
  return { enabled, connectionState, micEnabled, micStarting, modality, chainLabel: chainDisclosure({ cascade: true }).label, transcript, error, enable, disable, press, release, interrupt };
}
