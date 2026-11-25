import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { EvolutionPanel } from "./components/sidebar/EvolutionPanel";
import { conversationStore } from "./core/conversation";
import { sessionStore } from "./core/stores";

const baseItem = {
  id: "EVO-test-approval",
  ts: "2026-09-09T00:00:00Z",
  status: "pending_review",
  priority: "high",
  requires_human: false,
  content: "审批链路测试建议",
  impact_hint: "src/example.py",
};

function installFetch(options?: {
  requiresHuman?: boolean;
  reviewStatus?: number;
  reviewBody?: Record<string, unknown>;
  diffStatus?: number;
  diffBody?: Record<string, unknown>;
  sessionId?: string;
  items?: Array<Record<string, unknown>>;
  batchBody?: Record<string, unknown>;
  locatorStatus?: number;
  locatorBody?: Record<string, unknown>;
  switchStatus?: number;
  // EVO-20261125 热修复测试：按次序控制 review/detail/batch 响应；"hang"=请求挂起直到 abort 超时；
  // bodyHang=true=响应头立即返回但响应体永不结束（专测 deadline 必须覆盖 body 解析——修复①）
  reviewSequence?: Array<"hang" | { status: number; body?: Record<string, unknown>; bodyHang?: boolean }>;
  detailSequence?: Array<"fail" | { status?: number; body: Record<string, unknown> }>;
  batchSequence?: Array<"hang" | { bodyHang?: boolean }>;
}) {
  const hangResponse = (init?: RequestInit): Promise<Response> =>
    new Promise((_resolve, reject) => {
      const sig = (init?.signal ?? null) as AbortSignal | null;
      const onAbort = () =>
        reject(Object.assign(new Error("The operation was aborted."), { name: "AbortError" }));
      if (sig?.aborted) onAbort();
      else if (sig) sig.addEventListener("abort", onAbort);
    });
  // 响应头立即返回、响应体永不结束（直到 abort）：deadline 必须覆盖 body 解析，否则调用方永久挂起（修复①）
  const bodyHangResponse = (init?: RequestInit, status = 200): Promise<any> => {
    const sig = (init?.signal ?? null) as AbortSignal | null;
    return Promise.resolve({
      ok: status >= 200 && status < 300,
      status,
      statusText: "OK",
      json: () =>
        new Promise((_resolve, reject) => {
          const onAbort = () =>
            reject(Object.assign(new Error("The operation was aborted."), { name: "AbortError" }));
          if (sig?.aborted) onAbort();
          else if (sig) sig.addEventListener("abort", onAbort);
        }),
    });
  };
  const reviewQueue = options?.reviewSequence ? [...options.reviewSequence] : [];
  const detailQueue = options?.detailSequence ? [...options.detailSequence] : [];
  const batchQueue = options?.batchSequence ? [...options.batchSequence] : [];
  const item = { ...baseItem, requires_human: Boolean(options?.requiresHuman) };
  const listed = options?.items ?? [{ ...item }];
  const calls: Array<{ url: string; init?: RequestInit }> = [];
  // plain-object 响应：避免 undici Response.json() 的流读取被 fake timers 阻塞（EVO-20261125 测试）
  const jsonResponse = (status: number, body: unknown) => ({
    ok: status >= 200 && status < 300,
    status,
    statusText: status >= 200 && status < 300 ? "OK" : "Error",
    json: async () => body,
  });
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit): Promise<any> => {
    const url = String(input);
    calls.push({ url, init });
    if (url.startsWith("/api/v1/evolution/list")) {
      return jsonResponse(200, { suggestions: listed, count: listed.length });
    }
    if (url.startsWith("/api/v1/evolution/detail")) {
      const dq = detailQueue.shift();
      if (dq === "fail") throw new TypeError("Failed to fetch");
      if (dq) return jsonResponse(dq.status ?? 200, dq.body);
      return jsonResponse(200, {
        ...item,
        scope: "runtime",
        content: "完整建议正文第一段\n完整建议正文第二段",
        evidence: "完整证据：来自当前运行事实",
        impact_scope: "Web 演进审批可读性",
        impact_files: ["src/example.py"],
        reason_history: [{ reason: "补充当前证据", at: "2026-09-09T00:05:00Z" }],
      });
    }
    if (url.startsWith("/api/v1/evolution/diff")) {
      return jsonResponse(options?.diffStatus ?? 200, options?.diffBody ?? {
        id: item.id,
        impact_files: ["src/example.py"],
        actions: [{ type: "modify", path: "src/example.py", summary: "调整审批详情展示" }],
        note: "只读摘要（不含 prompt/密钥）",
      });
    }
    if (url.startsWith("/api/v1/evolution/session-locator")) {
      return jsonResponse(
        options?.locatorStatus ?? 200,
        options?.locatorBody ?? {
          ok: true,
          available: true,
          current: true,
          workspace_id: "ws-1",
          workspace_path: "/tmp/ws-1",
        }
      );
    }
    if (url === "/api/v1/workspaces/switch") {
      return jsonResponse(options?.switchStatus ?? 200, { ok: true });
    }
    if (url === "/api/v1/evolution/review-batch") {
      const bq = batchQueue.shift();
      if (bq === "hang") return hangResponse(init);
      if (bq && typeof bq === "object" && (bq as { bodyHang?: boolean }).bodyHang) return bodyHangResponse(init);
      return jsonResponse(200, options?.batchBody ?? { ok_count: 0, fail_count: 0, results: [] });
    }
    if (url === "/api/v1/evolution/review") {
      const rq = reviewQueue.shift();
      if (rq === "hang") return hangResponse(init);
      if (rq?.bodyHang) return bodyHangResponse(init, rq.status);
      if (rq) return jsonResponse(rq.status, rq.body);
      return jsonResponse(
        options?.reviewStatus ?? 200,
        options?.reviewBody ?? {
          ok: true,
          message: "已批准",
          ...(options?.sessionId ? { session_id: options.sessionId } : {}),
        }
      );
    }
    throw new Error(`unexpected fetch ${url}`);
  });
  vi.stubGlobal("fetch", fetchMock);
  return { calls, fetchMock };
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  sessionStore.setCurrentSession("");
  conversationStore.setState({ composerPrefill: null });
  localStorage.clear();
});

