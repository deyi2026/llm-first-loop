// 插话时延观测面板（可观测性 M1c，2026-10-14）
// 数据源（全部只读 GET，零写操作）：
//   全局：GET /api/v1/chat/queue/metrics/global（M1b 新增，跨 session 合并）
//   会话：GET /api/v1/chat/queue/metrics?session_id=…（Phase3 G2 既有端点，复用）
// 诚实口径（V3）：null=「无样本」（≠0ms）；n<5 标注「样本不足」；
//   数据窗口=最近 window_terminal_cap 条终态（非全历史），面板显式标注（B5）。
// fail-open（B4）：任一数据源失败仅该块显示「不可用」，不阻塞其余 UI，可手动重试。

import { useCallback, useEffect, useState } from "react";

const BUCKETS: { key: string; label: string }[] = [
  { key: "interruptible", label: "可打断点" },
  { key: "natural_boundary", label: "自然边界" },
  { key: "llm_stream", label: "流式·保守等待" },
  { key: "llm_stream_interrupt", label: "流式·打断收割" },
  { key: "sync_window_poll", label: "同步窗口轮询" },
  { key: "idle", label: "空闲收割" },
];

const METRICS: { key: string; label: string }[] = [
  { key: "t_ack_ms", label: "受理 t_ack" },
  { key: "t_persist_ms", label: "持久化 t_persist" },
  { key: "t_effect_ms", label: "生效 t_effect" },
  { key: "t_applied_ms", label: "应用 t_applied" },
];

interface BucketStats {
  n: number;
  p50_t_effect_ms: number | null;
  p95_t_effect_ms: number | null;
  insufficient_sample: boolean;
}

interface MetricsView {
  n: number;
  p50_t_ack_ms: number | null;
  p95_t_ack_ms: number | null;
  p50_t_persist_ms: number | null;
  p95_t_persist_ms: number | null;
  p50_t_effect_ms: number | null;
  p95_t_effect_ms: number | null;
  p50_t_applied_ms: number | null;
  p95_t_applied_ms: number | null;
  buckets: Record<string, BucketStats>;
  sessions_in_window?: number;
  window_terminal_cap?: number;
}

function fmtMs(v: number | null | undefined): string {
  if (v === null || v === undefined) return "无样本";
  return `${v >= 100 ? Math.round(v) : v} ms`;
}

const th: React.CSSProperties = {
  textAlign: "left",
  fontWeight: 600,
  padding: "3px 8px",
  borderBottom: "1px solid var(--dsw-alias-line-tertiary, #ddd)",
};
const td: React.CSSProperties = { padding: "3px 8px", borderBottom: "1px solid var(--dsw-alias-line-quaternary, #eee)" };
const badge: React.CSSProperties = {
  marginLeft: 6,
  fontSize: 10,
  padding: "1px 5px",
  borderRadius: 8,
  background: "var(--dsw-alias-state-warning-bg, #fef3c7)",
  color: "var(--dsw-alias-state-warning, #92400e)",
};
const muted = { fontSize: 11, color: "var(--dsw-alias-label-tertiary, #888)" } as const;

function SectionTitle({ children }: { children: React.ReactNode }) {
  return <div style={{ fontWeight: 700, margin: "10px 0 4px" }}>{children}</div>;
}

