// M3：屏幕来源共享（`T-M3-1`）：仅采集**用户选定来源**（`getDisplayMedia`）。
//
// 语义（RTM-VIS-01/02/03、SES-04）：
// - 仅采集用户手势选定的来源；**不采集未共享来源 / 任意外部标签页 DOM**；
// - 用户取消选择 → 如实返回失败（不切到其它来源）；
// - **共享停止 / 来源变化 → `source_epoch` 变化**（当前画面失效，证据保留由服务端承担）；
// - 设备依赖注入，jsdom 下可用 fake 验证接线；真实共享不在此验证（RTM-EVD-06）。

export interface VideoTrackLike {
  stop(): void;
}

export interface DisplayStreamLike {
  getVideoTracks(): VideoTrackLike[];
  getTracks(): VideoTrackLike[];
}

export interface DisplayMediaConstraints {
  video: unknown;
  audio?: boolean;
}

export interface DisplayMediaDevicesLike {
  getDisplayMedia(constraints: DisplayMediaConstraints): Promise<DisplayStreamLike>;
}

export interface ScreenShareOptions {
  video?: unknown;
  /** M3 上送画面不带共享音频（契约：`getDisplayMedia({video:true,audio:false})`）。 */
  audio?: boolean;
}

export class ScreenShareSession {
  private stream: DisplayStreamLike | null = null;
  private epoch = 0;
  private sourceIdentifier: string | null = null;
  private readonly endedListeners: (() => void)[] = [];

  constructor(
    private readonly devices: DisplayMediaDevicesLike,
    private readonly options: ScreenShareOptions = {},
  ) {}

  get active(): boolean {
    return this.stream !== null;
  }

  get sourceEpoch(): number {
    return this.epoch;
  }

  get sourceId(): string | null {
    return this.sourceIdentifier;
  }

  onEnded(listener: () => void): void {
    this.endedListeners.push(listener);
  }

  /** 用户手势发起选择；取消/不可用 → false（不切换到其它来源）。 */
  async start(sourceIdentifier = "display-1"): Promise<boolean> {
    if (this.stream !== null) {
      return false;
    }
    const constraints: DisplayMediaConstraints =
      this.options.audio !== undefined
        ? { video: this.options.video ?? true, audio: this.options.audio }
        : this.options.video !== undefined
          ? { video: this.options.video }
          : { video: true };
    try {
      this.stream = await this.devices.getDisplayMedia(constraints);
    } catch {
      this.stream = null;
      return false;
    }
    this.sourceIdentifier = sourceIdentifier;
    this.epoch += 1;
    return true;
  }

  /** 停止共享（用户点击浏览器「停止共享」或主动结束）：代次变化，通知失效。 */
  stop(): number {
    if (this.stream === null) {
      return this.epoch;
    }
    for (const track of this.stream.getTracks()) {
      track.stop();
    }
    this.stream = null;
    this.sourceIdentifier = null;
    this.epoch += 1;
    for (const listener of this.endedListeners) {
      listener();
    }
    return this.epoch;
  }

  /** 当前流（供抓帧器读取；仅活动时非空）。 */
  get currentStream(): DisplayStreamLike | null {
    return this.stream;
  }
}

/** 共享入口能力探测环境（测试可注入；缺省读浏览器事实）。 */
export interface ScreenShareCapabilityEnv {
  getDisplayMedia?: unknown;
  userAgent?: string;
  maxTouchPoints?: number;
  matchMedia?: (query: string) => { matches: boolean };
}

const MOBILE_UA = /Android|iPhone|iPad|Mobile/i;

/**
 * 共享画面入口能力检测（`T-M3-3`，RTM-A11Y-01/02、CAP-03/08）：
 * - 无 `getDisplayMedia` → 不显示共享按钮（展示文字/截图降级提示，不声称支持）；
 * - 移动端 UA / 触控主导（无精确指针）→ 同样隐藏（屏幕共享为桌面能力，未实测前不承诺）。
 */
export function detectScreenShareSupport(env: ScreenShareCapabilityEnv = {}): boolean {
  const getDisplayMedia =
    env.getDisplayMedia ??
    (typeof navigator !== "undefined"
      ? (navigator as unknown as { mediaDevices?: { getDisplayMedia?: unknown } }).mediaDevices?.getDisplayMedia
      : undefined);
  if (typeof getDisplayMedia !== "function") {
    return false;
  }
  const userAgent =
    env.userAgent ?? (typeof navigator !== "undefined" ? navigator.userAgent : "");
  if (MOBILE_UA.test(userAgent)) {
    return false;
  }
  const matchMedia = env.matchMedia ?? (typeof window !== "undefined" ? window.matchMedia : undefined);
  if (typeof matchMedia === "function") {
    if (matchMedia("(pointer: fine)").matches !== true) {
      return false; // 明确非精确指针（触控主导）→ 不显示共享入口
    }
  } else {
    // matchMedia 不可用（如 jsdom）：退回 maxTouchPoints 判定
    const maxTouchPoints =
      env.maxTouchPoints ?? (typeof navigator !== "undefined" ? navigator.maxTouchPoints ?? 0 : 0);
    if (maxTouchPoints > 0) {
      return false;
    }
  }
  return true;
}