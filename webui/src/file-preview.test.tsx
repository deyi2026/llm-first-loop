// 出产物文件预览模态（对齐 DSH documentpreview 能力面）行为测试：
// 文本分页（不重叠、eof 收敛）、Markdown 渲染、图片 data URI、pdf/html Blob
// iframe（html 沙箱 allow-scripts 且无 allow-same-origin）、目录浏览、已知
// 二进制空态、错误态、重载；文件树点击=预览、✍=协作编辑。

import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { FilePreviewModal } from "./components/FilePreviewModal";
import { FileTree } from "./components/sidebar/FileTree";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status });
}

function previewRouter(routes: Array<{ match: (url: string) => boolean; body: (url: string) => unknown; status?: number }>) {
  return vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    for (const r of routes) {
      if (r.match(url)) return jsonResponse(r.body(url), r.status);
    }
    return jsonResponse({}, 404);
  });
}

function stubBlobUrl() {
  class FakeURL extends URL {
    static createObjectURL(b: Blob): string {
      return `blob:${b.type}`;
    }
    static revokeObjectURL(): void {}
  }
  vi.stubGlobal("URL", FakeURL);
}

describe("FilePreviewModal 多格式预览", () => {
  it("text: 分页加载到 eof，页间不重叠", async () => {
    const fetchMock = previewRouter([
      {
        match: (u) => u.includes("/api/v1/files/preview") && !u.includes("offset=4"),
        body: () => ({
          type: "text", path: "big.txt", size: 40, offset: 1, lines: 3,
          content: "l1\nl2\nl3", eof: false, truncated: true,
        }),
      },
      {
        match: (u) => u.includes("offset=4"),
        body: () => ({
          type: "text", path: "big.txt", size: 40, offset: 4, lines: 1,
          content: "l4", eof: true, truncated: false,
        }),
      },
    ]);
    vi.stubGlobal("fetch", fetchMock);

    render(<FilePreviewModal path="big.txt" onClose={() => {}} />);
    await waitFor(() => expect(screen.getByText("l1")).toBeInTheDocument());
    expect(screen.getByText("l3")).toBeInTheDocument();
    // 未到 eof：行号从 1 开始 + 加载更多可见
    expect(screen.getByText("1").textContent).toBe("1");
    fireEvent.click(screen.getByTestId("preview-load-more"));
    await waitFor(() => expect(screen.getByText("l4")).toBeInTheDocument());
    expect(screen.queryByTestId("preview-load-more")).toBeNull();
    // 第二页 offset = 1 + 3 = 4（单调前进，不重复第一页）
    const second = fetchMock.mock.calls.find((c) => String(c[0]).includes("offset=4"));
    expect(second).toBeTruthy();
  });

  it("md: 默认 Markdown 渲染，可切换纯文本", async () => {
    vi.stubGlobal("fetch", previewRouter([
      {
        match: (u) => u.includes("/api/v1/files/preview"),
        body: () => ({
          type: "text", path: "readme.md", size: 20, offset: 1, lines: 1,
          content: "# 标题", eof: true, truncated: false,
        }),
      },
    ]));
    render(<FilePreviewModal path="readme.md" onClose={() => {}} />);
    await waitFor(() => expect(screen.getByTestId("preview-markdown")).toBeInTheDocument());
    expect(document.querySelector(".v2-preview-markdown, .v2-preview-md h1") || screen.getByTestId("preview-markdown")).toBeTruthy();
    // 切换纯文本：出现行号视图
    fireEvent.click(screen.getByTitle("以纯文本查看"));
    await waitFor(() => expect(screen.getByText("# 标题")).toBeInTheDocument());
  });

  it("image: data URI 渲染 <img>", async () => {
    vi.stubGlobal("fetch", previewRouter([
      {
        match: (u) => u.includes("/api/v1/files/preview"),
        body: () => ({
          type: "image", path: "pic.png", size: 8, mime: "image/png",
          content_base64: btoa("fakepng"),
        }),
      },
    ]));
    render(<FilePreviewModal path="pic.png" onClose={() => {}} />);
    const img = await screen.findByTestId("preview-image");
    await waitFor(() => expect(img.getAttribute("src")).toMatch(/^data:image\/png;base64,/));
  });

  it("html: 沙箱 iframe（allow-scripts 且无 allow-same-origin）", async () => {
    stubBlobUrl();
    vi.stubGlobal("fetch", previewRouter([
      {
        match: (u) => u.includes("/api/v1/files/preview"),
        body: () => ({
          type: "html", path: "page.html", size: 20, mime: "text/html",
          content_base64: btoa("<h1>x</h1>"),
        }),
      },
    ]));
    render(<FilePreviewModal path="page.html" onClose={() => {}} />);
    const frame = await screen.findByTestId("preview-html");
    expect(frame.getAttribute("sandbox")).toBe("allow-scripts");
    expect(frame.getAttribute("src")).toContain("blob:text/html");
  });

  it("pdf: Blob iframe 渲染", async () => {
    stubBlobUrl();
    vi.stubGlobal("fetch", previewRouter([
      {
        match: (u) => u.includes("/api/v1/files/preview"),
        body: () => ({
          type: "pdf", path: "doc.pdf", size: 9, mime: "application/pdf",
          content_base64: btoa("%PDF-fake"),
        }),
      },
    ]));
    render(<FilePreviewModal path="doc.pdf" onClose={() => {}} />);
    const frame = await screen.findByTestId("preview-pdf");
    expect(frame.getAttribute("src")).toContain("blob:application/pdf");
  });

  it("unsupported_binary: 空态且不发内容读取", async () => {
    const fetchMock = previewRouter([
      {
        match: (u) => u.includes("/api/v1/files/preview"),
        body: () => ({ type: "unsupported_binary", path: "arc.zip", ext: ".zip" }),
      },
    ]);
    vi.stubGlobal("fetch", fetchMock);
    render(<FilePreviewModal path="arc.zip" onClose={() => {}} />);
    await waitFor(() => expect(screen.getByTestId("preview-unsupported")).toBeInTheDocument());
    expect(screen.getByText(/二进制容器/)).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("not_text 错误态如实展示", async () => {
    vi.stubGlobal("fetch", previewRouter([
      {
        match: (u) => u.includes("/api/v1/files/preview"),
        status: 415,
        body: () => ({ error: "not_text", detail: "" }),
      },
    ]));
    render(<FilePreviewModal path="blob.dat" onClose={() => {}} />);
    await waitFor(() =>
      expect(screen.getByText(/不是可预览的 UTF-8 文本/)).toBeInTheDocument()
    );
  });

  it("dir: 单层浏览并可进入子项", async () => {
    const fetchMock = previewRouter([
      {
        match: (u) => u.includes("path=sub&") || u.includes("path=sub?"),
        body: () => ({
          type: "dir", path: "sub", parent: ".",
          dirs: ["nested"], files: [{ name: "a.txt", size: 3 }],
        }),
      },
      {
        match: (u) => u.includes("path=sub%2Fnested") || u.includes("path=sub/nested"),
        body: () => ({
          type: "dir", path: "sub/nested", parent: "sub", dirs: [], files: [],
        }),
      },
    ]);
    vi.stubGlobal("fetch", fetchMock);
    render(<FilePreviewModal path="sub" onClose={() => {}} />);
    await waitFor(() => expect(screen.getByTestId("preview-dir")).toBeInTheDocument());
    fireEvent.click(screen.getByText("nested"));
    await waitFor(() =>
      expect(screen.getByText(/空目录/)).toBeInTheDocument()
    );
    expect(fetchMock.mock.calls.some((c) => String(c[0]).includes("path=sub%2Fnested"))).toBe(true);
  });

  it("reload: 重新拉取当前文件", async () => {
    const fetchMock = previewRouter([
      {
        match: (u) => u.includes("/api/v1/files/preview"),
        body: () => ({
          type: "text", path: "x.txt", size: 2, offset: 1, lines: 1,
          content: "v1", eof: true, truncated: false,
        }),
      },
    ]);
    vi.stubGlobal("fetch", fetchMock);
    render(<FilePreviewModal path="x.txt" onClose={() => {}} />);
    await waitFor(() => expect(screen.getByText("v1")).toBeInTheDocument());
    fireEvent.click(screen.getByTestId("preview-reload"));
    await waitFor(() => expect(fetchMock.mock.calls.length).toBe(2));
  });
});

describe("FileTree 点击对齐（点击=预览，✍=协作编辑）", () => {
  function treeResponse(): Response {
    return jsonResponse({
      path: "/ws",
      parent: null,
      dirs: [],
      files: [{ name: "a.txt", size: 5 }],
    });
  }

  it("点击文件行打开预览模态", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/api/v1/fs/tree")) return treeResponse();
      if (url.includes("/api/v1/files/preview")) {
        return jsonResponse({
          type: "text", path: "a.txt", size: 5, offset: 1, lines: 1,
          content: "hello", eof: true, truncated: false,
        });
      }
      return jsonResponse({}, 404);
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<FileTree sessionId="s1" />);
    await waitFor(() => expect(screen.getByText("a.txt")).toBeInTheDocument());
    fireEvent.click(screen.getByText("a.txt"));
    await waitFor(() => expect(screen.getByTestId("file-preview")).toBeInTheDocument());
    expect(screen.getByText("hello")).toBeInTheDocument();
  });

  it("✍ 按钮进入协作编辑（观察请求）", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/api/v1/fs/tree")) return treeResponse();
      if (url.includes("/files/observe")) {
        return jsonResponse({
          path: "a.txt", snapshot_ref: "ref-1", sha256: "abcdef1234567890",
          size_bytes: 5, observed_at: 1, content_range: { start: 0, end_exclusive: 5 },
          content: "hello", total_lines: 1, workspace_path_state: "in_sync",
          file_contract_version: 1,
        });
      }
      return jsonResponse({}, 404);
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<FileTree sessionId="s1" />);
    await waitFor(() => expect(screen.getByText("a.txt")).toBeInTheDocument());
    fireEvent.click(screen.getByTestId("collab-edit-btn"));
    await waitFor(() => expect(screen.getByTestId("human-file-editor")).toBeInTheDocument());
  });
});
