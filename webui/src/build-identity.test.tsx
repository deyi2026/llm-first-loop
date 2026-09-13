import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { TopBar } from "./components/layout/TopBar";

describe("development build identity", () => {
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it("prefers exact build display over bare release version", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url === "/health") {
          return new Response(
            JSON.stringify({
              status: "ok",
              service: "llm-first-loop-web",
              version: "0.6.13",
              build: { display: "v0.6.13-120-g8513994b", release_exact: false },
            }),
            { status: 200, headers: { "Content-Type": "application/json" } }
          );
        }
        if (url === "/auth/status") {
          return new Response(
            JSON.stringify({ status: "ok", authenticated: false, browser_login: false }),
            { status: 200, headers: { "Content-Type": "application/json" } }
          );
        }
        return new Response(JSON.stringify({}), { status: 200 });
      })
    );

    render(<TopBar onToggleSidebar={() => undefined} />);

    await waitFor(() =>
      expect(screen.getByTestId("status-badge").textContent).toContain(
        "v0.6.13-120-g8513994b"
      )
    );
  });

  it("falls back to release version when old health payload has no build identity", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url === "/health") {
          return new Response(
            JSON.stringify({ status: "ok", service: "llm-first-loop-web", version: "0.6.13" }),
            { status: 200, headers: { "Content-Type": "application/json" } }
          );
        }
        return new Response(
          JSON.stringify({ status: "ok", authenticated: false, browser_login: false }),
          { status: 200, headers: { "Content-Type": "application/json" } }
        );
      })
    );

    render(<TopBar onToggleSidebar={() => undefined} />);

    await waitFor(() =>
      expect(screen.getByTestId("status-badge").textContent).toContain("v0.6.13")
    );
  });
});
