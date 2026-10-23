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
  const [transcript, setTranscript] = useState("");
  const [error, setError] = useState("");
  const activeRef = useRef<ActiveVoice | null>(null);
  const generation = useRef(0);
  const enabling = useRef(false);
  const finalRef = useRef(onFinal);
  finalRef.current = onFinal;
  const caps = typeof navigator === "undefined" ? null : navigator.mediaDevices;
  const modality = resolveModality({ mic: Boolean(caps?.getUserMedia), screenShare: Boolean(caps?.getDisplayMedia) });

  const dispose = useCallback(() => {
    generation.current++;
    enabling.current = false;
    const active = activeRef.current;
    activeRef.current = null;
    if (active) {
      active.controller.close();
      void active.context.close();
      closeWriter(active.mediaId);
    }
  }, []);
  const disable = useCallback(() => {
    dispose();
    setEnabled(false); setMicEnabled(false); setConnectionState("closed");
  }, [dispose]);
  useEffect(() => {
    setEnabled(false); setMicEnabled(false); setConnectionState("closed"); setTranscript(""); setError("");
    return dispose;
  }, [sessionId, dispose]);

  const enable = useCallback(async (): Promise<boolean> => {
    if (activeRef.current) return true;
    if (enabling.current) return false;
    if (!sessionId) { setError("请先选择会话或发送一条文字消息建立会话"); return false; }
    enabling.current = true;
    const owner = ++generation.current;
    let mediaId: string | null = null;
    let context: AudioContext | null = null;
    try {
      const response = await fetch("/api/v1/realtime/sessions", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: sessionId }),
      });
      if (!response.ok) throw new Error(`语音连接失败（HTTP ${response.status}）`);
      const body = await response.json() as { media_session_id: string; connection_epoch: number };
      mediaId = body.media_session_id;
      if (owner !== generation.current) { closeWriter(mediaId); return false; }
      context = new AudioContext();
      await context.resume();
      if (owner !== generation.current) { await context.close(); closeWriter(mediaId); return false; }
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
          if (state === "failed") {
            setError("语音连接已中断，请关闭后重试");
            activeRef.current?.controller.cancel();
            setMicEnabled(false);
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
      setEnabled(true); setError(""); return true;
    } catch (failure) {
      if (context) void context.close();
      if (mediaId) closeWriter(mediaId);
      if (owner === generation.current) {
        setConnectionState("failed"); setError(failure instanceof Error ? failure.message : "语音连接失败");
      }
      return false;
    } finally { if (owner === generation.current) enabling.current = false; }
  }, [sessionId]);

  const press = useCallback(() => {
    const active = activeRef.current;
    if (!active || active.client.connectionState !== "ready") return;
    active.controller.interrupt();
    setTranscript(""); setError("");
    void active.controller.press().then((started) => {
      if (activeRef.current === active) {
        setMicEnabled(started);
        if (!started && active.controller.pressedDown) setError("无法启动麦克风，请检查权限");
      }
    });
  }, []);
  const release = useCallback(() => { activeRef.current?.controller.release(); setMicEnabled(false); }, []);
  const interrupt = useCallback(() => { activeRef.current?.controller.interrupt(); }, []);
  return { enabled, connectionState, micEnabled, modality, chainLabel: chainDisclosure({ cascade: true }).label, transcript, error, enable, disable, press, release, interrupt };
}
