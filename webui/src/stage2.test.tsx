// 阶段 2：markdown/高亮/消息/输入区 单元与冒烟测试

import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { render, screen, fireEvent, cleanup, waitFor, within } from "@testing-library/react";
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

  it("出产物内联路径：正文中的文件路径 code 变为可点击链接", () => {
    const html = renderMarkdown(
      "已修改 `src/llm_loop/core/a.py` 与 `src/llm_loop/core/b.py`",
      new Set(["src/llm_loop/core/a.py"])
    );
    // 集合命中的路径 → v2-file-link（可点击打开）
    expect(html).toContain('class="v2-file-link" data-path="src/llm_loop/core/a.py"');
    // 未命中集合但路径样式 → 也可点（点击时后端校验存在性）
    expect(html).toContain('class="v2-file-link" data-path="src/llm_loop/core/b.py"');
  });

  it("出产物内联路径：无 clickablePaths 时路径样式 code 也可点，命令/普通词排除", () => {
    // 路径样式（含 / 或以已知扩展名结尾）→ 可点
    const html = renderMarkdown("修改了 `docs/development_methodology.md` 与 `src/a.py`");
    expect(html).toContain('class="v2-file-link" data-path="docs/development_methodology.md"');
    expect(html).toContain('class="v2-file-link" data-path="src/a.py"');
    // 命令（含空格）/ 普通词 → 保持普通 code
    const html2 = renderMarkdown("执行 `bash llm_loop evolve-review` 与 `hello` 与 `max_tokens`");
    expect(html2).not.toContain("v2-file-link");
    expect(html2).toContain("<code>bash llm_loop evolve-review</code>");
    expect(html2).toContain("<code>hello</code>");
    // URL 排除（marked 渲染为链接，不在 code 内）
    const html3 = renderMarkdown("看 `https://example.com/a.md`");
    expect(html3).not.toContain('class="v2-file-link" data-path="https://example.com/a.md"');
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

  it("用户/助手消息均有一键复制按钮", () => {
    render(<MessageItem msg={{ role: "user", content: "用户内容" }} />);
    expect(screen.getByTestId("copy-btn")).toBeInTheDocument();
    cleanup();
    render(<MessageItem msg={{ role: "assistant", content: "助手内容" }} />);
    expect(screen.getByTestId("copy-btn")).toBeInTheDocument();
  });

  it("点击复制 → 写入剪贴板 + 显示已复制（1s 恢复）", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    vi.stubGlobal("navigator", { ...navigator, clipboard: { writeText } });
    render(<MessageItem msg={{ role: "assistant", content: "待复制内容" }} />);
    fireEvent.click(screen.getByTestId("copy-btn"));
    expect(writeText).toHaveBeenCalledWith("待复制内容");
    await waitFor(() => expect(screen.getByText("已复制")).toBeInTheDocument());
    vi.useFakeTimers();
    // 触发 1s 定时器恢复（copied 状态由 setTimeout 复位）
    // 先等待写入 promise 微任务落地再推进
    vi.advanceTimersByTime(1000);
    vi.useRealTimers();
    await waitFor(() => expect(screen.getByText("复制")).toBeInTheDocument());
    vi.unstubAllGlobals();
  });

  it("助手消息：模型 + token 消耗页脚（M51/M52，k 单位格式化）", () => {
    render(
      <MessageItem
        msg={{ role: "assistant", content: "回答", model_used: "kimi/k3", tokens_in: 12345, tokens_out: 678 }}
      />
    );
    const footer = screen.getByTestId("msg-footer");
    expect(footer.textContent).toContain("—— kimi/k3");
    expect(footer.textContent).toContain("12.3k入");
    expect(footer.textContent).toContain("678出");
  });

  it("助手消息：无模型/token 时不渲染页脚", () => {
    render(<MessageItem msg={{ role: "assistant", content: "回答" }} />);
    expect(screen.queryByTestId("msg-footer")).not.toBeInTheDocument();
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

  it("出产物：edit_file 工具调用 → 文件 chips 即时可见", () => {
    render(
      <MessageItem
        msg={{
          role: "assistant",
          content: "",
          toolCalls: [
            { id: "c1", name: "edit_file", arguments: { path: "src/llm_loop/core/a.py" } },
            { id: "c2", name: "edit_file", arguments: { path: "src/llm_loop/core/a.py" } }, // 去重
            { id: "c3", name: "read_file", arguments: { path: "README.md" } }, // 非产出工具
          ],
        }}
      />
    );
    expect(screen.getByTestId("produced-files")).toBeInTheDocument();
    expect(screen.getByText("src/llm_loop/core/a.py")).toBeInTheDocument();
    expect(screen.queryByText("README.md")).not.toBeInTheDocument();
  });

  it("出产物：点击 chip → 打开文件预览（fetch 内容 + 模态显示）", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        new Response(JSON.stringify({ path: "src/a.py", size: 8, truncated: false, content: "print(1)" }), {
          status: 200,
        })
      )
    );
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
    await waitFor(() => expect(screen.getByTestId("file-preview")).toBeInTheDocument());
    expect(screen.getByText("print(1)")).toBeInTheDocument();
    vi.unstubAllGlobals();
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

  it("粘贴大内容发送后输入框高度复位（不再残留增高）", async () => {
    // chat/stream 返回 done（sendMessage 完整链路）
    vi.mocked(fetch).mockImplementation(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/api/v1/chat/stream")) {
        return new Response(
          "data: {\"type\":\"done\",\"data\":{\"final_answer\":\"ok\"}}\n\n",
          { status: 200 }
        );
      }
      return new Response(JSON.stringify({ models: [] }), { status: 200 });
    });
    render(<Composer />);
    const ta = screen.getByTestId("composer-input") as HTMLTextAreaElement;
    // 模拟粘贴大内容 → autoGrow 增高
    fireEvent.change(ta, { target: { value: "长内容\n".repeat(30) } });
    // 发送后高度应复位（空内容 → 内联高度清除，恢复 CSS 默认）
    fireEvent.click(screen.getByText("发送"));
    await waitFor(() => {
      expect((ta as HTMLTextAreaElement).style.height).toBe("");
    });
    expect((ta as HTMLTextAreaElement).value).toBe("");
  });

  it("/ 唤起命令面板", () => {
    render(<Composer />);
    const ta = screen.getByTestId("composer-input");
    fireEvent.change(ta, { target: { value: "/" } });
    expect(screen.getByTestId("cmd-popup")).toBeInTheDocument();
    expect(screen.getByText("/new")).toBeInTheDocument();
  });

  it("/model 目录选项可点击：点选即切换模型 + 反馈", async () => {
    // 真实契约：models 为字符串数组
    vi.mocked(fetch).mockImplementation(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/api/v1/models")) {
        return new Response(
          JSON.stringify({ models: ["deepseek/deepseek-v4-flash", "kimi/k3"], current: null }),
          { status: 200 }
        );
      }
      return new Response(JSON.stringify({}), { status: 200 });
    });
    const { sessionStore } = await import("./core/stores");
    render(<Composer />);
    const ta = screen.getByTestId("composer-input");
    fireEvent.change(ta, { target: { value: "/model" } });
    const popup = () => screen.getByTestId("cmd-popup");
    await waitFor(
      () => expect(within(popup()).getByText("deepseek/deepseek-v4-flash")).toBeInTheDocument(),
      { timeout: 3000 }
    );
    fireEvent.click(within(popup()).getByText("deepseek/deepseek-v4-flash"));
    expect(sessionStore.getState().model).toBe("deepseek/deepseek-v4-flash");
    expect(screen.getByTestId("composer-hint").textContent).toContain("已选择模型");
  });

  it("模型下拉：选择后 store 更新且 select 值保持（响应式不回弹）", async () => {
    vi.mocked(fetch).mockImplementation(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/api/v1/models")) {
        return new Response(
          JSON.stringify({ models: ["deepseek/deepseek-v4-flash", "kimi/k3"], current: null }),
          { status: 200 }
        );
      }
      return new Response(JSON.stringify({}), { status: 200 });
    });
    const { sessionStore } = await import("./core/stores");
    sessionStore.setModel(null);
    render(<Composer />);
    const select = (await screen.findByTestId("model-select")) as HTMLSelectElement;
    await waitFor(() => expect(select.options.length).toBeGreaterThan(1)); // 模型选项加载
    fireEvent.change(select, { target: { value: "kimi/k3" } });
    expect(sessionStore.getState().model).toBe("kimi/k3");
    // 响应式：select 受控值跟随 store（再渲染不回弹）
    expect(select.value).toBe("kimi/k3");
  });

  it("命令行点击直接执行（/new 无选项）", () => {
    render(<Composer />);
    const ta = screen.getByTestId("composer-input");
    fireEvent.change(ta, { target: { value: "/new" } });
    const popup = screen.getByTestId("cmd-popup");
    expect(popup).toBeInTheDocument();
    fireEvent.click(within(popup).getByText("/new"));
    expect((ta as HTMLTextAreaElement).value).toBe("");
  });
});
