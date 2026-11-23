import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { ProviderManager } from "./components/layout/ProviderManager";
import { ModelControls } from "./components/conversation/ModelControls";
import { RightPanel } from "./components/layout/RightPanel";
import { __resetCapabilitiesForTest } from "./core/capabilities";
import { sessionStore } from "./core/stores";
import { MODEL_CATALOG_CHANGED_EVENT } from "./core/chat";
import type { ProviderAdminSnapshot } from "./core/api";

const SNAPSHOT: ProviderAdminSnapshot = {
  source: "local",
  mutable: true,
  config_version: "version-1",
  configured_default_model: "glm/glm-5.3",
  runtime_default_model: "glm/glm-5.3",
  restart_required: false,
  effective_provider_count: 1,
  effective_model_count: 1,
  providers: [
    {
      id: "glm",
      enabled: true,
      effective: true,
      base_url: "https://provider.example/v1",
      api_key_env: "GLM_API_KEY",
      credential_configured: true,
      credential_source: "dotenv",
      default_model: "glm-5.3",
      models: [
        {
          id: "glm-5.3",
          enabled: true,
          effective: true,
          context: 262144,
          reasoning_capable: true,
          reasoning_control: "always_on_effort",
          reasoning_efforts: ["low", "high", "max"],
          reasoning_default_effort: "max",
          wire_protocol: "openai",
          send_tool_choice: true,
          reasoning_split: false,
          reasoning_replay: "configured",
        },
      ],
    },
  ],
};

const MODEL_CATALOG = {
  models: ["glm/glm-5.3"],
  current: "glm/glm-5.3",
  catalog: [{
    id: "glm/glm-5.3",
    provider: "glm",
    model: "glm-5.3",
    context: 262144,
    reasoning_capable: true,
    reasoning_control: "always_on_effort",
    reasoning_control_supported: true,
    reasoning_can_disable: false,
    reasoning_efforts: ["low", "high", "max"],
    reasoning_default_effort: "max",
  }],
};

beforeEach(() => {
  __resetCapabilitiesForTest();
});

afterEach(() => {
  cleanup();
  __resetCapabilitiesForTest();
  vi.unstubAllGlobals();
});

