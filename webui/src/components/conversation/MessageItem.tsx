// Web V2：消息渲染（对齐 DSH 会话 UI：
// 用户右侧气泡（--dsw-specific-bubble）、助手全宽正文、思考块默认折叠、
// 工具行折叠链、代码块 banner（语言+复制）+ 高亮 + 长块分块、笔记 footer）

import { memo, useEffect, useMemo, useRef, useState } from "react";
import type {
  AttachmentFact,
  ChatMessage,
  ProgressStage,
  ToolActivity,
  ToolActivityStatus,
  ToolCallInfo,
} from "../../core/types";
import {
  ensureMathRenderer,
  hasMathCandidate,
  isMathRendererReady,
  renderMarkdown,
} from "../../core/markdown";
import { formatTokens } from "../../core/chat";
import { forkSession, submitFeedback } from "../../core/api";
import { useCapabilities } from "../../core/capabilities";
import { loadHistory, prefillComposer } from "../../core/conversation";
import { sessionStore } from "../../core/stores";
import { normalizeToolStatus, parseToolReceiptStatus } from "../../core/toolActivity";
import { previewTabsStore } from "../../core/stores";
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

/** 流式 live 视图的解析窗口上限（字符）；终态渲染始终全量。
 *  16KB 实测（vitest bench）：代码密集 ~50ms/次。 */
const LIVE_PARSE_MAX_CHARS = 16 * 1024;

