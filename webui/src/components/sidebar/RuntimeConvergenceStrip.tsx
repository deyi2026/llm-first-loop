import { useEffect, useState } from "react";
import * as boardApi from "../../core/coordinationBoard";
import { isAuthRequired, subscribeAuthRequired } from "../../core/authSession";

/** Pure display: consumes the existing shared coordination-board snapshot. */
export interface RuntimeConvergenceSnapshot {
  desired_generation: number | null;
  desired_git_head: string | null;
  desired_version: string | null;
  services: Record<string, { state: string; pid?: number | null; git_head?: string | null;
    version?: string | null; wheel_sha256?: string | null; inferred: boolean }>;
  cli: { state: string; processes: Array<{ pid: number; generation: number | null; git_head: string; state: string }>;
    uncertain: number; coverage?: string };
}

const labels: Record<string, string> = {
  artifact_matches: "工件匹配", identity_matches_target: "代次匹配",
  update_required: "待切换", not_running: "未运行", unverified: "待核验",
};

export function RuntimeConvergenceStrip({ snapshot, stale = false }: {
  snapshot: RuntimeConvergenceSnapshot | null | undefined; stale?: boolean;
}) {
  if (!snapshot) return null;
  return (
    <div data-testid="runtime-convergence-strip" style={{ fontSize: 11, lineHeight: 1.6, padding: "4px 8px", overflowWrap: "anywhere" }}>
      <div>运行版本 · gen {snapshot.desired_generation ?? "—"} · {snapshot.desired_version || snapshot.desired_git_head?.slice(0, 9) || "—"}{stale ? " · 数据待刷新" : ""}</div>
      <div>{Object.entries(snapshot.services).map(([name, svc]) => (
        <span key={name} title={`${name}: ${svc.git_head || svc.version || "身份未知"}`} style={{ display: "inline-block", marginRight: 8 }}>
          {name} {labels[svc.state] ?? "待核验"}
        </span>
      ))}</div>
      <div title="仅统计新版持锁登记 CLI，不能证明遗留进程已退出。">
        CLI {snapshot.cli.state === "not_running" ? "无已登记进程" : labels[snapshot.cli.state] ?? "待核验"} · {snapshot.cli.processes.length} 个登记进程
        {snapshot.cli.processes.map(proc => <span key={proc.pid} style={{ display: "inline-block", marginLeft: 6 }}>gen {proc.generation ?? "—"} {proc.git_head?.slice(0, 9)}</span>)}
      </div>
    </div>
  );
}


type BoardSnapshot = { runtime_convergence?: RuntimeConvergenceSnapshot | null };
type Subscribe = (listener: (body: BoardSnapshot | null) => void) => () => void;

/** Shared coordination-board snapshot subscription (the shared poller; never another timer). */
function useRuntimeConvergenceSnapshot(): { snapshot: RuntimeConvergenceSnapshot | null; stale: boolean } {
  const [snapshot, setSnapshot] = useState<RuntimeConvergenceSnapshot | null>(null);
  const [stale, setStale] = useState(true);
  useEffect(() => {
    // Compatibility while the independently reviewed shared-poll lane is in flight.
    // After it merges this subscribes to its single poller; older code gets only
    // one explicitly stale snapshot, not an additional polling loop.
    const subscribe = Reflect.get(boardApi, "subscribeCoordinationBoard") as Subscribe | undefined;
    if (typeof subscribe === "function") {
      return subscribe(body => {
        if (isAuthRequired()) setSnapshot(null);
        else if (body) setSnapshot(body.runtime_convergence ?? null);
        setStale(!body);
      });
    }
    let cancelled = false;
    let authChanged = false;
    const clear = subscribeAuthRequired(() => { authChanged = true; setSnapshot(null); });
    if (!isAuthRequired() && !document.hidden) {
      void boardApi.fetchCoordinationBoard<BoardSnapshot>().then(body => {
        if (!cancelled && !authChanged && !isAuthRequired()) setSnapshot(body?.runtime_convergence ?? null);
      }).catch(() => {});
    }
    return () => { cancelled = true; clear(); };
  }, []);
  return { snapshot, stale };
}

/** The long-session lane owns the shared poller. Never create another timer. */
export function RuntimeConvergenceSubscriber() {
  const { snapshot, stale } = useRuntimeConvergenceSnapshot();
  return <RuntimeConvergenceStrip snapshot={snapshot} stale={stale} />;
}

// ── 侧栏轻量化（2026-11-25 专项）：左栏不再常驻显示运行版本 gen/SHA/CLI 详情。
// 仅当运行信息未知、陈旧或存在非正常状态时渲染一条紧凑可点击提示；
// 完整信息（desired/live/stable、四服务工件匹配、CLI 登记进程）仍由服务身份页展示。

const RUNTIME_OK_STATES = new Set(["artifact_matches", "identity_matches_target"]);
const RUNTIME_CLI_OK_STATES = new Set(["artifact_matches", "identity_matches_target", "not_running"]);

/**
 * 紧凑侧栏提示的判定：返回需关注原因，全部正常返回 null。
 * 未知/陈旧不冒充正常：缺快照、标记 stale 或任何服务/CLI 状态未确认都视为需关注。
 */
export function computeRuntimeAlert(
  snapshot: RuntimeConvergenceSnapshot | null | undefined, stale: boolean,
): string | null {
  if (stale) return "运行状态待刷新";
  if (!snapshot) return "运行状态未知";
  if (snapshot.desired_generation == null) return "运行代次未知";
  const concerns: string[] = [];
  for (const [name, svc] of Object.entries(snapshot.services)) {
    if (!RUNTIME_OK_STATES.has(svc.state)) concerns.push(`${name} ${labels[svc.state] ?? "待核验"}`);
  }
  if (!RUNTIME_CLI_OK_STATES.has(snapshot.cli.state)) {
    concerns.push(`CLI ${labels[snapshot.cli.state] ?? "待核验"}`);
  }
  if (concerns.length === 0) return null;
  return `${concerns.length} 项需关注：${concerns.slice(0, 3).join(" · ")}`;
}

/** 紧凑可点击提示；全部正常时不渲染任何运行信息。 */
export function RuntimeAlertStrip({ snapshot, stale = false, onOpenServices }: {
  snapshot: RuntimeConvergenceSnapshot | null | undefined; stale?: boolean;
  onOpenServices?: () => void;
}) {
  const alert = computeRuntimeAlert(snapshot, stale);
  if (!alert) return null;
  return (
    <button
      type="button"
      className="v2-runtime-alert"
      data-testid="runtime-alert-strip"
      title={`完整运行信息见「服务身份」页（desired · live · stable · CLI 登记进程）。当前：${alert}`}
      onClick={onOpenServices}
    >
      <span aria-hidden="true">⚠</span>
      <span className="v2-runtime-alert-text">{alert}</span>
      <span className="v2-runtime-alert-more" aria-hidden="true">详情 ›</span>
    </button>
  );
}

/** 侧栏变体：订阅共享协调快照（不新增轮询）。 */
export function RuntimeConvergenceAlertSubscriber({ onOpenServices }: { onOpenServices?: () => void }) {
  const { snapshot, stale } = useRuntimeConvergenceSnapshot();
  return <RuntimeAlertStrip snapshot={snapshot} stale={stale} onOpenServices={onOpenServices} />;
}
