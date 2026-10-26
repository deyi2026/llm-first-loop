// M1：对话区实时会话控制器（`T-M1-9/12`）：组合采集、控制通道与播放输出。
//
// - 按下 → **先本地停播（开口打断，不等服务端）** 再开始采集；松开 → 结束输入（服务端进入 `AwaitingFinal`）；
// - 采集帧 → 控制通道 `sendAudioFrame`（仅 `ready` 时上行）；**确有已上行音频**才在松开时发 `input.commit`；
// - `input.final` 记录终稿、`turn.committed` 触发**唯一一次**终稿提交（按 `turn_id` 去重；空终稿只提示不提交）；
// - 助手回复完成 → `tts.request`（同一回复只请求一次）；下行二进制经 `PlaybackQueue` 播放；
// - 发送失败/空终稿等降级走 `sink.onNotice`：**可见但非阻塞**（不静默吞掉、不报错轰炸）；
// - 依赖注入（可测）；真实设备/延迟不在此验证（RTM-EVD-06）。

import type { PlaybackOutput } from "./audioPlayback";
import type { MediaSessionClient } from "./mediaSessionClient";
import type { MicCapture } from "./micCapture";
import {
  REALTIME_PROTOCOL_VERSION,
  type RealtimeEnvelope,
  type VisualCommitRef,
} from "./realtimeEvents";

export interface RealtimeSessionIdentity {
  sessionId: string;
  mediaSessionId: string;
}

/** M3：提交时附带视觉指代的来源（由 `VisualShareController` 实现）。 */
export interface VisualCommitSource {
  commitVisual(): VisualCommitRef | null;
}

export interface RealtimeSessionSink {
  /** `turn.committed` 终稿到达：交上层复用既有 sendMessage 路径提交（不新造第二套提交）。 */
  onCommittedTranscript?: (text: string, turnId: string) => void;
  /**
   * M3：**带视觉的提交**由服务端提交任务（turn.committed 携带 visual 证据），
   * 客户端**不得**再把该 turn 终稿提交到对话（否则重复）；仅上报可见状态。
   */
  onVisualTurnCommitted?: (info: { turnId: string; text: string; taskRef: string | null }) => void;
  /** M3：`visual.clarify` 到达：必须向用户展示问题；**不得**自动改 kind 重发。 */
  onVisualClarify?: (question: string, turnId: string) => void;
  /** 可见但非阻塞的降级提示（发送失败/空终稿/播放被拒等）。 */
  onNotice?: (message: string) => void;
  /**
   * 87aa41fd2 语义移植：服务端 TTS 合成失败（audio.playback_unavailable）——
   * 上层据此把 playbackState 置 failed 并提供「重试语音回复」入口。
   */
  onPlaybackUnavailable?: (responseId: string) => void;
}

export interface RealtimeSessionDeps {
  client: MediaSessionClient;
  capture: MicCapture;
  playback: PlaybackOutput;
  identity: RealtimeSessionIdentity;
  sink?: RealtimeSessionSink;
  /** M3 视觉共享（可选；未注入 = 纯语音，行为零变化）。 */
  visual?: VisualCommitSource;
}

/** 已提交 turn 去重集合上限（长会话防无界增长；超出按插入序淘汰最旧）。 */
const MAX_REMEMBERED_TURNS = 200;

export class RealtimeSessionController {
  private seq = 0;
  private eventIdCounter = 0;
  private pressActive = false;
  private uploadedFrames = 0;
  /** M3：最近一次 input.commit 是否携带 visual（该 turn 由服务端提交，客户端不回投终稿）。 */
  private visualCommitPending = false;
  private readonly visualTurns = new Set<string>();
  private readonly committedTurns = new Set<string>();
  private readonly finalTexts = new Map<string, string>();
  private readonly ttsRequested = new Set<string>();
  /** 最近一次成功上送的 TTS 请求（text+responseId）：供「重试语音回复」原样重发。 */
  private lastTtsRequest: { text: string; responseId: string } | null = null;

  constructor(private readonly deps: RealtimeSessionDeps) {
    this.deps.client.onEvent?.((envelope) => this.handleEvent(envelope));
  }

  /** 按下说话：**先本地停播**（开口打断）、尽力恢复挂起的 AudioContext（自愈，失败不阻断），再开始采集。设备/权限失败/启动超时 → false（不伪装）。 */
  async press(): Promise<boolean> {
    this.interrupt();
    // M3 后续自愈：新一轮按住手势是解除 autoplay 挂起的最佳时机；resume 尽力而为，
    // 失败不阻断按压流程（播放侧仍有 playNext 的降级路径兜底）。
    try {
      await this.deps.playback.recoverIfSuspended();
    } catch {
      /* 自愈失败不影响本轮按压 */
    }
    const started = await this.deps.capture.press();
    if (started) {
      this.pressActive = true;
      this.uploadedFrames = 0;
    }
    return started;
  }

