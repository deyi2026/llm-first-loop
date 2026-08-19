// Web V2：会话主区（消息列表 + 输入区；会话切换时加载历史）

import { useEffect, useState } from "react";
import { MessageList } from "./MessageList";
import { Composer } from "./Composer";
import { SessionStats } from "./SessionStats";
import { useCurrentSessionId, useSessions } from "../../core/stores";
import { fetchAllMessages } from "../../core/api";
import { conversationStore, loadHistory, useConversation } from "../../core/conversation";
import { zh } from "../../i18n/zh";

export function Conversation() {
  const [exporting, setExporting] = useState(false);
  const currentId = useCurrentSessionId();
  const sessions = useSessions();
  const conv = useConversation();
  const current = sessions.find((s) => s.session_id === currentId);

  useEffect(() => {
    if (currentId) {
      void loadHistory(currentId);
    } else {
      // 新建会话：清空视图并复位归属标记（防旧会话流式终态写入新会话视图）
      conversationStore.setState({
        messages: [],
        hasMoreHistory: false,
        loadedHistoryCount: 0,
        streaming: false,
        streamingIndex: -1,
        backgroundRunning: false,
        lastError: null,
        streamStartedAt: null,
        sessionId: null,
        loading: false,
      });
    }
  }, [currentId]);

  const doExport = async (sid: string) => {
    setExporting(true);
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
    } catch {
      /* 导出失败静默（fail-open，不影响会话） */
    } finally {
      setExporting(false);
    }
  };

  return (
    <main className="v2-conversation" data-testid="conversation">
      {current && conv.backgroundRunning && (
        <div className="v2-bg-running" data-testid="bg-running">
          ⏳ 后台任务生成中（刷新/切换不会中断，完成后自动显示结果）
        </div>
      )}
      {current && (
        <div className="v2-conversation-header">
          <span className="v2-conversation-title">{current.title || current.session_id}</span>
          {conv.lastError && <span className="v2-conv-error">{conv.lastError}</span>}
          {currentId && <SessionStats sessionId={currentId} />}
          <div style={{ flex: 1 }} />
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
      )}
      <MessageList />
      <Composer />
    </main>
  );
}
