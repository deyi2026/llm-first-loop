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
  return known || raw || T.errors.unknown;
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

function text(value: number | null | undefined): string {
  return value === null || value === undefined ? "" : String(value);
}

interface ModelFormProps {
  draft: ProviderModelConfigInput;
  isNew: boolean;
  onChange: (next: ProviderModelConfigInput) => void;
}

function ModelFields({ draft, isNew, onChange }: ModelFormProps) {
  return (
    <div className="v2-provider-model-grid">
      <label>
        {T.modelId}
        <input
          value={draft.id}
          readOnly={!isNew}
          aria-readonly={!isNew}
          onChange={(event) => onChange({ ...draft, id: event.target.value })}
        />
      </label>
      <label>
        {T.modelName}
        <input
          value={draft.name ?? ""}
          onChange={(event) => onChange({ ...draft, name: event.target.value })}
        />
      </label>
      <label>
        {T.context}
        <input
          type="number"
          value={text(draft.context)}
          onChange={(event) => onChange({ ...draft, context: num(event.target.value) ?? 0 })}
        />
      </label>
      <label>
        {T.maxTokens}
        <input
          type="number"
          value={text(draft.max_tokens)}
          onChange={(event) => onChange({ ...draft, max_tokens: num(event.target.value) })}
        />
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
        {T.reasoningEfforts}
        <input
          value={(draft.reasoning_efforts ?? []).join(",")}
          onChange={(event) =>
            onChange({
              ...draft,
              reasoning_efforts: event.target.value
                .split(",")
                .map((item) => item.trim())
                .filter(Boolean),
            })
          }
        />
      </label>
      <label>
        {T.reasoningDefault}
        <input
          value={draft.reasoning_default_effort ?? ""}
          onChange={(event) =>
            onChange({ ...draft, reasoning_default_effort: event.target.value.trim() || null })
          }
        />
      </label>
      <label>
        {T.wireProtocol}
        <input
          value={draft.wire_protocol ?? "openai"}
          onChange={(event) => onChange({ ...draft, wire_protocol: event.target.value })}
        />
      </label>
      <label>
        {T.reasoning}
        <select
          value={draft.reasoning_capable ? "on" : "off"}
          onChange={(event) =>
            onChange({
              ...draft,
              reasoning_capable: event.target.value === "on",
              reasoning_control: event.target.value === "on" ? draft.reasoning_control ?? "effort" : "unknown",
            })
          }
        >
          <option value="off">关</option>
          <option value="on">开</option>
        </select>
      </label>
      <label>
        {T.note}
        <input
          value={draft.note ?? ""}
          onChange={(event) => onChange({ ...draft, note: event.target.value })}
        />
      </label>
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
  } | null>(null);
  const [modelForm, setModelForm] = useState<{
    providerId: string;
    mode: "add" | "edit";
    originalId?: string;
    draft: ProviderModelConfigInput;
  } | null>(null);
  const [discovery, setDiscovery] = useState<{
    providerId: string;
    candidates: DiscoveredModel[];
    selected: string[];
    error?: string;
  } | null>(null);

  const load = useCallback(async () => {
    const next = await fetchProviderAdmin();
    if (next) {
      setSnapshot(next);
      setError(null);
    } else {
      setError({ message: T.errors.load });
    }
    setLoading(false);
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => subscribeProvidersUpdated(() => void load()), [load]);

  const readOnly = !snapshot?.mutable;
  const def = snapshot?.default;
  const defaultModel = def?.model ?? snapshot?.configured_default_model ?? "";
  const runtimeModel = def?.runtime_model ?? snapshot?.runtime_default_model ?? "";
  const restartRequired = Boolean(def ? def.restart_required : snapshot?.restart_required);

  const modelOptions = useMemo(() => {
    const options: { value: string; label: string }[] = [];
    for (const provider of snapshot?.providers ?? []) {
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

  const runMutation = useCallback(
    async (key: string, action: () => Promise<Awaited<ReturnType<typeof patchProvider>>>, success: string) => {
      setBusy(key);
      setError(null);
      setFlash("");
      try {
        const result = await action();
        if (result.snapshot) setSnapshot(result.snapshot);
        else await load();
        if (!result.ok) {
          setError({
            message: errorLabel(result.error, result.detail),
            conflict: result.status === 409 || result.error === "provider_config_conflict",
          });
          return false;
        }
        setFlash(result.detail || success);
        notifyModelCatalogChanged();
        void onCatalogChanged?.();
        return true;
      } catch (err) {
        setError({ message: err instanceof Error ? err.message : T.errors.unknown });
        await load();
        return false;
      } finally {
        setBusy("");
      }
    },
    [load]
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
    const result = await testProviderConnection(provider.id, modelId);
    setTests((prev) => ({ ...prev, [key]: result.detail }));
    setBusy("");
  };

  const openCreate = () => {
    setError(null);
    setEditor({ mode: "create", draft: blankProvider(), apiKey: "" });
    setModelForm(null);
    setDiscovery(null);
  };

  const openEdit = (provider: ProviderAdminFact) => {
    setError(null);
    setEditor({
      mode: "edit",
      providerId: provider.id,
      draft: toProviderConfig(provider),
      apiKey: "",
    });
    setModelForm(null);
    setDiscovery(null);
  };

  const saveEditor = async () => {
    if (!snapshot || !editor) return;
    if (!editor.draft.id.trim()) {
      setError({ message: `${T.providerId} 不能为空` });
      return;
    }
    const ok = await runMutation(
      "editor",
      () =>
        editor.mode === "create"
          ? createProvider(snapshot.config_version, editor.draft, editor.apiKey)
          : replaceProvider(snapshot.config_version, editor.draft),
      T.saved
    );
    if (!ok) return;
    if (editor.mode === "edit" && editor.apiKey.trim() && editor.providerId) {
      await runMutation("credential", () => updateProviderCredential(editor.providerId as string, editor.apiKey), T.saved);
    }
    setEditor(null);
  };

  const saveModel = async () => {
    if (!snapshot || !modelForm) return;
    if (!modelForm.draft.id.trim()) {
      setError({ message: `${T.modelId} 不能为空` });
      return;
    }
    const ok = await runMutation(
      "model-form",
      () =>
        modelForm.mode === "edit"
          ? replaceProviderModel(
              modelForm.providerId,
              modelForm.originalId ?? modelForm.draft.id,
              snapshot.config_version,
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
    setDiscovery({ providerId: provider.id, candidates: [], selected: [], error: undefined });
    const result = await discoverProviderModels({
      base_url: provider.base_url,
      wire_protocol: modelForm.draft.wire_protocol || "openai",
      provider_id: provider.id,
    });
    setBusy("");
    if (!result.ok) {
      setDiscovery({
        providerId: provider.id,
        candidates: [],
        selected: [],
        error: errorLabel(result.errorCode, result.timeout ? T.errors.discovery_failed : T.errors.discovery_failed),
      });
      return;
    }
    setDiscovery({ providerId: provider.id, candidates: result.candidates, selected: [] });
  };

  const addSelected = async () => {
    if (!snapshot || !discovery || !modelForm) return;
    let version = snapshot.config_version;
    let added = 0;
    let failure = "";
    setBusy("discover-add");
    for (const id of discovery.selected) {
      const candidate = discovery.candidates.find((item) => item.id === id);
      const result = await addProviderModel(discovery.providerId, version, {
        ...blankModel(),
        id,
        name: candidate?.name || id,
        context: candidate?.context_window ?? 131072,
        max_tokens: candidate?.max_output_tokens ?? null,
        wire_protocol: modelForm.draft.wire_protocol || "openai",
        note: "",
      });
      if (result.snapshot) {
        setSnapshot(result.snapshot);
        version = result.snapshot.config_version;
      }
      if (!result.ok) {
        failure = errorLabel(result.error, result.detail);
        break;
      }
      added += 1;
    }
    setBusy("");
    if (failure) {
      setError({ message: failure, conflict: false });
      await load();
      return;
    }
    setFlash(`${T.addSelected} ${added}`);
    notifyModelCatalogChanged();
    setDiscovery(null);
    setModelForm(null);
  };

  const providerEditor = editor ? (
    <section className="v2-provider-editor" data-testid="provider-editor" aria-label={editor.mode === "create" ? T.addProvider : T.edit}>
      <div className="v2-provider-editor-head">
        <strong>{editor.mode === "create" ? T.addProvider : `${T.edit} · ${editor.providerId}`}</strong>
      </div>
      {editor.mode === "create" ? (
        <label className="v2-provider-fields">
          {T.copyFrom}
          <select
            value=""
            onChange={(event) => {
              const source = snapshot?.providers.find((item) => item.id === event.target.value);
              if (!source) return;
              setEditor({
                ...editor,
                draft: {
                  ...toProviderConfig(source),
                  id: "",
                  display_name: `${source.display_name || source.id} 副本`,
                  default_model: "",
                },
              });
            }}
          >
            <option value="">—</option>
            {(snapshot?.providers ?? []).map((item) => (
              <option key={item.id} value={item.id}>{item.display_name || item.id}</option>
            ))}
          </select>
        </label>
      ) : null}
      <div className="v2-provider-fields">
        <label>
          {T.providerId}
          <input
            value={editor.draft.id}
            readOnly={editor.mode === "edit"}
            onChange={(event) => setEditor({ ...editor, draft: { ...editor.draft, id: event.target.value } })}
          />
        </label>
        <label>
          {T.displayName}
          <input
            value={editor.draft.display_name ?? ""}
            onChange={(event) => setEditor({ ...editor, draft: { ...editor.draft, display_name: event.target.value } })}
          />
        </label>
        <label>
          {T.baseUrl}
          <input
            value={editor.draft.base_url}
            onChange={(event) => setEditor({ ...editor, draft: { ...editor.draft, base_url: event.target.value } })}
          />
        </label>
        <label>
          {editor.mode === "create" ? T.apiKey : T.apiKeyKeep}
          <input
            type="password"
            value={editor.apiKey}
            onChange={(event) => setEditor({ ...editor, apiKey: event.target.value })}
          />
        </label>
        <label>
          {T.apiKeyEnv}
          <input
            value={editor.draft.api_key_env ?? ""}
            onChange={(event) => setEditor({ ...editor, draft: { ...editor.draft, api_key_env: event.target.value } })}
          />
        </label>
        <label>
          {T.providerDefault}
          <input
            value={editor.draft.default_model ?? ""}
            onChange={(event) => setEditor({ ...editor, draft: { ...editor.draft, default_model: event.target.value } })}
          />
        </label>
      </div>
      <details className="v2-provider-advanced">
        <summary>{T.advanced}</summary>
        <div className="v2-provider-fields">
          <label>
            {T.timeout}
            <input
              type="number"
              value={text(editor.draft.timeout_s)}
              onChange={(event) => setEditor({ ...editor, draft: { ...editor.draft, timeout_s: num(event.target.value) } })}
            />
          </label>
          <label>
            {T.maxTokens}
            <input
              type="number"
              value={text(editor.draft.max_tokens)}
              onChange={(event) => setEditor({ ...editor, draft: { ...editor.draft, max_tokens: num(event.target.value) } })}
            />
          </label>
          <label>
            {T.maxInputTokens}
            <input
              type="number"
              value={text(editor.draft.max_input_tokens)}
              onChange={(event) =>
                setEditor({ ...editor, draft: { ...editor.draft, max_input_tokens: num(event.target.value) } })
              }
            />
          </label>
          <label>
            {T.historyBudget}
            <input
              type="number"
              value={text(editor.draft.history_budget_chars)}
              onChange={(event) =>
                setEditor({ ...editor, draft: { ...editor.draft, history_budget_chars: num(event.target.value) } })
              }
            />
          </label>
          <label>
            {T.charsPerToken}
            <input
              type="number"
              value={text(editor.draft.chars_per_token)}
              onChange={(event) =>
                setEditor({ ...editor, draft: { ...editor.draft, chars_per_token: num(event.target.value) } })
              }
            />
          </label>
        </div>
        <pre className="v2-provider-raw">{JSON.stringify(editor.draft, null, 2)}</pre>
      </details>
      <div className="v2-provider-model-editor-list">
        {editor.draft.models.map((model, index) => (
          <div className="v2-provider-model-editor" key={`${model.id}-${index}`}>
            <ModelFields
              draft={model}
              isNew
              onChange={(next) =>
                setEditor({
                  ...editor,
                  draft: {
                    ...editor.draft,
                    models: editor.draft.models.map((item, i) => (i === index ? next : item)),
                  },
                })
              }
            />
            <div className="v2-provider-card-actions">
              <button
                type="button"
                onClick={() =>
                  setEditor({
                    ...editor,
                    draft: { ...editor.draft, models: editor.draft.models.filter((_, i) => i !== index) },
                  })
                }
              >
                {T.remove}
              </button>
            </div>
          </div>
        ))}
      </div>
      <div className="v2-provider-editor-actions">
        <button type="button" onClick={() => setEditor({ ...editor, draft: { ...editor.draft, models: [...editor.draft.models, blankModel()] } })}>
          {T.addModel}
        </button>
        <button type="button" onClick={() => void saveEditor()} disabled={busy !== ""}>
          {busy === "editor" ? T.saving : T.saveAndApply}
        </button>
        <button type="button" onClick={() => setEditor(null)}>
          {T.cancel}
        </button>
      </div>
    </section>
  ) : null;

  const modelEditor = modelForm ? (
    <section className="v2-provider-editor" aria-label={modelForm.mode === "add" ? T.addModel : T.edit}>
      <div className="v2-provider-editor-head">
        <strong>{modelForm.mode === "add" ? `${T.addModel} · ${modelForm.providerId}` : `${T.edit} · ${modelForm.originalId}`}</strong>
      </div>
      <ModelFields
        draft={modelForm.draft}
        isNew={modelForm.mode === "add"}
        onChange={(next) => setModelForm({ ...modelForm, draft: next })}
      />
      {modelForm.mode === "add" ? (
        <div className="v2-provider-card-actions">
          <button type="button" onClick={() => void discover()} disabled={busy !== ""}>
            {busy === "discover" ? T.discovering : T.discover}
          </button>
        </div>
      ) : null}
      {discovery && discovery.providerId === modelForm.providerId ? (
        <div className="v2-provider-model-editor">
          {discovery.error ? (
            <p className="v2-provider-warning" role="alert">{discovery.error}</p>
          ) : discovery.candidates.length === 0 ? (
            <p className="v2-provider-footnote">{T.discoverEmpty}</p>
          ) : (
            <>
              <p className="v2-provider-footnote">{T.discoverPick}</p>
              {discovery.candidates.map((candidate) => (
                <label key={candidate.id} className="v2-provider-model-flags">
                  <input
                    type="checkbox"
                    checked={discovery.selected.includes(candidate.id)}
                    onChange={(event) =>
                      setDiscovery({
                        ...discovery,
                        selected: event.target.checked
                          ? [...discovery.selected, candidate.id]
                          : discovery.selected.filter((id) => id !== candidate.id),
                      })
                    }
                  />
                  {candidate.name || candidate.id}
                </label>
              ))}
              <button type="button" onClick={() => void addSelected()} disabled={discovery.selected.length === 0 || busy !== ""}>
                {T.addSelected}
              </button>
            </>
          )}
        </div>
      ) : null}
      <div className="v2-provider-editor-actions">
        <button type="button" onClick={() => void saveModel()} disabled={busy !== ""}>
          {busy === "model-form" ? T.saving : T.save}
        </button>
        <button
          type="button"
          onClick={() => {
            setModelForm(null);
            setDiscovery(null);
          }}
        >
          {T.cancel}
        </button>
      </div>
    </section>
  ) : null;

  return (
    <section className="v2-provider-admin">
      <header className="v2-provider-head">
        <div>
          <h3>{T.title}</h3>
          <p className="v2-provider-subhead">{T.subtitle}</p>
        </div>
        <div className="v2-provider-actions">
          <button type="button" onClick={() => void load()} disabled={loading}>
            {T.refresh}
          </button>
          <button
            type="button"
            onClick={() => void runMutation("reload", () => reloadProviderRegistry(), T.applied)}
            disabled={readOnly || busy !== ""}
          >
            {T.reload}
          </button>
          <button type="button" onClick={openCreate} disabled={readOnly || !snapshot}>
            {T.addProvider}
          </button>
        </div>
      </header>

      {error ? (
        <div className="v2-provider-warning" role="alert" aria-live="assertive">
          {error.message}
          {error.conflict ? ` ${T.conflictBanner}` : ""}
          {error.conflict ? <button type="button" onClick={() => void load()}>{T.refresh}</button> : null}
        </div>
      ) : null}
      {flash ? <p className="v2-provider-ok" role="status">{flash}</p> : null}
      {readOnly ? <p className="v2-provider-readonly-note">{T.envReadonly}</p> : null}

      {snapshot ? (
        <div className="v2-provider-summary" data-testid="provider-summary">
          <div><span>{T.source}</span><strong>{snapshot.source}</strong></div>
          <div><span>{T.configDefault}</span><strong>{defaultModel || "—"}</strong></div>
          <div><span>{T.runtimeDefault}</span><strong>{runtimeModel || "—"}</strong></div>
          <div><span>{T.persistence}</span><strong>{def?.persistence ?? "—"}</strong></div>
          <div>
            <span>{T.applied}</span>
            <strong>{restartRequired ? T.restartRequired : T.applied}</strong>
          </div>
          {restartRequired ? <p className="v2-provider-warning">{T.restartHint}</p> : null}
          {snapshot.degraded ? <p className="v2-provider-warning">{T.degraded}</p> : null}
        </div>
      ) : null}

      {snapshot ? (
        <label className="v2-provider-fields">
          {T.defaultModel}
          <select value={defaultModel} onChange={(event) => void setDefault(event.target.value)} disabled={readOnly || busy !== ""}>
            {defaultModel && !modelOptions.some((option) => option.value === defaultModel) ? (
              <option value={defaultModel}>{defaultModel}</option>
            ) : null}
            {modelOptions.map((option) => (
              <option key={option.value} value={option.value}>{option.label}</option>
            ))}
          </select>
        </label>
      ) : null}

      {providerEditor}
      {modelEditor}

      {loading ? <p>{T.loading}</p> : null}

      <div className="v2-provider-list">
        {(snapshot?.providers ?? []).map((provider) => {
          const providerModels = provider.models;
          const defaultChoices = providerModels.filter((model) => model.enabled !== false);
          return (
            <article className="v2-provider-card" key={provider.id} data-testid={`provider-${provider.id}`}>
              <div className="v2-provider-head">
                <div>
                  <strong>{provider.display_name || provider.id}</strong>
                  <p className="v2-provider-meta">
                    <span>{provider.id}</span>
                    <span>{provider.base_url}</span>
                    <span>{provider.credential_configured ? "已配置" : "未配置"} · {provider.credential_source ?? "none"}</span>
                    <span>{provider.enabled === false ? T.disabled : T.enabled}</span>
                  </p>
                </div>
                <div className="v2-provider-card-actions">
                  <button type="button" onClick={() => void toggleProvider(provider)} disabled={readOnly || busy !== ""}>
                    {provider.enabled === false ? T.enabled : T.disabled}
                  </button>
                  <button type="button" onClick={() => openEdit(provider)} disabled={readOnly}>{T.edit}</button>
                  {provider.credential_configured ? (
                    <button type="button" onClick={() => void clearCredential(provider)} disabled={readOnly || busy !== ""}>
                      {T.clearKey}
                    </button>
                  ) : null}
                  <button type="button" onClick={() => void removeProvider(provider)} disabled={readOnly || busy !== ""}>
                    {T.remove}
                  </button>
                  <button type="button" onClick={() => void runTest(provider, "")} disabled={busy !== ""}>
                    {busy === `test:${provider.id}/` ? T.testing : T.test}
                  </button>
                </div>
              </div>

              {tests[`${provider.id}/`] ? (
                <p className="v2-provider-test-fact" role="status">{tests[`${provider.id}/`]}</p>
              ) : null}

              <label className="v2-provider-fields">
                {T.providerDefault}
                <select
                  value={provider.default_model ?? ""}
                  onChange={(event) => void setProviderDefault(provider, event.target.value)}
                  disabled={readOnly || busy !== ""}
                >
                  <option value="">—</option>
                  {defaultChoices.map((model) => (
                    <option key={model.id} value={model.id}>{model.name || model.id}</option>
                  ))}
                </select>
              </label>

              <div className="v2-provider-models">
                {providerModels.length === 0 ? <p className="v2-provider-footnote">{T.noModels}</p> : null}
                {providerModels.map((model) => {
                  const key = `${provider.id}/${model.id}`;
                  return (
                    <div className="v2-provider-model-grid" key={key}>
                      <div className="v2-provider-meta">
                        <strong>{model.name || model.id}</strong>
                        <span>{model.id}</span>
                      </div>
                      <div className="v2-provider-model-flags">
                        <span>{T.context} {model.context ?? "—"}</span>
                        <span>{model.cost_tier ?? "—"}</span>
                        <span>{model.reasoning_capable ? `${T.reasoning} · ${model.reasoning_control ?? ""}` : ""}</span>
                        <span>{model.enabled === false ? T.disabled : ""}</span>
                        {model.effective === false ? <span>未生效</span> : null}
                      </div>
                      {model.note ? <p className="v2-provider-footnote">{model.note}</p> : null}
                      <div className="v2-provider-card-actions">
                        <button type="button" aria-label={`${T.toggle} ${model.id}`} onClick={() => void toggleModel(provider, model)} disabled={readOnly || busy !== ""}>
                          {model.enabled === false ? T.enabled : T.disabled}
                        </button>
                        <button type="button" aria-label={`${T.testModel} ${model.id}`} onClick={() => void runTest(provider, model.id)} disabled={busy !== ""}>
                          {busy === `test:${key}` ? T.testing : T.testModel}
                        </button>
                        <button
                          type="button"
                          aria-label={`${T.editModel} ${model.id}`}
                          onClick={() => {
                            setModelForm({ providerId: provider.id, mode: "edit", originalId: model.id, draft: toModelConfig(model) });
                            setDiscovery(null);
                          }}
                          disabled={readOnly}
                        >
                          {T.editModel}
                        </button>
                        <button type="button" aria-label={`${T.remove} ${model.id}`} onClick={() => void removeModel(provider, model)} disabled={readOnly || busy !== ""}>
                          {T.remove}
                        </button>
                      </div>
                      {tests[key] ? <span className="v2-provider-test-fact">{tests[key]}</span> : null}
                    </div>
                  );
                })}
              </div>
              <div className="v2-provider-card-actions">
                <button
                  type="button"
                  onClick={() => {
                    setModelForm({ providerId: provider.id, mode: "add", draft: { ...blankModel(), wire_protocol: provider.models[0]?.wire_protocol ?? "openai" } });
                    setDiscovery(null);
                  }}
                  disabled={readOnly}
                >
                  {T.addModel}
                </button>
              </div>
            </article>
          );
        })}
      </div>

      <LocalRuntimePanel
        onSynced={() => {
          setFlash(T.runtimeSynced);
        }}
      />
      <VideoPanel />
    </section>
  );
}
