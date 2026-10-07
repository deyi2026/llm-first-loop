// 安排目录（feature/webui-schedule-catalog-20260922，对齐 DSH ScheduleCatalogAction）：
// 会话头部紧凑入口：⏰ + "N 个提醒"；popover 行 = 状态点 + 提醒内容 +
// 频率 · 本地时间 · 相对时间；逾期行 warn 高亮且排最前；打开时 1s 心跳驱动相对时间。
// 数据是只读机械事实投影（/api/v1/sessions/{sid}/schedule，与 schedule 工具同一
// schedule.json 事实源）；overdue 由前端用 trigger_at 与本地时钟计算，后端不派生语义。
// 取消是显式用户动作（对齐 jobs kill 的产品语言；DSH 目录本身只读）。

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  cancelSessionScheduleItem,
  fetchSessionScheduleResult,
  type ScheduleItem,
} from "../../core/api";
import { useCapabilities } from "../../core/capabilities";
import { useConversation } from "../../core/conversation";
import { runAwareIntervalMs } from "../../core/runAwarePoll";
import { useCurrentSessionId } from "../../core/stores";
import { scheduleZh as zh } from "../../i18n/zh";

const UNIT_SECONDS: ReadonlyArray<readonly [ScheduleUnit, number]> = [
  ["day", 86400],
  ["hour", 3600],
  ["minute", 60],
  ["second", 1],
];

type ScheduleUnit = "day" | "hour" | "minute" | "second";

function unitLabel(unit: ScheduleUnit): string {
  if (unit === "day") return zh.unitDay;
  if (unit === "hour") return zh.unitHour;
  if (unit === "minute") return zh.unitMinute;
  return zh.unitSecond;
}

// 挑能整除 everySeconds 的最大自然单位（对齐 DSH formatScheduleFrequency）
function formatFrequency(item: ScheduleItem): string {
  if (item.kind !== "every" || !item.every_seconds) return zh.frequencyOnce;
  let selected: readonly [ScheduleUnit, number] = ["second", 1];
  for (const candidate of UNIT_SECONDS) {
    if (item.every_seconds % candidate[1] !== 0) continue;
    selected = candidate;
    break;
  }
  const value = item.every_seconds / selected[1];
  return zh.frequencyEvery(value, unitLabel(selected[0]));
}

function scheduleStatus(item: ScheduleItem, overdue: boolean): string {
  if (item.delivery_state === "waiting_human") return zh.statusWaitingAuthorization;
  if (item.delivery_state === "queued") return zh.statusWaitingRun;
  if (item.delivery_state === "started") return zh.statusStarted;
  if (item.delivery_state === "inactive") return zh.statusInactive;
  if (item.delivery_state === "retrying") {
    if (item.wait_reason === "session_busy") return zh.statusWaitingIdle;
    if (item.wait_reason === "service_restart_barrier") return zh.statusWaitingRestart;
    return zh.statusRetrying;
  }
  return overdue ? zh.statusOverdue : zh.statusScheduled;
}

function formatLocalTime(epochS: number): string {
  return new Intl.DateTimeFormat("zh-CN", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(epochS * 1000));
}

// 相对时间：未来 ceil、过去 floor（对齐 DSH formatScheduleRelative）
function formatRelative(epochS: number, nowMs: number): string {
  const difference = epochS * 1000 - nowMs;
  if (difference === 0) return zh.relativeNow;
  const absoluteSeconds = Math.abs(difference) / 1000;
  const selected =
    UNIT_SECONDS.find(([, seconds]) => absoluteSeconds >= seconds) ??
    (["second", 1] as const);
  const value = Math.max(
    1,
    difference > 0
      ? Math.ceil(absoluteSeconds / selected[1])
      : Math.floor(absoluteSeconds / selected[1])
  );
  const text = `${value} ${unitLabel(selected[0])}`;
  return difference > 0 ? zh.relativeFuture(text) : zh.relativeOverdue(text);
}

// 逾期优先，再按目标时间升序（对齐 DSH orderScheduleRecords）
export function orderScheduleItems(items: ScheduleItem[], nowMs: number): ScheduleItem[] {
  return [...items].sort((left, right) => {
    const leftOverdue = left.trigger_at * 1000 <= nowMs;
    const rightOverdue = right.trigger_at * 1000 <= nowMs;
    if (leftOverdue !== rightOverdue) return rightOverdue ? 1 : -1;
    return left.trigger_at - right.trigger_at;
  });
}

