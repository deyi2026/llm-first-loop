import { useEffect, useState } from "react";

interface SessionStats {
  turns: number;
  steps: number;
  tokens_in: number;
  tokens_out: number;
  cache_hit: number;
  cache_hit_rate: number;
  llm_ms: number;
  tool_ms: number;
  ttft_avg_ms: number;
  tok_s: number;
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
        if (resp.ok && alive) setStats((await resp.json()) as SessionStats);
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
      <span>{stats.turns} 轮 · {stats.steps} 步</span>
      <span className="v2-stats-sep">|</span>
      <span>LLM {fmtMs(stats.llm_ms)} · 工具 {fmtMs(stats.tool_ms)}</span>
      <span className="v2-stats-sep">|</span>
      <span>首 token 平均 {(stats.ttft_avg_ms / 1000).toFixed(1)}s · {stats.tok_s} tok/s</span>
      <span className="v2-stats-sep">|</span>
      <span
        className={stats.cache_hit_rate >= 90 ? "v2-stats-ok" : "v2-stats-warn"}
        // EVO-20260818（spec §5.4.1-1，grill-me Q6）: 口径标注——本处为会话累计口径；
        // 命中率权威口径为"会话近 10 次窗口"（architecture_status.cache_guard.recent_hit_rate）
        title={"会话累计口径（tokens_hit/tokens_in）；命中率权威口径为近 10 次窗口（architecture_status.cache_guard）"}
      >
        缓存命中 {stats.cache_hit_rate}%（累计）
      </span>
      <span className="v2-stats-sep">|</span>
      <span>输入 {fmtTok(stats.tokens_in)} tok · 输出 {fmtTok(stats.tokens_out)} tok</span>
    </div>
  );
}
