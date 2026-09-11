import { useEffect, useMemo, useState } from "react";
import {
  createProvider,
  deleteProviderConfig,
  fetchProviderAdmin,
  reloadProviderRegistry,
  replaceProvider,
  setConfiguredDefaultModel,
  testProviderConnection,
  updateProviderCredential,
  type ProviderAdminFact,
  type ProviderAdminInput,
  type ProviderAdminSnapshot,
  type ProviderModelAdminInput,
} from "../../core/api";
import { notifyModelCatalogChanged } from "../../core/chat";

const blankModel = (): ProviderModelAdminInput => ({
  id: "",
  enabled: true,
  context: 131072,
  max_input_tokens: null,
  max_tokens: null,
  cost_tier: "mid",
  thinking: false,
  reasoning_capable: false,
  reasoning_control: "unknown",
  reasoning: false,
  long_context: false,
  multimodal: false,
  wire_protocol: "openai",
  capability_tier: "unknown",
  send_tool_choice: true,
  reasoning_split: false,
  reasoning_replay: "configured",
  reasoning_effort_map: {},
  runtime_identity: "",
  temperature: null,
  top_p: null,
  top_k: null,
  min_p: null,
});

const blankProvider = (): ProviderAdminInput => ({
  id: "",
  enabled: true,
  base_url: "https://",
  api_key_env: "",
  default_model: "",
  timeout_s: 120,
  history_budget_chars: null,
  max_input_tokens: null,
  max_tokens: 16000,
  chars_per_token: null,
  models: [blankModel()],
});

function providerToInput(provider: ProviderAdminFact): ProviderAdminInput {
  return {
    id: provider.id,
    enabled: provider.enabled !== false,
    base_url: provider.base_url ?? "",
    api_key_env: provider.api_key_env ?? "",
    default_model: provider.default_model ?? "",
    timeout_s: provider.timeout_s ?? null,
    history_budget_chars: provider.history_budget_chars ?? null,
    max_input_tokens: provider.max_input_tokens ?? null,
    max_tokens: provider.max_tokens ?? null,
    chars_per_token: provider.chars_per_token ?? null,
    models: provider.models.map((model) => ({
      ...blankModel(),
      ...model,
      enabled: model.enabled !== false,
      reasoning_capable: Boolean(model.reasoning_capable),
      multimodal: Boolean(model.multimodal),
      send_tool_choice: model.send_tool_choice !== false,
      reasoning_split: Boolean(model.reasoning_split),
    })),
  };
}

function num(value: string): number | null {
  if (!value.trim()) return null;
  const n = Number(value);
  return Number.isFinite(n) ? n : null;
}

