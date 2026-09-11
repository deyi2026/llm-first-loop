import { useCallback, useEffect, useState } from "react";
import { zh } from "../../i18n/zh";
import {
  fetchAuthStatus,
  fetchSessionJobs,
  killSessionJob,
  type AuthStatus,
  type JobFact,
} from "../../core/api";
import {
  themeStore,
  useConnection,
  useCurrentSessionId,
  useTheme,
  type ThemePreference,
} from "../../core/stores";
import { fetchModels, type ModelCatalog } from "../../core/chat";
import { useCapabilities } from "../../core/capabilities";
import { ProviderManager } from "./ProviderManager";

export function RightPanel({ open }: { open: boolean }) {
  const caps = useCapabilities();
  const [tab, setTab] = useState<"settings" | "jobs">("settings");
  const conn = useConnection();
  const theme = useTheme();
  const currentSessionId = useCurrentSessionId();
  const [catalog, setCatalog] = useState<ModelCatalog>({ models: [], current: null, catalog: [] });
  const [auth, setAuth] = useState<AuthStatus | null>(null);
  const [jobs, setJobs] = useState<JobFact[]>([]);
  const [jobError, setJobError] = useState("");
  const [jobBusy, setJobBusy] = useState<string | null>(null);

  const loadSettings = useCallback(async () => {
    const [models, authStatus] = await Promise.all([fetchModels(), fetchAuthStatus()]);
    setCatalog(models);
    setAuth(authStatus);
  }, []);

  const loadJobs = useCallback(async () => {
    if (!currentSessionId) {
      setJobs([]);
      return;
    }
    setJobs(await fetchSessionJobs(currentSessionId));
  }, [currentSessionId]);

  useEffect(() => {
    if (open && tab === "settings") void loadSettings();
  }, [open, tab, loadSettings]);

  useEffect(() => {
    if (!open || tab !== "jobs" || !caps.jobs) return;
    void loadJobs();
    const timer = window.setInterval(() => void loadJobs(), 2000);
    return () => window.clearInterval(timer);
  }, [open, tab, caps.jobs, loadJobs]);

  if (!open) return null;

  const cancelJob = async (job: JobFact) => {
    if (!currentSessionId || jobBusy) return;
    setJobBusy(job.job_id);
    setJobError("");
    const result = await killSessionJob(currentSessionId, job.job_id);
    if (!result.ok) setJobError(result.detail || "停止失败：该任务当前不可由本进程控制。");
    await loadJobs();
    setJobBusy(null);
  };

  return (
    <aside className="v2-panel" data-testid="right-panel">
      <div className="v2-panel-tabs">
        <button
          type="button"
          className={`v2-panel-tab ${tab === "settings" ? "active" : ""}`}
          onClick={() => setTab("settings")}
        >
          {zh.panelSettings}
        </button>
        {caps.jobs ? (
          <button
            type="button"
            className={`v2-panel-tab ${tab === "jobs" ? "active" : ""}`}
            onClick={() => setTab("jobs")}
          >
            {zh.panelJobs}
          </button>
        ) : null}
      </div>
      <div className="v2-panel-body" data-testid="panel-body">
        {tab === "settings" || !caps.jobs ? (
          <SettingsView
            conn={conn}
            theme={theme}
            catalog={catalog}
            auth={auth}
            reload={loadSettings}
            providerAdminEnabled={caps.providerAdmin}
          />
        ) : (
          <JobsView
            sessionId={currentSessionId}
            jobs={jobs}
            error={jobError}
            busyId={jobBusy}
            onRefresh={loadJobs}
            onCancel={cancelJob}
          />
        )}
      </div>
    </aside>
  );
}

