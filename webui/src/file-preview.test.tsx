// 右侧栏预览（对齐 DSH documentpreview + sidebar tab 语义）行为测试：
// tab 化（身份/聚焦/关闭/常驻）、HTML 相对 .js/.css 依赖打包（readRelated，
// 上限与 fail-not-partial）、行号锚点跳转（翻页/挂起/一次性应答）、
// `path:42` 链接化、chips/文件树 → 右侧栏打开。

import { afterEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { FilePreviewView, packHtmlDependencies } from "./components/FilePreviewView";
import { PreviewTabsPanel } from "./components/PreviewTabsPanel";
import { FileTree } from "./components/sidebar/FileTree";
import { RightPanel } from "./components/layout/RightPanel";
import { MessageItem } from "./components/conversation/MessageItem";
import { previewTabsStore, rightPanelStore } from "./core/stores";
import { previewWatcher } from "./core/previewWatch";
import { renderMarkdown } from "./core/markdown";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  previewTabsStore.closeAll();
  previewTabsStore.bindSession("");
  rightPanelStore.setOpen(false);
  rightPanelStore.setTab("settings");
  localStorage.clear();
});

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status });
}

type Route = { match: (url: string) => boolean; body: (url: string) => unknown; status?: number };

function previewRouter(routes: Route[]) {
  return vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    for (const r of routes) {
      if (r.match(url)) return jsonResponse(r.body(url), r.status);
    }
    return jsonResponse({}, 404);
  });
}

function textPage(path: string, offset: number, lines: string, eof: boolean, mtimeNs = 100) {
  return {
    type: "text" as const,
    path,
    size: 100,
    mtime_ns: mtimeNs,
    offset,
    lines: lines.split("\n").length,
    content: lines,
    eof,
    truncated: !eof,
  };
}

const createdBlobs: Blob[] = [];

function stubBlobUrl() {
  createdBlobs.length = 0;
  class FakeURL extends URL {
    static createObjectURL(b: Blob): string {
      createdBlobs.push(b);
      return `blob:${b.type}`;
    }
    static revokeObjectURL(): void {}
  }
  vi.stubGlobal("URL", FakeURL);
}

function relatedBody(content: string, opts: { path?: string; mime?: string; raw?: boolean } = {}) {
  const raw = opts.raw ?? false;
  return {
    type: "related" as const,
    path: opts.path ?? "/abs",
    size: content.length,
    mime: opts.mime ?? "text/javascript",
    content_base64: raw ? content : btoa(content),
  };
}

describe("PreviewTabsPanel：右侧栏 tab 化", () => {
  it("open() 建 tab 并渲染视图；同 path 再开聚焦既有 tab", async () => {
    const fetchMock = previewRouter([
      { match: (u) => u.includes("/api/v1/files/preview"), body: () => textPage("a.txt", 1, "hello", true) },
    ]);
    vi.stubGlobal("fetch", fetchMock);
    render(<PreviewTabsPanel />);

    act(() => previewTabsStore.open("a.txt"));
    await waitFor(() => expect(screen.getByTestId("file-preview")).toBeInTheDocument());
    expect(screen.getByText("hello")).toBeInTheDocument();

    act(() => {
      previewTabsStore.open("b.txt");
      previewTabsStore.open("a.txt"); // 再开同路径：聚焦既有
    });
    const { tabs, active } = previewTabsStore.getState();
    expect(tabs.map((t) => t.path)).toEqual(["a.txt", "b.txt"]);
    expect(active).toBe("a.txt");
  });

  it("关闭活动 tab 后相邻 tab 接管；全部关闭显示空态", async () => {
    vi.stubGlobal("fetch", previewRouter([
      { match: (u) => u.includes("/api/v1/files/preview"), body: () => textPage("x", 1, "c", true) },
    ]));
    render(<PreviewTabsPanel />);
    act(() => {
      previewTabsStore.open("one.txt");
      previewTabsStore.open("two.txt");
    });
    await waitFor(() => expect(screen.getAllByTestId("file-preview").length).toBe(2));
    act(() => previewTabsStore.close("two.txt"));
    expect(previewTabsStore.getState().active).toBe("one.txt");
    act(() => previewTabsStore.close("one.txt"));
    await waitFor(() => expect(screen.getByTestId("preview-tabs-empty")).toBeInTheDocument());
  });

  it("tab 标题 = basename；行号目标体现在 :N 徽标", async () => {
    vi.stubGlobal("fetch", previewRouter([
      { match: (u) => u.includes("/api/v1/files/preview"), body: () => textPage("src/deep/mod.py", 1, "l", true) },
    ]));
    render(<PreviewTabsPanel />);
    act(() => previewTabsStore.open("src/deep/mod.py", 42));
    await waitFor(() => expect(screen.getByText("mod.py")).toBeInTheDocument());
    expect(screen.getByText(":42")).toBeInTheDocument();
  });
});

