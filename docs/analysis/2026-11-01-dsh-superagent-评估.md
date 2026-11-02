# dsh-superagent（DeepSeek Super-agent 原型）评估：对本仓的影响与接入可行性

- 日期：2026-11-01（Asia/Shanghai）
- 状态：分析建议（ANALYSIS_ONLY）；本文不表示任何方案已实现、已授权或已部署。
- 触发材料：今日头条《刚刚，DeepSeek 开源新 Agent 架构：可接 Github 和飞书，研究让 AI 自己接活》（InfoQ 整理，作者冬梅）→ https://m.toutiao.com/article/7702923173360173587/
- 一手源：`github.com/deepseek-ai/dsh-superagent-prototype`（README + docs/000~008 + package.json + cordis.patch.yml + src/index.ts）、GitHub REST API、npm registry、本机 DSH 安装与本仓代码。
- 证据口径：**已核**＝本轮工具直接取到的事实；**推断**＝我的分析，非事实；**未核**＝本轮未验证。

---

## 0. 结论摘要

1. **文章的技术主张与上游一手源基本一致，但漏抄了 6 条关键限定语**（README 自称"非官方产品 / 研究原型 / 与设计文章描述的实现不同 / 文章中的部分设计未实现"；npm 未发布只能源码构建；前置依赖清单；必须独立 DSH profile 且会改进程级 PATH 与 git 配置；面向单个 github.com 仓库）。详见 §2。
2. **直接接入的可行性：中等偏低，且与本仓主线弱相关**——本仓没有 github.com 上可被 Super-agent 观察的目标仓（主 remote 是 gitee），且 cordis peer 版本钉死与本机 profile 现状冲突（§4 路径 A）。
3. **但它的概念设计暴露了本仓 4 个真实缺口**，其中 3 个在本仓已有文档中被明确记为"局限/不做"（`docs/local/DSH-ORCHESTRATION-PLAN-20260816.md` §5.3 上下文不共享、§7.2 双轨、§7.3 进程冷启动）。**推荐路径 B：借设计，不装代码**（§4 路径 B、§6）。
4. **安全姿态：上游比本仓宽。**上游原文："Executor Sessions run commands without approval as the operator's OS user" / "These wrappers and directories establish defaults, not a security boundary."（已核，docs/003-execution.md:27,80）。本仓破坏性工具走 approval + exec_mode 分级（已核，`src/llm_loop/tools/registry.py:613-615`）。若在本机装 Super-agent，等于在本机额外开一个"OS 用户身份、无需审批"的执行面。

---

## 1. 上游一手事实（已核）

| 项 | 值 | 核验方式 |
|---|---|---|
| 仓库 | `deepseek-ai/dsh-superagent-prototype` | GitHub API |
| 许可证 | MIT（package.json `license: MIT`；API `spdx_id: MIT`） | package.json + API |
| 创建 / 最后推送 | `2026-10-31T09:32:46Z` / `2026-10-31T12:05:51Z` | API |
| 热度（2026-11-01 07:2x CST 采样） | 2123 star / 180 fork / 0 open issue | API |
| 形态 | **DSH bundle layer**：`package.json.dsh.bundle.patch = ./cordis.patch.yml`，`private: true`，`version 0.1.0` | package.json |
| 分发 | **npm 未发布**：`dsh-superagent` 与 `@deepseek-ai/dsh-superagent` registry 均 HTTP 404 → 必须 `git clone` + `pnpm install && pnpm build` + `dsh plugin --profile <p> add "link:$PWD"` | registry 实测 + docs/006 |
| 引擎约束 | `node ^22.19.0 \|\| >=24.0.0`、`dsh ^0.2.1-alpha.2`、`packageManager pnpm@11.7.0` | package.json |
| peer 依赖 | 21 个：`@deepseek-ai/cordis` **精确钉 `4.0.5-alpha.1`**；其余 dsh-* 均 `^0.2.1-alpha.2` | package.json |
| 前置（部署文档） | Node 22.19+/24+、pnpm、git 2.32+、Python 3.8+、tmux、GitHub CLI 2.48+、一个 github.com 仓库（**GHE Server 不支持**） | docs/006-deployment.md |
| 安装形态 | 需要**独立** DSH profile（示例名 `superagent`），由 Web 模板派生；上游原文："the plugin changes process-wide `PATH` and git settings, and its process needs independent restarts and upgrades" | docs/006 |
| 面板 | DeepSeek Harness Web 侧栏 Superagent 入口，127.0.0.1，独立端口（由 profile 的 `webserver` 条目设置） | docs/005 + docs/006 |

