import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
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
}) {
  const item = { ...baseItem, requires_human: Boolean(options?.requiresHuman) };
  const listed = options?.items ?? [{ ...item }];
  const calls: Array<{ url: string; init?: RequestInit }> = [];
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    calls.push({ url, init });
    if (url.startsWith("/api/v1/evolution/list")) {
      return new Response(JSON.stringify({ suggestions: listed, count: listed.length }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    }
    if (url.startsWith("/api/v1/evolution/detail")) {
      return new Response(JSON.stringify({
        ...item,
        scope: "runtime",
        content: "完整建议正文第一段\n完整建议正文第二段",
        evidence: "完整证据：来自当前运行事实",
        impact_scope: "Web 演进审批可读性",
        impact_files: ["src/example.py"],
        reason_history: [{ reason: "补充当前证据", at: "2026-09-09T00:05:00Z" }],
      }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    }
    if (url.startsWith("/api/v1/evolution/diff")) {
      return new Response(JSON.stringify(options?.diffBody ?? {
        id: item.id,
        impact_files: ["src/example.py"],
        actions: [{ type: "modify", path: "src/example.py", summary: "调整审批详情展示" }],
        note: "只读摘要（不含 prompt/密钥）",
      }), {
        status: options?.diffStatus ?? 200,
        headers: { "Content-Type": "application/json" },
      });
    }
    if (url.startsWith("/api/v1/evolution/session-locator")) {
      return new Response(
        JSON.stringify(
          options?.locatorBody ?? {
            ok: true,
            available: true,
            current: true,
            workspace_id: "ws-1",
            workspace_path: "/tmp/ws-1",
          }
        ),
        { status: options?.locatorStatus ?? 200, headers: { "Content-Type": "application/json" } }
      );
    }
    if (url === "/api/v1/workspaces/switch") {
      return new Response(JSON.stringify({ ok: true }), {
        status: options?.switchStatus ?? 200,
        headers: { "Content-Type": "application/json" },
      });
    }
    if (url === "/api/v1/evolution/review-batch") {
      return new Response(
        JSON.stringify(options?.batchBody ?? { ok_count: 0, fail_count: 0, results: [] }),
        { status: 200, headers: { "Content-Type": "application/json" } }
      );
    }
    if (url === "/api/v1/evolution/review") {
      return new Response(
        JSON.stringify(
          options?.reviewBody ?? {
            ok: true,
            message: "已批准",
            ...(options?.sessionId ? { session_id: options.sessionId } : {}),
          }
        ),
        {
          status: options?.reviewStatus ?? 200,
          headers: { "Content-Type": "application/json" },
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
