import { describe, expect, it } from "vitest";
import { renderMarkdown } from "./core/markdown";
describe("code math isolation", () => {
  const command = 'echo "$PWD" "$HOME"';
  it.each([
    ["open fence", "```bash\n" + command],
    ["open tilde", "~~~bash\n" + command],
    ["longer closing fence", "```bash\n" + command + "\n````"],
    ["indented code", "    " + command],
    ["multiline span", "``echo \n$PWD $HOME``"],
  ])("preserves %s", (_name, source) => {
    const node = document.createElement("div");
    node.innerHTML = renderMarkdown(source);
    expect(node.textContent).not.toContain("katex");
    expect(node.querySelector(".katex")).toBeNull();
    expect(node.textContent).toContain("$PWD");
    expect(node.textContent).toContain("$HOME");
  });
  it("preserves copy bytes", () => {
    const node = document.createElement("div");
    node.innerHTML = renderMarkdown("```sh\n" + command);
    expect(node.querySelector("pre code")?.textContent).toBe(command);
  });
});

describe("math preprocessing must not mutate markdown syntax", () => {
  it("preserves dollar-bearing link destinations byte-for-byte", () => {
    const href = "https://example.test/download/$VERSION$/pkg?price=$5";
    const node = document.createElement("div");
    node.innerHTML = renderMarkdown(`[下载](${href})`);
    expect(node.querySelector("a")?.getAttribute("href")).toBe(href);
    expect(node.querySelector(".katex")).toBeNull();
  });

  it("honors escaped dollars while still rendering adjacent real math", () => {
    const node = document.createElement("div");
    node.innerHTML = renderMarkdown(String.raw`价格 \$5；环境变量写作 \$HOME；公式 $x^2$`);
    expect(node.textContent).toContain("价格 $5");
    expect(node.textContent).toContain("$HOME");
    expect(node.querySelectorAll(".katex")).toHaveLength(1);
  });

  it("keeps KaTeX layout metadata instead of stripping trusted renderer styles", () => {
    const node = document.createElement("div");
    node.innerHTML = renderMarkdown("公式 $x^2 + y_1$");
    const strut = node.querySelector(".katex-html .katex-strut");
    expect(strut).not.toBeNull();
    expect(strut?.getAttribute("style")).toMatch(/height:/);
    expect(node.querySelector(".katex-html")).toHaveAttribute("aria-hidden", "true");
  });

  it("malformed TeX fails open as literal source instead of injecting a KaTeX error tree", () => {
    const source = String.raw`坏公式 $\frac{1$ 仍应可复制`;
    const node = document.createElement("div");
    node.innerHTML = renderMarkdown(source);
    expect(node.textContent).toContain(String.raw`$\frac{1$`);
    expect(node.querySelector(".katex-error")).toBeNull();
  });

  it("trusted KaTeX restore keeps trust=false: dangerous URL commands never become active elements", () => {
    const node = document.createElement("div");
    node.innerHTML = renderMarkdown(String.raw`$\href{javascript:alert(1)}{x}$ $\includegraphics{javascript:alert(1)}$`);
    expect(node.querySelector('a[href^="javascript:"]')).toBeNull();
    expect(node.querySelector('img[src^="javascript:"]')).toBeNull();
  });
});