核心机制（均已核自 docs/000~003）：

- **Mandate**：一次接纳授予的"强度 / 范围 / 所依据的 Policy 版本"；每个 Ticket 记录被匹配的规则名（002:109、002:100-105）。
- **准入三分**：`off` / `observe`（**默认**；评估后只记录 "would accept" 而不启动）/ `auto`（002:95-99）。
- **权限不可被内容改写**："Messages, comments and quoted documents are inputs to a decision; they cannot change those permissions."（002:5）
- **执行**：前台命令 >5s 转后台（worker preset）；**每轮结束后后台工作最多 30 分钟**，到限杀 shell job 并把 Ticket 报为 waiting，子 agent 可继续（003:27,35）。
- **并发**：为"人的消息或状态查询"多留 1 个执行槽（003:59）。
- **Ticket 生命周期**独立于 Executor Session；Ticket↔Thread 订阅（001）。

---

## 2. 文章 ↔ 上游：一致 / 漏抄 / 需限定

### 2.1 文章说对的（已核）

- "10 月 31 日公开设计探索并同步开放研究原型代码" → 创建日 10-31 ✅
- "MIT 许可证 / 在 DeepSeek AI 官方 GitHub 组织下" ✅
- "分层架构：主 Session 接收事件并判断是否启动，Executor Session 独立执行" ✅（001/007）
- "Source 维护事件读取位置并归入 Thread" ✅（001）
- "Eval → Ticket + Mandate → Assignment → Executor" ✅（001）
- "Ticket 与 Executor Session 分离、订阅关系使工作可延续" ✅（001）
- "30 分钟后台上限 / 人工消息预留额外执行槽" ✅（003:35,59）
- "Executor 以部署者 OS 用户身份运行命令，工作目录与命令限制不等于完整隔离" ✅（003:27,80）——**这条限定语文章抄到了，属于少见的诚实转述**
- "off/observe/auto 三模式，默认 observe" ✅（002:95-99）
- "聊天/评论/引用文档只能作为判断输入" ✅（002:5）

### 2.2 文章漏掉、且改变结论的限定语（已核）

1. **README 自述定位**："Research prototype for reference only, **not an official DeepSeek product**… Treat it as research code, not production-ready software."（README:3）
2. **原型 ≠ 设计文章所述实现**："We have adapted it for publication, so it is **not identical** to our internal version **or the implementation described in *Exploring Super-agent Design***. Some designs discussed in the article are **directions for future development and are not implemented in this prototype**."（README:5）→ 文章用"从公开原型来看"叙述设计文章里的机制，二者并不等价。
3. **未发布 npm**：`private: true` + registry 404 → 不能 `npm i` 用，只能源码构建后 link 安装。
4. **前置条件清单**（Node/pnpm/git/python/tmux/gh + github.com 仓）文章完全没提。
5. **必须独立 profile + 改进程级 PATH 与 git 配置**（006）——文章没提。
6. **只面向一个 github.com 仓库**（README："A proactive coding agent for one GitHub repository"）——文章说"可接 GitHub 和飞书"但没给出这个作用域限制。

### 2.3 文章表述与上游的细微偏差

| 文章表述 | 上游原文 | 判定 |
|---|---|---|
| "常规后台工作…最多继续 30 分钟，达到限制后会终止相应 Shell 任务并记录状态；子 Agent 则有单独的生命周期处理规则" | 到限杀 shell job、Ticket 报 waiting；**"Subagents are allowed to continue"**（是"允许继续"，不是"单独规则"） | 方向对，措辞虚化 |
| Ticket 状态"等待执行、正在工作、等待外部事件、等待人工回答、等待审查、受阻或失败" | 上游 stage 集合更细：`person/delivery`、`person/answer`、`person/review`、`person/blocked`、`person/failed`、`working/queued`、`idle(Waiting for a Trigger)`、`working` | 近似，且把 idle 误称为"等待外部事件" |
| "模型可以负责判断某个任务应该如何处理，却不能仅凭自己的判断扩大权限" | Mandate 记录 Policy 版本 + 匹配规则；但**模型是 Assessment 的主体**（002:100-105），"判断权"本身仍归模型 | 语义有被读者高估的空间 |

