// Web V2（对齐 DSH 左侧栏树）：文件/目录树骨架
// 数据源：现有 /api/v1/fs/dirs（目录懒加载）；/fs/tree（含文件）就绪后接文件行。
// 交互：目录展开/折叠（▶/▼）、文件占位（📄）、hover 操作（复制路径——先落地；
// 新建/重命名/删除等后端 API 就绪后接入）。

import { useEffect, useRef, useState } from "react";
import { fetchDirs } from "../../core/api";
import { zh } from "../../i18n/zh";

interface TreeNode {
  path: string;
  name: string;
  kind: "dir" | "file";
  children?: TreeNode[];
}

interface DirData {
  path: string;
  parent: string | null;
  dirs: string[];
}

export function FileTree({ root }: { root?: string }) {
  // expanded: 展开的目录路径集合；cache: 目录 → 子项（懒加载）
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [children, setChildren] = useState<Map<string, TreeNode[]>>(new Map());
  const [rootDirs, setRootDirs] = useState<TreeNode[]>([]);
  const [loadingRoot, setLoadingRoot] = useState(false);
  const [error, setError] = useState("");
  const [copied, setCopied] = useState<string | null>(null);
  const loadingRef = useRef<Set<string>>(new Set());

  // 加载目录子项（懒加载——目录/文件列表）
  const loadDir = async (path: string): Promise<TreeNode[]> => {
    if (loadingRef.current.has(path)) return [];
    loadingRef.current.add(path);
    try {
      const data: DirData | null = await fetchDirs(path);
      if (!data) return [];
      // 骨架阶段：仅目录（dirs API）；/fs/tree 就绪后含 files
      const items: TreeNode[] = (data.dirs ?? []).map((name) => ({
        path: `${path}/${name}`,
        name,
        kind: "dir",
      }));
      return items;
    } catch {
      return [];
    } finally {
      loadingRef.current.delete(path);
    }
  };

  // 根目录加载
  useEffect(() => {
    let alive = true;
    setLoadingRoot(true);
    setError("");
    void loadDir(root ?? "").then((items) => {
      if (!alive) return;
      setRootDirs(items);
      setLoadingRoot(false);
    });
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [root]);

  // 展开/折叠目录
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

  // 渲染一行（缩进 = depth）
  const renderRow = (node: TreeNode, depth: number) => {
    const isOpen = expanded.has(node.path);
    const hasChildren = children.get(node.path)?.length;
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
          role="button"
          tabIndex={0}
          onClick={() => showArrow && void toggle(node)}
          onKeyDown={(e) => {
            if (showArrow && (e.key === "Enter" || e.key === " ")) {
              e.preventDefault();
              void toggle(node);
            }
          }}
          title={node.path}
        >
          {node.kind === "dir" ? "📂" : "📄"}
        </span>
        <span
          className="v2-tree-name"
          title={node.path}
          onClick={() => showArrow && void toggle(node)}
        >
          {node.name}
          {showArrow && isOpen && hasChildren === 0 && (
            <span className="v2-tree-empty-hint">（空）</span>
          )}
        </span>
        <span className="v2-tree-actions">
          <button
            type="button"
            className="v2-icon-btn"
            title={zh.copyPath}
            onClick={() => copyPath(node.path)}
          >
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
        <span className="v2-tree-root" title={root || "~（家目录）"}>
          {root ? root.split("/").filter(Boolean).pop() : "~"}
        </span>
      </div>
      <div className="v2-tree-body">
        {loadingRoot ? (
          <div className="v2-tree-loading">加载中…</div>
        ) : error ? (
          <div className="v2-tree-loading err">{error}</div>
        ) : rootDirs.length === 0 ? (
          <div className="v2-tree-loading">（无子目录）</div>
        ) : (
          rootDirs.map((n) => renderNode(n, 0))
        )}
      </div>
      <div className="v2-tree-hint">{zh.treeHint}</div>
    </div>
  );
}