function SettingsView({
  conn,
  theme,
  catalog,
  auth,
  reload,
  providerAdminEnabled,
}: {
  conn: ReturnType<typeof useConnection>;
  theme: ReturnType<typeof useTheme>;
  catalog: ModelCatalog;
  auth: AuthStatus | null;
  reload: () => Promise<void>;
  providerAdminEnabled: boolean;
}) {
  const themes: Array<{ key: ThemePreference; label: string }> = [
    { key: "system", label: "跟随系统" },
    { key: "light", label: "亮色" },
    { key: "dark", label: "暗色" },
  ];
  return (
    <div className="v2-settings-sections" data-testid="settings-sections">
      <section>
        <h3>界面</h3>
        <div className="v2-choice-row">
          {themes.map((item) => (
            <button
              type="button"
              key={item.key}
              className={theme.preference === item.key ? "active" : ""}
              onClick={() => themeStore.setPreference(item.key)}
            >
              {item.label}
            </button>
          ))}
        </div>
      </section>
      <section>
        <h3>输入与文件</h3>
        <div className="v2-settings-facts">
          <span>多文件上传：已启用</span>
          <span>拖放 / 粘贴图片：已启用</span>
          <span>单文件上限：10 MB</span>
          <span>附件进入模型前使用 workspace-scoped opaque ref 再校验</span>
        </div>
      </section>
      <section>
        <h3>模型与推理</h3>
        <div className="v2-model-catalog" data-testid="model-catalog">
          {catalog.catalog.length > 0
            ? catalog.catalog.map((model) => (
                <div key={model.id} className={`v2-catalog-item ${model.id === catalog.current ? "current" : ""}`}>
                  <span className="v2-catalog-id">{model.id}</span>
                  <span className="v2-catalog-detail">
                    {model.context ? `${Math.round(model.context / 1000)}k ctx` : "ctx?"} · {model.cost_tier || "cost?"} · {model.reasoning_capable ? `reasoning/${model.reasoning_control}` : "reasoning 未证实"}
                  </span>
                  {model.id === catalog.current ? <span className="v2-catalog-current">当前</span> : null}
                </div>
              ))
            : catalog.models.map((model) => (
                <div key={model} className={`v2-catalog-item ${model === catalog.current ? "current" : ""}`}>
                  <span className="v2-catalog-id">{model}</span>
                  <span className="v2-catalog-detail">能力元数据未提供；请求时保持 provider 默认。</span>
                  {model === catalog.current ? <span className="v2-catalog-current">当前</span> : null}
                </div>
              ))}
          {catalog.current && catalog.currentAvailable === false ? (
            <div className="v2-catalog-item current-unavailable" data-testid="stale-current-model">
              <span className="v2-catalog-id">{catalog.current}</span>
              <span className="v2-catalog-detail">当前会话仍选择此模型，但它已不在有效 Registry。</span>
              <span className="v2-catalog-current">当前不可用</span>
            </div>
          ) : null}
          {catalog.models.length === 0 ? <div className="v2-placeholder">模型目录暂不可用</div> : null}
        </div>
        {providerAdminEnabled ? (
          <ProviderManager onCatalogChanged={reload} />
        ) : (
          <div className="v2-provider-readonly-note">当前后端未提供 Provider 管理 API；保留只读模型目录。</div>
        )}
      </section>
      <section>
        <h3>连接与安全</h3>
        <div className="v2-kv">
          <span className="k">服务</span><span className="v">{conn.service || "—"}</span>
          <span className="k">版本</span><span className="v">{conn.version || "—"}</span>
          <span className="k">连接</span><span className="v">{conn.ok ? zh.statusConnected : zh.statusDisconnected}</span>
          <span className="k">浏览器登录</span><span className="v">{auth?.authenticated ? "已验证" : auth?.browser_login ? "未验证" : "未启用"}</span>
        </div>
      </section>
      <button type="button" className="v2-btn ghost" onClick={() => void reload()}>
        ⟳ {zh.reload}
      </button>
    </div>
  );
}

function JobsView({
  sessionId,
  jobs,
  error,
  busyId,
  onRefresh,
  onCancel,
}: {
  sessionId: string | null;
  jobs: JobFact[];
  error: string;
  busyId: string | null;
  onRefresh: () => Promise<void>;
  onCancel: (job: JobFact) => Promise<void>;
}) {
  if (!sessionId) return <div className="v2-placeholder">选择一个会话后查看后台任务。</div>;
  return (
    <div className="v2-jobs" data-testid="jobs-panel">
      <div className="v2-panel-toolbar">
        <span>{jobs.length} 个任务事实</span>
        <button type="button" className="v2-btn ghost" onClick={() => void onRefresh()}>⟳ 刷新</button>
      </div>
      {error ? <div className="v2-panel-error">{error}</div> : null}
      {jobs.length === 0 ? <div className="v2-placeholder">当前会话没有可见后台任务。</div> : null}
      {jobs.map((job) => {
        const running = job.state === "running";
        const killable = running && job.local_handle === true && !job.killed;
        return (
          <div className="v2-job-card" key={job.job_id} data-testid="job-card">
            <div className="v2-job-head">
              <strong>{job.executor || "external"}</strong>
              <span className={`v2-status-chip ${job.state === "completed" ? "ok" : job.state === "failed" ? "err" : job.state === "orphaned" ? "warn" : "neutral"}`}>
                {job.state}
              </span>
            </div>
            <code>{job.job_id}</code>
            {job.command ? <div className="v2-job-command">{job.command}</div> : null}
            {job.output?.length ? <pre className="v2-job-output"><code>{job.output.slice(-20).join("\n")}</code></pre> : null}
            {job.state === "orphaned" ? <div className="v2-job-note">重启后只保留 durable 生命周期事实；无本地控制句柄，不自动接管/重跑。</div> : null}
            {killable ? (
              <button type="button" className="v2-btn danger" disabled={busyId === job.job_id} onClick={() => void onCancel(job)}>
                {busyId === job.job_id ? "停止中…" : "停止任务"}
              </button>
            ) : null}
          </div>
        );
      })}
    </div>
  );
}