describe("HTML 依赖打包（readRelated 对齐）", () => {
  function htmlBody(scripts: string, mime = "text/html") {
    return {
      type: "html" as const,
      path: "page.html",
      size: 10,
      mime,
      content_base64: btoa(scripts),
    };
  }

  it("相对经典 script 与 stylesheet 内联（去重），iframe 出现", async () => {
    stubBlobUrl();
    const fetchMock = previewRouter([
      {
        match: (u) => u.includes("/api/v1/files/preview"),
        body: () =>
          htmlBody(
            '<html><head><link rel="stylesheet" href="a.css"></head><body>' +
              '<script src="app.js"></script><script src="app.js"></script>' +
              '<script type="module" src="m.js"></script>' +
              '<script src="https://cdn.example/x.js"></script>' +
              '<script src="/abs.js"></script></body></html>'
          ),
      },
      { match: (u) => u.includes("/api/v1/files/related") && u.includes("app.js"), body: () => relatedBody("console.log(1)") },
      { match: (u) => u.includes("/api/v1/files/related") && u.includes("a.css"), body: () => relatedBody("body{}") },
    ]);
    vi.stubGlobal("fetch", fetchMock);
    render(<FilePreviewView path="page.html" line={null} />);
    await screen.findByTestId("preview-html");
    const relatedCalls = fetchMock.mock.calls.filter((c) => String(c[0]).includes("/api/v1/files/related"));
    const urls = relatedCalls.map((c) => String(c[0]));
    // 仅相对 .js/.css；module/https/绝对路径不打包；重复引用只读一次
    expect(urls.some((u) => u.includes("app.js"))).toBe(true);
    expect(urls.some((u) => u.includes("a.css"))).toBe(true);
    expect(urls.filter((u) => u.includes("app.js")).length).toBe(1);
    expect(urls.some((u) => u.includes("m.js"))).toBe(false);
    expect(urls.some((u) => u.includes("cdn.example"))).toBe(false);
    expect(urls.some((u) => u.includes("abs.js"))).toBe(false);
  });

  it("<base href> 存在时不打包（浏览器解析）", async () => {
    stubBlobUrl();
    const fetchMock = previewRouter([
      {
        match: (u) => u.includes("/api/v1/files/preview"),
        body: () => htmlBody('<html><head><base href="https://x/"></head><body><script src="app.js"></script></body></html>'),
      },
    ]);
    vi.stubGlobal("fetch", fetchMock);
    render(<FilePreviewView path="page.html" line={null} />);
    await screen.findByTestId("preview-html");
    expect(fetchMock.mock.calls.some((c) => String(c[0]).includes("/api/v1/files/related"))).toBe(false);
  });

  it("任一依赖失败 → 整体错误态（不部分发布）", async () => {
    stubBlobUrl();
    vi.stubGlobal(
      "fetch",
      previewRouter([
        {
          match: (u) => u.includes("/api/v1/files/preview"),
          body: () => htmlBody("<html><body><script src=\"app.js\"></script></body></html>"),
        },
        { match: (u) => u.includes("/api/v1/files/related"), status: 404, body: () => ({ error: "file_not_found" }) },
      ])
    );
    render(<FilePreviewView path="page.html" line={null} />);
    await waitFor(() => expect(screen.getByRole("alert")).toBeInTheDocument());
    expect(screen.getByRole("alert").textContent).toContain("app.js");
  });

  it("超过 64 个不同资产 → 打包失败", async () => {
    const refs = Array.from({ length: 65 }, (_, i) => `<script src="f${i}.js"></script>`).join("");
    vi.stubGlobal(
      "fetch",
      previewRouter([
        {
          match: (u) => u.includes("/api/v1/files/preview"),
          body: () => htmlBody(`<html><body>${refs}</body></html>`),
        },
        {
          match: (u) => u.includes("/api/v1/files/related"),
          // absPath 按 ref 唯一（countedPaths 以解析后绝对路径去重）
          body: (u) => {
            const ref = new URL(u, "http://x").searchParams.get("path") ?? "x.js";
            return relatedBody("console.log(1)", { path: `/ws/${ref}` });
          },
        },
      ])
    );
    await expect(packHtmlDependencies("page.html", `<body>${refs}</body>`)).rejects.toThrow(/64/);
  });
});

