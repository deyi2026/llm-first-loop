// Web V2：消息渲染（对齐 DSH 会话 UI：
// 用户右侧气泡（--dsw-specific-bubble）、助手全宽正文、思考块默认折叠、
// 工具行折叠链、代码块 banner（语言+复制）+ 高亮 + 长块分块、笔记 footer）

import { useEffect, useMemo, useRef, useState } from "react";
import type { ChatMessage, ToolCallInfo } from "../../core/types";
import { renderMarkdown } from "../../core/markdown";
import { formatTokens } from "../../core/chat";
import { fetchFilePreview, submitFeedback } from "../../core/api";
import { zh } from "../../i18n/zh";

/** 写剪贴板（navigator.clipboard 不可用/失败 → false，静默） */
async function writeClipboard(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    return false;
  }
}

/** 一键复制按钮（对齐 DSH MessageIconActions 的 copy：点击 → "已复制" 1s 恢复） */
function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  const timer = useRef<number | null>(null);
  useEffect(
    () => () => {
      if (timer.current !== null) window.clearTimeout(timer.current);
    },
    []
  );
  const onCopy = async () => {
    const ok = await writeClipboard(text);
    if (!ok) return;
    setCopied(true);
    if (timer.current !== null) window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => setCopied(false), 1000);
  };
  return (
    <button
      type="button"
      className={`v2-copy-btn ${copied ? "copied" : ""}`}
      data-testid="copy-btn"
      title={copied ? zh.copied : zh.copy}
      onClick={() => void onCopy()}
    >
      {copied ? zh.copied : zh.copy}
    </button>
  );
}

