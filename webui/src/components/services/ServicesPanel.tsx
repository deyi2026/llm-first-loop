// Web V2：受管服务身份面板（desired/live/stable 三层身份可见性；TASK-005）
// 数据源与 service_control 工具共用同一后端 composer（/api/v1/services/status）。

import { useEffect, useState } from "react";
import { fetchServicesStatus, type ServicesStatusInfo } from "../../core/api";

function shortHead(head: string | null | undefined): string {
  if (!head) return "—";
  return head.slice(0, 7);
}

// live manifest 写 +0800、store 回执写 +00:00（ISO 原样来自两个进程）；
// 面板必须统一渲染，否则同屏两种时区肉眼不可比（2026-09-22 14:53 误读案例）。
// 渲染目标：**服务器挂钟**（server_tz_offset_minutes，后端实时给出含夏令时的偏移），
// 与访问设备的浏览器时区无关；后端未提供该字段时回退浏览器本地时区。
function fmtServerClock(
  iso: string | null | undefined,
  serverOffsetMin: number | undefined
): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const opts: Intl.DateTimeFormatOptions = {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  };
  if (serverOffsetMin === undefined) return d.toLocaleString(undefined, opts);
  // 平移到服务器挂钟后以 UTC 格式化（toLocaleString 不再二次偏移）
  const shifted = new Date(
    d.getTime() + (serverOffsetMin + d.getTimezoneOffset()) * 60000
  );
  return shifted.toLocaleString(undefined, { ...opts, timeZone: "UTC" });
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
  const serverOffset = info?.server_tz_offset_minutes;

  return (
    <div className="v2-learning-panel v2-services-view" data-testid="services-panel">
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
          <div className="v2-service-code-root" style={{ fontSize: 12, color: "var(--dsw-alias-label-tertiary)" }}>
            code_root {deployment.code_root}
          </div>
        </div>
      ) : loaded ? (
        <div style={cardStyle}>（尚未发布 desired deployment）</div>
      ) : null}
      {/* Service cards are peers, not the label/value pairs in LearningPanel.
          Reusing .v2-learning-grid makes every other card a 110px column. */}
      <div className="v2-services-grid" data-testid="services-grid">
        {Object.entries(info?.services ?? {}).map(([name, svc]) => (
          <div key={name} className="v2-service-card" style={cardStyle} data-testid={"service-card-" + name}>
            <strong>
              {name}{" "}
              {svc.restart_required ? (
                <span style={{ color: "#d46b08" }}>⚠ 运行身份需核验/重启</span>
              ) : (
                <span style={{ color: "#237804" }}>✓ 运行代码与 desired 一致</span>
              )}
            </strong>
            {svc.live.manifest_present ? (
              <div>
                live: pid {svc.live.pid ?? "—"}
                {svc.live.pid_alive === false ? "（进程不存在）" : ""} ·{" "}
                {shortHead(svc.live.git_head)}
                {svc.live.started_at ? " · " + fmtServerClock(svc.live.started_at, serverOffset) : ""}
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
                  {" · " + fmtServerClock(svc.stable.succeeded_at, serverOffset)}
                </>
              ) : (
                "（尚无成功重启回执）"
              )}
            </div>
            {deployment && svc.stable && svc.stable.generation < deployment.generation ? (
              <div style={{ fontSize: 12, color: "#ad6800" }} data-testid={"stable-lag-" + name}>
                ○ 稳定回执未追平：距 desired gen {deployment.generation} 差 {deployment.generation - svc.stable.generation} 代。
                {svc.restart_required ? "运行身份需单独核验。" : "运行代码已匹配，无需仅为追平代次重启。"}
              </div>
            ) : deployment && svc.stable && svc.stable.generation > deployment.generation ? (
              <div style={{ fontSize: 12, color: "#ad6800" }}>
                ⚠ 稳定回执代次高于当前 desired，请核验部署历史。
              </div>
            ) : deployment && svc.stable && svc.stable.matches_desired_generation ? (
              <div style={{ fontSize: 12, color: "#237804" }}>✓ 稳定回执已追平 desired</div>
            ) : deployment && svc.stable ? (
              <div style={{ fontSize: 12, color: "#ad6800" }}>⚠ 稳定回执尚未确认与 desired 匹配</div>
            ) : null}
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
