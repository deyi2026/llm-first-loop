// Web V2：目录浏览器模态（对齐 DSH directory-browser：应用内选择工作区目录）
// 纯 Web 无法用原生对话框拿绝对路径 → 后端 /api/v1/fs/dirs 提供目录导航。

import { useEffect, useState } from "react";
import { fetchDirs, registerWorkspace, type WorkspaceInfo } from "../../core/api";

interface DirBrowserProps {
  /** 打开成功回调（携带新工作区完整信息） */
  onOpened: (ws: WorkspaceInfo) => void;
  onClose: () => void;
}

function basename(path: string): string {
  const parts = path.replace(/\\/g, "/").split("/").filter(Boolean);
  return parts[parts.length - 1] ?? path;
}

export function DirBrowser({ onOpened, onClose }: DirBrowserProps) {
  const [path, setPath] = useState(""); // "" = 后端默认家目录
  const [parent, setParent] = useState<string | null>(null);
  const [dirs, setDirs] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const load = (p: string) => {
    setLoading(true);
    setError("");
    void fetchDirs(p).then((data) => {
      setLoading(false);
      if (!data) {
        setError("目录读取失败（服务不可用）");
        return;
      }
      setPath(data.path);
      setParent(data.parent);
      setDirs(data.dirs);
    });
  };

  useEffect(() => {
    load("");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const open = async () => {
    setBusy(true);
    setError("");
    const ws = await registerWorkspace(path);
    setBusy(false);
    if (!ws) {
      setError("打开失败（路径不存在或服务不可用）");
      return;
    }
    onOpened(ws);
  };

  return (
    <div className="v2-dir-mask" data-testid="dir-browser" onClick={onClose}>
      <div className="v2-dir-card" onClick={(e) => e.stopPropagation()}>
        <div className="v2-dir-head">
          <span className="v2-dir-path" title={path || "家目录"}>
            {path ? basename(path) : "家目录"}
          </span>
          <button type="button" className="v2-preview-close" onClick={onClose} aria-label="关闭">
            ✕
          </button>
        </div>
        <div className="v2-dir-body">
          {parent ? (
            <button type="button" className="v2-dir-row parent" onClick={() => load(parent)} data-testid="dir-up">
              <span className="v2-dir-row-name">⬆ 上级：{basename(parent)}</span>
            </button>
          ) : null}
          {loading ? (
            <div className="v2-dir-hint">加载中…</div>
          ) : error ? (
            <div className="v2-dir-hint err">{error}</div>
          ) : dirs.length === 0 ? (
            <div className="v2-dir-hint">（无子目录）</div>
          ) : (
            dirs.map((name) => (
              <button
                key={name}
                type="button"
                className="v2-dir-row"
                onClick={() => load(`${path}/${name}`)}
                data-testid="dir-item"
              >
                <span className="v2-dir-row-icon">📂</span>
                <span className="v2-dir-row-name">{name}</span>
                <span className="v2-dir-row-arrow">▸</span>
              </button>
            ))
          )}
        </div>
        <div className="v2-dir-foot">
          <span className="v2-dir-full">{path || "~（家目录）"}</span>
          <button
            type="button"
            className="v2-btn primary"
            disabled={busy || !path}
            onClick={() => void open()}
            data-testid="dir-open"
          >
            {busy ? "打开中…" : "打开此目录"}
          </button>
        </div>
      </div>
    </div>
  );
}