  /**
   * 松开：结束输入（flush 余量后）提交 `input.commit`。
   * 仅当**本轮确有已上行音频**且连接 `ready` 时发送；重复 release / 无音频 / 未就绪 → 不发送，可见提示。
   * M3：共享中附带 `visual:{source_id,kind}`（由注入的 `visual` 来源决定；无 = 纯语音零变化）。
   */
  release(): void {
    const wasPressed = this.pressActive;
    this.pressActive = false;
    this.deps.capture.release(); // flush 余量 → onFrame → handleCapturedFrame（ready 时计数）
    if (!wasPressed) {
      return; // 重复松开：不得重复提交
    }
    const uploaded = this.uploadedFrames;
    this.uploadedFrames = 0;
    if (uploaded === 0) {
      this.notify("未采集到可上传的音频，本轮语音不提交");
      return;
    }
    if (this.deps.client.connectionState !== "ready") {
      this.notify("实时连接未就绪，本轮语音未能提交");
      return;
    }
    const visual = this.deps.visual?.commitVisual() ?? null;
    if (!this.sendEvent("input.commit", visual !== null ? { visual } : undefined)) {
      this.notify("input.commit 发送失败，本轮语音未能提交");
      return;
    }
    // 记录本次提交是否带视觉：带视觉的 turn 由服务端提交任务，客户端不再回投终稿
    this.visualCommitPending = visual !== null;
  }

  /** 触摸取消：结束输入并丢弃余量（不提交）。 */
  cancel(): void {
    this.pressActive = false;
    this.uploadedFrames = 0;
    this.deps.capture.cancel();
  }

  /** 上行一帧 16k PCM16（仅 `ready` 时发送；成功才计入本轮已上行音频）。 */
  sendFrame(frame: Int16Array): boolean {
    return this.handleCapturedFrame(frame);
  }

  /** 采集接线入口：每帧经此上行（供 press/release 计数「确有采集音频」）。 */
  handleCapturedFrame(frame: Int16Array): boolean {
    const sent = this.deps.client.sendAudioFrame(frame);
    if (sent) {
      this.uploadedFrames += 1;
    }
    return sent;
  }

  /**
   * 助手回复完成后请求本地 TTS：同一回复（`responseId`）**只请求一次**。
   * 成功后预绑定下行二进制分片的回复归属（见 `MediaSessionClient.noteActiveResponse`）。
   */
  requestTts(text: string, responseId: string): boolean {
    const trimmed = text.trim();
    if (!trimmed || !responseId) {
      return false;
    }
    if (this.ttsRequested.has(responseId)) {
      return false; // 同一回复不重复请求
    }
    if (this.deps.client.connectionState !== "ready") {
      this.notify("实时连接未就绪，本轮回复不播报（文本已保留在对话中）");
      return false;
    }
    if (!this.sendEvent("tts.request", { response_id: responseId, text: trimmed })) {
      this.notify("tts.request 发送失败，本轮回复不播报（文本已保留在对话中）");
      return false;
    }
    this.ttsRequested.add(responseId);
    this.lastTtsRequest = { text: trimmed, responseId };
    this.deps.client.noteActiveResponse?.(responseId);
    return true;
  }

  /**
   * 87aa41fd2 语义移植：重试语音回复——把最近一次 TTS 请求原样重发一次
   * （绕过同回复去重：失败重试不等于重复播报）。无可用请求返回 false。
   */
  retryTts(): boolean {
    const last = this.lastTtsRequest;
    if (last === null) {
      return false;
    }
    if (this.deps.client.connectionState !== "ready") {
      this.notify("实时连接未就绪，暂不能重试语音回复");
      return false;
    }
    this.ttsRequested.delete(last.responseId);
    const sent = this.sendEvent("tts.request", { response_id: last.responseId, text: last.text });
    if (sent) {
      this.ttsRequested.add(last.responseId);
    }
    return sent;
  }

  /** 开口打断：**本地立即停播**，并通知服务端（区分请求与完成，D27）。 */
  interrupt(responseId?: string): boolean {
    const stoppedPlayback = this.deps.playback.stop();
    const stoppedQueue = this.deps.client.requestLocalInterrupt(responseId);
    return stoppedPlayback || stoppedQueue;
  }

  get connectionState(): MediaSessionClient["connectionState"] {
    return this.deps.client.connectionState;
  }

  get micEnabled(): boolean {
    return this.deps.capture.micEnabled;
  }

