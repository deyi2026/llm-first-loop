// Web V2（对齐 DSH 左侧栏树）：文件/目录树
// 数据源：/api/v1/fs/tree（目录+文件，单层可展；工作区根内安全边界后端把关）
// 交互：目录展开/折叠（▶▼）、文件行（📄+大小）、hover 操作（复制路径/新建目录/
// 重命名/删除两步确认——DELETE confirm=true）

import { useEffect, useRef, useState } from "react";
import { fetchFsTree, fsDelete, fsMkdir, fsRename, type FsTree } from "../../core/api";
import { zh } from "../../i18n/zh";

interface TreeNode {
  path: string;
  name: string;
  kind: "dir" | "file";
  size?: number;
}

function fmtSize(n: number | undefined): string {
  if (n === undefined) return "";
  if (n < 1024) return `${n}B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)}K`;
  return `${(n / 1024 / 1024).toFixed(1)}M`;
}

export function FileTree() {
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [children, setChildren] = useState<Map<string, TreeNode[]>>(new Map());
  const [rootItems, setRootItems] = useState<TreeNode[]>([]);
  const [loadingRoot, setLoadingRoot] = useState(false);
  const [error, setError] = useState("");
  const [copied, setCopied] = useState<string | null>(null);
  // 操作态：renameTarget / confirmDelete（两步确认）/ newDirParent
  const [renameTarget, setRenameTarget] = useState<TreeNode | null>(null);
  const [renameValue, setRenameValue] = useState("");
  const [confirmDelete, setConfirmDelete] = useState<TreeNode | null>(null);
  const [newDirParent, setNewDirParent] = useState<string | null>(null);
  const [newDirValue, setNewDirValue] = useState("");
  const [busy, setBusy] = useState(false);
  const [root, setRoot] = useState("");
  const loadingRef = useRef<Set<string>>(new Set());

  const toNodes = (t: FsTree): TreeNode[] => [
    ...(t.dirs ?? []).map((name) => ({ path: `${t.path}/${name}`, name, kind: "dir" as const })),
    ...(t.files ?? []).map((f) => ({
      path: `${t.path}/${f.name}`,
      name: f.name,
      kind: "file" as const,
      size: f.size,
    })),
  ];

  const loadDir = async (path: string): Promise<TreeNode[]> => {
    if (loadingRef.current.has(path)) return [];
    loadingRef.current.add(path);
    try {
      const data = await fetchFsTree(path);
      return data ? toNodes(data) : [];
    } catch {
      return [];
    } finally {
      loadingRef.current.delete(path);
    }
  };

  // 根 = 工作区根（tree API ""）
  useEffect(() => {
    let alive = true;
    setLoadingRoot(true);
    setError("");
    void fetchFsTree("").then((data) => {
      if (!alive) return;
      if (data) {
        setRoot(data.path);
        setRootItems(toNodes(data));
      } else {
        setError("文件树读取失败（服务不可用）");
      }
      setLoadingRoot(false);
    });
    return () => {
      alive = false;
    };
  }, []);

  const toggle = async (node: TreeNode) => {
    const next = new Set(expanded);
    if (next.has(node.path)) {
      next.delete(node.path);
      setExpanded(next);
      return;
    }
    next.add(node.path);
    setExpanded(next);
    if (!children.has(node.path)) {
      const items = await loadDir(node.path);
      setChildren((prev) => {
        const m = new Map(prev);
        m.set(node.path, items);
        return m;
      });
    }
  };

  const copyPath = (path: string) => {
    void navigator.clipboard?.writeText(path).catch(() => undefined);
    setCopied(path);
    window.setTimeout(() => setCopied((v) => (v === path ? null : v)), 1200);
  };

  const doMkdir = async () => {
    if (!newDirParent || !newDirValue.trim()) return;
    setBusy(true);
    const ok = await fsMkdir(`${newDirParent}/${newDirValue.trim()}`);
    setBusy(false);
    if (ok) {
      setNewDirParent(null);
      setNewDirValue("");
      // 刷新父目录
      const items = await loadDir(newDirParent);
      setChildren((prev) => {
        const m = new Map(prev);
        m.set(newDirParent, items);
        return m;
      });
      setExpanded((prev) => new Set(prev).add(newDirParent));
    }
  };

  const doRename = async () => {
    if (!renameTarget || !renameValue.trim()) return;
    setBusy(true);
    const ok = await fsRename(renameTarget.path, renameValue.trim());
    setBusy(false);
    if (ok) {
      const parent = renameTarget.path.split("/").slice(0, -1).join("/");
      setRenameTarget(null);
      const items = await loadDir(parent || "");
      setChildren((prev) => {
        const m = new Map(prev);
        m.set(parent || "", items);
        return m;
      });
    }
  };

  const doDelete = async () => {
    if (!confirmDelete) return;
    setBusy(true);
    const ok = await fsDelete(confirmDelete.path);
    setBusy(false);
    if (ok) {
      const parent = confirmDelete.path.split("/").slice(0, -1).join("/");
      setConfirmDelete(null);
      const items = await loadDir(parent || "");
      setChildren((prev) => {
        const m = new Map(prev);
        m.set(parent || "", items);
        return m;
      });
    }
  };

  const renderRow = (node: TreeNode, depth: number) => {
    const isOpen = expanded.has(node.path);
    const kids = children.get(node.path);
    const showArrow = node.kind === "dir";
    return (
      <div key={node.path} className="v2-tree-row" style={{ paddingLeft: 6 + depth * 14 }}>
        {showArrow ? (
          <button
            type="button"
            className="v2-tree-arrow"
            onClick={() => void toggle(node)}
            aria-label={isOpen ? "折叠" : "展开"}
          >
            {isOpen ? "▼" : "▶"}
          </button>
        ) : (
          <span className="v2-tree-arrow placeholder" />
        )}
        <span
          className={`v2-tree-icon ${node.kind}`}
          onClick={() => showArrow && void toggle(node)}
          title={node.path}
        >
          {node.kind === "dir" ? "📂" : "📄"}
        </span>
        <span className="v2-tree-name" title={node.path} onClick={() => showArrow && void toggle(node)}>
          {node.name}
          {node.kind === "file" && node.size !== undefined && (
            <span className="v2-tree-size">{fmtSize(node.size)}</span>
          )}
          {showArrow && isOpen && kids && kids.length === 0 && (
            <span className="v2-tree-empty-hint">（空）</span>
          )}
        </span>
        <span className="v2-tree-actions">
          {node.kind === "dir" && (
            <button
              type="button"
              className="v2-icon-btn"
              title={zh.newFolder}
              onClick={() => {
                setNewDirParent(node.path);
                setNewDirValue("");
              }}
            >
              ＋
            </button>
          )}
          <button
            type="button"
            className="v2-icon-btn"
            title={zh.rename}
            onClick={() => {
              setRenameTarget(node);
              setRenameValue(node.name);
            }}
          >
            ✎
          </button>
          <button
            type="button"
            className={`v2-icon-btn danger ${confirmDelete?.path === node.path ? "confirming" : ""}`}
            title={confirmDelete?.path === node.path ? zh.confirmDelete : zh.delete}
            onClick={() => {
              if (confirmDelete?.path !== node.path) {
                setConfirmDelete(node);
                window.setTimeout(() => setConfirmDelete((v) => (v?.path === node.path ? null : v)), 3000);
              } else {
                void doDelete();
              }
            }}
          >
            {confirmDelete?.path === node.path ? "确认?" : "🗑"}
          </button>
          <button type="button" className="v2-icon-btn" title={zh.copyPath} onClick={() => copyPath(node.path)}>
            {copied === node.path ? "✓" : "⧉"}
          </button>
        </span>
      </div>
    );
  };

  const renderNode = (node: TreeNode, depth: number) => {
    const rows = [renderRow(node, depth)];
    if (expanded.has(node.path) && node.kind === "dir") {
      const kids = children.get(node.path);
      if (kids && kids.length > 0) {
        for (const k of kids) rows.push(...renderNode(k, depth + 1));
      } else if (!kids) {
        rows.push(
          <div key={`${node.path}-loading`} className="v2-tree-loading" style={{ paddingLeft: 24 + depth * 14 }}>
            加载中…
          </div>
        );
      }
    }
    return rows;
  };

  return (
    <div className="v2-tree" data-testid="file-tree">
      <div className="v2-tree-head">
        <span className="v2-tree-title">📁 {zh.fileTree}</span>
        <span className="v2-tree-root" title={root}>
          {root ? root.split("/").filter(Boolean).pop() : "…"}
        </span>
      </div>
      <div className="v2-tree-body">
        {loadingRoot ? (
          <div className="v2-tree-loading">加载中…</div>
        ) : error ? (
          <div className="v2-tree-loading err">{error}</div>
        ) : rootItems.length === 0 ? (
          <div className="v2-tree-loading">（空工作区）</div>
        ) : (
          rootItems.map((n) => renderNode(n, 0))
        )}
      </div>
      {newDirParent && (
        <div className="v2-tree-inline-form" data-testid="mkdir-form">
          <input
            className="v2-tree-inline-input"
            placeholder={zh.newFolderName}
            value={newDirValue}
            autoFocus
            onChange={(e) => setNewDirValue(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") void doMkdir();
              if (e.key === "Escape") setNewDirParent(null);
            }}
          />
          <button type="button" className="v2-btn primary" disabled={busy || !newDirValue.trim()} onClick={() => void doMkdir()}>
            {zh.confirm}
          </button>
          <button type="button" className="v2-btn" onClick={() => setNewDirParent(null)}>
            {zh.cancel}
          </button>
        </div>
      )}
      {renameTarget && (
        <div className="v2-tree-inline-form" data-testid="rename-form">
          <input
            className="v2-tree-inline-input"
            placeholder={zh.rename}
            value={renameValue}
            autoFocus
            onChange={(e) => setRenameValue(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") void doRename();
              if (e.key === "Escape") setRenameTarget(null);
            }}
          />
          <button type="button" className="v2-btn primary" disabled={busy || !renameValue.trim()} onClick={() => void doRename()}>
            {zh.confirm}
          </button>
          <button type="button" className="v2-btn" onClick={() => setRenameTarget(null)}>
            {zh.cancel}
          </button>
        </div>
      )}
      <div className="v2-tree-hint">{zh.treeHint}</div>
    </div>
  );
}
