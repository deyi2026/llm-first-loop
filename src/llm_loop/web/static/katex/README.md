# KaTeX 本地分发资源

- 版本：0.16.47
- 许可证：MIT（见同目录 LICENSE）
- 来源：`~/.hermes/hermes-agent/node_modules/katex/dist/`（本机 npm 副本，零联网下载）
- 分发说明：
  - `katex.min.js` / `katex.min.css`：KaTeX 渲染引擎（按需动态加载，不随首屏加载）
  - `fonts/*.woff2`：20 个字体文件（`katex.min.css` 的 `@font-face` woff2 居首，命中后不再请求其他格式）
  - 不复制 ttf/woff，仅 woff2
- 用途：Web 端 LaTeX 数学公式渲染（P4-3），资源经 `/static/` 本地分发，不依赖外部 CDN

更多信息见 KaTeX 官方仓库：https://github.com/KaTeX/KaTeX