// P0-2 + P2-4 删除/撤销（前端契约与交互）:
// - fsDelete 两步令牌：先 GET delete-token，再 DELETE confirm=true+token（hard=true 附 &hard=true）；
//   令牌类 409 有界重试一次；所有失败一律 {ok:false, error}（不抛异常），错误消息绝不外泄 token 原文。
// - P2-4 回收站：默认删除成功 → {ok:true, status:"trashed", undoToken, expiresIn}；hard=true → status:"deleted"。
// - fsRestore：POST /fs/restore?token=...；成功 ok:true；409/404 按错误码给出可区分的中文文案。
// - FileTree 交互：删除后出现撤销入口（含倒计时）；点击撤销调用 restore 并刷新父目录；
//   撤销失败显示错误、不刷新、不谎报成功；Esc 可关闭提示。
import { afterEach, describe, expect, it, vi } from "vitest";
import { createElement } from "react";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { fsDelete, fsRestore } from "./core/api";
import { FileTree } from "./components/sidebar/FileTree";

function json(body: unknown, status: number): Response {
  return new Response(JSON.stringify(body), { status });
}

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("fsDelete 两步删除令牌（P0-2）+ 回收站契约（P2-4）", () => {
  it("hard=true：先 GET delete-token，再 DELETE confirm=true+token&hard=true；返回 status=deleted", async () => {
    const calls: Array<{ method: string; url: string }> = [];
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const method = init?.method ?? "GET";
      calls.push({ method, url });
      if (url.includes("/api/v1/fs/delete-token")) {
        return json({ token: "tok-1", expires_in: 300, path: "/ws/a.txt" }, 200);
      }
      return json({ status: "deleted", path: "/ws/a.txt", hard: true }, 200);
    }));

    const res = await fsDelete("/ws/a.txt", { hard: true });
    expect(res).toEqual({ ok: true, status: "deleted" });
    expect(calls).toEqual([
      { method: "GET", url: "/api/v1/fs/delete-token?path=%2Fws%2Fa.txt" },
      { method: "DELETE", url: "/api/v1/fs/delete?path=%2Fws%2Fa.txt&confirm=true&token=tok-1&hard=true" },
    ]);
  });

  it("默认删除进回收站：返回 undoToken 与撤销窗口（expires_in=600），URL 不带 hard", async () => {
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.includes("/api/v1/fs/delete-token")) {
        return json({ token: "tok-9", expires_in: 300, path: "/ws/a.txt" }, 200);
      }
      expect(init?.method).toBe("DELETE");
      expect(url).not.toContain("hard=true");
      return json(
        {
          status: "trashed",
          path: "/ws/a.txt",
          trash_path: "/ws/.trash/a.txt.1690000000",
          undo_token: "undo-1",
          expires_in: 600,
          hard: false,
        },
        200
      );
    }));

    const res = await fsDelete("/ws/a.txt");
    expect(res.ok).toBe(true);
    expect(res.status).toBe("trashed");
    expect(res.undoToken).toBe("undo-1");
    expect(res.expiresIn).toBe(600);
  });

  it("409 token_invalid → 重取令牌再试一次（仅一次），第二次成功且透传 undoToken", async () => {
    let issues = 0;
    const deleteUrls: string[] = [];
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/api/v1/fs/delete-token")) {
        issues += 1;
        return json({ token: `tok-${issues}`, expires_in: 300, path: "/ws/b" }, 200);
      }
      deleteUrls.push(url);
      if (deleteUrls.length === 1) {
        return json({ error: "token_invalid", detail: "令牌不存在或已失效。" }, 409);
      }
      return json(
        { status: "trashed", path: "/ws/b", trash_path: "/ws/.trash/b", undo_token: "undo-2", expires_in: 600, hard: false },
        200
      );
    }));

    const res = await fsDelete("/ws/b");
    expect(res.ok).toBe(true);
    expect(res.undoToken).toBe("undo-2");
    expect(issues).toBe(2); // 重取恰好一次
    expect(deleteUrls).toHaveLength(2); // 有界：共两次 DELETE
    expect(deleteUrls[1]).toContain("token=tok-2");
  });

  it("重试后仍 409 → ok=false（不再抛异常），error 含 error 码与 detail，且不含 token 原文", async () => {
    let deleteCalls = 0;
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/api/v1/fs/delete-token")) {
        return json({ token: "SECRET-TOKEN-9f", expires_in: 300, path: "/ws/c" }, 200);
      }
      deleteCalls += 1;
      return json({ error: "token_invalid", detail: "令牌不存在或已失效。" }, 409);
    }));

    const res = await fsDelete("/ws/c");
    expect(res.ok).toBe(false);
    expect(res.error).toContain("token_invalid");
    expect(res.error).toContain("令牌不存在或已失效"); // detail 透出，可读
    expect(res.error).not.toContain("SECRET-TOKEN-9f");
    expect(deleteCalls).toBe(2); // 首次 + 有界重试一次，无死循环
  });

  it("409 confirm_token_required 同样触发一次重试", async () => {
    let issues = 0;
    let deleteCalls = 0;
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/api/v1/fs/delete-token")) {
        issues += 1;
        return json({ token: `tok-${issues}`, expires_in: 300, path: "/ws/d" }, 200);
      }
      deleteCalls += 1;
      if (deleteCalls === 1) {
        return json({ error: "confirm_token_required", detail: "删除须两步确认" }, 409);
      }
      return json({ status: "trashed", path: "/ws/d", trash_path: "/ws/.trash/d", undo_token: "undo-4", expires_in: 600, hard: false }, 200);
    }));

    const res = await fsDelete("/ws/d");
    expect(res.ok).toBe(true);
    expect(res.undoToken).toBe("undo-4");
    expect(issues).toBe(2);
    expect(deleteCalls).toBe(2);
  });

  it("非令牌类 409（如 protected_root）不重试，直接 ok=false 且 error 可读", async () => {
    let issues = 0;
    let deleteCalls = 0;
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/api/v1/fs/delete-token")) {
        issues += 1;
        return json({ token: "tok-1", expires_in: 300, path: "/ws/e" }, 200);
      }
      deleteCalls += 1;
      return json({ error: "protected_root", detail: "受保护路径（workspace root），拒绝删除。" }, 409);
    }));

    const res = await fsDelete("/ws/e");
    expect(res.ok).toBe(false);
    expect(res.error).toContain("protected_root");
    expect(res.error).toContain("受保护路径");
    expect(issues).toBe(1);
    expect(deleteCalls).toBe(1);
  });

  it("令牌领取失败（如 404 file_not_found）→ ok=false 且 error 可读，不发 DELETE", async () => {
    let deleteCalls = 0;
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/api/v1/fs/delete-token")) {
        return json({ error: "file_not_found", detail: "目标不存在" }, 404);
      }
      deleteCalls += 1;
      return json({ status: "deleted" }, 200);
    }));

    const res = await fsDelete("/ws/gone");
    expect(res.ok).toBe(false);
    expect(res.error).toContain("file_not_found");
    expect(res.error).toContain("目标不存在");
    expect(deleteCalls).toBe(0);
  });

  it("网络失败（fetch 抛错）→ ok=false，不抛未捕获异常", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => {
      throw new TypeError("offline");
    }));
    const res = await fsDelete("/ws/offline");
    expect(res.ok).toBe(false);
    expect(res.error).toBeTruthy();
  });
});

