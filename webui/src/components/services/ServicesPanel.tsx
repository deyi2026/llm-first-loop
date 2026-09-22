// Web V2：受管服务身份面板（desired/live/stable 三层身份可见性；TASK-005）
// 数据源与 service_control 工具共用同一后端 composer（/api/v1/services/status）。

import { useEffect, useState } from "react";
import { fetchServicesStatus, type ServicesStatusInfo } from "../../core/api";

function shortHead(head: string | null | undefined): string {
  if (!head) return "—";
  return head.slice(0, 7);
}

// live manifest 写 +0800、store 回执写 +00:00（ISO 原样来自两个进程）；
// 面板统一渲染为浏览器本地时区，否则同屏两种时区肉眼不可比（2026-09-22 14:53 误读案例）。
function fmtLocal(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString(undefined, {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

const cardStyle: React.CSSProperties = {
  border: "1px solid #ddd",
  borderRadius: 8,
  padding: 12,
  fontSize: 13,
  lineHeight: 1.7,
};

export function ServicesPanel() {
  const [info, setInfo] = useState<ServicesStatusInfo | null>(null);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    let cancelled = false;
    const refresh = () => {
      void fetchServicesStatus().then((data) => {
        if (!cancelled) {
          setInfo(data);
          setLoaded(true);
        }
      });
    };
    refresh();
    const timer = window.setInterval(refresh, 15000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, []);

  const deployment = info?.deployment ?? null;

  return (
    <div className="v2-learning-panel" data-testid="services-panel">
      <h2>🛠 受管服务身份</h2>
      <p style={{ fontSize: 12, color: "var(--dsw-alias-label-tertiary)" }}>
        desired = operator 发布的期望部署 · live = 服务进程 startup manifest · stable =
        最近一次受控重启成功回执
      </p>
      {deployment ? (
        <div style={cardStyle}>
          <strong>desired deployment</strong>
          <div>
            generation {deployment.generation} · {shortHead(deployment.git_head)}
          </div>
          <div style={{ fontSize: 12, color: "var(--dsw-alias-label-tertiary)" }}>
            code_root {deployment.code_root}
          </div>
        </div>
      ) : loaded ? (
        <div style={cardStyle}>（尚未发布 desired deployment）</div>
      ) : null}
      <div className="v2-learning-grid">
        {Object.entries(info?.services ?? {}).map(([name, svc]) => (
          <div key={name} style={cardStyle} data-testid={"service-card-" + name}>
            <strong>
              {name}{" "}
              {svc.restart_required ? (
                <span style={{ color: "#d46b08" }}>⚠ 需要重启</span>
              ) : (
                <span style={{ color: "#237804" }}>✓ 与 desired 一致</span>
              )}
            </strong>
            {svc.live.manifest_present ? (
              <div>
                live: pid {svc.live.pid ?? "—"}
                {svc.live.pid_alive === false ? "（进程不存在）" : ""} ·{" "}
                {shortHead(svc.live.git_head)}
                {svc.live.started_at ? " · " + fmtLocal(svc.live.started_at) : ""}
              </div>
            ) : (
              <div>live: （无 startup manifest）</div>
            )}
            {svc.live.manifest_error ? <div>live: （manifest 不可读）</div> : null}
            <div>
              stable:{" "}
              {svc.stable ? (
                <>
                  gen {svc.stable.generation}
                  {svc.stable.matches_desired_generation
                    ? " · " + shortHead(svc.stable.git_head)
                    : " · （早于当前 desired，不声明 git 身份）"}
                  {" · " + fmtLocal(svc.stable.succeeded_at)}
                </>
              ) : (
                "（尚无成功重启回执）"
              )}
            </div>
            {svc.reasons.length > 0 ? (
              <div style={{ fontSize: 12, color: "#d46b08" }}>
                {svc.reasons.map((reason) => (
                  <div key={reason}>{reason}</div>
                ))}
              </div>
            ) : null}
          </div>
        ))}
      </div>
      {loaded && !info ? <div style={cardStyle}>（服务身份接口暂不可用）</div> : null}
    </div>
  );
}