describe("EvolutionPanel approval feedback", () => {
  it("opens a full review view with complete suggestion, evidence and diff before approval", async () => {
    const { calls } = installFetch();
    render(<EvolutionPanel />);

    await screen.findByText(baseItem.id);
    fireEvent.click(screen.getByRole("button", { name: "查看详情" }));

    const modal = await screen.findByTestId("evo-detail-modal");
    expect(modal).toBeInTheDocument();
    expect(await screen.findByTestId("evo-detail-content")).toHaveTextContent("完整建议正文第一段");
    expect(screen.getByTestId("evo-detail-content")).toHaveTextContent("完整建议正文第二段");
    expect(screen.getByText("完整证据：来自当前运行事实")).toBeInTheDocument();
    expect(screen.getByText("Web 演进审批可读性")).toBeInTheDocument();
    expect(screen.getByText("src/example.py")).toBeInTheDocument();
    expect(await screen.findByTestId("evo-diff-actions")).toHaveTextContent("modify");
    expect(screen.getByTestId("evo-diff-actions")).toHaveTextContent("调整审批详情展示");
    expect(screen.getByTestId("evo-detail-approve")).toBeInTheDocument();
    expect(screen.getByTestId("evo-detail-reject")).toBeInTheDocument();
    fireEvent.click(screen.getByTestId("evo-detail-approve"));
    expect(screen.getByTestId("evo-confirm-modal")).toBeInTheDocument();
    fireEvent.click(screen.getByText("取消"));
    expect(screen.queryByTestId("evo-confirm-modal")).toBeNull();
    expect(calls.some((call) => call.url.startsWith("/api/v1/evolution/detail"))).toBe(true);
    expect(calls.some((call) => call.url.startsWith("/api/v1/evolution/diff"))).toBe(true);

    fireEvent.click(screen.getByRole("button", { name: "关闭演进建议详情" }));
    expect(screen.queryByTestId("evo-detail-modal")).toBeNull();
  });

  it("keeps full suggestion readable when there is no associated diff", async () => {
    installFetch({ diffStatus: 404, diffBody: { error: "no_diff", detail: "该建议无关联改动。" } });
    render(<EvolutionPanel />);

    await screen.findByText(baseItem.id);
    fireEvent.click(screen.getByRole("button", { name: "查看详情" }));

    expect(await screen.findByTestId("evo-detail-content")).toHaveTextContent("完整建议正文第一段");
    expect(await screen.findByText("该建议无关联改动。")).toBeInTheDocument();
  });
  it("keeps a failed approval dialog open and shows the backend detail inside it", async () => {
    installFetch({
      reviewStatus: 400,
      reviewBody: { error: "evolve_disabled", detail: "演进存储未从生产引擎装配。" },
    });
    render(<EvolutionPanel />);

    await screen.findByText(baseItem.id);
    fireEvent.click(screen.getByText(baseItem.id));
    fireEvent.click(await screen.findByTestId("evo-approve"));
    fireEvent.click(screen.getByTestId("evo-prompt-surface-check"));
    fireEvent.click(screen.getByTestId("evo-confirm-ok"));

    expect(await screen.findByTestId("evo-confirm-message")).toHaveTextContent(
      "演进存储未从生产引擎装配"
    );
    expect(screen.getByTestId("evo-confirm-modal")).toBeInTheDocument();
  });

  it("requires the boundary acknowledgement and sends extra_confirm=true", async () => {
    const { calls } = installFetch({ requiresHuman: true });
    render(<EvolutionPanel />);

    await screen.findByText(baseItem.id);
    fireEvent.click(screen.getByText(baseItem.id));
    fireEvent.click(await screen.findByTestId("evo-approve"));

    const okButton = screen.getByTestId("evo-confirm-ok");
    expect(okButton).toBeDisabled();
    expect(screen.getByText("请先勾选 Provider Prompt 影响核对，再执行批准。")).toBeInTheDocument();

    fireEvent.click(screen.getByTestId("evo-prompt-surface-check"));
    expect(screen.getByText("请先勾选安全边界确认或显式授权执行，再执行批准。")).toBeInTheDocument();
    fireEvent.click(screen.getByTestId("evo-extra-confirm"));
    expect(okButton).not.toBeDisabled();
    fireEvent.click(okButton);

    await waitFor(() => expect(screen.queryByTestId("evo-confirm-modal")).not.toBeInTheDocument());
    const post = calls.find((call) => call.url === "/api/v1/evolution/review");
    expect(post).toBeDefined();
    const body = JSON.parse(String(post?.init?.body ?? "{}"));
    expect(body.extra_confirm).toBe(true);
    expect(body.expected_status).toBe("pending_review");
  });

  it("shows a copyable AI notification receipt after approval (EVO-20260918-d1182270)", async () => {
    installFetch({
      reviewBody: { ok: true, message: "✅ 已批准", id: baseItem.id, new_status: "accepted" },
    });
    render(<EvolutionPanel />);

    await screen.findByText(baseItem.id);
    fireEvent.click(screen.getByText(baseItem.id));
    fireEvent.click(await screen.findByTestId("evo-approve"));
    fireEvent.click(screen.getByTestId("evo-prompt-surface-check"));
    fireEvent.click(screen.getByTestId("evo-confirm-ok"));

    const receipt = await screen.findByTestId("evo-review-receipt");
    expect(receipt).toHaveTextContent("AI 会话不会自动收到");
    const receiptText = screen.getByTestId("evo-review-receipt-text");
    expect(receiptText).toHaveTextContent(`已批准 ${baseItem.id}`);
    expect(receiptText).toHaveTextContent("新状态 accepted");
    expect(receiptText).toHaveTextContent("【人工审批回执】");
    expect(screen.getByTestId("evo-review-receipt-copy")).toBeInTheDocument();

    // 关闭回执：用户明确放弃后才隐藏
    fireEvent.click(screen.getByTitle("关闭回执"));
    expect(screen.queryByTestId("evo-review-receipt")).toBeNull();
  });

  it("keeps long post-approval feedback and its copy button inside the same scrollport as the list", async () => {
    installFetch({
      reviewBody: {
        ok: true,
        message: "审批完成，但执行仍需继续核验和回执。".repeat(40),
        new_status: "executing",
      },
    });
    render(<EvolutionPanel />);
    await screen.findByText(baseItem.id);
    const scrollport = screen.getByTestId("evo-scroll-region");
    scrollport.scrollTop = 100;
    fireEvent.click(screen.getByText(baseItem.id));
    fireEvent.click(await screen.findByTestId("evo-approve"));
    fireEvent.click(screen.getByTestId("evo-prompt-surface-check"));
    fireEvent.click(screen.getByTestId("evo-confirm-ok"));

    const receipt = await screen.findByTestId("evo-review-receipt");
    expect(scrollport.scrollTop).toBe(0);
    expect(scrollport).toContainElement(screen.getByTestId("evo-action-msg"));
    expect(scrollport).toContainElement(receipt);
    expect(scrollport).toContainElement(screen.getByTestId("evo-review-receipt-copy"));
    expect(scrollport).toHaveAttribute("tabIndex", "0");
    expect(receipt).toHaveTextContent("新状态 executing");
  });

  it("keeps batch approval controls next to the tabs instead of burying them within the list", async () => {
    installFetch();
    render(<EvolutionPanel />);
    await screen.findByText(baseItem.id);
    fireEvent.click(screen.getByTitle("勾选批量"));
    const bar = screen.getByTestId("evo-batchbar");
    expect(bar).toBeInTheDocument();
    expect(screen.getByTestId("evo-scroll-region")).not.toContainElement(bar);
  });

  it("offers explicit exec authorization for non-boundary items (EVO-20261018-f5f7580a)", async () => {
    // 修复前授权勾选框只在 requires_human 时渲染，非边界条目在档位 0 下无入口可授权。
    const { calls } = installFetch({ requiresHuman: false });
    render(<EvolutionPanel />);

    await screen.findByText(baseItem.id);
    fireEvent.click(screen.getByText(baseItem.id));
    fireEvent.click(await screen.findByTestId("evo-approve"));

    const authorize = screen.getByTestId("evo-authorize-exec");
    expect(authorize).toBeInTheDocument();
    fireEvent.click(screen.getByTestId("evo-prompt-surface-check"));
    fireEvent.click(authorize);
    fireEvent.click(screen.getByTestId("evo-confirm-ok"));

    await waitFor(() => expect(screen.queryByTestId("evo-confirm-modal")).not.toBeInTheDocument());
    const post = calls.find((call) => call.url === "/api/v1/evolution/review");
    expect(post).toBeDefined();
    const body = JSON.parse(String(post?.init?.body ?? "{}"));
    expect(body.exec_override).toBe(true);
    expect(body.extra_confirm).toBe(false);
  });

  it("labels boundary authorization truthfully and sends exec_override (RULE-AI-28 P1-1)", async () => {
    // 文案必须与实现一致：override 越过边界与档位，不能再写"仍过权限级别门禁"。
    const { calls } = installFetch({ requiresHuman: true });
    render(<EvolutionPanel />);

    await screen.findByText(baseItem.id);
    fireEvent.click(screen.getByText(baseItem.id));
    fireEvent.click(await screen.findByTestId("evo-approve"));

    const authorize = screen.getByTestId("evo-authorize-exec");
    expect(authorize.parentElement?.textContent).toContain("越过边界拦截与执行档位");
    expect(authorize.parentElement?.textContent).not.toContain("仍过权限级别门禁");

    fireEvent.click(screen.getByTestId("evo-prompt-surface-check"));
    fireEvent.click(authorize);
    fireEvent.click(screen.getByTestId("evo-confirm-ok"));

    await waitFor(() => expect(screen.queryByTestId("evo-confirm-modal")).not.toBeInTheDocument());
    const post = calls.find((call) => call.url === "/api/v1/evolution/review");
    const body = JSON.parse(String(post?.init?.body ?? "{}"));
    expect(body.exec_override).toBe(true);
    expect(body.extra_confirm).toBe(false);
  });
});