export function ProviderManager({ onCatalogChanged }: { onCatalogChanged?: () => Promise<void> | void }) {
  const [snapshot, setSnapshot] = useState<ProviderAdminSnapshot | null>(null);
  const [editor, setEditor] = useState<ProviderAdminInput | null>(null);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [apiKey, setApiKey] = useState("");
  const [busy, setBusy] = useState("");
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [testFacts, setTestFacts] = useState<Record<string, string>>({});

  const load = async () => {
    const data = await fetchProviderAdmin();
    setSnapshot(data);
    return data;
  };

  useEffect(() => { void load(); }, []);

  const allModels = useMemo(() => {
    if (!snapshot) return [];
    return snapshot.providers.flatMap((provider) =>
      provider.models
        .filter((model) => model.enabled !== false && provider.enabled !== false)
        .map((model) => `${provider.id}/${model.id}`)
    );
  }, [snapshot]);

  const syncCatalogConsumers = async () => {
    await onCatalogChanged?.();
    notifyModelCatalogChanged();
  };

  const finish = async (text: string) => {
    setMessage(text);
    setError("");
    await load();
    await syncCatalogConsumers();
  };

  const fail = (text: string) => {
    setError(text || "操作失败");
    setMessage("");
  };

  const saveEditor = async () => {
    if (!snapshot || !editor || busy) return;
    setBusy("save");
    setError("");
    try {
      const normalized: ProviderAdminInput = {
        ...editor,
        default_model: editor.default_model || editor.models[0]?.id || "",
      };
      const result = editingId
        ? await replaceProvider(snapshot.config_version, normalized)
        : await createProvider(snapshot.config_version, normalized, apiKey || undefined);
      if (!result.ok) {
        fail(result.detail);
        return;
      }
      let finalResult = result;
      if (editingId && apiKey) {
        finalResult = await updateProviderCredential(editingId, apiKey);
        if (!finalResult.ok) {
          fail(`Provider 配置已保存；API Key 更新失败：${finalResult.detail}`);
          await load();
          await syncCatalogConsumers();
          return;
        }
      }
      setEditor(null);
      setEditingId(null);
      setApiKey("");
      await finish(editingId ? "Provider 已保存并热重载。" : "Provider 已添加并热重载。");
    } finally {
      setBusy("");
    }
  };

  const toggleProvider = async (provider: ProviderAdminFact) => {
    if (!snapshot || busy) return;
    setBusy(`toggle:${provider.id}`);
    const next = providerToInput(provider);
    next.enabled = !next.enabled;
    const result = await replaceProvider(snapshot.config_version, next);
    if (result.ok) await finish(next.enabled ? "Provider 已启用。" : "Provider 已停用。");
    else fail(result.detail);
    setBusy("");
  };

  const removeProvider = async (provider: ProviderAdminFact) => {
    if (!snapshot || busy) return;
    if (!window.confirm(`删除 Provider “${provider.id}”？API Key 将保留，避免误删外部凭证。`)) return;
    setBusy(`delete:${provider.id}`);
    const result = await deleteProviderConfig(provider.id, snapshot.config_version);
    if (result.ok) await finish("Provider 已删除；凭证按安全策略保留。" );
    else fail(result.detail);
    setBusy("");
  };

  const clearCredential = async (providerId: string) => {
    if (!window.confirm(`清除 ${providerId} 的 Web 管理 API Key？`)) return;
    setBusy(`credential:${providerId}`);
    const result = await updateProviderCredential(providerId, "");
    if (result.ok) await finish("API Key 已从本机 .env 清除。" );
    else fail(result.detail);
    setBusy("");
  };

  const test = async (provider: ProviderAdminFact) => {
    if (busy) return;
    setBusy(`test:${provider.id}`);
    const result = await testProviderConnection(provider.id, provider.default_model ?? "");
    setTestFacts((old) => ({ ...old, [provider.id]: result.detail }));
    if (!result.ok) fail(result.detail);
    setBusy("");
  };

  const setDefault = async (model: string) => {
    if (!model || busy) return;
    setBusy("default");
    const result = await setConfiguredDefaultModel(model);
    if (result.ok) await finish("默认模型配置已保存；共享默认 Client 将在 Web Runtime 重启后生效。" );
    else fail(result.detail);
    setBusy("");
  };

  const reload = async () => {
    if (busy) return;
    setBusy("reload");
    const result = await reloadProviderRegistry();
    if (result.ok) await finish("Provider Registry 已热重载；默认 Client 仍保持启动快照。" );
    else fail(result.detail);
    setBusy("");
  };

  if (!snapshot) return <div className="v2-placeholder">正在读取 Provider 配置…</div>;

  return (
    <div className="v2-provider-admin" data-testid="provider-admin">
      <div className="v2-provider-summary">
        <div><span>配置来源</span><strong>{snapshot.source}</strong></div>
        <div><span>配置默认</span><strong>{snapshot.configured_default_model || "—"}</strong></div>
        <div><span>运行默认</span><strong>{snapshot.runtime_default_model || "—"}</strong></div>
      </div>
      {snapshot.restart_required ? (
        <div className="v2-provider-warning">默认模型配置已变化；动态选择可立即使用，新默认路由需重启 Web Runtime 后生效。</div>
      ) : null}
      {!snapshot.mutable ? (
        <div className="v2-provider-warning">MODEL_PROVIDERS 环境变量当前拥有配置权；Web 仅只读展示，不写入被遮蔽的本地文件。</div>
      ) : null}
      {message ? <div className="v2-provider-ok">{message}</div> : null}
      {error ? <div className="v2-panel-error">{error}</div> : null}

      <div className="v2-provider-actions">
        <select
          aria-label="配置默认模型"
          value={snapshot.configured_default_model ?? ""}
          onChange={(event) => void setDefault(event.target.value)}
          disabled={!snapshot.mutable || Boolean(busy)}
        >
          <option value="">选择全局默认模型</option>
          {allModels.map((model) => <option value={model} key={model}>{model}</option>)}
        </select>
        <button type="button" className="v2-btn ghost" disabled={!snapshot.mutable || Boolean(busy)} onClick={() => void reload()}>
          热重载 Registry
        </button>
        <button
          type="button"
          className="v2-btn"
          disabled={!snapshot.mutable || Boolean(busy)}
          onClick={() => { setEditor(blankProvider()); setEditingId(null); setApiKey(""); setError(""); }}
        >
          + 添加 Provider
        </button>
      </div>

      <div className="v2-provider-list">
        {snapshot.providers.map((provider) => (
          <article className="v2-provider-card" key={provider.id} data-testid={`provider-${provider.id}`}>
            <div className="v2-provider-head">
              <div>
                <strong>{provider.id}</strong>
                <span className={`v2-status-chip ${provider.effective ? "ok" : "neutral"}`}>
                  {provider.effective ? "已加载" : provider.enabled ? "未生效" : "已停用"}
                </span>
              </div>
              <span>{provider.models.length} 个模型</span>
            </div>
            <code>{provider.base_url}</code>
            <div className="v2-provider-meta">
              <span>凭证：{provider.api_key_env ? (provider.credential_configured ? `已配置 · ${provider.credential_source}` : `缺失 · ${provider.api_key_env}`) : "无需凭证"}</span>
              <span>Provider 默认：{provider.default_model || "—"}</span>
            </div>
            <div className="v2-provider-models">
              {provider.models.map((model) => (
                <span key={model.id} className={model.effective ? "effective" : ""}>
                  {model.id} · {model.context ? `${Math.round(model.context / 1000)}k` : "ctx?"}
                  {model.reasoning_capable ? ` · ${model.reasoning_control || "reasoning"}` : ""}
                </span>
              ))}
            </div>
            {testFacts[provider.id] ? <div className="v2-provider-test-fact">{testFacts[provider.id]}</div> : null}
            <div className="v2-provider-card-actions">
              <button type="button" className="v2-btn ghost" disabled={Boolean(busy)} onClick={() => { setEditor(providerToInput(provider)); setEditingId(provider.id); setApiKey(""); }}>
                编辑
              </button>
              <button type="button" className="v2-btn ghost" disabled={!provider.effective || Boolean(busy)} title="会发起一次最多 8 token 的真实无工具模型请求" onClick={() => void test(provider)}>
                {busy === `test:${provider.id}` ? "测试中…" : "测试连接"}
              </button>
              <button type="button" className="v2-btn ghost" disabled={!snapshot.mutable || Boolean(busy)} onClick={() => void toggleProvider(provider)}>
                {provider.enabled ? "停用" : "启用"}
              </button>
              {provider.credential_configured && provider.credential_source === "dotenv" ? (
                <button type="button" className="v2-btn ghost" disabled={Boolean(busy)} onClick={() => void clearCredential(provider.id)}>清除 Key</button>
              ) : null}
              <button type="button" className="v2-btn danger" disabled={!snapshot.mutable || Boolean(busy)} onClick={() => void removeProvider(provider)}>删除</button>
            </div>
          </article>
        ))}
        {snapshot.providers.length === 0 ? <div className="v2-placeholder">当前没有 Provider。可从 Web 添加云端或本地 OpenAI-compatible 端点。</div> : null}
      </div>

      {editor ? (
        <ProviderEditor
          value={editor}
          existing={editingId !== null}
          apiKey={apiKey}
          onApiKey={setApiKey}
          onChange={setEditor}
          onCancel={() => { setEditor(null); setEditingId(null); setApiKey(""); }}
          onSave={() => void saveEditor()}
          saving={busy === "save"}
        />
      ) : null}
    </div>
  );
}

