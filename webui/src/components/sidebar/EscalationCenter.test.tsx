// P0-5 展示-审批绑定（防 TOCTOU）+ M1 审批可信（2026-11-06 设计书）:
// - 提交体必须带 expected_sha256（=列表返回的 command_sha256）
// - ESC-05（FR-05）: 截断命令未查看完整原文前批准禁用；查看后启用并展示原文
// - ESC-07（FR-07）: 待审走 status=pending 专用查询，不被最新 50 条历史挤出
// - 409 stale_review 提示重新打开并刷新列表；400 missing_expected_sha256 兜底提示
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { EscalationPanel, EscalationWatcher, type EscalationRequest } from "./EscalationCenter";

const SHA = "1f2e3d4c5b6a79880f1e2d3c4b5a69781f2e3d4c5b6a79880f1e2d3c4b5a6978";
const FULL_CMD = "bash -c 'for i in $(seq 1 100000); do shred -u /tmp/build-$i; done' # 完整原文尾部标记-end";

function makeReq(over: Partial<EscalationRequest> = {}): EscalationRequest {
  return {
    id: "esc-1",
    tool_name: "shell",
    command: FULL_CMD.slice(0, 40) + "…（超长展示截断）",
    justification: "批量清理临时构建产物",
    session_id: "s1",
    status: "pending",
    created_at: "2026-10-26T10:00:00Z",
    decided_at: "",
    decided_by: "",
    decision_note: "",
    command_sha256: SHA,
    command_len: FULL_CMD.length,
    command_truncated: true,
    ...over,
  };
}

function ok(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status });
}

