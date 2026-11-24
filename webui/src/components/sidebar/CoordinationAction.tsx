import { useEffect, useRef, useState } from "react";
import { enqueueQueueMessage, fetchStreamStatus, interjectQueueItem, type StreamStatus } from "../../core/chat";
import { refreshQueue } from "../../core/conversation";
import { sessionStore, useSessions } from "../../core/stores";

export type CoordinationTarget = { sessionId: string; label: string };

/** Explicit human delivery to an exact target. The existing durable queue owns
 * dispatch/recovery; the sidebar never starts a second runner or writes history. */
export function CoordinationAction({ target, onClose }: { target: CoordinationTarget; onClose: () => void }) {
  const session = useSessions().find((s) => s.session_id === target.sessionId);
  const [message, setMessage] = useState("");
  const [status, setStatus] = useState<StreamStatus | null>(null);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState(false);
  const sending = useRef(false);
  const sectionRef = useRef<HTMLElement | null>(null);

  useEffect(() => {
    let active = true;
    let inFlight = false;
    const refresh = () => {
      if (document.hidden || inFlight) return;
      inFlight = true;
      void fetchStreamStatus(target.sessionId).then((next) => {
        if (active) setStatus(next);
      }).finally(() => { inFlight = false; });
    };
    sectionRef.current?.scrollIntoView?.({ block: "nearest" });
    refresh();
    const timer = window.setInterval(refresh, 5000);
    return () => { active = false; window.clearInterval(timer); };
  }, [target.sessionId]);

  const generation = status?.running ? status.run_generation : undefined;
  const allowed = session?.web_reusable !== false;
  const send = async (urgent: boolean) => {
    const text = message.trim();
    const clickedGeneration = generation;
    if (!allowed || !text || sending.current || (urgent && !clickedGeneration)) return;
    sending.current = true;
    setBusy(true);
    setNotice("");
    setError(false);
    try {
      // Never copy the currently displayed session's model/effort/attachments.
      const queued = await enqueueQueueMessage(target.sessionId, text, [], null, null, null);
      if (!queued.ok || !queued.queue_id) {
        setError(true);
        setNotice(queued.detail || "未确认入队；请先检查目标会话队列，避免重复提交。");
        return;
      }
      setMessage(""); // Durable receipt exists; never re-submit on an interject failure.
      const receipt = "队列 " + queued.queue_id;
      if (urgent && clickedGeneration) {
        const inserted = await interjectQueueItem(target.sessionId, queued.queue_id, clickedGeneration);
        setError(!inserted.ok);
        setNotice(inserted.ok
          ? "插入请求已受理，等待当前 Run 安全接收 · " + receipt
          : (inserted.detail || "插入未确认，请查看目标队列状态。") + " · " + receipt);
      } else {
        setNotice("已加入目标会话队列，空闲时自动派发 · " + receipt);
      }
      // Only refresh the currently displayed target, not another session's queue.
      if (sessionStore.getState().currentSessionId === target.sessionId) void refreshQueue(target.sessionId);
    } finally {
      sending.current = false;
      setBusy(false);
    }
  };

  return (
    <section ref={sectionRef} aria-label={"协助 " + target.label} data-testid="coordination-action"
      style={{ padding: 8, border: "1px solid rgba(128,128,128,0.35)", borderRadius: 8, margin: "4px 0" }}>
      <strong>{target.label}</strong>
      <div style={{ fontSize: 11, overflowWrap: "anywhere" }}>{target.sessionId}</div>
      <div role="status" style={{ margin: "4px 0" }}>
        {!allowed ? "此会话不属于 Web/飞书可执行边界，仅可查看。"
          : status === null ? "运行状态未确认，可普通排队"
          : status.running ? "当前 Run 运行中" : "当前无可见 Web Run，排队后后台自动派发"}
      </div>
      <textarea aria-label="协助指令" value={message} disabled={!allowed || busy}
        onChange={(event) => setMessage(event.target.value)}
        placeholder="输入需要目标会话执行的指令"
        rows={3} style={{ width: "100%", boxSizing: "border-box", resize: "vertical", fontSize: 14 }} />
      <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
        <button type="button" className="v2-btn ghost" style={{ minHeight: 44 }}
          disabled={!allowed || busy || !message.trim()} onClick={() => void send(false)}>
          {status?.running === false ? "唤醒执行（排队）" : "加入执行队列"}
        </button>
        <button type="button" className="v2-btn ghost" style={{ minHeight: 44 }}
          disabled={!allowed || busy || !message.trim() || !generation} onClick={() => void send(true)}>
          紧急插入
        </button>
        <button type="button" className="v2-btn ghost" style={{ minHeight: 44 }} disabled={busy} onClick={onClose}>关闭</button>
      </div>
      {notice && <div role={error ? "alert" : "status"} style={{ overflowWrap: "anywhere" }}>{notice}</div>}
    </section>
  );
}
