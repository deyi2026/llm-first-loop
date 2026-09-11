// Web V2：消息渲染（对齐 DSH 会话 UI：
// 用户右侧气泡（--dsw-specific-bubble）、助手全宽正文、思考块默认折叠、
// 工具行折叠链、代码块 banner（语言+复制）+ 高亮 + 长块分块、笔记 footer）

import { useEffect, useMemo, useRef, useState } from "react";
import type { AttachmentFact, ChatMessage, ToolActivity, ToolActivityStatus, ToolCallInfo } from "../../core/types";
import { renderMarkdown } from "../../core/markdown";
import { formatTokens } from "../../core/chat";
import { fetchFilePreview, forkSession, submitFeedback } from "../../core/api";
import { useCapabilities } from "../../core/capabilities";
import { loadHistory, prefillComposer } from "../../core/conversation";
import { sessionStore } from "../../core/stores";
import { normalizeToolStatus, parseToolReceiptStatus } from "../../core/toolActivity";
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

function Markdown({
  text,
  clickablePaths,
  enableMath = true,
}: {
  text: string;
  clickablePaths?: Set<string>;
  enableMath?: boolean;
}) {
  const html = useMemo(
    () => renderMarkdown(text, clickablePaths, { enableMath }),
    [text, clickablePaths, enableMath]
  );
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
          {/* Reasoning often contains shell variables such as $d$p.  Treating those as
              inline-TeX corrupts the diagnostic surface with KaTeX MathML. */}
          <Markdown text={text} enableMath={false} />
          {streaming && <span className="v2-think-cursor">▌</span>}
        </div>
      )}
    </div>
  );
}

function toolStatusMeta(status: ToolActivityStatus): { icon: string; label: string; className: string } {
  if (status === "running") return { icon: "●", label: "执行中", className: "running" };
  if (status === "success") return { icon: "✓", label: "成功", className: "ok" };
  if (status === "failure" || status === "error") return { icon: "!", label: "失败", className: "err" };
  if (status === "blocked") return { icon: "!", label: "已拦截", className: "warn" };
  if (status === "unauthorized") return { icon: "!", label: "未授权", className: "warn" };
  if (status === "timeout") return { icon: "!", label: "超时", className: "err" };
  if (status === "cancelled" || status === "interrupted") return { icon: "–", label: "已中断", className: "neutral" };
  if (status === "unknown") return { icon: "•", label: "状态未知", className: "neutral" };
  return { icon: "•", label: "已结束", className: "neutral" };
}

function toolDisplayName(name: string): string {
  const labels: Record<string, string> = {
    read_file: "读取文件",
    read_attachment: "读取附件",
    search_text: "搜索代码",
    search_files: "搜索文件",
    search_archive: "搜索历史",
    search_records: "搜索记录",
    write_file: "写入文件",
    edit_file: "修改文件",
    execute_command: "运行命令",
    web_fetch: "访问网页",
    architecture_status: "检查架构状态",
  };
  return labels[name] ?? name.replaceAll("_", " ");
}

function activitySubtitle(activity: ToolActivity): string {
  const args = activity.arguments ?? {};
  for (const key of ["path", "query", "command", "url", "pattern"] as const) {
    const value = args[key];
    if (typeof value === "string" && value.trim()) return value.trim();
  }
  return activity.argsSummary || "";
}

function ToolActivityRow({ activity }: { activity: ToolActivity }) {
  const [open, setOpen] = useState(false);
  const meta = toolStatusMeta(activity.status);
  const subtitle = activitySubtitle(activity);
  const details = useMemo(() => {
    const parts: string[] = [];
    if (activity.arguments && Object.keys(activity.arguments).length > 0) {
      try {
        parts.push(`参数\n${JSON.stringify(activity.arguments, null, 2)}`);
      } catch {
        parts.push("参数\n[无法序列化]");
      }
    } else if (activity.argsSummary) {
      parts.push(`参数摘要\n${activity.argsSummary}`);
    }
    if (activity.resultContent) parts.push(`结果\n${activity.resultContent}`);
    return parts.join("\n\n");
  }, [activity]);

  return (
    <div className={`v2-tool-activity-row ${meta.className}`} data-testid="tool-activity-row">
      <button
        type="button"
        className="v2-tool-activity-row-toggle"
        onClick={() => details && setOpen((value) => !value)}
        aria-expanded={details ? open : undefined}
      >
        <span className={`v2-tool-activity-icon ${meta.className}`}>{meta.icon}</span>
        <span className="v2-tool-activity-copy">
          <span className="v2-tool-activity-name">{toolDisplayName(activity.name)}</span>
          {subtitle ? <span className="v2-tool-activity-subtitle">{subtitle}</span> : null}
        </span>
        <span className={`v2-tool-activity-status ${meta.className}`}>{meta.label}</span>
        {details ? <span className="v2-tool-arrow">{open ? "▾" : "▸"}</span> : null}
      </button>
      {open && details ? (
        <pre className="v2-tool-activity-detail"><code>{details}</code></pre>
      ) : null}
    </div>
  );
}