/** M1 后 list 端点被调用两次：历史窗口 + pending 专用查询（ESC-07）。 */
function listMock(pending: EscalationRequest[], history: EscalationRequest[] = []) {
  return async (input: RequestInfo | URL) => {
    const url = String(input);
    if (url.includes("status=pending")) return ok({ requests: pending, pending_count: pending.length });
    if (url.includes("/api/v1/escalation/list")) return ok({ requests: history, pending_count: pending.length });
    if (url.includes("/api/v1/escalation/detail")) {
      const id = decodeURIComponent(url.split("id=")[1] || "");
      const req = pending.find((r) => r.id === id);
      if (!req) return ok({ error: "请求不存在" }, 404);
      return ok({ id, command: FULL_CMD, command_sha256: req.command_sha256, command_len: FULL_CMD.length });
    }
    return ok({}, 404);
  };
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("EscalationPanel 审批（P0-5 + ESC-05 完整命令门控）", () => {
  it.each(["human_auth_required", "human_channel_required"])(
    "403 %s → 显示未登录原因和真实登录入口，保持待审",
    async (error) => {
      const req = makeReq({ command: "echo safe", command_truncated: false });
      vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url.includes("/api/v1/escalation/review")) {
          return ok({ error, detail: "必须由浏览器会话审批" }, 403);
        }
        return listMock([req])(input);
      }));
      render(<EscalationPanel />);
      await waitFor(() => expect(screen.getByTestId("esc-approve-esc-1")).toBeEnabled());
      fireEvent.click(screen.getByTestId("esc-approve-esc-1"));
      await waitFor(() => expect(screen.getByTestId("esc-login-required")).toBeInTheDocument());
      expect(screen.getByTestId("esc-panel-msg")).toHaveTextContent("审批未生效");
      expect(screen.getByTestId("esc-login-link")).toHaveAttribute("href", expect.stringContaining("/login?next="));
      expect(screen.getByTestId("esc-item-esc-1")).toBeInTheDocument();
    }
  );

  it("详情区展示 sha256 前 16 位 + command_len + 截断提示；未查看完整命令前批准禁用", async () => {
    const req = makeReq();
    const posts: Array<Record<string, unknown>> = [];
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.includes("/api/v1/escalation/")) {
        const base = await listMock([req])(input);
        if (base.status !== 404) return base;
      }
      if (url.includes("/api/v1/escalation/review")) {
        posts.push(JSON.parse(String(init?.body)) as Record<string, unknown>);
        return ok({ ok: true, request: { ...req, status: "approved" } });
      }
      return ok({}, 404);
    }));

    render(<EscalationPanel />);
    await waitFor(() => expect(screen.getByTestId("esc-item-esc-1")).toBeInTheDocument());
    const hash = screen.getByTestId("esc-hash-esc-1");
    expect(hash).toHaveTextContent(SHA.slice(0, 16));
    expect(hash.textContent ?? "").not.toContain(SHA);
    expect(hash).toHaveTextContent(String(FULL_CMD.length));
    expect(screen.getByTestId("esc-truncated-esc-1")).toHaveTextContent("批准前必须先查看完整命令");

    // ESC-05: 截断命令未查看完整原文 → 批准按钮禁用
    expect(screen.getByTestId("esc-approve-esc-1")).toBeDisabled();

    // 查看完整命令 → 原文展示 → 批准启用 → 提交体带 expected_sha256
    fireEvent.click(screen.getByTestId("esc-view-full-esc-1"));
    await waitFor(() => expect(screen.getByTestId("esc-fullcmd-esc-1")).toHaveTextContent("完整原文尾部标记-end"));
    expect(screen.getByTestId("esc-approve-esc-1")).toBeEnabled();
    fireEvent.click(screen.getByTestId("esc-approve-esc-1"));
    await waitFor(() => expect(posts).toHaveLength(1));
    expect(posts[0]).toMatchObject({ id: "esc-1", decision: "approved", expected_sha256: SHA });
  });

  it("未截断命令不受完整命令门控影响，可直接批准", async () => {
    const req = makeReq({ command: "bash -lc 'echo hi'", command_truncated: false });
    const posts: Array<Record<string, unknown>> = [];
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const base = await listMock([req])(input);
      if (base.status !== 404) return base;
      if (url.includes("/api/v1/escalation/review")) {
        posts.push(JSON.parse(String(init?.body)) as Record<string, unknown>);
        return ok({ ok: true, request: { ...req, status: "approved" } });
      }
      return ok({}, 404);
    }));

    render(<EscalationPanel />);
    await waitFor(() => expect(screen.getByTestId("esc-approve-esc-1")).toBeEnabled());
    expect(screen.queryByTestId("esc-view-full-esc-1")).toBeNull();
    fireEvent.click(screen.getByTestId("esc-approve-esc-1"));
    await waitFor(() => expect(posts).toHaveLength(1));
    expect(posts[0]).toMatchObject({ expected_sha256: SHA });
  });

  it("409 stale_review → 提示待审内容已变化并刷新列表", async () => {
    const req = makeReq();
    const posts: Array<Record<string, unknown>> = [];
    const calls: string[] = [];
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      calls.push(url);
      const base = await listMock([req])(input);
      if (base.status !== 404) return base;
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
    // 先查看完整命令解除门控，再批准触发 409
    fireEvent.click(screen.getByTestId("esc-view-full-esc-1"));
    await waitFor(() => expect(screen.getByTestId("esc-fullcmd-esc-1")).toBeInTheDocument());
    const reviewIdx = calls.length;
    fireEvent.click(screen.getByTestId("esc-approve-esc-1"));
    await waitFor(() => expect(screen.getByTestId("esc-panel-msg")).toHaveTextContent("待审内容已变化，请重新打开"));
    expect(posts[0]).toMatchObject({ id: "esc-1", expected_sha256: SHA });
    const listCallsAfter = calls.filter((u, i) => u.includes("/api/v1/escalation/list") && i > reviewIdx).length;
    expect(listCallsAfter).toBeGreaterThan(0);
  });

  it("400 missing_expected_sha256（不应发生）→ 兜底提示重新打开详情", async () => {
    const req = makeReq({ command_sha256: "", command_truncated: false });
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      const base = await listMock([req])(input);
      if (base.status !== 404) return base;
      if (url.includes("/api/v1/escalation/review")) {
        return new Response(
          JSON.stringify({ error: "missing_expected_sha256", detail: "审批请求必须携带 expected_sha256" }),
          { status: 400 }
        );
      }
      return ok({}, 404);
    }));

    render(<EscalationPanel />);
    await waitFor(() => expect(screen.getByTestId("esc-approve-esc-1")).toBeEnabled());
    fireEvent.click(screen.getByTestId("esc-approve-esc-1"));
    await waitFor(() => expect(screen.getByTestId("esc-panel-msg")).toHaveTextContent("审批缺少命令哈希绑定"));
  });
});

