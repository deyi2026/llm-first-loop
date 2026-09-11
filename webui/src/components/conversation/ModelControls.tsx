import { useEffect, useMemo, useState } from "react";
import type { ModelCapability, ModelCatalog } from "../../core/chat";
import {
  sessionStore,
  useModel,
  useReasoningEffort,
  useThinkingMode,
  type ThinkingMode,
} from "../../core/stores";

function shortModelName(value: string): string {
  const parts = value.split("/");
  return parts[parts.length - 1] || value;
}

function capabilityFor(catalog: ModelCatalog, model: string | null): ModelCapability | undefined {
  const selected = model || catalog.current;
  return catalog.catalog.find((item) => item.id === selected);
}

export function ModelControls({ catalog }: { catalog: ModelCatalog }) {
  const currentModel = useModel();
  const effort = useReasoningEffort();
  const mode = useThinkingMode();
  const [reasoningOpen, setReasoningOpen] = useState(false);
  const capability = useMemo(
    () => capabilityFor(catalog, currentModel),
    [catalog, currentModel]
  );

  useEffect(() => {
    if (!capability) return;
    if (!capability.reasoning_control_supported && mode !== "auto") {
      sessionStore.setThinkingMode("auto");
    }
    if (
      effort &&
      capability.reasoning_efforts.length > 0 &&
      !capability.reasoning_efforts.includes(effort)
    ) {
      sessionStore.setReasoningEffort(null);
    }
    if (effort && capability.reasoning_efforts.length === 0) {
      sessionStore.setReasoningEffort(null);
    }
  }, [capability, effort, mode]);

  const selected = currentModel || catalog.current || "";
  const staleSelected = Boolean(
    selected && catalog.currentAvailable === false && selected === catalog.current
  );
  const reasoningLabel = (() => {
    if (!capability?.reasoning_capable) return "推理:模型自管";
    if (!capability.reasoning_control_supported) return "推理:模型自管";
    if (mode === "auto") return "推理:自动";
    if (mode === "off" && capability.reasoning_control === "always_on_effort") return "推理:最低";
    if (mode === "off") return "推理:关";
    return effort ? `推理:${effort}` : "推理:开";
  })();

  const setMode = (value: ThinkingMode) => {
    sessionStore.setThinkingMode(value);
    if (value === "auto") sessionStore.setReasoningEffort(null);
  };

  return (
    <div className="v2-model-controls" data-testid="model-controls">
      <select
        className="v2-control-pill v2-model-pill"
        value={selected}
        onChange={(e) => sessionStore.setModel(e.target.value || null)}
        aria-label="选择模型"
        title={selected || "默认模型"}
        data-testid="model-select"
      >
        {staleSelected ? (
          <option value={selected} disabled>
            {shortModelName(selected)} · 当前不可用
          </option>
        ) : null}
        {catalog.models.length === 0 && !staleSelected ? <option value="">默认模型</option> : null}
        {catalog.models.map((model) => (
          <option key={model} value={model}>
            {shortModelName(model)}
          </option>
        ))}
      </select>
      <div className="v2-reasoning-control">
        <button
          type="button"
          className="v2-control-pill"
          onClick={() => setReasoningOpen((value) => !value)}
          aria-expanded={reasoningOpen}
          data-testid="reasoning-button"
        >
          {reasoningLabel} ▾
        </button>
        {reasoningOpen ? (
          <div className="v2-mini-popover" data-testid="reasoning-popover">
            <div className="v2-mini-title">
              {capability?.reasoning_capable ? "推理控制" : "未证实可控推理"}
            </div>
            <div className="v2-choice-row">
              <button
                type="button"
                className={mode === "auto" ? "active" : ""}
                onClick={() => setMode("auto")}
              >
                自动
              </button>
              {capability?.reasoning_control_supported ? (
                <button
                  type="button"
                  className={mode === "on" ? "active" : ""}
                  onClick={() => setMode("on")}
                >
                  开启
                </button>
              ) : null}
              {capability?.reasoning_can_disable ? (
                <button
                  type="button"
                  className={mode === "off" ? "active" : ""}
                  onClick={() => setMode("off")}
                >
                  关闭
                </button>
              ) : capability?.reasoning_control === "always_on_effort" ? (
                <button
                  type="button"
                  className={mode === "off" ? "active" : ""}
                  onClick={() => setMode("off")}
                  title="该模型始终推理；这里映射到最低推理等级"
                >
                  最低
                </button>
              ) : null}
            </div>
            {capability?.reasoning_efforts.length ? (
              <>
                <div className="v2-mini-title">推理等级</div>
                <div className="v2-choice-row">
                  {capability.reasoning_efforts.map((item) => (
                    <button
                      key={item}
                      type="button"
                      className={effort === item ? "active" : ""}
                      disabled={mode === "auto" || mode === "off"}
                      onClick={() => sessionStore.setReasoningEffort(item)}
                    >
                      {item}
                    </button>
                  ))}
                </div>
              </>
            ) : null}
            {capability?.reasoning_control === "always_on_effort" ? (
              <div className="v2-mini-note">该模型始终启用推理，“最低”不是关闭。</div>
            ) : !capability?.reasoning_control_supported ? (
              <div className="v2-mini-note">没有已证实的显式控制协议，保持模型/provider 默认。</div>
            ) : null}
          </div>
        ) : null}
      </div>
    </div>
  );
}
