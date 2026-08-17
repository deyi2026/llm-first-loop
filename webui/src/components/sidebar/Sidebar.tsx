// Web V2：侧边栏（会话列表：搜索/置顶/删除/分支/新会话；来源通道标签；激活态）
// 阶段 3：管理交互（pin/delete 两步确认/fork）——删除与分支后自动刷新并切换。

import { useEffect, useState } from "react";
import { channelLabel, deleteSession, forkSession, setSessionPin, type SessionMeta } from "../../core/api";
import { refreshSessionsAndCurrent } from "../../core/events";
import { sessionStore, useCurrentSessionId, useSessions } from "../../core/stores";
import { conversationStore } from "../../core/conversation";
import { loadHistory } from "../../core/conversation";
import { WorkspaceGroups, formatRelative } from "./WorkspaceGroups";
import { FileTree } from "./FileTree";
import { zh } from "../../i18n/zh";

export function Sidebar({ collapsed }: { collapsed: boolean }) {
  const sessions = useSessions();
  const currentId = useCurrentSessionId();
  const [query, setQuery] = useState("");
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null);
  // 对齐 DSH：侧栏视图切换（会话列表 ↔ 文件树）
  const [view, setView] = useState<"sessions" | "files">("sessions");

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
    sessionStore.setCurrentSession("");
    conversationStore.setState({
      messages: [],
      hasMoreHistory: false,
      loadedHistoryCount: 0,
      streamStartedAt: null,
    });
  };

  const handleDelete = async (sid: string) => {
    if (confirmDelete !== sid) {
      setConfirmDelete(sid); // 两步确认：再次点击才执行
      window.setTimeout(() => setConfirmDelete((v) => (v === sid ? null : v)), 3000);
      return;
    }
    setConfirmDelete(null);
    const ok = await deleteSession(sid);
    if (ok && currentId === sid) {
      sessionStore.setCurrentSession("");
      conversationStore.setState({
        messages: [],
        hasMoreHistory: false,
        loadedHistoryCount: 0,
        streamStartedAt: null,
      });
    }
    await refreshSessionsAndCurrent();
  };

  const handleFork = async (sid: string) => {
    const report = await forkSession(sid);
    if (report?.new_session_id) {
      sessionStore.setCurrentSession(report.new_session_id);
      await refreshSessionsAndCurrent();
      await loadHistory(report.new_session_id);
    }
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
      <button type="button" className="v2-new-session" data-testid="new-session" onClick={handleNew}>
        ＋ {zh.newSession}
      </button>
      <div className="v2-sidebar-tabs">
        <button
          type="button"
          className={`v2-tab ${view === "sessions" ? "active" : ""}`}
          onClick={() => setView("sessions")}
          data-testid="tab-sessions"
        >
          💬 {zh.sessions}
        </button>
        <button
          type="button"
          className={`v2-tab ${view === "files" ? "active" : ""}`}
          onClick={() => setView("files")}
          data-testid="tab-files"
        >
          📁 {zh.fileTree}
        </button>
      </div>
      {view === "files" ? (
        <FileTree />
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
          {filtered.map((s: SessionMeta) => (
            <div
              key={s.session_id}
              className={`v2-session-item-wrap ${s.session_id === currentId ? "active" : ""}`}
              data-testid="session-item"
            >
              <button
                type="button"
                className="v2-session-item"
                onClick={() => sessionStore.setCurrentSession(s.session_id)}
              >
                <span className="v2-session-title">
                  {s.pinned ? "📌 " : ""}
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
                <button
                  type="button"
                  className="v2-icon-btn"
                  title={s.pinned ? "取消置顶" : "置顶"}
                  onClick={() => void setSessionPin(s.session_id, !s.pinned).then(() => refreshSessionsAndCurrent())}
                >
                  📌
                </button>
                <button
                  type="button"
                  className="v2-icon-btn"
                  title="在新会话中分支"
                  onClick={() => void handleFork(s.session_id)}
                >
                  ⑂
                </button>
                <button
                  type="button"
                  className={`v2-icon-btn danger ${confirmDelete === s.session_id ? "confirming" : ""}`}
                  title={confirmDelete === s.session_id ? "再次点击确认删除" : "删除会话"}
                  onClick={() => void handleDelete(s.session_id)}
                >
                  {confirmDelete === s.session_id ? "确认?" : "🗑"}
                </button>
              </div>
            </div>
          ))}
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
