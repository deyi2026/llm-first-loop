import { useCallback, useEffect, useMemo, useState } from "react";
import { LocalRuntimePanel } from "./LocalRuntimePanel";
import { VideoPanel } from "./VideoPanel";
import { providerAdminZh as T } from "../../i18n/zh";
import {
  addProviderModel,
  createProvider,
  deleteProviderConfig,
  deleteProviderModel,
  discoverProviderModels,
  fetchProviderAdmin,
  patchProvider,
  reloadProviderRegistry,
  replaceProvider,
  replaceProviderModel,
  setConfiguredDefaultModel,
  subscribeProvidersUpdated,
  testProviderConnection,
  toModelConfig,
  toProviderConfig,
  updateProviderCredential,
  type DiscoveredModel,
  type ProviderAdminFact,
  type ProviderAdminSnapshot,
  type ProviderModelAdminFact,
  type ProviderConfigInput,
  type ProviderModelConfigInput,
} from "../../core/api";
import { notifyModelCatalogChanged } from "../../core/chat";

/** 错误码 → 可操作文案（§6.1.4/§7.7）：服务端 detail 优先，码兜底。 */
function errorLabel(code?: string, raw?: string): string {
  const known = code ? T.errors[code] : "";
  return raw || known || T.errors.unknown;
}

function blankModel(): ProviderModelConfigInput {
  return {
    id: "",
    name: "",
    enabled: true,
    context: 131072,
    max_input_tokens: null,
    max_tokens: null,
    cost_tier: "mid",
    capability_tier: "unknown",
    input_modalities: ["text"],
    multimodal: false,
    wire_protocol: "openai",
    thinking: false,
    reasoning: false,
    long_context: false,
    reasoning_capable: false,
    reasoning_control: "unknown",
    reasoning_efforts: [],
    reasoning_effort_map: {},
    reasoning_default_effort: null,
    reasoning_replay: "configured",
    send_tool_choice: true,
    reasoning_split: false,
    runtime_identity: "",
    temperature: null,
    top_p: null,
    top_k: null,
    min_p: null,
    note: "",
  };
}

function blankProvider(): ProviderConfigInput {
  return {
    id: "",
    display_name: "",
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
  };
}

