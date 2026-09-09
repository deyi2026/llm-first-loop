import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { ProviderManager } from "./components/layout/ProviderManager";
import { RightPanel } from "./components/layout/RightPanel";
import { __resetCapabilitiesForTest } from "./core/capabilities";
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
    reasoning_efforts: ["low", "medium", "high"],
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

  it("添加 Provider 使用当前 config_version，保存后不把 Key 放进界面状态", async () => {
    const createBodies: Record<string, unknown>[] = [];
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
    expect(document.body.textContent).not.toContain("provider-secret-fixture-456");
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