---

## 3. 本机与本仓现状（已核）

### 3.1 本机 DSH 环境

| 项 | 值 | 判定 |
|---|---|---|
| dsh 版本 | `0.2.1-rc.2`，装在 `~/.local/dsh`（**不在** npm global） | `dsh --version` + `npm ls -g` |
| semver 判定 | `0.2.1-rc.2` satisfies `^0.2.1-alpha.2` = **true** → 满足 bundle 的 `engines.dsh` 与全部 `^0.2.1-alpha.2` peer | npm 自带 semver 实测 |
| 但上游安装说明钉 | `npm install -g @deepseek-ai/dsh@0.2.1-rc.3` | docs/006 → 与 rc.2 差一版，**软闸门** |
| cordis（本机 profile） | `4.0.5`；bundle peer 精确钉 `4.0.5-alpha.1` → **不满足**（实测 `satisfies('4.0.5','4.0.5-alpha.1')`=false；registry 两者都有） | 风险点，见 §4-A |
| 缺失 peer | `@deepseek-ai/dsh-client-ui-slots` 本机 profile node_modules **无**（registry 有 `0.2.1-alpha.2`） | 需装 |
| profile 目录 | `data/dsh-home/profiles/{web,headless}` 与 `~/.dsh/profiles/{desktop,feishu,headless}`；**无 superagent** | `ls` |
| DSH_HOME | 本仓 `dsh_task` 走项目内 `data/dsh-home`（`dsh_task.py:62-85`）；Super-agent 默认装 `~/.dsh` → **天然隔离** | 代码 + docs/006 |
| 工具链 | node v24.18.0 ✅、pnpm 12.11.2（上游钉 11.7.0，corepack 可能拦）、git 2.50.1 ✅、tmux 3.7b ✅、Python 3.14.6 ✅、gh 2.98.0 ✅ 已登录 `deyi2026`（scope 含 repo）✅、**lark-cli 缺失** → Feishu 源不可用（上游默认亦 disabled） | 实测 |
| CLI 能力 | rc.2 支持 `dsh <profile> --from-default-profile web --dump-config`（usage：`dsh [--profile] <name>`，positional 即 profile 名）与 `dsh plugin --profile <p> <pnpm-args>` → **上游安装命令的语法在 rc.2 上成立** | `dsh --help` |

### 3.2 本仓已有机制（已核，grep 零命中项也标出）

