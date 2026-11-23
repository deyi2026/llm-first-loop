import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { clearAuthRequired, reportUnauthorized } from "./core/authSession";

vi.mock("./components/sidebar/Sidebar", () => ({ Sidebar: () => <div>侧栏</div> }));
vi.mock("./components/layout/TopBar", () => ({ TopBar: () => <div>顶栏</div> }));
vi.mock("./components/layout/RightPanel", () => ({ RightPanel: () => null }));
vi.mock("./components/conversation/Conversation", () => ({ Conversation: () => <div>会话</div> }));
vi.mock("./components/InteropNotice", () => ({ InteropNotice: () => null }));
vi.mock("./components/learning/LearningPanel", () => ({ LearningPanel: () => null }));
vi.mock("./components/learning/KnowledgePanel", () => ({ KnowledgePanel: () => null }));
vi.mock("./components/services/ServicesPanel", () => ({ ServicesPanel: () => null }));
vi.mock("./core/events", () => ({ initEventStream: vi.fn() }));
vi.mock("./core/capabilities", () => ({ probeSessionCapabilities: vi.fn() }));

import { App } from "./App";

afterEach(() => {
  cleanup();
  clearAuthRequired();
});

describe("login recovery banner", () => {
  it("offers a safe same-origin re-login link without resending a Run", () => {
    reportUnauthorized(401);
    render(<App />);
    const banner = screen.getByTestId("auth-recovery-banner");
    expect(banner).toHaveTextContent("后台任务不会因此停止");
    expect(banner).toHaveTextContent("重新登录");
    expect(screen.getByRole("link", { name: "重新登录" })).toHaveAttribute("href",
      "/login?next=%2F");
    expect(screen.getByRole("button", { name: "已登录，刷新" })).toBeInTheDocument();
  });
});
