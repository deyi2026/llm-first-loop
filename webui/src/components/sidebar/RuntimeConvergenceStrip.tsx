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

/** The long-session lane owns the shared poller. Never create another timer. */
export function RuntimeConvergenceSubscriber() {
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
  return <RuntimeConvergenceStrip snapshot={snapshot} stale={stale} />;
}
