import { useEffect, useState } from "react";
import { archiveSession, deleteSession, setSessionPin } from "../../core/api";
import { useCapabilities } from "../../core/capabilities";
import { conversationStore } from "../../core/conversation";
import { refreshSessionsAndCurrent } from "../../core/events";
import { sessionStore, useCurrentSessionId, useSessions } from "../../core/stores";
import { buildSessionShareUrl, syncSessionIdInLocation } from "../../core/sessionUrl";

async function writeClipboard(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    return false;
  }
}

async function clearCurrentAndRefresh(targetId: string): Promise<void> {
  if (sessionStore.getState().currentSessionId === targetId) {
    syncSessionIdInLocation(null);
    sessionStore.setCurrentSession("");
    sessionStore.setNewSessionPending(false);
    conversationStore.setState({
      messages: [],
      hasMoreHistory: false,
      loadedHistoryCount: 0,
      streamStartedAt: null,
    });
  }
  await refreshSessionsAndCurrent();
}

function useTransientNotice(): [string, (text: string) => void] {
  const [notice, setNotice] = useState("");
  const flash = (text: string) => {
    setNotice(text);
    window.setTimeout(() => setNotice((value) => (value === text ? "" : value)), 1800);
  };
  return [notice, flash];
}

function SessionMoreMenu({
  busy,
  pinned,
  confirmDelete,
  onShowFiles,
  onPin,
  onArchive,
  onDelete,
}: {
  busy: boolean;
  pinned: boolean;
  confirmDelete: boolean;
  onShowFiles: () => void;
  onPin: () => void;
  onArchive: () => void;
  onDelete: () => void;
}) {
  const caps = useCapabilities();
  return (
    <div className="v2-header-menu" role="menu" data-testid="session-more-menu">
      {caps.fsTree ? (
        <button type="button" role="menuitem" disabled={busy} onClick={onShowFiles}>
          ▤ 查看聊天中的文件
        </button>
      ) : null}
      {caps.pin ? (
        <button type="button" role="menuitem" disabled={busy} onClick={onPin}>
          ⌖ {pinned ? "取消置顶" : "置顶聊天"}
        </button>
      ) : null}
      {caps.archive ? (
        <button type="button" role="menuitem" disabled={busy} onClick={onArchive}>
          ▣ 归档
        </button>
      ) : null}
      {caps.delete ? (
        <button type="button" role="menuitem" className="danger" disabled={busy} onClick={onDelete}>
          🗑 {confirmDelete ? "再次点击确认删除" : "删除"}
        </button>
      ) : null}
    </div>
  );
}

function SessionShareButton({
  enabled,
  onShare,
}: {
  enabled: boolean;
  onShare: () => void;
}) {
  return (
    <button
      type="button"
      className="v2-btn ghost"
      disabled={!enabled}
      onClick={onShare}
      aria-label="复制会话链接"
      title="复制此 LFL 部署的会话链接（受部署自身鉴权保护，非公开分享）"
    >
      ⇧ 复制链接
    </button>
  );
}

export function SessionHeaderActions({ onShowFiles }: { onShowFiles?: () => void }) {
  const currentId = useCurrentSessionId();
  const sessions = useSessions();
  const current = sessions.find((item) => item.session_id === currentId);
  const [menuOpen, setMenuOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [notice, flash] = useTransientNotice();

  useEffect(() => {
    setMenuOpen(false);
    setConfirmDelete(false);
  }, [currentId]);

  const share = async () => {
    if (!currentId) return;
    const ok = await writeClipboard(buildSessionShareUrl(currentId));
    flash(ok ? "会话链接已复制" : "复制失败");
  };

  const pin = async () => {
    if (!currentId || busy) return;
    setBusy(true);
    const ok = await setSessionPin(currentId, !current?.pinned);
    if (ok) {
      await refreshSessionsAndCurrent();
      setMenuOpen(false);
    } else {
      flash("置顶状态更新失败");
    }
    setBusy(false);
  };

  const archive = async () => {
    if (!currentId || busy) return;
    setBusy(true);
    const ok = await archiveSession(currentId, true);
    if (ok) {
      setMenuOpen(false);
      await clearCurrentAndRefresh(currentId);
    } else {
      flash("归档失败");
    }
    setBusy(false);
  };

  const remove = async () => {
    if (!currentId || busy) return;
    if (!confirmDelete) {
      setConfirmDelete(true);
      window.setTimeout(() => setConfirmDelete(false), 3000);
      return;
    }
    setBusy(true);
    const ok = await deleteSession(currentId);
    if (ok) {
      setMenuOpen(false);
      setConfirmDelete(false);
      await clearCurrentAndRefresh(currentId);
    } else {
      flash("删除失败");
    }
    setBusy(false);
  };

  return (
    <div className="v2-header-actions" data-testid="session-header-actions">
      {notice ? <span className="v2-header-notice" role="status">{notice}</span> : null}
      <SessionShareButton enabled={Boolean(currentId)} onShare={() => void share()} />
      <div className="v2-header-more-wrap">
        <button
          type="button"
          className="v2-icon-btn"
          disabled={!currentId}
          onClick={() => {
            setMenuOpen((value) => !value);
            setConfirmDelete(false);
          }}
          aria-label="更多"
          aria-expanded={menuOpen}
        >
          ⋯
        </button>
        {menuOpen ? (
          <SessionMoreMenu
            busy={busy}
            pinned={Boolean(current?.pinned)}
            confirmDelete={confirmDelete}
            onShowFiles={() => { onShowFiles?.(); setMenuOpen(false); }}
            onPin={() => void pin()}
            onArchive={() => void archive()}
            onDelete={() => void remove()}
          />
        ) : null}
      </div>
    </div>
  );
}
