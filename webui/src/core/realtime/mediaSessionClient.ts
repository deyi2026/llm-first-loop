// M1：实时媒体会话控制通道 WS 客户端（`T-M1-9/10/12`）。
//
// 语义（对齐服务端 `media_session` / `realtime_ws`，RTM-SES-01/05、REC-03/09、IDN-03/07、CAP-14）：
// - `ready` = 握手完成 + 传输就绪（**不要求先收到首帧**）；`opening` 未就绪前**不得上传媒体**；
// - **非可重试关闭码**（4401 未登录 / 4403 跨站 / 4404 越权）→ `failed`，**不循环重连**；
// - 其他断开 → **有界重连**（默认 3 次，0.5/1/2s 抖动）；
// - 旧 `connection_epoch` 事件不得更新当前会话；
// - 下行二进制 = 本地 TTS 音频 → 交 `PlaybackQueue`；**开口打断本地立即停播**。
//
// 本模块以**注入式 Socket/定时器**实现纯逻辑（可 vitest 验证）；真实网络与设备不在此验证。

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

/** 非可重试关闭码：鉴权失效/跨站/越权（RTM-REC-09、RTM-CAP-14）。 */
export const NON_RETRYABLE_CLOSE_CODES: ReadonlySet<number> = new Set([4401, 4403, 4404]);

export interface MediaSessionClientOptions {
  url: string;
  createSocket: (url: string) => SocketLike;
  playback: PlaybackQueue;
  backoffMs?: readonly number[];
  scheduleTimeout?: (fn: () => void, ms: number) => void;
}

const DEFAULT_BACKOFF: readonly number[] = [500, 1000, 2000];

export class MediaSessionClient {
  private state: ConnectionState = "closed";
  private epoch = 1;
  private attempts = 0;
  private socket: SocketLike | null = null;
  private currentResponseId: string | null = null;
  private readonly listeners: ((event: RealtimeEnvelope) => void)[] = [];

  constructor(private readonly options: MediaSessionClientOptions) {}

  get connectionState(): ConnectionState {
    return this.state;
  }

  get connectionEpoch(): number {
    return this.epoch;
  }

  get reconnectAttempts(): number {
    return this.attempts;
  }

  connect(epoch = 1): void {
    if (this.state === "opening" || this.state === "ready") {
      return;
    }
    this.epoch = epoch;
    this.attempts = 0;
    this.openSocket();
  }

  onEvent(listener: (event: RealtimeEnvelope) => void): void {
    this.listeners.push(listener);
  }

  private openSocket(): void {
    this.state = "opening";
    const socket = this.options.createSocket(this.options.url);
    this.socket = socket;
    socket.onopen = (): void => {
      this.state = "ready";
      this.attempts = 0;
    };
    socket.onmessage = (event): void => this.handleMessage(event.data);
    socket.onerror = (): void => {
      /* 等待 onclose 决定重连或失败 */
    };
    socket.onclose = (event): void => this.handleClose(event.code);
  }

  private handleClose(code: number): void {
    this.socket = null;
    if (this.state === "closing") {
      this.state = "closed";
      return;
    }
    if (NON_RETRYABLE_CLOSE_CODES.has(code)) {
      this.state = "failed";
      return;
    }
    const backoff = this.options.backoffMs ?? DEFAULT_BACKOFF;
    if (this.attempts >= backoff.length) {
      this.state = "failed";
      return;
    }
    const delay = backoff[this.attempts];
    this.attempts += 1;
    this.state = "reconnecting";
    const schedule = this.options.scheduleTimeout ?? ((fn, ms) => setTimeout(fn, ms));
    schedule(() => this.openSocket(), delay);
  }

  close(): void {
    if (this.state === "closed") {
      return;
    }
    this.state = "closing";
    const socket = this.socket;
    this.socket = null;
    if (socket) {
      socket.close(1000);
    }
    this.state = "closed";
  }

  /** 仅 `ready` 允许上传 16k PCM16 音频（RTM-SES-01）。 */
  sendAudioFrame(pcm: Int16Array): boolean {
    if (this.state !== "ready" || this.socket === null) {
      return false;
    }
    this.socket.send(pcm.buffer as ArrayBuffer);
    return true;
  }

  sendEvent(envelope: RealtimeEnvelope): boolean {
    if (this.state !== "ready" || this.socket === null) {
      return false;
    }
    this.socket.send(JSON.stringify(envelope));
    return true;
  }

  /** 客户端开口打断：**本地立即停播**（不等服务端确认，D27）。 */
  requestLocalInterrupt(responseId?: string): boolean {
    return this.options.playback.interrupt(responseId);
  }

  handleMessage(data: string | ArrayBuffer): void {
    if (typeof data !== "string") {
      this.options.playback.enqueue({
        responseId: this.currentResponseId ?? "local_tts",
        connectionEpoch: this.epoch,
        data,
      });
      return;
    }
    const envelope = JSON.parse(data) as RealtimeEnvelope;
    assertEnvelope(envelope);
    if (envelope.connection_epoch < this.epoch) {
      return; // 旧代次不得更新当前会话
    }
    if (envelope.response_id !== undefined) {
      this.currentResponseId = envelope.response_id;
    }
    for (const listener of this.listeners) {
      listener(envelope);
    }
  }
}