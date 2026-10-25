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
  /** 连接状态变化通知（供 UI/接线层同步 `connectionState`）。 */
  onStateChange?: (state: ConnectionState) => void;
  /**
   * 下行协议错误（JSON 解析失败/信封断言失败）的有界上报：**每连接仅首个坏帧回调一次**
   * （不逐帧刷屏），帧本身丢弃、不中断处理链；回调只携带错误类别与计数，**不含原始载荷**
   * （隐私契约 §6：日志/UI 禁止记录帧内容）。
   */
  onProtocolError?: (info: { kind: ProtocolErrorKind; malformedFrames: number }) => void;
}

/** 坏帧类别：`parse` = 非 JSON 文本；`envelope` = JSON 但必填字段/版本/序号不合法。 */
export type ProtocolErrorKind = "parse" | "envelope";

const DEFAULT_BACKOFF: readonly number[] = [500, 1000, 2000];

export class MediaSessionClient {
  private state: ConnectionState = "closed";
  private epoch = 1;
  private attempts = 0;
  private socket: SocketLike | null = null;
  /** 已排期的重连定时器句柄（默认 `setTimeout` 路径；close() 时取消，防僵尸 socket）。 */
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  /**
   * 显式 close() 标记：初始 state 即 "closed"（从未连接），不能凭 state 区分
   * 「尚未 connect」与「已 disable」——后者必须挡住迟到的重连回调（僵尸 socket）。
   */
  private explicitlyClosed = false;
  private currentResponseId: string | null = null;
  private readonly listeners: ((event: RealtimeEnvelope) => void)[] = [];
  /** 本连接丢弃的坏帧数（协议错误有界上报的计数部分）。 */
  private malformedFrames = 0;
  /** 本连接是否已上报过协议错误（每连接只回调一次，避免逐帧刷屏）。 */
  private protocolErrorNotified = false;

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

  /** 本连接累计丢弃的坏帧数（供诊断/测试断言；不含任何载荷内容）。 */
  get malformedFrameCount(): number {
    return this.malformedFrames;
  }

  /** 坏帧丢弃的统一出口：计数 + 每连接一次的有界回调（不携带原始载荷）。 */
  private reportProtocolError(kind: ProtocolErrorKind): void {
    this.malformedFrames += 1;
    if (this.protocolErrorNotified) {
      return;
    }
    this.protocolErrorNotified = true;
    this.options.onProtocolError?.({ kind, malformedFrames: this.malformedFrames });
  }

  private setState(next: ConnectionState): void {
    this.state = next;
    this.options.onStateChange?.(next);
  }