describe("provider manager", () => {
  it("Deepin 缺密钥时在 GLM 卡片直接保存，不整包 PUT，不回显密钥", async () => {
    const secret = "fixture-coding-plan-secret";
    const calls: Array<{ url: string; method: string; body: Record<string, unknown> }> = [];
    const missing = {
      ...SNAPSHOT,
      providers: [{ ...SNAPSHOT.providers[0]!, credential_configured: false, credential_source: "missing" }],
    };
    const configured = {
      ...missing,
      providers: [{ ...missing.providers[0]!, credential_configured: true, credential_source: "dotenv" }],
    };
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = init?.method ?? "GET";
      if (method === "PUT" || method === "POST") {
        calls.push({ url, method, body: JSON.parse(String(init?.body ?? "{}")) as Record<string, unknown> });
      }
      if (url === "/api/v1/providers/glm/credential" && method === "PUT") {
        return new Response(JSON.stringify(configured), { status: 200 });
      }
      if (url === "/api/v1/providers") return new Response(JSON.stringify(missing), { status: 200 });
      return new Response(JSON.stringify({}), { status: 200 });
    }));

    render(<ProviderManager />);
    const card = await screen.findByTestId("provider-glm");
    fireEvent.click(within(card).getByRole("button", { name: "配置 API Key" }));
    const form = within(card).getByRole("form", { name: "glm API Key 配置" });
    fireEvent.change(within(form).getByLabelText("glm API Key"), { target: { value: secret } });
    fireEvent.click(within(form).getByRole("button", { name: "保存 API Key" }));

    await waitFor(() => expect(calls).toHaveLength(1));
    expect(calls[0]).toEqual({
      url: "/api/v1/providers/glm/credential",
      method: "PUT",
      body: { api_key: secret },
    });
    await waitFor(() => expect(within(card).queryByRole("form", { name: "glm API Key 配置" })).toBeNull());
    expect(screen.getByText(/API Key 已保存并生效/)).toBeInTheDocument();
    expect(document.body.textContent).not.toContain(secret);
    expect(screen.queryByDisplayValue(secret)).toBeNull();
  });

  it("密钥保存失败时保持原位编辑并显示错误，重试成功才关闭", async () => {
    let attempts = 0;
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url === "/api/v1/providers/glm/credential" && init?.method === "PUT") {
        attempts += 1;
        if (attempts === 1) {
          return new Response(JSON.stringify({ error: "provider_config_conflict", detail: "保存失败，请刷新后重试" }), { status: 409 });
        }
        return new Response(JSON.stringify(SNAPSHOT), { status: 200 });
      }
      if (url === "/api/v1/providers") return new Response(JSON.stringify(SNAPSHOT), { status: 200 });
      return new Response(JSON.stringify({}), { status: 200 });
    }));

    render(<ProviderManager />);
    const card = await screen.findByTestId("provider-glm");
    fireEvent.click(within(card).getByRole("button", { name: "更换 API Key" }));
    const form = within(card).getByRole("form", { name: "glm API Key 配置" });
    fireEvent.change(within(form).getByLabelText("glm API Key"), { target: { value: "retry-fixture-secret" } });
    fireEvent.click(within(form).getByRole("button", { name: "保存 API Key" }));
    await waitFor(() => expect(within(form).getByText("保存失败，请刷新后重试")).toBeInTheDocument());
    expect(within(form).getByLabelText("glm API Key")).toHaveValue("retry-fixture-secret");
    expect(within(screen.getAllByRole("alert")[0]!).getByRole("button", { name: "刷新" })).toBeInTheDocument();
    fireEvent.click(within(form).getByRole("button", { name: "保存 API Key" }));
    await waitFor(() => expect(attempts).toBe(2));
    await waitFor(() => expect(within(card).queryByRole("form", { name: "glm API Key 配置" })).toBeNull());
  });

  it("写入成功但配置回读失败时不误报成功、不关闭密钥输入框", async () => {
    let reads = 0;
    let writes = 0;
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url === "/api/v1/providers/glm/credential" && init?.method === "PUT") {
        writes += 1;
        return new Response(JSON.stringify({ detail: "accepted" }), { status: 200 });
      }
      if (url === "/api/v1/providers") {
        reads += 1;
        if (reads === 1) return new Response(JSON.stringify(SNAPSHOT), { status: 200 });
        return new Response(JSON.stringify({ detail: "upstream timeout" }), { status: 503 });
      }
      return new Response(JSON.stringify({}), { status: 200 });
    }));

    render(<ProviderManager />);
    const card = await screen.findByTestId("provider-glm");
    fireEvent.click(within(card).getByRole("button", { name: "更换 API Key" }));
    const form = within(card).getByRole("form", { name: "glm API Key 配置" });
    fireEvent.change(within(form).getByLabelText("glm API Key"), { target: { value: "unconfirmed-fixture" } });
    fireEvent.click(within(form).getByRole("button", { name: "保存 API Key" }));
    await waitFor(() => expect(screen.getAllByText(/服务器已接受操作，但无法确认最新配置/)).toHaveLength(2));
    expect(writes).toBe(1);
    expect(reads).toBe(2);
    expect(within(card).getByRole("form", { name: "glm API Key 配置" })).toBeInTheDocument();
    expect(within(form).getByLabelText("glm API Key")).toHaveValue("unconfirmed-fixture");
    expect(screen.queryByText(/API Key 已保存并生效/)).toBeNull();
  });

  it("编辑 Provider 就地展开，密钥独立配置，不隐藏在远处的整包编辑器", async () => {
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      if (String(input) === "/api/v1/providers") return new Response(JSON.stringify(SNAPSHOT), { status: 200 });
      return new Response(JSON.stringify({}), { status: 200 });
    }));
    render(<ProviderManager />);
    const card = await screen.findByTestId("provider-glm");
    fireEvent.click(within(card).getByRole("button", { name: "编辑" }));
    const editor = within(card).getByTestId("provider-editor");
    expect(within(editor).getByLabelText("Base URL")).toBeInTheDocument();
    expect(within(editor).queryByLabelText("API Key（留空则保留现有）")).toBeNull();
    expect(screen.getAllByTestId("provider-editor")).toHaveLength(1);
  });

  it("只展示凭证状态，不渲染 API Key 明文", async () => {
    const secret = "provider-secret-should-never-render";
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      if (String(input).includes("/api/v1/providers")) {
        return new Response(JSON.stringify(SNAPSHOT), { status: 200 });
      }
      return new Response(JSON.stringify({}), { status: 200 });
    }));

    render(<ProviderManager />);
    await waitFor(() => expect(screen.getByTestId("provider-glm")).toBeInTheDocument());
    expect(screen.getByText(/已配置 · dotenv/)).toBeInTheDocument();
    expect(screen.queryByText(secret)).toBeNull();
    expect(document.body.textContent).not.toContain(secret);
  });

  it("添加 Provider 使用当前 config_version，保存后广播 catalog 变更且不把 Key 放进界面状态", async () => {
    const createBodies: Record<string, unknown>[] = [];
    let catalogChanged = 0;
    const onCatalogChanged = () => { catalogChanged += 1; };
    window.addEventListener(MODEL_CATALOG_CHANGED_EVENT, onCatalogChanged);
    const added = {
      ...SNAPSHOT,
      config_version: "version-2",
      providers: [
        ...SNAPSHOT.providers,
        {
          id: "custom",
          enabled: true,
          effective: true,
          base_url: "https://custom.example/v1",
          api_key_env: "LFL_PROVIDER_CUSTOM_API_KEY",
          credential_configured: true,
          credential_source: "dotenv",
          default_model: "model-x",
          models: [{ id: "model-x", enabled: true, effective: true, context: 131072, reasoning_capable: false, reasoning_control: "unknown" }],
        },
      ],
    };
    let current = SNAPSHOT;
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url === "/api/v1/providers" && init?.method === "POST") {
        createBodies.push(JSON.parse(String(init.body ?? "{}")) as Record<string, unknown>);
        current = added;
        return new Response(JSON.stringify(added), { status: 201 });
      }
      if (url === "/api/v1/providers") return new Response(JSON.stringify(current), { status: 200 });
      if (url.includes("/api/v1/models")) return new Response(JSON.stringify(MODEL_CATALOG), { status: 200 });
      return new Response(JSON.stringify({}), { status: 200 });
    }));

    render(<ProviderManager />);
    await waitFor(() => expect(screen.getByRole("button", { name: "+ 添加服务商" })).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "+ 添加服务商" }));
    const editor = screen.getByTestId("provider-editor");
    fireEvent.change(within(editor).getByLabelText("Provider ID"), { target: { value: "custom" } });
    fireEvent.change(within(editor).getByLabelText("Base URL"), { target: { value: "https://custom.example/v1" } });
    fireEvent.change(within(editor).getByLabelText("API Key"), { target: { value: "provider-secret-fixture-456" } });
    fireEvent.change(within(editor).getByLabelText("Model ID"), { target: { value: "model-x" } });
    fireEvent.click(within(editor).getByRole("button", { name: "保存并热重载" }));

    await waitFor(() => expect(createBodies).toHaveLength(1));
    const createBody = createBodies[0]!;
    expect(createBody.expected_version).toBe("version-1");
    expect(createBody.api_key).toBe("provider-secret-fixture-456");
    expect((createBody.provider as Record<string, unknown>).id).toBe("custom");
    await waitFor(() => expect(screen.getByTestId("provider-custom")).toBeInTheDocument());
    await waitFor(() => expect(catalogChanged).toBe(1));
    expect(document.body.textContent).not.toContain("provider-secret-fixture-456");
    window.removeEventListener(MODEL_CATALOG_CHANGED_EVENT, onCatalogChanged);
  });

  it("测试连接是显式动作，展示机械 latency 结果而非模型正文", async () => {
    let testCalls = 0;
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url === "/api/v1/providers") return new Response(JSON.stringify(SNAPSHOT), { status: 200 });
      if (url.endsWith("/api/v1/providers/glm/test") && init?.method === "POST") {
        testCalls += 1;
        return new Response(JSON.stringify({ ok: true, latency_ms: 234, model: "glm-5.3" }), { status: 200 });
      }
      return new Response(JSON.stringify({}), { status: 200 });
    }));

    render(<ProviderManager />);
    await waitFor(() => expect(screen.getByRole("button", { name: "测试连接" })).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "测试连接" }));
    await waitFor(() => expect(testCalls).toBe(1));
    expect(await screen.findByText("连接成功 · 234 ms")).toBeInTheDocument();
  });

  it("模型可在设置页声明自己的推理档位和默认档位", async () => {
    const putBodies: Record<string, unknown>[] = [];
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url === "/api/v1/providers/glm/models/glm-5.3" && init?.method === "PUT") {
        putBodies.push(JSON.parse(String(init.body ?? "{}")) as Record<string, unknown>);
        return new Response(JSON.stringify(SNAPSHOT), { status: 200 });
      }
      if (url === "/api/v1/providers") return new Response(JSON.stringify(SNAPSHOT), { status: 200 });
      return new Response(JSON.stringify({}), { status: 200 });
    }));

    render(<ProviderManager />);
    await waitFor(() => expect(screen.getByRole("button", { name: "编辑模型 glm-5.3" })).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "编辑模型 glm-5.3" }));
    const editor = screen.getByRole("region", { name: "编辑" });
    fireEvent.click(within(editor).getByText(/高级模型参数/));
    expect(within(editor).getByLabelText("推理档位")).toHaveValue("low,high,max");
    expect(within(editor).getByLabelText("默认推理档位")).toHaveValue("max");
    fireEvent.click(within(editor).getByRole("button", { name: "保存" }));

    await waitFor(() => expect(putBodies).toHaveLength(1));
    const model = putBodies[0]!.model as Record<string, unknown>;
    expect(model.reasoning_efforts).toEqual(["low", "high", "max"]);
    expect(model.reasoning_default_effort).toBe("max");
  });
  it("缺少密钥时在服务商卡片直接保存，仅写 credential，不整包 PUT", async () => {
    const missing = {
      ...SNAPSHOT,
      providers: [{ ...SNAPSHOT.providers[0]!, credential_configured: false, credential_source: "missing" }],
    };
    const configured = {
      ...SNAPSHOT,
      providers: [{ ...SNAPSHOT.providers[0]!, credential_configured: true, credential_source: "dotenv" }],
    };
    const calls: Array<{ url: string; method: string; body: Record<string, unknown> }> = [];
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = init?.method ?? "GET";
      if (method === "PUT") calls.push({ url, method, body: JSON.parse(String(init?.body ?? "{}")) as Record<string, unknown> });
      if (url === "/api/v1/providers/glm/credential" && method === "PUT") {
        return new Response(JSON.stringify(configured), { status: 200 });
      }
      if (url === "/api/v1/providers") return new Response(JSON.stringify(missing), { status: 200 });
      return new Response(JSON.stringify({}), { status: 200 });
    }));
    render(<ProviderManager />);
    const card = await screen.findByTestId("provider-glm");
    fireEvent.click(within(card).getByRole("button", { name: "配置 API Key" }));
    const form = within(card).getByRole("form", { name: "glm API Key 配置" });
    fireEvent.change(within(form).getByLabelText("glm API Key"), { target: { value: "fixture-secret" } });
    expect(document.body.textContent).not.toContain("fixture-secret");
    fireEvent.click(within(form).getByRole("button", { name: "保存 API Key" }));
    await waitFor(() => expect(calls).toHaveLength(1));
    expect(calls[0]).toEqual({
      url: "/api/v1/providers/glm/credential",
      method: "PUT",
      body: { api_key: "fixture-secret" },
    });
    await waitFor(() => expect(within(card).queryByRole("form", { name: "glm API Key 配置" })).toBeNull());
    expect(screen.getByText(/API Key 已保存并生效/)).toBeInTheDocument();
    expect(screen.queryByDisplayValue("fixture-secret")).toBeNull();
  });

  it("写入已接受但回读失败时保留密钥表单，不误报保存成功", async () => {
    let reads = 0;
    let writes = 0;
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url === "/api/v1/providers/glm/credential" && init?.method === "PUT") {
        writes += 1;
        return new Response(JSON.stringify({ detail: "accepted" }), { status: 200 });
      }
      if (url === "/api/v1/providers") {
        reads += 1;
        return reads === 1
          ? new Response(JSON.stringify(SNAPSHOT), { status: 200 })
          : new Response(JSON.stringify({ detail: "unavailable" }), { status: 503 });
      }
      return new Response(JSON.stringify({}), { status: 200 });
    }));
    render(<ProviderManager />);
    const card = await screen.findByTestId("provider-glm");
    fireEvent.click(within(card).getByRole("button", { name: "更换 API Key" }));
    const form = within(card).getByRole("form", { name: "glm API Key 配置" });
    fireEvent.change(within(form).getByLabelText("glm API Key"), { target: { value: "unconfirmed-secret" } });
    fireEvent.click(within(form).getByRole("button", { name: "保存 API Key" }));
    await waitFor(() => expect(screen.getAllByText(/服务器已接受操作，但无法确认最新配置/).length).toBeGreaterThan(0));
    expect(writes).toBe(1);
    expect(reads).toBe(2);
    expect(within(card).getByRole("form", { name: "glm API Key 配置" })).toBeInTheDocument();
    expect(within(form).getByLabelText("glm API Key")).toHaveValue("unconfirmed-secret");
    expect(screen.queryByText(/API Key 已保存并生效/)).toBeNull();
  });

  it("编辑服务商与添加模型就地展开，不把用户送回列表顶部", async () => {
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      if (String(input) === "/api/v1/providers") return new Response(JSON.stringify(SNAPSHOT), { status: 200 });
      return new Response(JSON.stringify({}), { status: 200 });
    }));
    render(<ProviderManager />);
    const card = await screen.findByTestId("provider-glm");
    fireEvent.click(within(card).getByRole("button", { name: "编辑" }));
    const editor = within(card).getByTestId("provider-editor");
    expect(within(editor).getByLabelText("Base URL")).toBeInTheDocument();
    expect(within(editor).queryByLabelText("API Key（留空则保留现有）")).toBeNull();
    fireEvent.click(within(editor).getByRole("button", { name: "取消" }));
    fireEvent.click(within(card).getByRole("button", { name: "+ 添加模型" }));
    expect(within(card).getByRole("region", { name: "+ 添加模型" })).toBeInTheDocument();
  });

});

