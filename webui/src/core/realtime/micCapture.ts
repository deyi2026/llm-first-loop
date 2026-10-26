// M1：麦克风采集 DOM 接线（`T-M1-9`）：`getUserMedia` + `AudioWorklet` → 16k PCM16 帧。
//
// 语义（RTM-AUD-01/03/06、CAP-14）：
// - **按下开始采集、松开结束输入**；允许松开后完成识别与提交（服务端 `AwaitingFinal`）；
// - **失焦 / 触摸取消**：结束输入（`onBlur`）或取消本轮（`cancel`）；
// - 设备/权限失败**如实返回失败**，不伪造采集；
// - `getUserMedia` 有 10s 有界超时（浏览器层挂起时 `press()` 不得永久 pending）；
//   超时返回 false 并经 `onNotice` 可见提示；迟到的 stream 释放轨道防泄漏；
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

/** getUserMedia 有界超时（M3 后续：浏览器层挂起时的反饨上限）。 */
const GUM_TIMEOUT_MS = 10_000;
const GUM_TIMEOUT_ERROR = "getUsermedia_start_timeout";

export interface MicCaptureOptions {
  mediaDevices: MediaDevicesLike;
  pipeline: CapturePipeline;
  onFrame: (frame: Int16Array) => void;
  createPort: () => WorkletPortLike;
  constraints?: { audio: unknown };
  /** M3 后续：可见降级提示（如启动超时）；可选注入。 */
  onNotice?: (message: string) => void;
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

  /** 按下说话：开始采集。返回是否真正开始（权限/设备失败/启动超时 → false，不伪造）。 */
  async press(): Promise<boolean> {
    if (this.stream !== null) {
      this.pressed = true;
      return true;
    }
    try {
      this.stream = await this.acquireStream();
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

  /**
   * 获取采集流：`getUserMedia` 加 10s 有界超时（Promise.race）。
   * 浏览器层挂起（如 CDP audioCapture 环境）时该调用可能永远
   * pending，`press()` 无反馈。超时：经既有 `onNotice` 路径可见提示；
   * 迟到的 stream 释放全部轨道防泄漏，迟到的拒绝静默。权限/设备
   * 拒绝与正常 resolve 路径零变化。
   */
  private async acquireStream(): Promise<MediaStreamLike> {
    const request = this.options.mediaDevices.getUserMedia(
      this.options.constraints ?? { audio: true },
    );
    let timer: ReturnType<typeof setTimeout> | null = null;
    const timeout = new Promise<never>((_, reject) => {
      timer = setTimeout(() => reject(new Error(GUM_TIMEOUT_ERROR)), GUM_TIMEOUT_MS);
    });
    try {
      return await Promise.race([request, timeout]);
    } catch (error) {
      if (error instanceof Error && error.message === GUM_TIMEOUT_ERROR) {
        this.options.onNotice?.("麦克风启动超时，请检查权限/设备后重试");
      }
      // 请求仍可能迟到完成：resolve 则释放全部轨道（已获得的麦克风不得泄漏），
      // reject 则静默（不再产生未处理拒绝）。
      void request.then(
        (stream) => {
          for (const track of stream.getTracks()) {
            track.stop();
          }
        },
        () => undefined,
      );
      throw error;
    } finally {
      if (timer !== null) {
        clearTimeout(timer);
      }
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