// 预览版本观察器（对齐 DSH changes 流的 LFL 等价物）：
// 后端没有文件系统观察总线（DSH 是 fs/observed 仪器化事件），这里用有界的
// stat 轮询实现同一事实面——对已打开的预览文件按 size+mtime_ns 比较版本
// 指纹，变更/消失如实通知订阅者；观察失败（网络/5xx）不产生任何变更事实
// （不冒充 stale）。程序只报机械事实，是否重载由用户决定。
//
// 有界性：仅注册中的路径（= 当前挂载的预览 tab）；页面隐藏时暂停；
// 单飞（in-flight 去重）防止轮询堆叠。

export interface PreviewStatFacts {
  size: number;
  mtime_ns: number;
}

/** null = 文件已消失（absent）；非 null = 观察到的当前版本指纹 */
export type PreviewChangeListener = (facts: PreviewStatFacts | null) => void;

const POLL_INTERVAL_MS = 3000;

const listeners = new Map<string, Set<PreviewChangeListener>>();
let timer: number | null = null;
let inFlight = false;

function notify(path: string, facts: PreviewStatFacts | null): void {
  const set = listeners.get(path);
  if (!set) return;
  for (const cb of [...set]) cb(facts);
}

function ensureTimer(): void {
  if (timer === null && typeof window !== "undefined") {
    timer = window.setInterval(() => void previewWatcher.pollNow(), POLL_INTERVAL_MS);
  }
}

function maybeStopTimer(): void {
  if (listeners.size === 0 && timer !== null) {
    window.clearInterval(timer);
    timer = null;
  }
}

export const previewWatcher = {
  /** 注册一个路径的版本观察；返回注销函数（tab 卸载时调用） */
  register(path: string, cb: PreviewChangeListener): () => void {
    let set = listeners.get(path);
    if (!set) {
      set = new Set();
      listeners.set(path, set);
    }
    set.add(cb);
    ensureTimer();
    return () => {
      set.delete(cb);
      if (set.size === 0) listeners.delete(path);
      maybeStopTimer();
    };
  },
  /** 立即观察一轮（定时器内部调用；测试与手动刷新共用） */
  async pollNow(): Promise<void> {
    if (inFlight || listeners.size === 0) return;
    if (typeof document !== "undefined" && document.hidden) return;
    inFlight = true;
    try {
      await Promise.all(
        [...listeners.keys()].map(async (path) => {
          let resp: Response;
          try {
            resp = await fetch(`/api/v1/files/stat?path=${encodeURIComponent(path)}`);
          } catch {
            return; // 网络失败：不产生变更事实
          }
          if (resp.status === 404) {
            notify(path, null);
            return;
          }
          if (!resp.ok) return; // 观察失败：不冒充 stale
          const data: unknown = await resp.json().catch(() => null);
          if (
            data &&
            typeof (data as PreviewStatFacts).size === "number" &&
            typeof (data as PreviewStatFacts).mtime_ns === "number"
          ) {
            notify(path, {
              size: (data as PreviewStatFacts).size,
              mtime_ns: (data as PreviewStatFacts).mtime_ns,
            });
          }
        })
      );
    } finally {
      inFlight = false;
    }
  },
};
