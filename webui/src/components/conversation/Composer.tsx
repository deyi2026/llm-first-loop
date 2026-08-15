// Web V2：输入区（对齐 DSH composer：
// 文本域自动增高 / Enter 发送 Shift+Enter 换行 / 发送·停止切换 / 附件图片预览
// / “/” 命令面板（匹配+选项+应用中）/ 模型选择下拉）

import { useEffect, useMemo, useRef, useState } from "react";
import { zh } from "../../i18n/zh";
import { sendMessage, stopStreaming, useConversation } from "../../core/conversation";
import { fetchModels, uploadFileBase64 } from "../../core/chat";
import { sessionStore } from "../../core/stores";
import type { ModelEntry } from "../../core/types";

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
  options?: () => Promise<CommandOption[]>;
  run: (arg: string) => void;
}

export function Composer() {
  const conv = useConversation();
  const [text, setText] = useState("");
  const [attachments, setAttachments] = useState<Attachment[]>([]);
  const [cmdOpen, setCmdOpen] = useState(false);
  const [cmdMatch, setCmdMatch] = useState<CommandDef[]>([]);
  const [cmdOptions, setCmdOptions] = useState<CommandOption[]>([]);
  const [cmdBusy, setCmdBusy] = useState(false);
  const [models, setModels] = useState<ModelEntry[]>([]);
  const [hint, setHint] = useState("");
  const hintTimer = useRef<number | null>(null);
  const taRef = useRef<HTMLTextAreaElement>(null);

  const flashHint = (msg: string) => {
    setHint(msg);
    if (hintTimer.current) window.clearTimeout(hintTimer.current);
    hintTimer.current = window.setTimeout(() => setHint(""), 2500);
  };

  // 模型目录（下拉与 /model 命令共用）
  useEffect(() => {
    void fetchModels().then(setModels);
  }, []);

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
        options: async () =>
          models.map((m) => ({
            label: String(m.id),
            run: () => {
              sessionStore.setModel(String(m.id));
              flashHint(`已选择模型：${m.id}（当前请求生效）`);
            },
          })),
        run: (arg) => {
          if (arg) {
            sessionStore.setModel(arg);
            flashHint(`已选择模型：${arg}（当前请求生效）`);
          }
        },
      },
    ],
    [models]
  );

  const autoGrow = () => {
    const el = taRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = Math.min(el.scrollHeight, 180) + "px";
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      void doSend();
    } else if (e.key === "Escape" && cmdOpen) {
      setCmdOpen(false);
    }
  };

  const onTextChange = (v: string) => {
    setText(v);
    autoGrow();
    if (v.startsWith("/") && !v.includes(" ")) {
      const q = v.slice(1).toLowerCase();
      const matches = commands.filter((c) => c.name.startsWith(q));
      setCmdMatch(matches);
      setCmdOpen(matches.length > 0);
      if (matches.length === 1 && matches[0].options) {
        setCmdBusy(true);
        void matches[0].options().then((opts) => {
          setCmdOptions(opts);
          setCmdBusy(false);
        });
      } else {
        setCmdOptions([]);
      }
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
        setText("");
        setCmdOpen(false);
        return;
      }
    }
    // 乐观 UI（2026-08-15 现场反馈）：发送即清空输入与附件——
    // 流式完成前文字留在框里会让人以为"没发出去/没反馈"
    setText("");
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

  const currentModel = sessionStore.getState().model;

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
          {cmdBusy && <div className="v2-cmd-item dim">正在加载选项…</div>}
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
          {!cmdBusy &&
            cmdMatch.map((c) => (
              <div key={c.name} className="v2-cmd-item static">
                <span className="v2-cmd-name">/{c.name}</span>
                <span className="v2-cmd-desc">{c.desc}</span>
              </div>
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
              <option key={String(m.id)} value={String(m.id)}>
                {String(m.id)}
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