describe("provider admin capability gating", () => {
  it("manifest 明确 providerAdmin=false 时保留只读模型目录但不渲染管理面", async () => {
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/api/v1/capabilities")) {
        return new Response(JSON.stringify({ capabilities: { providerAdmin: false, jobs: false } }), { status: 200 });
      }
      if (url.includes("/api/v1/models")) return new Response(JSON.stringify(MODEL_CATALOG), { status: 200 });
      if (url.includes("/auth/status")) return new Response(JSON.stringify({ browser_login: false, authenticated: false }), { status: 200 });
      return new Response(JSON.stringify({}), { status: 200 });
    }));

    render(<RightPanel open />);
    await waitFor(() => expect(screen.getByText("glm/glm-5.3")).toBeInTheDocument());
    await waitFor(() => expect(screen.queryByTestId("provider-admin")).toBeNull());
    expect(screen.getByText(/当前后端未提供 Provider 管理 API/)).toBeInTheDocument();
  });
});


describe("provider admin stale current model", () => {
  it("keeps the session selection visible but disabled when Registry no longer offers it", () => {
    sessionStore.setModel(null);
    render(
      <ModelControls
        catalog={{
          models: ["beta/m2"],
          current: "alpha/m1",
          currentAvailable: false,
          catalog: [],
        }}
      />
    );

    const select = screen.getByTestId("model-select") as HTMLSelectElement;
    expect(select.value).toBe("alpha/m1");
    const stale = within(select).getByRole("option", { name: /当前不可用/ }) as HTMLOptionElement;
    expect(stale.disabled).toBe(true);
    expect(within(select).getByRole("option", { name: "m2" })).toBeInTheDocument();
  });
});

