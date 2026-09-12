// 演进建议审批面板（Approval UX v2 批 1，2026-08-21 镜像）
// 数据源：GET /api/v1/evolution/list（摘要+impact_hint）/ detail（全文懒加载）
// 决策：review（单条，二次确认+拒绝理由必填+CAS）/ review-batch（批量，服务端跳过 requires_human）
// 交互：分类 Tab / 详情懒加载 / 二次确认 / 拒绝理由必填 / 批量 / 409 冲突提示 / 涉边界禁用批量

import { useEffect, useMemo, useState } from "react";
import { zh } from "../../i18n/zh";

interface EvoItem {
  id: string;
  ts: string;
  status: string;
  priority: string;
  requires_human: boolean;
  content: string;
  impact_hint?: string;
  rejected_reason?: string;
  reviewed_at?: string | null;
  executed_at?: string | null;
  verified_at?: string | null;
}

interface EvoDetail extends EvoItem {
  scope?: string;
  evidence?: string;
  impact_scope?: string;
  impact_files?: string[];
  reason_history?: { reason: string; at: string }[];
}

interface EvoDiff {
  id: string;
  impact_files?: string[];
  actions?: Record<string, unknown>[];
  note?: string;
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

const TABS: { key: string; label: string }[] = [
  { key: "pending_review", label: "🔔 待审批" },
  { key: "accepted", label: "✅ 已接受" },
  { key: "rejected", label: "❌ 已拒绝" },
  { key: "executed", label: "⚙ 已执行" },
  { key: "", label: "全部" },
];

function fmtTs(ts: string | undefined | null): string {
  if (!ts) return "";
  const d = new Date(ts);
  if (Number.isNaN(d.getTime())) return ts.slice(0, 16);
  return `${d.getMonth() + 1}-${d.getDate()} ${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
}

export function EvolutionPanel() {
  const [items, setItems] = useState<EvoItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [tab, setTab] = useState("pending_review");
  const [expanded, setExpanded] = useState<string | null>(null);
  const [detail, setDetail] = useState<Record<string, EvoDetail>>({});
  const [viewerSummary, setViewerSummary] = useState<EvoItem | null>(null);
  const [viewerDetail, setViewerDetail] = useState<EvoDetail | null>(null);
  const [viewerDiff, setViewerDiff] = useState<EvoDiff | null>(null);
  const [viewerLoading, setViewerLoading] = useState(false);
  const [viewerError, setViewerError] = useState("");
  const [viewerDiffMessage, setViewerDiffMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [actionMsg, setActionMsg] = useState("");
  const [confirmMsg, setConfirmMsg] = useState("");
  const [confirm, setConfirm] = useState<{ id: string; decision: string; requires_human?: boolean } | null>(null);
  const [rejectReason, setRejectReason] = useState("");
  const [extraConfirmChecked, setExtraConfirmChecked] = useState(false); // 涉边界单条批准额外确认勾选（批 1 #9）
  const [selected, setSelected] = useState<Set<string>>(new Set());

  const load = (keepTab = true) => {
    setLoading(true);
    const statusQ = keepTab && tab ? `&status=${encodeURIComponent(tab)}` : "";
    void fetch(`/api/v1/evolution/list?limit=200${statusQ}`)
      .then((r) => (r.ok ? r.json() : { suggestions: [] }))
      .then((d) => setItems(d.suggestions ?? []))
      .catch(() => setItems([]))
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    load();
    const t = window.setInterval(() => load(), 30000);
    return () => window.clearInterval(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tab]);

  const fetchDetail = (id: string) => {
    if (detail[id]) return;
    void fetch(`/api/v1/evolution/detail?id=${encodeURIComponent(id)}`)
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => d && setDetail((prev) => ({ ...prev, [id]: d })))
      .catch(() => undefined);
  };

  const openViewer = (item: EvoItem) => {
    setViewerSummary(item);
    setViewerDetail(null);
    setViewerDiff(null);
    setViewerError("");
    setViewerDiffMessage("");
    setViewerLoading(true);

    void (async () => {
      try {
        const detailResp = await fetch(`/api/v1/evolution/detail?id=${encodeURIComponent(item.id)}`);
        const detailBody = await detailResp.json().catch(() => ({}));
        if (!detailResp.ok) {
          throw new Error(String(detailBody.detail || detailBody.message || `详情读取失败(${detailResp.status})`));
        }
        const fullDetail = detailBody as EvoDetail;
        setViewerDetail(fullDetail);
        setDetail((prev) => ({ ...prev, [item.id]: fullDetail }));

        try {
          const diffResp = await fetch(`/api/v1/evolution/diff?id=${encodeURIComponent(item.id)}`);
          const diffBody = await diffResp.json().catch(() => ({}));
          if (diffResp.ok) {
            setViewerDiff(diffBody as EvoDiff);
          } else {
            setViewerDiffMessage(String(diffBody.detail || diffBody.message || "暂无关联改动摘要。"));
          }
        } catch (err) {
          setViewerDiffMessage(`改动摘要读取失败：${err instanceof Error ? err.message : String(err)}`);
        }
      } catch (err) {
        setViewerError(err instanceof Error ? err.message : String(err));
      } finally {
        setViewerLoading(false);
      }
    })();
  };

  const closeViewer = () => {
    setViewerSummary(null);
    setViewerDetail(null);
    setViewerDiff(null);
    setViewerError("");
    setViewerDiffMessage("");
    setViewerLoading(false);
  };

  const review = (id: string, decision: string, reason: string, extraConfirm = false) => {
    setBusy(true);
    setActionMsg("");
    setConfirmMsg("");
    return fetch("/api/v1/evolution/review", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        id,
        decision,
        reason,
        expected_status: "pending_review", // CAS：仅待审批可操作
        extra_confirm: extraConfirm, // 涉边界项单条批准额外确认（Approval UX v2 批 1）
      }),
    })
      .then(async (r) => {
        const d = await r.json().catch(() => ({ message: r.statusText }));
        const message = r.ok
          ? String(d.message || "已处理")
          : `⚠️ ${String(d.detail || d.message || `失败(${r.status})`)}`;
        setActionMsg(message);
        setConfirmMsg(message);
        if (r.status === 409 || r.ok) load();
        return r.ok; // 成功才关闭；失败原因必须留在当前弹窗内可见
      })
      .catch((err) => {
        const message = `请求失败: ${String(err)}`;
        setActionMsg(message);
        setConfirmMsg(message);
        return false;
      })
      .finally(() => setBusy(false));
  };

  const batchApprove = () => {
    if (selected.size === 0) return;
    setBusy(true);
    setActionMsg("");
    const itemsReq = Array.from(selected).map((id) => ({
      id,
      decision: "accepted",
      expected_status: "pending_review",
    }));
    return fetch("/api/v1/evolution/review-batch", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ items: itemsReq, decision: "accepted" }),
    })
      .then(async (r) => {
        const d = await r.json().catch(() => ({ results: [] }));
        const ok = d.ok_count ?? 0;
        const fail = d.fail_count ?? 0;
        setActionMsg(`批量完成：成功 ${ok} / 失败 ${fail}`);
        setSelected(new Set());
        load();
      })
      .catch((err) => setActionMsg(`批量请求失败: ${String(err)}`))
      .finally(() => setBusy(false));
  };

  const pendingCount = items.filter((i) => i.status === "pending_review").length;
  const tabItems = useMemo(
    () => (tab ? items.filter((i) => i.status === tab) : items),
    [items, tab]
  );

  const toggleSelect = (id: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  return (
    <div className="v2-evo" data-testid="evolution-panel">
      <div className="v2-evo-head">
        <span className="v2-evo-title">📋 {zh.evolutionTitle}</span>
        {pendingCount > 0 && (
          <span className="v2-evo-pending-badge">{pendingCount} 待审批</span>
        )}
        <button type="button" className="v2-icon-btn" title={zh.refresh} onClick={() => load()}>
          ⟳
        </button>
      </div>

      {/* 分类 Tab */}
      <div className="v2-evo-tabs" data-testid="evo-tabs">
        {TABS.map((t) => (
          <button
            key={t.key || "all"}
            type="button"
            className={`v2-evo-tab ${tab === t.key ? "active" : ""}`}
            onClick={() => {
              setTab(t.key);
              setSelected(new Set());
            }}
          >
            {t.label}
          </button>
        ))}
      </div>

      {/* 面板级操作反馈（UX 修复: 原渲染在条目 map 内，条目刷新消失后消息跟着消失 → 用户感知"没反应"） */}
      {actionMsg && (
        <div className="v2-evo-action-msg" data-testid="evo-action-msg">{actionMsg}</div>
      )}

      {/* 批量栏（仅待审批 Tab + 有可选） */}
      {tab === "pending_review" && selected.size > 0 && (
        <div className="v2-evo-batchbar" data-testid="evo-batchbar">
          <span>已选 {selected.size} 条</span>
          <button type="button" className="v2-evo-btn approve" disabled={busy} onClick={batchApprove}>
            批量批准
          </button>
          <button
            type="button"
            className="v2-evo-btn ghost"
            disabled={busy}
            onClick={() => setSelected(new Set())}
          >
            清除
          </button>
        </div>
      )}

      <div className="v2-evo-body">
        {loading ? (
          <div className="v2-tree-loading">加载中…</div>
        ) : tabItems.length === 0 ? (
          <div className="v2-tree-loading">（无演进建议）</div>
        ) : (
          tabItems.map((it) => (
            <div
              key={it.id}
              className={`v2-evo-item ${it.status === "pending_review" ? "pending" : ""}`}
              data-testid="evo-item"
            >
              <div className="v2-evo-row">
                {it.status === "pending_review" && (
                  <input
                    type="checkbox"
                    className="v2-evo-check"
                    disabled={it.requires_human}
                    title={it.requires_human ? "涉边界不可批量" : "勾选批量"}
                    checked={selected.has(it.id)}
                    onChange={() => toggleSelect(it.id)}
                    onClick={(e) => e.stopPropagation()}
                  />
                )}
                <span
                  className="v2-evo-id"
                  title={it.id}
                  onClick={() => {
                    setExpanded(expanded === it.id ? null : it.id);
                    if (expanded !== it.id) fetchDetail(it.id);
                  }}
                >
                  {it.id}
                </span>
                <span className="v2-evo-status" style={{ color: STATUS_COLOR[it.status] ?? "inherit" }}>
                  {STATUS_LABEL[it.status] ?? it.status}
                </span>
                {it.priority && <span className="v2-evo-priority">{it.priority}</span>}
                <span className="v2-evo-ts">{fmtTs(it.ts)}</span>
              </div>
              <div className="v2-evo-summary">{it.content}</div>
              {it.impact_hint && <div className="v2-evo-impact">📎 影响面：{it.impact_hint}</div>}
              <div className="v2-evo-card-actions">
                <button
                  type="button"
                  className="v2-evo-btn ghost"
                  data-testid={`evo-view-${it.id}`}
                  onClick={(e) => {
                    e.stopPropagation();
                    openViewer(it);
                  }}
                >
                  查看详情
                </button>
              </div>
              {expanded === it.id && (
                <div className="v2-evo-detail" data-testid="evo-detail">
                  {it.requires_human && <div className="v2-evo-note">⚠ 需人工确认（涉边界，禁止批量）</div>}
                  {detail[it.id]?.evidence && <div className="v2-evo-note">证据：{detail[it.id]?.evidence}</div>}
                  {(detail[it.id]?.impact_files?.length ?? 0) > 0 && (
                    <div className="v2-evo-note">影响文件：{(detail[it.id]?.impact_files ?? []).join(", ")}</div>
                  )}
                  {it.executed_at && <div className="v2-evo-note">执行于 {fmtTs(it.executed_at)}</div>}
                  {it.reviewed_at && <div className="v2-evo-note">审批于 {fmtTs(it.reviewed_at)}</div>}
                  {it.status === "rejected" && it.rejected_reason && (
                    <div className="v2-evo-note reject-reason">理由：{it.rejected_reason}</div>
                  )}
                  {it.status === "pending_review" && (
                    <div className="v2-evo-actions" data-testid="evo-actions">
                      <button
                        className="v2-evo-btn approve"
                        data-testid="evo-approve"
                        disabled={busy}
                        onClick={(e) => {
                          e.stopPropagation();
                          setRejectReason("");
                          setExtraConfirmChecked(false);
                          setConfirmMsg("");
                          setConfirm({ id: it.id, decision: "accepted", requires_human: it.requires_human });
                        }}
                      >
                        ✅ 批准
                      </button>
                      <button
                        className="v2-evo-btn reject"
                        data-testid="evo-reject"
                        disabled={busy}
                        onClick={(e) => {
                          e.stopPropagation();
                          setRejectReason("");
                          setExtraConfirmChecked(false);
                          setConfirmMsg("");
                          setConfirm({ id: it.id, decision: "rejected", requires_human: it.requires_human });
                        }}
                      >
                        ❌ 拒绝
                      </button>
                    </div>
                  )}
                  {it.status !== "pending_review" && <div className="v2-evo-hint">{zh.evoHint}</div>}
                </div>
              )}
            </div>
          ))
        )}
      </div>

      {/* 完整建议审阅层：只读读取既有 detail/diff API，审批仍走原 review 契约。 */}
      {viewerSummary && (
        <div
          className="v2-evo-modal"
          data-testid="evo-detail-modal"
          role="dialog"
          aria-modal="true"
          aria-label={`演进建议 ${viewerSummary.id} 详情`}
          onMouseDown={(event) => {
            if (event.currentTarget === event.target) closeViewer();
          }}
        >
          <div className="v2-evo-modal-box v2-evo-detail-box">
            <div className="v2-evo-detail-head">
              <div>
                <div className="v2-evo-modal-title">演进建议 · {viewerSummary.id}</div>
                <div className="v2-evo-detail-meta">
                  <span style={{ color: STATUS_COLOR[viewerDetail?.status ?? viewerSummary.status] ?? "inherit" }}>
                    {STATUS_LABEL[viewerDetail?.status ?? viewerSummary.status] ?? (viewerDetail?.status ?? viewerSummary.status)}
                  </span>
                  {(viewerDetail?.priority ?? viewerSummary.priority) && (
                    <span>优先级：{viewerDetail?.priority ?? viewerSummary.priority}</span>
                  )}
                  <span>{fmtTs(viewerDetail?.ts ?? viewerSummary.ts)}</span>
                </div>
              </div>
              <button type="button" className="v2-icon-btn" onClick={closeViewer} aria-label="关闭演进建议详情">✕</button>
            </div>

            <div className="v2-evo-detail-scroll">
              {viewerLoading && <div className="v2-tree-loading">正在读取完整内容…</div>}
              {viewerError && (
                <div className="v2-evo-action-msg" role="alert" data-testid="evo-detail-error">
                  ⚠️ {viewerError}
                </div>
              )}
              {viewerDetail && (
                <>
                  {viewerDetail.requires_human && (
                    <div className="v2-evo-note">⚠ 需人工确认（涉边界，禁止批量）</div>
                  )}
                  <section className="v2-evo-detail-section">
                    <h4>建议内容</h4>
                    <div className="v2-evo-detail-content" data-testid="evo-detail-content">
                      {viewerDetail.content || "（无正文）"}
                    </div>
                  </section>
                  <div className="v2-evo-detail-grid">
                    <section className="v2-evo-detail-section">
                      <h4>作用域</h4>
                      <div>{viewerDetail.scope || "—"}</div>
                    </section>
                    <section className="v2-evo-detail-section">
                      <h4>影响范围</h4>
                      <div>{viewerDetail.impact_scope || viewerSummary.impact_hint || "—"}</div>
                    </section>
                  </div>
                  <section className="v2-evo-detail-section">
                    <h4>证据 / 依据</h4>
                    <div className="v2-evo-detail-content">{viewerDetail.evidence || "（未附证据文本）"}</div>
                  </section>
                  <section className="v2-evo-detail-section">
                    <h4>影响文件</h4>
                    {(viewerDetail.impact_files?.length ?? 0) > 0 ? (
                      <ul className="v2-evo-detail-list">
                        {(viewerDetail.impact_files ?? []).map((path) => <li key={path}>{path}</li>)}
                      </ul>
                    ) : <div>（无文件清单）</div>}
                  </section>
                  <section className="v2-evo-detail-section">
                    <h4>关联改动摘要</h4>
                    {viewerDiff ? (
                      <>
                        {viewerDiff.note && <div className="v2-evo-hint">{viewerDiff.note}</div>}
                        {(viewerDiff.actions?.length ?? 0) > 0 ? (
                          <div className="v2-evo-diff-actions" data-testid="evo-diff-actions">
                            {(viewerDiff.actions ?? []).map((action, index) => (
                              <pre key={index} className="v2-evo-diff-action">{JSON.stringify(action, null, 2)}</pre>
                            ))}
                          </div>
                        ) : <div>（无 action 摘要）</div>}
                      </>
                    ) : <div className="v2-evo-hint">{viewerDiffMessage || "正在读取改动摘要…"}</div>}
                  </section>
                  {(viewerDetail.reason_history?.length ?? 0) > 0 && (
                    <section className="v2-evo-detail-section">
                      <h4>理由历史</h4>
                      <ul className="v2-evo-detail-list">
                        {(viewerDetail.reason_history ?? []).map((entry, index) => (
                          <li key={`${entry.at}-${index}`}>{fmtTs(entry.at)} · {entry.reason}</li>
                        ))}
                      </ul>
                    </section>
                  )}
                  <section className="v2-evo-detail-section">
                    <h4>状态时间</h4>
                    <div className="v2-evo-detail-meta v2-evo-detail-meta-wrap">
                      {viewerDetail.reviewed_at && <span>审批：{fmtTs(viewerDetail.reviewed_at)}</span>}
                      {viewerDetail.executed_at && <span>执行：{fmtTs(viewerDetail.executed_at)}</span>}
                      {viewerDetail.verified_at && <span>验证：{fmtTs(viewerDetail.verified_at)}</span>}
                      {!viewerDetail.reviewed_at && !viewerDetail.executed_at && !viewerDetail.verified_at && <span>尚无后续状态时间</span>}
                    </div>
                    {viewerDetail.status === "rejected" && viewerDetail.rejected_reason && (
                      <div className="v2-evo-note reject-reason">拒绝理由：{viewerDetail.rejected_reason}</div>
                    )}
                  </section>
                </>
              )}
            </div>
            <div className="v2-evo-modal-actions v2-evo-detail-actions">
              {viewerDetail?.status === "pending_review" && (
                <>
                  <button
                    type="button"
                    className="v2-evo-btn approve"
                    data-testid="evo-detail-approve"
                    disabled={busy}
                    onClick={() => {
                      setRejectReason("");
                      setExtraConfirmChecked(false);
                      setConfirmMsg("");
                      setConfirm({ id: viewerDetail.id, decision: "accepted", requires_human: viewerDetail.requires_human });
                    }}
                  >
                    ✅ 批准
                  </button>
                  <button
                    type="button"
                    className="v2-evo-btn reject"
                    data-testid="evo-detail-reject"
                    disabled={busy}
                    onClick={() => {
                      setRejectReason("");
                      setExtraConfirmChecked(false);
                      setConfirmMsg("");
                      setConfirm({ id: viewerDetail.id, decision: "rejected", requires_human: viewerDetail.requires_human });
                    }}
                  >
                    ❌ 拒绝
                  </button>
                </>
              )}
              <button type="button" className="v2-evo-btn ghost" onClick={closeViewer}>关闭</button>
            </div>
          </div>
        </div>
      )}

      {/* 二次确认弹层 */}
      {confirm && (
        <div className="v2-evo-modal" data-testid="evo-confirm-modal">
          <div className="v2-evo-modal-box">
            <div className="v2-evo-modal-title">
              {confirm.decision === "accepted" ? "确认批准" : "确认拒绝"} {confirm.id}？
            </div>
            {confirm.decision === "accepted" ? (
              <div className="v2-evo-modal-note">
                批准后按权限自动执行（EVOLVE_LOCAL_EXEC 分级）。
                {confirm.requires_human && (
                  <label className="v2-evo-modal-check">
                    <input
                      type="checkbox"
                      data-testid="evo-extra-confirm"
                      checked={extraConfirmChecked}
                      onChange={(e) => setExtraConfirmChecked(e.target.checked)}
                    />
                    我已知悉此建议涉及安全边界，确认单条批准
                  </label>
                )}
              </div>
            ) : (
              <div className="v2-evo-modal-note">
                拒绝理由（必填，留痕）：
                <input
                  className="v2-evo-reason-input"
                  data-testid="evo-reason-input"
                  value={rejectReason}
                  maxLength={500}
                  onChange={(e) => setRejectReason(e.target.value)}
                  placeholder="请输入拒绝理由…"
                />
              </div>
            )}
            {confirmMsg ? (
              <div className="v2-evo-action-msg" role="status" data-testid="evo-confirm-message">
                {confirmMsg}
              </div>
            ) : null}
            {confirm.decision === "accepted" && confirm.requires_human && !extraConfirmChecked ? (
              <div className="v2-evo-action-msg">请先勾选安全边界确认，再执行批准。</div>
            ) : null}
            <div className="v2-evo-modal-actions">
              <button
                className="v2-evo-btn approve"
                disabled={
                  busy ||
                  (confirm.decision === "rejected" && !rejectReason.trim()) ||
                  (confirm.decision === "accepted" && confirm.requires_human && !extraConfirmChecked)
                }
                data-testid="evo-confirm-ok"
                onClick={() => {
                  void review(
                    confirm.id,
                    confirm.decision,
                    confirm.decision === "rejected" ? rejectReason.trim() : "",
                    confirm.requires_human ? extraConfirmChecked : false
                  ).then((ok) => {
                    if (ok) {
                      setConfirm(null); // UX 修复: 成功才关弹窗；失败保持弹窗可重试（消息面板级显示）
                      setRejectReason("");
                      setExtraConfirmChecked(false);
                      setConfirmMsg("");
                      if (viewerSummary?.id === confirm.id) closeViewer();
                    }
                  });
                }}
              >
                {busy ? "处理中…" : "确定"}
              </button>
              <button
                className="v2-evo-btn ghost"
                onClick={() => {
                  setConfirm(null);
                  setRejectReason("");
                  setExtraConfirmChecked(false);
                  setConfirmMsg("");
                }}
              >
                取消
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
