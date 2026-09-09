// 回归测试：能力探测门控（capability gating）
// 场景：同一份 webui 部署在两类后端——完整内部后端（全能力）与开源精简
// 后端（仅核心对话/会话/工作区/演进）。精简后端缺失的端点必须隐藏入口，
// 而不是让用户点击后收到 404；完整后端必须保持全功能（默认乐观，不误伤）。

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { Sidebar } from "./components/sidebar/Sidebar";
import { RightPanel } from "./components/layout/RightPanel";
import { ContinuityBanner } from "./components/conversation/ContinuityBanner";
import { __resetCapabilitiesForTest, probeSessionCapabilities } from "./core/capabilities";

vi.mock("./core/events", async (importOriginal) => {
  const actual = await importOriginal<typeof import("./core/events")>();
  return { ...actual, initEventStream: vi.fn(() => () => {}) };
});

// ---- fetch stub：按 URL 前缀决定 200/404 ----
type Route = { match: RegExp; status: number; body?: unknown };
let routes: Route[] = [];
const jsonResponse = (status: number, body: unknown) =>
  new Response(JSON.stringify(body ?? {}), {
    status,
    headers: { "Content-Type": "application/json" },
  });
const stubFetch = vi.fn((input: RequestInfo | URL) => {
  const url = String(input);
  for (const r of routes) {
    if (r.match.test(url)) return Promise.resolve(jsonResponse(r.status, r.body));
  }
  return Promise.resolve(jsonResponse(200, []));
});

const SESSION = { id: "s-cap-1", title: "能力探测", updated_at: "2026-09-09", source: "web" };

// 开源精简后端：会话运维端点全部 404，核心端点 200
const OSS_ROUTES: Route[] = [
  { match: /\/api\/v1\/sessions\/__capability_probe__/, status: 404 },
  { match: /\/api\/v1\/sessions\/s-cap-1\/(jobs|continuity)/, status: 404 },
  { match: /\/api\/v1\/attachments\/recent/, status: 404 },
  { match: /\/api\/v1\/fs\/tree/, status: 404 },
  { match: /\/api\/v1\/sessions(\?|$)/, status: 200, body: [SESSION] },
  { match: /\/api\/v1\/sessions\/s-cap-1$/, status: 200, body: SESSION },
  { match: /\/api\/v1\/models/, status: 200, body: { models: [] } },
];

// 完整内部后端：探测端点返回 200/405 → 能力存在
const FULL_ROUTES: Route[] = [
  { match: /\/api\/v1\/sessions\/__capability_probe__/, status: 405 },
  { match: /\/api\/v1\/sessions\/s-cap-1\/(jobs|continuity)/, status: 405 },
  { match: /\/api\/v1\/attachments\/recent/, status: 200, body: { items: [] } },
  { match: /\/api\/v1\/fs\/tree/, status: 200, body: { entries: [] } },
  { match: /\/api\/v1\/sessions(\?|$)/, status: 200, body: [SESSION] },
  { match: /\/api\/v1\/sessions\/s-cap-1$/, status: 200, body: SESSION },
  { match: /\/api\/v1\/sessions\/s-cap-1\/messages/, status: 200, body: [] },
  { match: /\/api\/v1\/models/, status: 200, body: { models: [] } },
];

beforeEach(() => {
  vi.stubGlobal("fetch", stubFetch);
});
afterEach(() => {
  cleanup();
  __resetCapabilitiesForTest();
  routes = [];
});

describe("能力探测门控", () => {
  it("开源精简后端：隐藏会话运维按钮/文件标签/任务面板/连续性横幅", async () => {
    routes = OSS_ROUTES;
    render(
      <>
        <Sidebar collapsed={false} />
        <RightPanel open />
        <ContinuityBanner sessionId="s-cap-1" />
      </>
    );
    // App.tsx 在拿到真实会话 id 后触发会话级探测（jobs/continuity）
    probeSessionCapabilities("s-cap-1");
    await waitFor(
      () => {
        expect(screen.queryByTestId("tab-files")).toBeNull();
      },
      { timeout: 3000 }
    );
    expect(screen.queryByText(/置顶/)).toBeNull();
    expect(screen.queryByTitle(/分支/)).toBeNull();
    expect(screen.queryByText(/后台任务/)).toBeNull();
    expect(screen.queryByText(/跨会话连续性/)).toBeNull();
  });

  it("完整内部后端：默认乐观 + 探测通过 → 全功能保留", async () => {
    routes = FULL_ROUTES;
    render(
      <>
        <Sidebar collapsed={false} />
        <RightPanel open />
      </>
    );
    await waitFor(() => expect(screen.getByTestId("tab-files")).toBeTruthy());
    expect(screen.getByText(/后台任务/)).toBeTruthy();
    expect(screen.getByText(/设置/)).toBeTruthy();
  });

  it("会话级探测：jobs 端点存在但 continuity 缺失 → 各自独立门控", async () => {
    routes = [
      ...FULL_ROUTES.filter((r) => !/continuity/.test(String(r.match))),
      { match: /\/api\/v1\/sessions\/s-cap-1\/continuity/, status: 404 },
    ];
    render(
      <>
        <RightPanel open />
        <ContinuityBanner sessionId="s-cap-1" />
      </>
    );
    probeSessionCapabilities("s-cap-1");
    await waitFor(() => expect(screen.getByText(/后台任务/)).toBeTruthy(), { timeout: 3000 });
    expect(screen.queryByText(/跨会话连续性/)).toBeNull();
  });
});
