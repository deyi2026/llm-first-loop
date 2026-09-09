// Web V2：跨会话连续性横幅（目标/任务/续跑状态；后端无该能力时不渲染）

import { useCallback, useEffect, useMemo, useState } from "react";
import { fetchContinuityStatus, type ContinuityFact } from "../../core/api";
import { useCapabilities } from "../../core/capabilities";

export function ContinuityBanner({ sessionId }: { sessionId: string }) {
  const caps = useCapabilities();
  const [fact, setFact] = useState<ContinuityFact | null>(null);
  const [details, setDetails] = useState(false);

  const refresh = useCallback(async () => {
    if (!sessionId) return;
    const next = await fetchContinuityStatus(sessionId);
    setFact(next);
  }, [sessionId]);

  useEffect(() => {
    setFact(null);
    setDetails(false);
    if (!sessionId || !caps.continuity) return;
    void refresh();
    const timer = window.setInterval(() => void refresh(), 5000);
    return () => window.clearInterval(timer);
  }, [sessionId, caps.continuity, refresh]);

  const counts = useMemo(() => {
    const mechanical = fact?.mechanical_execution;
    return {
      tools: mechanical?.tool_executions?.length ?? 0,
      external: mechanical?.external_executions?.length ?? 0,
    };
  }, [fact]);

  if (!caps.continuity) return null;
  if (!fact?.open) return null;
  return (
    <div className="v2-continuity-banner" data-testid="continuity-banner">
      <div className="v2-continuity-main">
        <span aria-hidden="true">↻</span>
        <strong>检测到可恢复的中断状态</strong>
        <span>
          {fact.model || fact.provider || "模型状态"}
          {fact.text_chars ? ` · 输出检查点 ${fact.text_chars} 字符` : ""}
          {counts.tools || counts.external ? ` · 执行事实 ${counts.tools + counts.external}` : ""}
        </span>
        <button type="button" className="v2-link-btn" onClick={() => setDetails((value) => !value)}>
          {details ? "收起" : "查看详情"}
        </button>
        <button type="button" className="v2-link-btn" onClick={() => void refresh()} title="刷新恢复状态">
          刷新
        </button>
      </div>
      {details ? (
        <div className="v2-continuity-details">
          <span>来源：{fact.source || "unknown"}</span>
          <span>provider：{fact.provider || "—"}</span>
          <span>model：{fact.model || "—"}</span>
          <span>正文检查点：{fact.text_chars ?? 0} 字符</span>
          <span>推理检查点：{fact.reasoning_chars ?? 0} 字符</span>
          <span>工具执行：{counts.tools}</span>
          <span>外部执行：{counts.external}</span>
          <span>不会因该状态自动重跑或接管外部进程。</span>
        </div>
      ) : null}
    </div>
  );
}
