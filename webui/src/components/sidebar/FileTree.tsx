// Web V2（对齐 DSH 左侧栏树）：文件/目录树
// 数据源：/api/v1/fs/tree（目录+文件，单层可展；工作区根内安全边界后端把关）
// 交互：目录展开/折叠（▶▼）、文件行（📄+大小）；点击文件=预览（对齐 DSH
// Files tab 点击打开预览），✍ 进入带版本保护的协作编辑；hover 操作
// （复制路径/新建目录/重命名/删除两步确认——DELETE confirm=true）

import { useEffect, useRef, useState } from "react";
import {
  fetchFsTree,
  fsDelete,
  fsMkdir,
  fsRename,
  fsRestore,
  observeHumanFile,
  saveHumanFile,
  type FsTree,
  type HumanFileObservation,
} from "../../core/api";
import { writeClipboardText } from "../../core/clipboard";
import { previewTabsStore } from "../../core/stores";
import { zh } from "../../i18n/zh";
import { UndoDeleteToast } from "./UndoDeleteToast";

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

export function FileTree({ sessionId = "" }: { sessionId?: string }) {
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [children, setChildren] = useState<Map<string, TreeNode[]>>(new Map());
  const [rootItems, setRootItems] = useState<TreeNode[]>([]);
  const [loadingRoot, setLoadingRoot] = useState(false);
  const [error, setError] = useState("");
  const [actionError, setActionError] = useState("");
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
  const [editor, setEditor] = useState<HumanFileObservation | null>(null);
  const [draft, setDraft] = useState("");
  const [editorBusy, setEditorBusy] = useState(false);
  const [editorStatus, setEditorStatus] = useState("");
  const [pendingSave, setPendingSave] = useState<{ key: string; requestId: string } | null>(null);
  // P2-4：删除进回收站后的撤销态（token 只存内存，不落盘不外显）
  const [undo, setUndo] = useState<{ name: string; parent: string; token: string; expiresAt: number } | null>(null);
  const [undoBusy, setUndoBusy] = useState(false);
  const [undoError, setUndoError] = useState("");
  const [undoDone, setUndoDone] = useState("");

  useEffect(() => {
    setEditor(null);
    setDraft("");
    setEditorStatus("");
    setPendingSave(null);
  }, [sessionId]);

  const toNodes = (t: FsTree): TreeNode[] => [
    ...(t.dirs ?? []).map((name) => ({ path: `${t.path}/${name}`, name, kind: "dir" as const })),
    ...(t.files ?? []).map((f) => ({
      path: `${t.path}/${f.name}`,
      name: f.name,
      kind: "file" as const,
      size: f.size,
    })),
  ];

  const loadDir = async (path: string): Promise<TreeNode[] | null> => {
    if (loadingRef.current.has(path)) return null;
    loadingRef.current.add(path);
    try {
      const data = await fetchFsTree(path);
      return data ? toNodes(data) : null;
    } catch {
      return null;
    } finally {
      loadingRef.current.delete(path);
    }
  };

  const storeListing = (path: string, items: TreeNode[]): void => {
    if (path === root) {
      setRootItems(items);
      return;
    }
    setChildren((prev) => {
      const m = new Map(prev);
      m.set(path, items);
      return m;
    });
  };

  const refreshAfterMutation = async (path: string): Promise<boolean> => {
    const items = await loadDir(path);
    if (items === null) {
      setActionError("操作已完成，但目录刷新失败；已保留当前列表，请重试。");
      return false;
    }
    storeListing(path, items);
    return true;
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
    if (expanded.has(node.path)) {
      setExpanded((prev) => {
        const next = new Set(prev);
        next.delete(node.path);
        return next;
      });
      return;
    }
    if (!children.has(node.path)) {
      const items = await loadDir(node.path);
      if (items === null) {
        setActionError("目录读取失败；未把未知状态当成空目录，请重试。");
        return;
      }
      setActionError("");
      storeListing(node.path, items);
    }
    setExpanded((prev) => new Set(prev).add(node.path));
  };

  const copyPath = async (path: string) => {
    const { ok } = await writeClipboardText(path);
    if (!ok) {
      setActionError("复制失败；请长按/选中路径后手动复制。");
      return;
    }
    setActionError("");
    setCopied(path);
    window.setTimeout(() => setCopied((v) => (v === path ? null : v)), 1200);
  };

  const doMkdir = async () => {
    if (!newDirParent || !newDirValue.trim() || busy) return;
    setBusy(true);
    setActionError("");
    const ok = await fsMkdir(`${newDirParent}/${newDirValue.trim()}`);
    setBusy(false);
    if (!ok) {
      setActionError("新建目录失败；文件树未修改，请重试。");
      return;
    }
    if (ok) {
      setActionError("");
      setNewDirParent(null);
      setNewDirValue("");
      // 刷新父目录
      await refreshAfterMutation(newDirParent);
      setExpanded((prev) => new Set(prev).add(newDirParent));
    }
  };

  const doRename = async () => {
    if (!renameTarget || !renameValue.trim() || busy) return;
    setBusy(true);
    setActionError("");
    const ok = await fsRename(renameTarget.path, renameValue.trim());
    setBusy(false);
    if (!ok) {
      setActionError("重命名失败；原文件/目录保持不变，请重试。");
      return;
    }
    if (ok) {
      setActionError("");
      const parent = renameTarget.path.split("/").slice(0, -1).join("/");
      setRenameTarget(null);
      await refreshAfterMutation(parent || root);
    }
  };

  const doDelete = async () => {
    if (!confirmDelete || busy) return;
    setBusy(true);
    setActionError("");
    const target = confirmDelete;
    const res = await fsDelete(target.path);
    setBusy(false);
    if (!res.ok) {
      setActionError("删除失败；原文件/目录仍保留，请重试。");
      return;
    }
    setActionError("");
    const parent = target.path.split("/").slice(0, -1).join("/");
    setConfirmDelete(null);
    await refreshAfterMutation(parent || root);
    // P2-4：默认删除进回收站——展示撤销入口（10 分钟窗口，倒计时在 Toast 内）。
    if (res.status === "trashed" && res.undoToken) {
      setUndoError("");
      setUndoDone("");
      setUndo({
        name: target.name,
        parent: parent || root,
        token: res.undoToken,
        expiresAt: Date.now() + (res.expiresIn ?? 600) * 1000,
      });
    }
  };

  // P2-4：撤销删除——POST /fs/restore?token=undo_token；成功刷新父目录并提示"已恢复"，
  // 失败按错误码提示（过期/冲突/丢失），不刷新目录（文件仍在回收站，入口保留可重试/关闭）。
  const doUndo = async () => {
    if (!undo || undoBusy) return;
    setUndoBusy(true);
    setUndoError("");
    const res = await fsRestore(undo.token);
    setUndoBusy(false);
    if (!res.ok) {
      setUndoError(res.error ?? "恢复失败；文件仍保留在回收站。");
      return;
    }
    const name = undo.name;
    const parent = undo.parent;
    setUndo(null);
    setUndoError("");
    setUndoDone(`已恢复：${name}`);
    window.setTimeout(
      () => setUndoDone((v) => (v === `已恢复：${name}` ? "" : v)),
      6000
    );
    await refreshAfterMutation(parent);
  };

  const relativePath = (path: string): string => {
    const prefix = root.endsWith("/") ? root : `${root}/`;
    return path.startsWith(prefix) ? path.slice(prefix.length) : path;
  };

  const openEditor = async (node: TreeNode) => {
    if (!sessionId) {
      setEditorStatus("请先选择一个会话，再进行协作编辑。");
      return;
    }
    setEditorBusy(true);
    setEditorStatus("正在观察当前文件…");
    const result = await observeHumanFile(sessionId, relativePath(node.path));
    setEditorBusy(false);
    if (result.status !== 200 || !("snapshot_ref" in result.data)) {
      const err = result.data as { error?: string; detail?: string };
      setEditorStatus(`无法打开：${err.error ?? err.detail ?? "请求失败"}`);
      return;
    }
    setEditor(result.data);
    setDraft(result.data.content);
    setPendingSave(null);
    setEditorStatus("已取得当前物理版本；保存时会再次核对该版本。");
  };

  const saveEditor = async () => {
    if (!sessionId || !editor) return;
    setEditorBusy(true);
    setEditorStatus("正在核对版本并保存…");
    const requestKey = `${editor.snapshot_ref}\0${draft}`;
    const requestId =
      pendingSave?.key === requestKey
        ? pendingSave.requestId
        : globalThis.crypto?.randomUUID?.() ?? `human-${Date.now()}-${Math.random().toString(16).slice(2)}`;
    setPendingSave({ key: requestKey, requestId });
    const result = await saveHumanFile(sessionId, requestId, editor.path, editor.snapshot_ref, draft);
    setEditorBusy(false);
    if (result.status === 0) {
      setEditorStatus("保存结果暂时未知：草稿与 request_id 均已保留；再次保存会查询/复用同一操作，不会自动重放。");
      return;
    }
    if (result.status === 409) {
      setPendingSave(null);
      const err = result.data as { error?: string };
      setEditorStatus(
        err.error === "version_conflict"
          ? "版本已变化：未覆盖文件，当前草稿已保留。请显式重新载入后再决定如何处理。"
          : `保存冲突：${err.error ?? "conflict"}；草稿已保留。`
      );
      return;
    }
    if (result.status !== 200) {
      setPendingSave(null);
      const err = result.data as { error?: string; detail?: string };
      setEditorStatus(`保存失败：${err.error ?? err.detail ?? "请求失败"}；草稿已保留。`);
      return;
    }
    const receipt = result.data as {
      effect_state?: string;
      causation_proven?: boolean;
    };
    if (receipt.effect_state !== "observed_match" || receipt.causation_proven !== true) {
      setEditorStatus(
        receipt.effect_state === "outcome_unknown"
          ? "保存结果仍未证明：草稿与 request_id 已保留；不会自动重放。请显式重新载入核对当前文件。"
          : "保存结果未能证明已按预期落盘：草稿与 request_id 已保留；不会自动重放。"
      );
      return;
    }
    setPendingSave(null);
    const refreshed = await observeHumanFile(sessionId, editor.path);
    if (refreshed.status === 200 && "snapshot_ref" in refreshed.data) {
      setEditor(refreshed.data);
      setDraft(refreshed.data.content);
    }
    setEditorStatus("已保存并验证；未触发模型运行或自动继续。 ");
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
          onClick={() => (showArrow ? void toggle(node) : previewTabsStore.open(node.path))}
          title={node.path}
        >
          {node.kind === "dir" ? "📂" : "📄"}
        </span>
        <span
          className="v2-tree-name"
          title={node.path}
          onClick={() => (showArrow ? void toggle(node) : previewTabsStore.open(node.path))}
        >
          {node.name}
          {node.kind === "file" && node.size !== undefined && (
            <span className="v2-tree-size">{fmtSize(node.size)}</span>
          )}
          {showArrow && isOpen && kids && kids.length === 0 && (
            <span className="v2-tree-empty-hint">（空）</span>
          )}
        </span>
        <span className="v2-tree-actions">
          {node.kind === "file" && (
            <button
              type="button"
              className="v2-icon-btn"
              title={zh.collabEdit}
              disabled={busy}
              onClick={() => void openEditor(node)}
              data-testid="collab-edit-btn"
            >
              ✍
            </button>
          )}
          {node.kind === "dir" && (
            <button
              type="button"
              className="v2-icon-btn"
              title={zh.newFolder}
              disabled={busy}
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
            disabled={busy}
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
            disabled={busy}
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
          <button type="button" className="v2-icon-btn" title={zh.copyPath} onClick={() => void copyPath(node.path)}>
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
      {actionError ? (
        <div className="v2-tree-action-error" role="status">{actionError}</div>
      ) : null}
      {undo ? (
        <UndoDeleteToast
          name={undo.name}
          expiresAt={undo.expiresAt}
          busy={undoBusy}
          error={undoError}
          onUndo={() => void doUndo()}
          onClose={() => {
            setUndo(null);
            setUndoError("");
          }}
        />
      ) : null}
      {!undo && undoDone ? (
        <div className="v2-tree-loading" role="status" data-testid="undo-done">{undoDone}</div>
      ) : null}
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
      {editor && (
        <div className="v2-file-editor" data-testid="human-file-editor">
          <div className="v2-file-editor-head">
            <strong title={editor.path}>{editor.path}</strong>
            <button type="button" className="v2-icon-btn" onClick={() => setEditor(null)} title="关闭">×</button>
          </div>
          <textarea
            className="v2-file-editor-text"
            value={draft}
            disabled={editorBusy}
            spellCheck={false}
            onChange={(e) => setDraft(e.target.value)}
          />
          <div className="v2-file-editor-meta">
            baseline {editor.sha256.slice(0, 12)} · {editor.size_bytes}B · contract v{editor.file_contract_version}
          </div>
          <div className="v2-file-editor-actions">
            <button type="button" className="v2-btn primary" disabled={editorBusy} onClick={() => void saveEditor()}>
              保存当前版本
            </button>
            <button type="button" className="v2-btn" disabled={editorBusy} onClick={() => void openEditor({ path: `${root}/${editor.path}`, name: editor.path, kind: "file" })}>
              重新载入
            </button>
          </div>
          <div className="v2-file-editor-status" aria-live="polite">{editorStatus}</div>
        </div>
      )}
      {!editor && editorStatus && <div className="v2-tree-loading">{editorStatus}</div>}
      <div className="v2-tree-hint">{zh.treeHint}</div>
    </div>
  );
}
