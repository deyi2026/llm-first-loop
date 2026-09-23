// 会话头部任务列表（feature/webui-jobs-catalog-20260922，对齐 DSH JobListAction）：
// ⚡ 计数触发器（有 live 任务时带运行点）+ popover 行 =
// 状态点 · 执行器徽标 · 命令（等宽/省略/ title 全文）· 状态 · 时长（tabular-nums）。
// 状态语义对齐 DSH：stopping（终止请求中）与 killed 共用警示色——都是"按用户请求
// 结束"而非自然失败。面板只读；停止任务走右侧「后台任务」面板的显式 kill。
// 排序：live 在前按开始时间升序，settled 按结束时间降序（最新完成靠前）。

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { fetchSessionJobs, type JobFact } from "../../core/api";
import { useCapabilities } from "../../core/capabilities";
import { useConversation } from "../../core/conversation";
import { runAwareIntervalMs } from "../../core/runAwarePoll";
import { useCurrentSessionId } from "../../core/stores";
import { jobsZh as zh } from "../../i18n/zh";

type JobDotState = "ongoing" | "warning" | "done" | "error" | "idle";

// LFL 机械 state（含 cancel_requested）→ DSH 语义状态
export type JobDisplayStatus = "running" | "stopping" | "completed" | "killed" | "failed" | "orphaned";

export function jobDisplayStatus(job: JobFact): JobDisplayStatus {
  if (job.state === "running") return job.cancel_requested ? "stopping" : "running";
  if (job.state === "killed") return "killed";
  if (job.state === "failed") return "failed";
  if (job.state === "orphaned") return "orphaned";
  return "completed";
}

export function isLiveStatus(status: JobDisplayStatus): boolean {
  return status === "running" || status === "stopping";
}

function dotState(status: JobDisplayStatus): JobDotState {
  switch (status) {
    case "running":
      return "ongoing";
    case "stopping":
      return "warning";
    case "completed":
      return "done";
    case "killed":
      return "warning";
    case "failed":
      return "error";
    default:
      return "idle";
  }
}

export function jobStatusLabel(status: JobDisplayStatus): string {
  switch (status) {
    case "running":
      return zh.statusRunning;
    case "stopping":
      return zh.statusStopping;
    case "completed":
      return zh.statusCompleted;
    case "killed":
      return zh.statusKilled;
    case "failed":
      return zh.statusFailed;
    default:
      return zh.statusOrphaned;
  }
}

// 至多两个相邻单位（对齐 DSH formatDuration；小时为最大单位）
export function formatJobDuration(elapsedMs: number): string {
  const total = Math.max(0, Math.floor(elapsedMs / 1000));
  const seconds = total % 60;
  const minutes = Math.floor(total / 60) % 60;
  const hours = Math.floor(total / 3600);
  if (hours > 0) return zh.durationHours(hours, minutes);
  if (minutes > 0) return zh.durationMinutes(minutes, seconds);
  return zh.durationSeconds(seconds);
}

// live 在前按开始时间升序；settled 按结束时间降序（对齐 DSH ordered）
export function orderJobs(jobs: JobFact[]): JobFact[] {
  return [...jobs].sort((left, right) => {
    const leftLive = isLiveStatus(jobDisplayStatus(left));
    const rightLive = isLiveStatus(jobDisplayStatus(right));
    if (leftLive !== rightLive) return leftLive ? -1 : 1;
    const leftStart = left.started_at ?? 0;
    const rightStart = right.started_at ?? 0;
    if (leftLive) return leftStart - rightStart;
    const finished = (right.finished_at ?? right.started_at ?? 0) - (left.finished_at ?? left.started_at ?? 0);
    return finished !== 0 ? finished : leftStart - rightStart;
  });
}

export function JobsCatalog() {
  const caps = useCapabilities();
  const _conv = useConversation();
  const runBusy = Boolean(_conv.streaming || _conv.backgroundRunning);
  const sessionId = useCurrentSessionId();
  const [jobs, setJobs] = useState<JobFact[]>([]);
  const [open, setOpen] = useState(false);
  const [now, setNow] = useState(() => Date.now());
  const rootRef = useRef<HTMLDivElement | null>(null);
  const activeSession = useRef(sessionId);
  activeSession.current = sessionId;

  const load = useCallback(async () => {
    const sid = activeSession.current;
    if (!sid) {
      setJobs([]);
      return;
    }
    const next = await fetchSessionJobs(sid);
    if (activeSession.current === sid) setJobs(next);
  }, []);

  // 发现轮询：空则隐藏 trigger，仍需发现新任务
  useEffect(() => {
    if (!caps.jobs) return;
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
  }, [caps.jobs, sessionId, load]);

  const liveCount = useMemo(
    () => jobs.filter((job) => isLiveStatus(jobDisplayStatus(job))).length,
    [jobs]
  );

  // 打开且有 live 任务时 1s 心跳驱动时长（对齐 DSH）
  useEffect(() => {
    if (!open || liveCount === 0) return;
    setNow(Date.now());
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [open, liveCount]);

  useEffect(() => {
    if (jobs.length === 0 && open) setOpen(false);
  }, [jobs.length, open]);

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

  const rows = useMemo(() => orderJobs(jobs), [jobs]);

  if (!caps.jobs || jobs.length === 0) return null;

  const countLabel = liveCount > 0 ? zh.countLive(liveCount) : zh.countIdle(jobs.length);

  const onKeyDown = (event: React.KeyboardEvent) => {
    if (event.key !== "Escape" || !open) return;
    event.preventDefault();
    setOpen(false);
  };

  return (
    <div className="v2-catalog" ref={rootRef} onKeyDown={onKeyDown} data-testid="jobs-catalog">
      <button
        type="button"
        className="v2-catalog-trigger"
        aria-expanded={open}
        aria-label={countLabel}
        onClick={() => {
          setNow(Date.now());
          setOpen((v) => !v);
        }}
        data-testid="jobs-catalog-trigger"
      >
        {liveCount > 0 ? <span className="v2-catalog-livedot ongoing" aria-hidden="true" /> : null}
        <span>{countLabel}</span>
        <span className={`v2-catalog-caret ${open ? "open" : ""}`} aria-hidden="true">▾</span>
      </button>
      {open && (
        <ul className="v2-catalog-menu jobs" aria-label={zh.listAria} data-testid="jobs-catalog-menu">
          {rows.map((job) => {
            const status = jobDisplayStatus(job);
            const live = isLiveStatus(status);
            const startedAt = job.started_at ?? null;
            const finishedAt = job.finished_at ?? null;
            const duration =
              startedAt != null
                ? formatJobDuration((live ? now : (finishedAt ?? startedAt) * 1000) - startedAt * 1000)
                : null;
            return (
              <li
                key={job.job_id}
                className={`v2-jobs-row ${live ? "" : "settled"}`}
                data-testid="jobs-catalog-row"
              >
                <span className={`v2-catalog-livedot ${dotState(status)}`} aria-hidden="true" />
                <span className="v2-jobs-kind">{job.executor || "external"}</span>
                <span className="v2-jobs-label" title={job.command || job.job_id}>
                  {job.command || job.job_id}
                </span>
                <span className="v2-jobs-status">{jobStatusLabel(status)}</span>
                <span
                  className="v2-jobs-duration"
                  title={
                    duration
                      ? live
                        ? zh.durationTitleLive(duration)
                        : zh.durationTitleDone(duration)
                      : undefined
                  }
                >
                  {duration ?? "—"}
                </span>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