| Super-agent 概念 | 本仓对应物 | 证据 |
|---|---|---|
| Mandate（授权依据+范围+策略版本） | `TaskBudgetGrant`：`authority_source` / `workspace_scope` / `policy_version` / `deadline_epoch_s`，ed25519 签发（`operator-ed25519-v1`、`operator-event-ed25519-v3`） | `src/llm_loop/resources/task_budget_contracts.py:166-173`；`task_budget_authority.py:108-111`；`task_budget_positive_authority.py:120-125` |
| Ticket（持久工作单） | Goal/Task 图：`pending→in_progress→done/blocked/…` 合法转移表、`blocked_reason` 必填、`evidence_required` 时 →done 必带 `evidence_refs` | `src/llm_loop/introspection/tools_task.py:59-86` |
| Gate（谁能起活） | 飞书入站审批白名单：私聊 + open_id 允许集（`feishu_session_map.json` 的 `p:` 前缀 + `FEISHU_APPROVAL_ALLOWED`） | `src/llm_loop/feishu/approval.py:75-95` |
| Source（事件流） | 飞书入站有（去重 + `im.message.receive_v1`）；**GitHub 事件源无**；git remote 仅 gitee（主）+ github legacy（archived, no-push） | `src/llm_loop/feishu/bridge.py:3,297`；`git remote -v` |
| Trigger / Thread | **无**（`src` 全量 grep `mandate\|ticket\|thread_id` = 0 命中） | grep |
| Ticket↔Executor Session 绑定 | **无**：`dsh_task` 每任务新 Agent + 新 session，自述"无跨任务记忆" | `dsh_task.py:10,42,253,383` |
| Ticket 独立工作目录 | **无**：仅传 `cwd`（默认工作区），不建独立目录/worktree | `dsh_task.py:156-159`（无 mkdtemp/worktree） |
| Subscription（事件续接工单） | **无** | grep 0 命中 |
| accept mode off/observe/auto（主动候选影子评估） | **无**：`src/llm_loop` 中 `proactive\|auto_accept\|inferred_candidate` 全仓 0 命中 | grep |
| "只在人要做事时说话" | 仅飞书出站限流（60s 窗口 / 上限可配）；**无按任务状态的注意力闸** | `src/llm_loop/introspection/tools_feishu_outbound.py:42,88-102` |
| 30 分钟轮次后后台上限 | `dsh_task` 是**整调用超时**：默认 300s / 上限 3600s，语义 ≠ "每轮后 30 分钟" | `dsh_task.py:44-45` |
| 人工消息预留执行槽 | 无对应；并发受 job limit 约束（`JobLimitExceeded`） | `dsh_task.py:294` |
| 执行审批 | 本仓破坏性工具走 `exec_mode` + approval（`execute_command/edit_file/write_file/delete_file/append_file`）；`dsh_task` 子进程本身无隔离 | `registry.py:613-615`；`dsh_task.py` |

---

## 4. 三条路径的可行性

### 路径 A｜本机另起独立 profile 接 Super-agent（指向某个 github.com 仓）

可行但与本仓主线弱相关，且有 4 个实质问题：

1. **没有目标仓**：Super-agent 观察 github.com 的 Issue/PR；本仓主 remote 是 gitee，github legacy 已 archived + no-push。→ 只能指向一个**别的**仓，那就不是"本仓受益"。
2. **cordis 双版本风险**（推断）：bundle peer 精确钉 `4.0.5-alpha.1`，本机 profile 装的是 `4.0.5`；pnpm 自动装 peer 时可能在同一 profile 出现两个 cordis，而插件的 `ctx` 来自宿主 Context → 运行期身份不一致。**必须实测**（§7 G3）。
3. **dsh 版本**：engines/peers 由 rc.2 满足（实测 semver），但上游安装说明钉 rc.3 → 软闸门，建议直接升 rc.3+（registry latest `0.2.1-rc.5`）。
4. **安全暴露面扩大**（已核上游自述）：executor 以 OS 用户身份、无需审批运行命令；本机持有 gh `repo` scope token 与多家模型 API key 环境变量。

其他前置：node/gh/git/tmux/Python 齐备 ✅；`lark-cli` 缺失 → Feishu 源不可用（上游默认亦 disabled，可接受）。

### 路径 B｜借设计，不装代码（**推荐**）

Super-agent 真正的贡献不是代码，是"工单是系统组织单位"和"注意力经济学"这两条设计律。本仓可低成本吸收其中 4 项，且与既有规则（admission asymmetry、RULE-AI-23 当前任务授权）兼容——具体见 §6。

### 路径 C｜把 Super-agent 当 DSH 插件通过 MCP 桥接进 LFL

本仓已有 `scripts/dsh_plugin_bridge.mjs`：按 `data/dsh-bridge/plugins.json` 清单把 DSH 插件装配成 MCP stdio 工具（bridge:12-13,36,57-60；`scripts/dsh_plugin.sh` 负责 npm install + 写清单）。但 Super-agent 是 **bundle layer + 自带 Web 面板 + 自带 Settings/Management API**，不是一组可被 MCP 暴露的工具 → 接进来要另写一层适配，工作量远大于收益。**不建议**。

---

## 5. 一个容易被忽略的对照：本仓已经更"硬"的地方

不要把 Super-agent 当成整体更先进的框架来对标。它在两处比本仓**更弱**（已核）：

