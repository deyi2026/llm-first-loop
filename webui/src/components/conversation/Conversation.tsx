// Web V2：会话主区（消息列表 + 输入区；会话切换时加载历史）

import { useEffect, useState } from "react";
import { MessageList } from "./MessageList";
import { ChatQueue } from "./ChatQueue";
import { Composer } from "./Composer";
import { SessionStats } from "./SessionStats";
import { ContinuityBanner } from "./ContinuityBanner";
import { ScheduleCatalog } from "./ScheduleCatalog";
import { JobsCatalog } from "./JobsCatalog";
import { SubagentLineage } from "./SubagentLineage";
import { useCurrentSessionId, useSessions } from "../../core/stores";
import { fetchAllMessages } from "../../core/api";
import { conversationStore, loadHistory, useConversation } from "../../core/conversation";
import { errorRecoveryHint } from "../../core/errorRecovery";
import { zh } from "../../i18n/zh";

export function Conversation() {
  const [exporting, setExporting] = useState(false);
  const [exportError, setExportError] = useState("");
  const [retryingHistory, setRetryingHistory] = useState(false);
  const [loadingHistoryFor, setLoadingHistoryFor] = useState<string | null>(null);
  const currentId = useCurrentSessionId();
  const sessions = useSessions();
  const conv = useConversation();
  const current = sessions.find((s) => s.session_id === currentId);
  const historyError = Boolean(conv.lastError && /会话历史|历史读取|更早历史/.test(conv.lastError));

  useEffect(() => {
    let active = true;
    setExportError("");
    setRetryingHistory(false);
    if (currentId) {
      setLoadingHistoryFor(currentId);
      void loadHistory(currentId).finally(() => {
        if (active) setLoadingHistoryFor(null);
      });
    } else {
      setLoadingHistoryFor(null);
      conversationStore.setState({ messages: [], hasMoreHistory: false, loadedHistoryCount: 0 });
    }
    return () => { active = false; };
  }, [currentId]);

  const doExport = async (sid: string) => {
    setExporting(true);
    setExportError("");
    try {
      const msgs = await fetchAllMessages(sid);
      const lines: string[] = [`# 会话导出：${current?.title ?? sid}`, ""];
      for (const m of msgs) {
        const role = m.role === "user" ? "👤 用户" : m.role === "assistant" ? "🤖 助手" : `⚙️ ${m.role}`;
        lines.push(`## ${role}`, "", m.content ?? "", "");
      }
      const blob = new Blob([lines.join("\n")], { type: "text/markdown;charset=utf-8" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `session-${sid.slice(0, 8)}.md`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (error) {
      const detail = error instanceof Error ? error.message : String(error);
      setExportError(`导出失败：${detail || "请重试"}`);
    } finally {
      setExporting(false);
    }
  };

  const retryHistory = async () => {
    if (!currentId || retryingHistory) return;
    setRetryingHistory(true);
    try {
      // A read-only retry never sends a new user turn or starts another Run.
      await loadHistory(currentId);
    } finally {
      setRetryingHistory(false);
    }
  };

  return (
    <main className="v2-conversation" data-testid="conversation">
      {current && conv.backgroundRunning && (
        <div className="v2-bg-running" data-testid="bg-running">
          ⏳ 后台任务生成中（刷新/切换不会中断，完成后自动显示结果）
        </div>
      )}
      {currentId ? <ContinuityBanner sessionId={currentId} /> : null}
      {current && (
        <>
          <div className="v2-conversation-header">
            <span className="v2-conversation-title">{current.title || current.session_id}</span>
            <div className="v2-conversation-header-actions">
              {currentId && <SessionStats sessionId={currentId} />}
              <SubagentLineage />
              <ScheduleCatalog />
              <JobsCatalog />
              <div className="v2-header-actions-spacer" />
              <button
                type="button"
                className="v2-btn ghost"
                disabled={exporting}
                title={zh.exportSession}
                onClick={() => void doExport(current.session_id)}
                data-testid="export-btn"
              >
                {exporting ? zh.exporting : "⭳ 导出"}
              </button>
            </div>
          </div>
          {exportError || conv.lastError ? (
            <div className={`v2-conv-error ${historyError && !exportError ? "v2-history-error" : ""}`} role="alert">
              <div className="v2-conv-error-copy">
                {exportError || conv.lastError}
                {conv.lastError && !exportError ? (
                  <p>{historyError
                    ? conv.backgroundRunning
                      ? "历史记录仍保留；当前任务仍在运行。重试只读取消息，不会重复执行任务。"
                      : "历史记录仍保留。重试只读取消息，不会发送新的任务。"
                    : errorRecoveryHint(conv.lastError)}</p>
                ) : null}
              </div>
              {historyError && !exportError ? (
                <button
                  type="button"
                  className="v2-btn ghost v2-history-retry"
                  disabled={retryingHistory}
                  onClick={() => void retryHistory()}
                  data-testid="history-retry"
                >
                  {retryingHistory ? "读取中…" : "重新读取"}
                </button>
              ) : null}
            </div>
          ) : null}
        </>
      )}
      <MessageList historyLoading={Boolean(currentId && loadingHistoryFor === currentId)} />
      <ChatQueue />
      <Composer />
    </main>
  );
}
