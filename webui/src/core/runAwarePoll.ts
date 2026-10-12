/** run 期间轮询降频（2026-09-23 CPU #2）.

 * 当前会话流式/后台运行时，服务端发现类轮询（schedule/jobs/lineage）
 * 间隔 ×4——SSE 流本身已在推送实时事实，发现类轮询只需降频保底。
 * 页面不可见跳过的既有语义由调用方回调内保留，本钩子不重复。
 */
import { useEffect } from "react";
import { useConversation } from "./conversation";

/** 纯函数：busy 时 baseMs ×4（run 期间 5s→20s）。 */
export function runAwareIntervalMs(baseMs: number, busy: boolean): number {
  return busy ? baseMs * 4 : baseMs;
}

/** 会话 run 感知的轮询间隔（cb 需稳定引用；busy 变化时自动重排 interval）。 */
export function useRunAwareInterval(cb: () => void, baseMs: number): void {
  const conv = useConversation();
  const busy = Boolean(conv.streaming || conv.backgroundRunning);
  useEffect(() => {
    const t = window.setInterval(cb, runAwareIntervalMs(baseMs, busy));
    return () => window.clearInterval(t);
  }, [cb, baseMs, busy]);
}
