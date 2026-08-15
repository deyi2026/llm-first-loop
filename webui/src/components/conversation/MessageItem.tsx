// Web V2：消息渲染（对齐 DSH 会话 UI：
// 用户右侧气泡（--dsw-specific-bubble）、助手全宽正文、思考块默认折叠、
// 工具行折叠链、代码块 banner（语言+复制）+ 高亮 + 长块分块、笔记 footer）

import { useMemo, useState } from "react";
import type { ChatMessage, ToolCallInfo } from "../../core/types";
import { renderMarkdown } from "../../core/markdown";
import { zh } from "../../i18n/zh";

function Markdown({ text }: { text: string }) {
  const html = useMemo(() => renderMarkdown(text), [text]);
  return <div className="v2-md" dangerouslySetInnerHTML={{ __html: html }} />;
}

function ThinkingBlock({ text, streaming }: { text: string; streaming?: boolean }) {
  const [open, setOpen] = useState(false);
  const len = text.length;
  return (
    <div className="v2-think" data-testid="think-block">
      <button type="button" className="v2-think-toggle" onClick={() => setOpen((v) => !v)}>
        💭 思考过程（{len} 字）{open ? "▾" : "▸"}
      </button>
      {open && (
        <div className="v2-think-body">
          <Markdown text={text} />
          {streaming && <span className="v2-think-cursor">▌</span>}
        </div>
      )}
    </div>
  );
}

function ToolRow({ tool }: { tool: ToolCallInfo }) {
  const [open, setOpen] = useState(false);
  const args = useMemo(() => {
    try {
      return JSON.stringify(tool.arguments ?? {}, null, 2);
    } catch {
      return String(tool.arguments ?? "");
    }
  }, [tool]);
  return (
    <div className="v2-tool-row" data-testid="tool-row">
      <button type="button" className="v2-tool-toggle" onClick={() => setOpen((v) => !v)}>
        <span className="v2-tool-icon">🔧</span>
        <span className="v2-tool-name">{tool.name}</span>
        <span className="v2-tool-id">{tool.id}</span>
        <span className="v2-tool-arrow">{open ? "▾" : "▸"}</span>
      </button>
      {open && (
        <pre className="v2-tool-args">
          <code>{args}</code>
        </pre>
      )}
    </div>
  );
}

function ToolChain({ calls }: { calls: ToolCallInfo[] }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="v2-tool-chain" data-testid="tool-chain">
      <button type="button" className="v2-tool-chain-toggle" onClick={() => setOpen((v) => !v)}>
        ⚙️ 工具调用（{calls.length}）{open ? "▾" : "▸"}
      </button>
      {open && calls.map((t) => <ToolRow key={t.id} tool={t} />)}
    </div>
  );
}

export function MessageItem({ msg }: { msg: ChatMessage }) {
  if (msg.role === "user") {
    return (
      <div className="v2-msg user" data-testid="msg-user">
        <div className="v2-msg-bubble user">
          <div className="v2-msg-text">{msg.content}</div>
        </div>
      </div>
    );
  }
  if (msg.role === "tool") {
    return (
      <div className="v2-msg tool" data-testid="msg-tool">
        <div className="v2-tool-row static">
          <span className="v2-tool-icon">⚙️</span>
          <span className="v2-tool-name">{msg.toolName || "tool"}</span>
          <span className="v2-tool-id">{msg.toolCallId || ""}</span>
        </div>
      </div>
    );
  }
  // assistant
  return (
    <div className="v2-msg assistant" data-testid="msg-assistant">
      <div className="v2-msg-body">
        {msg.reasoningContent ? (
          <ThinkingBlock text={msg.reasoningContent} streaming={msg.streaming} />
        ) : null}
        {Array.isArray(msg.toolCalls) && msg.toolCalls.length > 0 ? (
          <ToolChain calls={msg.toolCalls} />
        ) : null}
        {msg.content ? <Markdown text={msg.content} /> : null}
        {msg.streaming && !msg.content && (
          <div className="v2-thinking-hint">{zh.thinkingHint}</div>
        )}
        {msg.note ? <div className="v2-msg-note">{msg.note}</div> : null}
      </div>
    </div>
  );
}

/** 历史消息 → 代码块识别渲染（消息内容内嵌 markdown 代码块） */
export function MessageBody({ text }: { text: string }) {
  return <Markdown text={text} />;
}
