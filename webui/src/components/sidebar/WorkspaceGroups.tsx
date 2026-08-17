// Web V2：工作区分组侧栏（对齐 DSH：工作区列表不折叠、常驻分组显示）
// 每个工作区 = 分组头（📁 名称 + 会话数）+ 会话列表；当前工作区分组显示完整
// 会话（含操作，由调用方渲染），其他工作区分组显示只读会话（点击 = 切换并打开）。

import { useEffect, useState, type ReactNode } from "react";
import {
  fetchWorkspaceSessions,
  fetchWorkspaces,
  switchWorkspace,
  type SessionMeta,
  type WorkspaceInfo,
} from "../../core/api";
import { DirBrowser } from "./DirBrowser";

function basename(path: string): string {
  const parts = path.replace(/\\/g, "/").split("/").filter(Boolean);
  return parts[parts.length - 1] ?? path;
}

/** 相对时间（对齐 DSH 侧栏：5分钟 / 2小时 / 3天；超 7 天回落月日） */
export function formatRelative(iso: string): string {
  if (!iso) return "";
  const t = new Date(iso).getTime();
  if (Number.isNaN(t)) return "";
  const diff = Date.now() - t;
  if (diff < 60_000) return "刚刚";
  if (diff < 3_600_000) return `${Math.floor(diff / 60_000)}分钟`;
  if (diff < 86_400_000) return `${Math.floor(diff / 3_600_000)}小时`;
  if (diff < 7 * 86_400_000) return `${Math.floor(diff / 86_400_000)}天`;
  const d = new Date(t);
  return `${d.getMonth() + 1}月${d.getDate()}日`;
}

interface Props {
  /** 当前工作区分组体（Sidebar 传入完整会话列表 + 操作） */
  children?: ReactNode;
  /** 激活会话 id（当前工作区高亮） */
  activeSessionId?: string;
  /** 其他工作区会话打开回调（已切好工作区；调用方打开会话并刷新） */
  onOpenOtherSession?: (workspaceId: string, sessionId: string) => void;
  /** 工作区变更（注册/切换）后调用方刷新 */
  onWorkspaceChanged?: () => void;
}

