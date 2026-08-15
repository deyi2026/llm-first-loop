// Web V2：会话主区（消息列表 + 输入区；会话切换时加载历史）

import { useEffect } from "react";
import { MessageList } from "./MessageList";
import { Composer } from "./Composer";
import { useCurrentSessionId, useSessions } from "../../core/stores";
import { conversationStore, loadHistory, useConversation } from "../../core/conversation";

export function Conversation() {
  const currentId = useCurrentSessionId();
  const sessions = useSessions();
  const conv = useConversation();
  const current = sessions.find((s) => s.session_id === currentId);

  useEffect(() => {
    if (currentId) {
      void loadHistory(currentId);
    } else {
      conversationStore.setState({ messages: [], hasMoreHistory: false, loadedHistoryCount: 0 });
    }
  }, [currentId]);

  return (
    <main className="v2-conversation" data-testid="conversation">
      {current && (
        <div className="v2-conversation-header">
          <span className="v2-conversation-title">{current.title || current.session_id}</span>
          {conv.lastError && <span className="v2-conv-error">{conv.lastError}</span>}
        </div>
      )}
      <MessageList />
      <Composer />
    </main>
  );
}