describe("EscalationPanel/Watcher 待审独立查询（ESC-07）", () => {
  it("历史窗口不含 pending 时，待审区仍渲染专用查询返回的 pending 项", async () => {
    const squeezed = makeReq({ id: "esc-old-pending", created_at: "2026-10-25T09:00:00Z" });
    const history = Array.from({ length: 50 }, (_, i) =>
      makeReq({ id: `esc-hist-${i}`, status: "denied", decided_at: "2026-10-26T11:00:00Z", command: `denied-case-${i}`, command_truncated: false })
    );
    vi.stubGlobal("fetch", vi.fn(listMock([squeezed], history)));

    render(<EscalationPanel />);
    await waitFor(() => expect(screen.getByTestId("esc-item-esc-old-pending")).toBeInTheDocument());
    // 专用查询 URL 必须带 status=pending（穿透历史窗口）
    const urls = (vi.mocked(fetch) as unknown as { mock: { calls: Array<[RequestInfo | URL]> } }).mock.calls.map(String);
    expect(urls.some((u) => u.includes("status=pending"))).toBe(true);
    // 历史区渲染最近记录，待审徽标计数 ≥ 1
    expect(screen.getByText(/待审批 \(1\)/)).toBeInTheDocument();
    expect(screen.getByText("denied-case-0")).toBeInTheDocument();
  });

  it("Watcher 弹窗同样使用 pending 专用查询", async () => {
    const req = makeReq();
    vi.stubGlobal("fetch", vi.fn(listMock([req])));
    render(<EscalationWatcher />);
    await waitFor(() => expect(screen.getByTestId("esc-modal")).toBeInTheDocument());
    expect(screen.getByTestId("esc-item-esc-1")).toBeInTheDocument();
  });
});

describe("EscalationWatcher 可见审批反馈", () => {
  it("403 human_channel_required → 弹窗固定区域显示登录入口，申请仍待审", async () => {
    const req = makeReq({ command: "verify receipt", command_truncated: false, request_kind: "verify_receipt" });
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      if (String(input).includes("/api/v1/escalation/review")) {
        return ok({ error: "human_channel_required" }, 403);
      }
      return listMock([req])(input);
    }));
    render(<EscalationWatcher />);
    await waitFor(() => expect(screen.getByTestId("esc-modal")).toBeInTheDocument());
    fireEvent.click(screen.getByTestId("esc-approve-esc-1"));
    await waitFor(() => expect(screen.getByTestId("esc-login-required")).toBeInTheDocument());
    expect(screen.getByTestId("esc-modal-feedback")).toHaveTextContent("审批未生效");
    expect(screen.getByTestId("esc-login-link")).toHaveAttribute("href", expect.stringContaining("/login?next="));
    // 反馈在可滚动命令区之外：即使命令很长，也不会被卷到看不见。
    expect(screen.getByTestId("esc-login-required").parentElement).toHaveClass("v2-esc-modal");
    expect(screen.getByTestId("esc-item-esc-1")).toBeInTheDocument();
  });

  it("提交期间按钮禁用且显示处理中，拒绝响应不误报成功", async () => {
    const req = makeReq({ command: "verify receipt", command_truncated: false });
    let settle!: (r: Response) => void;
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      if (String(input).includes("/api/v1/escalation/review")) {
        return new Promise<Response>((resolve) => { settle = resolve; });
      }
      return listMock([req])(input);
    }));
    render(<EscalationWatcher />);
    await waitFor(() => expect(screen.getByTestId("esc-modal")).toBeInTheDocument());
    const approve = screen.getByTestId("esc-approve-esc-1");
    fireEvent.click(approve);
    expect(approve).toBeDisabled();
    expect(approve).toHaveTextContent("处理中");
    expect(screen.getByTestId("esc-modal-feedback")).toHaveTextContent("正在提交审批");
    await act(async () => { settle(ok({ error: "human_channel_required" }, 403)); });
    expect(approve).toBeEnabled();
    expect(approve).toHaveTextContent("批准");
    expect(screen.getByTestId("esc-modal-feedback")).toHaveTextContent("审批未生效");
  });
});

