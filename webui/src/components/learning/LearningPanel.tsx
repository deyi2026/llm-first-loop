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
          <span>Method candidate</span><code>{job.candidate_ref}</code>
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
        <div><span>排队</span><strong>{status.counts.queued ?? 0}</strong></div>
        <div><span>学习中</span><strong>{status.counts.started ?? 0}</strong></div>
        <div><span>已生成</span><strong>{status.counts.saved ?? 0}</strong></div>
        <div><span>失败</span><strong>{status.counts.failed ?? 0}</strong></div>
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
