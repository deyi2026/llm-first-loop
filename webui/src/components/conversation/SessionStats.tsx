import { useEffect, useState } from "react";

interface SessionStats {
  turns: number;
  steps: number;
  tokens_in: number;
  tokens_out: number;
  cache_hit: number;
  cache_hit_rate: number | null;
  usage_source: string;
  agent_scope: "subagent" | "session";
  llm_ms: number;
  tool_ms: number;
  ttft_avg_ms: number;
  tok_s: number;
}

function finiteNumber(value: unknown): number {
  return typeof value === "number" && Number.isFinite(value) ? value : 0;
}

/** HTTP JSON 是运行时输入：旧端点/部分响应不得把 NaN/undefined 泄漏到 UI。 */
function normalizeSessionStats(value: unknown): SessionStats | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const raw = value as Record<string, unknown>;
  return {
    turns: finiteNumber(raw.turns),
    steps: finiteNumber(raw.steps),
    tokens_in: finiteNumber(raw.tokens_in),
    tokens_out: finiteNumber(raw.tokens_out),
    cache_hit: finiteNumber(raw.cache_hit),
    // "usage not reported" is not a 0%-hit sample.
    cache_hit_rate: typeof raw.cache_hit_rate === "number" && Number.isFinite(raw.cache_hit_rate)
      ? raw.cache_hit_rate : null,
    usage_source: typeof raw.usage_source === "string" ? raw.usage_source : "unknown",
    agent_scope:
      typeof raw.agent_scope === "object" && raw.agent_scope !== null
      && (raw.agent_scope as Record<string, unknown>).kind === "subagent"
        ? "subagent" : "session",
    llm_ms: finiteNumber(raw.llm_ms),
    tool_ms: finiteNumber(raw.tool_ms),
    ttft_avg_ms: finiteNumber(raw.ttft_avg_ms),
    tok_s: finiteNumber(raw.tok_s),
  };
}

/** 时间格式化（ms → 可读：3.6s / 5m12s / 11h05m） */
function fmtMs(ms: number): string {
  if (ms <= 0) return "0s";
  const s = ms / 1000;
  if (s < 60) return `${s.toFixed(1)}s`;
  if (s < 3600) return `${Math.floor(s / 60)}m${Math.floor(s % 60)}s`;
  return `${Math.floor(s / 3600)}h${Math.floor((s % 3600) / 60).toString().padStart(2, "0")}m`;
}

/** token 大数格式化（k/M/G，对齐 DSH 输入 1859M tok） */
function fmtTok(n: number): string {
  if (n >= 1e9) return `${(n / 1e9).toFixed(1)}G`;
  if (n >= 1e6) return `${(n / 1e6).toFixed(0)}M`;
  if (n >= 1e3) return `${(n / 1e3).toFixed(0)}k`;
  return `${n}`;
}

/** 会话统计条（M59，对齐 DSH 统计栏：轮/步/耗时/首 token/吞吐/缓存命中/token 总量）. */
export function SessionStats({ sessionId }: { sessionId: string }) {
  const [stats, setStats] = useState<SessionStats | null>(null);

  useEffect(() => {
    let alive = true;
    const load = async () => {
      try {
        const resp = await fetch(`/api/v1/sessions/${sessionId}/stats`);
        if (!resp.ok) return;
        const next = normalizeSessionStats(await resp.json());
        if (alive) setStats(next);
      } catch {
        /* 端点不可用 → 静默隐藏 */
      }
    };
    load();
    const timer = window.setInterval(load, 60_000); // 60s 轮询（会话进行中刷新）
    return () => {
      alive = false;
      window.clearInterval(timer);
    };
  }, [sessionId]);

  if (!stats || (stats.turns === 0 && stats.steps === 0)) return null;

  return (
    <div className="v2-session-stats" data-testid="session-stats">
      <span>{stats.agent_scope === "subagent" ? "子代理 · " : ""}{stats.turns} 轮 · {stats.steps} 步</span>
      <span className="v2-stats-sep">|</span>
      <span>LLM {fmtMs(stats.llm_ms)} · 工具 {fmtMs(stats.tool_ms)}</span>
      <span className="v2-stats-sep">|</span>
      <span>首 token 平均 {(stats.ttft_avg_ms / 1000).toFixed(1)}s · {stats.tok_s} tok/s</span>
      <span className="v2-stats-sep">|</span>
      <span
        className={stats.cache_hit_rate === null ? "" : stats.cache_hit_rate >= 90 ? "v2-stats-ok" : "v2-stats-warn"}
        // EVO-20260818（spec §5.4.1-1，grill-me Q6）: 口径标注——本处为会话累计口径；
        // 命中率权威口径为"会话近 10 次窗口"（architecture_status.cache_guard.recent_hit_rate）
        title={stats.agent_scope === "subagent"
          ? "子代理独立物理 Provider 回执（含隐藏重试），不与父会话混计；未上报不等于零命中"
          : "会话累计口径（tokens_hit/tokens_in）；命中率权威口径为近 10 次窗口（architecture_status.cache_guard）"}
      >
        缓存命中 {stats.cache_hit_rate === null ? "未上报" : stats.cache_hit_rate + "%"}（累计）
      </span>
      <span className="v2-stats-sep">|</span>
      <span>输入 {fmtTok(stats.tokens_in)} tok · 输出 {fmtTok(stats.tokens_out)} tok</span>
    </div>
  );
}
