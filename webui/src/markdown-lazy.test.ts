import { describe, expect, it, vi } from "vitest";

describe("lazy KaTeX renderer", () => {
  it("keeps math literal before the optional chunk loads, then renders identically after load", async () => {
    vi.resetModules();
    const markdown = await import("./core/markdown");
    expect(markdown.isMathRendererReady()).toBe(false);
    expect(markdown.hasMathCandidate('运行 `echo "$PWD"`')).toBe(false);
    expect(markdown.hasMathCandidate("公式 $x^2$")).toBe(true);

    const before = document.createElement("div");
    before.innerHTML = markdown.renderMarkdown("公式 $x^2$");
    expect(before.querySelector(".katex")).toBeNull();
    expect(before.textContent).toContain("$x^2$");

    await markdown.ensureMathRenderer();
    expect(markdown.isMathRendererReady()).toBe(true);
    const after = document.createElement("div");
    after.innerHTML = markdown.renderMarkdown("公式 $x^2$");
    expect(after.querySelector(".katex")).not.toBeNull();
  });
});