describe("行号锚点跳转", () => {
  it("目标行在后续页：自动翻页直至包含并高亮，一次性应答", async () => {
    const fetchMock = previewRouter([
      { match: (u) => u.includes("offset=1&"), body: () => textPage("big.py", 1, "l1\nl2", false) },
      { match: (u) => u.includes("offset=3&"), body: () => textPage("big.py", 3, "l3\nl4", true) },
    ]);
    vi.stubGlobal("fetch", fetchMock);
    render(<FilePreviewView path="big.py" line={4} lineSeq={1} />);
    // 自动翻页到 offset=3（不重叠）
    await waitFor(() =>
      expect(fetchMock.mock.calls.some((c) => String(c[0]).includes("offset=3&"))).toBe(true)
    );
    await waitFor(() => {
      const el = document.querySelector('[data-line="4"]');
      expect(el?.classList.contains("anchor-flash")).toBe(true);
    });
    expect(screen.getByText("l4")).toBeInTheDocument();
    expect(screen.queryByTestId("preview-load-more")).toBeNull(); // eof
  });

  it("Markdown 渲染态挂起；切纯文本后执行跳转", async () => {
    vi.stubGlobal(
      "fetch",
      previewRouter([
        {
          match: (u) => u.includes("/api/v1/files/preview"),
          body: () => textPage("note.md", 1, "# T\n\nbody", true),
        },
      ])
    );
    render(<FilePreviewView path="note.md" line={3} lineSeq={1} />);
    await waitFor(() => expect(screen.getByTestId("preview-markdown")).toBeInTheDocument());
    // 挂起提示可见
    expect(screen.getByText(/第 3 行/)).toBeInTheDocument();
    expect(document.querySelector('[data-line="3"]')).toBeNull();
    // 切纯文本 → 执行
    fireEvent.click(screen.getByTitle("以纯文本查看"));
    await waitFor(() => {
      const el = document.querySelector('[data-line="3"]');
      expect(el?.classList.contains("anchor-flash")).toBe(true);
    });
  });

  it("同值行号再请求（新 seq）重新触发跳转", async () => {
    vi.stubGlobal(
      "fetch",
      previewRouter([
        { match: (u) => u.includes("/api/v1/files/preview"), body: () => textPage("a.py", 1, "one", true) },
      ])
    );
    const { rerender } = render(<FilePreviewView path="a.py" line={1} lineSeq={1} />);
    await waitFor(() => expect(screen.getByText("one")).toBeInTheDocument());
    await waitFor(() => {
      expect(document.querySelector('[data-line="1"]')?.classList.contains("anchor-flash")).toBe(true);
    });
    // 同值行号新 seq：重新挂起并再次锚定（对齐 DSH 新 revision 应答）
    rerender(<FilePreviewView path="a.py" line={1} lineSeq={2} />);
    await waitFor(() => {
      expect(document.querySelector('[data-line="1"]')).not.toBeNull();
    });
  });
});

describe("`path:42` 行号链接化", () => {
  it("inline code 携带行号 → data-path 剥离 :42、data-line=42", () => {
    const html = renderMarkdown("看 `src/a.py:42` 的实现", new Set(["src/a.py"]));
    expect(html).toContain('data-path="src/a.py"');
    expect(html).toContain('data-line="42"');
    expect(html).not.toContain('data-path="src/a.py:42"');
  });

  it("无行号路径链接保持原样", () => {
    const html = renderMarkdown("看 `src/a.py` 的实现", new Set(["src/a.py"]));
    expect(html).toContain('data-path="src/a.py"');
    expect(html).not.toContain("data-line");
  });
});