- **授权不可伪造性**：上游 Mandate 记录 Policy 版本与匹配规则，但由模型做 Assessment（002:100-105），判"值不值得做"的权力在模型侧；本仓 Grant 由 ed25519 签名签发（`operator-ed25519-v1`），且 `deadline_epoch_s` 是有限期的——授权来源可验、有效期可查。
- **执行隔离**：上游明写"defaults, not a security boundary"；本仓破坏性工具走分级审批。

它真正领先的是**工作组织方式**（Ticket 独立于 Session、Thread 订阅、影子评估、注意力闸），不是安全或授权模型。

---

## 6. 可吸收的 4 个设计增量（推断，待设计）

| # | 增量 | 对应本仓缺口 | 与既有规则的兼容性 |
|---|---|---|---|
| D1 | **工单绑定执行上下文**：Goal/Task 绑定一个可复用的 DSH Session（而非每任务新 session），使后续轮次能在原上下文续做 | `dsh_task` 自述"无跨任务记忆"；本仓 §5.3 已记为局限 | 中性；需先解决 session 复用与并发隔离 |
| D2 | **影子评估层（observe 档）**：对"未被明确请求但可能值得做"的工作只产出评估记录、不启动 | 全仓无主动候选评估机制 | **兼容**：只记录不执行 = 不扩权，符合 admission asymmetry 与 RULE-AI-23 |
| D3 | **注意力闸**：出站通知按任务状态过滤——只在 `blocked` / `waiting_review` / `failed` / `done` 时推人，进度类不推 | 现仅有 60s 限流，无状态语义 | 兼容 |
| D4 | **执行隔离**：每次委派建独立工作目录（或 worktree），不直接在主工作区改 | `dsh_task` 直传 cwd | 兼容；提升安全，与 §5 一致 |

D2 是其中最值得先做的：它把"要不要主动干活"的判断显性化并留痕，同时**不授予任何执行权**——正是本仓 admission asymmetry 想解决而尚未建模的那一块。

---

## 7. 开工前必须实测的闸门

| 闸门 | 问题 | 判定方式 |
|---|---|---|
| G1 | 目标 github.com 仓是否存在且允许该 agent 账号访问 | `gh repo view <owner/repo>` |
| G2 | dsh 升到 rc.3+ 后 `dsh <p> --from-default-profile web --dump-config` 是否正常 | 实跑 + 看 `--dump-config` 树 |
| G3 | 在 profile 内 `dsh plugin add "link:$PWD"` 后 cordis 是否出现双版本、插件 `ctx` 是否正常 | profile 内 `pnpm why @deepseek-ai/cordis` + 启动日志 |
| G4 | `pnpm build` 是否能在本机 node 24.18 / pnpm 12.11 下通过（packageManager 钉 11.7.0） | 实跑 `pnpm install && pnpm build` |
| G5 | 装完 `scripts/dsh-superagent status` 是否 exit 0、无 setup problem | 实跑 |
| G6 | 若走 Feishu 源：需 `lark-cli` + bot 配置（本机缺失） | `command -v lark-cli` |

**这些闸门未实测前，不应写"可以接入"**；本文只给"可行性边界与实测清单"。

---

## 8. 未核 / 不声称

- **未取到设计文章原文**《Exploring Super-agent Design: Towards a More Autonomous Agent System》——本轮核的是仓库 README + docs/000~008 + 代码，**不是**那篇文章；文章与 docs/008 的一致性未验证。
- 未实测安装、未实测构建、未实测 profile 行为、未验证任何性能/效果主张。
- 上游 2123 star / 180 fork 是 2026-11-01 07:2x CST 的采样快照，会变。
- 本文未评估"上游内部实现"与"公开原型"的差异（公开原型是发布适配版，README 明说不完全等同内部实现）。
- 未涉及本仓任何代码改动；未做提交；工作树在本文写作前已有 92 untracked / 24 modified，非本文产生。

---

## 附：本文档的收录决定

按 `docs/INDEX.md` 的"公开面原则"，本文件是**架构/竞品参考类**文档，参照既有先例 `docs/analysis/2026-10-10-openJiuwen_竞品分析.md` 与 `docs/agent-harness-landscape-2026.md`：**入库（tracked）但不进 INDEX 清单**。若后续结论落地为实施项，另立设计文档并按 RULE-AI-28 走独立审查。