function ToolActivityPanel({ activities, streaming }: { activities: ToolActivity[]; streaming?: boolean }) {
  const hasIssue = activities.some((activity) =>
    ["failure", "error", "blocked", "unauthorized", "timeout", "cancelled", "interrupted", "unknown"].includes(activity.status)
  );
  const hasRunning = activities.some((activity) => activity.status === "running");
  const hasUncertain = activities.some((activity) => activity.status === "completed");
  const [open, setOpen] = useState(Boolean(streaming || hasRunning || hasIssue));

  useEffect(() => {
    if (streaming || hasRunning || hasIssue) setOpen(true);
    else setOpen(false);
  }, [streaming, hasRunning, hasIssue]);

  const summary = hasRunning
    ? activities.length === 1
      ? `正在使用工具 · ${toolDisplayName(activities[0].name)}`
      : `正在使用 ${activities.length} 个工具`
    : hasIssue
      ? `工具执行有异常 · ${activities.length} 个工具`
      : `使用了 ${activities.length} 个工具`;

  return (
    <div className={`v2-tool-activity ${hasIssue ? "has-issue" : ""}`} data-testid="tool-activity">
      <button
        type="button"
        className="v2-tool-activity-toggle"
        onClick={() => setOpen((value) => !value)}
        aria-expanded={open}
      >
        <span className={`v2-tool-activity-summary-icon ${hasRunning ? "running" : hasIssue ? "issue" : hasUncertain ? "neutral" : "done"}`}>
          {hasRunning ? "●" : hasIssue ? "!" : hasUncertain ? "•" : "✓"}
        </span>
        <span>{summary}</span>
        <span className="v2-tool-arrow">{open ? "▾" : "▸"}</span>
      </button>
      {open ? (
        <div className="v2-tool-activity-list">
          {activities.map((activity) => <ToolActivityRow key={activity.id} activity={activity} />)}
        </div>
      ) : null}
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

function formatAttachmentSize(size?: number): string {
  if (!size || size < 1) return "";
  if (size < 1024) return `${size} B`;
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`;
  return `${(size / (1024 * 1024)).toFixed(1)} MB`;
}

function UserAttachments({ attachments }: { attachments?: AttachmentFact[] }) {
  if (!attachments?.length) return null;
  return (
    <div className="v2-msg-attachments" data-testid="msg-attachments">
      {attachments.map((a) => (
        <div className="v2-attachment" key={a.ref} title={a.filename}>
          <span aria-hidden="true">📎</span>
          <span className="v2-attachment-name">{a.filename}</span>
          {a.size_bytes ? <span className="v2-attachment-size">{formatAttachmentSize(a.size_bytes)}</span> : null}
        </div>
      ))}
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

function formatMessageTime(ts?: number): string | null {
  if (!ts || !Number.isFinite(ts) || ts <= 0) return null;
  const d = new Date(ts * 1000);
  if (Number.isNaN(d.getTime())) return null;
  const now = new Date();
  const sameDay =
    d.getFullYear() === now.getFullYear() &&
    d.getMonth() === now.getMonth() &&
    d.getDate() === now.getDate();
  const time = new Intl.DateTimeFormat(undefined, {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  }).format(d);
  if (sameDay) return time;
  const date = new Intl.DateTimeFormat(undefined, {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(d);
  return `${date} ${time}`;
}

function MessageTime({ ts }: { ts?: number }) {
  const text = formatMessageTime(ts);
  return text ? (
    <time className="v2-msg-time" dateTime={new Date(ts! * 1000).toISOString()} title="按设备系统时区显示">
      {text}
    </time>
  ) : null;
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
  const caps = useCapabilities();
  const [editing, setEditing] = useState(false);
  const [editText, setEditText] = useState(msg.content);
  const [editBusy, setEditBusy] = useState(false);
  const [editError, setEditError] = useState("");

  const editAndFork = async () => {
    if (!sessionId || typeof msg.sourceIndex !== "number" || msg.sourceIndex < 0 || editBusy) return;
    if (!editText.trim()) {
      setEditError("编辑后的消息不能为空。");
      return;
    }
    setEditBusy(true);
    setEditError("");
    const report = await forkSession(sessionId, "", msg.sourceIndex);
    const newSessionId = report?.new_session_id ?? "";
    if (!newSessionId) {
      setEditBusy(false);
      setEditError("创建分支失败；原会话未修改，请重试。");
      return;
    }
    sessionStore.setCurrentSession(newSessionId);
    localStorage.removeItem(`lfl-draft-${newSessionId}`);
    await loadHistory(newSessionId);
    prefillComposer(editText, msg.attachments ?? []);
    setEditing(false);
    setEditBusy(false);
  };

  if (msg.role === "user") {
    return (
      <div className="v2-msg user" data-testid="msg-user">
        <div className="v2-msg-bubble user">
          {/* EVO-20260818: 用户输入消息与 assistant 同格式渲染（markdown/代码块/表格/
              公式/路径点击）——输入端（Composer）直接输入 markdown 语法即可 */}
          <UserAttachments attachments={msg.attachments} />
          {msg.content ? (
            <div className="v2-msg-text">
              <Markdown text={msg.content} clickablePaths={producedPaths} />
            </div>
          ) : null}
          <MessageTime ts={msg.ts} />
        </div>
        <div className="v2-msg-actions">
          <CopyButton text={msg.content} />
          {caps.fork && sessionId && typeof msg.sourceIndex === "number" && msg.sourceIndex >= 0 ? (
            <button
              type="button"
              className="v2-copy-btn"
              title="编辑并从这里创建新分支（原历史不变）"
              onClick={() => {
                setEditText(msg.content);
                setEditError("");
                setEditing((value) => !value);
              }}
            >
              编辑并分支
            </button>
          ) : null}
        </div>
        {editing ? (
          <div className="v2-edit-fork" data-testid="edit-fork-panel">
            <textarea
              value={editText}
              onChange={(event) => setEditText(event.target.value)}
              rows={Math.min(8, Math.max(2, editText.split("\n").length))}
              aria-label="编辑消息内容"
              autoFocus
            />
            <div className="v2-edit-fork-note">原会话保持不可变；将在这条 USER 消息之前创建分支，并把编辑内容填入新分支输入框，不自动发送。</div>
            {editError ? <div className="v2-panel-error">{editError}</div> : null}
            <div className="v2-edit-fork-actions">
              <button type="button" className="v2-btn primary" disabled={editBusy || !editText.trim()} onClick={() => void editAndFork()}>
                {editBusy ? "创建中…" : "创建分支并填入"}
              </button>
              <button type="button" className="v2-btn ghost" disabled={editBusy} onClick={() => setEditing(false)}>取消</button>
            </div>
          </div>
        ) : null}
      </div>
    );
  }
  if (msg.role === "tool") {
    const fallbackActivity: ToolActivity = {
      id: msg.toolCallId || `orphan:${msg.sourceIndex ?? "unknown"}`,
      name: msg.toolName || "tool",
      status: msg.toolStatus
        ? normalizeToolStatus(msg.toolStatus, "unknown")
        : parseToolReceiptStatus(msg.content),
      resultContent: msg.content,
      ...(typeof msg.toolDurationMs === "number" ? { durationMs: msg.toolDurationMs } : {}),
    };
    return (
      <div className="v2-msg tool" data-testid="msg-tool">
        <div className="v2-msg-body">
          <ToolActivityPanel activities={[fallbackActivity]} />
          <MessageTime ts={msg.ts} />
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
        {Array.isArray(msg.toolActivities) && msg.toolActivities.length > 0 ? (
          <ToolActivityPanel activities={msg.toolActivities} streaming={msg.streaming} />
        ) : null}
        {Array.isArray(msg.toolCalls) && msg.toolCalls.length > 0 ? (
          /* 出产物（对齐 DSH deliverables）：编辑的文件即时可见可打开 */
          <ProducedFiles calls={msg.toolCalls} />
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
            {msg.tokens_in && msg.tokens_cache_hit !== undefined && msg.tokens_cache_hit !== null
              ? // EVO-20260818（spec §5.4.1-1，grill-me Q6）: 口径标注——本轮请求命中率；
                // 权威口径为会话近 10 次窗口（architecture_status.cache_guard）
                ` · ⚡ ${((msg.tokens_cache_hit / msg.tokens_in) * 100).toFixed(1)}%（本轮）`
              : ""}
          </div>
        ) : null}
        {msg.note ? <div className="v2-msg-note">{msg.note}</div> : null}
        <MessageTime ts={msg.ts} />
        <div className="v2-msg-actions">
          <CopyButton text={msg.content} />
          {caps.feedback && typeof index === "number" && sessionId ? <FeedbackButtons sessionId={sessionId} index={index} /> : null}
        </div>
      </div>
    </div>
  );
}

/** 历史消息 → 代码块识别渲染（消息内容内嵌 markdown 代码块） */
export function MessageBody({ text }: { text: string }) {
  return <Markdown text={text} />;
}