describe("入口联动（chips / 文件树 → 右侧栏预览 tab）", () => {
  it("MessageItem 出产物 chip 点击 → previewTabsStore 打开 + 面板 reveal", () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse({ sessions: [], count: 0 })));
    render(
      <MessageItem
        msg={{
          role: "assistant",
          content: "",
          toolCalls: [{ id: "c1", name: "edit_file", arguments: { path: "src/a.py" } }],
        }}
      />
    );
    fireEvent.click(screen.getByText("src/a.py"));
    const { tabs, active } = previewTabsStore.getState();
    expect(tabs.map((t) => t.path)).toEqual(["src/a.py"]);
    expect(active).toBe("src/a.py");
    expect(rightPanelStore.getState().open).toBe(true);
    expect(rightPanelStore.getState().tab).toBe("preview");
  });

  it("FileTree 点击文件 → 打开预览 tab（不再本地挂模态）", async () => {
    vi.stubGlobal(
      "fetch",
      previewRouter([
        {
          match: (u) => u.includes("/api/v1/fs/tree"),
          body: () => ({ path: "/ws", parent: null, dirs: [], files: [{ name: "a.txt", size: 5 }] }),
        },
      ])
    );
    render(<FileTree sessionId="s1" />);
    await waitFor(() => expect(screen.getByText("a.txt")).toBeInTheDocument());
    fireEvent.click(screen.getByText("a.txt"));
    expect(previewTabsStore.getState().tabs.map((t) => t.path)).toEqual(["/ws/a.txt"]);
    expect(screen.queryByTestId("file-preview")).toBeNull(); // 模态不复存在
  });
});

describe("预览 tab 布局按会话持久化（对齐 DSH Session 布局绑定）", () => {
  it("bindSession 切换：旧会话布局落盘、新会话取自己的桶、切回恢复 tabs+line+col+active", () => {
    previewTabsStore.bindSession("sA");
    previewTabsStore.open("a1.py");
    previewTabsStore.open("a2.py", 42, 7);
    previewTabsStore.setActive("a1.py");

    previewTabsStore.bindSession("sB"); // 切走 → sA 落盘，sB 从空桶开始
    expect(previewTabsStore.getState().tabs).toEqual([]);
    previewTabsStore.open("b1.md");

    previewTabsStore.bindSession("sA"); // 切回 → 恢复
    const { tabs, active } = previewTabsStore.getState();
    expect(tabs.map((t) => t.path)).toEqual(["a1.py", "a2.py"]);
    expect(tabs[1].line).toBe(42);
    expect(tabs[1].col).toBe(7);
    expect(active).toBe("a1.py");

    previewTabsStore.bindSession("sB");
    expect(previewTabsStore.getState().tabs.map((t) => t.path)).toEqual(["b1.md"]);
  });

  it("持久化落在 localStorage：模块重载（模拟刷新）后 bindSession 恢复", async () => {
    previewTabsStore.bindSession("sX");
    previewTabsStore.open("deep/note.md", 3);
    vi.resetModules();
    const fresh = await import("./core/stores");
    fresh.previewTabsStore.bindSession("sX");
    const { tabs, active } = fresh.previewTabsStore.getState();
    expect(tabs.map((t) => t.path)).toEqual(["deep/note.md"]);
    expect(tabs[0].line).toBe(3);
    expect(active).toBe("deep/note.md");
  });

  it("存储桶内 tab 数量有上限（保留最近的）", () => {
    previewTabsStore.bindSession("sCap");
    for (let i = 0; i < 20; i += 1) previewTabsStore.open(`f${i}.txt`);
    const raw = JSON.parse(localStorage.getItem("lfl-preview-layout-v1") ?? "{}") as {
      sCap?: { tabs: Array<{ path: string }>; active: string };
    };
    expect((raw.sCap?.tabs ?? []).length).toBeLessThanOrEqual(16);
    expect(raw.sCap?.active).toBe("f19.txt");
  });

  it("布局持久化不含内容（字节/分页不入存储，重开重取）", () => {
    previewTabsStore.bindSession("sC");
    previewTabsStore.open("a.py", 9, 3);
    const raw = localStorage.getItem("lfl-preview-layout-v1") ?? "";
    expect(raw).not.toContain("content");
    expect(raw).not.toContain("content_base64");
    expect(raw).not.toContain("pages");
  });
});