export function ScheduleCatalog() {
  const caps = useCapabilities();
  const _conv = useConversation();
  const runBusy = Boolean(_conv.streaming || _conv.backgroundRunning);
  const sessionId = useCurrentSessionId();
  const [items, setItems] = useState<ScheduleItem[]>([]);
  const [open, setOpen] = useState(false);
  const [now, setNow] = useState(() => Date.now());
  const [busySid, setBusySid] = useState<string | null>(null);
  const [error, setError] = useState("");
  const rootRef = useRef<HTMLDivElement | null>(null);
  const activeSession = useRef(sessionId);
  activeSession.current = sessionId;

  const load = useCallback(async () => {
    const sid = activeSession.current;
    if (!sid) {
      setItems([]);
      setError("");
      return;
    }
    const result = await fetchSessionScheduleResult(sid);
    if (activeSession.current !== sid) return;
    if (!result.ok) {
      setError("提醒状态读取失败；当前显示上次已知结果。");
      return;
    }
    setError("");
    setItems(result.items);
  }, []);

  // 发现轮询：能力可用即拉（trigger 空则隐藏，仍需发现新增提醒）
  useEffect(() => {
    if (!caps.schedule) return;
    void load();
    const timer = window.setInterval(() => {
      if (!document.hidden) void load();
    }, runAwareIntervalMs(5000, runBusy));
    const onVisible = () => {
      if (!document.hidden) void load();
    };
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      window.clearInterval(timer);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [caps.schedule, sessionId, load]);

  // 打开时 1s 心跳驱动相对时间（对齐 DSH）
  useEffect(() => {
    if (!open) return;
    setNow(Date.now());
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [open]);

  // 空态自动收起（对齐 DSH：不可见或空时收起）
  useEffect(() => {
    if (items.length === 0 && open) setOpen(false);
  }, [items.length, open]);

  // 外部点击关闭
  useEffect(() => {
    if (!open) return;
    const onPointerDown = (event: PointerEvent) => {
      if (rootRef.current && !rootRef.current.contains(event.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener("pointerdown", onPointerDown);
    return () => document.removeEventListener("pointerdown", onPointerDown);
  }, [open]);

  const rows = useMemo(() => orderScheduleItems(items, now), [items, now]);

  if (!caps.schedule || items.length === 0) return null;

  const cancel = async (sid: string) => {
    const currentSession = activeSession.current;
    if (!currentSession || busySid) return;
    setBusySid(sid);
    setError("");
    const result = await cancelSessionScheduleItem(currentSession, sid);
    if (!result.ok) setError(result.detail || zh.cancelFailed);
    await load();
    setBusySid(null);
  };

  const onKeyDown = (event: React.KeyboardEvent) => {
    if (event.key !== "Escape" || !open) return;
    event.preventDefault();
    setOpen(false);
  };

  return (
    <div className="v2-catalog" ref={rootRef} onKeyDown={onKeyDown} data-testid="schedule-catalog">
      <button
        type="button"
        className="v2-catalog-trigger"
        aria-expanded={open}
        aria-label={zh.trigger(items.length)}
        onClick={() => {
          setNow(Date.now());
          setOpen((v) => !v);
        }}
        data-testid="schedule-catalog-trigger"
      >
        <span className="v2-catalog-icon" aria-hidden="true">⏰</span>
        <span>{zh.trigger(items.length)}</span>
        <span className={`v2-catalog-caret ${open ? "open" : ""}`} aria-hidden="true">▾</span>
      </button>
      {open && (
        <ul className="v2-catalog-menu" aria-label={zh.listAria} data-testid="schedule-catalog-menu">
          {rows.map((item) => {
            const overdue = item.trigger_at * 1000 <= now;
            return (
              <li
                key={item.sid}
                className={`v2-catalog-row ${overdue ? "overdue" : ""}`}
                data-testid="schedule-catalog-row"
              >
                <span className="v2-catalog-status">
                  <span className="v2-catalog-dot" aria-hidden="true" />
                  <span>{scheduleStatus(item, overdue)}</span>
                </span>
                <span className="v2-catalog-prompt" title={item.message}>
                  {item.message}
                </span>
                <span className="v2-catalog-metadata">
                  <span>{formatFrequency(item)}</span>
                  <span aria-hidden="true">·</span>
                  <span>{formatLocalTime(item.scheduled_trigger_at ?? item.trigger_at)}</span>
                  {item.scheduled_trigger_at && item.scheduled_trigger_at !== item.trigger_at ? (
                    <span>{zh.nextAttempt} {formatLocalTime(item.trigger_at)}</span>
                  ) : null}
                  <span aria-hidden="true">·</span>
                  <span className={overdue ? "v2-catalog-relative-overdue" : ""}>
                    {formatRelative(item.trigger_at, now)}
                  </span>
                  {item.wake ? <span className="v2-catalog-wake">{zh.wakeBadge}</span> : null}
                </span>
                <button
                  type="button"
                  className="v2-catalog-cancel"
                  disabled={busySid === item.sid}
                  title={zh.cancel}
                  onClick={() => void cancel(item.sid)}
                  data-testid="schedule-catalog-cancel"
                >
                  {busySid === item.sid ? "…" : "✕"}
                </button>
              </li>
            );
          })}
          {error ? (
            <li className="v2-catalog-error" role="status">
              {error}
            </li>
          ) : null}
        </ul>
      )}
    </div>
  );
}