  connect(epoch = 1): void {
    if (this.state === "opening" || this.state === "ready") {
      return;
    }
    if (this.reconnectTimer !== null) {
      // 重连退避窗口内被显式重连：丢弃旧定时器，防同一客户端双开 socket
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    this.explicitlyClosed = false; // 显式 connect 请求：重置关闭标记（重新启用）
    this.epoch = epoch;
    this.attempts = 0;
    this.openSocket();
  }

  onEvent(listener: (event: RealtimeEnvelope) => void): void {
    this.listeners.push(listener);
  }

  private openSocket(): void {
    if (this.explicitlyClosed || this.socket !== null) {
      return; // 已显式 close()：迟到的重连回调不得复活（僵尸 socket）；
      // 已有活动连接（重新启用期间旧回调迟到）：不得双开
    }
    this.setState("opening");
    // 新连接 = 新的协议错误上报窗口（有界：每连接一次）
    this.malformedFrames = 0;
    this.protocolErrorNotified = false;
    const socket = this.options.createSocket(this.options.url);
    this.socket = socket;
    socket.onopen = (): void => {
      this.setState("ready");
      this.attempts = 0;
    };
    socket.onmessage = (event): void => this.handleMessage(event.data);
    socket.onerror = (): void => {
      /* 等待 onclose 决定重连或失败 */
    };
    socket.onclose = (event): void => {
      // e8a1d0a19 语义移植：废弃 socket 的重复/迟到 onclose 不得再次消耗重试预算
      // （handleClose 已置空 this.socket、或新连接已替换旧 socket 时，直接忽略）。
      if (this.socket !== socket) return;
      this.handleClose(event.code);
    };
  }

  private handleClose(code: number): void {
    this.socket = null;
    if (this.state === "closing") {
      this.setState("closed");
      return;
    }
    if (this.state === "closed") {
      return; // close() 已完成：迟到 onclose 不得复活（不重连、不改状态）
    }
    if (NON_RETRYABLE_CLOSE_CODES.has(code)) {
      this.setState("failed");
      return;
    }
    const backoff = this.options.backoffMs ?? DEFAULT_BACKOFF;
    if (this.attempts >= backoff.length) {
      this.setState("failed");
      return;
    }
    const delay = backoff[this.attempts];
    this.attempts += 1;
    this.setState("reconnecting");
    this.scheduleReconnect(delay);
  }

  /**
   * 排期一次重连。重连调度处与 `openSocket()` 入口**双重**校验 closed：
   * `close()` 落在退避窗口（0.5–2s）内时，默认路径的定时器被取消；注入式
   * `scheduleTimeout` 不可取消的回调由守卫兜底——任何路径都不得在 close()
   * 之后重开 socket（僵尸 socket / disabled 后状态复活）。
   */
  private scheduleReconnect(delay: number): void {
    if (this.state === "closed" || this.explicitlyClosed) {
      return; // 已显式关闭：不再排期
    }
    const fire = (): void => {
      this.reconnectTimer = null;
      if (this.state === "closed" || this.explicitlyClosed) {
        return; // close() 落在退避窗口内：迟到回调不得重开
      }
      this.openSocket();
    };
    const schedule = this.options.scheduleTimeout;
    if (schedule !== undefined) {
      schedule(fire, delay); // 注入式调度器无取消句柄 → 依赖 openSocket 守卫兜底
      return;
    }
    this.reconnectTimer = setTimeout(fire, delay);
  }

  close(): void {
    if (this.state === "closed") {
      return;
    }
    // 显式关闭标记：此后迟到的重连回调/迟到 onclose 都不得复活（见 explicitlyClosed）
    this.explicitlyClosed = true;
    // 取消已排期的重连定时器：disable 落在退避窗口内时不得让定时器复活已关闭的客户端
    if (this.reconnectTimer !== null) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    this.setState("closing");
    const socket = this.socket;
    this.socket = null;
    if (socket) {
      socket.close(1000);
    }
    // 关闭后迟到消息不得再触发任何上层动作（终稿提交/播报）
    this.listeners.length = 0;
    this.setState("closed");
  }

  /** 仅 `ready` 允许上传 16k PCM16 音频（RTM-SES-01）。 */
  sendAudioFrame(pcm: Int16Array): boolean {
    if (this.state !== "ready" || this.socket === null) {
      return false;
    }
    this.socket.send(pcm.buffer as ArrayBuffer);
    return true;
  }

  /** 发送文本控制事件；信封先过 `assertEnvelope`（缺字段显式失败，不造假任务）。 */
  sendEvent(envelope: RealtimeEnvelope): boolean {
    assertEnvelope(envelope);
    if (this.state !== "ready" || this.socket === null) {
      return false;
    }
    this.socket.send(JSON.stringify(envelope));
    return true;
  }

  /**
   * 绑定后续二进制分片的回复归属：发出 `tts.request` 后、`audio.playback` 事件到达前，
   * 服务端先下行音频二进制帧（`realtime_session_runtime`：send_binary 在 emit 之前），
   * 故以**本端请求的 response_id** 预绑定，避免分片落到上一回复/占位 id。
   */
  noteActiveResponse(responseId: string): void {
    this.currentResponseId = responseId;
  }

  /** 客户端开口打断：**本地立即停播**（不等服务端确认，D27）。 */
  requestLocalInterrupt(responseId?: string): boolean {
    return this.options.playback.interrupt(responseId);
  }

  handleMessage(data: string | ArrayBuffer): void {
    if (typeof data !== "string") {
      // 下行二进制 = 本地 TTS 无头 16k PCM16（RTM-PLY-07、CAP-05）
      this.options.playback.enqueue({
        responseId: this.currentResponseId ?? "local_tts",
        connectionEpoch: this.epoch,
        data,
        format: "pcm16",
      });
      return;
    }
    // P2-11：下行坏帧（非 JSON / 信封断言失败）不得抛出打断 onmessage 处理链——
    // 丢弃该帧并走有界上报（每连接一次 + 计数），绝不携带原始载荷（隐私契约 §6）。
    let parsed: unknown;
    try {
      parsed = JSON.parse(data);
    } catch {
      this.reportProtocolError("parse");
      return;
    }
    const envelope = parsed as RealtimeEnvelope;
    try {
      assertEnvelope(envelope);
    } catch {
      this.reportProtocolError("envelope");
      return;
    }
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