function Markdown({
  text,
  clickablePaths,
  enableMath = true,
  live = false,
}: {
  text: string;
  clickablePaths?: Set<string>;
  enableMath?: boolean;
  /** 流式中渲染（msg.streaming）：解析按自适应退避节流 + 尾部窗口上限。
   *  高频 delta（真实 provider 可达 100+/s）逐条全量重解析会饱和主线程，
   *  把点击/切换事件饿死（2026-09-22 "推理时切换不了会话" 事故实测 longtask
   *  秒级）。终态由 streaming=false 的完整渲染兜底，内容零丢失。 */
  live?: boolean;
}) {
  const [mathRevision, setMathRevision] = useState(0);
  const gate = useRef<{ at: number; dur: number; text: string; html: string }>({
    at: 0,
    dur: 0,
    text: "",
    html: "",
  });
  useEffect(() => {
    if (live || !enableMath || isMathRendererReady() || !hasMathCandidate(text)) return;
    let active = true;
    void ensureMathRenderer()
      .then(() => {
        if (active) setMathRevision((value) => value + 1);
      })
      .catch(() => {
        // Chunk/network failure is non-fatal: the literal Markdown remains readable.
      });
    return () => {
      active = false;
    };
  }, [text, enableMath, live]);
  const html = useMemo(() => {
    if (live) {
      const now = Date.now();
      if (gate.current.text === text) return gate.current.html;
      // 自适应退避：下次解析距上次至少 max(200ms, 2×上次解析耗时)，占空比 ≤1/3
      if (gate.current.html && now - gate.current.at < Math.max(200, gate.current.dur * 2)) {
        return gate.current.html;
      }
      // live 视图只解析尾部窗口；完整内容由终态渲染保证（不截断存储与终态）
      let source = text;
      if (text.length > LIVE_PARSE_MAX_CHARS) {
        const cut = text.lastIndexOf("\n\n", text.length - LIVE_PARSE_MAX_CHARS);
        source = text.slice(cut >= 0 ? cut + 2 : text.length - LIVE_PARSE_MAX_CHARS);
      }
      // live 禁 KaTeX：每公式产出 1-2KB span 汤并进 DOMPurify——公式密集内容
      // 单次解析秒级；公式终态全量渲染，流式期间原文显示。
      const t0 = performance.now();
      const parsed = renderMarkdown(source, clickablePaths, { enableMath: false });
      gate.current = { at: now, dur: performance.now() - t0, text, html: parsed };
      return parsed;
    }
    return renderMarkdown(text, clickablePaths, { enableMath });
  }, [text, clickablePaths, enableMath, live, mathRevision]);
  // 代码块复制按钮 + 出产物内联路径链接：dangerouslySetInnerHTML 内容无法绑
  // React 事件 → 事件委托。链接点击 → 右侧栏预览 tab（对齐 DSH openResource，
  // `path:42`/`path:42:7` 形式携带 1-based 行/列锚点）。
  const onBodyClick = async (e: React.MouseEvent<HTMLDivElement>) => {
    const target = e.target as HTMLElement;
    const link = target.closest?.(".v2-file-link") as HTMLElement | null;
    if (link) {
      const p = link.getAttribute("data-path");
      if (p) {
        const lineRaw = link.getAttribute("data-line");
        const colRaw = link.getAttribute("data-col");
        const line = lineRaw ? Number.parseInt(lineRaw, 10) : NaN;
        const col = colRaw ? Number.parseInt(colRaw, 10) : NaN;
        previewTabsStore.open(
          p,
          Number.isFinite(line) ? line : null,
          Number.isFinite(col) ? col : null
        );
      }
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
    <div className="v2-md" onClick={onBodyClick} dangerouslySetInnerHTML={{ __html: html }} />
  );
}

function ThinkingBlock({ text, streaming }: { text: string; streaming?: boolean }) {
  // The block mounts on the first reasoning delta. Make live reasoning visible immediately;
  // historical reasoning remains collapsed by default, and the user can still close a live block.
  const [open, setOpen] = useState(Boolean(streaming));
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
          <Markdown text={text} enableMath={false} live={Boolean(streaming)} />
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

const PROGRESS_HEARTBEAT_MS = 12_000;

function progressStageLabel(stage: ProgressStage | undefined): string {
  switch (stage) {
    case "preparing": return "正在准备";
    case "analyzing": return "正在分析";
    case "tool": return "正在使用工具";
    case "integrating": return "正在整理结果";
    case "answering": return "正在生成回答";
    case "recovering": return "正在恢复连接";
    default: return "正在处理";
  }
}

function progressSnapshot(msg: ChatMessage, now: number): {
  stage: string;
  summary: string;
  next: string;
  heartbeat: string | null;
} {
  const activities = msg.toolActivities ?? [];
  const running = activities.filter((item) => item.status === "running");
  const issues = activities.filter((item) =>
    ["failure", "error", "blocked", "unauthorized", "timeout", "cancelled", "interrupted", "unknown"].includes(item.status)
  );
  const completed = activities.length - running.length;
  const activeTool = running.at(-1);
  const latestSettled = [...activities].reverse().find((item) => item.status !== "running");
  const stage = progressStageLabel(msg.progressStage);

  let summary = "正在提交请求并等待运行确认。";
  let next = "收到运行回执后继续显示模型与工具阶段。";
  if (msg.progressStage === "recovering") {
    summary = "正在重新连接当前后台 run，并恢复可重放的执行事实。";
    next = "恢复后继续显示原 run 的工具和输出进展。";
  } else if (activeTool) {
    const subtitle = activitySubtitle(activeTool);
    summary = `正在执行 ${toolDisplayName(activeTool.name)}${subtitle ? ` · ${subtitle}` : ""}`;
    next = "等待工具返回后继续分析。";
  } else if (msg.progressStage === "integrating" || (activities.length > 0 && !msg.content)) {
    const resultSize = latestSettled && typeof latestSettled.resultChars === "number"
      ? latestSettled.resultChars >= 1000
        ? `${(latestSettled.resultChars / 1000).toFixed(1)}k 字符`
        : `${latestSettled.resultChars} 字符`
      : "";
    const duration = latestSettled && typeof latestSettled.durationMs === "number"
      ? latestSettled.durationMs >= 1000
        ? `${(latestSettled.durationMs / 1000).toFixed(1)}s`
        : `${Math.round(latestSettled.durationMs)}ms`
      : "";
    const latestFact = latestSettled
      ? [toolDisplayName(latestSettled.name), resultSize, duration].filter(Boolean).join(" · ")
      : "";
    summary = `已完成 ${completed} 个工具步骤${issues.length ? `，其中 ${issues.length} 个需要关注` : ""}${latestFact ? `。最近结果：${latestFact}` : "。"}`;
    next = issues.length ? "根据现有结果判断是否需要恢复或替代路径。" : "正在整合结果并决定下一步。";
  } else if (msg.progressStage === "answering" || msg.content) {
    summary = activities.length
      ? `已处理 ${completed} 个工具步骤，正在组织最终回答。`
      : "已有足够信息，正在组织回答。";
    next = "继续输出最终内容。";
  } else if (msg.progressStage === "analyzing" || msg.reasoningContent) {
    summary = activities.length
      ? `已获得 ${completed} 个工具结果，正在继续分析。`
      : "正在分析当前请求并确定所需步骤。";
    next = "需要外部证据时会显示相应工具调用。";
  }

  const updatedAt = msg.progressUpdatedAt ?? msg.streamStartedAt ?? now;
  const idleMs = Math.max(0, now - updatedAt);
  const heartbeat = idleMs >= PROGRESS_HEARTBEAT_MS
    ? activeTool
      ? `${toolDisplayName(activeTool.name)} 仍在执行 · ${Math.floor(idleMs / 1000)} 秒无新事件`
      : `仍在处理 · ${Math.floor(idleMs / 1000)} 秒无新事件`
    : null;
  return { stage, summary, next, heartbeat };
}

function ProgressCard({ msg }: { msg: ChatMessage }) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!msg.streaming) return;
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [msg.streaming]);
  const snapshot = useMemo(() => progressSnapshot(msg, now), [msg, now]);
  const elapsedMs = Math.max(0, now - (msg.streamStartedAt ?? now));

  return (
    <section className="v2-progress-card" data-testid="progress-card" aria-live="polite">
      <div className="v2-progress-head">
        <span className="v2-progress-dot" aria-hidden="true" />
        <strong>{snapshot.stage}</strong>
        <span className="v2-progress-elapsed">{Math.floor(elapsedMs / 1000)}s</span>
      </div>
      <div className="v2-progress-summary">{snapshot.summary}</div>
      <div className="v2-progress-next"><span>预计下一步</span>{snapshot.next}</div>
      {snapshot.heartbeat ? <div className="v2-progress-heartbeat">{snapshot.heartbeat}</div> : null}
    </section>
  );
}

