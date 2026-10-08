# 事实核查：Claude Code v2.1.286–v2.1.292 周更汇总一文

- 核查日期：2026-10-09
- 被核查文章：《Claude Code本周更新汇总（v2.1.286-v2.1.292）》（头条，group_id 7693915449126060580）
- 总评：**核心事实全部属实，可信度高；发现 1 处表述合并错误、2 处轻微不精确。**

## 证据源

| 来源 | 引用 | 抓取时间 |
|---|---|---|
| 官方 CHANGELOG | raw.githubusercontent.com/anthropics/claude-code/main/CHANGELOG.md（本地副本 /tmp/cc_changelog.md） | 2026-10-09 01:13 |
| npm 发布时间 | registry.npmjs.org/@anthropic-ai/claude-code `time` 字段 | 2026-10-09 01:56 |
| 官方 Mods 文档 | docs.claude.com（overview / reference / create / events / admin / api / interface / troubleshoot / test / gallery，本地副本 /tmp/mods_docs/） | 2026-10-09 01:17–01:43 |
| 官方 mods d.ts | github.com/anthropics/claude-code/blob/main/mods/types/claude-code.d.ts（HTTP 200，507,444 字节） | 2026-10-09 01:58 |

## 一、总体数字：全部精确吻合

| 文章主张 | 官方事实 | 结论 |
|---|---|---|
| 国庆期间 7 个版本，v2.1.286–v2.1.292 | npm 时间戳：2.1.286=09-30 17:14Z（北京 10-01 01:14）…2.1.292=10-06 17:10Z（北京 10-07 01:10），共 7 个 | ✅ 按北京时间口径成立 |
| 594 条官方顶层变更 | CHANGELOG 7 个版本小节 `- ` 顶层条目合计 = **594**，逐条可数 | ✅ 精确 |

## 二、逐主题核对

### 1. Mods / 插件（文章主线）

| 文章主张 | 官方条目（逐字核对） | 结论 |
|---|---|---|
| v2.1.287 引入 Claude Mods，"插件可修改更深层行为" | `Added Claude Mods: plugins may now modify deeper behavior`（2.1.287） | ✅ |
| 同版内置 Mod "You should know"，侧边 Agent 提醒 | `Added You should know, a built-in mod where a side agent watches your back…`（2.1.287） | ✅ |
| v2.1.289 agent.spawn / $.agent.list() idle & waiting | `Added agent.spawn for teammates, one agent id across plugin hook events, and idle and waiting states in $.agent.list()`（2.1.289） | ✅ |
| v2.1.290 tool.check 可见 agentId + ceiling | `Added agentId to the tool.check event of plugin hooks…`；`Added ceiling to the question and verdict a mod's tool.check hook reads`（2.1.290） | ✅ |
| claude plugin validate 列 gatingHooks 与 .catch | `Added to claude plugin validate: each hook a mod registers at a gating site is listed with whether it has a .catch (gatingHooks under --json)`（2.1.290） | ✅ |
| v2.1.292 prompt.autocomplete | `Added prompt.autocomplete, an event a mod hooks to add its own rows to the prompt box's autocomplete list`（2.1.292） | ✅ |
| v2.1.292 Mod 模型调用 prompt 缓存 | `Added prompt caching to $.model.complete for mods: prompt and system take blocks of text, and cache: true on a block caches the request up to it`（2.1.292） | ✅ |
| v2.1.292 为 workflow agent 创建提供 hook | `Added workflow agents to the agent.spawn mod hook, with their run and index, so a mod can refuse them`（2.1.292） | ⚠️ 意思对、表述松：是把 workflow agents 纳入已有 agent.spawn hook（可拒绝），不是新增独立 hook |

### 2. 安全修复

