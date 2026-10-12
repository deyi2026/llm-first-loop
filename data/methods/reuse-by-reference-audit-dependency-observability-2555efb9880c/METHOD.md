---
method_id: reuse-by-reference-audit-dependency-observability-2555efb9880c
name: reuse-by-reference-audit-dependency-observability
description: 当任务是按既有冻结模式新建一个消费者（协议/评测/runner）时：(a) 工件名已知就直接查版本库工件树（git ls-tree+grep 默认分支），语义文档搜索只是次级索引；(b) 继承参考消费者的判分纪律后，必须通读共享依赖（fixture/服务）源码，把每条新条款映射到依赖实际暴露的可观测面（如 /manifest 键、/state 事件）；(c) 发现不可观测的条款族时，在协议内预声明加法式修正案，而不是留到运行期失败才修；复用契约一律引用不重推导。本 episode 由此在设计期就暴露 navigate 族无服务端可观测的缺口，避免了先跑模型再返工。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:5d5ca284-3a97-4bd1-8ff4-ad803e0987fd:217:46ae093b890c01698ac0
evidence_refs: learning:learn:ef280848eb61
created_at: 2026-09-17T22:57:30.397271+00:00
updated_at: 2026-09-17T22:57:30.397271+00:00
---
## Trigger
用户要求按既有模式/建议新建协议、评测或 runner，且版本库中存在已冻结的参考实现（PROTOCOL/PLAN/runner 文件组）与共享 fixture/服务依赖；或新需求包含旧消费者未覆盖的条款族。

## Discriminator
两个当时即可见的事实可早缩搜索与验证空间：其一，查询词本身就是已提交工件名（browser_smc_* 协议族），且 git status 已显示评测工件按 evals/<name>/ 目录组织，故 ls-tree+grep 一步命中权威文件组；其二，参考协议明示判分面只有依赖暴露的 /manifest+/state，因此新条款是否可判只有依赖源码能回答，参考消费者协议本身回答不了。

## Short path
- 建立 git 基线并确认默认分支与 worktree 占用情况，选定安全提交位置。
- 用已知工件名对默认分支 ls-tree+grep，直查参考 PROTOCOL/PLAN/runner 及共享 fixture 的精确路径。
- 读参考协议+计划，继承其判分纪律（期望运行时取 manifest、效果唯一走 state 日志、runner 零硬编码）。
- 通读共享依赖源码，逐条款族核对 manifest 键与 state 事件是否实际覆盖该族。
- 发现不可观测条款族（如 navigate：GET 日志被静音、state 只记 POST）→ 在新协议内预声明版本递增的加法式修正案，并声明对旧消费者无影响。
- 在新 worktree 写并提交协议+计划，所有复用契约（worker/provider/浏览器启动）引用不重推导。

## Stop conditions
- 协议+计划落盘，且每条新期望都能映射到依赖实际暴露的 manifest 键或 state 事件，或被修正案明确覆盖。
- 所有参考契约以引用方式继承，没有重推导或复制改动。
- 缺口修正案已写明精确加法改动与对既有消费者的影响面（只读 events 的旧判分不受影响）。

## Verification
- 抽查每条新期望对应的键在依赖源码的 manifest 构建逻辑中确实输出。
- 抽查每条效果断言对应的日志键在依赖源码的 state 记录路径中确实写入。
- git log/diff 确认参考消费者与依赖本体未被改动，修正案为纯加法。

## Counterexamples
- 没有冻结参考工件的全新任务：无名字可 grep，应先做宽发现（docs 搜索、目录浏览），此时宽搜索不是绕路而是必要步骤。
- 依赖是外部第三方、只有冻结公开契约而无本地源码：审计契约文档即可，不必强求读源码。
- 参考协议已把依赖可观测面固化为带版本的接口契约且新条款全部落在其内：源码重读可跳过，直接进入编写。
- 仅微调既有协议参数、不引入新条款族的一次性修改：无需依赖源码审计。
