// 协同 Board 面板（DESIGN-20261105 §4.6）：main 主线 + 多 lane 并行统一只读视图。
// 后端契约: GET /api/v1/coordination/board 返回
//   { generated_at, main_head, deployment, lanes, overlaps, degraded }
// 三态纪律: 正常渲染 / degraded 非空（黄色告警条逐条 reason）/ 请求失败（错误态 + 可重试）；
// 无 lane 渲染空态「暂无登记 lane」。lane 记录无 ahead/behind 计数字段，
// 以 head_sha@base_main_sha 短 sha 呈现基线关系，不伪造计数。

import { useCallback, useEffect, useState } from "react";

interface LaneRow {
  lane_id: string;
  branch: string;
  goal_id: string;
  lane_role: string;
  status: string;
  head_sha: string;
  base_main_sha: string;
  verify_ref: string;
  priority: string;
  paths: string[];
  last_activity: string;
  base_is_broken?: boolean;
}

interface OverlapRow {
  a: string;
  b: string;
  branches: string[];
  shared_paths: string[];
}

interface BoardResp {
  generated_at: string;
  main_head: string;
  deployment: {
    deployed_sha: string;
    deployed_at: string;
    deployed_phase: string;
    in_sync: boolean;
    source?: string;
  };
  lanes: LaneRow[];
  overlaps: OverlapRow[];
  degraded: string[];
}

const POLL_MS = 10000;

function shortSha(sha: string | undefined | null): string {
  const s = String(sha || "").trim();
  return s ? s.slice(0, 7) : "—";
}

async function fetchBoard(): Promise<BoardResp | null> {
  try {
    const r = await fetch("/api/v1/coordination/board");
    if (!r.ok) return null;
    return await r.json() as BoardResp;
  } catch {
    return null;
  }
}

function SyncBadge({ deployment }: { deployment: BoardResp["deployment"] }) {
  if (deployment.in_sync) {
    return <span style={{ color: "#38a169", fontSize: 11 }}>✅ 与主线同步</span>;
  }
  if (deployment.deployed_sha) {
    return <span style={{ color: "#d69e2e", fontSize: 11 }}>⚠️ 未同步</span>;
  }
  return <span style={{ opacity: 0.6, fontSize: 11 }}>— 无部署记录</span>;
}