function ProviderEditor({
  value,
  existing,
  apiKey,
  onApiKey,
  onChange,
  onCancel,
  onSave,
  saving,
}: {
  value: ProviderAdminInput;
  existing: boolean;
  apiKey: string;
  onApiKey: (value: string) => void;
  onChange: (value: ProviderAdminInput) => void;
  onCancel: () => void;
  onSave: () => void;
  saving: boolean;
}) {
  const patch = (next: Partial<ProviderAdminInput>) => onChange({ ...value, ...next });
  const patchModel = (index: number, next: Partial<ProviderModelAdminInput>) => {
    const models = value.models.map((model, i) => i === index ? { ...model, ...next } : model);
    const defaultModel = value.default_model && value.models[index]?.id === value.default_model && next.id
      ? String(next.id)
      : value.default_model;
    onChange({ ...value, models, default_model: defaultModel });
  };
  const removeModel = (index: number) => {
    const removed = value.models[index];
    const models = value.models.filter((_, i) => i !== index);
    onChange({
      ...value,
      models,
      default_model: removed?.id === value.default_model ? (models[0]?.id ?? "") : value.default_model,
    });
  };

  return (
    <div className="v2-provider-editor" data-testid="provider-editor">
      <div className="v2-provider-editor-head">
        <strong>{existing ? `编辑 ${value.id}` : "添加 Provider"}</strong>
        <button type="button" className="v2-icon-btn" aria-label="关闭 Provider 编辑器" onClick={onCancel}>×</button>
      </div>
      <div className="v2-provider-fields">
        <label>Provider ID<input value={value.id} disabled={existing} onChange={(e) => patch({ id: e.target.value })} placeholder="glm / minimax / local" /></label>
        <label>Base URL<input value={value.base_url} onChange={(e) => patch({ base_url: e.target.value })} placeholder="https://api.example.com/v1" /></label>
        <label>API Key 环境变量<input value={value.api_key_env ?? ""} onChange={(e) => patch({ api_key_env: e.target.value })} placeholder="留空且填写 Key 时自动生成" /></label>
        <label>API Key<input type="password" autoComplete="new-password" value={apiKey} onChange={(e) => onApiKey(e.target.value)} placeholder={existing ? "留空保持现有 Key" : "可选；仅写入本机 .env"} /></label>
        <label>Provider 默认模型
          <select value={value.default_model ?? ""} onChange={(e) => patch({ default_model: e.target.value })}>
            <option value="">选择默认模型</option>
            {value.models.map((model) => <option value={model.id} key={`${model.id}-${model.context}`}>{model.id || "(未命名模型)"}</option>)}
          </select>
        </label>
        <label>超时(s)<input type="number" min="1" value={value.timeout_s ?? ""} onChange={(e) => patch({ timeout_s: num(e.target.value) })} /></label>
        <label>Provider 最大输入 token<input type="number" min="1" value={value.max_input_tokens ?? ""} onChange={(e) => patch({ max_input_tokens: num(e.target.value) })} /></label>
        <label>Provider 最大输出 token<input type="number" min="1" value={value.max_tokens ?? ""} onChange={(e) => patch({ max_tokens: num(e.target.value) })} /></label>
        <label className="v2-check"><input type="checkbox" checked={value.enabled} onChange={(e) => patch({ enabled: e.target.checked })} />启用 Provider</label>
      </div>

      <div className="v2-provider-model-editor-list">
        <div className="v2-provider-subhead"><strong>模型</strong><button type="button" className="v2-btn ghost" onClick={() => patch({ models: [...value.models, blankModel()] })}>+ 添加模型</button></div>
        {value.models.map((model, index) => (
          <div className="v2-provider-model-editor" key={`${index}-${model.id}`}>
            <div className="v2-provider-model-grid">
              <label>Model ID<input value={model.id} onChange={(e) => patchModel(index, { id: e.target.value })} /></label>
              <label>Context<input type="number" min="1024" value={model.context ?? 131072} onChange={(e) => patchModel(index, { context: num(e.target.value) ?? 131072 })} /></label>
              <label>最大输入<input type="number" min="1" value={model.max_input_tokens ?? ""} onChange={(e) => patchModel(index, { max_input_tokens: num(e.target.value) })} /></label>
              <label>最大输出<input type="number" min="1" value={model.max_tokens ?? ""} onChange={(e) => patchModel(index, { max_tokens: num(e.target.value) })} /></label>
              <label>协议<select value={model.wire_protocol ?? "openai"} onChange={(e) => patchModel(index, { wire_protocol: e.target.value })}><option value="openai">OpenAI</option><option value="anthropic">Anthropic</option><option value="google">Google</option><option value="lms-chat">LM Studio Chat</option></select></label>
              <label>推理控制<select value={model.reasoning_control ?? "unknown"} onChange={(e) => patchModel(index, { reasoning_control: e.target.value })}><option value="unknown">未验证/unknown</option><option value="none">无显式控制</option><option value="thinking_type">thinking_type</option><option value="chat_template">chat_template</option><option value="always_on_effort">always_on_effort</option><option value="legacy">legacy</option></select></label>
              <label>Reasoning replay<select value={model.reasoning_replay ?? "configured"} onChange={(e) => patchModel(index, { reasoning_replay: e.target.value })}><option value="configured">configured</option><option value="none">none</option><option value="tool_calls">tool_calls</option><option value="full">full</option></select></label>
              <label>Cost tier<input value={model.cost_tier ?? "mid"} onChange={(e) => patchModel(index, { cost_tier: e.target.value })} /></label>
            </div>
            <div className="v2-provider-model-flags">
              <label><input type="checkbox" checked={model.enabled !== false} onChange={(e) => patchModel(index, { enabled: e.target.checked })} />启用</label>
              <label><input type="checkbox" checked={Boolean(model.reasoning_capable)} onChange={(e) => patchModel(index, { reasoning_capable: e.target.checked })} />可产生 Reasoning</label>
              <label><input type="checkbox" checked={Boolean(model.multimodal)} onChange={(e) => patchModel(index, { multimodal: e.target.checked })} />多模态</label>
              <label><input type="checkbox" checked={model.send_tool_choice !== false} onChange={(e) => patchModel(index, { send_tool_choice: e.target.checked })} />发送 tool_choice</label>
              <label><input type="checkbox" checked={Boolean(model.reasoning_split)} onChange={(e) => patchModel(index, { reasoning_split: e.target.checked })} />reasoning_split</label>
              <button type="button" className="v2-btn danger" disabled={value.models.length <= 1} onClick={() => removeModel(index)}>删除模型</button>
            </div>
          </div>
        ))}
      </div>
      <div className="v2-provider-editor-actions">
        <button type="button" className="v2-btn ghost" onClick={onCancel}>取消</button>
        <button type="button" className="v2-btn" disabled={saving || !value.id || !value.base_url || value.models.some((m) => !m.id)} onClick={onSave}>{saving ? "保存中…" : "保存并热重载"}</button>
      </div>
      <div className="v2-provider-footnote">能力字段是配置事实，不等于真实 qualification；“会推理”和“支持显式推理开关”分开记录。</div>
    </div>
  );
}
