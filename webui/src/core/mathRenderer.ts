import katex from "katex";
import "katex/dist/katex.min.css";

/** Heavy optional renderer, isolated behind markdown.ts dynamic import. */
export function renderTrustedMath(expr: string, displayMode: boolean): string {
  return katex.renderToString(expr.trim(), {
    displayMode,
    throwOnError: true,
    trust: false,
  });
}
