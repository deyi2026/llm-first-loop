import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { FileTree } from "./components/sidebar/FileTree";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

function treeResponse() {
  return new Response(JSON.stringify({
    path: "/ws",
    parent: null,
    dirs: [{ name: "ignored" }].slice(0, 0),
    files: [{ name: "a.txt", size: 5 }],
  }), { status: 200 });
}

describe("file tree mutation controls", () => {
  it("rename failure remains visible and leaves the form/data unchanged", async () => {
    let renameCalls = 0;
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.includes("/api/v1/fs/tree")) return treeResponse();
      if (url.includes("/api/v1/fs/rename") && init?.method === "PUT") {
        renameCalls += 1;
        return new Response(JSON.stringify({ error: "busy" }), { status: 409 });
      }
      return new Response("{}", { status: 404 });
    }));

    render(<FileTree sessionId="s1" />);
    await waitFor(() => expect(screen.getByText("a.txt")).toBeInTheDocument());
    fireEvent.click(screen.getByTitle("重命名"));
    const input = screen.getByPlaceholderText("重命名");
    fireEvent.change(input, { target: { value: "b.txt" } });
    fireEvent.click(screen.getByRole("button", { name: "确定" }));
    await waitFor(() => expect(screen.getByText(/重命名失败/)).toBeInTheDocument());
    expect(renameCalls).toBe(1);
    expect(screen.getByPlaceholderText("重命名")).toHaveValue("b.txt");
    expect(screen.getByText("a.txt")).toBeInTheDocument();
  });

  it("delete failure is reported and does not remove the visible file", async () => {
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.includes("/api/v1/fs/tree")) return treeResponse();
      if (url.includes("/api/v1/fs/delete") && init?.method === "DELETE") {
        return new Response(JSON.stringify({ error: "busy" }), { status: 409 });
      }
      return new Response("{}", { status: 404 });
    }));

    render(<FileTree sessionId="s1" />);
    await waitFor(() => expect(screen.getByText("a.txt")).toBeInTheDocument());
    fireEvent.click(screen.getByTitle("删除"));
    fireEvent.click(screen.getByText("确认?"));
    await waitFor(() => expect(screen.getByText(/删除失败/)).toBeInTheDocument());
    expect(screen.getByText("a.txt")).toBeInTheDocument();
  });
});
