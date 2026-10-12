import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { TopBar } from "./components/layout/TopBar";
import { logoutBrowserSession } from "./core/api";

describe("browser auth controls", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn());
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it("shows logout only for an authenticated browser login session", async () => {
    vi.mocked(fetch).mockImplementation(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url === "/auth/status") {
        return new Response(
          JSON.stringify({ status: "ok", authenticated: true, browser_login: true }),
          { status: 200, headers: { "Content-Type": "application/json" } }
        );
      }
      if (url === "/health") {
        return new Response(JSON.stringify({ status: "ok", service: "lfl", version: "1" }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      }
      return new Response(JSON.stringify({}), { status: 200 });
    });

    render(<TopBar onToggleSidebar={() => undefined} />);
    await waitFor(() => expect(screen.getByRole("button", { name: "退出登录" })).toBeInTheDocument());
  });

  it("logout helper uses same-origin POST", async () => {
    vi.mocked(fetch).mockResolvedValue(
      new Response(JSON.stringify({ status: "ok" }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      })
    );

    await expect(logoutBrowserSession()).resolves.toBe(true);
    expect(fetch).toHaveBeenCalledWith("/auth/logout", { method: "POST" });
  });
});

describe("browser auth visibility", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn());
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it("does not show logout when browser login exists but this request is unauthenticated", async () => {
    vi.mocked(fetch).mockImplementation(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url === "/auth/status") {
        return new Response(
          JSON.stringify({ status: "ok", authenticated: false, browser_login: true }),
          { status: 200, headers: { "Content-Type": "application/json" } }
        );
      }
      if (url === "/health") {
        return new Response(JSON.stringify({ status: "ok", service: "lfl", version: "1" }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      }
      return new Response(JSON.stringify({}), { status: 200 });
    });

    render(<TopBar onToggleSidebar={() => undefined} />);
    await waitFor(() => expect(fetch).toHaveBeenCalledWith("/auth/status", undefined));
    expect(screen.queryByRole("button", { name: "退出登录" })).toBeNull();
  });
});
