// Web V2：受管服务身份面板（desired/live/stable 三层身份可见性；TASK-005）
// 数据源与 service_control 工具共用同一后端 composer（/api/v1/services/status）。

import { useEffect, useRef, useState } from "react";
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
    hour12: false,
  };
  if (serverOffsetMin === undefined) return d.toLocaleString(undefined, opts);
  // 平移到服务器挂钟后以 UTC 格式化（toLocaleString 不再二次偏移）
  const shifted = new Date(
    d.getTime() + serverOffsetMin * 60000
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
  // HOTFIX-20261126（三入口性能回归）：15s 轮询防重入 + 标签隐藏暂停 + 卸载取消在途；
  // 首屏明确 loading；失败保留最近有效身份并标记陈旧（asOf），不再冒充正常。
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState("");
  const [asOf, setAsOf] = useState(0);
  const [tick, setTick] = useState(0);
  const inFlight = useRef(false);
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    let cancelled = false;
    const refresh = async () => {
      if (inFlight.current) {
        const prev = abortRef.current;
        if (!prev || !prev.signal.aborted) return; // 防重入：慢端点轮询不堆积
        // 独审 P2-2：tick 重启已取消旧请求 → 立即接手，不等下一个 15s 周期
      }
      inFlight.current = true;
      const controller = new AbortController();
      abortRef.current = controller;
      try {
        const data = await fetchServicesStatus({ signal: controller.signal });
        if (cancelled || controller.signal.aborted) return;
        if (data) {
          setInfo(data); // 保留最近有效身份：成功才覆盖
          setErr("");
          setAsOf(Date.now());
        } else {
          // 独审 P2-1：null 可能来自认证被拒/超时/网络，文案不再误诊单一原因
          setErr("服务身份接口暂不可用（认证被拒、超时或网络异常，将自动重试）");
        }
        setLoaded(true);
        setLoading(false);
      } finally {
        if (abortRef.current === controller) {
          inFlight.current = false;
          abortRef.current = null;
        }
      }
    };
    void refresh();
    const timer = window.setInterval(() => {
      if (document.hidden) return; // 离开页面（标签隐藏）停止刷新
      void refresh();
    }, 15000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
      abortRef.current?.abort();
    };
  }, [tick]);

  const deployment = info?.deployment ?? null;
  const wheel = deployment?.artifact_kind === "wheel_release";
  const serverOffset = info?.server_tz_offset_minutes;

  return (
    <div className="v2-learning-panel v2-services-view" data-testid="services-panel">
      <h2>🛠 受管服务身份</h2>
      <p style={{ fontSize: 12, color: "var(--dsw-alias-label-tertiary)" }}>
        desired = operator 发布的期望部署 · live = 服务进程 startup manifest · stable =
        最近一次受控重启成功回执
      </p>
      {loading && !info ? (
        <div style={cardStyle} data-testid="services-loading">读取服务身份…</div>
      ) : null}
      {err ? (
        <div style={{ ...cardStyle, color: "#d46b08" }} data-testid="services-stale">
          ⚠ 刷新失败（{err}）
          {info
            ? ` — 以下为 ${asOf ? new Date(asOf).toLocaleTimeString() : "—"} 最近有效数据，已标记陈旧`
            : " — 未获取到过有效数据"}
          ；15s 后自动重试
          <div style={{ marginTop: 6 }}>
            <button
              onClick={() => {
                setErr("");
                setLoading(true);
                setTick((t) => t + 1);
              }}
            >
              重试
            </button>
          </div>
        </div>
      ) : null}
      {deployment ? (
        <div style={cardStyle}>
          <strong>desired deployment</strong>
          <div>
            generation {deployment.generation} · {wheel
              ? `wheel ${deployment.version} · SHA ${deployment.wheel_sha256?.slice(0, 12) ?? "—"}`
              : shortHead(deployment.git_head)}
          </div>
          <div className="v2-service-code-root" style={{ fontSize: 12, color: "var(--dsw-alias-label-tertiary)" }}>
            {wheel ? `release_dir ${deployment.release_dir}` : `code_root ${deployment.code_root}`}
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
                {wheel
                  ? `wheel ${svc.live.release_version || "身份缺失"} · SHA ${svc.live.wheel_sha256?.slice(0, 12) || "—"}`
                  : shortHead(svc.live.git_head)}
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
                    ? " · " + (wheel
                      ? `wheel ${svc.stable.version || "身份缺失"} · SHA ${svc.stable.wheel_sha256?.slice(0, 12) || "—"}`
                      : shortHead(svc.stable.git_head))
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
      {info?.cli_processes ? (
        <div style={cardStyle} className="v2-service-card" data-testid="service-card-cli">
          <strong>CLI · {info.cli_processes.state === "identity_matches_target" ? "运行身份匹配" :
            info.cli_processes.state === "update_required" ? "存在待升级进程" :
            info.cli_processes.state === "not_running" ? "无已登记运行进程" : "身份待核验"}</strong>
          <div style={{ fontSize: 12, color: "var(--dsw-alias-label-tertiary)" }}>
            仅统计持有进程锁的新版 CLI；未登记的旧进程不视为已收敛。
          </div>
          {info.cli_processes.processes.map((proc) => (
            <div key={proc.pid}>
              pid {proc.pid} · gen {proc.generation ?? "—"} · {proc.artifact_kind === "wheel_release"
                ? `wheel ${proc.version} · SHA ${proc.wheel_sha256.slice(0, 12)}` : shortHead(proc.git_head)}
              {proc.state !== "identity_matches_target" ? ` · ${proc.reason}` : ""}
            </div>
          ))}
          {info.cli_processes.uncertain > 0 ? <div>另有 {info.cli_processes.uncertain} 条身份待核验。</div> : null}
        </div>
      ) : null}
      {loaded && !info && !err ? <div style={cardStyle}>（服务身份接口暂不可用）</div> : null}
    </div>
  );
}
