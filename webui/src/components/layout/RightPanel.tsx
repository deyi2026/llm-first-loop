// Web V2：右侧面板（阶段 1 骨架：设置/后台任务标签占位，阶段 3/4 接入）

import { useState } from "react";
import { zh } from "../../i18n/zh";
import { useConnection } from "../../core/stores";

export function RightPanel({ open }: { open: boolean }) {
  const [tab, setTab] = useState<"settings" | "jobs">("settings");
  const conn = useConnection();

  if (!open) return null;

  return (
    <aside className="v2-panel" data-testid="right-panel">
      <div className="v2-panel-tabs">
        <button
          type="button"
          className={`v2-panel-tab ${tab === "settings" ? "active" : ""}`}
          onClick={() => setTab("settings")}
        >
          {zh.panelSettings}
        </button>
        <button
          type="button"
          className={`v2-panel-tab ${tab === "jobs" ? "active" : ""}`}
          onClick={() => setTab("jobs")}
        >
          {zh.panelJobs}
        </button>
      </div>
      <div className="v2-panel-body" data-testid="panel-body">
        {tab === "settings" ? (
          <>
            <div className="v2-kv">
              <span className="k">服务</span>
              <span className="v">{conn.service || "—"}</span>
              <span className="k">版本</span>
              <span className="v">{conn.version || "—"}</span>
              <span className="k">连接</span>
              <span className="v">{conn.ok ? zh.statusConnected : zh.statusDisconnected}</span>
            </div>
            <div className="v2-placeholder" style={{ marginTop: 16 }}>
              {zh.panelPlaceholder.replace("{stage}", "3")}（通用/模型目录）
            </div>
          </>
        ) : (
          <div className="v2-placeholder">{zh.panelPlaceholder.replace("{stage}", "3")}（后台任务）</div>
        )}
      </div>
    </aside>
  );
}