function MetricTable({ view, scope }: { view: MetricsView; scope: string }) {
  return (
    <table style={{ width: "100%", fontSize: 12, borderCollapse: "collapse" }} data-testid={`im-${scope}-metrics-table`}>
      <thead>
        <tr>
          <th style={th}>口径</th>
          <th style={th}>P50</th>
          <th style={th}>P95</th>
        </tr>
      </thead>
      <tbody>
        {METRICS.map((m) => (
          <tr key={m.key}>
            <td style={td}>{m.label}</td>
            <td style={td} data-testid={`im-${scope}-${m.key}-p50`}>
              {fmtMs(view[`p50_${m.key}` as keyof MetricsView] as number | null)}
            </td>
            <td style={td}>{fmtMs(view[`p95_${m.key}` as keyof MetricsView] as number | null)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function BucketTable({ view, scope }: { view: MetricsView; scope: string }) {
  return (
    <table style={{ width: "100%", fontSize: 12, borderCollapse: "collapse" }} data-testid="im-bucket-table">
      <thead>
        <tr>
          <th style={th}>消费桶</th>
          <th style={th}>n</th>
          <th style={th}>P50</th>
          <th style={th}>P95</th>
        </tr>
      </thead>
      <tbody>
        {BUCKETS.map((b) => {
          const s = view.buckets?.[b.key];
          const insuff = s?.insufficient_sample;
          return (
            <tr key={b.key} data-testid={`im-${scope}-bucket-${b.key}`}>
              <td style={td}>
                {b.label}
                {insuff ? (
                  <span style={badge} data-testid={`im-${scope}-insufficient-${b.key}`}>
                    样本不足
                  </span>
                ) : null}
              </td>
              <td style={td}>{s ? s.n : 0}</td>
              <td style={td}>{fmtMs(s?.p50_t_effect_ms)}</td>
              <td style={td}>{fmtMs(s?.p95_t_effect_ms)}</td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

export function InterjectMetricsPanel({ sessionId }: { sessionId: string }) {
  const [global, setGlobal] = useState<MetricsView | null>(null);
  const [globalError, setGlobalError] = useState("");
  const [globalLoading, setGlobalLoading] = useState(true);
  const [session, setSession] = useState<MetricsView | null>(null);
  const [sessionError, setSessionError] = useState("");
  const [tick, setTick] = useState(0);

  const load = useCallback(async () => {
    setGlobalLoading(true);
    setGlobalError("");
    try {
      const r = await fetch("/api/v1/chat/queue/metrics/global");
      if (!r.ok) throw new Error(String(r.status));
      setGlobal((await r.json()) as MetricsView);
    } catch {
      setGlobal(null);
      setGlobalError("全局视图不可用（诊断端点失败；不影响其它面板）");
    } finally {
      setGlobalLoading(false);
    }
    if (sessionId) {
      setSessionError("");
      try {
        const r = await fetch(`/api/v1/chat/queue/metrics?session_id=${encodeURIComponent(sessionId)}`);
        if (!r.ok) throw new Error(String(r.status));
        setSession((await r.json()) as MetricsView);
      } catch {
        setSession(null);
        setSessionError("当前会话视图不可用");
      }
    } else {
      setSession(null);
    }
  }, [sessionId]);

  useEffect(() => {
    void load();
  }, [load, tick]);

  return (
    <div style={{ padding: 12, fontSize: 12 }} data-testid="interject-metrics">
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <b>插话时延观测</b>
        <button type="button" onClick={() => setTick((t) => t + 1)} disabled={globalLoading}>
          刷新
        </button>
      </div>

      <SectionTitle>全局（跨会话合并）</SectionTitle>
      {globalError ? (
        <div role="status" style={{ color: "var(--dsw-alias-state-danger, #b91c1c)" }} data-testid="im-global-error">
          {globalError}
        </div>
      ) : global ? (
        <div>
          <div style={muted}>
            样本 <span data-testid="im-global-n">{global.n}</span> 条 · 来自{" "}
            {global.sessions_in_window ?? 0} 个会话
          </div>
          <MetricTable view={global} scope="global" />
          <BucketTable view={global} scope="global" />
        </div>
      ) : globalLoading ? (
        <div style={muted}>加载中…</div>
      ) : null}

      <SectionTitle>当前会话</SectionTitle>
      {sessionId ? (
        sessionError ? (
          <div role="status" style={{ color: "var(--dsw-alias-state-danger, #b91c1c)" }} data-testid="im-session-error">
            {sessionError}
          </div>
        ) : session ? (
          <div>
            <div style={muted}>
              样本 <span data-testid="im-session-n">{session.n}</span> 条（复用既有会话端点）
            </div>
            <BucketTable view={session} scope="session" />
          </div>
        ) : (
          <div style={muted}>加载中…</div>
        )
      ) : (
        <div style={muted} data-testid="im-session-empty">
          （无当前会话）
        </div>
      )}

      <div style={{ ...muted, marginTop: 10 }} data-testid="im-window-note">
        数据窗口：最近 {global?.window_terminal_cap ?? "—"} 条终态（滚动窗口，非全历史）；
        仅统计 interject_received 终态，denied/requeued 不计；null=无样本 ≠ 0ms。
      </div>
    </div>
  );
}
