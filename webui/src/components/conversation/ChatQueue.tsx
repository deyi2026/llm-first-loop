// Human Turn 队列条（feature/webui-human-turn-queue-20260910）：
// 生成中 Cmd/Ctrl+Enter 排队的插话在此展示（后端 durable 事实的镜像）。
// 活跃项存在时 3s 轮询收敛（多标签互操作：另一标签领取/取消也可见）。

import { useEffect, useState } from "react";
import { cancelQueueTurn, refreshQueue, useConversation } from "../../core/conversation";
import { queueZh as zh } from "../../i18n/zh";

export function ChatQueue() {
  const conv = useConversation();
  const [expanded, setExpanded] = useState(false);
  const items = conv.queueItems;

  // 活跃项存在时轮询镜像（claimed→发送中、queued→待发；终态项不返回所以列表自动缩短）
  useEffect(() => {
    if (items.length === 0) return;
    const sid = items[0]?.session_id as string | undefined;
    if (!sid) return;
    const t = window.setInterval(() => {
      void refreshQueue(sid);
    }, 3000);
    return () => window.clearInterval(t);
  }, [items.length, items[0]?.session_id]);

  if (items.length === 0) return null;
  const queuedCount = items.filter((it) => it.status === "queued").length;

  return (
    <div className="v2-chat-queue" data-testid="chat-queue">
      <button
        type="button"
        className="v2-chat-queue-bar"
        onClick={() => setExpanded((v) => !v)}
        data-testid="chat-queue-toggle"
      >
        <span>
          {zh.queueBarTitle(queuedCount)}
          {items.length > queuedCount ? ` · ${zh.queueItemSending}` : ""}
        </span>
        <span className="v2-chat-queue-caret">{expanded ? "▴" : "▾"}</span>
      </button>
      {expanded && (
        <ul className="v2-chat-queue-list" data-testid="chat-queue-list">
          {items.map((it, idx) => (
            <li key={it.queue_id} className={`v2-chat-queue-item ${it.status}`}>
              <span className="v2-chat-queue-pos">
                {it.status === "claimed" ? "▶" : `#${idx + 1}`}
              </span>
              <span className="v2-chat-queue-text" title={it.message}>
                {it.message || zh.queueAttachmentsOnly}
              </span>
              {it.status === "queued" && (
                <button
                  type="button"
                  className="v2-btn ghost"
                  onClick={() => void cancelQueueTurn(it.queue_id)}
                  data-testid="chat-queue-cancel"
                >
                  {zh.queueCancel}
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
