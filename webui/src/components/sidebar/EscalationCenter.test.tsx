// P0-5 展示-审批绑定（防 TOCTOU）: 审批提交体必须带 expected_sha256（=列表返回的
// command_sha256）；详情区展示命令指纹前 16 位 + 长度；409 stale_review 提示重新打开并
// 刷新列表；400 missing_expected_sha256 作为兜底提示。
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { EscalationPanel, EscalationWatcher, type EscalationRequest } from "./EscalationCenter";

const SHA = "1f2e3d4c5b6a79880f1e2d3c4b5a69781f2e3d4c5b6a79880f1e2d3c4b5a6978";

function makeReq(over: Partial<EscalationRequest> = {}): EscalationRequest {
  return {
    id: "esc-1",
    tool_name: "shell",
    command: "bash -c 'for i in $(seq 1 100000); do …'（超长展示截断）",
    justification: "批量清理临时构建产物",
    session_id: "s1",
    status: "pending",
    created_at: "2026-10-26T10:00:00Z",
    decided_at: "",
    decided_by: "",
    decision_note: "",
    command_sha256: SHA,
    command_len: 4096,
    command_truncated: true,
    ...over,
  };
}

function ok(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status });
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("EscalationPanel 审批（P0-5 展示-审批绑定）", () => {
  it("详情区展示 sha256 前 16 位 + command_len + 截断提示；提交体带 expected_sha256", async () => {
    const req = makeReq();
    const posts: Array<Record<string, unknown>> = [];
    let reviewed = false;
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.includes("/api/v1/escalation/list")) {
        return ok({ requests: reviewed ? [] : [req], pending_count: reviewed ? 0 : 1 });
      }
      if (url.includes("/api/v1/escalation/review")) {
        reviewed = true;
        posts.push(JSON.parse(String(init?.body)) as Record<string, unknown>);
        return ok({ ok: true, request: { ...req, status: "approved" } });
      }
      return ok({}, 404);
    }));

    render(<EscalationPanel />);
    await waitFor(() => expect(screen.getByTestId("esc-item-esc-1")).toBeInTheDocument());
    // 命令指纹：只展示前 16 位，完整哈希不落 DOM
    const hash = screen.getByTestId("esc-hash-esc-1");
    expect(hash).toHaveTextContent(SHA.slice(0, 16));
    expect(hash.textContent ?? "").not.toContain(SHA);
    expect(hash).toHaveTextContent("4096");
    // 截断命令提示：按哈希绑定
    expect(screen.getByTestId("esc-truncated-esc-1")).toHaveTextContent("命令过长，已按哈希绑定，请核对完整命令");

    fireEvent.click(screen.getByRole("button", { name: "批准" }));
    await waitFor(() => expect(posts).toHaveLength(1));
    expect(posts[0]).toMatchObject({ id: "esc-1", decision: "approved", expected_sha256: SHA });
    await waitFor(() => expect(screen.getByTestId("esc-panel-msg")).toHaveTextContent("已批准"));
  });

  it("409 stale_review → 提示待审内容已变化并刷新列表", async () => {
    const req = makeReq();
    const posts: Array<Record<string, unknown>> = [];
    const calls: string[] = [];
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      calls.push(url);
      if (url.includes("/api/v1/escalation/list")) {
        return ok({ requests: [req], pending_count: 1 });
      }
      if (url.includes("/api/v1/escalation/review")) {
        posts.push(JSON.parse(String(init?.body)) as Record<string, unknown>);
        return new Response(
          JSON.stringify({ error: "stale_review", detail: "expected_sha256 与当前待审记录不一致（命令已变化或视图过期）" }),
          { status: 409 }
        );
      }
      return ok({}, 404);
    }));

    render(<EscalationPanel />);
    await waitFor(() => expect(screen.getByTestId("esc-item-esc-1")).toBeInTheDocument());
    const listCallsBefore = calls.filter((u) => u.includes("/api/v1/escalation/list")).length;
    const reviewIdx = calls.length; // 点击前快照

    fireEvent.click(screen.getByRole("button", { name: "批准" }));
    await waitFor(() => expect(screen.getByTestId("esc-panel-msg")).toHaveTextContent("待审内容已变化，请重新打开"));
    // 提交体仍带 expected_sha256；提示后自动刷新列表（review 之后再次拉取 list）
    expect(posts[0]).toMatchObject({ id: "esc-1", expected_sha256: SHA });
    const listCallsAfter = calls.filter((u, i) => u.includes("/api/v1/escalation/list") && i > reviewIdx).length;
    expect(listCallsAfter).toBeGreaterThan(0);
    expect(listCallsBefore).toBeGreaterThanOrEqual(1);
  });

  it("400 missing_expected_sha256（不应发生）→ 兜底提示重新打开详情", async () => {
    const req = makeReq({ command_sha256: "", command_truncated: false });
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/api/v1/escalation/list")) {
        return ok({ requests: [req], pending_count: 1 });
      }
      if (url.includes("/api/v1/escalation/review")) {
        return new Response(
          JSON.stringify({ error: "missing_expected_sha256", detail: "审批请求必须携带 expected_sha256" }),
          { status: 400 }
        );
      }
      return ok({}, 404);
    }));

    render(<EscalationPanel />);
    await waitFor(() => expect(screen.getByTestId("esc-item-esc-1")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "批准" }));
    await waitFor(() => expect(screen.getByTestId("esc-panel-msg")).toHaveTextContent("重新打开详情"));
  });
});

describe("EscalationWatcher 弹窗（与面板共用绑定逻辑）", () => {
  it("弹窗内批准同样提交 expected_sha256", async () => {
    const req = makeReq();
    const posts: Array<Record<string, unknown>> = [];
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.includes("/api/v1/escalation/list")) {
        return ok({ requests: [req], pending_count: 1 });
      }
      if (url.includes("/api/v1/escalation/review")) {
        posts.push(JSON.parse(String(init?.body)) as Record<string, unknown>);
        return ok({ ok: true, request: { ...req, status: "approved" } });
      }
      return ok({}, 404);
    }));

    render(<EscalationWatcher />);
    await waitFor(() => expect(screen.getByTestId("esc-modal")).toBeInTheDocument());
    expect(screen.getByTestId("esc-hash-esc-1")).toHaveTextContent(SHA.slice(0, 16));
    fireEvent.click(screen.getByRole("button", { name: "批准" }));
    await waitFor(() => expect(posts).toHaveLength(1));
    expect(posts[0]).toMatchObject({ id: "esc-1", decision: "approved", expected_sha256: SHA });
  });
});