describe("fsRestore 撤销删除（P2-4）", () => {
  it("成功：POST /fs/restore?token=...，返回 {ok:true}", async () => {
    const calls: string[] = [];
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      calls.push(`${init?.method ?? "GET"} ${String(input)}`);
      return json({ status: "restored", path: "/ws/a.txt" }, 200);
    }));
    await expect(fsRestore("undo-1")).resolves.toEqual({ ok: true });
    expect(calls).toEqual(["POST /api/v1/fs/restore?token=undo-1"]);
  });

  it("409 undo_token_invalid → ok=false，中文文案透出后端 detail", async () => {
    vi.stubGlobal("fetch", vi.fn(async () =>
      json({ error: "undo_token_invalid", detail: "撤销窗口已过期（10 分钟）。" }, 409)
    ));
    const res = await fsRestore("undo-1");
    expect(res.ok).toBe(false);
    expect(res.error).toContain("撤销窗口已过期或令牌失效");
    expect(res.error).toContain("撤销窗口已过期（10 分钟）");
  });

  it("409 restore_conflict → ok=false，文案区分“原路径被占、文件仍在回收站”", async () => {
    vi.stubGlobal("fetch", vi.fn(async () =>
      json({ error: "restore_conflict", detail: "原路径已存在，拒绝覆盖: /ws/a.txt" }, 409)
    ));
    const res = await fsRestore("undo-1");
    expect(res.ok).toBe(false);
    expect(res.error).toContain("原路径已被占用");
    expect(res.error).toContain("仍保留在回收站");
  });

  it("404 trash_missing → ok=false，文案区分“回收站条目丢失”", async () => {
    vi.stubGlobal("fetch", vi.fn(async () =>
      json({ error: "trash_missing", detail: "回收站条目不存在（可能已被清理）。" }, 404)
    ));
    const res = await fsRestore("undo-1");
    expect(res.ok).toBe(false);
    expect(res.error).toContain("回收站条目不存在");
  });

  it("网络失败 → ok=false，不抛未捕获异常", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => {
      throw new TypeError("offline");
    }));
    const res = await fsRestore("undo-1");
    expect(res.ok).toBe(false);
    expect(res.error).toBeTruthy();
  });
});

