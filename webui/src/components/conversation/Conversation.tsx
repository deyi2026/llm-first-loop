// Web V2：会话主区（阶段 1 空状态占位；消息流在阶段 2 接入）

import { zh } from "../../i18n/zh";
import { useCurrentSessionId, useSessions } from "../../core/stores";

export function Conversation() {
  const currentId = useCurrentSessionId();
  const sessions = useSessions();
  const current = sessions.find((s) => s.session_id === currentId);

  return (
    <main className="v2-conversation" data-testid="conversation">
      <div className="v2-conversation-empty">
        <h2>{zh.emptyHeroTitle}</h2>
        <p>{zh.emptyHeroSub}</p>
        {current && (
          <div className="v2-kv" style={{ marginTop: 12, maxWidth: 320 }}>
            <span className="k">当前会话</span>
            <span className="v">{current.title || current.session_id}</span>
            <span className="k">消息数</span>
            <span className="v">{current.message_count}</span>
          </div>
        )}
        <p style={{ fontSize: 12, opacity: 0.7 }}>{zh.stage1Note}</p>
      </div>
    </main>
  );
}
