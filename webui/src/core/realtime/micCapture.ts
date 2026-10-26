// M1：麦克风采集 DOM 接线（`T-M1-9`）：`getUserMedia` + `AudioWorklet` → 16k PCM16 帧。
//
// 语义（RTM-AUD-01/03/06、CAP-14）：
// - **按下开始采集、松开结束输入**；允许松开后完成识别与提交（服务端 `AwaitingFinal`）；
// - **失焦 / 触摸取消**：结束输入（`onBlur`）或取消本轮（`cancel`）；
// - 设备/权限失败**如实返回失败**，不伪造采集；
// - 依赖（`mediaDevices`、worklet 端口）**注入**，故本模块可在 jsdom 下用 fake 验证接线逻辑；
//   真实设备与延迟**不在此验证**（RTM-EVD-06）。

import type { CapturePipeline } from "./capturePipeline";

export interface MediaStreamTrackLike {
  stop(): void;
}

export interface MediaStreamLike {
  getTracks(): MediaStreamTrackLike[];
}

export interface MediaDevicesLike {
  getUserMedia(constraints: { audio: unknown }): Promise<MediaStreamLike>;
}

export interface WorkletPortLike {
  onmessage: ((event: { data: { samples: Float32Array; sampleRate: number; channels?: number } }) => void) | null;
  close(): void;
}

export interface MicCaptureOptions {
  mediaDevices: MediaDevicesLike;
  pipeline: CapturePipeline;
  onFrame: (frame: Int16Array) => void;
  createPort: () => WorkletPortLike;
  constraints?: { audio: unknown };
}

/** 按下说话失败原因分类（供上层给出可操作的提示文案）。 */
export type MicPressErrorKind = "not-allowed" | "not-found" | "not-readable" | "unknown";

/** 把 getUserMedia 异常映射为稳定错误类（厂商历史 name 变体一并归并）。 */
export function classifyPressError(error: unknown): MicPressErrorKind {
  const name = error instanceof Error ? error.name : "";
  switch (name) {
    case "NotAllowedError":
    case "SecurityError":
    case "PermissionDeniedError":
      return "not-allowed";
    case "NotFoundError":
    case "DevicesNotFoundError":
      return "not-found";
    case "NotReadableError":
    case "TrackStartError":
    case "AbortError":
      return "not-readable";
    default:
      return "unknown";
  }
}

export class MicCapture {
  private stream: MediaStreamLike | null = null;
  private port: WorkletPortLike | null = null;
  private pressed = false;
  private lastError: MicPressErrorKind | null = null;

  constructor(private readonly options: MicCaptureOptions) {}

  get micEnabled(): boolean {
    return this.stream !== null;
  }

  get pressedDown(): boolean {
    return this.pressed;
  }

  /** 最近一次 press 失败的原因分类；成功或从未按下 → null。 */
  get pressError(): MicPressErrorKind | null {
    return this.lastError;
  }

  /** 按下说话：开始采集。返回是否真正开始（权限/设备失败 → false，不伪造）。 */
  async press(): Promise<boolean> {
    this.lastError = null;
    if (this.stream !== null) {
      this.pressed = true;
      return true;
    }
    try {
      this.stream = await this.options.mediaDevices.getUserMedia(
        this.options.constraints ?? { audio: true },
      );
    } catch (error) {
      this.stream = null;
      this.lastError = classifyPressError(error);
      return false;
    }
    const port = this.options.createPort();
    port.onmessage = (event): void => this.handleSamples(event.data);
    this.port = port;
    this.pressed = true;
    return true;
  }

  /** 松开：结束输入（停止采集）；余量 flush 发出，不丢尾段。 */
  release(): void {
    this.pressed = false;
    this.stopStream();
    for (const frame of this.options.pipeline.flush()) {
      this.options.onFrame(frame);
    }
  }

  /** 触摸取消：结束输入且**丢弃**当前余量。 */
  cancel(): void {
    this.pressed = false;
    this.stopStream();
  }

  /** 失焦：等同松开（结束输入，允许后续识别/提交，RTM-AUD-06）。 */
  onBlur(): void {
    if (this.pressed) {
      this.release();
    }
  }

  handleSamples(data: { samples: Float32Array; sampleRate: number; channels?: number }): void {
    if (this.stream === null) {
      return;
    }
    for (const frame of this.options.pipeline.push(data.samples, data.sampleRate, data.channels ?? 1)) {
      this.options.onFrame(frame);
    }
  }

  private stopStream(): void {
    if (this.port !== null) {
      this.port.onmessage = null;
      this.port.close();
      this.port = null;
    }
    if (this.stream !== null) {
      for (const track of this.stream.getTracks()) {
        track.stop();
      }
      this.stream = null;
    }
  }
}