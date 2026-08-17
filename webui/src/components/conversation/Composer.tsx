// Web V2：输入区（对齐 DSH composer：
// 文本域自动增高 / Enter 发送 Shift+Enter 换行 / 发送·停止切换 / 附件图片预览
// / “/” 命令面板（匹配+选项+应用中）/ 模型选择下拉）

import { useEffect, useMemo, useRef, useState } from "react";
import { zh } from "../../i18n/zh";
import { sendMessage, stopStreaming, useConversation } from "../../core/conversation";
import { fetchModels, uploadFileBase64 } from "../../core/chat";
import { forkSession, setSessionPin } from "../../core/api";
import { sessionStore, useModel } from "../../core/stores";
import { EVT_COMPOSER_FILL, focusSearch } from "../../core/shortcuts";

type AttachStatus = "ok" | "pending" | "degraded" | "error";

interface Attachment {
  filename: string;
  result_text: string;
  preview?: string;
  status: AttachStatus;
  detail?: string;
}

interface CommandOption {
  label: string;
  run: () => void;
}

interface CommandDef {
  name: string;
  desc: string;
  /** 同步选项（如 /model 目录）；渲染期随状态自动刷新 */
  options?: () => CommandOption[];
  run: (arg: string) => void;
}

export function Composer() {
  const conv = useConversation();
  const [text, setText] = useState("");
  const [attachments, setAttachments] = useState<Attachment[]>([]);
  const [cmdOpen, setCmdOpen] = useState(false);
  const [cmdMatch, setCmdMatch] = useState<CommandDef[]>([]);
  const [cmdOptions, setCmdOptions] = useState<CommandOption[]>([]);
  const [models, setModels] = useState<string[]>([]);
  // 模型列表 ref：命令 options 闭包始终读最新值（cmdMatch 旧闭包竞态修复）
  const modelsRef = useRef<string[]>([]);
  const [hint, setHint] = useState("");
  const hintTimer = useRef<number | null>(null);
  const taRef = useRef<HTMLTextAreaElement>(null);

  const flashHint = (msg: string) => {
    setHint(msg);
    if (hintTimer.current) window.clearTimeout(hintTimer.current);
    hintTimer.current = window.setTimeout(() => setHint(""), 2500);
  };

  // 模型目录（下拉与 /model 命令共用；initial current 同步到会话模型覆盖）
  useEffect(() => {
    void fetchModels().then(({ models, current }) => {
      modelsRef.current = models;
      setModels(models);
      if (current && !sessionStore.getState().model) sessionStore.setModel(current);
    });
  }, []);

  // models 到达/变更时刷新命令选项（修复竞态：先输入 /model、选项后到）
  useEffect(() => {
    modelsRef.current = models;
    if (cmdOpen && cmdMatch.length === 1 && cmdMatch[0].options) {
      setCmdOptions(cmdMatch[0].options());
    }
  }, [models, cmdOpen]);

  const commands: CommandDef[] = useMemo(
    () => [
      {
        name: "new",
        desc: "新建会话",
        run: () => {
          sessionStore.setCurrentSession("");
          window.location.reload();
        },
      },
      {
        name: "clear",
        desc: "清除上下文（下一条消息进入全新会话）",
        run: () => {
          sessionStore.setCurrentSession("");
          window.location.reload();
        },
      },
      {
        name: "model",
        desc: "选择模型（当前请求生效）",
        options: () =>
          modelsRef.current.map((m) => ({
            label: m,
            run: () => {
              sessionStore.setModel(m);
              flashHint(`已选择模型：${m}（当前请求生效）`);
            },
          })),
        run: (arg) => {
          if (arg) {
            sessionStore.setModel(arg);
            flashHint(`已选择模型：${arg}（当前请求生效）`);
          }
        },
      },
      {
        name: "fork",
        desc: "分叉当前会话（保留分支继续）",
        run: async () => {
          const sid = sessionStore.getState().currentSessionId;
          if (!sid) {
            flashHint(zh.noSession);
            return;
          }
          const report = await forkSession(sid);
          if (report?.new_session_id) {
            flashHint(`已分叉 → ${report.new_session_id.slice(0, 8)}…`);
          } else {
            flashHint(zh.forkFailed);
          }
        },
      },
      {
        name: "pin",
        desc: "置顶 / 取消置顶当前会话",
        run: async () => {
          const sid = sessionStore.getState().currentSessionId;
          if (!sid) {
            flashHint(zh.noSession);
            return;
          }
          const pinned = await setSessionPin(sid, true);
          flashHint(pinned ? zh.pinned : zh.pinFailed);
        },
      },
      {
        name: "stats",
        desc: "查看当前会话统计（轮次/耗时/缓存命中率）",
        run: async () => {
          const sid = sessionStore.getState().currentSessionId;
          if (!sid) {
            flashHint(zh.noSession);
            return;
          }
          try {
            const resp = await fetch(`/api/v1/sessions/${encodeURIComponent(sid)}/stats`);
            if (!resp.ok) {
              flashHint(zh.statsFailed);
              return;
            }
            const s = await resp.json();
            const rate = s.tokens_in
              ? ((s.cache_hit ?? 0) / s.tokens_in) * 100
              : 0;
            flashHint(
              `统计: ${s.turns ?? 0} 轮 · ${s.steps ?? 0} 步 · 命中率 ${rate.toFixed(1)}% · LLM ${(
                (s.llm_ms ?? 0) / 1000
              ).toFixed(1)}s`
            );
          } catch {
            flashHint(zh.statsFailed);
          }
        },
      },
      {
        name: "help",
        desc: "列出全部命令",
        run: () => {
          flashHint(
            commands
              .map((c) => `/${c.name}—${c.desc}`)
              .join(" · ")
          );
        },
      },
    ],
    [models]
  );

  const autoGrow = () => {
    const el = taRef.current;
    if (!el) return;
    if (!el.value) {
      // 空内容 → 清除内联高度，恢复 CSS 默认（scrollHeight 含 padding 不等于默认行高）
      el.style.height = "";
      return;
    }
    el.style.height = "auto";
    el.style.height = Math.min(el.scrollHeight, 180) + "px";
  };

  // text 变化（含发送/命令清空）后按渲染结果复位高度——
  // 发送后 setText("") 是异步渲染，若在 doSend 内同步调 autoGrow 会读到旧 scrollHeight
  useEffect(() => {
    autoGrow();
  }, [text]);

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      void doSend();
      return;
    }
    if (e.key === "Escape") {
      if (cmdOpen) {
        setCmdOpen(false);
        return;
      }
      if (conv.streaming) {
        // 对齐 DSH：Esc 停止流式生成（非命令菜单态）
        e.preventDefault();
        stopStreaming();
        flashHint(zh.streamStopped);
      }
      return;
    }
    if (e.key === "ArrowUp" && !e.shiftKey && !text.trim()) {
      // 对齐 DSH：输入为空时 ↑ 回填上一条 user 消息（编辑后重发）
      const msgs = conv.messages;
      for (let i = msgs.length - 1; i >= 0; i--) {
        if (msgs[i].role === "user" && msgs[i].content?.trim()) {
          e.preventDefault();
          setText(msgs[i].content as string);
          return;
        }
      }
      return;
    }
    if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
      // 对齐 DSH：⌘K / Ctrl+K 聚焦会话内搜索
      e.preventDefault();
      focusSearch();
    }
  };

  // 对齐 DSH：跨组件回填（↑/user 消息"重发"）→ 填入文本并聚焦
  useEffect(() => {
    const onFill = (e: Event) => {
      const text0 = (e as CustomEvent<{ text: string }>).detail?.text ?? "";
      setText(text0);
      setCmdOpen(false);
      requestAnimationFrame(() => taRef.current?.focus());
    };
    window.addEventListener(EVT_COMPOSER_FILL, onFill);
    return () => window.removeEventListener(EVT_COMPOSER_FILL, onFill);
  }, []);

  const onTextChange = (v: string) => {
    setText(v); // 高度自适应由 useEffect([text]) 统一处理
    if (v.startsWith("/") && !v.includes(" ")) {
      const q = v.slice(1).toLowerCase();
      const matches = commands.filter((c) => c.name.startsWith(q));
      setCmdMatch(matches);
      setCmdOpen(matches.length > 0);
      setCmdOptions(matches.length === 1 && matches[0].options ? matches[0].options() : []);
    } else {
      setCmdOpen(false);
    }
  };

  const doSend = async () => {
    const trimmed = text.trim();
    if (!trimmed || conv.streaming) return;
    // 命令分支（纯前端，对齐 M39）
    if (trimmed.startsWith("/")) {
      const [name, ...rest] = trimmed.slice(1).split(/\s+/);
      const cmd = commands.find((c) => c.name === name);
      if (cmd) {
        cmd.run(rest.join(" "));
        setText(""); // 高度复位由 useEffect([text]) 处理
        setCmdOpen(false);
        return;
      }
    }
    // 乐观 UI（2026-08-15 现场反馈）：发送即清空输入与附件——
    // 流式完成前文字留在框里会让人以为"没发出去/没反馈"
    setText(""); // 高度复位由 useEffect([text]) 处理
    setAttachments([]);
    setCmdOpen(false);
    await sendMessage(trimmed, attachments);
  };

  const onPickFile = async (file: File) => {
    const reader = new FileReader();
    reader.onload = async () => {
      const b64 = String(reader.result).split(",")[1] ?? "";
      const { status, data } = await uploadFileBase64(file.name, b64);
      if (status === 200) {
        const attach: Attachment = {
          filename: file.name,
          result_text: data.result_text ?? "",
          preview: file.type.startsWith("image/") ? String(reader.result) : undefined,
          status: (data.status as AttachStatus) ?? "error",
          detail: data.detail,
        };
        setAttachments((prev) => [...prev, attach]);
      } else {
        setAttachments((prev) => [
          ...prev,
          {
            filename: file.name,
            result_text: "",
            status: "error",
            detail: `上传失败（${status}）：${data.detail ?? "未知错误"}`,
          },
        ]);
      }
    };
    reader.readAsDataURL(file);
  };

  const currentModel = useModel();

  return (
    <div className="v2-composer" data-testid="composer">
      {attachments.length > 0 && (
        <div className="v2-attachments">
          {attachments.map((a, i) => (
            <div key={i} className={`v2-attachment ${a.status}`}>
              {a.preview ? <img src={a.preview} alt={a.filename} /> : <span>📄</span>}
              <span className="v2-attachment-name" title={a.detail ?? ""}>
                {a.filename}
                {a.status === "degraded" || a.status === "error" ? "（降级/失败）" : ""}
              </span>
              <button
                type="button"
                className="v2-icon-btn"
                onClick={() => setAttachments((prev) => prev.filter((_, j) => j !== i))}
                title="移除"
              >
                ✕
              </button>
            </div>
          ))}
        </div>
      )}
      {cmdOpen && (
        <div className="v2-cmd-popup" data-testid="cmd-popup">
          {cmdOptions.map((o, i) => (
            <button
              key={i}
              type="button"
              className="v2-cmd-item"
              onClick={() => {
                o.run();
                setCmdOpen(false);
                setCmdOptions([]);
                taRef.current?.focus();
              }}
            >
              {o.label}
            </button>
          ))}
          {cmdMatch.map((c) => (
              <button
                key={c.name}
                type="button"
                className="v2-cmd-item"
                onClick={() => {
                  if (c.options) {
                    // 有选项的命令：点击 → 展示选项（如 /model 目录，同步刷新）
                    setCmdOptions(c.options());
                  } else {
                    c.run("");
                    setText("");
                    setCmdOpen(false);
                    taRef.current?.focus();
                  }
                }}
              >
                <span className="v2-cmd-name">/{c.name}</span>
                <span className="v2-cmd-desc">{c.desc}</span>
              </button>
            ))}
        </div>
      )}
      <div className="v2-composer-bar">
        <textarea
          ref={taRef}
          className="v2-composer-input"
          placeholder={zh.composerPlaceholder}
          value={text}
          onChange={(e) => onTextChange(e.target.value)}
          onKeyDown={handleKeyDown}
          rows={1}
          data-testid="composer-input"
        />
        <div className="v2-composer-actions">
          <select
            className="v2-model-select"
            value={currentModel ?? ""}
            onChange={(e) => sessionStore.setModel(e.target.value || null)}
            title={zh.modelSelect}
            data-testid="model-select"
          >
            <option value="">{zh.modelDefault}</option>
            {models.map((m) => (
              <option key={m} value={m}>
                {m}
              </option>
            ))}
          </select>
          <label className="v2-icon-btn" title={zh.attach}>
            📎
            <input
              type="file"
              hidden
              accept="image/*,.txt,.md,.pdf,.docx"
              onChange={(e) => {
                const f = e.target.files?.[0];
                if (f) void onPickFile(f);
                e.target.value = "";
              }}
            />
          </label>
          {conv.streaming ? (
            <button type="button" className="v2-btn primary" onClick={stopStreaming}>
              ■ {zh.stop}
            </button>
          ) : (
            <button
              type="button"
              className="v2-btn primary"
              onClick={() => void doSend()}
              disabled={!text.trim()}
            >
              {zh.send}
            </button>
          )}
        </div>
      </div>
      <div className="v2-composer-hint" data-testid="composer-hint">
        {hint || zh.composerHint}
      </div>
    </div>
  );
}
