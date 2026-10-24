// M3：按需采样与拥塞替换（`T-M3-1`，RTM-VIS-05/08）。
//
// - 按需采样（建议初始 0.5–1fps）；用户指代/页面变化可强制采样；
// - 拥塞时**只替换未绑定的预览帧**；已绑定帧不在预览缓冲（不丢已绑定帧/工具事实）。

export interface SamplingOptions {
  intervalMs?: number;
  maxPreviews?: number;
}

const DEFAULT_INTERVAL_MS = 1000; // 1fps
const DEFAULT_MAX_PREVIEWS = 2;

export class SamplingThrottle {
  private lastCapturedMs = Number.NEGATIVE_INFINITY;

  constructor(private readonly intervalMs: number = DEFAULT_INTERVAL_MS) {
    if (intervalMs <= 0) {
      throw new Error("intervalMs must be positive");
    }
  }

  /** 到间隔才采样；`forced`（用户指代/页面变化）绕过间隔。 */
  shouldCapture(nowMs: number, forced = false): boolean {
    if (forced || nowMs - this.lastCapturedMs >= this.intervalMs) {
      this.lastCapturedMs = nowMs;
      return true;
    }
    return false;
  }

  reset(): void {
    this.lastCapturedMs = Number.NEGATIVE_INFINITY;
  }
}

export class PreviewBuffer {
  private readonly previews: string[] = [];

  constructor(private readonly maxPreviews: number = DEFAULT_MAX_PREVIEWS) {
    if (maxPreviews < 1) {
      throw new Error("maxPreviews must be >= 1");
    }
  }

  /**
   * 加入预览帧；超容量时**只淘汰最旧的未绑定预览**（`isBound` 判定；RET-04：
   * 已绑定帧永不淘汰）。全部已绑定 → 新预览不入环（`dropped:true`，不丢已绑定帧）。
   */
  add(frameId: string, isBound: (id: string) => boolean = () => false): {
    replaced: string | null;
    dropped: boolean;
  } {
    if (this.previews.includes(frameId)) {
      return { replaced: null, dropped: true };
    }
    if (this.previews.length >= this.maxPreviews) {
      const oldestUnbound = this.previews.findIndex((id) => !isBound(id));
      if (oldestUnbound === -1) {
        return { replaced: null, dropped: true }; // 满环且全绑定：宁可丢弃新预览
      }
      const [replaced] = this.previews.splice(oldestUnbound, 1);
      this.previews.push(frameId);
      return { replaced: replaced ?? null, dropped: false };
    }
    this.previews.push(frameId);
    return { replaced: null, dropped: false };
  }

  remove(frameId: string): boolean {
    const index = this.previews.indexOf(frameId);
    if (index === -1) {
      return false;
    }
    this.previews.splice(index, 1);
    return true;
  }

  takeLatest(): string | null {
    return this.previews.length === 0 ? null : this.previews[this.previews.length - 1];
  }

  size(): number {
    return this.previews.length;
  }

  clear(): void {
    this.previews.length = 0;
  }
}