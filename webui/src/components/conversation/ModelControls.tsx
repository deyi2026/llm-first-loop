import { useEffect, useMemo, useState } from "react";
import type { ModelCapability, ModelCatalog } from "../../core/chat";
import { setSessionModel } from "../../core/api";
import {
  sessionStore,
  useModel,
  useReasoningEffort,
  useThinkingMode,
  type ThinkingMode,
} from "../../core/stores";
import { useDismissibleLayer } from "../../core/useDismissibleLayer";

function shortModelName(value: string): string {
  const parts = value.split("/");
  return parts[parts.length - 1] || value;
}

function modelDisplayName(catalog: ModelCatalog, value: string): string {
  return catalog.catalog.find((item) => item.id === value)?.display_name || shortModelName(value);
}

function capabilityFor(catalog: ModelCatalog, model: string | null): ModelCapability | undefined {
  const selected = model || catalog.current;
  return catalog.catalog.find((item) => item.id === selected);
}

/** §6.3.2/C4-lite：按 Provider 分组（optgroup label=provider display_name，缺省回退 id）；
 *  选项显示 display_name，缺省回退短名。目录条目缺失的 id（如运行时过期事实）按
 *  id 前缀兜底分组，保持可用。 */
function groupedModelOptions(
  catalog: ModelCatalog
): Array<{ key: string; label: string; items: Array<{ id: string; label: string }> }> {
  const map = new Map<string, { key: string; label: string; items: Array<{ id: string; label: string }> }>();
  const ensure = (key: string, label: string) => {
    let group = map.get(key);
    if (!group) {
      group = { key, label, items: [] };
      map.set(key, group);
    }
    return group;
  };
  for (const item of catalog.catalog) {
    const key = item.provider || "其他";
    ensure(key, item.provider_name || key).items.push({
      id: item.id,
      label: item.display_name || shortModelName(item.id),
    });
  }
  const listed = new Set(catalog.catalog.map((item) => item.id));
  for (const id of catalog.models) {
    if (listed.has(id)) continue;
    const key = id.includes("/") ? id.slice(0, id.indexOf("/")) : "其他";
    ensure(key, key).items.push({ id, label: shortModelName(id) });
  }
  return Array.from(map.values());
}

export function ModelControls({ catalog }: { catalog: ModelCatalog }) {
  const currentModel = useModel();
  const effort = useReasoningEffort();
  const mode = useThinkingMode();
  const [reasoningOpen, setReasoningOpen] = useState(false);
  const rootRef = useDismissibleLayer<HTMLDivElement>(reasoningOpen, () => setReasoningOpen(false));
  const capability = useMemo(
    () => capabilityFor(catalog, currentModel),
    [catalog, currentModel]
  );
  const groups = useMemo(() => groupedModelOptions(catalog), [catalog]);

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
  const selectedMissing = Boolean(selected && !catalog.models.includes(selected));
  const staleSelected = Boolean(
    selectedMissing && catalog.currentAvailable === false && selected === catalog.current
  );
  const selectedMissingLabel = staleSelected
    ? `${modelDisplayName(catalog, selected)} · 当前不可用`
    : catalog.models.length === 0
      ? `${modelDisplayName(catalog, selected)} · 当前选择 · 目录暂不可用`
      : `${modelDisplayName(catalog, selected)} · 当前选择 · 目录中未列出`;
  const reasoningLabel = (() => {
    if (!capability?.reasoning_capable) return "推理:模型自管";
    if (!capability.reasoning_control_supported) return "推理:模型自管";
    if (mode === "auto") {
      return capability.reasoning_default_effort
        ? `推理:自动(${capability.reasoning_default_effort})`
        : "推理:自动";
    }
    if (mode === "off" && capability.reasoning_control === "always_on_effort") return "推理:最低";
    if (mode === "off") return "推理:关";
    return effort ? `推理:${effort}` : "推理:开";
  })();

  const setMode = (value: ThinkingMode) => {
    sessionStore.setThinkingMode(value);
    if (value === "auto") sessionStore.setReasoningEffort(null);
  };

  // §7.6 会话覆盖：store 立即生效（乐观），已定位会话则落盘 session model；
  // 空值 = 清除 override（跟随全局默认）。新会话待建（newSessionPending）时跳过落盘，
  // 由首条消息携带模型创建。
  const selectModel = (value: string) => {
    sessionStore.selectModel(value || null);
    const sid = sessionStore.getState().currentSessionId;
    if (sid && !sessionStore.getState().newSessionPending) {
      void setSessionModel(sid, value || null);
    }
  };

  return (
    <div className="v2-model-controls" data-testid="model-controls" ref={rootRef}>
      <select
        className="v2-control-pill v2-model-pill"
        value={selected}
        onChange={(e) => selectModel(e.target.value)}
        aria-label="选择模型"
        title={selected || "默认模型"}
        data-testid="model-select"
      >
        {selectedMissing ? (
          <option value={selected} disabled>
            {selectedMissingLabel}
          </option>
        ) : null}
        <option value="">
          {catalog.default ? `默认模型（${shortModelName(catalog.default)}）` : "默认模型"}
        </option>
        {groups.map((group) => (
          <optgroup key={group.key} label={group.label}>
            {group.items.map((item) => (
              <option key={item.id} value={item.id} title={item.id}>
                {item.label}
              </option>
            ))}
          </optgroup>
        ))}
      </select>
      {catalog.current ? (
        <span
          className="v2-model-source-chip"
          data-testid="model-source"
          title={`当前：${catalog.current}`}
        >
          {catalog.currentSource === "session" ? "会话" : "默认"}
          {catalog.currentAvailable === false ? " · 不可用" : ""}
        </span>
      ) : null}
      <div className="v2-reasoning-control">
        <button
          type="button"
          className="v2-control-pill"
          onClick={() => setReasoningOpen((value) => !value)}
          aria-expanded={reasoningOpen}
          aria-haspopup="menu"
          data-testid="reasoning-button"
        >
          {reasoningLabel} ▾
        </button>
        {reasoningOpen ? (
          <div className="v2-mini-popover" data-testid="reasoning-popover" role="menu">
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
              ) : capability?.reasoning_control === "always_on_effort" && capability.reasoning_efforts.includes("low") ? (
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
                      disabled={
                        mode === "off" ||
                        !capability.reasoning_control_supported ||
                        (mode === "auto" && capability.reasoning_control !== "provider_owned")
                      }
                      onClick={() => {
                        // Browser-owned provider effort is directly selectable:
                        // choosing a concrete level is itself an explicit
                        // request override, so leave auto and enter `on`.
                        if (capability.reasoning_control === "provider_owned" && mode === "auto") {
                          sessionStore.setThinkingMode("on");
                        }
                        sessionStore.setReasoningEffort(item);
                      }}
                    >
                      {item}
                    </button>
                  ))}
                </div>
              </>
            ) : null}
            {capability?.reasoning_control === "always_on_effort" ? (
              <div className="v2-mini-note">
                该模型始终启用推理，“最低”不是关闭。
                {capability.reasoning_default_effort ? ` 自动默认：${capability.reasoning_default_effort}。` : ""}
              </div>
            ) : capability?.reasoning_control === "provider_owned" ? (
              <div className="v2-mini-note">
                该档位会在本次请求发送前同步到网页版模型并机械确认；“自动”使用 provider 默认档位。
              </div>
            ) : !capability?.reasoning_control_supported ? (
              <div className="v2-mini-note">没有已证实的显式控制协议，保持模型/provider 默认。</div>
            ) : null}
          </div>
        ) : null}
      </div>
    </div>
  );
}
