// Human Turn 队列 dock（feature/webui-human-turn-queue-20260910；
// 20260922 对齐 DSH QueueDock 交互）：
// 生成中 Cmd/Ctrl+Enter 排队消息在 composer 上方 dock 展示；行操作三件套：
// 编辑（撤回并回填草稿）/ 删除（纯移除）/ 立即插入（live-run 真插话，仅运行中可用）；
// 已被领取（claimed）或插话流转中的行按钮禁用并显示状态。
// 活跃项存在时 3s 轮询收敛（多标签互操作：另一标签领取/取消也可见）。

import { useEffect, useState } from "react";
import {
  interjectQueueTurn,
  refreshQueue,
  removeQueueTurn,
  useConversation,
  withdrawQueueTurn,
} from "../../core/conversation";
import { queueZh as zh } from "../../i18n/zh";

export function ChatQueue() {
  const conv = useConversation();
  const [expanded, setExpanded] = useState(true);
  const [feedback, setFeedback] = useState("");
  const items = conv.queueItems;
  const streaming = Boolean(conv.streaming || conv.backgroundRunning);
  const canInterject = streaming && Boolean(conv.activeRunGeneration);
  const interjectTitle = canInterject
    ? zh.queueInterject
    : streaming
      ? zh.queueInterjectIdentityPending
      : zh.queueInterjectUnavailable;

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
        <span className="v2-chat-queue-bar-icon" aria-hidden="true">▤</span>
        <span>{zh.queueBarTitle(queuedCount)}</span>
        <span className="v2-chat-queue-caret">{expanded ? "▴" : "▾"}</span>
      </button>}
      {items.length > 0 && expanded && (
        <ul className="v2-chat-queue-list" data-testid="chat-queue-list">
          {items.map((it, idx) => {
            const locked = it.status !== "queued";
            return (
              <li key={it.queue_id} className={`v2-chat-queue-item ${it.status}`}>
                <span className="v2-chat-queue-pos">
                  {it.status === "claimed" ? "▶" : `#${idx + 1}`}
                </span>
                <span className="v2-chat-queue-body">
                  {it.attachment_facts?.length ? (
                    <span className="v2-chat-queue-files">
                      {it.attachment_facts.map((fact) => (
                        <span
                          key={fact.ref}
                          className="v2-chat-queue-file"
                          title={zh.queueFile(fact.filename)}
                        >
                          📎 {fact.filename}
                        </span>
                      ))}
                    </span>
                  ) : null}
                  <span className="v2-chat-queue-text" title={it.message}>
                    {it.message || zh.queueAttachmentsOnly}
                  </span>
                </span>
                {locked && (
                  <span className="v2-chat-queue-status" data-testid="chat-queue-status">
                    {statusLabel(it.status)}
                  </span>
                )}
                <span className="v2-chat-queue-actions">
                  <button
                    type="button"
                    className="v2-btn ghost"
                    disabled={locked}
                    onClick={() => void act(withdrawQueueTurn, it.queue_id, zh.queueWithdrawn)}
                    data-testid="chat-queue-edit"
                  >
                    {zh.queueEdit}
                  </button>
                  <button
                    type="button"
                    className="v2-btn ghost"
                    disabled={locked}
                    onClick={() => void act(removeQueueTurn, it.queue_id, zh.queueRemoved)}
                    data-testid="chat-queue-remove"
                  >
                    {zh.queueRemove}
                  </button>
                  <button
                    type="button"
                    className="v2-btn ghost"
                    disabled={locked || !canInterject}
                    title={interjectTitle}
                    onClick={() => void act(interjectQueueTurn, it.queue_id)}
                    data-testid="chat-queue-interject"
                  >
                    {zh.queueInterject}
                  </button>
                </span>
              </li>
            );
          })}
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