describe("行号锚点按列定位（line:col）", () => {
  it("链接化：`path:42:7` → data-line=42 data-col=7；`path:42` → 无 data-col", () => {
    const withCol = renderMarkdown("见 `src/a.py:42:7`", new Set(["src/a.py"]));
    expect(withCol).toContain('data-path="src/a.py"');
    expect(withCol).toContain('data-line="42"');
    expect(withCol).toContain('data-col="7"');

    const noCol = renderMarkdown("见 `src/a.py:42`", new Set(["src/a.py"]));
    expect(noCol).toContain('data-line="42"');
    expect(noCol).not.toContain("data-col");
  });

  it("MessageItem 链接点击透传列号到 tab 状态", () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse({ sessions: [], count: 0 })));
    render(
      <MessageItem
        msg={{ role: "assistant", content: "见 `src/a.py:42:7`", toolCalls: [] }}
      />
    );
    fireEvent.click(document.querySelector(".v2-file-link") as HTMLElement);
    const tab = previewTabsStore.getState().tabs[0];
    expect(tab.path).toBe("src/a.py");
    expect(tab.line).toBe(42);
    expect(tab.col).toBe(7);
  });

  it("视图：目标行+列 → 该行内列字符高亮锚点（data-anchor-col）", async () => {
    vi.stubGlobal(
      "fetch",
      previewRouter([
        {
          match: (u) => u.includes("/api/v1/files/preview"),
          body: () => textPage("a.py", 1, "alpha\nbeta", true),
        },
      ])
    );
    render(<FilePreviewView path="a.py" line={2} col={3} lineSeq={1} />);
    await waitFor(() => {
      const colEl = document.querySelector("[data-anchor-col]");
      expect(colEl).not.toBeNull();
      expect(colEl?.classList.contains("anchor-flash")).toBe(true);
    });
    // 行 2 = "beta"，col 3（1-based）= 't'
    expect(document.querySelector("[data-anchor-col]")?.textContent).toBe("t");
    expect(document.querySelector('[data-line="2"]')?.classList.contains("anchor-flash")).toBe(true);
  });

  it("列号超出行长：仅行锚点，不出列字符也不报错", async () => {
    vi.stubGlobal(
      "fetch",
      previewRouter([
        {
          match: (u) => u.includes("/api/v1/files/preview"),
          body: () => textPage("a.py", 1, "ab", true),
        },
      ])
    );
    render(<FilePreviewView path="a.py" line={1} col={99} lineSeq={1} />);
    await waitFor(() => {
      expect(document.querySelector('[data-line="1"]')?.classList.contains("anchor-flash")).toBe(true);
    });
    expect(document.querySelector("[data-anchor-col]")).toBeNull();
  });

  it("tab 徽标带列：`:42:7`", async () => {
    vi.stubGlobal("fetch", previewRouter([
      { match: (u) => u.includes("/api/v1/files/preview"), body: () => textPage("mod.py", 1, "l", true) },
    ]));
    render(<PreviewTabsPanel />);
    act(() => previewTabsStore.open("mod.py", 42, 7));
    await waitFor(() => expect(screen.getByText(":42:7")).toBeInTheDocument());
  });
});