describe("provider admin contract（§9.3）", () => {
  const model = (id: string, enabled = true) => ({
    id,
    name: id.toUpperCase(),
    enabled,
    effective: enabled,
    context: 8192,
    cost_tier: "mid",
    reasoning_capable: false,
    reasoning: false,
    long_context: false,
    reasoning_control: "unknown",
    wire_protocol: "openai",
    send_tool_choice: true,
    reasoning_split: false,
    reasoning_replay: "configured",
  });

  const provider = (id: string, models: ReturnType<typeof model>[], defaultModel: string) => ({
    id,
    enabled: true,
    effective: true,
    base_url: `https://${id}.example/v1`,
    api_key_env: `${id.toUpperCase()}_KEY`,
    credential_configured: true,
    credential_source: "dotenv",
    default_model: defaultModel,
    models,
  });

  const snapshot = (overrides: Partial<ProviderAdminSnapshot> = {}): ProviderAdminSnapshot => ({
    source: "local",
    mutable: true,
    config_version: "version-9",
    configured_default_model: "alpha/m1",
    runtime_default_model: "alpha/m1",
    restart_required: false,
    effective_provider_count: 2,
    effective_model_count: 3,
    default: {
      model: "alpha/m1",
      runtime_model: "alpha/m1",
      persistence: "dotenv",
      applied: true,
      restart_required: false,
    },
    providers: [
      provider("alpha", [model("m1"), model("m2")], "m1"),
      provider("beta", [model("b1")], "b1"),
    ],
    ...overrides,
  } as ProviderAdminSnapshot);

  type Call = { url: string; method: string; body: Record<string, unknown> };

  const json = (body: unknown, status = 200) =>
    new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

  const stubFetch = (
    route: (call: Call) => Response | undefined,
    initial: ProviderAdminSnapshot = snapshot()
  ): Call[] => {
    const calls: Call[] = [];
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = (init?.method ?? "GET").toUpperCase();
      const body = init?.body ? (JSON.parse(String(init.body)) as Record<string, unknown>) : {};
      const call = { url, method, body };
      calls.push(call);
      const custom = route(call);
      if (custom) return custom;
      if (url === "/api/v1/providers" && method === "GET") return json(initial);
      if (url.startsWith("/api/v1/models")) return json(MODEL_CATALOG);
      return json({});
    }));
    return calls;
  };

  it("全局默认模型走 POST default-model，body 只带 model，并按 default.applied 展示已生效", async () => {
    const calls = stubFetch((call) =>
      call.url === "/api/v1/providers/default-model" && call.method === "POST"
        ? json(snapshot({
            configured_default_model: "beta/b1",
            runtime_default_model: "beta/b1",
            default: {
              model: "beta/b1",
              runtime_model: "beta/b1",
              persistence: "dotenv",
              applied: true,
              restart_required: false,
            },
          }))
        : undefined
    );

    render(<ProviderManager />);
    await screen.findByTestId("provider-alpha");
    fireEvent.change(screen.getByLabelText("全局默认模型"), { target: { value: "beta/b1" } });

    await waitFor(() => expect(calls.some((call) => call.url === "/api/v1/providers/default-model")).toBe(true));
    const call = calls.find((item) => item.url === "/api/v1/providers/default-model")!;
    expect(call.body).toEqual({ model: "beta/b1" });
    expect(screen.getAllByText("已生效").length).toBeGreaterThan(0);
  });

  it("停用默认模型失败时展示可读原因，且模型级写入携带 expected_version", async () => {
    const calls = stubFetch((call) =>
      call.url === "/api/v1/providers/alpha/models/m1" && call.method === "PUT"
        ? json({ error: "default_model_cannot_disable", detail: "该模型是当前默认模型，先切换默认模型再停用。" }, 422)
        : undefined
    );

    render(<ProviderManager />);
    await screen.findByTestId("provider-alpha");
    fireEvent.click(screen.getByRole("button", { name: "启停 m1" }));

    await waitFor(() =>
      expect(screen.getAllByRole("alert").some((node) => node.textContent?.includes("先切换默认模型再停用"))).toBe(true)
    );
    const call = calls.find((item) => item.method === "PUT")!;
    expect(call.body.expected_version).toBe("version-9");
    expect((call.body.model as Record<string, unknown>).enabled).toBe(false);
  });

  it("编辑期间后台快照前进也使用打开时的 CAS 版本，不静默覆盖其他修改", async () => {
    let current = snapshot();
    const calls = stubFetch((call) => {
      if (call.url === "/api/v1/providers" && call.method === "GET") return json(current);
      if (call.url === "/api/v1/providers/alpha/models/m1" && call.method === "PUT") {
        return json({ error: "provider_config_conflict", detail: "版本冲突" }, 409);
      }
      return undefined;
    });
    render(<ProviderManager />);
    await screen.findByTestId("provider-alpha");
    fireEvent.click(screen.getByRole("button", { name: "编辑模型 m1" }));
    const form = screen.getByRole("region", { name: "编辑" });
    fireEvent.change(within(form).getByLabelText("显示名"), { target: { value: "Keep my draft" } });
    current = snapshot({ config_version: "version-10" });
    fireEvent.click(screen.getByRole("button", { name: "刷新" }));
    await waitFor(() => expect(calls.filter((call) => call.method === "GET" && call.url === "/api/v1/providers").length).toBe(2));
    fireEvent.click(within(form).getByRole("button", { name: "保存" }));
    await waitFor(() => expect(calls.some((call) => call.method === "PUT")).toBe(true));
    expect(calls.find((call) => call.method === "PUT")!.body.expected_version).toBe("version-9");
    expect(within(form).getByLabelText("显示名")).toHaveValue("Keep my draft");
    expect(screen.getAllByRole("alert").some((node) => node.textContent?.includes("版本冲突"))).toBe(true);
  });

  it("模型级编辑只提交可写字段，不回传 effective/credential_* 事实", async () => {
    const calls = stubFetch((call) =>
      call.url === "/api/v1/providers/alpha/models/m1" && call.method === "PUT"
        ? json(snapshot())
        : undefined
    );

    render(<ProviderManager />);
    await screen.findByTestId("provider-alpha");
    fireEvent.click(screen.getByRole("button", { name: "编辑模型 m1" }));
    const form = screen.getByRole("region", { name: "编辑" });
    fireEvent.change(within(form).getByLabelText("显示名"), { target: { value: "M One X" } });
    fireEvent.click(within(form).getByRole("button", { name: "保存" }));

    await waitFor(() => expect(calls.some((call) => call.method === "PUT")).toBe(true));
    const put = calls.find((call) => call.method === "PUT")!;
    const payload = put.body.model as Record<string, unknown>;
    expect(payload.name).toBe("M One X");
    expect(payload).not.toHaveProperty("effective");
    expect(payload).not.toHaveProperty("credential_source");
    expect(payload).not.toHaveProperty("credential_configured");
  });

  it("删除模型必须先确认，确认后 DELETE 携带 expected_version", async () => {
    const calls = stubFetch((call) =>
      call.url.startsWith("/api/v1/providers/alpha/models/m1") && call.method === "DELETE"
        ? json(snapshot())
        : undefined
    );
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(false);

    render(<ProviderManager />);
    await screen.findByTestId("provider-alpha");
    fireEvent.click(screen.getByRole("button", { name: "删除 m1" }));
    await waitFor(() => expect(confirmSpy).toHaveBeenCalled());
    expect(calls.some((call) => call.method === "DELETE")).toBe(false);

    confirmSpy.mockReturnValue(true);
    fireEvent.click(screen.getByRole("button", { name: "删除 m1" }));
    await waitFor(() => expect(calls.some((call) => call.method === "DELETE")).toBe(true));
    const del = calls.find((call) => call.method === "DELETE")!;
    expect(del.url).toContain("expected_version=version-9");
    confirmSpy.mockRestore();
  });

  it("source=env 只读：写入口禁用并给出环境变量说明", async () => {
    stubFetch(() => undefined, snapshot({ source: "env", mutable: false }));

    render(<ProviderManager />);
    await screen.findByTestId("provider-alpha");
    expect(screen.getByText(/MODEL_PROVIDERS 环境变量拥有/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "+ 添加服务商" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "启停 m1" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "编辑模型 m1" })).toBeDisabled();
  });

  it("版本冲突 409：展示冲突 banner，刷新按钮重新拉取真实快照", async () => {
    const calls = stubFetch((call) =>
      call.url === "/api/v1/providers/alpha" && call.method === "PATCH"
        ? json({ error: "provider_config_conflict", detail: "配置已被其他页面修改", current_version: "version-10" }, 409)
        : undefined
    );

    render(<ProviderManager />);
    await screen.findByTestId("provider-alpha");
    const before = calls.filter((call) => call.url === "/api/v1/providers" && call.method === "GET").length;
    fireEvent.click(within(screen.getByTestId("provider-alpha")).getByRole("button", { name: "停用" }));

    await waitFor(() =>
      expect(screen.getAllByRole("alert").some((node) => node.textContent?.includes("配置已被其他页面修改"))).toBe(true)
    );
    const banner = screen.getAllByRole("alert").find((node) => node.textContent?.includes("配置已被其他页面修改"))!;
    fireEvent.click(within(banner).getByRole("button", { name: "刷新" }));
    await waitFor(() =>
      expect(calls.filter((call) => call.url === "/api/v1/providers" && call.method === "GET").length).toBeGreaterThan(before)
    );
  });

  it("default.restart_required=true 时提示需重启而不是已生效", async () => {
    stubFetch(() => undefined, snapshot({
      restart_required: true,
      default: {
        model: "alpha/m1",
        runtime_model: "alpha/m0",
        persistence: "dotenv",
        applied: false,
        restart_required: true,
      },
    }));

    render(<ProviderManager />);
    await screen.findByTestId("provider-alpha");
    expect(screen.getAllByText("需重启").length).toBeGreaterThan(0);
    expect(screen.getByText(/重启服务或新会话后生效/)).toBeInTheDocument();
  });

  it("清除 Key 需确认，确认后提交空 api_key", async () => {
    const calls = stubFetch((call) =>
      call.url === "/api/v1/providers/alpha/credential" && call.method === "PUT" ? json(snapshot()) : undefined
    );
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(true);

    render(<ProviderManager />);
    await screen.findByTestId("provider-alpha");
    fireEvent.click(within(screen.getByTestId("provider-alpha")).getByRole("button", { name: "清除 Key" }));

    await waitFor(() => expect(calls.some((call) => call.url.includes("/credential"))).toBe(true));
    const put = calls.find((call) => call.url.includes("/credential"))!;
    expect(put.body).toEqual({ api_key: "" });
    confirmSpy.mockRestore();
  });

  it("模型保存往返保留 reasoning 与 long_context（不静默清零）", async () => {
    const alpha = provider("alpha", [{ ...model("m1"), reasoning: true, long_context: true }, model("m2")], "m1");
    const calls = stubFetch(
      (call) => (call.url === "/api/v1/providers/alpha/models/m1" && call.method === "PUT" ? json(snapshot()) : undefined),
      snapshot({ providers: [alpha, provider("beta", [model("b1")], "b1")] })
    );

    render(<ProviderManager />);
    await screen.findByTestId("provider-alpha");
    fireEvent.click(screen.getByRole("button", { name: "编辑模型 m1" }));
    const form = screen.getByRole("region", { name: "编辑" });
    fireEvent.click(within(form).getByRole("button", { name: "保存" }));

    await waitFor(() => expect(calls.some((call) => call.method === "PUT")).toBe(true));
    const payload = calls.find((call) => call.method === "PUT")!.body.model as Record<string, unknown>;
    expect(payload.reasoning).toBe(true);
    expect(payload.long_context).toBe(true);
  });

  it("快速接入预设服务商：自动填端点/变量，模型 ID 成为默认，密钥不回显", async () => {
    const calls = stubFetch((call) =>
      call.url === "/api/v1/providers" && call.method === "POST" ? json(snapshot()) : undefined
    );
    render(<ProviderManager />);
    await screen.findByTestId("provider-alpha");
    fireEvent.click(screen.getByRole("button", { name: "+ 添加服务商" }));
    const form = screen.getByTestId("provider-editor");
    fireEvent.change(within(form).getByLabelText("服务商模板"), { target: { value: "minimax" } });
    expect(within(form).getByLabelText("Provider ID")).toHaveValue("minimax");
    expect(within(form).getByLabelText("Base URL")).toHaveValue("https://api.minimax.chat/v1");
    fireEvent.change(within(form).getByLabelText("Model ID"), { target: { value: "MiniMax-M3.1-Flash" } });
    fireEvent.change(within(form).getByLabelText("API Key"), { target: { value: "fake-secret-for-test" } });
    expect(document.body.textContent).not.toContain("fake-secret-for-test");
    fireEvent.click(within(form).getByRole("button", { name: "保存并热重载" }));
    await waitFor(() => expect(calls.some((call) => call.method === "POST" && call.url === "/api/v1/providers")).toBe(true));
    const body = calls.find((call) => call.method === "POST" && call.url === "/api/v1/providers")!.body;
    const payload = body.provider as Record<string, unknown>;
    expect(payload.api_key_env).toBe("MINIMAX_API_KEY");
    expect(payload.default_model).toBe("MiniMax-M3.1-Flash");
    expect((payload.models as Array<Record<string, unknown>>)[0]!.id).toBe("MiniMax-M3.1-Flash");
    expect(body.expected_version).toBe("version-9");
    expect(body.api_key).toBe("fake-secret-for-test");
    expect(payload).not.toHaveProperty("api_key");
  });

  it("搜索按服务商和模型过滤，搜索匹配时展开非默认服务商", async () => {
    stubFetch(() => undefined);
    render(<ProviderManager />);
    await screen.findByTestId("provider-alpha");
    const input = screen.getByLabelText("搜索服务商或模型");
    fireEvent.change(input, { target: { value: "b1" } });
    expect(screen.queryByTestId("provider-alpha")).toBeNull();
    const beta = screen.getByTestId("provider-beta");
    expect(within(beta).getByRole("button", { name: /beta/ })).toHaveAttribute("aria-expanded", "true");
    expect(within(beta).getAllByText("B1").length).toBeGreaterThan(0);
    fireEvent.change(input, { target: { value: "no-such-model" } });
    expect(screen.getByText(/没有匹配的服务商或模型/)).toBeInTheDocument();
    fireEvent.change(input, { target: { value: "" } });
    expect(screen.getByTestId("provider-alpha")).toBeInTheDocument();
    expect(within(screen.getByTestId("provider-beta")).getByRole("button", { name: /beta/ }))
      .toHaveAttribute("aria-expanded", "false");
  });

  it("模型高级参数默认收起，展开后可编辑且不会丢失原有能力字段", async () => {
    const calls = stubFetch((call) =>
      call.url === "/api/v1/providers/alpha/models/m1" && call.method === "PUT" ? json(snapshot()) : undefined
    );
    render(<ProviderManager />);
    await screen.findByTestId("provider-alpha");
    fireEvent.click(screen.getByRole("button", { name: "编辑模型 m1" }));
    const form = screen.getByRole("region", { name: "编辑" });
    const advanced = within(form).getByText(/高级模型参数/).closest("details") as HTMLDetailsElement;
    expect(advanced.open).toBe(false);
    fireEvent.click(within(advanced).getByText(/高级模型参数/));
    expect(advanced.open).toBe(true);
    expect(within(form).getByLabelText("协议")).toHaveValue("openai");
    fireEvent.click(within(form).getByRole("button", { name: "保存" }));
    await waitFor(() => expect(calls.some((call) => call.method === "PUT")).toBe(true));
    const payload = calls.find((call) => call.method === "PUT")!.body.model as Record<string, unknown>;
    expect(payload.reasoning_replay).toBe("configured");
    expect(payload.send_tool_choice).toBe(true);
    expect(payload).not.toHaveProperty("effective");
  });

  it("发现列表标记已配置模型并禁止重复选择", async () => {
    stubFetch((call) =>
      call.url === "/api/v1/providers/discover-models" && call.method === "POST"
        ? json({ candidates: [{ id: "m1", name: "Existing" }, { id: "m3", name: "New Model" }], latency_ms: 10 })
        : undefined
    );
    render(<ProviderManager />);
    await screen.findByTestId("provider-alpha");
    fireEvent.click(within(screen.getByTestId("provider-alpha")).getByRole("button", { name: "+ 添加模型" }));
    fireEvent.click(screen.getByRole("button", { name: "发现模型" }));
    expect(await screen.findByLabelText(/Existing/)).toBeDisabled();
    const input = screen.getByLabelText("搜索发现的模型");
    fireEvent.change(input, { target: { value: "New Model" } });
    expect(screen.queryByLabelText(/Existing/)).toBeNull();
    expect(screen.getByLabelText(/New Model/)).not.toBeDisabled();
  });

  it("选择已有服务商模板可直接跳转到模型列表，不重复创建 Provider", async () => {
    const calls = stubFetch(() => undefined);
    render(<ProviderManager />);
    await screen.findByTestId("provider-alpha");
    fireEvent.click(screen.getByRole("button", { name: "+ 添加服务商" }));
    const form = screen.getByTestId("provider-editor");
    fireEvent.change(within(form).getByLabelText("Provider ID"), { target: { value: "alpha" } });
    fireEvent.click(within(form).getByRole("button", { name: "查看现有服务商并添加模型" }));
    expect(screen.queryByTestId("provider-editor")).toBeNull();
    expect(screen.getByLabelText("搜索服务商或模型")).toHaveValue("alpha");
    expect(screen.getByTestId("provider-alpha")).toBeInTheDocument();
    expect(calls.some((call) => call.method === "POST" && call.url === "/api/v1/providers")).toBe(false);
  });

  it("Qwen 模板自动填兼容端点，用户仍可修改而不写入真实凭证", async () => {
    stubFetch(() => undefined);
    render(<ProviderManager />);
    await screen.findByTestId("provider-alpha");
    fireEvent.click(screen.getByRole("button", { name: "+ 添加服务商" }));
    const form = screen.getByTestId("provider-editor");
    fireEvent.change(within(form).getByLabelText("服务商模板"), { target: { value: "qwen" } });
    expect(within(form).getByLabelText("Provider ID")).toHaveValue("qwen");
    expect(within(form).getByLabelText("Base URL"))
      .toHaveValue("https://dashscope.aliyuncs.com/compatible-mode/v1");
    const advanced = within(form).getByText(/高级设置/).closest("details") as HTMLDetailsElement;
    fireEvent.click(within(advanced).getByText(/高级设置/));
    expect(within(form).getByLabelText("API Key 环境变量")).toHaveValue("DASHSCOPE_API_KEY");
  });

  it("高级模型设置支持图片输入与推理协议，不丢失旧字段", async () => {
    const calls = stubFetch((call) =>
      call.url === "/api/v1/providers/alpha/models/m1" && call.method === "PUT" ? json(snapshot()) : undefined
    );
    render(<ProviderManager />);
    await screen.findByTestId("provider-alpha");
    fireEvent.click(screen.getByRole("button", { name: "编辑模型 m1" }));
    const form = screen.getByRole("region", { name: "编辑" });
    const advanced = within(form).getByText(/高级模型参数/).closest("details") as HTMLDetailsElement;
    fireEvent.click(within(advanced).getByText(/高级模型参数/));
    fireEvent.click(within(form).getByLabelText("支持图片输入"));
    fireEvent.change(within(form).getByLabelText("推理控制协议"), { target: { value: "always_on_effort" } });
    fireEvent.click(within(form).getByRole("button", { name: "保存" }));
    await waitFor(() => expect(calls.some((call) => call.method === "PUT")).toBe(true));
    const payload = calls.find((call) => call.method === "PUT")!.body.model as Record<string, unknown>;
    expect(payload.input_modalities).toEqual(["text", "image"]);
    expect(payload.multimodal).toBe(true);
    expect(payload.reasoning_control).toBe("always_on_effort");
    expect(payload.reasoning_replay).toBe("configured");
  });

  it("无密钥的本地端点不误报缺少 API Key", async () => {
    const local = {
      ...provider("local", [model("local-model")], "local-model"),
      base_url: "http://127.0.0.1:8901/v1",
      api_key_env: "",
      credential_configured: false,
      credential_source: "none",
    };
    stubFetch(() => undefined, snapshot({ providers: [local] }));
    render(<ProviderManager />);
    const card = await screen.findByTestId("provider-local");
    expect(within(card).getByText(/本地端点 · 无需 API Key/)).toBeInTheDocument();
    expect(within(card).queryByRole("button", { name: "配置 API Key" })).toBeNull();
  });

  it("批量添加部分成功后只重试剩余模型，不重复提交已成功项", async () => {
    const withM3 = snapshot({
      config_version: "version-10",
      providers: [provider("alpha", [model("m1"), model("m2"), model("m3")], "m1"),
        provider("beta", [model("b1")], "b1")],
    });
    const withBoth = snapshot({
      config_version: "version-11",
      providers: [provider("alpha", [model("m1"), model("m2"), model("m3"), model("m4")], "m1"),
        provider("beta", [model("b1")], "b1")],
    });
    let current = snapshot();
    let m4Attempts = 0;
    const calls = stubFetch((call) => {
      if (call.url === "/api/v1/providers" && call.method === "GET") return json(current);
      if (call.url === "/api/v1/providers/discover-models" && call.method === "POST") {
        return json({ candidates: [{ id: "m3", name: "M Three" }, { id: "m4", name: "M Four" }] });
      }
      if (call.url === "/api/v1/providers/alpha/models" && call.method === "POST") {
        const id = (call.body.model as Record<string, unknown>).id;
        if (id === "m3") { current = withM3; return json(current); }
        if (id === "m4" && ++m4Attempts === 1) {
          return json({ error: "provider_config_conflict", detail: "版本冲突，请刷新" }, 409);
        }
        if (id === "m4") { current = withBoth; return json(current); }
      }
      return undefined;
    });
    render(<ProviderManager />);
    await screen.findByTestId("provider-alpha");
    fireEvent.click(within(screen.getByTestId("provider-alpha")).getByRole("button", { name: "+ 添加模型" }));
    fireEvent.click(screen.getByRole("button", { name: "发现模型" }));
    fireEvent.click(await screen.findByLabelText(/M Three/));
    fireEvent.click(screen.getByLabelText(/M Four/));
    fireEvent.click(screen.getByRole("button", { name: "添加所选（2）" }));
    await waitFor(() => expect(m4Attempts).toBe(1));
    await waitFor(() => expect(screen.getByRole("button", { name: "添加所选（1）" })).toBeEnabled());
    expect(screen.getByLabelText(/M Three/)).toBeDisabled();
    expect(screen.getByLabelText(/M Three/)).not.toBeChecked();
    fireEvent.click(screen.getByRole("button", { name: "添加所选（1）" }));
    await waitFor(() => expect(m4Attempts).toBe(2));
    await waitFor(() => expect(screen.queryByRole("button", { name: /添加所选/ })).toBeNull());
    const posts = calls.filter((call) => call.url === "/api/v1/providers/alpha/models" && call.method === "POST");
    expect(posts.map((call) => (call.body.model as Record<string, unknown>).id)).toEqual(["m3", "m4", "m4"]);
    expect(posts.map((call) => call.body.expected_version)).toEqual(["version-9", "version-10", "version-10"]);
  });

  it("写入已接受但回读失败时阻止重复添加，刷新核对后清除已存在项", async () => {
    const withM3 = snapshot({
      config_version: "version-10",
      providers: [provider("alpha", [model("m1"), model("m2"), model("m3")], "m1"),
        provider("beta", [model("b1")], "b1")],
    });
    let reads = 0;
    let posts = 0;
    const calls = stubFetch((call) => {
      if (call.url === "/api/v1/providers" && call.method === "GET") {
        reads += 1;
        return reads === 1 ? json(snapshot()) : reads <= 3 ? json({ detail: "unavailable" }, 503) : json(withM3);
      }
      if (call.url === "/api/v1/providers/discover-models" && call.method === "POST") {
        return json({ candidates: [{ id: "m3", name: "M Three" }] });
      }
      if (call.url === "/api/v1/providers/alpha/models" && call.method === "POST") {
        posts += 1;
        return json({ detail: "accepted" });
      }
      return undefined;
    });
    render(<ProviderManager />);
    await screen.findByTestId("provider-alpha");
    fireEvent.click(within(screen.getByTestId("provider-alpha")).getByRole("button", { name: "+ 添加模型" }));
    fireEvent.click(screen.getByRole("button", { name: "发现模型" }));
    fireEvent.click(await screen.findByLabelText(/M Three/));
    fireEvent.click(screen.getByRole("button", { name: "添加所选（1）" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "刷新并核对" })).toBeInTheDocument());
    expect(screen.getByRole("button", { name: "添加所选（1）" })).toBeDisabled();
    expect(posts).toBe(1);
    fireEvent.click(screen.getByRole("button", { name: "刷新并核对" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "添加所选（0）" })).toBeDisabled());
    expect(screen.getByLabelText(/M Three/)).toBeDisabled();
    expect(screen.getByLabelText(/M Three/)).not.toBeChecked();
    expect(posts).toBe(1);
    expect(calls.filter((call) => call.url === "/api/v1/providers/alpha/models" && call.method === "POST")).toHaveLength(1);
  });

  it("发现模型后勾选添加：只写被选中的模型，不自动保存其它字段", async () => {
    const calls = stubFetch((call) => {
      if (call.url === "/api/v1/providers/discover-models" && call.method === "POST") {
        return json({ candidates: [{ id: "m3", name: "M Three", context_window: 65536 }], latency_ms: 12 });
      }
      if (call.url === "/api/v1/providers/alpha/models" && call.method === "POST") {
        return json(snapshot({
          config_version: "version-10",
          providers: [provider("alpha", [model("m1"), model("m2"), model("m3")], "m1"),
            provider("beta", [model("b1")], "b1")],
        }));
      }
      return undefined;
    });

    render(<ProviderManager />);
    await screen.findByTestId("provider-alpha");
    fireEvent.click(within(screen.getByTestId("provider-alpha")).getByRole("button", { name: "+ 添加模型" }));
    fireEvent.click(screen.getByRole("button", { name: "发现模型" }));
    const candidate = await screen.findByLabelText(/M Three/);
    fireEvent.click(candidate);
    fireEvent.click(screen.getByRole("button", { name: /添加所选/ }));

    await waitFor(() => expect(calls.some((call) => call.method === "POST" && call.url.endsWith("/models"))).toBe(true));
    const add = calls.find((call) => call.method === "POST" && call.url === "/api/v1/providers/alpha/models")!;
    const payload = add.body.model as Record<string, unknown>;
    expect(payload.id).toBe("m3");
    expect(payload.context).toBe(65536);
    expect(add.body.expected_version).toBe("version-9");
  });
});

