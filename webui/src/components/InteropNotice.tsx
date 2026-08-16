import { useEffect, useState } from "react";

interface InteropMessage {
  id: string;
  from: string;
  to: string;
  ts: string;
  topic: string;
  body: string;
  status?: string;
}

interface InteropDirection {
  pending: InteropMessage[];
  recent_done: InteropMessage[];
}

interface InteropPayload {
  lfl_to_dsh: InteropDirection;
  dsh_to_lfl: InteropDirection;
}

/** 协调通道消息提示（只读展示，不触发 run）——web 端可见 pending 协调消息. */
export function InteropNotice() {
  const [data, setData] = useState<InteropPayload | null>(null);
  const [open, setOpen] = useState(false);

  useEffect(() => {
    let alive = true;
    const load = async () => {
      try {
        const resp = await fetch("/api/v1/interop/messages");
        if (resp.ok && alive) setData((await resp.json()) as InteropPayload);
      } catch {
        /* 端点不可用 → 静默隐藏（纯展示组件） */
      }
    };
    load();
    const timer = window.setInterval(load, 30_000); // 30s 轮询，无需刷新
    return () => {
      alive = false;
      window.clearInterval(timer);
    };
  }, []);

  const incoming = data?.lfl_to_dsh ?? { pending: [], recent_done: [] };
  const outgoing = data?.dsh_to_lfl ?? { pending: [], recent_done: [] };
  const pendingTotal = incoming.pending.length + outgoing.pending.length;
  const doneTotal = incoming.recent_done.length + outgoing.recent_done.length;
  if (pendingTotal + doneTotal === 0) return null;

  const renderList = (title: string, items: InteropMessage[]) =>
    items.length === 0 ? null : (
      <div className="v2-interop-group">
        <div className="v2-interop-group-title">{title}</div>
        {items.map((m) => (
          <div key={m.id} className="v2-interop-item">
            <div className="v2-interop-meta">
              [{m.from}→{m.to}] {m.ts} · {m.topic} · {m.id}
              {m.status === "done" && <span className="v2-interop-done">（已处理）</span>}
            </div>
            <div className="v2-interop-body">{m.body}</div>
          </div>
        ))}
      </div>
    );

  return (
    <div className="v2-interop" data-testid="interop-notice">
      <button
        type="button"
        className="v2-interop-toggle"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
      >
        📮 协调消息 {pendingTotal}
        {pendingTotal === 0 && doneTotal > 0 ? `（最近 ${doneTotal} 条已处理）` : ""}
      </button>
      {open && (
        <div className="v2-interop-panel">
          {renderList("待 LFL 处理（DSH → LFL）", incoming.pending)}
          {renderList("待 DSH 处理（LFL → DSH）", outgoing.pending)}
          {renderList("最近协调（已处理）", [...incoming.recent_done, ...outgoing.recent_done])}
        </div>
      )}
    </div>
  );
}