describe("版本变更监听（对齐 DSH changes 流 + stale 页提示）", () => {
  it("观察到的版本较新 → stale 横幅出现、内容不自动替换；重载后清横幅", async () => {
    let previewCalls = 0;
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/api/v1/files/stat")) {
        // 磁盘现状恒为 mtime 200（打开后已被外部改写）
        return jsonResponse({ path: "a.txt", size: 100, mtime_ns: 200 });
      }
      if (url.includes("/api/v1/files/preview")) {
        previewCalls += 1;
        // 首载拿到旧版本（100）；重载后拿到磁盘现状（200）
        return jsonResponse(textPage("a.txt", 1, previewCalls > 1 ? "new-content" : "old-content", true, previewCalls > 1 ? 200 : 100));
      }
      return jsonResponse({}, 404);
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<FilePreviewView path="a.txt" line={null} />);
    await waitFor(() => expect(screen.getByText("old-content")).toBeInTheDocument());
    expect(screen.queryByTestId("preview-stale")).toBeNull();

    await act(async () => {
      await previewWatcher.pollNow(); // 观察到 mtime 200 ≠ 读取基线 100
    });
    await waitFor(() => expect(screen.getByTestId("preview-stale")).toBeInTheDocument());
    expect(screen.getByText(/已变更/)).toBeInTheDocument();
    expect(screen.getByText("old-content")).toBeInTheDocument(); // 不自动替换

    fireEvent.click(screen.getByRole("button", { name: /重新加载/ }));
    await waitFor(() => expect(screen.queryByTestId("preview-stale")).toBeNull()); // 已观察版本不再报变更
    expect(previewCalls).toBe(2);
    // 行文本经语法高亮 span 拆分，断言用行级 textContent
    expect(document.querySelector(".v2-preview-lines")?.textContent).toContain("new-content");
  });

  it("文件消失（stat 404）→ absent 提示，内容保留", async () => {
    vi.stubGlobal(
      "fetch",
      previewRouter([
        { match: (u) => u.includes("/api/v1/files/preview"), body: () => textPage("g.txt", 1, "kept", true) },
        { match: (u) => u.includes("/api/v1/files/stat"), status: 404, body: () => ({ error: "file_not_found" }) },
      ])
    );
    render(<FilePreviewView path="g.txt" line={null} />);
    await waitFor(() => expect(screen.getByText("kept")).toBeInTheDocument());
    await act(async () => {
      await previewWatcher.pollNow();
    });
    await waitFor(() => expect(screen.getByTestId("preview-stale")).toBeInTheDocument());
    expect(screen.getByText(/不在磁盘上/)).toBeInTheDocument();
    expect(screen.getByText("kept")).toBeInTheDocument();
  });

  it("观察失败（stat 500）不冒充 stale", async () => {
    vi.stubGlobal(
      "fetch",
      previewRouter([
        { match: (u) => u.includes("/api/v1/files/preview"), body: () => textPage("s.txt", 1, "v", true) },
        { match: (u) => u.includes("/api/v1/files/stat"), status: 500, body: () => ({ error: "read_failed" }) },
      ])
    );
    render(<FilePreviewView path="s.txt" line={null} />);
    await waitFor(() => expect(screen.getByText("v")).toBeInTheDocument());
    await act(async () => {
      await previewWatcher.pollNow();
      await new Promise((r) => setTimeout(r, 30));
    });
    expect(screen.queryByTestId("preview-stale")).toBeNull();
  });

  it("分页续读版本漂移 → 不混版本，从头重读新版本", async () => {
    // 首载（offset=1）返回旧版本 eof=false；加载更多 offset=3 返回 mtime 200
    // （≠基线 100）→ 触发 offset=1 重读（同一 URL，按调用顺序区分）新版本。
    const previewCalls: string[] = [];
    const mock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/api/v1/files/stat")) return jsonResponse({ size: 1, mtime_ns: 100 });
      if (url.includes("/api/v1/files/preview")) {
        if (url.includes("offset=3")) {
          previewCalls.push("3");
          return jsonResponse(textPage("d.txt", 3, "p2", false, 200));
        }
        previewCalls.push("1");
        const first = previewCalls.filter((c) => c === "1").length === 1;
        return jsonResponse(
          first
            ? textPage("d.txt", 1, "old-v1-l1\nold-v1-l2", false, 100)
            : textPage("d.txt", 1, "new-v2-l1\nnew-v2-l2", false, 200)
        );
      }
      return jsonResponse({}, 404);
    });
    vi.stubGlobal("fetch", mock);
    render(<FilePreviewView path="d.txt" line={null} />);
    await waitFor(() => expect(screen.getByText("old-v1-l2")).toBeInTheDocument());
    fireEvent.click(screen.getByTestId("preview-load-more"));
    await waitFor(() =>
      expect(document.querySelector(".v2-preview-lines")?.textContent).toContain("new-v2-l2")
    );
    expect(document.querySelector(".v2-preview-lines")?.textContent).not.toContain("old-v1-l1"); // 不混版本
    expect(previewCalls).toEqual(["1", "3", "1"]); // 首载 → 漂移续读 → 从头重读
  });
});