describe("提权审批非阻塞及结果核实", () => {
  it("单条审批不锁其他卡片，弹窗和侧栏共享同一请求的提交锁", async () => {
    const first = makeReq({ id: "esc-parallel-a", command: "echo a", command_truncated: false });
    const second = makeReq({ id: "esc-parallel-b", command: "echo b", command_truncated: false });
    const posts: string[] = [];
    let settle!: (r: Response) => void;
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      if (String(input).includes("/api/v1/escalation/review")) {
        posts.push(JSON.parse(String(init?.body)).id);
        return new Promise<Response>((resolve) => { settle = resolve; });
      }
      return listMock([first, second])(input);
    }));
    render(<><EscalationWatcher /><EscalationPanel /></>);
    await waitFor(() => expect(screen.getAllByTestId("esc-approve-esc-parallel-a")).toHaveLength(2));
    const [a, aOther] = screen.getAllByTestId("esc-approve-esc-parallel-a");
    fireEvent.click(a);
    expect(a).toBeDisabled();
    expect(aOther).toBeDisabled();
    fireEvent.click(aOther);
    expect(posts).toEqual([first.id]);
    screen.getAllByTestId("esc-approve-esc-parallel-b").forEach((button) => expect(button).toBeEnabled());
    await act(async () => { settle(ok({ error: "human_channel_required" }, 403)); });
    expect(a).toBeEnabled();
  });

  it("响应体超时后只读核实，待审不代表可重发，重新挂载仍锁定", async () => {
    const req = makeReq({ id: "esc-body-timeout", command: "echo timeout", command_truncated: false });
    let status = "pending";
    let posts = 0;
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.includes("/api/v1/escalation/review")) {
        posts++;
        return { ok: true, status: 200, json: () => new Promise((_, reject) => {
          init?.signal?.addEventListener("abort", () => reject(new Error("aborted")), { once: true });
        }) } as Response;
      }
      if (url.includes("/api/v1/escalation/detail")) return ok({ ...req, status });
      return listMock([req])(input);
    }));
    const view = render(<EscalationPanel />);
    await waitFor(() => expect(screen.getByTestId("esc-approve-esc-body-timeout")).toBeEnabled());
    vi.useFakeTimers();
    try {
      fireEvent.click(screen.getByTestId("esc-approve-esc-body-timeout"));
      await act(async () => { await vi.advanceTimersByTimeAsync(15000); });
      expect(screen.getByTestId("esc-review-state-esc-body-timeout")).toHaveTextContent("不要重复提交");
      expect(screen.getByTestId("esc-approve-esc-body-timeout")).toBeDisabled();
      view.unmount();
    } finally { vi.useRealTimers(); }
    render(<EscalationPanel />);
    await waitFor(() => expect(screen.getByTestId("esc-check-esc-body-timeout")).toBeInTheDocument());
    expect(screen.getByTestId("esc-approve-esc-body-timeout")).toBeDisabled();
    status = "consumed";
    fireEvent.click(screen.getByTestId("esc-check-esc-body-timeout"));
    await waitFor(() => expect(screen.getByTestId("esc-review-state-esc-body-timeout")).toHaveTextContent("令牌已使用"));
    expect(posts).toBe(1);
  });

  it("超时后同一编号的可信详情指纹变化：旧请求保持锁定，来源会话恢复，新编号可独立审批", async () => {
    const original = makeReq({ id: "esc-changed-material", command: "echo old", command_truncated: false });
    const changed = { ...original, command: "echo changed", command_sha256: "cd".repeat(32) };
    const fresh = makeReq({ id: "esc-fresh-material", command: "echo fresh", command_sha256: "ef".repeat(32), command_truncated: false });
    let rows = [original];
    const posts: string[] = [];
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.includes("/api/v1/escalation/review")) {
        const id = JSON.parse(String(init?.body)).id;
        posts.push(id);
        if (id === fresh.id) return ok({ error: "human_channel_required" }, 403);
        return new Promise<Response>((_, reject) => {
          init?.signal?.addEventListener("abort", () => reject(new Error("aborted")), { once: true });
        });
      }
      if (url.includes("/api/v1/escalation/detail")) return ok(changed);
      return listMock(rows)(input);
    }));
    render(<EscalationPanel />);
    const oldButton = await screen.findByTestId(`esc-approve-${original.id}`);
    vi.useFakeTimers();
    try {
      fireEvent.click(oldButton);
      rows = [changed, fresh];
      await act(async () => { await vi.advanceTimersByTimeAsync(15000); });
      expect(screen.getByTestId(`esc-review-state-${original.id}`)).toHaveTextContent("审批材料指纹已变化");
      expect(screen.getByTestId(`esc-review-state-${original.id}`)).toHaveTextContent("不要重复提交旧请求");
      expect(screen.getByTestId(`esc-approve-${original.id}`)).toBeDisabled();
      expect(screen.getByTestId(`esc-origin-${original.id}`)).toHaveTextContent("重新发起审批");
      expect(screen.getByTestId(`esc-approve-${fresh.id}`)).toBeEnabled();
      fireEvent.click(screen.getByTestId(`esc-check-${original.id}`));
      await act(async () => { await vi.advanceTimersByTimeAsync(0); });
      expect(screen.getByTestId(`esc-approve-${original.id}`)).toBeDisabled();
      expect(posts).toEqual([original.id]);
      fireEvent.click(screen.getByTestId(`esc-approve-${fresh.id}`));
      await act(async () => { await vi.advanceTimersByTimeAsync(0); });
      expect(posts).toEqual([original.id, fresh.id]);
    } finally { vi.useRealTimers(); }
  });
});

