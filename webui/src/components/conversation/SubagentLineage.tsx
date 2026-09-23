// 子代理谱系（feature/webui-subagent-lineage-20260922，对齐 DSH SubagentHeaderLineage）：
// 会话头部计数触发器（有运行中后代时带 active 点）+ 下拉行列表。
// 行 = 状态点 · 会话标题 · 活动/结果/回收徽标；点击即切换到该子会话（导航，
// 非 steer）。活动事实来自 /api/v1/agents/tree 的 topology 投影（running/inactive，
// 未知时不伪造）；端点缺失（精简后端）时整个入口隐藏且不再轮询。

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { fetchAgentsTreeNodes, type AgentTreeNode } from "../../core/api";
import { useConversation } from "../../core/conversation";
import { runAwareIntervalMs } from "../../core/runAwarePoll";
import { sessionStore, useCurrentSessionId, useSessions } from "../../core/stores";
import { subagentZh as zh } from "../../i18n/zh";

export function subagentOutcomeLabel(outcome: string | undefined): string {
  switch (outcome) {
    case "completed":
      return zh.outcomeCompleted;
    case "failed":
      return zh.outcomeFailed;
    case "cancelled":
      return zh.outcomeCancelled;
    case "truncated":
      return zh.outcomeTruncated;
    case "refused":
      return zh.outcomeRefused;
    default:
      return "";
  }
}

export function SubagentLineage() {
  const _conv = useConversation();
  const runBusy = Boolean(_conv.streaming || _conv.backgroundRunning);
  const currentId = useCurrentSessionId();
  const sessions = useSessions();
  const [nodes, setNodes] = useState<AgentTreeNode[] | null>(null);
  const [unavailable, setUnavailable] = useState(false);
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement | null>(null);
  const activeSession = useRef(currentId);
  activeSession.current = currentId;

  const load = useCallback(async () => {
    const next = await fetchAgentsTreeNodes();
    if (next === null) {
      setUnavailable(true);
      return;
    }
    setNodes(next);
  }, []);

  // 发现轮询：5s；端点缺失后停止（精简后端）
  useEffect(() => {
    if (unavailable) return;
    void load();
    const timer = window.setInterval(() => {
      if (!document.hidden) void load();
    }, runAwareIntervalMs(5000, runBusy));
    const onVisible = () => {
      if (!document.hidden) void load();
    };
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      window.clearInterval(timer);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [unavailable, load]);

  // 切换会话时收起
  useEffect(() => {
    setOpen(false);
  }, [currentId]);

  useEffect(() => {
    if (!open) return;
    const onPointerDown = (event: PointerEvent) => {
      if (rootRef.current && !rootRef.current.contains(event.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener("pointerdown", onPointerDown);
    return () => document.removeEventListener("pointerdown", onPointerDown);
  }, [open]);

  const children = useMemo(
    () => (nodes ?? []).filter((n) => n.parent_id === currentId),
    [nodes, currentId]
  );
  const runningCount = useMemo(
    () => children.filter((c) => c.activity === "running").length,
    [children]
  );

  if (unavailable || children.length === 0) return null;

  const titleFor = (id: string): string => {
    const meta = sessions.find((s) => s.session_id === id);
    return meta?.title || zh.unnamedSession;
  };

  const countLabel =
    runningCount > 0 ? zh.countRunning(runningCount) : zh.countTotal(children.length);

  const onKeyDown = (event: React.KeyboardEvent) => {
    if (event.key !== "Escape" || !open) return;
    event.preventDefault();
    setOpen(false);
  };

  const openChild = (id: string, title: string) => {
    sessionStore.setCurrentSession(id);
    setOpen(false);
    void title; // title 仅用于 aria
  };

  return (
    <div className="v2-catalog" ref={rootRef} onKeyDown={onKeyDown} data-testid="subagent-lineage">
      <button
        type="button"
        className="v2-catalog-trigger"
        aria-expanded={open}
        aria-label={countLabel}
        onClick={() => setOpen((v) => !v)}
        data-testid="subagent-lineage-trigger"
      >
        {runningCount > 0 ? (
          <span className="v2-catalog-livedot ongoing" aria-hidden="true" />
        ) : (
          <span className="v2-catalog-icon" aria-hidden="true">⑃</span>
        )}
        <span>{countLabel}</span>
        <span className={`v2-catalog-caret ${open ? "open" : ""}`} aria-hidden="true">▾</span>
      </button>
      {open && (
        <ul className="v2-catalog-menu agents" aria-label={zh.listAria} data-testid="subagent-lineage-menu">
          {children.map((child) => {
            const running = child.activity === "running";
            const unknown = child.activity === undefined;
            const outcome = subagentOutcomeLabel(child.outcome);
            return (
              <li key={child.id}>
                <button
                  type="button"
                  className="v2-agents-row"
                  aria-label={zh.openChild(titleFor(child.id))}
                  onClick={() => openChild(child.id, titleFor(child.id))}
                  data-testid="subagent-lineage-row"
                >
                  <span
                    className={`v2-catalog-livedot ${running ? "ongoing" : unknown ? "idle" : "done"}`}
                    aria-hidden="true"
                  />
                  <span className="v2-agents-label" title={child.id}>
                    {titleFor(child.id)}
                  </span>
                  <span className="v2-agents-meta">
                    <span className={running ? "v2-agents-running" : ""}>
                      {unknown ? zh.activityUnknown : running ? zh.activityRunning : zh.activityInactive}
                    </span>
                    {outcome ? <span className="v2-agents-badge">{outcome}</span> : null}
                    {child.settlement === "uncollected" ? (
                      <span className="v2-agents-badge warn">{zh.settlementUncollected}</span>
                    ) : null}
                  </span>
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
