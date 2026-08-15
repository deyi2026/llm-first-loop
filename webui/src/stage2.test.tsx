// 阶段 2：markdown/高亮/消息/输入区 单元与冒烟测试

import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { render, screen, fireEvent, cleanup } from "@testing-library/react";
import { renderMarkdown, highlightCode } from "./core/markdown";
import { MessageItem } from "./components/conversation/MessageItem";
import { Composer } from "./components/conversation/Composer";

describe("renderMarkdown", () => {
  it("GFM 基础渲染", () => {
    const html = renderMarkdown("# 标题\n\n**加粗** 与 `code`");
    expect(html).toContain("<h1>标题</h1>");
    expect(html).toContain("<strong>加粗</strong>");
    expect(html).toContain("<code>code</code>");
  });

  it("数学 KaTeX 渲染（块级/行内）", () => {
    const html = renderMarkdown("行内 $x^2$ 与块级 $$E=mc^2$$");
    expect(html).toContain("katex");
  });

  it("XSS 脚本被剥离（白名单 sanitize）", () => {
    const html = renderMarkdown('<script>alert(1)</script>正文');
    expect(html).not.toContain("<script>");
    expect(html).toContain("正文");
  });
});

describe("highlightCode", () => {
  it("关键字/字符串/注释/数字分色", () => {
    const html = highlightCode('def f(x):\n    # 注释\n    return "s" + 1');
    expect(html).toContain("shiki-keyword");
    expect(html).toContain("shiki-string");
    expect(html).toContain("shiki-comment");
    expect(html).toContain("shiki-number");
  });

  it("特殊字符转义（防 XSS）", () => {
    const html = highlightCode("<script>alert(1)</script>");
    expect(html).not.toContain("<script>");
    expect(html).toContain("&lt;script&gt;");
  });
});

describe("MessageItem", () => {
  it("用户消息气泡", () => {
    render(<MessageItem msg={{ role: "user", content: "你好" }} />);
    expect(screen.getByTestId("msg-user")).toBeInTheDocument();
    expect(screen.getByText("你好")).toBeInTheDocument();
  });

  it("助手消息：正文 + 思考块默认折叠", () => {
    render(
      <MessageItem
        msg={{ role: "assistant", content: "回答内容", reasoningContent: "推理过程" }}
      />
    );
    expect(screen.getByText("回答内容")).toBeInTheDocument();
    expect(screen.getByTestId("think-block")).toBeInTheDocument();
    expect(screen.getByText("💭 思考过程（4 字）▸")).toBeInTheDocument();
    fireEvent.click(screen.getByTestId("think-block").querySelector("button")!);
    expect(screen.getByText("推理过程")).toBeInTheDocument();
  });

  it("工具链折叠 + 工具参数展开", () => {
    render(
      <MessageItem
        msg={{
          role: "assistant",
          content: "",
          toolCalls: [{ id: "c1", name: "read_file", arguments: { path: "/tmp/a" } }],
        }}
      />
    );
    expect(screen.getByTestId("tool-chain")).toBeInTheDocument();
    fireEvent.click(screen.getByTestId("tool-chain").querySelector("button")!);
    expect(screen.getByText("read_file")).toBeInTheDocument();
  });
});

describe("Composer", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn(async () => {
      return new Response(JSON.stringify({ models: [] }), { status: 200 });
    }));
  });
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it("发送按钮随文本启用/禁用", () => {
    render(<Composer />);
    const send = screen.getByText("发送") as HTMLButtonElement;
    expect(send.disabled).toBe(true);
    fireEvent.change(screen.getByTestId("composer-input"), { target: { value: "hi" } });
    expect(send.disabled).toBe(false);
  });

  it("/ 唤起命令面板", () => {
    render(<Composer />);
    const ta = screen.getByTestId("composer-input");
    fireEvent.change(ta, { target: { value: "/" } });
    expect(screen.getByTestId("cmd-popup")).toBeInTheDocument();
    expect(screen.getByText("/new")).toBeInTheDocument();
  });
});
