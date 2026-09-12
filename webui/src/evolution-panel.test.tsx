import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { EvolutionPanel } from "./components/sidebar/EvolutionPanel";

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
}) {
  const item = { ...baseItem, requires_human: Boolean(options?.requiresHuman) };
  const calls: Array<{ url: string; init?: RequestInit }> = [];
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    calls.push({ url, init });
    if (url.startsWith("/api/v1/evolution/list")) {
      return new Response(JSON.stringify({ suggestions: [item], count: 1 }), {
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
    if (url === "/api/v1/evolution/review") {
      return new Response(JSON.stringify(options?.reviewBody ?? { ok: true, message: "已批准" }), {
        status: options?.reviewStatus ?? 200,
        headers: { "Content-Type": "application/json" },
      });
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
    expect(screen.getByText("请先勾选安全边界确认，再执行批准。")).toBeInTheDocument();

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
});
