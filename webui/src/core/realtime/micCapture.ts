// M1：麦克风采集 DOM 接线（`T-M1-9`）：`getUserMedia` + `AudioWorklet` → 16k PCM16 帧。
//
// 语义（RTM-AUD-01/03/06、CAP-14）：
// - **按下开始采集、松开结束输入**；允许松开后完成识别与提交（服务端 `AwaitingFinal`）；
// - **失焦 / 触摸取消**：结束输入（`onBlur`）或取消本轮（`cancel`）；
// - 设备/权限失败**如实返回失败**，不伪造采集；
// - `getUserMedia` 有 10s 有界超时（浏览器层挂起时 `press()` 不得永久 pending）；
//   超时返回 false 并经 `onNotice` 可见提示；迟到的 stream 释放轨道防泄漏；
// - port 创建失败（worklet 加载失败等）同样**如实失败**：释放本轮全部轨道、置
//   `lastError="port-init"`、`press()` 返回 false（不静默、不留半装配状态）；
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
  /**
   * worklet 端口工厂：在 `getUserMedia` 成功后收到本轮采集流（真实装配为
   * `createBrowserCapturePort`，允许异步——worklet `addModule` 是 Promise）。
   * 未注入时回退**空 port**（jsdom 无音频栈也能驱动接线逻辑，既有测试依赖）。
   */
  createPort?: (stream: MediaStreamLike) => WorkletPortLike | Promise<WorkletPortLike>;
  constraints?: { audio: unknown };
  /** M3 后续：可见降级提示（如启动超时）；可选注入。 */
  onNotice?: (message: string) => void;
}

/** 按下说话失败原因分类（供上层给出可操作的提示文案）。 */
export type MicPressErrorKind = "not-allowed" | "not-found" | "not-readable" | "port-init" | "unknown";

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

/** 默认空 port：无音频栈环境（jsdom）的回退——不产帧、close 幂等，接线逻辑仍可驱动。 */
function createEmptyPort(): WorkletPortLike {
  return { onmessage: null, close: () => undefined };
}

export class MicCapture {
  private stream: MediaStreamLike | null = null;
  private port: WorkletPortLike | null = null;
  private pressed = false;
  private lastError: MicPressErrorKind | null = null;
  /**
   * 迟到守卫（沿用视觉共享 P2-9c「await 后复查」模式）：press 递增取号，
   * release/cancel 再递增使在途 press 作废——getUserMedia/createPort 两个 await
   * 窗口内被松开的轮次，迟到的流/port 一律丢弃并释放，不悬挂、不复活。
   */
  private pressGeneration = 0;

  constructor(private readonly options: MicCaptureOptions) {}

  get micEnabled(): boolean {
    return this.stream !== null;
  }

  get pressedDown(): boolean {
    return this.pressed;
  }

  /** 按下说话失败原因分类（供上层给出可操作的提示文案）。 */
  get pressError(): MicPressErrorKind | null { return this.lastError; }

  /** 按下说话：开始采集。返回是否真正开始（权限/设备失败/启动超时/port 创建失败 → false，不伪造）。 */
  async press(): Promise<boolean> {
    const generation = ++this.pressGeneration;
    this.lastError = null;
    if (this.stream !== null) {
      this.pressed = true;
      return true;
    }
    let stream: MediaStreamLike;
    try {
      stream = await this.acquireStream();
    } catch (error) {
      if (generation !== this.pressGeneration) {
        return false; // 迟到失败：本轮已被 release/cancel/新 press 取代，不改写他人状态
      }
      this.lastError = classifyPressError(error);
      this.stream = null;
      return false;
    }
    if (generation !== this.pressGeneration) {
      // 迟到流：getUserMedia 等待期间已 release/cancel → 本轮作废，轨道立即释放
      this.releaseTracks(stream);
      return false;
    }
    this.stream = stream;
    try {
      const port = await (this.options.createPort?.(stream) ?? createEmptyPort());
      if (generation !== this.pressGeneration) {
        // 迟到 port：装配等待期间已 release/cancel（stopStream 已停轨清流）→ 不接线，
        // port 立即关闭防泄漏（AudioContext/worklet 不得残留）。
        port.close();
        return false;
      }
      port.onmessage = (event): void => this.handleSamples(event.data);
      this.port = port;
      this.pressed = true;
      return true;
    } catch {
      // port 创建失败（worklet 加载失败等）：释放本轮全部轨道、如实置失败分类，
      // 绝不静默伪造采集（上层据此给可见提示）。
      if (generation === this.pressGeneration) {
        this.releaseTracks(stream);
        this.stream = null;
        this.lastError = "port-init";
      }
      return false;
    }
  }

  /** 松开：结束输入（停止采集）；余量 flush 发出，不丢尾段。 */
  release(): void {
    this.pressGeneration += 1; // 在途 press 的迟到流/port 一并作废
    this.pressed = false;
    this.stopStream();
    for (const frame of this.options.pipeline.flush()) {
      this.options.onFrame(frame);
    }
  }

  /** 触摸取消：结束输入且**丢弃**当前余量。 */
  cancel(): void {
    this.pressGeneration += 1; // 同 release：在途 press 作废
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

  private releaseTracks(stream: MediaStreamLike): void {
    for (const track of stream.getTracks()) {
      track.stop();
    }
  }

  private stopStream(): void {
    if (this.port !== null) {
      this.port.onmessage = null;
      this.port.close();
      this.port = null;
    }
    if (this.stream !== null) {
      this.releaseTracks(this.stream);
      this.stream = null;
    }
  }
}
