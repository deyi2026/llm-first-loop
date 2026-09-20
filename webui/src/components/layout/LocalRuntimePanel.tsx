import { useCallback, useEffect, useRef, useState } from "react";
import {
  fetchLocalRuntime,
  fetchLocalRuntimeJob,
  startLocalRuntimeJob,
  type LocalRuntimeJob,
  type LocalRuntimeStatus,
} from "../../core/api";

type SyncOutcome = { message?: string; error?: string };

function stateDot(status: LocalRuntimeStatus | null): string {
  if (!status) return "…";
  if (status.state.health === true && status.state.port_listening) return "健康";
  if (status.state.launchd === "running") return "启动中";
  if (status.state.launchd) return String(status.state.launchd);
  return "未运行";
}

export function LocalRuntimePanel({ onSynced }: { onSynced?: () => Promise<SyncOutcome | void> | void }) {
  const [status, setStatus] = useState<LocalRuntimeStatus | null>(null);
  const [unavailable, setUnavailable] = useState(false);
  const [job, setJob] = useState<LocalRuntimeJob | null>(null);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const timerRef = useRef<number | null>(null);
  const settledRef = useRef<Set<string>>(new Set());
  const busy = job?.status === "running";

  const loadStatus = useCallback(async () => {
    try {
      const next = await fetchLocalRuntime();
      if (next) {
        setStatus(next);
        setUnavailable(false);
        setJob(next.job ?? null);
      } else {
        setUnavailable(true);
      }
    } catch {
      setUnavailable(true);
    }
  }, []);

  // job 结算（完成/失败）统一入口：立即完成与轮询发现都走这里，只结算一次
  const settle = useCallback(async (settled: LocalRuntimeJob) => {
    if (settledRef.current.has(settled.id) || settled.status === "running") return;
    settledRef.current.add(settled.id);
    await loadStatus();
    if (settled.status === "done") {
      const result = settled.result as { registry_synced?: boolean; model_ref?: string; registry_sync_error?: string } | null;
      if (result?.registry_synced && result.model_ref) {
        setMessage(`切换完成，已同步到注册表：${result.model_ref}（${settled.duration_s}s）`);
      } else if (result?.registry_sync_error) {
        setError(`切换完成，但注册表同步失败：${result.registry_sync_error}`);
      } else {
        setMessage(`完成（${settled.duration_s}s）`);
      }
      await onSynced?.();
    } else if (settled.status === "failed") {
      setError(`失败：${settled.error ?? "lfrt 非零退出"}（${settled.duration_s}s）`);
    }
  }, [loadStatus, onSynced]);

  useEffect(() => {
    void loadStatus();
  }, [loadStatus]);

  // 轮询进行中的 job；结束后刷新状态并同步模型目录
  useEffect(() => {
    if (job?.status !== "running") return undefined;
    const timer = window.setInterval(async () => {
      const next = await fetchLocalRuntimeJob(job.id);
      if (next && next.status === "running") {
        setJob(next);
      } else if (next) {
        setJob(next);
        await settle(next);
      }
    }, 2500);
    timerRef.current = timer;
    return () => window.clearInterval(timer);
  }, [job?.status, job?.id, settle]);

  const act = useCallback(async (
    action: "switch_model" | "switch_backend" | "restart" | "stop" | "start",
    options: { model?: string; backend?: string; confirm?: boolean } = {},
    describe: string
  ) => {
    setError("");
    setMessage(`正在${describe}…（大模型加载+预热可能需要几分钟）`);
    const result = await startLocalRuntimeJob(action, options);
    if (result.ok && result.job) {
      setJob(result.job);
      if (result.job.status !== "running") {
        await settle(result.job);
      }
    } else {
      setError(`${describe}未开始：${result.detail}`);
      setMessage("");
    }
  }, []);

  if (unavailable) {
    return (
      <section className="v2-local-runtime v2-local-runtime--off" data-testid="local-runtime">
        <div className="v2-provider-subhead"><strong>本地运行时（lfrt）</strong></div>
        <div className="v2-placeholder">未检测到 lfrt（settings.lfrt_cli / LFL_LFRT_CLI）。配置后可在此切换本地 GGUF / MLX 模型。</div>
      </section>
    );
  }
  if (!status) {
    return (
      <section className="v2-local-runtime" data-testid="local-runtime">
        <div className="v2-placeholder">正在读取本地运行时…</div>
      </section>
    );
  }

  const otherBackend = status.backend === "llama" ? "mlx" : "llama";
  const canSwapBackend = status.stashed_backends.includes(otherBackend);

  return (
    <section className="v2-local-runtime" data-testid="local-runtime">
      <div className="v2-provider-subhead">
        <strong>本地运行时（lfrt）</strong>
        <span className="v2-local-runtime-state">
          {stateDot(status)} · 后端 {status.backend} · :{status.port} · 空闲内存 {status.free_gb ?? "?"}GB
          {status.alias ? ` · ${status.alias}` : ""}
          {status.provider ? ` → ${status.provider.id}` : "（未接入 provider）"}
        </span>
      </div>
      {message ? <div className="v2-provider-ok">{message}</div> : null}
      {error ? <div className="v2-panel-error">{error}</div> : null}
      <div className="v2-local-runtime-actions">
        <button type="button" className="v2-btn ghost" disabled={busy} onClick={() => void act("restart", {}, "重启服务")}>重启</button>
        <button type="button" className="v2-btn ghost" disabled={busy} onClick={() => void act("start", {}, "启动服务")}>启动</button>
        <button
          type="button"
          className="v2-btn danger"
          disabled={busy}
          onClick={() => {
            if (window.confirm("停止本地运行时会中断所有本地推理请求，确认？")) {
              void act("stop", { confirm: true }, "停止服务");
            }
          }}
        >
          停止
        </button>
        {canSwapBackend ? (
          <button type="button" className="v2-btn ghost" disabled={busy} onClick={() => void act("switch_backend", { backend: otherBackend }, `切到 ${otherBackend} 后端`)}>
            切到 {otherBackend} 后端
          </button>
        ) : null}
      </div>
      <div className="v2-local-runtime-models">
        {status.models.map((model) => (
          <div className={`v2-local-runtime-model${model.active ? " is-active" : ""}`} key={model.name}>
            <div className="v2-local-runtime-model-name">
              {model.name}
              <span className="v2-local-runtime-badge">{model.kind === "gguf" ? "GGUF" : "MLX"}</span>
              {model.active ? <span className="v2-local-runtime-badge is-active">当前</span> : null}
            </div>
            <div className="v2-local-runtime-model-meta">
              {model.size_gb != null ? `${model.size_gb}GB` : ""}
              {model.shards ? ` · 分片 ${model.shards}` : ""}
              {model.kind === "gguf" && model.shards_ok === false ? " · 分片缺失" : ""}
            </div>
            <button
              type="button"
              className="v2-btn ghost"
              disabled={busy || model.active || (model.kind === "gguf" && model.shards_ok === false)}
              title={model.active ? "已是当前模型" : model.kind === "gguf" && model.shards_ok === false ? "分片不完整，lfrt 会拒绝" : "切换到该模型（自动退出当前模型进程；跨后端类型时单次重启内完成交换）"}
              onClick={() => void act("switch_model", { model: model.name }, `切换到 ${model.name}`)}
            >
              切换
            </button>
          </div>
        ))}
      </div>
      {job ? (
        <div className="v2-local-runtime-job" data-testid="local-runtime-job">
          <div className="v2-local-runtime-job-head">
            {job.label} · {job.status}{job.duration_s ? ` · ${job.duration_s}s` : ""}
            {job.error ? ` · ${job.error}` : ""}
          </div>
          {job.output_tail.length > 0 ? <pre>{job.output_tail.join("\n")}</pre> : null}
        </div>
      ) : null}
    </section>
  );
}
