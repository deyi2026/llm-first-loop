// Web V2（web 审批状态展示）：演进建议面板
// 数据源：GET /api/v1/evolution/list（只读——审批走飞书/CLI）
// 展示：id/状态标签/优先级/摘要/时间——待审批（pending_review）高亮——点击展开详情

import { useEffect, useState } from "react";
import { zh } from "../../i18n/zh";

interface EvoItem {
  id: string;
  ts: string;
  status: string;
  priority: string;
  requires_human: boolean;
  content: string;
  executed_at?: string | null;
  verified_at?: string | null;
}

const STATUS_LABEL: Record<string, string> = {
  pending_review: "待审批",
  accepted: "已接受",
  executed: "已执行",
  rejected: "已拒绝",
};

const STATUS_COLOR: Record<string, string> = {
  pending_review: "var(--dsw-alias-state-warning, #d97706)",
  accepted: "var(--dsw-alias-state-success, #16a34a)",
  executed: "var(--dsw-alias-state-info, #2563eb)",
  rejected: "var(--dsw-alias-label-tertiary, #888)",
};

function fmtTs(ts: string | undefined | null): string {
  if (!ts) return "";
  const d = new Date(ts);
  if (Number.isNaN(d.getTime())) return ts.slice(0, 16);
  return `${d.getMonth() + 1}-${d.getDate()} ${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
}

export function EvolutionPanel() {
  const [items, setItems] = useState<EvoItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [expanded, setExpanded] = useState<string | null>(null);

  const load = () => {
    setLoading(true);
    void fetch("/api/v1/evolution/list?limit=30")
      .then((r) => (r.ok ? r.json() : { suggestions: [] }))
      .then((d) => setItems(d.suggestions ?? []))
      .catch(() => setItems([]))
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    load();
    // 30s 轮询（状态可变化——飞书/CLI 审批后自动刷新）
    const t = window.setInterval(load, 30000);
    return () => window.clearInterval(t);
  }, []);

  const pending = items.filter((i) => i.status === "pending_review");

  return (
    <div className="v2-evo" data-testid="evolution-panel">
      <div className="v2-evo-head">
        <span className="v2-evo-title">📋 {zh.evolutionTitle}</span>
        {pending.length > 0 && (
          <span className="v2-evo-pending-badge">{pending.length} 待审批</span>
        )}
        <button type="button" className="v2-icon-btn" title={zh.refresh} onClick={load}>
          ⟳
        </button>
      </div>
      <div className="v2-evo-body">
        {loading ? (
          <div className="v2-tree-loading">加载中…</div>
        ) : items.length === 0 ? (
          <div className="v2-tree-loading">（无演进建议）</div>
        ) : (
          items.map((it) => (
            <div
              key={it.id}
              className={`v2-evo-item ${it.status === "pending_review" ? "pending" : ""}`}
              data-testid="evo-item"
              onClick={() => setExpanded(expanded === it.id ? null : it.id)}
            >
              <div className="v2-evo-row">
                <span className="v2-evo-id" title={it.id}>
                  {it.id}
                </span>
                <span
                  className="v2-evo-status"
                  style={{ color: STATUS_COLOR[it.status] ?? "inherit" }}
                >
                  {STATUS_LABEL[it.status] ?? it.status}
                </span>
                {it.priority && <span className="v2-evo-priority">{it.priority}</span>}
                <span className="v2-evo-ts">{fmtTs(it.ts)}</span>
              </div>
              <div className="v2-evo-summary">{it.content}</div>
              {expanded === it.id && (
                <div className="v2-evo-detail" data-testid="evo-detail">
                  {it.requires_human && <div className="v2-evo-note">⚠ 需人工确认（飞书审批）</div>}
                  {it.executed_at && <div className="v2-evo-note">执行于 {fmtTs(it.executed_at)}</div>}
                  {it.verified_at && <div className="v2-evo-note">核验于 {fmtTs(it.verified_at)}</div>}
                  <div className="v2-evo-hint">{zh.evoHint}</div>
                </div>
              )}
            </div>
          ))
        )}
      </div>
    </div>
  );
}
