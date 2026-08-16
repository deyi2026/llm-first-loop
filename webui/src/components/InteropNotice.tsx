import { useEffect, useState } from "react";

interface InteropMessage {
  id: string;
  from: string;
  to: string;
  ts: string;
  topic: string;
  body: string;
}

interface InteropPayload {
  lfl_to_dsh: InteropMessage[];
  dsh_to_lfl: InteropMessage[];
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

  const incoming = data?.lfl_to_dsh ?? [];
  const outgoing = data?.dsh_to_lfl ?? [];
  const total = incoming.length + outgoing.length;
  if (total === 0) return null;

  const renderList = (title: string, items: InteropMessage[]) =>
    items.length === 0 ? null : (
      <div className="v2-interop-group">
        <div className="v2-interop-group-title">{title}</div>
        {items.map((m) => (
          <div key={m.id} className="v2-interop-item">
            <div className="v2-interop-meta">
              [{m.from}→{m.to}] {m.ts} · {m.topic} · {m.id}
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
        📮 协调消息 {total}
      </button>
      {open && (
        <div className="v2-interop-panel">
          {renderList("待 LFL 处理（DSH → LFL）", incoming)}
          {renderList("待 DSH 处理（LFL → DSH）", outgoing)}
        </div>
      )}
    </div>
  );
}