function Markdown({ text, clickablePaths }: { text: string; clickablePaths?: Set<string> }) {
  const html = useMemo(() => renderMarkdown(text, clickablePaths), [text, clickablePaths]);
  const [previewPath, setPreviewPath] = useState<string | null>(null);
  // 代码块复制按钮 + 出产物内联路径链接：dangerouslySetInnerHTML 内容无法绑
  // React 事件 → 事件委托
  const onBodyClick = async (e: React.MouseEvent<HTMLDivElement>) => {
    const target = e.target as HTMLElement;
    const link = target.closest?.(".v2-file-link") as HTMLElement | null;
    if (link) {
      const p = link.getAttribute("data-path");
      if (p) setPreviewPath(p);
      return;
    }
    const btn = target.closest?.(".v2-code-copy") as HTMLButtonElement | null;
    if (!btn) return;
    const code = btn.closest(".v2-code-block")?.querySelector("pre code");
    const ok = await writeClipboard(code?.textContent ?? "");
    if (ok) {
      const orig = btn.textContent;
      btn.textContent = zh.copied;
      window.setTimeout(() => {
        btn.textContent = orig;
      }, 1000);
    }
  };
  return (
    <>
      <div className="v2-md" onClick={onBodyClick} dangerouslySetInnerHTML={{ __html: html }} />
      {previewPath ? <FilePreviewModal path={previewPath} onClose={() => setPreviewPath(null)} /> : null}
    </>
  );
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

/** 工具回执状态解析（content 内 [状态: xxx] 标记；缺失中性） */
function receiptStatus(content: string): { key: string; label: string } {
  const m = /\[状态:\s*([a-z_]+)\]/i.exec(content || "");
  const key = (m ? m[1] : "done").toLowerCase();
  const labels: Record<string, string> = {
    success: "成功",
    failure: "失败",
    error: "错误",
    blocked: "已拦截",
    timeout: "超时",
    done: "完成",
    running: "执行中",
  };
  return { key, label: labels[key] ?? key };
}

function ToolReceipt({ msg }: { msg: ChatMessage }) {
  const [open, setOpen] = useState(false);
  const st = receiptStatus(msg.content);
  const statusClass = st.key === "success" || st.key === "done" ? "ok" : st.key === "blocked" ? "warn" : st.key === "failure" || st.key === "error" ? "err" : "neutral";
  return (
    <div className="v2-tool-receipt" data-testid="tool-receipt">
      <button type="button" className="v2-tool-receipt-toggle" onClick={() => setOpen((v) => !v)}>
        <span className="v2-tool-icon">⚙️</span>
        <span className="v2-tool-name">{msg.toolName || "tool"}</span>
        <span className={`v2-status-chip ${statusClass}`}>{st.label}</span>
        {msg.toolCallId ? <span className="v2-tool-id">{msg.toolCallId}</span> : null}
        <span className="v2-tool-arrow">{open ? "▾" : "▸"}</span>
      </button>
      {open && (
        <pre className="v2-tool-receipt-body">
          <code>{msg.content}</code>
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

/** 出产物文件预览模态（对齐 DSH deliverables 点击打开；只读） */
function FilePreviewModal({ path, onClose }: { path: string; onClose: () => void }) {
  const [state, setState] = useState<{ loading: boolean; error?: string; data?: { content: string; truncated: boolean; size: number } }>({ loading: true });
  useEffect(() => {
    let alive = true;
    setState({ loading: true });
    void fetchFilePreview(path).then((pv) => {
      if (!alive) return;
      if (!pv) setState({ loading: false, error: "预览失败（文件不存在或越界）" });
      else setState({ loading: false, data: { content: pv.content, truncated: pv.truncated, size: pv.size } });
    });
    return () => {
      alive = false;
    };
  }, [path]);
  return (
    <div className="v2-preview-mask" data-testid="file-preview" onClick={onClose}>
      <div className="v2-preview-card" onClick={(e) => e.stopPropagation()}>
        <div className="v2-preview-head">
          <span className="v2-preview-path" title={path}>{path}</span>
          <button type="button" className="v2-preview-close" onClick={onClose} aria-label="关闭">✕</button>
        </div>
        <div className="v2-preview-body">
          {state.loading ? (
            <div className="v2-preview-hint">加载中…</div>
          ) : state.error ? (
            <div className="v2-preview-hint err">{state.error}</div>
          ) : (
            <>
              <pre className="v2-preview-content"><code>{state.data!.content}</code></pre>
              {state.data!.truncated ? (
                <div className="v2-preview-truncated">（预览超过 20 万字符已截断，共 {state.data!.size} 字符）</div>
              ) : null}
            </>
          )}
        </div>
      </div>
    </div>
  );
}

/** 出产物路径提取（edit_file/write_file 的 path 参数，去重）——chips 与正文链接共用 */
export function extractProducedPaths(calls: ToolCallInfo[] | null | undefined): string[] {
  const out: string[] = [];
  for (const t of calls ?? []) {
    if (t.name !== "edit_file" && t.name !== "write_file") continue;
    const p = (t.arguments as Record<string, unknown>)?.path;
    if (typeof p === "string" && p.trim() && !out.includes(p)) out.push(p.trim());
  }
  return out;
}

/** 出产物文件列表（从 edit_file/write_file 工具调用提取路径，点击打开预览） */
function ProducedFiles({ calls }: { calls: ToolCallInfo[] }) {
  const [previewPath, setPreviewPath] = useState<string | null>(null);
  const paths = useMemo(() => extractProducedPaths(calls), [calls]);
  if (paths.length === 0) return null;
  return (
    <div className="v2-produced" data-testid="produced-files">
      <span className="v2-produced-label">📄 出产物</span>
      {paths.map((p) => (
        <button
          key={p}
          type="button"
          className="v2-produced-chip"
          title={`打开 ${p}`}
          onClick={() => setPreviewPath(p)}
        >
          {p}
        </button>
      ))}
      {previewPath ? <FilePreviewModal path={previewPath} onClose={() => setPreviewPath(null)} /> : null}
    </div>
  );
}

function StreamingHint({ startedAt }: { startedAt: number | null }) {
  const [elapsed, setElapsed] = useState(0);
  useEffect(() => {
    if (!startedAt) return;
    const t = window.setInterval(() => {
      setElapsed(Math.max(0, Math.floor((Date.now() - startedAt) / 1000)));
    }, 1000);
    return () => window.clearInterval(t);
  }, [startedAt]);
  return (
    <div className="v2-thinking-hint" data-testid="thinking-hint">
      {zh.thinkingHint}
      {elapsed >= 5 ? `（已等待 ${elapsed}s，首 token 生成中，同会话串行排队中）` : ""}
    </div>
  );
}

function FeedbackButtons({ sessionId, index }: { sessionId: string; index: number }) {
  const [picked, setPicked] = useState<"up" | "down" | null>(null);
  const [saved, setSaved] = useState(false);
  const send = async (fb: "up" | "down") => {
    if (picked) return; // 一次性反馈（本地状态）
    setPicked(fb);
    const ok = await submitFeedback(sessionId, index, fb);
    setSaved(ok);
    if (!ok) setPicked(null); // 失败复位可重试
  };
  if (saved) {
    // 反馈已记录：常显确认态（不随 hover 消失，点击有明确反馈）
    return (
      <div className="v2-feedback saved" data-testid="msg-feedback">
        <span className={`v2-fb-saved ${picked === "up" ? "up" : "down"}`}>
          {picked === "up" ? "👍 已记录（有帮助）" : "👎 已记录（有问题）"}
        </span>
      </div>
    );
  }
  return (
    <div className="v2-feedback" data-testid="msg-feedback">
      <button
        type="button"
        className={`v2-fb-btn ${picked === "up" ? "picked" : ""}`}
        title={zh.feedbackUp}
        onClick={() => void send("up")}
      >
        👍
      </button>
      <button
        type="button"
        className={`v2-fb-btn ${picked === "down" ? "picked down" : ""}`}
        title={zh.feedbackDown}
        onClick={() => void send("down")}
      >
        👎
      </button>
    </div>
  );
}

export function MessageItem({
  msg,
  index,
  sessionId,
  producedPaths,
}: {
  msg: ChatMessage;
  index?: number;
  sessionId?: string;
  /** 会话级出产物路径集合（正文路径引用可点击打开；由 MessageList 计算） */
  producedPaths?: Set<string>;
}) {
  if (msg.role === "user") {
    return (
      <div className="v2-msg user" data-testid="msg-user">
        <div className="v2-msg-bubble user">
          <div className="v2-msg-text">{msg.content}</div>
        </div>
        <div className="v2-msg-actions">
          <CopyButton text={msg.content} />
        </div>
      </div>
    );
  }
  if (msg.role === "tool") {
    return (
      <div className="v2-msg tool" data-testid="msg-tool">
        <ToolReceipt msg={msg} />
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
          <>
            <ToolChain calls={msg.toolCalls} />
            {/* 出产物（对齐 DSH deliverables）：编辑的文件即时可见可打开 */}
            <ProducedFiles calls={msg.toolCalls} />
          </>
        ) : null}
        {msg.content ? (
          <Markdown text={msg.content} clickablePaths={producedPaths} />
        ) : null}
        {msg.streaming && !msg.content && (
          <StreamingHint startedAt={msg.streamStartedAt ?? null} />
        )}
        {msg.model_used || msg.tokens_in || msg.tokens_out ? (
          // M51/M52: 模型 + token 消耗页脚（对齐 feishu「—— 模型 · N入/M出」格式）
          // M58（2026-08-18 用户需求）: 每次命中率也加到末尾——⚡ 命中率%
          <div className="v2-msg-footer" data-testid="msg-footer">
            {msg.model_used ? `—— ${msg.model_used}` : ""}
            {msg.tokens_in || msg.tokens_out
              ? ` · ${formatTokens(msg.tokens_in)}入/${formatTokens(msg.tokens_out)}出`
              : ""}
            {msg.tokens_in && msg.tokens_cache_hit
              ? ` · ⚡ ${((msg.tokens_cache_hit / msg.tokens_in) * 100).toFixed(1)}%`
              : ""}
          </div>
        ) : null}
        {msg.note ? <div className="v2-msg-note">{msg.note}</div> : null}
        <div className="v2-msg-actions">
          <CopyButton text={msg.content} />
          {typeof index === "number" && sessionId ? <FeedbackButtons sessionId={sessionId} index={index} /> : null}
        </div>
      </div>
    </div>
  );
}

/** 历史消息 → 代码块识别渲染（消息内容内嵌 markdown 代码块） */
export function MessageBody({ text }: { text: string }) {
  return <Markdown text={text} />;
}