export function LaneBoard() {
  const [data, setData] = useState<BoardResp | null>(null);
  const [loadErr, setLoadErr] = useState(false);
  const load = useCallback(() => {
    void fetchBoard().then((d) => {
      if (d) {
        setData(d);
        setLoadErr(false);
      } else {
        setLoadErr(true);
      }
    });
  }, []);
  useEffect(() => {
    load();
    const t = window.setInterval(load, POLL_MS);
    return () => window.clearInterval(t);
  }, [load]);

  return (
    <div className="v2-evo" data-testid="lane-board">
      <div className="v2-evo-head">
        <span className="v2-evo-title">🛤 协同 Board</span>
        <button type="button" className="v2-icon-btn" title="刷新" onClick={() => load()}>
          ⟳
        </button>
      </div>

      {/* 请求失败：错误态（不静默空白；已有旧数据时保留展示并叠加提示） */}
      {loadErr && (
        <div className="v2-sidebar-error" role="alert" data-testid="lane-board-error">
          Board 加载失败，无法确认 lane 与部署状态。
          <button type="button" className="v2-ws-session-toggle" onClick={() => load()}>
            重试
          </button>
        </div>
      )}

      {!data && !loadErr ? (
        <div className="v2-tree-loading" role="status" data-testid="lane-board-loading">
          正在加载 Board…
        </div>
      ) : null}

      {data ? (
        <>
          {/* 部署条带：主线 HEAD / 已部署 sha / in_sync（裁决 Q5：Board 最该给的比特） */}
          <div className="v2-evo-item" data-testid="lane-deploy-strip" style={{ display: "flex", flexDirection: "column", gap: 4 }}>
            <div className="v2-evo-row">
              <span>主线 HEAD</span>
              <code>{shortSha(data.main_head)}</code>
            </div>
            <div className="v2-evo-row">
              <span>已部署</span>
              <code>{shortSha(data.deployment && data.deployment.deployed_sha)}</code>
              <SyncBadge deployment={data.deployment} />
            </div>
            {data.deployment && data.deployment.deployed_at ? (
              <div style={{ opacity: 0.6, fontSize: 11 }}>部署于 {data.deployment.deployed_at}</div>
            ) : null}
          </div>

          {/* degraded 非空：黄色告警条逐条列 reason（如实呈现，不伪造空值） */}
          {data.degraded.length > 0 ? (
            <div
              data-testid="lane-degraded"
              role="status"
              style={{
                margin: "8px 0",
                padding: "6px 10px",
                borderRadius: 6,
                background: "rgba(214,158,46,0.14)",
                border: "1px solid rgba(214,158,46,0.45)",
                color: "#d69e2e",
                fontSize: 12,
              }}
            >
              ⚠️ 数据源降级（如实呈现，未伪造）：
              <ul style={{ margin: "4px 0 0 16px", padding: 0 }}>
                {data.degraded.map((reason) => {
                  return (
                    <li key={reason} data-testid="lane-degraded-reason">
                      {reason}
                    </li>
                  );
                })}
              </ul>
            </div>
          ) : null}
          {/* lane 表：goal / 分支 / 状态 / head@base / 最后验证 / 重叠告警
              （lane 记录无 ahead/behind 计数字段，以 head_sha@base_main_sha 短 sha 呈现，不伪造计数） */}
          <table data-testid="lane-table" style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
            <thead>
              <tr style={{ textAlign: "left", opacity: 0.7 }}>
                <th style={{ padding: "4px 6px" }}>goal</th>
                <th style={{ padding: "4px 6px" }}>分支</th>
                <th style={{ padding: "4px 6px" }}>状态</th>
                <th style={{ padding: "4px 6px" }}>head@base</th>
                <th style={{ padding: "4px 6px" }}>最后验证</th>
                <th style={{ padding: "4px 6px" }}>重叠</th>
              </tr>
            </thead>
            <tbody>
              {data.lanes.map((lane) => {
                const laneOverlaps = data.overlaps.filter(
                  (o) => o.a === lane.lane_id || o.b === lane.lane_id
                );
                return (
                  <tr key={lane.lane_id} data-testid="lane-row" style={{ borderTop: "1px solid rgba(128,128,128,0.25)" }}>
                    <td style={{ padding: "4px 6px" }} title={lane.goal_id}>
                      {lane.goal_id || "—"}
                    </td>
                    <td style={{ padding: "4px 6px" }}>
                      <code>{lane.branch}</code>
                      {lane.lane_role === "sub" ? (
                        <span style={{ opacity: 0.6, fontSize: 11 }}> sub</span>
                      ) : null}
                    </td>
                    <td style={{ padding: "4px 6px" }}>
                      {lane.status}
                      {lane.priority === "hotfix" ? " ⚡" : ""}
                      {lane.base_is_broken ? (
                        <span style={{ color: "#e53e3e", fontSize: 11 }}> base受损</span>
                      ) : null}
                    </td>
                    <td style={{ padding: "4px 6px" }}>
                      <code>
                        {shortSha(lane.head_sha)}@{shortSha(lane.base_main_sha)}
                      </code>
                    </td>
                    <td style={{ padding: "4px 6px" }}>
                      {lane.verify_ref ? <code>{lane.verify_ref}</code> : "—"}
                    </td>
                    <td style={{ padding: "4px 6px" }}>
                      {laneOverlaps.length > 0 ? (
                        laneOverlaps.map((o, i) => {
                          const other = (o.branches || []).filter((b) => b !== lane.branch)[0] || "其它lane";
                          return (
                            <div key={i} title={o.shared_paths.join("\n")} style={{ color: "#d69e2e" }}>
                              ⚠️ 与 {other} 重叠 {o.shared_paths.length} 条路径
                            </div>
                          );
                        })
                      ) : (
                        "—"
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>

          {/* 空态：有数据但无在途 lane */}
          {data.lanes.length === 0 && (
            <div className="v2-tree-loading" data-testid="lane-empty">
              （暂无登记 lane）
            </div>
          )}
        </>
      ) : null}
    </div>
  );
}
