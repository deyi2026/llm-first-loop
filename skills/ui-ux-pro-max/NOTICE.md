# NOTICE — ui-ux-pro-max

本目录是第三方内容的 vendored 副本，版权归原作者所有。

- 上游项目：nextlevelbuilder/ui-ux-pro-max-skill（https://github.com/nextlevelbuilder/ui-ux-pro-max-skill）
- 上游路径：`.claude/skills/ui-ux-pro-max`
- 固定版本：`9a3f14f7423037ccb8feeb4fee7482291b9c820e`（2026-10-31 取得）
- 许可：MIT，完整条款见 `LICENSE`（逐字复制自上游仓库根 LICENSE）

## 本地修改

1. `SKILL.md` frontmatter 的 `description` 由英文改写为中文并补充触发词；其中数据条数与上游 `data/catalog-summary.json` 逐项核对一致（79/50 styles、192 palettes、74 font pairings、119 UX guidelines、105 icons、17 motion presets、25 chart types、22 stacks）。
2. 新增 `license: MIT` 与 `metadata.vendored-from` 字段。
3. 正文开头插入一段 “LFL 本地化说明” 引用块。
4. 全文 11 处命令由 `python "${CLAUDE_PLUGIN_ROOT}/.claude/skills/ui-ux-pro-max/scripts/search.py"` 改写为 `python3 skills/ui-ux-pro-max/scripts/search.py`（本机无 `python` 可执行文件，也没有 `CLAUDE_PLUGIN_ROOT` 变量）。
5. “Running the search tool” 段落与本地化说明补充了实际路径与执行方式：命令使用仓库相对路径 `skills/ui-ux-pro-max/scripts/search.py`，并要求按 skill_load 回执中的 `runtime_root` 拼出绝对路径调用（运行时 cwd 可能是 release 目录，不是仓库根）。
6. `data/stacks/javafx.csv` 中 “Code Bad” 示例里的本地路径占位（形如 `/Users/<用户名>/Desktop/logo.png`）改为 `/Users/<user>/Desktop/logo.png`：本仓 pre-commit 安全扫描（`scripts/git_security_scan.sh` 规则 3 与规则 5）会拦截任何 `/Users/<用户名>/` 形态。示例语义不变，仅去掉机器名形态。该文件不在上游 `data/catalog-summary.json` 的哈希快照内（该快照只覆盖 `google-fonts.csv`、`google-font-licenses.json`、`icons.csv`、`phosphor-icons-upstream.json`），因此不影响 `scripts/validate_data.py` 的一致性校验。

除上述改动外，`scripts/`、`data/`、`references/` 下的文件均逐字复制自上游，未作修改。

## 裁剪（运行时不需要）

- `scripts/tests/`：绑定上游仓库布局（依赖仓库根的 `scripts/generate-catalog-summary.py`），随本仓不运行。
- 上游 CLI 源码与 `uipro init` 生成物：文件已直接 vendored 到本目录，无需 npm 安装即可运行。

## 数据来源

`data/data-provenance.json` 记录每条数据的来源与核验日期；`data/catalog-summary.json` 记录目录快照与 sha256（上游 `verifiedAt` 为 2026-08-26）。数据随上游仓库分发，许可同上。
