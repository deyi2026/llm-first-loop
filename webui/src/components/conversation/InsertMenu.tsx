import { useRef, useState } from "react";
import {
  fetchFsTree,
  fetchRecentAttachments,
  importWorkspaceAttachment,
  type AttachmentLibraryItem,
  type FsTree,
} from "../../core/api";
import type { ComposerAttachment } from "./composerTypes";

interface InsertMenuProps {
  disabled?: boolean;
  onFiles: (files: File[]) => void;
  onAddAttachment: (attachment: Omit<ComposerAttachment, "id">) => void;
}

function childPath(base: string, name: string): string {
  if (!base) return name;
  return `${base.replace(/[\\/]$/, "")}/${name}`;
}

export function InsertMenu({ disabled, onFiles, onAddAttachment }: InsertMenuProps) {
  const [open, setOpen] = useState(false);
  const [view, setView] = useState<"main" | "recent" | "workspace">("main");
  const [recent, setRecent] = useState<AttachmentLibraryItem[]>([]);
  const [tree, setTree] = useState<FsTree | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);

  const resetError = () => setError("");

  const openRecent = async () => {
    setView("recent");
    setBusy(true);
    resetError();
    const items = await fetchRecentAttachments(30);
    setRecent(items);
    setBusy(false);
  };

  const openWorkspace = async (path = "") => {
    setView("workspace");
    setBusy(true);
    resetError();
    const result = await fetchFsTree(path);
    setTree(result);
    if (!result) setError("工作区文件列表读取失败。可关闭菜单后重试。");
    setBusy(false);
  };

  const importFile = async (path: string) => {
    setBusy(true);
    resetError();
    const { status, data } = await importWorkspaceAttachment(path);
    setBusy(false);
    const ref = typeof data.attachment_ref === "string" ? data.attachment_ref : "";
    const filename = typeof data.source_filename === "string" ? data.source_filename : path.split("/").pop() || path;
    const itemStatus = typeof data.status === "string" ? data.status : "error";
    if (status !== 200 || !ref) {
      setError(String(data.detail ?? `导入失败（${status || "网络"}）`));
      return;
    }
    onAddAttachment({
      filename,
      result_text: String(data.result_text ?? ""),
      status: itemStatus === "ok" ? "ok" : itemStatus === "degraded" ? "degraded" : "error",
      detail: typeof data.detail === "string" ? data.detail : undefined,
      attachment_ref: ref,
      content_type: typeof data.content_type === "string" ? data.content_type : undefined,
      size_bytes: typeof data.size_bytes === "number" ? data.size_bytes : undefined,
      sha256: typeof data.sha256 === "string" ? data.sha256 : undefined,
    });
    setOpen(false);
  };

  const useRecent = (item: AttachmentLibraryItem) => {
    onAddAttachment({
      filename: item.filename,
      result_text: "",
      status: "ok",
      attachment_ref: item.ref,
      content_type: item.content_type,
      size_bytes: item.size_bytes,
      sha256: item.sha256,
    });
    setOpen(false);
  };

  return (
    <div className="v2-insert-wrap">
      <button
        type="button"
        className="v2-round-btn"
        aria-label="添加内容"
        title="添加文件、工作区文件或最近附件"
        disabled={disabled}
        onClick={() => {
          setOpen((value) => !value);
          setView("main");
          resetError();
        }}
        data-testid="insert-button"
      >
        ＋
      </button>
      <input
        ref={inputRef}
        type="file"
        hidden
        multiple
        accept="image/*,.txt,.md,.pdf,.docx"
        onChange={(event) => {
          const files = Array.from(event.target.files ?? []);
          if (files.length) onFiles(files);
          event.target.value = "";
          setOpen(false);
        }}
        data-testid="file-input"
      />
      {open ? (
        <div className="v2-insert-popover" data-testid="insert-popover">
          {view !== "main" ? (
            <button type="button" className="v2-popover-back" onClick={() => setView("main")}>← 返回</button>
          ) : null}
          {view === "main" ? (
            <>
              <button type="button" onClick={() => inputRef.current?.click()}>📎 上传文件 <span>多选 / ≤10MB</span></button>
              <button type="button" onClick={() => void openWorkspace()}>📁 从工作区选择 <span>显式导入引用</span></button>
              <button type="button" onClick={() => void openRecent()}>🕘 最近附件 <span>无需重新上传</span></button>
            </>
          ) : null}
          {view === "recent" ? (
            <div className="v2-picker-list">
              {busy ? <div className="v2-picker-empty">读取中…</div> : null}
              {!busy && recent.length === 0 ? <div className="v2-picker-empty">暂无最近附件</div> : null}
              {recent.map((item) => (
                <button key={item.ref} type="button" onClick={() => useRecent(item)}>
                  <strong>{item.filename}</strong>
                  <span>{item.size_bytes ? `${Math.ceil(item.size_bytes / 1024)} KB` : "附件"}</span>
                </button>
              ))}
            </div>
          ) : null}
          {view === "workspace" ? (
            <div className="v2-picker-list">
              {busy ? <div className="v2-picker-empty">读取中…</div> : null}
              {tree?.parent ? (
                <button type="button" onClick={() => void openWorkspace(tree.parent || "")}>📁 .. <span>上级</span></button>
              ) : null}
              {tree?.dirs.map((name) => (
                <button key={`d:${name}`} type="button" onClick={() => void openWorkspace(childPath(tree.path, name))}>
                  📁 <strong>{name}</strong>
                </button>
              ))}
              {tree?.files.map((file) => (
                <button key={`f:${file.name}`} type="button" disabled={busy} onClick={() => void importFile(childPath(tree.path, file.name))}>
                  📄 <strong>{file.name}</strong><span>{Math.ceil(file.size / 1024)} KB</span>
                </button>
              ))}
            </div>
          ) : null}
          {error ? <div className="v2-popover-error">{error}</div> : null}
        </div>
      ) : null}
    </div>
  );
}
