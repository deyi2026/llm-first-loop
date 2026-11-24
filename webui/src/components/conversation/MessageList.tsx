// Web V2：消息列表（滚动跟随/回到底部/加载更早；流式期间自动跟随）

import { useEffect, useMemo, useRef, useState } from "react";
import { MessageItem, extractProducedPaths } from "./MessageItem";
import { conversationStore, loadEarlierHistory, loadHistory, useConversation } from "../../core/conversation";
import { sessionStore } from "../../core/stores";
import { projectToolActivityMessages } from "../../core/toolActivity";
import type { ChatMessage } from "../../core/types";
import { zh } from "../../i18n/zh";

export function MessageList({ historyLoading = false }: { historyLoading?: boolean }) {
  const conv = useConversation();
  const sessionId = sessionStore.getState().currentSessionId ?? undefined;
  const [atBottom, setAtBottom] = useState(true);
  const [loadingEarlier, setLoadingEarlier] = useState(false);
  const earlierInFlight = useRef(false);
  const scrollRevision = useRef(0);
  const scrollRef = useRef<HTMLDivElement>(null);
  const rowIdentity = useRef({ next: 0, ids: new WeakMap<ChatMessage, number>() });

  const persistedKey = (message: ChatMessage, originalIndex: number): string => {
    if (message.sourceIndex === undefined) return `live:${originalIndex}`;
    // A prepend retains the original raw message object. A fresh snapshot can
    // replace the same ordinal (e.g. retraction), so reset its local UI state.
    const raw = conv.messages[originalIndex] ?? message;
    const identities = rowIdentity.current;
    let id = identities.ids.get(raw);
    if (id === undefined) {
      id = ++identities.next;
      identities.ids.set(raw, id);
    }
    return `history:${message.sourceIndex}:${id}`;
  };

  // 展示层机械聚合 assistant(tool_calls) ↔ tool(receipt)。原始历史数组保持不变。
  const projectedMessages = useMemo(() => projectToolActivityMessages(conv.messages), [conv.messages]);

  // 会话级出产物集合（对齐 DSH turn 级 deliverables）：跨消息累积 edit_file 路径，
  // 供最终回答正文中的路径引用可点击打开（编辑与引用通常在不同消息）
  const producedPaths = useMemo(() => {
    const out = new Set<string>();
    for (const { msg: m } of projectedMessages) {
      for (const p of extractProducedPaths(m.toolCalls)) {
        out.add(p);
      }
    }
    return out;
  }, [projectedMessages]);

  const updateBottom = () => {
    const el = scrollRef.current;
    if (!el) return;
    scrollRevision.current += 1;
    setAtBottom(el.scrollHeight - el.scrollTop - el.clientHeight < 120);
  };

  // 消息变化（含流式增量）→ 底部态跟随滚动
  useEffect(() => {
    const el = scrollRef.current;
    if (el && atBottom) {
      el.scrollTop = el.scrollHeight;
    }
  }, [conv.messages, atBottom]);

  const loadEarlier = async () => {
    if (earlierInFlight.current) return;
    const sid = sessionStore.getState().currentSessionId;
    if (!sid) return;
    earlierInFlight.current = true;
    setLoadingEarlier(true);
    const node = scrollRef.current;
    const oldHeight = node?.scrollHeight ?? 0;
    const oldTop = node?.scrollTop ?? 0;
    const startRevision = scrollRevision.current;
    setAtBottom(false);
    try {
      await loadEarlierHistory(sid);
    } catch {
      if (sessionStore.getState().currentSessionId === sid) {
        conversationStore.setState({ lastError: "更早历史读取失败，请重试。" });
      }
    } finally {
      // Preserve the visible message after rows are prepended.  A network
      // failure leaves the height unchanged. Never override user scrolling
      // while the request is in flight (or the browser's own scroll anchoring).
      window.requestAnimationFrame(() => {
        const current = scrollRef.current;
        if (
          current &&
          sessionStore.getState().currentSessionId === sid &&
          scrollRevision.current === startRevision &&
          Math.abs(current.scrollTop - oldTop) < 2
        ) {
          current.scrollTop = oldTop + Math.max(0, current.scrollHeight - oldHeight);
        }
        earlierInFlight.current = false;
        setLoadingEarlier(false);
      });
    }
  };

  if (conv.messages.length === 0) {
    if (historyLoading) {
      return (
        <div className="v2-conversation-loading" data-testid="history-loading" role="status">
          正在加载会话历史…
        </div>
      );
    }
    const sid = sessionStore.getState().currentSessionId;
    if (sid && conv.lastError) {
      return (
        <div className="v2-conversation-empty" data-testid="history-error">
          <h2>会话暂不可显示</h2>
          <p>历史记录未被清空。重新读取不会重新发送消息。</p>
          <button type="button" className="v2-btn ghost" onClick={() => void loadHistory(sid)}>
            重新加载会话
          </button>
        </div>
      );
    }
    return (
      <div className="v2-conversation-empty" data-testid="empty-state">
        <h2>{zh.emptyHeroTitle}</h2>
        <p>{zh.emptyHeroSub}</p>
      </div>
    );
  }

  return (
    <div
      className={`v2-message-list${projectedMessages.length > 200 ? " v2-long-history" : ""}`}
      ref={scrollRef}
      onScroll={updateBottom}
      data-testid="message-list"
    >
      {conv.hasMoreHistory && (
        <button
          type="button"
          className="v2-load-earlier"
          disabled={loadingEarlier}
          onClick={() => void loadEarlier()}
        >
          {loadingEarlier ? "正在读取更早消息…" : `↑ ${zh.loadEarlier}`}
        </button>
      )}
      {projectedMessages.map(({ msg: m, originalIndex }) => (
        <MessageItem
          // Persisted source positions do not change when older pages prepend.
          // Keep existing message DOM/expansion state instead of remounting the
          // entire visible window. Session identity prevents cross-chat reuse.
          key={`${sessionId ?? ""}:${m.role}:${persistedKey(m, originalIndex)}`}
          msg={m}
          index={m.sourceIndex}
          sessionId={sessionId}
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