describe("ESC-08 存储故障前端如实呈现", () => {
  it("list 503 → 错误横幅（esc-store-error）而非歧义空列表", async () => {
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("status=pending")) {
        return new Response(JSON.stringify({ error: "审批存储读取失败（详情见服务端日志）", requests: null, pending_count: null }), { status: 503 });
      }
      return new Response(JSON.stringify({ error: "审批存储读取失败（详情见服务端日志）", requests: null, pending_count: null }), { status: 503 });
    }));
    render(<EscalationPanel />);
    await waitFor(() => expect(screen.getByTestId("esc-store-error")).toBeInTheDocument());
    expect(screen.getByTestId("esc-store-error")).toHaveTextContent("审批存储读取失败");
    expect(screen.getByTestId("esc-store-error")).toHaveTextContent("勿据此判断");
  });
});

// ── M1.1 复审修复批（LFL_Sandbox_Escalation_Implementation_Review_2026-11-06）──

describe("M1.1 R2 错误态保留最后成功快照", () => {
  it("先成功后 503 → 旧快照保留 + 横幅标注可能已过期", async () => {
    vi.useFakeTimers();
    try {
      const req = makeReq();
      let round = 0;
      vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
        round += 1;
        if (round <= 2) return listMock([req])(input);
        return ok({ error: "审批存储读取失败", requests: null, pending_count: null }, 503);
      }));
      render(<EscalationPanel />);
      await act(async () => {
        await vi.advanceTimersByTimeAsync(0);
      });
      expect(screen.getByTestId("esc-item-esc-1")).toBeInTheDocument();
      await act(async () => {
        await vi.advanceTimersByTimeAsync(5100);
      });
      // R2: 503 不得清空旧快照（未知 ≠ 空）
      expect(screen.getByTestId("esc-item-esc-1")).toBeInTheDocument();
      expect(screen.getByTestId("esc-store-error")).toHaveTextContent("过期");
    } finally {
      vi.useRealTimers();
    }
  });

  it("首屏 503 → 不显示『（无待审批提权申请）』", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => ok({ error: "审批存储读取失败" }, 503)));
    render(<EscalationPanel />);
    await waitFor(() => expect(screen.getByTestId("esc-store-error")).toBeInTheDocument());
    expect(screen.queryByText("（无待审批提权申请）")).toBeNull();
  });

  it("Watcher 不可见态 503 → 全局错误 chip 出现", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => ok({ error: "审批存储读取失败" }, 503)));
    render(<EscalationWatcher />);
    await waitFor(() => expect(screen.getByTestId("esc-watch-error")).toBeInTheDocument());
  });
});

describe("M1.1 R3 失效历史可见", () => {
  it("失效（_sig_unverified）pending 在历史区显示『已失效』而非消失", async () => {
    const dead = makeReq({
      id: "esc-dead",
      command: "dead-cmd",
      command_truncated: false,
      _sig_unverified: true,
    });
    vi.stubGlobal("fetch", vi.fn(listMock([], [dead])));
    render(<EscalationPanel />);
    await waitFor(() => expect(screen.getByText("已失效")).toBeInTheDocument());
    expect(screen.getByText("dead-cmd")).toBeInTheDocument();
  });
});

