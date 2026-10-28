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
    await waitFor(() => expect(screen.getByRole("button", { name: "+ 添加 Provider" })).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "+ 添加 Provider" }));
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
      if (url === "/api/v1/providers/glm" && init?.method === "PUT") {
        putBodies.push(JSON.parse(String(init.body ?? "{}")) as Record<string, unknown>);
        return new Response(JSON.stringify(SNAPSHOT), { status: 200 });
      }
      if (url === "/api/v1/providers") return new Response(JSON.stringify(SNAPSHOT), { status: 200 });
      return new Response(JSON.stringify({}), { status: 200 });
    }));

    render(<ProviderManager />);
    await waitFor(() => expect(screen.getByRole("button", { name: "编辑" })).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "编辑" }));
    const editor = screen.getByTestId("provider-editor");
    expect(within(editor).getByLabelText("推理档位")).toHaveValue("low,high,max");
    expect(within(editor).getByLabelText("默认推理档位")).toHaveValue("max");
    fireEvent.click(within(editor).getByRole("button", { name: "保存并热重载" }));

    await waitFor(() => expect(putBodies).toHaveLength(1));
    const provider = putBodies[0]!.provider as { models: Array<Record<string, unknown>> };
    expect(provider.models[0]!.reasoning_efforts).toEqual(["low", "high", "max"]);
    expect(provider.models[0]!.reasoning_default_effort).toBe("max");
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
    expect(screen.getByRole("button", { name: "+ 添加 Provider" })).toBeDisabled();
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

  it("发现模型后勾选添加：只写被选中的模型，不自动保存其它字段", async () => {
    const calls = stubFetch((call) => {
      if (call.url === "/api/v1/providers/discover-models" && call.method === "POST") {
        return json({ candidates: [{ id: "m3", name: "M Three", context_window: 65536 }], latency_ms: 12 });
      }
      if (call.url === "/api/v1/providers/alpha/models" && call.method === "POST") {
        return json(snapshot());
      }
      return undefined;
    });

    render(<ProviderManager />);
    await screen.findByTestId("provider-alpha");
    fireEvent.click(within(screen.getByTestId("provider-alpha")).getByRole("button", { name: "+ 添加模型" }));
    fireEvent.click(screen.getByRole("button", { name: "发现模型" }));
    const candidate = await screen.findByLabelText("M Three");
    fireEvent.click(candidate);
    fireEvent.click(screen.getByRole("button", { name: "添加所选" }));

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