  close(): void {
    this.pressActive = false;
    this.uploadedFrames = 0;
    this.visualCommitPending = false;
    this.deps.capture.cancel();
    this.deps.playback.stop();
    this.deps.client.requestLocalInterrupt(); // 清空播放队列（本地停播语义，防迟到分片复活）
    this.deps.client.close();
    this.committedTurns.clear();
    this.visualTurns.clear();
    this.finalTexts.clear();
    this.ttsRequested.clear();
  }

  private handleEvent(envelope: RealtimeEnvelope): void {
    if (envelope.type === "input.final" && envelope.turn_id !== undefined) {
      // 终稿先到：记录文本（committed 携带同名文本时以事件为准）
      if (typeof envelope.text === "string") {
        this.finalTexts.set(envelope.turn_id, envelope.text);
      }
      return;
    }
    if (envelope.type === "turn.committed" && envelope.turn_id !== undefined) {
      const turnId = envelope.turn_id;
      // 带视觉的 turn：服务端已提交任务（visual 证据数组），客户端不再回投终稿（防重复提交）
      const isVisualTurn =
        this.visualCommitPending ||
        this.visualTurns.has(turnId) ||
        Array.isArray(envelope.visual);
      if (this.committedTurns.has(turnId)) {
        return; // 按 turn_id 去重：只处理一次
      }
      this.rememberTurn(turnId);
      const text =
        typeof envelope.text === "string" && envelope.text.trim() !== ""
          ? envelope.text
          : this.finalTexts.get(turnId) ?? "";
      const trimmed = text.trim();
      if (isVisualTurn) {
        this.visualCommitPending = false;
        this.visualTurns.add(turnId);
        if (!trimmed) {
          this.notify(`带画面的语音终稿为空（turn ${turnId}）`);
          return;
        }
        this.deps.sink?.onVisualTurnCommitted?.({
          turnId,
          text: trimmed,
          taskRef: typeof envelope.task_ref === "string" && envelope.task_ref !== "" ? envelope.task_ref : null,
        });
        return;
      }
      if (!trimmed) {
        this.notify(`语音终稿为空（turn ${turnId}），未提交`);
        return;
      }
      this.deps.sink?.onCommittedTranscript?.(trimmed, turnId);
      return;
    }
    if (envelope.type === "visual.clarify") {
      // 澄清：只展示问题，绝不自动改 kind 重发（契约 §6.4）
      const turnId = typeof envelope.turn_id === "string" ? envelope.turn_id : "";
      const question = typeof envelope.question === "string" ? envelope.question : "";
      this.visualCommitPending = false;
      if (turnId !== "") {
        this.visualTurns.add(turnId);
      }
      if (question !== "") {
        this.deps.sink?.onVisualClarify?.(question, turnId);
      }
      return;
    }
    if (envelope.type === "audio.playback_unavailable") {
      // 87aa41fd2 语义移植：TTS 合成失败 → 有界降级（文本已保留），提供重试入口。
      const responseId = typeof envelope.response_id === "string" ? envelope.response_id : "";
      this.notify("语音回复未播放（本地语音合成失败）；回复文本已保留，可重试语音回复");
      this.deps.sink?.onPlaybackUnavailable?.(responseId);
      return;
    }
    if (envelope.type === "error") {
      // 有界错误：可见提示（不阻塞）；带视觉的提交失败时服务端不派发任务
      this.visualCommitPending = false;
      const code = typeof envelope.code === "number" ? envelope.code : 0;
      const reason = typeof envelope.reason === "string" ? envelope.reason : "unknown";
      this.notify(`实时服务返回错误（${code} ${reason}）`);
    }
  }

  private rememberTurn(turnId: string): void {
    this.committedTurns.add(turnId);
    if (this.committedTurns.size > MAX_REMEMBERED_TURNS) {
      const oldest = this.committedTurns.values().next().value;
      if (oldest !== undefined) {
        this.committedTurns.delete(oldest);
        this.finalTexts.delete(oldest);
      }
    }
  }

  private sendEvent(
    type: "input.commit" | "tts.request",
    extra?: Pick<RealtimeEnvelope, "response_id" | "text" | "visual">,
  ): boolean {
    const envelope: RealtimeEnvelope = {
      version: REALTIME_PROTOCOL_VERSION,
      type,
      event_id: this.nextEventId(),
      seq: (this.seq += 1),
      connection_epoch: this.deps.client.connectionEpoch,
      session_id: this.deps.identity.sessionId,
      media_session_id: this.deps.identity.mediaSessionId,
      ...extra,
    };
    return this.deps.client.sendEvent(envelope);
  }

  private nextEventId(): string {
    this.eventIdCounter += 1;
    const uuid = globalThis.crypto?.randomUUID?.();
    return uuid ?? `evt-${Date.now()}-${this.eventIdCounter}`;
  }

  private notify(message: string): void {
    this.deps.sink?.onNotice?.(message);
  }
}