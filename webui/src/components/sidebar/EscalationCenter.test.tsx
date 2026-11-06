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
});

describe("EscalationPanel 审批（P0-5 + ESC-05 完整命令门控）", () => {
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
