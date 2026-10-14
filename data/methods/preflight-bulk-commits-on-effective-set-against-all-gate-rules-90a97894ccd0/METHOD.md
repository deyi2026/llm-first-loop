---
method_id: preflight-bulk-commits-on-effective-set-against-all-gate-rules-90a97894ccd0
name: preflight-bulk-commits-on-effective-set-against-all-gate-rules
description: 批量入库大量 untracked 文件前，先把审计范围缩到『有效 staging 集』＝untracked 减去 .gitignore 已排除项（.venv/ 等运行时目录不可能入库，扫它们只会产出第三方源码误报）；再对有效集按提交门全维度预检：凭据、本地绝对路径、文件体积。审计输出（命中清单、大文件清单）必须回写进 staging/gitignore 决策后才提交，而不是被门逐条拦截、每轮只修一条规则；首条拦截回执若点名执法脚本（如 _ALLOWLIST），读一次完整规则列表，一次修全。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:1897dc0c-c278-413c-b54d-22c50b97372f:1527:702e9fa76189195eb701
evidence_refs: learning:learn:e042d5317c5a
created_at: 2026-10-14T13:15:44.331693+08:00
updated_at: 2026-10-14T13:15:44.331693+08:00
---
## Trigger
需要把几十到几百个 untracked 文件分类提交入库（知识沉淀/产物收口），且仓库存在多规则提交门（pre-commit 安全扫描：密钥、本地路径、体积门）时

## Discriminator
已读取的 .gitignore 显示 .venv/ 等目录任意层级被排除——这些文件不可能进提交，扫描它们只会制造上百个误报并触发二次重扫；且自有审计输出当时已列出全部 >300K 文件（含 4 个 ~1.5M 渲染件）。范围事实与体积事实在 staging 决策前已在手，却未与提交计划和门的规则维度对齐

## Short path
- 读 status 分组计数、先例提交与 .gitignore，确定排除规则与入库口径（未知量：什么会真正进提交）
- 求有效 staging 集：untracked 减去 ignore（ls-files --others --exclude-standard 或 check-ignore 过滤），4565→~309 文件
- 对有效集做全维度预检：凭据模式、本地绝对路径（/Users/ 等）、体积>门限（未知量：每条门规则会不会拦）
- 逐命中读上下文裁决：公开徽章 URL 参数等误报放行，真实凭据先处置（未知量：命中是泄漏还是噪音）
- 把裁决回写计划：可再生的超大派生渲染走 gitignore（md 源+构建脚本入库），本地路径统一脱敏
- 分类 add+commit；若仍被拦截且回执点名执法脚本，读其完整规则列表一次修全，不做逐规则重试

## Stop conditions
- 有效集预检全绿，命中裁决与体积处置已回写 staging 计划
- 分类提交通过仓库门，post-status 无新增 untracked

## Verification
- 提交后 git status 树净（tracked 面无遗留 untracked）
- 被 gitignore 的派生物确认可由已入库源+构建脚本再生；被放行的命中已通过上下文核对确认非凭据

## Counterexamples
- 小规模纯文本提交且门规则已知单一：直接提交让门兜底更短，全套预检是过度流程
- .gitignore 尚未读取或仓库无 ignore 规则：不能假设任何排除，须先全量审计再缩范围
- 大文件是不可再生的原始证据（唯一截图/日志原件）：不应 gitignore 排除了事，需豁免登记或外部存储决策
