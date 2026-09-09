// Web V2：侧边栏（会话列表：搜索/置顶/删除/分支/新会话；来源通道标签；激活态）
// 阶段 3：管理交互（pin/delete 两步确认/fork）——删除与分支后自动刷新并切换。

import { useEffect, useState } from "react";
import { channelLabel, archiveSession, deleteSession, fetchAgentsTree, fetchSessions, forkSession, setSessionPin, type SessionMeta } from "../../core/api";
import { refreshSessionsAndCurrent } from "../../core/events";
import { useCapabilities } from "../../core/capabilities";
import {
  sessionStore,
  sidebarViewStore,
  useCurrentSessionId,
  useSessions,
  useSidebarView,
} from "../../core/stores";
import { conversationStore } from "../../core/conversation";
import { loadHistory } from "../../core/conversation";
import { WorkspaceGroups, formatRelative } from "./WorkspaceGroups";
import { FileTree } from "./FileTree";
import { EvolutionPanel } from "./EvolutionPanel";
import { zh } from "../../i18n/zh";

export function Sidebar({ collapsed }: { collapsed: boolean }) {
  const caps = useCapabilities();
  const sessions = useSessions();
  const currentId = useCurrentSessionId();
  const [query, setQuery] = useState("");
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null);
  const [busyAction, setBusyAction] = useState<string | null>(null);
  const [actionError, setActionError] = useState("");
  // 侧栏视图也可由顶栏真实导航动作驱动。
  const view = useSidebarView();
  // 2026-08-21: 归档文件夹——旧会话收拢防误操作（fetchSessions(true) 含归档）
  const [archived, setArchived] = useState<SessionMeta[]>([]);
  useEffect(() => {
    if (view === "archived") {
      void fetchSessions(true).then((list) =>
        setArchived(list.filter((s) => s.status === "archived"))
      );
    }
  }, [view]);
  // 对齐 DSH 会话树：parent_id 映射（fetchAgentsTree 合并——会话树状层级）
  const [parentMap, setParentMap] = useState<Map<string, string | null>>(new Map());
  // 会话树：展开的父会话集合（默认折叠——每个主会话可展开子代理区域）
  const [expandedSessions, setExpandedSessions] = useState<Set<string>>(new Set());

  useEffect(() => {
    void fetchAgentsTree().then(setParentMap);
  }, []);

  useEffect(() => {
    void refreshSessionsAndCurrent();
  }, []);

  const filtered = sessions.filter((s) => {
    if (!query) return true;
    const q = query.toLowerCase();
    return (
      (s.title || "").toLowerCase().includes(q) ||
      (s.last_message_preview || "").toLowerCase().includes(q)
    );
  });

  const handleNew = () => {
    if (busyAction) return;
    setActionError("");
    sessionStore.setCurrentSession("");
    sessionStore.setNewSessionPending(true);  // 2026-08-18 修复跳回旧会话
    conversationStore.setState({
      messages: [],
      hasMoreHistory: false,
      loadedHistoryCount: 0,
      streamStartedAt: null,
    });
    // 2026-08-19: 清草稿防 Composer 草稿恢复 effect 回填旧输入
    localStorage.removeItem("lfl-draft-new");
  };

  const beginAction = (key: string): boolean => {
    if (busyAction) return false;
    setBusyAction(key);
    setActionError("");
    return true;
  };

  const finishAction = () => setBusyAction(null);

  const handlePin = async (sid: string, pinned: boolean) => {
    if (!beginAction(`pin:${sid}`)) return;
    const ok = await setSessionPin(sid, pinned);
    if (ok) await refreshSessionsAndCurrent();
    else setActionError("置顶状态更新失败；会话未修改，请重试。");
    finishAction();
  };

  const handleArchive = async (sid: string, archivedValue: boolean) => {
    if (!beginAction(`archive:${sid}`)) return;
    const ok = await archiveSession(sid, archivedValue);
    if (ok) {
      if (archivedValue) await refreshSessionsAndCurrent();
      else setArchived((prev) => prev.filter((item) => item.session_id !== sid));
    } else {
      setActionError(archivedValue ? "归档失败；会话未修改，请重试。" : "恢复会话失败，请重试。");
    }
    finishAction();
  };

  const handleDelete = async (sid: string) => {
    if (busyAction) return;
    if (confirmDelete !== sid) {
      setConfirmDelete(sid); // 两步确认：再次点击才执行
      setActionError("");
      window.setTimeout(() => setConfirmDelete((v) => (v === sid ? null : v)), 3000);
      return;
    }
    if (!beginAction(`delete:${sid}`)) return;
    setConfirmDelete(null);
    const ok = await deleteSession(sid);
    if (!ok) {
      setActionError("删除失败；原会话仍保留，请重试。");
      finishAction();
      return;
    }
    if (currentId === sid) {
      sessionStore.setCurrentSession("");
      conversationStore.setState({
        messages: [],
        hasMoreHistory: false,
        loadedHistoryCount: 0,
        streamStartedAt: null,
      });
    }
    await refreshSessionsAndCurrent();
    finishAction();
  };

  const handleFork = async (sid: string) => {
    if (!beginAction(`fork:${sid}`)) return;
    const report = await forkSession(sid);
    if (!report?.new_session_id) {
      setActionError("创建分支失败；原会话未修改，请重试。");
      finishAction();
      return;
    }
    sessionStore.setCurrentSession(report.new_session_id);
    await refreshSessionsAndCurrent();
    await loadHistory(report.new_session_id);
    finishAction();
  };

  if (collapsed) {
    return (
      <aside className="v2-sidebar collapsed" data-testid="sidebar">
        <div className="v2-brand">
          <span className="v2-brand-logo">L</span>
        </div>
      </aside>
    );
  }

  return (
    <aside className="v2-sidebar" data-testid="sidebar">
      <div className="v2-brand">
        <span className="v2-brand-logo">L</span>
        <span>{zh.brand}</span>
        <span style={{ color: "var(--dsw-alias-label-tertiary)", fontWeight: 400, fontSize: 12 }}>
          {zh.brandSub}
        </span>
      </div>
      <button type="button" className="v2-new-session" data-testid="new-session" onClick={handleNew} disabled={Boolean(busyAction)}>
        ＋ {zh.newSession}
      </button>
      <div className="v2-sidebar-tabs">
        <button
          type="button"
          className={`v2-tab ${view === "sessions" ? "active" : ""}`}
          onClick={() => sidebarViewStore.setView("sessions")}
          data-testid="tab-sessions"
        >
          💬 {zh.sessions}
        </button>
        {caps.fsTree ? (
          <button
            type="button"
            className={`v2-tab ${view === "files" ? "active" : ""}`}
            onClick={() => sidebarViewStore.setView("files")}
            data-testid="tab-files"
          >
            📁 {zh.fileTree}
          </button>
        ) : null}
        <button
          type="button"
          className={`v2-tab ${view === "evo" ? "active" : ""}`}
          onClick={() => sidebarViewStore.setView("evo")}
          data-testid="tab-evo"
        >
          📋 {zh.evolutionShort}
        </button>
        <button
          type="button"
          className={`v2-tab ${view === "archived" ? "active" : ""}`}
          onClick={() => sidebarViewStore.setView("archived")}
          data-testid="tab-archived"
        >
          🗄 归档
        </button>
      </div>
      {actionError ? (
        <div className="v2-sidebar-error" role="status" data-testid="sidebar-action-error">
          {actionError}
        </div>
      ) : null}
      {view === "files" && caps.fsTree ? (
        <FileTree sessionId={currentId ?? ""} />
      ) : view === "evo" ? (
        <EvolutionPanel />
      ) : view === "archived" ? (
        <div className="v2-archived-list" data-testid="archived-list">
          {archived.length === 0 ? (
            <div style={{ padding: 12, fontSize: 12, color: "var(--dsw-alias-label-tertiary)" }}>
              （归档文件夹为空）
            </div>
          ) : (
            archived.map((s) => (
              <div key={s.session_id} className="v2-session-row" data-testid="archived-item">
                <button
                  type="button"
                  className="v2-session-item"
                  onClick={() => sessionStore.setCurrentSession(s.session_id)}
                >
                  <span className="v2-session-title">🗄 {s.title || "未命名"}</span>
                  <span className="v2-session-preview">
                    {s.last_message_preview || "（空会话）"}
                    {s.updated_at ? ` · ${formatRelative(s.updated_at)}` : ""}
                  </span>
                  <span className="v2-session-count">{s.message_count} 条 · 已归档</span>
                </button>
                <div className="v2-session-actions">
                  {caps.archive ? (
                    <button
                      type="button"
                      className="v2-icon-btn"
                      title="恢复为活跃会话"
                      disabled={Boolean(busyAction)}
                      onClick={() => void handleArchive(s.session_id, false)}
                    >
                      ↪
                    </button>
                  ) : null}
                </div>
              </div>
            ))
          )}
        </div>
      ) : (
      <>
      <input
        className="v2-session-search"
        type="text"
        placeholder={zh.searchPlaceholder}
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        aria-label={zh.searchPlaceholder}
      />
      <WorkspaceGroups
        activeSessionId={currentId ?? undefined}
        onOpenOtherSession={(_wsId, sid) => {
          // 工作区已由 WorkspaceGroups 切换；打开会话（Conversation 随 currentId 加载历史）
          sessionStore.setCurrentSession(sid);
          void refreshSessionsAndCurrent();
        }}
        onWorkspaceChanged={() => {
          // 新工作区无旧会话上下文：清空当前会话与对话区（对齐 handleNew）
          sessionStore.setCurrentSession("");
          conversationStore.setState({ messages: [], hasMoreHistory: false, loadedHistoryCount: 0 });
          void refreshSessionsAndCurrent();
        }}
      >
        <div className="v2-session-list" data-testid="session-list">
          {(() => {
            // 会话树：按 parent_id 分组（根平铺 + 子代理缩进挂载）
            const ids = new Set(filtered.map((s) => s.session_id));
            const childrenMap = new Map<string, SessionMeta[]>();
            const roots: SessionMeta[] = [];
            for (const s of filtered) {
              const p = parentMap.get(s.session_id);
              if (p && p !== s.session_id && ids.has(p)) {
                const arr = childrenMap.get(p) ?? [];
                arr.push(s);
                childrenMap.set(p, arr);
              } else {
                roots.push(s);
              }
            }
            const renderRow = (s: SessionMeta, depth: number): React.ReactElement => {
              const kids = childrenMap.get(s.session_id) ?? [];
              const isExpanded = expandedSessions.has(s.session_id);
              return (
              <div key={s.session_id}>
                <div
                  className={`v2-session-item-wrap ${s.session_id === currentId ? "active" : ""}`}
                  data-testid="session-item"
                  style={{ paddingLeft: depth > 0 ? 22 : 0 }}
                >
                  {depth > 0 && <span className="v2-tree-branch" aria-hidden />}
                  {depth === 0 && (
                    <button
                      type="button"
                      className="v2-session-arrow"
                      title={isExpanded ? "折叠" : "展开"}
                      onClick={(e) => {
                        e.stopPropagation();
                        setExpandedSessions((prev) => {
                          const n = new Set(prev);
                          if (n.has(s.session_id)) n.delete(s.session_id);
                          else n.add(s.session_id);
                          return n;
                        });
                      }}
                    >
                      {isExpanded ? "▼" : "▶"}
                    </button>
                  )}
                  <button
                    type="button"
                    className="v2-session-item"
                    onClick={() => sessionStore.setCurrentSession(s.session_id)}
                  >
                    <span className="v2-session-title">
                      {s.pinned ? "📌 " : ""}
                      {depth > 0 ? "└ " : ""}
                      {s.title || "未命名"}
                    </span>
                    <span className="v2-session-preview">
                      {s.last_message_preview || "（空会话）"}
                      {s.updated_at ? ` · ${formatRelative(s.updated_at)}` : ""}
                    </span>
                    <span className="v2-session-meta-row">
                      <span className="v2-channel-tag">{channelLabel(s.channel)}</span>
                      {s.session_id.startsWith("subagent_") && (
                        <span className="v2-channel-tag subagent">{zh.subagentTag}</span>
                      )}
                      <span className="v2-session-count">{s.message_count} 条</span>
                    </span>
                  </button>
                  <div className="v2-session-actions" data-testid="session-actions">
                    {caps.pin ? (
                      <button
                        type="button"
                        className="v2-icon-btn"
                        title={s.pinned ? "取消置顶" : "置顶"}
                        disabled={Boolean(busyAction)}
                        onClick={() => void handlePin(s.session_id, !s.pinned)}
                      >
                        📌
                      </button>
                    ) : null}
                    {caps.fork ? (
                      <button
                        type="button"
                        className="v2-icon-btn"
                        title="在新会话中分支"
                        disabled={Boolean(busyAction)}
                        onClick={() => void handleFork(s.session_id)}
                      >
                        ⑂
                      </button>
                    ) : null}
                    {caps.archive ? (
                      <button
                        type="button"
                        className="v2-icon-btn"
                        title="归档到归档文件夹（防误操作）"
                        disabled={Boolean(busyAction)}
                        onClick={() => void handleArchive(s.session_id, true)}
                      >
                        📁
                      </button>
                    ) : null}
                    {caps.delete ? (
                      <button
                        type="button"
                        className={`v2-icon-btn danger ${confirmDelete === s.session_id ? "confirming" : ""}`}
                        title={confirmDelete === s.session_id ? "再次点击确认删除" : "删除会话"}
                        disabled={Boolean(busyAction)}
                        onClick={() => void handleDelete(s.session_id)}
                      >
                        {confirmDelete === s.session_id ? "确认?" : "🗑"}
                      </button>
                    ) : null}
                  </div>
                </div>
                {isExpanded && kids.map((c) => renderRow(c, depth + 1))}
                {isExpanded && kids.length === 0 && (
                  <div className="v2-session-empty-kids" style={{ paddingLeft: 40 }}>
                    （无子代理）
                  </div>
                )}
              </div>
              );
            };
            return roots.map((s) => renderRow(s, 0));
          })()}
          {filtered.length === 0 && (
            <div style={{ padding: 12, fontSize: 12, color: "var(--dsw-alias-label-tertiary)" }}>
              {query ? "无匹配会话" : "暂无会话"}
            </div>
          )}
        </div>
      </WorkspaceGroups>
      </>
      )}
      <div className="v2-sidebar-footer">
        <span>{zh.sessionCount.replace("{n}", String(sessions.length))}</span>
      </div>
    </aside>
  );
}