| 文章主张 | 官方条目 | 结论 |
|---|---|---|
| v2.1.286 组织策略关闭后远程控制仍保持连接 | `Fixed Remote Control sessions…staying connected after your organization's policy turns Remote Control off` | ✅ |
| v2.1.286 多类秘密脱敏缺口 | 两条：日志/转录中密钥名含不可见字符；URL 密码含标点/`[::1]` 括号主机泄露 | ✅ |
| v2.1.287 MCP 特殊工具名让每工具上限静默失效 | `Fixed organization per-tool permission ceilings being silently dropped for an MCP tool named __proto__` | ✅ |
| v2.1.288 hook 匹配失败/输入无法序列化时改为阻断 | `Fixed PreToolUse and PermissionRequest hooks being skipped when matching them failed or the tool's input could not be serialized to JSON; the call is now blocked` | ✅ |
| v2.1.288 危险 rm 藏在嵌套 shell（bash -c/sh -c）绕过提示 | `Fixed a dangerous rm…inside a bash -c or sh -c script running without a prompt in bypassPermissions mode or under a shell allow rule (anthropics/claude-code#…)` | ✅ |
| v2.1.289 复合 shell / 环境变量前缀 deny/ask 失效 | 三条：复合命令嵌套部分、环境变量前缀展开值（`TZ="$HOME" rm -rf build`）、裸变量赋值 | ✅ |
| v2.1.290 符号链接越过 Read 限制 | `Fixed a project CLAUDE.md, rule or AGENTS.md symlinked outside the working directories loading under permissions.blockReadsOutsideWorkingDirectories or a Read deny rule`（另有 2.1.289 的 @-提及/IDE 符号链接 Read deny 条目） | ✅ |
| v2.1.290 用户 Mod 让组织 guard 跳过检查 | `Fixed a case where a user-installed mod could make an organization's guard skip its check; such a mod is now unloaded` | ✅ |
| v2.1.292 server-managed settings 缓存被篡改 | `Security: Fixed a server-managed settings block being added to the cache and later read as if you had applied it when you only viewed it` | ✅ |
| v2.1.292 UNC 网络路径读取 | `Security: Fixed PreToolUse hook approvals and auto mode bypassing the permission prompt for file reads from network (UNC) paths` | ✅ |
| v2.1.292 读文件时链接被替换 | `Fixed a notebook or PDF read on macOS and Windows being able to return a file outside what was approved, through a link swapped in mid-read`（image 变体已在 2.1.290 修） | ✅ |
| v2.1.292 plugin worker 重启漏权限 hooks | `Fixed permission hooks not running at plugin worker startup` | ✅ |
| "官方 release notes 没有 CVE、严重等级或受影响规模" | 逐条检查：仅个别条目标 `Security:` 前缀，无 CVE 编号、无等级、无规模 | ✅ 文章的克制表述成立 |

### 3. 后台 Agent / 恢复

| 文章主张 | 官方条目 | 结论 |
|---|---|---|
| v2.1.286 Workflow subagent 从原始提示重启 | `Fixed Workflow tool subagents being restarted from their original prompt when a connection stalled for a few minutes mid-response` | ✅ |
| v2.1.286 后台任务等待审批却显示完成 | `Fixed background jobs showing done while waiting for your approval` | ✅ |
| v2.1.288 resume 丢文件/丢最后回复/读截断 transcript | 三条逐字对应 | ✅ |
| v2.1.288 无头会话与 subagent 中途超时后从部分响应继续 | `Fixed mid-response API timeouts failing the turn: non-interactive sessions and subagents now continue from the partial response` | ✅ |
| v2.1.290 scheduled task 在 compact+resume 后消失 | `Fixed scheduled tasks (/loop with an interval, reminders) silently not coming back on resume once the conversation was compacted` | ✅ |
| v2.1.290 前台转后台不触发/重复触发 | `Fixed scheduled tasks set in the foreground never firing after a ← or /background hand-off, and recurring ones firing an extra run on every resume, respawn or fork` | ✅ |
| v2.1.290 等待 /loop 唤醒的会话跨更新与低内存保持运行 | `Changed background sessions waiting on a scheduled wakeup (/loop): they are now left running through updates and low memory…` | ✅ |
| v2.1.292 一次性 claude -p 与 Agent SDK 过早终止后台命令 | `Fixed one-shot claude -p runs and the Agent SDK stopping a background command 5 seconds after the final result` | ✅ |
| v2.1.292 后台 /loop 进程重启后停止 | `Fixed a background session's /loop silently stopping when the session's process restarted…because its pending wakeup was lost` | ✅ |
| v2.1.292 云端知道哪些 stopped agents 可按 id 恢复 | `Improved cloud sessions after a restart: Claude is now told which stopped background agents it can resume by id` | ✅ |
| v2.1.291 回归热修两条 | `Fixed a regression in 2.1.290 where cloud sessions could drop answers to permission prompts`；`Fixed a regression in 2.1.288 where the last messages of a session could be lost when quitting` | ✅ |
| v2.1.292 Agent tool 新参数 effort | `Added effort to the Agent tool…` | ✅ |

