// M1：对话区实时会话控制器（`T-M1-9/12`）：组合采集、控制通道与播放输出。
//
// - 按下 → 采集开始；松开 → 结束输入（服务端进入 `AwaitingFinal`）；
// - 采集帧 → 控制通道 `sendAudioFrame`（仅 `ready` 时上行）；
// - **开口打断**：本地立即停播 + 通知服务端（区分请求与完成）；
// - 依赖注入（可测）；真实设备/延迟不在此验证（RTM-EVD-06）。

import type { PlaybackOutput } from "./audioPlayback";
import type { MediaSessionClient } from "./mediaSessionClient";
import type { MicCapture } from "./micCapture";

export interface RealtimeSessionDeps {
  client: MediaSessionClient;
  capture: MicCapture;
  playback: PlaybackOutput;
  onCommit?: () => void;
  onCancel?: () => void;
}

export class RealtimeSessionController {
  private inputOpen = false;
  constructor(private readonly deps: RealtimeSessionDeps) {}

  /** 按下说话：开始采集。设备/权限失败 → false（不伪装）。 */
  async press(): Promise<boolean> {
    if (this.deps.client.connectionState !== "ready") return false;
    this.inputOpen = true;
    return this.deps.capture.press();
  }

  /** 松开：结束输入（不停止识别；服务端完成终稿）。 */
  release(): void {
    const commit = this.inputOpen;
    this.inputOpen = false;
    this.deps.capture.release();
    if (commit) this.deps.onCommit?.();
  }

  /** 触摸取消：结束输入并丢弃余量。 */
  cancel(): void {
    this.inputOpen = false;
    this.deps.capture.cancel();
    this.deps.onCancel?.();
  }

  /** 上行一帧 16k PCM16（仅 `ready` 时发送）。 */
  sendFrame(frame: Int16Array): boolean {
    return this.deps.client.sendAudioFrame(frame);
  }

  /** 开口打断：**本地立即停播**，并通知服务端（区分请求与完成，D27）。 */
  interrupt(responseId?: string): boolean {
    const stoppedPlayback = this.deps.playback.stop();
    const stoppedQueue = this.deps.client.requestLocalInterrupt(responseId);
    // The local voice synthesizer is independent of the LLM task. Cancel only
    // its pending audio, never claim that the chat run itself was cancelled.
    this.deps.client.sendControl("tts.cancel");
    return stoppedPlayback || stoppedQueue;
  }

  get connectionState(): MediaSessionClient["connectionState"] {
    return this.deps.client.connectionState;
  }

  get pressedDown(): boolean { return this.deps.capture.pressedDown; }

  get micEnabled(): boolean {
    return this.deps.capture.micEnabled;
  }

  close(): void {
    this.deps.capture.cancel();
    this.deps.playback.stop();
    this.deps.client.close();
  }
}