export function WorkspaceGroups({ children, activeSessionId, onOpenOtherSession, onWorkspaceChanged }: Props) {
  const [workspaces, setWorkspaces] = useState<WorkspaceInfo[]>([]);
  // 当前工作区分组折叠态（点击分组头折叠/展开会话列表——对齐树状分组）
  const [collapsedCurrent, setCollapsedCurrent] = useState(false);
  const [currentWsId, setCurrentWsId] = useState("");
  // 其他工作区会话缓存：{ wsId: SessionMeta[] }
  const [otherSessions, setOtherSessions] = useState<Record<string, SessionMeta[]>>({});
  const [browsing, setBrowsing] = useState(false);

  const reload = (preferredCurrent: string) => {
    void fetchWorkspaces().then((data) => {
      if (!data) return;
      const list = Array.isArray(data.workspaces) ? data.workspaces : [];
      setWorkspaces(list);
      const current = typeof data.current === "string" && data.current ? data.current : preferredCurrent;
      setCurrentWsId(current);
      // 并行拉取非当前工作区会话
      const others = list.filter((w) => w.id !== current);
      void Promise.all(
        others.map((w) =>
          fetchWorkspaceSessions(w.id).then((ss) => ({ id: w.id, sessions: ss }))
        )
      ).then((all) => {
        const map: Record<string, SessionMeta[]> = {};
        for (const item of all) map[item.id] = item.sessions;
        setOtherSessions(map);
      });
    });
  };

  useEffect(() => {
    reload("");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const openOtherSession = async (wsId: string, sid: string) => {
    const ok = await switchWorkspace(wsId);
    if (!ok) return;
    setCurrentWsId(wsId);
    reload(wsId);
    onOpenOtherSession?.(wsId, sid);
  };

  /** 点击其他工作区分组头 = 切换工作区（无会话的工作区也可切换） */
  const switchWs = async (wsId: string) => {
    if (wsId === currentWsId) return;
    const ok = await switchWorkspace(wsId);
    if (!ok) return;
    setCurrentWsId(wsId);
    reload(wsId);
    onWorkspaceChanged?.();
  };

  const onDirOpened = (ws: WorkspaceInfo) => {
    setBrowsing(false);
    // 立即切换分组（不等 reload 异步返回，避免仍显示旧工作区）
    setCurrentWsId(ws.id);
    // 新工作区插入开头（当前工作区置顶，不被堆叠挤到最下面）
    setWorkspaces((prev) =>
      prev.some((w) => w.id === ws.id) ? prev : [ws, ...prev]
    );
    onWorkspaceChanged?.();
    // 重拉工作区列表（补全会话与其他工作区数据）
    reload(ws.id);
  };

  return (
    <div className="v2-ws-tree" data-testid="ws-groups">
      {workspaces.length === 0 ? (
        // 工作区加载中/失败 → 默认组兜底渲染 children（会话列表不空白）
        <div className="v2-ws-tree-node current" data-testid="ws-group">
          <div className="v2-ws-tree-head">
            <span className="v2-ws-tree-icon">📁</span>
            <span className="v2-ws-tree-name">工作区</span>
          </div>
          <div className="v2-ws-tree-children">{children}</div>
        </div>
      ) : (
        // 当前工作区置顶（打开新工作区后不被堆叠挤到最下面），其余保持注册序
        [...workspaces]
          .sort((a, b) => {
            if (a.id === currentWsId) return -1;
            if (b.id === currentWsId) return 1;
            return 0;
          })
          .map((ws) => {
            const isCurrent = ws.id === currentWsId;
            const others = otherSessions[ws.id] ?? [];
            return (
              <div
                key={ws.id}
                className={`v2-ws-tree-node ${isCurrent ? "current" : ""}`}
                data-testid="ws-group"
              >
                <div
                  className="v2-ws-tree-head"
                  title={ws.path}
                  role="button"
                  tabIndex={0}
                  onClick={() => {
                    if (isCurrent) {
                      setCollapsedCurrent((v) => !v);
                    } else {
                      void switchWs(ws.id);
                    }
                  }}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" || e.key === " ") {
                      if (isCurrent) setCollapsedCurrent((v) => !v);
                      else void switchWs(ws.id);
                    }
                  }}
                  data-testid="ws-tree-head"
                >
                  <span className="v2-ws-tree-arrow">{isCurrent ? (collapsedCurrent ? "▶" : "▼") : ""}</span>
                  <span className="v2-ws-tree-icon">{isCurrent ? "📁" : "📂"}</span>
                  <span className="v2-ws-tree-name">{basename(ws.path)}</span>
                  {!isCurrent ? <span className="v2-ws-tree-count">{others.length}</span> : null}
                </div>
                <div className="v2-ws-tree-children">
                  {isCurrent ? (
                    collapsedCurrent ? null : children
                  ) : (
                    <div className="v2-ws-other-sessions" data-testid="ws-other-sessions">
                      {others.map((s) => (
                        <button
                          key={s.session_id}
                          type="button"
                          className={`v2-session-item compact ${s.session_id === activeSessionId ? "active" : ""}`}
                          title={s.title || "未命名"}
                          onClick={() => void openOtherSession(ws.id, s.session_id)}
                          data-testid="other-session-item"
                        >
                          <span className="v2-session-title">{s.title || "未命名"}</span>
                          <span className="v2-session-rel">{formatRelative(s.updated_at)}</span>
                        </button>
                      ))}
                      {others.length === 0 ? <div className="v2-ws-empty">暂无会话</div> : null}
                    </div>
                  )}
                </div>
              </div>
            );
          })
      )}
      {browsing ? (
        <DirBrowser onOpened={onDirOpened} onClose={() => setBrowsing(false)} />
      ) : (
        <button
          type="button"
          className="v2-ws-add-btn"
          onClick={() => setBrowsing(true)}
          data-testid="ws-add-btn"
        >
          ＋ 打开新工作区
        </button>
      )}
    </div>
  );
}