/** 出产物文件预览：chips/正文链接统一走 previewTabsStore.open → 右侧栏
 *  预览 tab（components/PreviewTabsPanel.tsx + FilePreviewView.tsx）。 */

/** 出产物路径提取（edit_file/write_file 参数路径 + present_files 显式声明，去重）——chips 与正文链接共用 */
export function extractProducedPaths(calls: ToolCallInfo[] | null | undefined): string[] {
  const out: string[] = [];
  for (const t of calls ?? []) {
    if (t.name === "present_files") {
      // DSH present 语义对齐：模型显式声明的交付物（execute_command 等方式
      // 创建的产物只有这里有路径事实）。全有或全无由工具侧裁决，展示层只提取。
      const files = (t.arguments as Record<string, unknown>)?.files;
      if (Array.isArray(files)) {
        for (const f of files) {
          const p = (f as Record<string, unknown> | null)?.path;
          if (typeof p === "string" && p.trim() && !out.includes(p.trim())) out.push(p.trim());
        }
      }
      continue;
    }
    if (t.name !== "edit_file" && t.name !== "write_file") continue;
    const p = (t.arguments as Record<string, unknown>)?.path;
    if (typeof p === "string" && p.trim() && !out.includes(p)) out.push(p.trim());
  }
  return out;
}

/** present_files 声明携带的 description（path → 说明，供 chip tooltip） */
export function extractProducedDescriptions(
  calls: ToolCallInfo[] | null | undefined
): Map<string, string> {
  const out = new Map<string, string>();
  for (const t of calls ?? []) {
    if (t.name !== "present_files") continue;
    const files = (t.arguments as Record<string, unknown>)?.files;
    if (!Array.isArray(files)) continue;
    for (const f of files) {
      const item = f as Record<string, unknown> | null;
      const p = typeof item?.path === "string" ? item.path.trim() : "";
      const desc = typeof item?.description === "string" ? item.description.trim() : "";
      if (p && desc && !out.has(p)) out.set(p, desc);
    }
  }
  return out;
}

/** 出产物文件列表（edit_file/write_file 参数路径 + present_files 声明，点击打开预览） */
function ProducedFiles({ calls }: { calls: ToolCallInfo[] }) {
  const paths = useMemo(() => extractProducedPaths(calls), [calls]);
  const descriptions = useMemo(() => extractProducedDescriptions(calls), [calls]);
  if (paths.length === 0) return null;
  return (
    <div className="v2-produced" data-testid="produced-files">
      <span className="v2-produced-label">📄 出产物</span>
      {paths.map((p) => (
        <button
          key={p}
          type="button"
          className="v2-produced-chip"
          title={descriptions.get(p) || `打开 ${p}`}
          onClick={() => previewTabsStore.open(p)}
        >
          {p}
        </button>
      ))}
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
      {elapsed >= 5 ? `（已等待 ${elapsed}s，正在处理）` : ""}
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

export const MessageItem = memo(
  MessageItemImpl,
  // 2026-09-22（推理时切换不了会话事故）：流式 delta 每次只替换 streaming 消息
  // 引用；未变消息（patchStreaming 保持原引用）跳过重渲染，每 delta O(N)→O(1)。
  // producedPaths 不参与比较：内容只随流式消息工具轮增长，非流式消息渲染不变；
  // 路径可点击性在 run 终态 loadHistory 全量重渲染时补齐（自愈，无数据丢失）。
  (a, b) => a.msg === b.msg && a.index === b.index && a.sessionId === b.sessionId
);

function MessageItemImpl({
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
              <Markdown text={msg.content} clickablePaths={producedPaths} live={Boolean(msg.streaming)} />
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
        {msg.streaming ? <ProgressCard msg={msg} /> : null}
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
          <Markdown text={msg.content} clickablePaths={producedPaths} live={Boolean(msg.streaming)} />
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