describe("HTML 预览 CSS 资源打包（url() / @import）", () => {
  function htmlBody(content: string) {
    return {
      type: "html" as const,
      path: "page.html",
      size: 10,
      mtime_ns: 1,
      mime: "text/html",
      content_base64: btoa(content),
    };
  }

  it("css 内相对 url(图片) → data URI；https/data 引用不打包", async () => {
    stubBlobUrl();
    const cssText = "body{background:url(bg.png)} .a{src:url('https://cdn/x.png')} .b{list-style:url(data:image/png;base64,AAAA)}";
    const fetchMock = previewRouter([
      {
        match: (u) => u.includes("/api/v1/files/preview"),
        body: () => htmlBody('<html><head><link rel="stylesheet" href="css/main.css"></head><body></body></html>'),
      },
      {
        match: (u) => u.includes("/api/v1/files/related") && u.includes("main.css"),
        body: () => relatedBody(cssText, { path: "/ws/css/main.css", mime: "text/css" }),
      },
      {
        match: (u) => u.includes("/api/v1/files/related") && u.includes("bg.png"),
        body: () => relatedBody(epsBase64("PNGDATA"), { path: "/ws/css/bg.png", mime: "image/png", raw: true }),
      },
    ]);
    vi.stubGlobal("fetch", fetchMock);
    render(<FilePreviewView path="page.html" line={null} />);
    await screen.findByTestId("preview-html");
    // bg.png 以 css 文件为 base 解析
    await waitFor(() => {
      const call = fetchMock.mock.calls.find(
        (c) => String(c[0]).includes("/api/v1/files/related") && String(c[0]).includes("bg.png")
      );
      expect(call).toBeTruthy();
      expect(String(call![0])).toContain(encodeURIComponent("/ws/css/main.css"));
    });
    const html = (await Promise.all(createdBlobs.map(readBlobText))).join("\n");
    expect(html).toContain("url(data:image/png;base64,");
    expect(html).not.toContain("url(bg.png)");
    expect(html).toContain("https://cdn/x.png"); // 非 relative 原样保留
    expect(fetchMock.mock.calls.filter((c) => String(c[0]).includes("/api/v1/files/related")).length).toBe(2);
  });

  it("@import 相对 css 递归内联（以被导入 css 为 base）", async () => {
    stubBlobUrl();
    const fetchMock = previewRouter([
      {
        match: (u) => u.includes("/api/v1/files/preview"),
        body: () => htmlBody('<html><head><link rel="stylesheet" href="a.css"></head><body></body></html>'),
      },
      {
        match: (u) => u.includes("/api/v1/files/related") && u.includes("a.css") && !u.includes("sub.css"),
        body: () => relatedBody('@import "sub.css"; body{color:red}', { path: "/ws/a.css", mime: "text/css" }),
      },
      {
        match: (u) => u.includes("/api/v1/files/related") && u.includes("sub.css"),
        body: () => relatedBody(".x{margin:0}", { path: "/ws/sub.css", mime: "text/css" }),
      },
    ]);
    vi.stubGlobal("fetch", fetchMock);
    render(<FilePreviewView path="page.html" line={null} />);
    await screen.findByTestId("preview-html");
    await waitFor(() => {
      const subCall = fetchMock.mock.calls.find(
        (c) => String(c[0]).includes("/api/v1/files/related") && String(c[0]).includes("sub.css")
      );
      expect(subCall).toBeTruthy();
      expect(String(subCall![0])).toContain(encodeURIComponent("/ws/a.css"));
    });
    const html = (await Promise.all(createdBlobs.map(readBlobText))).join("\n");
    expect(html).toContain(".x{margin:0}");
    expect(html).not.toContain("@import");
  });
});

/** 把原始字节串按每字节转成 latin1 字符后 btoa（构造二进制 base64，与 TextDecoder 无关） */
function epsBase64(s: string): string {
  return btoa(s);
}

/** jsdom Blob 无 .text()：FileReader 兜底读取断言内容 */
function readBlobText(b: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const fr = new FileReader();
    fr.onload = () => resolve(String(fr.result));
    fr.onerror = () => reject(fr.error);
    fr.readAsText(b);
  });
}

