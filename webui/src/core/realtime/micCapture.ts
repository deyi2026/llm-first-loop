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

export class MicCapture {
  private stream: MediaStreamLike | null = null;
  private port: WorkletPortLike | null = null;
  private pressed = false;

  constructor(private readonly options: MicCaptureOptions) {}

  get micEnabled(): boolean {
    return this.stream !== null;
  }

  get pressedDown(): boolean {
    return this.pressed;
  }

  /** 按下说话：开始采集。返回是否真正开始（权限/设备失败 → false，不伪造）。 */
  async press(): Promise<boolean> {
    if (this.stream !== null) {
      this.pressed = true;
      return true;
    }
    try {
      this.stream = await this.options.mediaDevices.getUserMedia(
        this.options.constraints ?? { audio: true },
      );
    } catch {
      this.stream = null;
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