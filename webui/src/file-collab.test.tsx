import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { FileTree } from "./components/sidebar/FileTree";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("Human-AI file collaboration", () => {
  it("version conflict keeps the human draft and never retries automatically", async () => {
    let editCalls = 0;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url.includes("/api/v1/fs/tree")) {
          return new Response(
            JSON.stringify({ path: "/ws", parent: null, dirs: [], files: [{ name: "a.txt", size: 5 }] }),
            { status: 200 }
          );
        }
        if (url.includes("/files/observe")) {
          return new Response(
            JSON.stringify({
              path: "a.txt",
              snapshot_ref: `artifact://v1/${"a".repeat(32)}`,
              sha256: "b".repeat(64),
              size_bytes: 5,
              observed_at: 1,
              content_range: { start: 0, end_exclusive: 1 },
              content: "base\n",
              total_lines: 1,
              workspace_path_state: "current_match",
              file_contract_version: 1,
            }),
            { status: 200 }
          );
        }
        if (url.includes("/files/edit")) {
          editCalls += 1;
          return new Response(JSON.stringify({ error: "version_conflict" }), { status: 409 });
        }
        return new Response("{}", { status: 404 });
      })
    );

    render(<FileTree sessionId="s1" />);
    await waitFor(() => expect(screen.getByText("a.txt")).toBeInTheDocument());
    fireEvent.click(screen.getByText("a.txt"));
    const editor = await screen.findByRole("textbox");
    expect(editor).toHaveValue("base\n");
    fireEvent.change(editor, { target: { value: "my draft\n" } });
    fireEvent.click(screen.getByText("保存当前版本"));
    await waitFor(() => expect(screen.getByText(/版本已变化/)).toBeInTheDocument());
    expect(editor).toHaveValue("my draft\n");
    expect(editCalls).toBe(1);
  });
});

describe("Human-AI file collaboration request identity", () => {
  it("unknown network outcome reuses the same request_id on explicit retry", async () => {
    const ids: string[] = [];
    let editAttempt = 0;
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        if (url.includes("/api/v1/fs/tree")) {
          return new Response(JSON.stringify({ path: "/ws", parent: null, dirs: [], files: [{ name: "a.txt", size: 5 }] }), { status: 200 });
        }
        if (url.includes("/files/observe")) {
          return new Response(JSON.stringify({
            path: "a.txt", snapshot_ref: `artifact://v1/${"a".repeat(32)}`, sha256: "b".repeat(64),
            size_bytes: 5, observed_at: 1, content_range: { start: 0, end_exclusive: 1 }, content: "base\n",
            total_lines: 1, workspace_path_state: "current_match", file_contract_version: 1,
          }), { status: 200 });
        }
        if (url.includes("/files/edit")) {
          editAttempt += 1;
          const body = JSON.parse(String(init?.body ?? "{}")) as { request_id?: string };
          ids.push(body.request_id ?? "");
          if (editAttempt === 1) throw new TypeError("network lost after send");
          return new Response(JSON.stringify({ operation_id: "op", origin: "authenticated_user" }), { status: 200 });
        }
        return new Response("{}", { status: 404 });
      })
    );

    render(<FileTree sessionId="s1" />);
    await waitFor(() => expect(screen.getByText("a.txt")).toBeInTheDocument());
    fireEvent.click(screen.getByText("a.txt"));
    await screen.findByRole("textbox");
    fireEvent.click(screen.getByText("保存当前版本"));
    await waitFor(() => expect(screen.getByText(/保存结果暂时未知/)).toBeInTheDocument());
    fireEvent.click(screen.getByText("保存当前版本"));
    await waitFor(() => expect(ids).toHaveLength(2));
    expect(ids[0]).toBe(ids[1]);
  });
});