describe("FileTree 删除撤销交互（P2-4）", () => {
  function stubTrashFlow(restore: () => Response) {
    let trashed = false;
    let restored = false;
    let treeCalls = 0;
    const restoreUrls: string[] = [];
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.includes("/api/v1/fs/delete-token")) {
        return json({ token: "tok-1", expires_in: 300, path: "/ws/a.txt" }, 200);
      }
      if (url.includes("/api/v1/fs/delete") && init?.method === "DELETE") {
        trashed = true;
        return json(
          {
            status: "trashed",
            path: "/ws/a.txt",
            trash_path: "/ws/.trash/a.txt.1690000000",
            undo_token: "undo-1",
            expires_in: 600,
            hard: false,
          },
          200
        );
      }
      if (url.includes("/api/v1/fs/restore")) {
        restored = true;
        restoreUrls.push(url);
        return restore();
      }
      if (url.includes("/api/v1/fs/tree")) {
        treeCalls += 1;
        return json(
          {
            path: "/ws",
            parent: null,
            dirs: [],
            files: trashed && !restored ? [] : [{ name: "a.txt", size: 5 }],
          },
          200
        );
      }
      return json({}, 404);
    }));
    return {
      treeCalls: () => treeCalls,
      restoreUrls: () => restoreUrls,
    };
  }

  async function deleteToTrash() {
    render(createElement(FileTree, { sessionId: "s1" }));
    await waitFor(() => expect(screen.getByText("a.txt")).toBeInTheDocument());
    fireEvent.click(screen.getByTitle("删除"));
    fireEvent.click(screen.getByText("确认?"));
    await waitFor(() => expect(screen.getByTestId("undo-delete-toast")).toBeInTheDocument());
  }

  it("删除成功后出现撤销入口（含文件名与 10 分钟倒计时起点）", async () => {
    stubTrashFlow(() => json({ status: "restored", path: "/ws/a.txt" }, 200));
    await deleteToTrash();
    const toast = screen.getByTestId("undo-delete-toast");
    expect(toast).toHaveTextContent("a.txt");
    expect(toast).toHaveTextContent(/10:00|9:59/);
    expect(screen.getByTestId("undo-delete-btn")).toBeInTheDocument();
  });

  it("点击撤销 → 调用 /fs/restore?token=undo-1 并刷新父目录，提示“已恢复”", async () => {
    const stub = stubTrashFlow(() => json({ status: "restored", path: "/ws/a.txt" }, 200));
    await deleteToTrash();
    const treesAfterDelete = stub.treeCalls();
    fireEvent.click(screen.getByTestId("undo-delete-btn"));
    await waitFor(() => expect(screen.getByText("a.txt")).toBeInTheDocument()); // 已恢复并刷新
    expect(stub.restoreUrls()).toEqual(["/api/v1/fs/restore?token=undo-1"]);
    expect(stub.treeCalls()).toBeGreaterThan(treesAfterDelete); // 父目录已刷新
    expect(screen.getByTestId("undo-done")).toHaveTextContent("已恢复");
    expect(screen.queryByTestId("undo-delete-toast")).toBeNull(); // 入口关闭
  });

  it("撤销失败（409 undo_token_invalid）→ 显示错误、不刷新、不谎报成功、入口保留", async () => {
    const stub = stubTrashFlow(() =>
      json({ error: "undo_token_invalid", detail: "撤销窗口已过期（10 分钟）。" }, 409)
    );
    await deleteToTrash();
    const treesAfterDelete = stub.treeCalls();
    fireEvent.click(screen.getByTestId("undo-delete-btn"));
    await waitFor(() => expect(screen.getByTestId("undo-error")).toHaveTextContent("撤销窗口已过期"));
    expect(stub.treeCalls()).toBe(treesAfterDelete); // 失败不刷新
    expect(screen.queryByTestId("undo-done")).toBeNull(); // 不谎报成功
    expect(screen.getByTestId("undo-delete-toast")).toBeInTheDocument(); // 入口保留可重试
  });

  it("Esc 关闭撤销提示", async () => {
    stubTrashFlow(() => json({ status: "restored", path: "/ws/a.txt" }, 200));
    await deleteToTrash();
    fireEvent.keyDown(screen.getByTestId("undo-delete-btn"), { key: "Escape" });
    expect(screen.queryByTestId("undo-delete-toast")).toBeNull();
  });
});