### 4. MCP 协议

| 文章主张 | 官方条目 | 结论 |
|---|---|---|
| v2.1.287 支持 MCP 2025-11-25 URL prompts | `Added URL prompts from MCP servers on the 2025-11-25 protocol, for example to sign in…` | ✅ |
| v2.1.288 更高 OAuth scope 重新认证提示 | `Added a re-authenticate prompt when an MCP server asks for more OAuth scope during a tool call` | ✅ |
| v2.1.292 stdio MCP 默认协商 2026-07-28 + legacy 退出 | `Changed local (stdio) MCP server connections to negotiate protocol version 2026-07-28 by default on every install…MCP_PROTOCOL_NEGOTIATION=legacy opts out`；慢连接旧服务器被记住 7 天走旧方式 | ✅ |
| 连接器协议变化导致重复调用 | `Fixed an MCP connector tool call occasionally running twice…when its server changed which MCP protocol version it supports`（2.1.287） | ✅ |
| 工具名过长让请求整体失败 | `Fixed an MCP tool with a name longer than 128 characters making every request fail; that tool is now left out and an MCP error names it`（2.1.292） | ✅ |
| 代理环境 NO_PROXY 未生效 | `Fixed NO_PROXY being ignored for Claude Code's own API requests…when HTTPS_PROXY is set`（2.1.292） | ✅ |
| **"超大结果触发重复调用"** | **无此条目**。相近的两条是：①2.1.287 连接器协议变化→tool call 偶尔运行两次；②2.1.290 HTTP MCP server 超大响应→无上限内存占用。疑似把两条并成一条 | ❌ 表述错误 |

## 三、关键佐证："官方没给 Mods 稳定承诺"——成立且比文章说的更明确

文章判断："官方没有给出 Mods API 的完整边界、稳定周期或兼容承诺。"

官方源码直接背书这一点。mods 官方类型声明文件（`mods/types/claude-code.d.ts`，由文档 reference 页明确指定为"完整参考"）文件头原文：

```text
// Written by Claude Code 2.1.277.
// Claude Code function hooks: the plugin API's TypeScript declarations.
//
// EARLY ACCESS: this surface may change between releases without notice.
// Written by `/plugin-types`; regenerate with that command after an update
// rather than editing. The first line names the Claude Code version that
// wrote it. ...
```

配套事实（官方 Mods 文档，docs.claude.com）：

- `CLAUDE_CODE_ENABLE_FUNCTION_HOOKS` 自 **v2.1.287 起被完全忽略**（设 `0` 也不会关掉 mods；官方改用内置 guard 的设置项管理）。治理上"想用环境变量一键关闭"这条路已封死，需要走 managed settings 的内置 guard 选项。
- "A mod runs with your permissions"（overview）：Mod 以用户全权运行，装前需审查。
- 组织策略优先：用户装的 Mod 若使组织 guard 跳过检查，2.1.290 起直接卸载该 Mod。

## 四、发现的问题汇总

1. **"超大结果触发重复调用"（MCP 小节）**：官方 changelog 无此条目，系两条不同条目（协议变化→重复调用；超大响应→内存）的合并，属表述错误。
2. **"为 workflow agent 的创建提供了 hook"**：官方是把 workflow agents 纳入已有 `agent.spawn` mod hook（可拒绝），非新增独立 hook，表述略松。
3. **"国庆期间发布"**：v2.1.286 的 npm 发布时间是 2026-09-30 17:14 UTC（北京时间 10-01 01:14）。按北京时间口径成立，严格 UTC 口径首个版本在 9 月 30 日。属口径问题，不算错。

## 五、结论

- 文章对官方 changelog 的转述**逐条可溯源、无虚构**，594 条总数精确，版本归属准确率极高（抽查 30+ 条仅 1 处合并错误）。
- 其克制判断（无 CVE/等级不能推出"沙箱已安全"；恢复修复≠exactly-once；EARLY ACCESS 无稳定承诺）**与官方文档和源码一致**，且 EARLY ACCESS 声明比文章表述更直接。
- 采用建议合理：生产验收至少 v2.1.291（回归热修），窗口内更合理目标 v2.1.292；依赖 Mods API 的集成应按"版本间可破坏变更"设计（d.ts 头部明示），并随每次升级用 `/plugin-types` 重新生成声明。
