import { useEffect, useState } from "react";

import {
  fetchLearningStatus,
  type LearningJobInfo,
  type LearningStatusInfo,
} from "../../core/api";

function localTime(ts?: number | null): string {
  if (!ts) return "—";
  try {
    return new Date(ts * 1000).toLocaleString();
  } catch {
    return "—";
  }
}

function durationLabel(seconds?: number | null): string {
  if (seconds == null || !Number.isFinite(seconds)) return "—";
  const s = Math.max(0, Math.round(seconds));
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m${s % 60 ? `${s % 60}s` : ""}`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h${m % 60 ? `${m % 60}m` : ""}`;
  return `${Math.floor(h / 24)}d${h % 24 ? `${h % 24}h` : ""}`;
}

const ADMISSION_REASON_LABELS: Record<string, string> = {
  foreground_busy: "前台会话占用（learning 让位）",
  quiet_window: "静默期未过",
  straggler_draining: "遗留任务排空中",
  governor_or_transport: "资源治理未放行",
};

const REQUEUE_REASON_LABELS: Record<string, string> = {
  resource_authority_changed: "资源权威变更重入队",
  preempted_by_foreground: "被前台抢占",
  foreground_arrived: "前台到达",
  service_restart_barrier: "服务重启屏障",
};

function admissionReasonLabel(reason?: string | null): string {
  if (!reason) return "—";
  if (ADMISSION_REASON_LABELS[reason]) return ADMISSION_REASON_LABELS[reason];
  if (reason.startsWith("service_barrier:")) return `服务重启屏障：${reason.slice("service_barrier:".length)}`;
  return reason;
}

function requeueReasonLabel(reason: string): string {
  return REQUEUE_REASON_LABELS[reason] ?? reason;
}

function stateLabel(state: string): string {
  const labels: Record<string, string> = {
    queued: "排队",
    admitted: "已准入",
    started: "学习中",
    saved: "已生成 Method",
    none: "无候选",
    failed: "失败",
    cancelled: "已取消",
  };
  return labels[state] ?? state;
}

// EVO-20261013-2: candidate_ref 不只指向 method（memory-extract 等也走 saved），
// 按前缀如实标注产物类型，不再一律写 "Method candidate"。
function refLabel(ref: string): string {
  if (ref.startsWith("method:")) return "Method candidate";
  if (ref.startsWith("memory-extract:")) return "记忆抽取产物";
  if (ref.startsWith("experience:")) return "经验条目";
  return "产物引用";
}

function JobCard({ job }: { job: LearningJobInfo }) {
  const facts = job.trigger_facts ?? {};
  return (
    <article className="v2-learning-job" data-testid="learning-job">
      <div className="v2-learning-job-head">
        <strong>{stateLabel(job.state)}</strong>
        <span className={`v2-learning-state ${job.state}`}>{job.state}</span>
      </div>
      <div className="v2-learning-grid">
        <span>Job</span><code>{job.job_id}</code>
        <span>来源 Episode</span><code>{job.source_episode_ref || "—"}</code>
        <span>来源 Session</span><code>{job.source_session_id || "—"}</code>
        <span>模型</span><code>{job.source_model || "—"}</code>
        <span>Attempt</span><span>{job.attempt}</span>
        <span>开始</span><span>{localTime(job.started_at ?? job.created_at)}</span>
        <span>完成</span><span>{localTime(job.finished_at)}</span>
      </div>
      {job.candidate_ref ? (
        <div className="v2-learning-result">
          <span>{refLabel(job.candidate_ref)}</span><code>{job.candidate_ref}</code>
        </div>
      ) : null}
      {job.reason ? <div className="v2-learning-reason">{job.reason}</div> : null}
      {Object.keys(facts).length > 0 ? (
        <details className="v2-learning-facts">
          <summary>机械触发事实</summary>
          <pre>{JSON.stringify(facts, null, 2)}</pre>
        </details>
      ) : null}
    </article>
  );
}

