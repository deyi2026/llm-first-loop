// Web V2：右侧面板（阶段 3：设置=通用+模型目录；后台任务=如实占位）

import { useEffect, useState } from "react";
import { zh } from "../../i18n/zh";
import { useConnection } from "../../core/stores";
import { fetchModels } from "../../core/chat";

export function RightPanel({ open }: { open: boolean }) {
  const [tab, setTab] = useState<"settings" | "jobs">("settings");
  const conn = useConnection();
  const [models, setModels] = useState<string[]>([]);
  const [current, setCurrent] = useState<string | null>(null);

  const loadCatalog = async () => {
    const { models, current } = await fetchModels();
    setModels(models);
    setCurrent(current);
  };

  useEffect(() => {
    if (open && tab === "settings") void loadCatalog();
  }, [open, tab]);

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
            <div className="v2-panel-section-title">模型目录</div>
            <div className="v2-model-catalog" data-testid="model-catalog">
              {models.map((m) => (
                <div
                  key={m}
                  className={`v2-catalog-item ${m === current ? "current" : ""}`}
                  data-testid="catalog-item"
                >
                  <span className="v2-catalog-id">{m}</span>
                  {m === current && <span className="v2-catalog-current">当前</span>}
                </div>
              ))}
              {models.length === 0 && (
                <div className="v2-placeholder">模型目录为空（/api/v1/models）</div>
              )}
            </div>
            <button type="button" className="v2-btn ghost" onClick={() => void loadCatalog()}>
              ⟳ {zh.reload}
            </button>
          </>
        ) : (
          <div className="v2-placeholder">{zh.panelPlaceholder.replace("{stage}", "4")}（后台任务）</div>
        )}
      </div>
    </aside>
  );
}