describe("EvolutionPanel origin session link", () => {
  const SID = "11111111-2222-3333-4444-555555555555";

  async function approveOnce() {
    await screen.findByText(baseItem.id);
    fireEvent.click(screen.getByText(baseItem.id));
    fireEvent.click(await screen.findByTestId("evo-approve"));
    fireEvent.click(screen.getByTestId("evo-prompt-surface-check"));
    fireEvent.click(screen.getByTestId("evo-confirm-ok"));
    return screen.findByTestId("evo-review-receipt");
  }

  it("renders the source session line and the open button below copy", async () => {
    installFetch({ sessionId: SID });
    render(<EvolutionPanel />);
    await approveOnce();

    const copy = screen.getByTestId("evo-review-receipt-copy");
    const btn = await screen.findByTestId("evo-open-origin-session");

    expect(screen.getByTestId("evo-origin-sid")).toHaveTextContent(SID);
    expect(btn).toHaveTextContent("打开来源会话并粘贴");
    expect(copy.compareDocumentPosition(btn) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("shows the legacy hint and no button when the suggestion has no session id", async () => {
    installFetch();
    render(<EvolutionPanel />);
    await approveOnce();

    expect(screen.getByTestId("evo-origin-none")).toHaveTextContent("来源会话未记录");
    expect(screen.queryByTestId("evo-open-origin-session")).toBeNull();
  });

  it("opens the current-workspace session and prefills the receipt without sending", async () => {
    const { calls } = installFetch({ sessionId: SID });
    render(<EvolutionPanel />);
    await approveOnce();

    fireEvent.click(await screen.findByTestId("evo-open-origin-session"));

    await waitFor(() => expect(sessionStore.getState().currentSessionId).toBe(SID));
    expect(conversationStore.getState().composerPrefill?.text).toContain("【人工审批回执】");
    expect(calls.some((call) => call.url.startsWith("/api/v1/chat"))).toBe(false);
    expect(await screen.findByTestId("evo-origin-note")).toHaveTextContent("回执已填入输入框");
  });

  it("disables the button with a truthful reason for identity sessions", async () => {
    installFetch({ sessionId: SID, locatorBody: { ok: true, available: false, reason: "identity_only" } });
    render(<EvolutionPanel />);
    await approveOnce();

    const button = await screen.findByTestId("evo-open-origin-session");
    await waitFor(() => expect(button).toBeDisabled());
    expect(screen.getByTestId("evo-origin-reason")).toHaveTextContent("属于身份会话");
    fireEvent.click(button);
    expect(sessionStore.getState().currentSessionId || null).toBeNull();
  });

  it("switches workspace before selecting the session and prefilling", async () => {
    const { calls } = installFetch({
      sessionId: SID,
      locatorBody: {
        ok: true,
        available: true,
        current: false,
        workspace_id: "ws-lfl",
        workspace_path: "/srv/lfl-workspace",
      },
    });
    render(<EvolutionPanel />);
    await approveOnce();

    const button = await screen.findByTestId("evo-open-origin-session");
    await waitFor(() => expect(button).toHaveTextContent("将切换到 /srv/lfl-workspace"));
    fireEvent.click(button);

    await waitFor(() => expect(sessionStore.getState().currentSessionId).toBe(SID));
    const switchCall = calls.find((call) => call.url === "/api/v1/workspaces/switch");
    expect(switchCall).toBeDefined();
    expect(JSON.parse(String(switchCall?.init?.body ?? "{}"))).toEqual({ id: "ws-lfl" });
    expect(conversationStore.getState().composerPrefill?.text).toContain("【人工审批回执】");
  });

  it("reports workspace_busy on 409 and does not navigate", async () => {
    installFetch({
      sessionId: SID,
      switchStatus: 409,
      locatorBody: { ok: true, available: true, current: false, workspace_id: "ws-lfl", workspace_path: "/tmp/lfl" },
    });
    render(<EvolutionPanel />);
    await approveOnce();

    fireEvent.click(await screen.findByTestId("evo-open-origin-session"));

    await waitFor(() =>
      expect(screen.getByTestId("evo-origin-note")).toHaveTextContent("当前会话运行中，暂不能切换工作区")
    );
    expect(sessionStore.getState().currentSessionId || null).toBeNull();
  });

  it("tells the user when the receipt is appended to an existing draft", async () => {
    localStorage.setItem(`lfl-draft-${SID}`, "已有草稿");
    installFetch({ sessionId: SID });
    render(<EvolutionPanel />);
    await approveOnce();

    fireEvent.click(await screen.findByTestId("evo-open-origin-session"));

    await waitFor(() =>
      expect(screen.getByTestId("evo-origin-note")).toHaveTextContent("该会话已有草稿，回执已追加在末尾")
    );
  });

  it("dedupes batch origins, caps buttons at 3 and reports the remainder", async () => {
    const items = Array.from({ length: 5 }, (_, i) => ({ ...baseItem, id: `EVO-batch-${i}` }));
    installFetch({
      items,
      batchBody: {
        ok_count: 5,
        fail_count: 0,
        results: [
          { id: "EVO-batch-0", ok: true, session_id: "sid-a" },
          { id: "EVO-batch-1", ok: true, session_id: "sid-a" },
          { id: "EVO-batch-2", ok: true, session_id: "sid-b" },
          { id: "EVO-batch-3", ok: true, session_id: "sid-c" },
          { id: "EVO-batch-4", ok: true, session_id: "sid-d" },
        ],
      },
    });
    render(<EvolutionPanel />);
    await screen.findByText("EVO-batch-0");

    screen.getAllByTitle("勾选批量").forEach((el) => fireEvent.click(el));
    fireEvent.click(screen.getByRole("button", { name: "批量批准" }));

    await screen.findByTestId("evo-review-receipt");
    expect(screen.getAllByTestId("evo-open-origin-session")).toHaveLength(3);
    expect(screen.getByTestId("evo-origin-block")).toHaveTextContent("等 1 个");
    expect(screen.getByTestId("evo-origin-block")).toHaveTextContent("（2 条建议）");
  });
});

describe("EvolutionPanel bounded approval feedback (EVO-20261125)", () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  // 打开单条批准确认弹窗并点击确定（勾选 prompt surface 确认）；id 可指定（"结果不明"锁为模块级、
  // 跨用例保留，需要锁残留的用例必须用独立 id 隔离）
  async function openConfirmAndApprove(id: string = baseItem.id) {
    await screen.findByText(id);
    fireEvent.click(screen.getByText(id));
    await screen.findByTestId("evo-approve");
    fireEvent.click(screen.getByTestId("evo-approve"));
    fireEvent.click(screen.getByTestId("evo-prompt-surface-check"));
    fireEvent.click(screen.getByTestId("evo-confirm-ok"));
  }

  it("shows busy feedback immediately and recovers as approved via read-only query when POST times out after backend accepted", async () => {
    // 仅 mock 定时器，避免 fake timers 干扰 React 渲染调度（MessageChannel/scheduler）
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout", "setInterval", "clearInterval"], shouldAdvanceTime: true });
    // 第 1 项 detail 供详情 viewer 加载；第 2 项供超时后的 queryStatus（复现 EVO-20261125-bb60b1d4：后端已 accepted）
    const { calls } = installFetch({
      reviewSequence: ["hang"],
      detailSequence: [
        { body: { ...baseItem } },
        { body: { ...baseItem, status: "accepted", session_id: "sid-timeout-ok" } },
      ],
    });
    render(<EvolutionPanel />);
    await openConfirmAndApprove();

    // 点击后立即有明确"处理中"反馈且按钮禁用；busy 期间重复点击不发出第二个 POST
    const okButton = screen.getByTestId("evo-confirm-ok");
    expect(okButton).toHaveTextContent("处理中…");
    expect(okButton).toBeDisabled();
    fireEvent.click(okButton);

    // 推进到 15s 有界超时：POST 中止 → 只读查询 detail 确认真实状态（复现 EVO-20261125-bb60b1d4：后端已 accepted）
    await act(async () => {
      await vi.advanceTimersByTimeAsync(15000);
    });
    await waitFor(() => expect(screen.queryByTestId("evo-confirm-modal")).not.toBeInTheDocument());

    const receiptText = screen.getByTestId("evo-review-receipt-text");
    expect(receiptText).toHaveTextContent(`已批准 ${baseItem.id}`);
    expect(receiptText).toHaveTextContent("新状态 accepted");
    expect(screen.getByTestId("evo-review-receipt")).toHaveTextContent("查询核实");

    const posts = calls.filter((call) => call.url === "/api/v1/evolution/review" && call.init?.method === "POST");
    expect(posts).toHaveLength(1); // 超时后绝不自动重复 POST
    expect(calls.some((call) => call.url.startsWith("/api/v1/evolution/detail"))).toBe(true);
    expect(JSON.parse(String(posts[0]?.init?.body ?? "{}")).expected_status).toBe("pending_review"); // CAS 契约保留
  });

  it("locks resubmission and offers a query entry when neither POST nor status query succeeds", async () => {
    // 仅 mock 定时器，避免 fake timers 干扰 React 渲染调度（MessageChannel/scheduler）
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout", "setInterval", "clearInterval"], shouldAdvanceTime: true });
    // "结果不明"锁为模块级、跨用例保留：本用例结束时会留下锁，必须用独立 id 隔离
    const lockId = "EVO-lock-unknown";
    const { calls } = installFetch({
      items: [{ ...baseItem, id: lockId }],
      reviewSequence: ["hang"],
      // 第 1 项供详情 viewer；第 2 次查询（review 超时后）失败 → 未知锁定；第 3 次查询（手动）仍失败 → 保持锁定
      detailSequence: [{ body: { ...baseItem, id: lockId } }, "fail", "fail"],
    });
    render(<EvolutionPanel />);
    await openConfirmAndApprove(lockId);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(15000);
    });
    const okButton = await screen.findByTestId("evo-confirm-ok");
    await waitFor(() => expect(okButton).toHaveTextContent("禁止重复提交"));
    expect(okButton).toBeDisabled();
    expect(screen.getByTestId("evo-confirm-modal")).toBeInTheDocument();
    expect(screen.getByTestId("evo-query-status")).toBeInTheDocument();

    // 用户点「查询状态」（仍失败）→ 保持锁定；全程无第二次 POST
    fireEvent.click(screen.getByTestId("evo-query-status"));
    await waitFor(() =>
      expect(screen.getByTestId("evo-confirm-message")).toHaveTextContent("查询仍失败或状态不明")
    );
    const posts = calls.filter((call) => call.url === "/api/v1/evolution/review" && call.init?.method === "POST");
    expect(posts).toHaveLength(1);
  });

  it("keeps resubmission locked when the query still shows pending_review (original POST may still be processing)", async () => {
    // 仅 mock 定时器，避免 fake timers 干扰 React 渲染调度（MessageChannel/scheduler）
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout", "setInterval", "clearInterval"], shouldAdvanceTime: true });
    // 仍待审批不能证明此前请求已终止（可能仍在服务端处理）→ 禁止重发，仅可继续只读核实（修复③）
    const lockId = "EVO-lock-pending";
    const { calls } = installFetch({
      items: [{ ...baseItem, id: lockId }],
      reviewSequence: ["hang"],
      detailSequence: [
        { body: { ...baseItem, id: lockId } },
        { body: { ...baseItem, id: lockId, status: "pending_review" } },
      ],
    });
    render(<EvolutionPanel />);
    await openConfirmAndApprove(lockId);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(15000);
    });
    const okButton = await screen.findByTestId("evo-confirm-ok");
    await waitFor(() => expect(okButton).toHaveTextContent("禁止重复提交"));
    expect(okButton).toBeDisabled();
    await waitFor(() =>
      expect(screen.getByTestId("evo-confirm-message")).toHaveTextContent("可能仍在服务端处理")
    );

    // 关闭后重新打开确认弹窗：锁定保留，不静默解锁（修复③）
    fireEvent.click(screen.getByText("取消"));
    await waitFor(() => expect(screen.queryByTestId("evo-confirm-modal")).not.toBeInTheDocument());
    fireEvent.click(await screen.findByTestId("evo-approve"));
    const okAgain = await screen.findByTestId("evo-confirm-ok");
    expect(okAgain).toBeDisabled();
    expect(screen.getByTestId("evo-query-status")).toBeInTheDocument();

    const posts = calls.filter((call) => call.url === "/api/v1/evolution/review" && call.init?.method === "POST");
    expect(posts).toHaveLength(1);
  });

  it("treats an explicit 409 gate rejection as provable non-application: user may re-initiate once", async () => {
    const { calls } = installFetch({
      reviewSequence: [
        { status: 409, body: { error: "status_conflict", detail: "状态冲突：并发变更，可重试" } },
        { status: 200, body: { ok: true, message: "已批准", new_status: "accepted", session_id: "sid-retry" } },
      ],
      detailSequence: [{ body: { ...baseItem } }],
    });
    render(<EvolutionPanel />);
    await openConfirmAndApprove();

    await waitFor(() => expect(screen.getByTestId("evo-confirm-message")).toHaveTextContent("状态冲突"));
    // 服务端门禁已明确拒绝第一次提交（可证明未生效）→ 允许用户显式重发；仍然一次点击一次请求
    fireEvent.click(screen.getByTestId("evo-confirm-ok"));
    await waitFor(() => expect(screen.queryByTestId("evo-confirm-modal")).not.toBeInTheDocument());
    const posts = calls.filter((call) => call.url === "/api/v1/evolution/review" && call.init?.method === "POST");
    expect(posts).toHaveLength(2);
  });

  it("times out even when only the response body hangs (deadline covers headers + body parsing)", async () => {
    // 仅 mock 定时器，避免 fake timers 干扰 React 渲染调度（MessageChannel/scheduler）
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout", "setInterval", "clearInterval"], shouldAdvanceTime: true });
    const hangId = "EVO-bodyhang-1";
    const { calls } = installFetch({
      items: [{ ...baseItem, id: hangId }],
      // 响应头 200 立即返回，响应体永不结束：有界 helper 必须在 deadline 内按结果不明处理（修复①）
      reviewSequence: [{ status: 200, bodyHang: true }],
      detailSequence: [
        { body: { ...baseItem, id: hangId } },
        { body: { ...baseItem, id: hangId, status: "pending_review" } },
      ],
    });
    render(<EvolutionPanel />);
    await openConfirmAndApprove(hangId);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(15000);
    });
    const okButton = await screen.findByTestId("evo-confirm-ok");
    await waitFor(() => expect(okButton).toHaveTextContent("禁止重复提交"));
    expect(okButton).toBeDisabled();
    const posts = calls.filter((call) => call.url === "/api/v1/evolution/review" && call.init?.method === "POST");
    expect(posts).toHaveLength(1);
  });

  it("does not fake a 0/0 batch completion when only the batch response body hangs", async () => {
    // 仅 mock 定时器，避免 fake timers 干扰 React 渲染调度（MessageChannel/scheduler）
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout", "setInterval", "clearInterval"], shouldAdvanceTime: true });
    const items = Array.from({ length: 2 }, (_, i) => ({ ...baseItem, id: `EVO-bh-${i}` }));
    const { calls } = installFetch({ items, batchSequence: [{ bodyHang: true }] });
    render(<EvolutionPanel />);
    await screen.findByText("EVO-bh-0");
    screen.getAllByTitle("勾选批量").forEach((el) => fireEvent.click(el));
    fireEvent.click(screen.getByRole("button", { name: "批量批准" }));

    await act(async () => {
      await vi.advanceTimersByTimeAsync(15000);
    });
    const msg = await screen.findByTestId("evo-action-msg");
    expect(msg).toHaveTextContent("提交结果不明");
    expect(msg).not.toHaveTextContent("批量完成");
    expect(msg).not.toHaveTextContent("成功 0 / 失败 0");
    const batchPosts = calls.filter((call) => call.url === "/api/v1/evolution/review-batch");
    expect(batchPosts).toHaveLength(1); // 结果不明绝不自动重发
  });

  it("treats a 5xx as indeterminate and recovers via read-only query (cannot trust the status line)", async () => {
    // 仅 mock 定时器，避免 fake timers 干扰 React 渲染调度（MessageChannel/scheduler）
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout", "setInterval", "clearInterval"], shouldAdvanceTime: true });
    const errId = "EVO-5xx-1";
    const { calls } = installFetch({
      items: [{ ...baseItem, id: errId }],
      reviewSequence: [{ status: 500, body: { error: "review_failed", detail: "boom" } }],
      detailSequence: [
        { body: { ...baseItem, id: errId } },
        { body: { ...baseItem, id: errId, status: "accepted", session_id: "sid-5xx" } },
      ],
    });
    render(<EvolutionPanel />);
    await openConfirmAndApprove(errId);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(15000);
    });
    // 5xx 走结果不明恢复路径（后端 read-then-approve 非原子，不能轻信状态行）：查询确认已接受 → 如实恢复
    await waitFor(() => expect(screen.queryByTestId("evo-confirm-modal")).not.toBeInTheDocument());
    expect(screen.getByTestId("evo-review-receipt-text")).toHaveTextContent(`已批准 ${errId}`);
    const posts = calls.filter((call) => call.url === "/api/v1/evolution/review" && call.init?.method === "POST");
    expect(posts).toHaveLength(1);
  });

  it("narrates the executing state truthfully (approval stage vs execution stage)", async () => {
    // 仅 mock 定时器，避免 fake timers 干扰 React 渲染调度（MessageChannel/scheduler）
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout", "setInterval", "clearInterval"], shouldAdvanceTime: true });
    const execId = "EVO-exec-1";
    installFetch({
      items: [{ ...baseItem, id: execId }],
      reviewSequence: ["hang"],
      // 复现 EVO-20261125-bb60b1d4 真实状态链：已接受且进入执行中（修复②）
      detailSequence: [
        { body: { ...baseItem, id: execId } },
        { body: { ...baseItem, id: execId, status: "executing", session_id: "sid-exec" } },
      ],
    });
    render(<EvolutionPanel />);
    await openConfirmAndApprove(execId);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(15000);
    });
    await waitFor(() => expect(screen.queryByTestId("evo-confirm-modal")).not.toBeInTheDocument());
    expect(screen.getByTestId("evo-review-receipt-text")).toHaveTextContent("新状态 executing");
    expect(screen.getByTestId("evo-review-receipt")).toHaveTextContent("正在执行");
  });

  it("rejects a detail receipt whose id does not match and keeps resubmission locked", async () => {
    // 仅 mock 定时器，避免 fake timers 干扰 React 渲染调度（MessageChannel/scheduler）
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout", "setInterval", "clearInterval"], shouldAdvanceTime: true });
    const mineId = "EVO-idmismatch-1";
    installFetch({
      items: [{ ...baseItem, id: mineId }],
      reviewSequence: ["hang"],
      detailSequence: [
        { body: { ...baseItem, id: mineId } },
        // 回执 id 不一致：不得把别的条目状态冒充本条核实结果（修复②）
        { body: { ...baseItem, id: "EVO-someone-else", status: "accepted" } },
        "fail",
      ],
    });
    render(<EvolutionPanel />);
    await openConfirmAndApprove(mineId);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(15000);
    });
    const okButton = await screen.findByTestId("evo-confirm-ok");
    await waitFor(() => expect(okButton).toHaveTextContent("禁止重复提交"));
    expect(okButton).toBeDisabled();
    // 再次手动查询（失败）仍锁定
    fireEvent.click(screen.getByTestId("evo-query-status"));
    await waitFor(() =>
      expect(screen.getByTestId("evo-confirm-message")).toHaveTextContent("查询仍失败或状态不明")
    );
  });

  it("labels every authoritative status including executing and execution terminal states", async () => {
    installFetch({
      items: [
        { ...baseItem, id: "EVO-st-executing", status: "executing" },
        { ...baseItem, id: "EVO-st-rolled", status: "rolled_back" },
        { ...baseItem, id: "EVO-st-failed", status: "failed" },
      ],
    });
    render(<EvolutionPanel />);
    fireEvent.click(screen.getByRole("button", { name: "全部" }));
    expect(await screen.findByText("执行中")).toBeInTheDocument();
    expect(screen.getByText("已回滚")).toBeInTheDocument();
    expect(screen.getByText("执行失败")).toBeInTheDocument();
  });

  it("does not send a second POST on rapid double submit (synchronous in-flight guard)", async () => {
    const dblId = "EVO-dblclick-1";
    const { calls } = installFetch({
      items: [{ ...baseItem, id: dblId }],
      reviewSequence: [{ status: 200, body: { ok: true, message: "已批准", new_status: "accepted" } }],
      detailSequence: [{ body: { ...baseItem, id: dblId } }],
    });
    render(<EvolutionPanel />);
    await screen.findByText(dblId);
    fireEvent.click(screen.getByText(dblId));
    fireEvent.click(await screen.findByTestId("evo-approve"));
    fireEvent.click(screen.getByTestId("evo-prompt-surface-check"));
    const okButton = screen.getByTestId("evo-confirm-ok");
    fireEvent.click(okButton);
    fireEvent.click(okButton); // 同一 tick 连点：busyRef 同步闸保证只有一个 POST（修复③）
    fireEvent.click(okButton);
    await waitFor(() => expect(screen.queryByTestId("evo-confirm-modal")).not.toBeInTheDocument());
    const posts = calls.filter((call) => call.url === "/api/v1/evolution/review" && call.init?.method === "POST");
    expect(posts).toHaveLength(1);
  });

  it("keeps the 409 conflict dialog open with the backend detail and restores the button", async () => {
    installFetch({
      reviewStatus: 409,
      reviewBody: { error: "status_conflict", detail: "状态冲突：当前状态 executing（期望 pending_review）" },
    });
    render(<EvolutionPanel />);
    await openConfirmAndApprove();

    await waitFor(() =>
      expect(screen.getByTestId("evo-confirm-message")).toHaveTextContent("状态冲突")
    );
    expect(screen.getByTestId("evo-confirm-modal")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByTestId("evo-confirm-ok")).not.toBeDisabled());
  });

  it("batch button shows busy text and refreshes the list without reposting on timeout", async () => {
    // 仅 mock 定时器，避免 fake timers 干扰 React 渲染调度（MessageChannel/scheduler）
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout", "setInterval", "clearInterval"], shouldAdvanceTime: true });
    const items = Array.from({ length: 2 }, (_, i) => ({ ...baseItem, id: `EVO-bt-${i}` }));
    const { calls } = installFetch({ items, batchSequence: ["hang"] });
    render(<EvolutionPanel />);
    await screen.findByText("EVO-bt-0");

    screen.getAllByTitle("勾选批量").forEach((el) => fireEvent.click(el));
    fireEvent.click(screen.getByRole("button", { name: "批量批准" }));

    // 点击后立即有明确"处理中"反馈
    expect(screen.getByRole("button", { name: "处理中…" })).toBeDisabled();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(15000);
    });
    await waitFor(() =>
      expect(screen.getByTestId("evo-action-msg")).toHaveTextContent("提交结果不明")
    );
    // 清空勾选（防盲目重试）→ 批量 bar 隐藏；"处理中…"消失 = busy 解除
    expect(screen.queryByRole("button", { name: "处理中…" })).not.toBeInTheDocument();

    const batchPosts = calls.filter((call) => call.url === "/api/v1/evolution/review-batch");
    expect(batchPosts).toHaveLength(1); // 超时后绝不自动重发
    const listCalls = calls.filter((call) => call.url.startsWith("/api/v1/evolution/list"));
    expect(listCalls.length).toBeGreaterThanOrEqual(2); // 超时后只读刷新列表呈现真实状态
  });
});
