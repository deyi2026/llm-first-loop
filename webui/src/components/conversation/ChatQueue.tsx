// Human Turn 队列条（feature/webui-human-turn-queue-20260910）：
// 生成中 Cmd/Ctrl+Enter 排队消息在此展示；“立即插入”是独立 live-run handoff。
// 活跃项存在时 3s 轮询收敛（多标签互操作：另一标签领取/取消也可见）。

import { useEffect, useState } from "react";
import {
  interjectQueueTurn,
  refreshQueue,
  useConversation,
  withdrawQueueTurn,
} from "../../core/conversation";
import { queueZh as zh } from "../../i18n/zh";

export function ChatQueue() {
  const conv = useConversation();
  const [expanded, setExpanded] = useState(true);
  const [feedback, setFeedback] = useState("");
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

  if (items.length === 0 && !feedback) return null;
  const queuedCount = items.filter((it) => it.status === "queued").length;
  const statusLabel = (status: string) => {
    if (status === "claimed") return zh.queueItemSending;
    if (status === "interject_pending") return zh.queueInterjectPending;
    if (status === "interject_received") return zh.queueInterjectReceived;
    return "";
  };
  const act = async (
    fn: (queueId: string) => Promise<{ ok: boolean; detail?: string }>,
    queueId: string,
    success?: string
  ) => {
    const result = await fn(queueId);
    setFeedback(result.ok ? (success ?? "") : (result.detail ?? "操作失败，请重试"));
  };

  return (
    <div className="v2-chat-queue" data-testid="chat-queue">
      {items.length > 0 && <button
        type="button"
        className="v2-chat-queue-bar"
        onClick={() => setExpanded((v) => !v)}
        data-testid="chat-queue-toggle"
      >
        <span>
          {zh.queueBarTitle(queuedCount)}
        </span>
        <span className="v2-chat-queue-caret">{expanded ? "▴" : "▾"}</span>
      </button>}
      {items.length > 0 && expanded && (
        <ul className="v2-chat-queue-list" data-testid="chat-queue-list">
          {items.map((it, idx) => (
            <li key={it.queue_id} className={`v2-chat-queue-item ${it.status}`}>
              <span className="v2-chat-queue-pos">
                {it.status === "claimed" ? "▶" : `#${idx + 1}`}
              </span>
              <span className="v2-chat-queue-text" title={it.message}>
                {it.message || zh.queueAttachmentsOnly}
              </span>
              {it.status !== "queued" && (
                <span className="v2-chat-queue-status" data-testid="chat-queue-status">
                  {statusLabel(it.status)}
                </span>
              )}
              {it.status === "queued" && (
                <>
                  <button
                    type="button"
                    className="v2-btn ghost"
                    onClick={() => void act(withdrawQueueTurn, it.queue_id, zh.queueWithdrawn)}
                    data-testid="chat-queue-withdraw"
                  >
                    {zh.queueWithdraw}
                  </button>
                  <button
                    type="button"
                    className="v2-btn ghost"
                    onClick={() => void act(interjectQueueTurn, it.queue_id)}
                    data-testid="chat-queue-interject"
                  >
                    {zh.queueInterject}
                  </button>
                </>
              )}
            </li>
          ))}
        </ul>
      )}
      {feedback && (
        <div className="v2-chat-queue-feedback" role="status" data-testid="chat-queue-feedback">
          {feedback}
        </div>
      )}
    </div>
  );
}
