import { PlaybackQueue } from "./playbackQueue";
import { assertEnvelope, type RealtimeEnvelope } from "./realtimeEvents";

export type ConnectionState = "opening" | "ready" | "reconnecting" | "failed" | "closing" | "closed";
export interface SocketLike {
  send(data: string | ArrayBuffer): void;
  close(code?: number): void;
  onopen: (() => void) | null;
  onmessage: ((event: { data: string | ArrayBuffer }) => void) | null;
  onclose: ((event: { code: number }) => void) | null;
  onerror: ((event: unknown) => void) | null;
}
export const NON_RETRYABLE_CLOSE_CODES: ReadonlySet<number> = new Set([4401, 4403, 4404]);
export interface MediaSessionClientOptions {
  url: string;
  createSocket: (url: string) => SocketLike;
  playback: PlaybackQueue;
  sessionId?: string;
  mediaSessionId?: string;
  onStateChange?: (state: ConnectionState) => void;
  onAudio?: () => void;
  backoffMs?: readonly number[];
  scheduleTimeout?: (fn: () => void, ms: number) => void;
}
const DEFAULT_BACKOFF = [500, 1000, 2000] as const;

export class MediaSessionClient {
  private state: ConnectionState = "closed";
  private epoch = 1;
  private attempts = 0;
  private socket: SocketLike | null = null;
  private currentResponseId: string | null = null;
  private requestedTtsResponseId: string | null = null;
  private expectedAudioResponseId: string | null = null;
  private readonly ignoredAudioResponses = new Set<string>();
  private generation = 0;
  private seq = 0;
  private readonly listeners: ((event: RealtimeEnvelope) => void)[] = [];
  constructor(private readonly options: MediaSessionClientOptions) {}
  get connectionState(): ConnectionState { return this.state; }
  get connectionEpoch(): number { return this.epoch; }
  get reconnectAttempts(): number { return this.attempts; }
  private setState(state: ConnectionState): void {
    this.state = state;
    this.options.onStateChange?.(state);
  }
  connect(epoch = 1): void {
    if (this.state === "opening" || this.state === "ready") return;
    this.epoch = epoch;
    this.attempts = 0;
    this.generation++;
    this.openSocket(this.generation);
  }
  onEvent(listener: (event: RealtimeEnvelope) => void): void { this.listeners.push(listener); }
  private openSocket(generation: number): void {
    if (generation !== this.generation) return;
    this.setState("opening");
    const socket = this.options.createSocket(this.options.url);
    this.socket = socket;
    const active = () => generation === this.generation && this.socket === socket;
    socket.onopen = () => { if (active()) this.setState("ready"); };
    socket.onmessage = (event) => { if (active()) this.handleMessage(event.data); };
    socket.onerror = () => { /* onclose owns retry/failure. */ };
    socket.onclose = (event) => { if (active()) this.handleClose(event.code, generation); };
  }
  private handleClose(code: number, generation: number): void {
    this.socket = null;
    this.requestedTtsResponseId = null;
    this.expectedAudioResponseId = null;
    if (NON_RETRYABLE_CLOSE_CODES.has(code)) { this.setState("failed"); return; }
    const backoff = this.options.backoffMs ?? DEFAULT_BACKOFF;
    if (this.attempts >= backoff.length) { this.setState("failed"); return; }
    const delay = backoff[this.attempts++];
    this.setState("reconnecting");
    const schedule = this.options.scheduleTimeout ?? ((fn, ms) => setTimeout(fn, ms));
    schedule(() => this.openSocket(generation), delay);
  }
  close(): void {
    this.generation++; // Fences callbacks and queued reconnect timers.
    const socket = this.socket;
    this.socket = null;
    this.requestedTtsResponseId = null;
    this.expectedAudioResponseId = null;
    this.setState("closing");
    socket?.close(1000);
    this.options.playback.clear();
    this.setState("closed");
  }
  sendAudioFrame(pcm: Int16Array): boolean {
    if (this.state !== "ready" || this.socket === null) return false;
    this.socket.send(pcm.slice().buffer as ArrayBuffer);
    return true;
  }
  sendEvent(envelope: RealtimeEnvelope): boolean {
    if (this.state !== "ready" || this.socket === null) return false;
    this.socket.send(JSON.stringify(envelope));
    return true;
  }
  sendControl(type: string, payload: Record<string, unknown> = {}): boolean {
    if (!this.options.sessionId || !this.options.mediaSessionId) return false;
    const sent = this.sendEvent({
      ...payload, version: 1, type, event_id: crypto.randomUUID(), seq: ++this.seq,
      connection_epoch: this.epoch, session_id: this.options.sessionId,
      media_session_id: this.options.mediaSessionId,
    });
    if (sent && (type === "tts.request" || type === "tts.cancel")) {
      // Only binary introduced by the latest owned TTS request is playable.
      this.requestedTtsResponseId = type === "tts.request" && typeof payload.response_id === "string"
        ? payload.response_id : null;
      this.expectedAudioResponseId = null;
    }
    return sent;
  }
  requestLocalInterrupt(responseId?: string): boolean {
    const ignored = responseId ?? this.currentResponseId;
    if (ignored) {
      this.ignoredAudioResponses.add(ignored);
      if (this.ignoredAudioResponses.size > 64) {
        this.ignoredAudioResponses.delete(this.ignoredAudioResponses.values().next().value!);
      }
    }
    this.requestedTtsResponseId = null;
    this.expectedAudioResponseId = null;
    return this.options.playback.interrupt(responseId);
  }
  handleMessage(data: string | ArrayBuffer): void {
    if (typeof data !== "string") {
      const responseId = this.expectedAudioResponseId;
      this.expectedAudioResponseId = null; // One binary chunk per audio.playback marker.
      if (!responseId || this.ignoredAudioResponses.has(responseId)) return;
      if (this.options.playback.enqueue({ responseId, connectionEpoch: this.epoch, data })) {
        this.options.onAudio?.();
      }
      return;
    }
    let envelope: RealtimeEnvelope;
    try {
      envelope = JSON.parse(data) as RealtimeEnvelope;
      assertEnvelope(envelope);
    } catch {
      this.close();
      this.setState("failed");
      return;
    }
    if (envelope.connection_epoch !== this.epoch) return;
    if (this.options.sessionId && envelope.session_id !== this.options.sessionId) return;
    if (this.options.mediaSessionId && envelope.media_session_id !== this.options.mediaSessionId) return;
    if (envelope.type === "audio.playback") {
      const responseId = envelope.response_id;
      if (!responseId || this.ignoredAudioResponses.has(responseId)) return;
      if (this.options.sessionId && this.options.mediaSessionId) {
        if (this.requestedTtsResponseId !== responseId) return;
        this.requestedTtsResponseId = null;
      }
      this.expectedAudioResponseId = responseId;
    }
    if (envelope.response_id !== undefined) this.currentResponseId = envelope.response_id;
    for (const listener of this.listeners) listener(envelope);
  }
}
