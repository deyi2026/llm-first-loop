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