export function LearningPanel() {
  const [status, setStatus] = useState<LearningStatusInfo | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let mounted = true;
    const refresh = async () => {
      const next = await fetchLearningStatus(80);
      if (!mounted) return;
      setStatus(next);
      setLoading(false);
    };
    void refresh();
    const timer = window.setInterval(() => void refresh(), 5000);
    return () => {
      mounted = false;
      window.clearInterval(timer);
    };
  }, []);

  if (loading) {
    return <main className="v2-learning-panel"><div className="v2-learning-empty">读取学习通道…</div></main>;
  }
  if (!status) {
    return <main className="v2-learning-panel"><div className="v2-learning-empty">学习通道状态暂不可用</div></main>;
  }

  const worker = status.worker ?? {};
  const oldest = status.oldest_queued ?? null;
  const admission = status.admission ?? null;
  const requeue = status.requeue_stats ?? null;
  const admissionState = admission?.present ? (admission.stale ? "stale" : admission.state ?? "unknown") : "absent";
  const admissionStateLabel: Record<string, string> = {
    draining: "排水中",
    idle: "空闲（无排队）",
    blocked: "阻塞",
    stale: "心跳过期（worker 存活但未刷新）",
    absent: "无心跳",
    unknown: "未知",
  };
  const topRequeueReasons = requeue
    ? Object.entries(requeue.total)
        .sort((a, b) => b[1] - a[1])
        .slice(0, 4)
    : [];
  return (
    <main className="v2-learning-panel" data-testid="learning-panel">
      <header className="v2-learning-header">
        <div>
          <h2>🧠 学习通道</h2>
          <p>独立 Learning Plane · Episode → Reflection → Method candidate</p>
        </div>
        <span className={`v2-learning-worker ${worker.running ? "running" : "stopped"}`}>
          {worker.running ? "● Worker 运行中" : "○ Worker 未运行"}
        </span>
      </header>
      <section className="v2-learning-summary">
        <div><span>模型</span><strong>{worker.model_ref || "—"}</strong></div>
        <div title="全 journal 口径：当前排队中的任务总数"><span>排队</span><strong>{status.counts.queued ?? 0}</strong></div>
        <div><span>学习中</span><strong>{status.counts.started ?? 0}</strong></div>
        <div><span>已生成</span><strong>{status.counts.saved ?? 0}</strong></div>
        <div><span>失败</span><strong>{status.counts.failed ?? 0}</strong></div>
      </section>
      {status.observability_errors?.length ? (
        <div className="v2-learning-reason" data-testid="journal-error">
          ⚠ journal 读取部分失败（{status.observability_errors.join("、")}）：上方数字/任务列表可能缺失，与正常状态不同
        </div>
      ) : null}
      <section className="v2-learning-backpressure" data-testid="learning-backpressure">
        <div className="v2-learning-bp-row">
          <div className="v2-learning-bp-item">
            <span className="v2-learning-bp-label">最老排队等待</span>
            <strong className={oldest && oldest.wait_seconds > 3600 ? "warn" : ""}>
              {oldest ? durationLabel(oldest.wait_seconds) : "—"}
            </strong>
            {oldest ? (
              <code className="v2-learning-bp-sub">
                {oldest.job_id} · {localTime(oldest.created_at)} 入队
              </code>
            ) : (
              <span className="v2-learning-bp-sub">无排队任务</span>
            )}
          </div>
          <div className="v2-learning-bp-item">
            <span className="v2-learning-bp-label">准入状态</span>
            <strong
              className={
                admissionState === "blocked"
                  ? "bad"
                  : admissionState === "draining"
                    ? "good"
                    : admissionState === "stale"
                      ? "warn"
                      : ""
              }
            >
              {admissionStateLabel[admissionState] ?? admissionState}
            </strong>
            {admission?.present ? (
              <span className="v2-learning-bp-sub">
                {admissionState === "blocked"
                  ? admissionReasonLabel(admission.reason)
                  : admission.queued != null
                    ? `心跳 ${admission.age_seconds ?? 0}s 前 · 在队 ${admission.queued}（心跳时点口径）`
                    : ""}
                {admission.since && admissionState === "blocked"
                  ? ` · 已持续 ${durationLabel((admission.ts ?? 0) - admission.since)}`
                  : ""}
              </span>
            ) : (
              <span className="v2-learning-bp-sub">
                {worker.running ? "新版本 worker 部署后可见" : "worker 未运行"}
              </span>
            )}
          </div>
        </div>
        {topRequeueReasons.length > 0 ? (
          <div className="v2-learning-bp-requeue">
            <span className="v2-learning-bp-label">重入队原因（累计 / 近 24h）</span>
            <div className="v2-learning-bp-chips">
              {topRequeueReasons.map(([reason, total]) => (
                <span key={reason} className="v2-learning-bp-chip">
                  {requeueReasonLabel(reason)}
                  <b>{total}</b>
                  <i>/ {(requeue?.recent?.[reason] ?? 0)}</i>
                </span>
              ))}
            </div>
          </div>
        ) : null}
      </section>
      <div className="v2-learning-note">
        仅展示 durable lifecycle、机械触发事实和显式 Method 结果；不保存或展示 raw hidden reasoning。
      </div>
      <section className="v2-learning-jobs">
        {status.jobs.length === 0 ? (
          <div className="v2-learning-empty">暂无学习任务</div>
        ) : (
          status.jobs.map((job) => <JobCard key={job.job_id} job={job} />)
        )}
      </section>
    </main>
  );
}