describe("M1.1 R4 真实计数与游标分页", () => {
  it("pending_count 超过已加载 → 显示真实总数 + 加载更多稳定游标续读", async () => {
    const all = Array.from({ length: 60 }, (_, i) =>
      makeReq({ id: `esc-p${i}`, command: `p-cmd-${i}`, command_truncated: false }),
    );
    const calls: string[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url.includes("status=pending")) {
          calls.push(url);
          if (url.includes("before_id=esc-p10")) return ok({ requests: all.slice(0, 10).reverse(), pending_count: 60 });
          return ok({ requests: all.slice(10).reverse(), pending_count: 60 });
        }
        if (url.includes("/api/v1/escalation/list")) return ok({ requests: [] });
        return ok({}, 404);
      }),
    );
    render(<EscalationPanel />);
    await waitFor(() => expect(screen.getByTestId("esc-item-esc-p59")).toBeInTheDocument());
    // R4: 标题显示权威 pending_count（60），而非窗口内数组长度（50）
    expect(screen.getByText(/待审批 \(60\)/)).toBeInTheDocument();
    expect(screen.queryByTestId("esc-item-esc-p0")).toBeNull();
    // R4: 加载更多 → before_id 稳定游标（以已加载最旧 id 定位）
    fireEvent.click(screen.getByTestId("esc-load-more"));
    await waitFor(() => expect(screen.getByTestId("esc-item-esc-p0")).toBeInTheDocument());
    expect(calls.some((u) => u.includes("before_id=esc-p10"))).toBe(true);
    expect(screen.queryByTestId("esc-load-more")).toBeNull();
  });
});

describe("M1.1 R5 查看资格绑定命令指纹", () => {
  it("detail 响应缺 command_sha256 → 原文不展示且批准保持禁用（防降级旁路）", async () => {
    const req = makeReq();
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url.includes("/api/v1/escalation/detail")) {
          return ok({ id: "esc-1", command: FULL_CMD, command_len: FULL_CMD.length }); // 无指纹
        }
        const base = await listMock([req])(input);
        if (base.status !== 404) return base;
        return ok({}, 404);
      }),
    );
    render(<EscalationPanel />);
    await waitFor(() => expect(screen.getByTestId("esc-item-esc-1")).toBeInTheDocument());
    fireEvent.click(screen.getByTestId("esc-view-full-esc-1"));
    // R5: 缺指纹（降级旁路）→ 原文不展示（fail-closed 防钓鱼）+ 批准保持禁用
    await waitFor(() => expect(screen.getByText(/指纹缺失或不一致/)).toBeInTheDocument());
    expect(screen.queryByTestId("esc-fullcmd-esc-1")).toBeNull();
    expect(screen.getByTestId("esc-approve-esc-1")).toBeDisabled();
  });

  it("解锁后待审命令指纹变化（新一轮列表）→ 重新锁定", async () => {
    vi.useFakeTimers();
    try {
      let curSha = SHA;
      const SHA2 = "cd".repeat(32);
      vi.stubGlobal(
        "fetch",
        vi.fn(async (input: RequestInfo | URL) => {
          const url = String(input);
          if (url.includes("/api/v1/escalation/detail")) {
            return ok({ id: "esc-1", command: FULL_CMD, command_sha256: curSha, command_len: FULL_CMD.length });
          }
          const base = await listMock([makeReq({ command_sha256: curSha })])(input);
          if (base.status !== 404) return base;
          return ok({}, 404);
        }),
      );
      render(<EscalationPanel />);
      await act(async () => {
        await vi.advanceTimersByTimeAsync(0);
      });
      fireEvent.click(screen.getByTestId("esc-view-full-esc-1"));
      await act(async () => {
        await vi.advanceTimersByTimeAsync(0);
      });
      expect(screen.getByTestId("esc-approve-esc-1")).toBeEnabled();
      curSha = SHA2; // 新一轮轮询：同 id、不同指纹
      await act(async () => {
        await vi.advanceTimersByTimeAsync(5100);
      });
      expect(screen.getByTestId("esc-approve-esc-1")).toBeDisabled();
    } finally {
      vi.useRealTimers();
    }
  });
});

describe("审批轮询去重", () => {
  it("隐藏标签页暂停审批读取，重新可见时立即恢复", async () => {
    const hidden = vi.spyOn(document, "hidden", "get").mockReturnValue(true);
    const fetchMock = vi.fn(listMock([]));
    vi.stubGlobal("fetch", fetchMock);
    render(<EscalationWatcher />);
    await act(async () => { await Promise.resolve(); });
    expect(fetchMock).not.toHaveBeenCalled();

    hidden.mockReturnValue(false);
    fireEvent(document, new Event("visibilitychange"));
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
  });

  it("同一页面 Watcher 与 Panel 的同时读取共享在途请求", async () => {
    const fetchMock = vi.fn(listMock([]));
    vi.stubGlobal("fetch", fetchMock);
    render(<><EscalationWatcher /><EscalationPanel /></>);
    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
  });
});