describe("model selector 分组（C4-lite）", () => {
  it("按 Provider 分组并暴露默认模型选项", () => {
    const capability = (id: string, provider: string, providerName: string, displayName: string) => ({
      id,
      provider,
      provider_name: providerName,
      model: id.split("/")[1],
      display_name: displayName,
      context: 8192,
      reasoning_capable: false,
      reasoning_control: "unknown",
      reasoning_control_supported: false,
      reasoning_can_disable: false,
      reasoning_efforts: [],
    });

    render(
      <ModelControls
        catalog={{
          models: ["alpha/m1", "beta/b1"],
          current: "alpha/m1",
          currentSource: "default",
          currentAvailable: true,
          default: "alpha/m1",
          catalog: [
            capability("alpha/m1", "alpha", "Alpha Cloud", "M One"),
            capability("beta/b1", "beta", "Beta", "B One"),
          ],
        }}
      />
    );

    const select = screen.getByTestId("model-select") as HTMLSelectElement;
    const groups = Array.from(select.querySelectorAll("optgroup")).map((node) => node.getAttribute("label"));
    expect(groups).toEqual(["Alpha Cloud", "Beta"]);
    expect(select.options[0].textContent).toBe("默认模型（m1）");
    expect(select.options[1].textContent).toBe("M One");
  });
});