describe("Markdown 渲染默认视图（回归：tab 化重构后补回直测）", () => {
  it(".md 默认渲染 Markdown（非纯文本行号视图）；切纯文本出 data-line", async () => {
    vi.stubGlobal(
      "fetch",
      previewRouter([
        {
          match: (u) => u.includes("/api/v1/files/preview"),
          body: () => textPage("readme.md", 1, "# 标题A\n\n正文B", true),
        },
      ])
    );
    render(<FilePreviewView path="readme.md" line={null} />);
    await waitFor(() => expect(screen.getByTestId("preview-markdown")).toBeInTheDocument());
    const md = screen.getByTestId("preview-markdown");
    expect(md.querySelector("h1")?.textContent).toContain("标题A");
    expect(md.textContent).toContain("正文B");
    expect(document.querySelector(".v2-preview-line")).toBeNull(); // 非行号纯文本视图
    fireEvent.click(screen.getByTitle("以纯文本查看"));
    await waitFor(() => expect(document.querySelector(".v2-preview-line")).not.toBeNull());
  });

  it(".py 代码默认行号视图（DSH 同规：代码=文本+行号，无渲染形态）", async () => {
    vi.stubGlobal(
      "fetch",
      previewRouter([
        {
          match: (u) => u.includes("/api/v1/files/preview"),
          body: () => textPage("app.py", 1, "print(1)", true),
        },
      ])
    );
    render(<FilePreviewView path="app.py" line={null} />);
    await waitFor(() => expect(document.querySelector('.v2-preview-line[data-line="1"]')).not.toBeNull());
    expect(screen.queryByTestId("preview-markdown")).toBeNull();
  });
});

describe("预览可用性：代码高亮 / 面板宽度与收起", () => {
  it("代码行带语法高亮（shiki-token span，对齐聊天代码块）", async () => {
    vi.stubGlobal(
      "fetch",
      previewRouter([
        {
          match: (u) => u.includes("/api/v1/files/preview"),
          body: () => textPage("app.py", 1, "def main():\n    return 1  # done", true),
        },
      ])
    );
    render(<FilePreviewView path="app.py" line={null} />);
    await waitFor(() => expect(document.querySelector('.v2-preview-line[data-line="1"]')).not.toBeNull());
    const line1 = document.querySelector('.v2-preview-line[data-line="1"]');
    expect(line1?.querySelector(".shiki-keyword")?.textContent).toBe("def");
    const line2 = document.querySelector('.v2-preview-line[data-line="2"]');
    expect(line2?.querySelector(".shiki-number")?.textContent).toBe("1");
    expect(line2?.querySelector(".shiki-comment")?.textContent).toContain("done");
  });

  it("面板宽度：拖拽把手调宽并持久化；clamp 到边界", async () => {
    const { clampPanelWidth, PANEL_WIDTH_KEY } = await import("./App");
    expect(clampPanelWidth(200)).toBe(288); // 下限
    expect(clampPanelWidth(500)).toBe(500);
    expect(clampPanelWidth(2000)).toBeLessThanOrEqual(720); // 上限
    localStorage.setItem(PANEL_WIDTH_KEY, "");
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => jsonResponse({ sessions: [], count: 0 }))
    );
    const { App } = await import("./App");
    let container!: HTMLElement;
    await act(async () => {
      container = render(<App />).container;
      await new Promise((resolve) => window.setTimeout(resolve, 0));
    });
    await waitFor(() => expect(container.querySelector(".v2-panel")).not.toBeNull());
    const handle = container.querySelector('[data-testid="panel-resize-handle"]') as HTMLElement;
    expect(handle).not.toBeNull();
    fireEvent.pointerDown(handle, { clientX: 700, pointerId: 1 });
    fireEvent.pointerMove(window, { clientX: 500, pointerId: 1 });
    fireEvent.pointerUp(window, { pointerId: 1 });
    await waitFor(() => {
      const saved = Number(localStorage.getItem(PANEL_WIDTH_KEY));
      expect(saved).toBeGreaterThan(288);
    });
  });

  it("面板头部内嵌收起按钮 → rightPanelStore.open=false", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => jsonResponse({ sessions: [], count: 0 }))
    );
    rightPanelStore.setOpen(true);
    render(<RightPanel open />);
    const btn = screen.getByTestId("panel-collapse-btn");
    expect(btn).toBeInTheDocument();
    fireEvent.click(btn);
    expect(rightPanelStore.getState().open).toBe(false);
  });
});
