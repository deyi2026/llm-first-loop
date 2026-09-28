import { useCallback, useEffect, useRef, useState } from "react";
import {
  fetchChatGPTBindingHealth,
  fetchSessionProviderBinding,
  type ChatGPTBindingHealth,
  type ChatGPTBindingInfo,
} from "../../core/api";

function fmtNumber(value: unknown): string {
  return typeof value === "number" && Number.isFinite(value)
    ? value.toLocaleString()
    : "—";
}

function fmtTime(value: unknown): string {
  if (typeof value !== "string" || !value) return "—";
  const parsed = new Date(value);
  return Number.isFinite(parsed.getTime()) ? parsed.toLocaleString() : value;
}

export function SessionBindingPanel({ sessionId }: { sessionId: string | null }) {
  const [info, setInfo] = useState<ChatGPTBindingInfo | null>(null);
  const [health, setHealth] = useState<ChatGPTBindingHealth | null>(null);
  const [loading, setLoading] = useState(false);
  const [readError, setReadError] = useState(false);
  const inFlight = useRef(false);
  const activeSession = useRef(sessionId);
  activeSession.current = sessionId;

  const load = useCallback(async () => {
    if (!sessionId || inFlight.current) return;
    inFlight.current = true;
    setLoading(true);
    try {
      const [next, nextHealth] = await Promise.all([
        fetchSessionProviderBinding(sessionId),
        fetchChatGPTBindingHealth(),
      ]);
      if (activeSession.current !== sessionId) return;
      setHealth(nextHealth);
      if (next) {
        setInfo(next);
        setReadError(false);
      } else {
        setReadError(true);
      }
    } finally {
      inFlight.current = false;
      setLoading(false);
    }
  }, [sessionId]);

  useEffect(() => {
    setInfo(null);
    setHealth(null);
    setReadError(false);
    if (!sessionId) return;
    void load();
    const timer = window.setInterval(() => {
      if (!document.hidden) void load();
    }, 10_000);
    return () => window.clearInterval(timer);
  }, [sessionId]); // eslint-disable-line react-hooks/exhaustive-deps

  if (!sessionId) {
    return <div className="v2-placeholder">选择一个会话后查看 Provider 绑定。</div>;
  }
  if (!info && loading) {
    return <div className="v2-placeholder">正在读取会话绑定…</div>;
  }
  if (!info) {
    return (
      <div className="v2-jobs" data-testid="session-binding-panel">
        <div className="v2-panel-error">
          {readError ? "会话绑定读取失败；当前不做任何生命周期判断。" : "暂无绑定信息。"}
        </div>
        <button type="button" className="v2-btn ghost" onClick={() => void load()}>
          ⟳ 重试
        </button>
      </div>
    );
  }

  const binding = info.binding;
  const history = Array.isArray(info.history) ? info.history : [];
  const lifecycle = info.lifecycle ?? {};
  const policy = info.gc_policy ?? {};
  const metrics = health?.metrics ?? {};
  const alerts = Array.isArray(health?.alerts) ? health.alerts : [];
  const healthClass =
    health?.status === "critical"
      ? "err"
      : health?.status === "warning"
        ? "warn"
        : "ok";
  const metric = (key: string): unknown => metrics[key];

  return (
    <div className="v2-jobs" data-testid="session-binding-panel">
      <div className="v2-panel-toolbar">
        <span>ChatGPT Web transport</span>
        <button type="button" className="v2-btn ghost" disabled={loading} onClick={() => void load()}>
          {loading ? "刷新中…" : "⟳ 刷新"}
        </button>
      </div>
      <div className="v2-job-card" data-testid="binding-health-card">
        <div className="v2-job-head">
          <strong>运行指标 / 告警</strong>
          <span className={"v2-status-chip " + healthClass}>
            {health?.status || "unknown"}
          </span>
        </div>
        <div className="v2-kv">
          <span className="k">Bindings</span><span className="v">{fmtNumber(metric("bindings_total"))}</span>
          <span className="k">24h exchanges</span><span className="v">{fmtNumber(metric("exchanges_24h"))}</span>
          <span className="k">24h rollovers</span><span className="v">{fmtNumber(metric("rollovers_24h"))}</span>
          <span className="k">24h restore failures</span><span className="v">{fmtNumber(metric("restore_failures_24h"))}</span>
          <span className="k">24h restore success</span>
          <span className="v">
            {typeof metric("restore_success_rate_24h") === "number"
              ? (Number(metric("restore_success_rate_24h")) * 100).toFixed(1) + "%"
              : "—"}
          </span>
          <span className="k">最大 segment 压力</span>
          <span className="v">
            {typeof metric("segment_pressure_max_ratio") === "number"
              ? (Number(metric("segment_pressure_max_ratio")) * 100).toFixed(1) + "%"
              : "—"}
          </span>
          <span className="k">Telemetry events</span><span className="v">{fmtNumber(health?.telemetry?.event_count)}</span>
          <span className="k">最近事件</span><span className="v">{fmtTime(health?.telemetry?.last_event_at)}</span>
        </div>
        <div className="v2-job-note">
          近 1h/24h 指标只覆盖 telemetry 上线后的 event log，不回填历史调用；告警仅观测，不自动
          rollover、不自动 GC。
        </div>
        {alerts.length === 0 ? (
          <div className="v2-job-note">当前无 Binding/rollover 告警。</div>
        ) : (
          alerts.map((alert, index) => (
            <div className="v2-job-card" key={(alert.code || "alert") + "-" + index}>
              <div className="v2-job-head">
                <strong>{alert.code || "binding_alert"}</strong>
                <span className={"v2-status-chip " + (alert.severity === "critical" ? "err" : "warn")}>
                  {alert.severity || "warning"}
                </span>
              </div>
              <div className="v2-job-note">{alert.message || "Binding telemetry alert"}</div>
              {typeof alert.count === "number" ? (
                <div className="v2-job-note">count: {alert.count}</div>
              ) : null}
            </div>
          ))
        )}
      </div>
      {!info.bound || !binding ? (
        <div className="v2-placeholder">
          当前 LFL Session 尚未建立 ChatGPT Web conversation binding。
        </div>
      ) : (
        <>
          <div className="v2-job-card">
            <div className="v2-job-head">
              <strong>当前 segment</strong>
              <span className="v2-status-chip ok">已绑定</span>
            </div>
            <div className="v2-kv">
              <span className="k">LFL Session</span><span className="v"><code>{sessionId}</code></span>
              <span className="k">Conversation</span><span className="v"><code>{binding.conversation_id || "—"}</code></span>
              <span className="k">Segment</span><span className="v">{fmtNumber(binding.segment_seq)}</span>
              <span className="k">Segment 请求</span><span className="v">{fmtNumber(binding.segment_request_count)}</span>
              <span className="k">Segment chars</span><span className="v">{fmtNumber(binding.segment_request_chars)}</span>
              <span className="k">累计请求</span><span className="v">{fmtNumber(binding.total_request_count)}</span>
              <span className="k">更新时间</span><span className="v">{fmtTime(binding.updated_at)}</span>
              <span className="k">LFL 状态</span><span className="v">{info.session_status || "—"}</span>
            </div>
            {binding.conversation_url ? (
              <a
                className="v2-btn ghost"
                href={binding.conversation_url}
                target="_blank"
                rel="noreferrer"
              >
                打开 ChatGPT conversation ↗
              </a>
            ) : null}
          </div>

          <div className="v2-job-card">
            <div className="v2-job-head">
              <strong>生命周期 / GC</strong>
              <span className={"v2-status-chip " + (lifecycle.gc_eligible ? "warn" : "neutral")}>
                {lifecycle.gc_eligible ? "可清理" : "保留"}
              </span>
            </div>
            <div className="v2-kv">
              <span className="k">Session 存在</span><span className="v">{lifecycle.session_exists === false ? "否" : "是"}</span>
              <span className="k">判定</span><span className="v">{lifecycle.gc_reason || "—"}</span>
              <span className="k">自动 GC</span><span className="v">{policy.automatic_gc ? "开启" : "关闭"}</span>
              <span className="k">默认保留</span><span className="v">{fmtNumber(policy.default_min_age_days)} 天</span>
            </div>
            <div className="v2-job-note">
              Existing/archived LFL Session 永不自动清理；只有物理已删除且达到保留期的 orphan binding
              才可通过显式 confirm + expected_updated_at 清理。
            </div>
          </div>
        </>
      )}

      <div className="v2-panel-toolbar">
        <span>已关闭 segments：{history.length}</span>
      </div>
      {history.length === 0 ? <div className="v2-placeholder">暂无 rollover history。</div> : null}
      {[...history].reverse().map((segment, index) => (
        <div
          className="v2-job-card"
          key={String(segment.segment_seq ?? "?") + "-" + String(segment.conversation_id ?? index)}
        >
          <div className="v2-job-head">
            <strong>segment {fmtNumber(segment.segment_seq)}</strong>
            <span className="v2-status-chip neutral">{segment.reason || "rollover"}</span>
          </div>
          <code>{segment.conversation_id || "—"}</code>
          <div className="v2-kv">
            <span className="k">请求</span><span className="v">{fmtNumber(segment.request_count)}</span>
            <span className="k">chars</span><span className="v">{fmtNumber(segment.request_chars)}</span>
            <span className="k">关闭时间</span><span className="v">{fmtTime(segment.closed_at)}</span>
          </div>
        </div>
      ))}
    </div>
  );
}
