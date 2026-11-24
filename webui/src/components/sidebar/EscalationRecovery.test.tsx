import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { EscalationPanel, EscalationWatcher, type EscalationRequest } from "./EscalationCenter";
import { sessionStore } from "../../core/stores";
import { conversationStore } from "../../core/conversation";

function makeReq(over: Partial<EscalationRequest> = {}): EscalationRequest {
  return {
    id: "ESC-20261124-00000001", tool_name: "execute_command",
    command: "historical-command-must-not-replay", justification: "test",
    session_id: "origin-a", origin_goal_id: "GOAL-a", origin_run_generation: "run-a",
    status: "pending", created_at: "2026-11-24T00:00:00Z", decided_at: "",
    decided_by: "", decision_note: "", ...over,
  };
}

function mockRequests(req: EscalationRequest, available = true) {
  const mock = vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    const pending = req.status === "pending" && !req._sig_unverified;
    const body = url.includes("session-locator")
      ? { available, current: true, session_id: req.session_id }
      : { requests: url.includes("status=pending") && !pending ? [] : [req], pending_count: pending ? 1 : 0 };
    return new Response(JSON.stringify(body), { status: 200 });
  });
  vi.stubGlobal("fetch", mock);
  return mock;
}

afterEach(() => {
  cleanup();
  sessionStore.setSessions([]);
  sessionStore.setCurrentSession("");
  conversationStore.setState({ composerPrefill: null });
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("提权来源与恢复", () => {
  it("弹窗准确显示来源并跳转，不发审批或消息", async () => {
    const req = makeReq();
    const fetchMock = mockRequests(req);
    sessionStore.setCurrentSession("other-session");
    const onNavigate = vi.fn();
    render(<EscalationWatcher onNavigate={onNavigate} />);
    await waitFor(() => expect(screen.getByTestId("esc-origin-" + req.id)).toHaveTextContent("GOAL-a"));
    expect(screen.getByTestId("esc-origin-" + req.id)).toHaveTextContent("run-a");
    fireEvent.click(screen.getByRole("button", { name: "打开来源会话" }));
    await waitFor(() => expect(sessionStore.getState().currentSessionId).toBe("origin-a"));
    expect(onNavigate).toHaveBeenCalledTimes(1);
    expect(screen.queryByTestId("esc-modal")).toBeNull();
    expect(conversationStore.getState().composerPrefill).toBeNull();
    expect(fetchMock.mock.calls.every(([url]) => !String(url).includes("/review"))).toBe(true);
  });

  it.each([{ status: "expired" }, { status: "pending", _sig_unverified: true }])(
    "失效历史可回原会话重新申请（%o），不重放历史命令",
    async (state) => {
      const req = makeReq({ ...state, session_id: "origin-b" });
      const fetchMock = mockRequests(req);
      sessionStore.setCurrentSession("other-session");
      render(<EscalationPanel />);
      await waitFor(() => expect(screen.getByRole("button", { name: "重新发起审批" })).toBeEnabled());
      fireEvent.click(screen.getByRole("button", { name: "重新发起审批" }));
      await waitFor(() => expect(conversationStore.getState().composerPrefill?.text).toContain(req.id));
      expect(sessionStore.getState().currentSessionId).toBe("origin-b");
      expect(conversationStore.getState().composerPrefill?.text).not.toContain(req.command);
      expect(screen.queryByRole("button", { name: "批准" })).toBeNull();
      expect(fetchMock.mock.calls.every(([url]) => !String(url).includes("/review"))).toBe(true);
    }
  );

  it.each(["denied", "consumed"])("终态 %s 不提供重发，找不到会话不猜测跳转", async (status) => {
    const req = makeReq({ session_id: "missing", status });
    mockRequests(req, false);
    sessionStore.setCurrentSession("other-session");
    render(<EscalationPanel />);
    await waitFor(() => expect(screen.getByRole("button", { name: "打开来源会话" })).toBeEnabled());
    expect(screen.queryByRole("button", { name: "重新发起审批" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "打开来源会话" }));
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("无法定位来源会话"));
    expect(sessionStore.getState().currentSessionId).toBe("other-session");
    expect(conversationStore.getState().composerPrefill).toBeNull();
  });
});
