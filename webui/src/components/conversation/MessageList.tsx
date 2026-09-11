// Web V2：消息列表（滚动跟随/回到底部/加载更早；流式期间自动跟随）

import { useEffect, useMemo, useRef, useState } from "react";
import { MessageItem, extractProducedPaths } from "./MessageItem";
import { loadEarlierHistory, useConversation } from "../../core/conversation";
import { sessionStore } from "../../core/stores";
import { projectToolActivityMessages } from "../../core/toolActivity";
import { zh } from "../../i18n/zh";

export function MessageList() {
  const conv = useConversation();
  const [atBottom, setAtBottom] = useState(true);
  const scrollRef = useRef<HTMLDivElement>(null);

  // 展示层机械聚合 assistant(tool_calls) ↔ tool(receipt)。原始历史数组保持不变。
  const projectedMessages = useMemo(() => projectToolActivityMessages(conv.messages), [conv.messages]);

  // 会话级出产物集合（对齐 DSH turn 级 deliverables）：跨消息累积 edit_file 路径，
  // 供最终回答正文中的路径引用可点击打开（编辑与引用通常在不同消息）
  const producedPaths = useMemo(() => {
    const out: string[] = [];
    for (const { msg: m } of projectedMessages) {
      for (const p of extractProducedPaths(m.toolCalls)) {
        if (!out.includes(p)) out.push(p);
      }
    }
    return new Set(out);
  }, [projectedMessages]);

  const updateBottom = () => {
    const el = scrollRef.current;
    if (!el) return;
    setAtBottom(el.scrollHeight - el.scrollTop - el.clientHeight < 120);
  };

  // 消息变化（含流式增量）→ 底部态跟随滚动
  useEffect(() => {
    const el = scrollRef.current;
    if (el && atBottom) {
      el.scrollTop = el.scrollHeight;
    }
  }, [conv.messages, atBottom]);

  if (conv.messages.length === 0) {
    return (
      <div className="v2-conversation-empty" data-testid="empty-state">
        <h2>{zh.emptyHeroTitle}</h2>
        <p>{zh.emptyHeroSub}</p>
      </div>
    );
  }

  return (
    <div
      className="v2-message-list"
      ref={scrollRef}
      onScroll={updateBottom}
      data-testid="message-list"
    >
      {conv.hasMoreHistory && (
        <button
          type="button"
          className="v2-load-earlier"
          onClick={() => {
            const sid = sessionStore.getState().currentSessionId;
            if (sid) void loadEarlierHistory(sid);
          }}
        >
          ↑ {zh.loadEarlier}
        </button>
      )}
      {projectedMessages.map(({ msg: m, originalIndex }) => (
        <MessageItem
          key={`${originalIndex}:${m.role}:${m.sourceIndex ?? "live"}`}
          msg={m}
          index={m.sourceIndex}
          sessionId={sessionStore.getState().currentSessionId ?? undefined}
          producedPaths={producedPaths}
        />
      ))}
      {!atBottom && (
        <button
          type="button"
          className="v2-scroll-bottom"
          onClick={() => {
            const el = scrollRef.current;
            if (el) el.scrollTop = el.scrollHeight;
          }}
        >
          ↓ {zh.backToBottom}
        </button>
      )}
    </div>
  );
}