function num(value: string): number | null {
  if (value.trim() === "") return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function configuredModelIds(snapshot: ProviderAdminSnapshot | null, providerId: string): Set<string> {
  return new Set(snapshot?.providers.find((provider) => provider.id === providerId)?.models.map((model) => model.id) ?? []);
}

function text(value: number | null | undefined): string {
  return value === null || value === undefined ? "" : String(value);
}

interface ModelFormProps {
  draft: ProviderModelConfigInput;
  isNew: boolean;
  onChange: (next: ProviderModelConfigInput) => void;
}

/** Presets are editable examples, not an assertion of account entitlement or model availability. */
const PROVIDER_PRESETS = [
  { id: "custom", label: "自定义 / OpenAI 兼容", providerId: "", name: "", url: "https://", keyEnv: "" },
  { id: "deepseek", label: "DeepSeek", providerId: "deepseek", name: "DeepSeek", url: "https://api.deepseek.com/v1", keyEnv: "DEEPSEEK_API_KEY" },
  { id: "glm", label: "智谱 GLM（Coding）", providerId: "glm", name: "智谱 GLM", url: "https://open.bigmodel.cn/api/coding/paas/v4", keyEnv: "GLM_API_KEY" },
  { id: "minimax", label: "MiniMax", providerId: "minimax", name: "MiniMax", url: "https://api.minimax.chat/v1", keyEnv: "MINIMAX_API_KEY" },
  { id: "qwen", label: "阿里云百炼 / Qwen", providerId: "qwen", name: "Qwen", url: "https://dashscope.aliyuncs.com/compatible-mode/v1", keyEnv: "DASHSCOPE_API_KEY" },
  { id: "openai", label: "OpenAI API", providerId: "openai", name: "OpenAI", url: "https://api.openai.com/v1", keyEnv: "OPENAI_API_KEY" },
] as const;

function ModelFields({ draft, isNew, onChange }: ModelFormProps) {
  return (
    <div className="v2-provider-model-form">
      <div className="v2-provider-model-grid">
        <label>
          {T.modelId}
          <input
            value={draft.id}
            placeholder="例如：model-name"
            readOnly={!isNew}
            aria-readonly={!isNew}
            onChange={(event) => onChange({ ...draft, id: event.target.value.trim() })}
          />
        </label>
        <label>
          {T.modelName}
          <input
            value={draft.name ?? ""}
            placeholder="可选；留空使用 Model ID"
            onChange={(event) => onChange({ ...draft, name: event.target.value })}
          />
        </label>
        <label>
          {T.context}
          <input
            type="number"
            min={1024}
            value={text(draft.context)}
            onChange={(event) => onChange({ ...draft, context: num(event.target.value) ?? 0 })}
          />
        </label>
      </div>
      {isNew ? <p className="v2-provider-footnote">上下文默认值仅为初始配置，请以服务商实际支持范围为准。</p> : null}
      <details className="v2-provider-advanced v2-provider-model-advanced">
        <summary>高级模型参数 <span>输出、协议、推理能力与备注</span></summary>
        <div className="v2-provider-model-grid">
          <label>
            {T.maxTokens}
            <input
              type="number"
              min={1}
              value={text(draft.max_tokens)}
              placeholder="使用服务商默认"
              onChange={(event) => onChange({ ...draft, max_tokens: num(event.target.value) })}
            />
          </label>
          <label>
            {T.maxInputTokens}
            <input
              type="number"
              min={1}
              value={text(draft.max_input_tokens)}
              placeholder="使用服务商默认"
              onChange={(event) => onChange({ ...draft, max_input_tokens: num(event.target.value) })}
            />
          </label>
          <label>
            {T.wireProtocol}
            <select
              value={draft.wire_protocol ?? "openai"}
              onChange={(event) => onChange({ ...draft, wire_protocol: event.target.value })}
            >
              <option value="openai">OpenAI 兼容</option>
              <option value="anthropic">Anthropic</option>
              <option value="google">Google</option>
              <option value="lms-chat">LMS Chat</option>
            </select>
          </label>
          <label className="v2-provider-check">
            <input
              type="checkbox"
              checked={Boolean(draft.long_context)}
              onChange={(event) => onChange({ ...draft, long_context: event.target.checked })}
            />
            {T.longContext}
          </label>
          <label className="v2-provider-check">
            <input
              type="checkbox"
              checked={Boolean(draft.reasoning)}
              onChange={(event) => onChange({ ...draft, reasoning: event.target.checked })}
            />
            {T.reasoningField}
          </label>
          <label>
            {T.reasoning}
            <select
              value={draft.reasoning_capable ? "on" : "off"}
              onChange={(event) =>
                onChange({
                  ...draft,
                  reasoning_capable: event.target.value === "on",
                  reasoning_control: event.target.value === "on" ? draft.reasoning_control ?? "unknown" : "unknown",
                })
              }
            >
              <option value="off">未声明</option>
              <option value="on">支持</option>
            </select>
          </label>
          <label>
            推理控制协议
            <select
              value={draft.reasoning_control ?? "unknown"}
              onChange={(event) => onChange({ ...draft, reasoning_control: event.target.value })}
            >
              <option value="unknown">未确认（默认）</option>
              <option value="none">不支持</option>
              <option value="legacy">Legacy</option>
              <option value="thinking_type">thinking_type</option>
              <option value="chat_template">chat_template</option>
              <option value="always_on_effort">always_on_effort</option>
            </select>
          </label>
          <label className="v2-provider-check">
            <input
              type="checkbox"
              checked={Boolean(draft.input_modalities?.includes("image") ?? draft.multimodal)}
              onChange={(event) => onChange({
                ...draft,
                multimodal: event.target.checked,
                input_modalities: event.target.checked ? ["text", "image"] : ["text"],
              })}
            />
            支持图片输入
          </label>
          <label>
            {T.reasoningEfforts}
            <input
              value={(draft.reasoning_efforts ?? []).join(",")}
              placeholder="例如 low,high,max"
              onChange={(event) =>
                onChange({
                  ...draft,
                  reasoning_efforts: event.target.value.split(",").map((item) => item.trim()).filter(Boolean),
                })
              }
            />
          </label>
          <label>
            {T.reasoningDefault}
            <input
              value={draft.reasoning_default_effort ?? ""}
              placeholder="需属于上方档位"
              onChange={(event) =>
                onChange({ ...draft, reasoning_default_effort: event.target.value.trim() || null })
              }
            />
          </label>
          <label>
            {T.note}
            <input
              value={draft.note ?? ""}
              onChange={(event) => onChange({ ...draft, note: event.target.value })}
            />
          </label>
        </div>
      </details>
    </div>
  );
}

export function ProviderManager({ onCatalogChanged }: { onCatalogChanged?: () => Promise<void> | void }) {
  const [snapshot, setSnapshot] = useState<ProviderAdminSnapshot | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState<{ message: string; conflict?: boolean } | null>(null);
  const [flash, setFlash] = useState("");
  const [tests, setTests] = useState<Record<string, string>>({});
  const [editor, setEditor] = useState<{
    mode: "create" | "edit";
    providerId?: string;
    draft: ProviderConfigInput;
    apiKey: string;
    presetId?: string;
    baseVersion?: string;
  } | null>(null);
  const [modelForm, setModelForm] = useState<{
    providerId: string;
    mode: "add" | "edit";
    originalId?: string;
    baseVersion?: string;
    draft: ProviderModelConfigInput;
  } | null>(null);
  const [credentialEditor, setCredentialEditor] = useState<{ providerId: string; apiKey: string } | null>(null);
  const [search, setSearch] = useState("");
  const [expandedProviderIds, setExpandedProviderIds] = useState<string[] | null>(null);
  const [discoverySearch, setDiscoverySearch] = useState("");
  const [showExtraTools, setShowExtraTools] = useState(false);
  const [discovery, setDiscovery] = useState<{
    providerId: string;
    candidates: DiscoveredModel[];
    selected: string[];
    error?: string;
    needsRefresh?: boolean;
    uncertainId?: string;
  } | null>(null);

  const load = useCallback(async (clearError = false): Promise<boolean> => {
    try {
      const next = await fetchProviderAdmin();
      if (next) {
        setSnapshot(next);
        if (clearError) setError(null);
        return true;
      }
    } catch {
      // Keep the previous snapshot and any unsaved editor input intact.
    } finally {
      setLoading(false);
    }
    setError({ message: T.errors.load });
    return false;
  }, []);

  useEffect(() => {
    void load(true);
  }, [load]);

  useEffect(() => subscribeProvidersUpdated(() => void load()), [load]);

  const readOnly = !snapshot?.mutable;
  const def = snapshot?.default;
  const defaultModel = def?.model ?? snapshot?.configured_default_model ?? "";
  const runtimeModel = def?.runtime_model ?? snapshot?.runtime_default_model ?? "";
  const restartRequired = Boolean(def ? def.restart_required : snapshot?.restart_required);
  const runtimeApplied = def?.applied ?? (defaultModel && runtimeModel
    ? defaultModel === runtimeModel && !restartRequired
    : null);
  const runtimeStatus = restartRequired ? T.restartRequired
    : runtimeApplied === true ? T.applied
      : runtimeApplied === false ? "尚未生效" : "运行状态未确认";

  const modelOptions = useMemo(() => {
    const options: { value: string; label: string }[] = [];
    for (const provider of snapshot?.providers ?? []) {
      if (provider.enabled === false) continue;
      for (const model of provider.models) {
        if (model.enabled === false) continue;
        options.push({
          value: `${provider.id}/${model.id}`,
          label: `${provider.display_name || provider.id} · ${model.name || model.id}`,
        });
      }
    }
    return options;
  }, [snapshot]);

  const searchTerm = search.trim().toLocaleLowerCase();
  const visibleProviders = useMemo(() => {
    const defaultProvider = defaultModel.split("/")[0];
    return (snapshot?.providers ?? []).filter((provider) => {
      if (!searchTerm) return true;
      return [provider.id, provider.display_name, provider.base_url, ...provider.models.flatMap((model) => [model.id, model.name])]
        .some((value) => (value ?? "").toLocaleLowerCase().includes(searchTerm));
    }).sort((a, b) =>
      a.id === defaultProvider ? -1 : b.id === defaultProvider ? 1 :
        (a.display_name || a.id).localeCompare(b.display_name || b.id, "zh-CN")
    );
  }, [snapshot, searchTerm, defaultModel]);

  const providerIsExpanded = (providerId: string) =>
    Boolean(searchTerm) || (
      expandedProviderIds === null
        ? providerId === defaultModel.split("/")[0]
        : expandedProviderIds.includes(providerId)
    );
  const toggleExpandedProvider = (providerId: string) => {
    setExpandedProviderIds((prev) => {
      const current = prev ?? (defaultModel ? [defaultModel.split("/")[0]] : []);
      return current.includes(providerId)
        ? current.filter((id) => id !== providerId)
        : [...current, providerId];
    });
  };

  const runMutation = useCallback(
    async (key: string, action: () => Promise<Awaited<ReturnType<typeof patchProvider>>>, success: string) => {
      setBusy(key);
      setError(null);
      setFlash("");
      try {
        const result = await action();
        if (!result.ok) {
          setError({
            message: errorLabel(result.error, result.detail),
            conflict: result.status === 409 || result.error === "provider_config_conflict",
          });
          return false;
        }
        if (result.snapshot) setSnapshot(result.snapshot);
        else if (!(await load())) {
          // A 2xx write without a verifiable readback must not claim success.
          setError({ message: "服务器已接受操作，但无法确认最新配置。请先刷新核验，不要重复提交。" });
          return false;
        }
        setFlash(result.detail || success);
        notifyModelCatalogChanged();
        void onCatalogChanged?.();
        return true;
      } catch (err) {
        setError({ message: err instanceof Error ? err.message : T.errors.unknown });
        return false;
      } finally {
        setBusy("");
      }
    },
    [load, onCatalogChanged]
  );

  const setDefault = async (value: string) => {
    if (!value) return;
    await runMutation("default", () => setConfiguredDefaultModel(value), T.applied);
  };

  const toggleProvider = async (provider: ProviderAdminFact) => {
    if (!snapshot) return;
    await runMutation(
      `provider:${provider.id}`,
      () => patchProvider(provider.id, snapshot.config_version, { enabled: provider.enabled === false }),
      T.saved
    );
  };

  const setProviderDefault = async (provider: ProviderAdminFact, value: string) => {
    if (!snapshot) return;
    await runMutation(
      `provider:${provider.id}`,
      () => patchProvider(provider.id, snapshot.config_version, { default_model: value }),
      T.saved
    );
  };

  const toggleModel = async (provider: ProviderAdminFact, model: ProviderModelAdminFact) => {
    if (!snapshot) return;
    await runMutation(
      `model:${provider.id}/${model.id}`,
      () =>
        replaceProviderModel(
          provider.id,
          model.id,
          snapshot.config_version,
          toModelConfig({ ...model, enabled: model.enabled === false })
        ),
      T.saved
    );
  };

  const removeModel = async (provider: ProviderAdminFact, model: ProviderModelAdminFact) => {
    if (!snapshot) return;
    if (!window.confirm(T.removeModelConfirm.replace("{model}", model.id))) return;
    await runMutation(
      `model:${provider.id}/${model.id}`,
      () => deleteProviderModel(provider.id, model.id, snapshot.config_version),
      T.saved
    );
  };

  const removeProvider = async (provider: ProviderAdminFact) => {
    if (!snapshot) return;
    if (!window.confirm(T.removeProviderConfirm)) return;
    await runMutation(
      `provider:${provider.id}`,
      () => deleteProviderConfig(provider.id, snapshot.config_version),
      T.saved
    );
  };

  const clearCredential = async (provider: ProviderAdminFact) => {
    if (!window.confirm(T.clearKeyConfirm.replace("{provider}", provider.id))) return;
    await runMutation(
      `credential:${provider.id}`,
      () => updateProviderCredential(provider.id, ""),
      T.cleared
    );
  };

  const runTest = async (provider: ProviderAdminFact, modelId: string) => {
    const key = `${provider.id}/${modelId}`;
    setBusy(`test:${key}`);
    try {
      const result = await testProviderConnection(provider.id, modelId);
      setTests((prev) => ({ ...prev, [key]: result.detail }));
    } catch {
      setTests((prev) => ({ ...prev, [key]: "连接测试失败，请稍后重试。" }));
    } finally {
      setBusy("");
    }
  };

  const openCreate = () => {
    setError(null);
    setCredentialEditor(null);
    setEditor({ mode: "create", draft: blankProvider(), apiKey: "", presetId: "custom" });
    setModelForm(null);
    setDiscovery(null);
  };

  const openEdit = (provider: ProviderAdminFact) => {
    setError(null);
    setCredentialEditor(null);
    setEditor({
      mode: "edit",
      providerId: provider.id,
      baseVersion: snapshot?.config_version,
      draft: toProviderConfig(provider),
      apiKey: "",
    });
    setModelForm(null);
    setDiscovery(null);
  };

  const saveEditor = async () => {
    if (!snapshot || !editor) return;
    if (!/^[a-z][a-z0-9_-]{0,31}$/.test(editor.draft.id)) {
      setError({ message: "Provider ID 只能使用小写字母、数字、下划线和连字符，且必须以字母开头。" });
      return;
    }
    if (editor.mode === "create" && snapshot.providers.some((provider) => provider.id === editor.draft.id)) {
      setError({ message: "此服务商已存在，请在现有服务商卡片中添加模型。" });
      return;
    }
    if (!/^https?:\/\/[^/\s]+/.test(editor.draft.base_url)) {
      setError({ message: "请填写完整的 http(s) API 地址。" });
      return;
    }
    if (editor.mode === "create" && (
      editor.draft.models.some((model) => !model.id.trim()) ||
      new Set(editor.draft.models.map((model) => model.id)).size !== editor.draft.models.length
    )) {
      setError({ message: "请填写不重复的 Model ID，或删除未填写的模型项。" });
      return;
    }
    const ok = await runMutation(
      "editor",
      () =>
        editor.mode === "create"
          ? createProvider(snapshot.config_version, editor.draft, editor.apiKey)
          : replaceProvider(editor.baseVersion ?? snapshot.config_version, editor.draft),
      T.saved
    );
    if (!ok) return;
    setEditor(null);
  };

  const openCredential = (providerId: string) => {
    setError(null);
    setFlash("");
    setEditor(null);
    setModelForm(null);
    setDiscovery(null);
    setCredentialEditor({ providerId, apiKey: "" });
  };

  const saveCredential = async () => {
    if (!credentialEditor || !credentialEditor.apiKey.trim() || readOnly || busy) return;
    const providerId = credentialEditor.providerId;
    const ok = await runMutation(
      `credential:${providerId}`,
      () => updateProviderCredential(providerId, credentialEditor.apiKey.trim()),
      "API Key 已保存并生效"
    );
    if (ok) setCredentialEditor(null);
  };

  const saveModel = async () => {
    if (!snapshot || !modelForm) return;
    if (!modelForm.draft.id.trim()) {
      setError({ message: `${T.modelId} 不能为空` });
      return;
    }
    if (modelForm.mode === "add" && snapshot.providers.some((provider) =>
      provider.id === modelForm.providerId && provider.models.some((model) => model.id === modelForm.draft.id.trim())
    )) {
      setError({ message: "该模型已存在，请直接编辑现有模型。" });
      return;
    }
    const ok = await runMutation(
      "model-form",
      () =>
        modelForm.mode === "edit"
          ? replaceProviderModel(
              modelForm.providerId,
              modelForm.originalId ?? modelForm.draft.id,
              modelForm.baseVersion ?? snapshot.config_version,
              modelForm.draft
            )
          : addProviderModel(modelForm.providerId, snapshot.config_version, modelForm.draft),
      T.saved
    );
    if (ok) {
      setModelForm(null);
      setDiscovery(null);
    }
  };

  const discover = async () => {
    if (!snapshot || !modelForm) return;
    const provider = snapshot.providers.find((item) => item.id === modelForm.providerId);
    if (!provider) return;
    setBusy("discover");
    setDiscoverySearch("");
    setDiscovery({ providerId: provider.id, candidates: [], selected: [], error: undefined });
    try {
      const result = await discoverProviderModels({
        base_url: provider.base_url,
        wire_protocol: modelForm.draft.wire_protocol || "openai",
        provider_id: provider.id,
      });
      if (!result.ok) {
        setDiscovery({
          providerId: provider.id,
          candidates: [],
          selected: [],
          error: errorLabel(result.errorCode, T.errors.discovery_failed),
        });
        return;
      }
      setDiscovery({ providerId: provider.id, candidates: result.candidates, selected: [] });
    } catch {
      setDiscovery({ providerId: provider.id, candidates: [], selected: [], error: T.errors.discovery_failed });
    } finally {
      setBusy("");
    }
  };

  const addSelected = async () => {
    if (!snapshot || !discovery || !modelForm || discovery.needsRefresh || busy) return;
    const providerId = discovery.providerId;
    const pending = discovery.selected.filter((id) => !configuredModelIds(snapshot, providerId).has(id));
    if (!pending.length) return;
    let verifiedSnapshot = snapshot;
    let version = snapshot.config_version;
    let added = 0;
    let failure = "";
    let unverifiedId: string | null = null;
    let attemptedId: string | null = null;
    setBusy("discover-add");
    setError(null);
    try {
      for (const id of pending) {
        if (configuredModelIds(verifiedSnapshot, providerId).has(id)) continue;
        const candidate = discovery.candidates.find((item) => item.id === id);
        attemptedId = id;
        const result = await addProviderModel(providerId, version, {
          ...blankModel(),
          id,
          name: candidate?.name || id,
          context: candidate?.context_window ?? 131072,
          max_tokens: candidate?.max_output_tokens ?? null,
          wire_protocol: modelForm.draft.wire_protocol || "openai",
          note: "",
        });
        if (!result.ok) {
          // A definite 4xx rejection is safe to reconcile and retry; 5xx/unknown
          // may have committed before the response was lost.
          if (result.status < 400 || result.status >= 500) unverifiedId = id;
          failure = errorLabel(result.error, result.detail);
          break;
        }
        const verified = result.snapshot ?? await fetchProviderAdmin();
        if (!verified || !configuredModelIds(verified, providerId).has(id)) {
          unverifiedId = id;
          failure = "服务端已接受添加，但最新配置尚未确认；请刷新核对，避免重复提交。";
          break;
        }
        verifiedSnapshot = verified;
        setSnapshot(verified);
        version = verified.config_version;
        added += 1;
        const known = configuredModelIds(verified, providerId);
        setDiscovery((prev) => prev?.providerId === providerId
          ? { ...prev, selected: prev.selected.filter((item) => !known.has(item)) }
          : prev);
      }
    } catch {
      unverifiedId = attemptedId;
      failure = "模型添加结果未确认，请刷新核对，避免重复提交。";
    }
    if (added > 0) {
      notifyModelCatalogChanged();
      void onCatalogChanged?.();
    }
    if (failure) {
      let latest: ProviderAdminSnapshot | null = null;
      try {
        latest = await fetchProviderAdmin();
      } catch {
        // A failed readback must never make an accepted write safe to replay.
      }
      if (latest) {
        setSnapshot(latest);
        const known = configuredModelIds(latest, providerId);
        const needsRefresh = unverifiedId !== null && !known.has(unverifiedId);
        setDiscovery((prev) => prev?.providerId === providerId
          ? { ...prev, selected: prev.selected.filter((id) => !known.has(id)), needsRefresh,
              uncertainId: needsRefresh ? unverifiedId ?? undefined : undefined }
          : prev);
      } else {
        setDiscovery((prev) => prev?.providerId === providerId
          ? { ...prev, needsRefresh: true, uncertainId: unverifiedId ?? undefined } : prev);
      }
      setError({ message: added > 0 ? `已添加 ${added} 个模型，其余未完成：${failure}` : failure });
      setBusy("");
      return;
    }
    setBusy("");
    setFlash(`已添加 ${added} 个模型`);
    setDiscovery(null);
    setModelForm(null);
  };

  const refreshDiscovery = async () => {
    if (!discovery || busy) return;
    const providerId = discovery.providerId;
    setBusy("discover-refresh");
    try {
      const latest = await fetchProviderAdmin();
      if (!latest) {
        setError({ message: "配置读取失败，暂不能安全重试添加；请稍后刷新核对。" });
        return;
      }
      setSnapshot(latest);
      const known = configuredModelIds(latest, providerId);
      const unresolved = discovery.uncertainId && !known.has(discovery.uncertainId);
      setDiscovery((prev) => prev?.providerId === providerId
        ? { ...prev, selected: prev.selected.filter((id) => !known.has(id)),
            needsRefresh: Boolean(unresolved), uncertainId: unresolved ? discovery.uncertainId : undefined }
        : prev);
      setError(unresolved ? { message: "上次提交仍未确认；暂不自动重试该模型，避免重复写入。" } : null);
    } catch {
      setError({ message: "配置读取失败，暂不能安全重试添加；请稍后刷新核对。" });
    } finally {
      setBusy("");
    }
  };

  const providerEditor = editor ? (
    <section className="v2-provider-editor" data-testid="provider-editor" aria-label={editor.mode === "create" ? T.addProvider : T.edit}>
      <div className="v2-provider-editor-head">
        <div>
          <strong>{editor.mode === "create" ? "接入新服务商" : `服务商设置 · ${editor.providerId}`}</strong>
          <p className="v2-provider-footnote">{editor.mode === "create"
            ? "选择模板后填写模型 ID 与 API Key；端点和参数均可修改。"
            : "只修改需要的字段；留空 API Key 不会清除原有凭证。"}</p>
        </div>
        <button type="button" className="v2-provider-icon-button" onClick={() => setEditor(null)} aria-label="关闭服务商编辑">×</button>
      </div>
      {editor.mode === "create" ? (
        <label className="v2-provider-preset">
          服务商模板
          <select
            value={editor.presetId ?? "custom"}
            onChange={(event) => {
              const preset = PROVIDER_PRESETS.find((item) => item.id === event.target.value) ?? PROVIDER_PRESETS[0];
              setEditor({
                ...editor,
                presetId: preset.id,
                apiKey: "",
                draft: {
                  ...blankProvider(),
                  id: preset.providerId,
                  display_name: preset.name,
                  base_url: preset.url,
                  api_key_env: preset.keyEnv,
                },
              });
            }}
          >
            {PROVIDER_PRESETS.map((preset) => (
              <option key={preset.id} value={preset.id}>{preset.label}</option>
            ))}
          </select>
        </label>
      ) : null}
      {editor.mode === "create" && snapshot?.providers.some((provider) => provider.id === editor.draft.id && editor.draft.id) ? (
        <div className="v2-provider-warning" role="status">
          此服务商已存在，无需重复配置 API Key。
          <button type="button" onClick={() => {
            setSearch(editor.draft.id);
            setExpandedProviderIds([editor.draft.id]);
            setEditor(null);
          }}>查看现有服务商并添加模型</button>
        </div>
      ) : null}
      <div className="v2-provider-fields">
        <label>
          {T.providerId}
          <input
            value={editor.draft.id}
            placeholder="例如：custom"
            readOnly={editor.mode === "edit"}
            onChange={(event) => setEditor({ ...editor, draft: { ...editor.draft, id: event.target.value.trim().toLowerCase() } })}
          />
        </label>
        <label>
          {T.displayName}
          <input
            value={editor.draft.display_name ?? ""}
            placeholder="显示名称（可选）"
            onChange={(event) => setEditor({ ...editor, draft: { ...editor.draft, display_name: event.target.value } })}
          />
        </label>
        <label className="v2-provider-field-wide">
          {T.baseUrl}
          <input
            value={editor.draft.base_url}
            placeholder="https://api.example.com/v1"
            autoComplete="url"
            onChange={(event) => setEditor({ ...editor, draft: { ...editor.draft, base_url: event.target.value } })}
          />
        </label>
        {editor.mode === "create" ? (
          <label className="v2-provider-field-wide">
            {T.apiKey}
            <input
              type="password"
              value={editor.apiKey}
              autoComplete="new-password"
              placeholder="输入后安全保存；不会在页面回显"
              onChange={(event) => setEditor({ ...editor, apiKey: event.target.value })}
            />
          </label>
        ) : null}
      </div>
      {editor.mode === "create" ? (
        <div className="v2-provider-setup-step">
          <strong>模型信息</strong>
          <span className="v2-provider-footnote">至少填写一个 Model ID；可稍后再添加其他模型。</span>
          <div className="v2-provider-model-editor-list">
            {editor.draft.models.map((model, index) => (
              <div className="v2-provider-model-editor" key={index}>
                <ModelFields
                  draft={model}
                  isNew
                  onChange={(next) => {
                    const models = editor.draft.models.map((item, i) => (i === index ? next : item));
                    setEditor({
                      ...editor,
                      draft: {
                        ...editor.draft,
                        models,
                        default_model: !editor.draft.default_model || editor.draft.default_model === model.id
                          ? next.id
                          : editor.draft.default_model,
                      },
                    });
                  }}
                />
                {editor.draft.models.length > 1 ? (
                  <button
                    type="button"
                    className="v2-provider-text-danger"
                    onClick={() => setEditor({
                      ...editor,
                      draft: {
                        ...editor.draft,
                        models: editor.draft.models.filter((_, i) => i !== index),
                        default_model: editor.draft.default_model === model.id ? "" : editor.draft.default_model,
                      },
                    })}
                  >{T.remove}</button>
                ) : null}
              </div>
            ))}
          </div>
          <button type="button" className="v2-provider-add-another" onClick={() =>
            setEditor({ ...editor, draft: { ...editor.draft, models: [...editor.draft.models, blankModel()] } })
          }>{T.addModel}</button>
        </div>
      ) : null}
      <details className="v2-provider-advanced">
        <summary>{T.advanced} <span>凭证变量、超时与预算</span></summary>
        <div className="v2-provider-fields">
          <label>
            {T.apiKeyEnv}
            <input
              value={editor.draft.api_key_env ?? ""}
              placeholder="例如：CUSTOM_API_KEY"
              onChange={(event) => setEditor({ ...editor, draft: { ...editor.draft, api_key_env: event.target.value } })}
            />
          </label>
          <label>
            {T.providerDefault}
            <select
              value={editor.draft.default_model ?? ""}
              onChange={(event) => setEditor({ ...editor, draft: { ...editor.draft, default_model: event.target.value } })}
            >
              <option value="">未指定</option>
              {editor.draft.models.filter((model) => model.id).map((model) => (
                <option key={model.id} value={model.id}>{model.name || model.id}</option>
              ))}
            </select>
          </label>
          <label>
            {T.timeout}
            <input type="number" min={1} value={text(editor.draft.timeout_s)}
              onChange={(event) => setEditor({ ...editor, draft: { ...editor.draft, timeout_s: num(event.target.value) } })} />
          </label>
          <label>
            {T.maxTokens}
            <input type="number" min={1} value={text(editor.draft.max_tokens)}
              onChange={(event) => setEditor({ ...editor, draft: { ...editor.draft, max_tokens: num(event.target.value) } })} />
          </label>
          <label>
            {T.maxInputTokens}
            <input type="number" min={1} value={text(editor.draft.max_input_tokens)}
              onChange={(event) => setEditor({ ...editor, draft: { ...editor.draft, max_input_tokens: num(event.target.value) } })} />
          </label>
          <label>
            {T.historyBudget}
            <input type="number" min={1000} value={text(editor.draft.history_budget_chars)}
              onChange={(event) => setEditor({ ...editor, draft: { ...editor.draft, history_budget_chars: num(event.target.value) } })} />
          </label>
          <label>
            {T.charsPerToken}
            <input type="number" step="0.1" value={text(editor.draft.chars_per_token)}
              onChange={(event) => setEditor({ ...editor, draft: { ...editor.draft, chars_per_token: num(event.target.value) } })} />
          </label>
        </div>
        {editor.mode === "create" ? (
          <details className="v2-provider-advanced">
            <summary>{T.copyFrom}</summary>
            <label className="v2-provider-fields">
              从已有服务商复制模型和端点（不复制 API Key）
              <select value="" onChange={(event) => {
                const source = snapshot?.providers.find((item) => item.id === event.target.value);
                if (!source) return;
                setEditor({
                  ...editor,
                  presetId: "custom",
                  apiKey: "",
                  draft: {
                    ...toProviderConfig(source),
                    id: "",
                    display_name: `${source.display_name || source.id} 副本`,
                  },
                });
              }}>
                <option value="">选择服务商</option>
                {(snapshot?.providers ?? []).map((item) => (
                  <option key={item.id} value={item.id}>{item.display_name || item.id}</option>
                ))}
              </select>
            </label>
          </details>
        ) : (
          <details className="v2-provider-advanced">
            <summary>现有模型参数（{editor.draft.models.length}）</summary>
            <div className="v2-provider-model-editor-list">
              {editor.draft.models.map((model, index) => (
                <div className="v2-provider-model-editor" key={model.id}>
                  <ModelFields
                    draft={model}
                    isNew={false}
                    onChange={(next) => setEditor({
                      ...editor,
                      draft: {
                        ...editor.draft,
                        models: editor.draft.models.map((item, i) => i === index ? next : item),
                      },
                    })}
                  />
                </div>
              ))}
            </div>
          </details>
        )}
      </details>
      {error ? <p className="v2-provider-warning" role="alert">{error.message}</p> : null}
      <div className="v2-provider-editor-actions">
        <button type="button" className="v2-provider-primary" onClick={() => void saveEditor()} disabled={busy !== ""}>
          {busy === "editor" ? T.saving : T.saveAndApply}
        </button>
        <button type="button" onClick={() => setEditor(null)}>{T.cancel}</button>
      </div>
    </section>
  ) : null;

  const modelEditor = modelForm ? (
    <section className="v2-provider-editor" aria-label={modelForm.mode === "add" ? T.addModel : T.edit}>
      <div className="v2-provider-editor-head">
        <div>
          <strong>{modelForm.mode === "add" ? `添加模型 · ${modelForm.providerId}` : `编辑模型 · ${modelForm.originalId}`}</strong>
          <p className="v2-provider-footnote">填写 Model ID 即可保存；高级能力只在确认支持后声明。添加后可单独测试连接。</p>
        </div>
        <button type="button" className="v2-provider-icon-button" aria-label="关闭模型编辑" onClick={() => {
          setModelForm(null);
          setDiscovery(null);
        }}>×</button>
      </div>
      {modelForm.mode === "add" ? (
        <div className="v2-provider-discovery-bar">
          <span>不确定模型 ID？先从服务商获取列表。</span>
          <button type="button" onClick={() => void discover()} disabled={busy !== "" || Boolean(discovery?.needsRefresh)}>
            {busy === "discover" ? T.discovering : T.discover}
          </button>
        </div>
      ) : null}
      {discovery && discovery.providerId === modelForm.providerId ? (
        <div className="v2-provider-discovery-results">
          {discovery.error ? (
            <p className="v2-provider-warning" role="alert">{discovery.error}；仍可手动填写 Model ID。</p>
          ) : discovery.candidates.length === 0 ? (
            <p className="v2-provider-footnote">{T.discoverEmpty}；可手动填写 Model ID。</p>
          ) : (
            <>
              <label className="v2-provider-discovery-search">
                搜索发现的模型
                <input
                  value={discoverySearch}
                  onChange={(event) => setDiscoverySearch(event.target.value)}
                  placeholder="输入名称或 Model ID"
                />
              </label>
              <p className="v2-provider-footnote">
                发现 {discovery.candidates.length} 个候选；已有模型不可重复添加。勾选后批量保存。
              </p>
              {discovery.needsRefresh ? (
                <div className="v2-provider-warning" role="status">
                  上次写入结果尚未确认，请先刷新核对，避免重复提交。
                  <button type="button" onClick={() => void refreshDiscovery()} disabled={busy !== ""}>
                    {busy === "discover-refresh" ? T.loading : "刷新并核对"}
                  </button>
                </div>
              ) : null}
              <div className="v2-provider-discovery-list">
                {discovery.candidates
                  .filter((candidate) =>
                    [candidate.id, candidate.name].some((value) => (value ?? "").toLocaleLowerCase().includes(discoverySearch.trim().toLocaleLowerCase()))
                  )
                  .slice(0, 60)
                  .map((candidate) => {
                    const exists = snapshot?.providers.find((item) => item.id === modelForm.providerId)?.models
                      .some((model) => model.id === candidate.id) ?? false;
                    return (
                      <label key={candidate.id} className="v2-provider-discovery-option">
                        <input
                          type="checkbox"
                          disabled={exists || busy !== ""}
                          checked={!exists && discovery.selected.includes(candidate.id)}
                          onChange={(event) => setDiscovery((prev) => prev?.providerId === modelForm.providerId
                            ? {
                                ...prev,
                                selected: event.target.checked
                                  ? [...new Set([...prev.selected, candidate.id])]
                                  : prev.selected.filter((id) => id !== candidate.id),
                              }
                            : prev)}
                        />
                        <span><strong>{candidate.name || candidate.id}</strong><small>{candidate.id}</small></span>
                        {exists ? <span className="v2-provider-pill">已添加</span> : null}
                      </label>
                    );
                  })}
              </div>
              {discovery.candidates.filter((candidate) =>
                [candidate.id, candidate.name].some((value) => (value ?? "").toLocaleLowerCase().includes(discoverySearch.trim().toLocaleLowerCase()))
              ).length > 60 ? <p className="v2-provider-footnote">仅显示前 60 项，请缩小搜索范围。</p> : null}
              <button type="button" className="v2-provider-primary" onClick={() => void addSelected()}
                disabled={Boolean(discovery.needsRefresh) || discovery.selected.filter((id) =>
                  !configuredModelIds(snapshot, discovery.providerId).has(id)).length === 0 || busy !== ""}>
                {busy === "discover-add" ? T.saving : `添加所选（${discovery.selected.filter((id) =>
                  !configuredModelIds(snapshot, discovery.providerId).has(id)).length}）`}
              </button>
            </>
          )}
        </div>
      ) : null}
      <ModelFields
        draft={modelForm.draft}
        isNew={modelForm.mode === "add"}
        onChange={(next) => setModelForm({ ...modelForm, draft: next })}
      />
      {error ? <p className="v2-provider-warning" role="alert">{error.message}</p> : null}
      <div className="v2-provider-editor-actions">
        <button type="button" className="v2-provider-primary" onClick={() => void saveModel()}
          disabled={busy !== "" || Boolean(discovery?.needsRefresh && discovery.providerId === modelForm.providerId)}>
          {busy === "model-form" ? T.saving : T.save}
        </button>
        <button type="button" onClick={() => {
          setModelForm(null);
          setDiscovery(null);
        }}>{T.cancel}</button>
      </div>
    </section>
  ) : null;

  return (
    <section className="v2-provider-admin" aria-label="模型与服务商管理">
      <header className="v2-provider-page-head">
        <div>
          <h3>{T.title}</h3>
          <p className="v2-provider-subhead">快速接入模型，按服务商管理。配置与实际运行状态分别核验。</p>
        </div>
        <button type="button" className="v2-provider-primary" onClick={openCreate}
          disabled={readOnly || !snapshot || busy !== ""}>{T.addProvider}</button>
      </header>

      {error ? (
        <div className="v2-provider-warning" role="alert" aria-live="assertive">
          {error.message}
          {error.conflict ? ` ${T.conflictBanner}` : ""}
          {error.conflict ? <button type="button" onClick={() => void load()}>{T.refresh}</button> : null}
        </div>
      ) : null}
      {flash ? <p className="v2-provider-ok" role="status">{flash}</p> : null}
      {readOnly && snapshot ? <p className="v2-provider-readonly-note">{T.envReadonly}</p> : null}

      {snapshot ? (
        <div className="v2-provider-overview">
          <div className="v2-provider-overview-top">
            <label className="v2-provider-default-control">
              {T.defaultModel}
              <select value={defaultModel} onChange={(event) => void setDefault(event.target.value)}
                disabled={readOnly || busy !== ""}>
                {defaultModel && !modelOptions.some((option) => option.value === defaultModel) ? (
                  <option value={defaultModel}>{defaultModel}</option>
                ) : null}
                {modelOptions.map((option) => (
                  <option key={option.value} value={option.value}>{option.label}</option>
                ))}
              </select>
            </label>
            <span className={restartRequired || runtimeApplied === false ? "v2-provider-state is-warning" : "v2-provider-state"}>
              {runtimeStatus}
            </span>
          </div>
          <div className="v2-provider-overview-bottom">
            <span>{snapshot.providers.length} 个服务商 · {snapshot.providers.reduce((sum, item) => sum + item.models.length, 0)} 个模型</span>
            <details className="v2-provider-overview-details">
              <summary>配置与运行详情</summary>
              <div className="v2-provider-summary" data-testid="provider-summary">
                <div><span>{T.source}</span><strong>{snapshot.source}</strong></div>
                <div><span>{T.configDefault}</span><strong>{defaultModel || "—"}</strong></div>
                <div><span>{T.runtimeDefault}</span><strong>{runtimeModel || "—"}</strong></div>
                <div><span>{T.persistence}</span><strong>{def?.persistence ?? "—"}</strong></div>
              </div>
            </details>
          </div>
          {restartRequired ? <p className="v2-provider-warning">{T.restartHint}</p> : null}
          {snapshot.degraded ? <p className="v2-provider-warning">{T.degraded}</p> : null}
        </div>
      ) : null}

      {editor?.mode === "create" ? providerEditor : null}
      {loading ? <p>{T.loading}</p> : null}

      {snapshot ? (
        <div className="v2-provider-list-toolbar">
          <label className="v2-provider-search">
            搜索服务商或模型
            <input type="search" value={search} placeholder="名称 / Model ID / 地址"
              onChange={(event) => setSearch(event.target.value)} />
          </label>
          <div className="v2-provider-actions">
            <button type="button" onClick={() => void load()} disabled={loading || busy !== ""}>{T.refresh}</button>
            <details className="v2-provider-more">
              <summary>维护</summary>
              <div className="v2-provider-more-menu">
                <button type="button" onClick={() => void runMutation("reload", () => reloadProviderRegistry(), T.applied)}
                  disabled={readOnly || busy !== ""}>{T.reload}</button>
              </div>
            </details>
          </div>
        </div>
      ) : null}

      <div className="v2-provider-list">
        {visibleProviders.length === 0 && !loading ? (
          <p className="v2-provider-footnote">没有匹配的服务商或模型，请调整搜索词。</p>
        ) : null}
        {visibleProviders.map((provider) => {
          const expanded = providerIsExpanded(provider.id);
          const providerMatch = [provider.id, provider.display_name, provider.base_url]
            .some((value) => (value ?? "").toLocaleLowerCase().includes(searchTerm));
          const providerModels = !searchTerm || providerMatch
            ? provider.models
            : provider.models.filter((model) =>
              [model.id, model.name].some((value) => (value ?? "").toLocaleLowerCase().includes(searchTerm))
            );
          const defaultChoices = provider.models.filter((model) => model.enabled !== false);
          const localNoKey = !provider.api_key_env &&
            /^https?:\/\/(localhost|127\.0\.0\.1)(:|\/|$)/i.test(provider.base_url);
          return (
            <article className="v2-provider-card" key={provider.id} data-testid={`provider-${provider.id}`}>
              <div className="v2-provider-card-top">
                <div className="v2-provider-card-identity">
                  <button type="button" className="v2-provider-expand"
                    aria-expanded={expanded} aria-controls={`provider-models-${provider.id}`}
                    onClick={() => toggleExpandedProvider(provider.id)}>
                    <span aria-hidden="true">{expanded ? "▾" : "▸"}</span>
                    <strong>{provider.display_name || provider.id}</strong>
                  </button>
                  <div className="v2-provider-card-status">
                    <span className={provider.credential_configured ? "v2-provider-pill is-ready" : localNoKey ? "v2-provider-pill" : "v2-provider-pill is-warning"}>
                      {provider.credential_configured
                        ? `已配置 · ${provider.credential_source ?? "none"}`
                        : localNoKey ? "本地端点 · 无需 API Key" : "未配置 API Key"}
                    </span>
                    <span className="v2-provider-pill">{provider.models.length} 个模型</span>
                    {provider.enabled === false ? <span className="v2-provider-pill is-warning">{T.disabled}</span> : null}
                    {defaultModel.startsWith(`${provider.id}/`) ? <span className="v2-provider-pill">默认服务商</span> : null}
                  </div>
                </div>
                <div className="v2-provider-card-actions">
                  <button type="button" className="v2-provider-primary" onClick={() => {
                    setEditor(null);
                    setCredentialEditor(null);
                    setModelForm({
                      providerId: provider.id,
                      mode: "add",
                      draft: { ...blankModel(), wire_protocol: provider.models[0]?.wire_protocol ?? "openai" },
                    });
                    setDiscovery(null);
                    setDiscoverySearch("");
                    setExpandedProviderIds((prev) => [...new Set([...(prev ?? (defaultModel ? [defaultModel.split("/")[0]] : [])), provider.id])]);
                  }} disabled={readOnly || busy !== ""}>{T.addModel}</button>
                  {!localNoKey ? (
                    <button type="button" className={!provider.credential_configured ? "v2-provider-primary" : ""}
                      onClick={() => openCredential(provider.id)} disabled={readOnly || busy !== ""}
                      aria-expanded={credentialEditor?.providerId === provider.id}>
                      {provider.credential_configured ? "更换 API Key" : "配置 API Key"}
                    </button>
                  ) : null}
                  <button type="button" onClick={() => void runTest(provider, "")} disabled={busy !== ""}>
                    {busy === `test:${provider.id}/` ? T.testing : T.test}
                  </button>
                  <button type="button" onClick={() => openEdit(provider)} disabled={readOnly || busy !== ""}>{T.edit}</button>
                  <details className="v2-provider-more">
                    <summary>更多操作</summary>
                    <div className="v2-provider-more-menu">
                      <button type="button" onClick={() => void toggleProvider(provider)} disabled={readOnly || busy !== ""}>
                        {provider.enabled === false ? T.enabled : T.disabled}
                      </button>
                      {provider.credential_configured ? (
                        <button type="button" className="v2-provider-text-danger" onClick={() => void clearCredential(provider)}
                          disabled={readOnly || busy !== ""}>{T.clearKey}</button>
                      ) : null}
                      <button type="button" className="v2-provider-text-danger" onClick={() => void removeProvider(provider)}
                        disabled={readOnly || busy !== ""}>{T.remove}</button>
                    </div>
                  </details>
                </div>
              </div>
              <p className="v2-provider-endpoint" title={provider.base_url}>{provider.id} · {provider.base_url}</p>
              {credentialEditor?.providerId === provider.id ? (
                <form className="v2-provider-credential-form" aria-label={`${provider.id} API Key 配置`}
                  onSubmit={(event) => { event.preventDefault(); void saveCredential(); }}>
                  <label>
                    API Key（只写入，不回显）
                    <input type="password" autoComplete="new-password" autoFocus
                      aria-label={`${provider.id} API Key`}
                      value={credentialEditor.apiKey}
                      onChange={(event) => setCredentialEditor({ ...credentialEditor, apiKey: event.target.value })}
                      disabled={busy !== ""} />
                  </label>
                  <p className="v2-provider-footnote">只更新此服务商的凭证，不更改默认模型；保存后用于后续请求。</p>
                  {error ? <p className="v2-provider-warning" role="alert">{error.message}</p> : null}
                  <div className="v2-provider-editor-actions">
                    <button type="submit" className="v2-provider-primary"
                      disabled={!credentialEditor.apiKey.trim() || busy !== ""}>
                      {busy === `credential:${provider.id}` ? T.saving : "保存 API Key"}
                    </button>
                    <button type="button" onClick={() => setCredentialEditor(null)} disabled={busy !== ""}>{T.cancel}</button>
                  </div>
                </form>
              ) : null}
              {editor?.mode === "edit" && editor.providerId === provider.id ? providerEditor : null}
              {tests[`${provider.id}/`] ? (
                <p className="v2-provider-test-fact" role="status">{tests[`${provider.id}/`]}</p>
              ) : null}

              {expanded ? (
                <div className="v2-provider-card-body" id={`provider-models-${provider.id}`}>
                  <label className="v2-provider-default-control v2-provider-provider-default">
                    {T.providerDefault}
                    <select value={provider.default_model ?? ""}
                      onChange={(event) => void setProviderDefault(provider, event.target.value)}
                      disabled={readOnly || busy !== ""}>
                      <option value="">未指定</option>
                      {provider.default_model && !defaultChoices.some((model) => model.id === provider.default_model) ? (
                        <option value={provider.default_model}>{provider.default_model}（当前不可用）</option>
                      ) : null}
                      {defaultChoices.map((model) => (
                        <option key={model.id} value={model.id}>{model.name || model.id}</option>
                      ))}
                    </select>
                  </label>
                  {modelForm?.mode === "add" && modelForm.providerId === provider.id ? modelEditor : null}
                  <div className="v2-provider-models">
                    {providerModels.length === 0 ? <p className="v2-provider-footnote">{T.noModels}</p> : null}
                    {providerModels.map((model) => {
                      const key = `${provider.id}/${model.id}`;
                      return (
                        <div className="v2-provider-model-row" key={key}>
                          <div className="v2-provider-model-identity">
                            <strong>{model.name || model.id}</strong>
                            <code>{model.id}</code>
                            {model.note ? <p className="v2-provider-footnote">{model.note}</p> : null}
                          </div>
                          <div className="v2-provider-model-facts">
                            <span>{model.context ? `${Math.round(model.context / 1024)}K 上下文` : "上下文未声明"}</span>
                            {model.reasoning_capable ? <span>支持推理</span> : null}
                            {model.enabled === false ? <span className="is-warning">{T.disabled}</span> : null}
                            {model.effective === false ? <span className="is-warning">未生效</span> : null}
                            {defaultModel === key ? <span>全局默认</span> : null}
                          </div>
                          <div className="v2-provider-card-actions v2-provider-model-actions">
                            <button type="button" aria-label={`${T.testModel} ${model.id}`}
                              onClick={() => void runTest(provider, model.id)} disabled={busy !== ""}>
                              {busy === `test:${key}` ? T.testing : T.testModel}
                            </button>
                            <button type="button" aria-label={`${T.editModel} ${model.id}`} onClick={() => {
                              setEditor(null);
                              setCredentialEditor(null);
                              setModelForm({ providerId: provider.id, mode: "edit", originalId: model.id,
                                baseVersion: snapshot?.config_version, draft: toModelConfig(model) });
                              setDiscovery(null);
                            }} disabled={readOnly || busy !== ""}>{T.editModel}</button>
                            <details className="v2-provider-more">
                              <summary aria-label={`更多操作 ${model.id}`}>更多</summary>
                              <div className="v2-provider-more-menu">
                                <button type="button" aria-label={`${T.toggle} ${model.id}`}
                                  onClick={() => void toggleModel(provider, model)} disabled={readOnly || busy !== ""}>
                                  {model.enabled === false ? T.enabled : T.disabled}
                                </button>
                                <button type="button" className="v2-provider-text-danger" aria-label={`${T.remove} ${model.id}`}
                                  onClick={() => void removeModel(provider, model)} disabled={readOnly || busy !== ""}>
                                  {T.remove}
                                </button>
                              </div>
                            </details>
                          </div>
                          {tests[key] ? <p className="v2-provider-test-fact" role="status">{tests[key]}</p> : null}
                          {modelForm?.mode === "edit" && modelForm.providerId === provider.id && modelForm.originalId === model.id
                            ? modelEditor : null}
                        </div>
                      );
                    })}
                  </div>
                </div>
              ) : null}
            </article>
          );
        })}
      </div>
      <details className="v2-provider-extra-tools" onToggle={(event) => setShowExtraTools(event.currentTarget.open)}>
        <summary>本地运行时与视频工具</summary>
        {showExtraTools ? (
          <>
            <LocalRuntimePanel onSynced={() => setFlash(T.runtimeSynced)} />
            <VideoPanel />
          </>
        ) : null}
      </details>
    </section>
  );
}
