---
method_id: verify-declared-runtime-deps-in-fresh-execution-root-a4fa73c1d822
name: verify-declared-runtime-deps-in-fresh-execution-root
description: 当把一个已冻结的 runner/worker 契约移植到新建 git worktree（或任何全新 checkout）中执行时，被复用源码已经以路径常量形式声明了它的运行时资产依赖（数据/配置文件、固定端口、外部二进制）。应在读契约的同时提取这些声明，并在首次启动前逐一确认它们在执行根（worktree）中存在：gitignored/未跟踪资产按构造不会出现在新根里，未验证的移植会在启动瞬间崩溃，耗掉失败轮次、一笔热修提交和重启——而真正的未知量（被测行为）一步都没测到。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:5d5ca284-3a97-4bd1-8ff4-ad803e0987fd:257:6d33ca9abea60c0bbee0
evidence_refs: learning:learn:457853ba0ca5
created_at: 2026-09-17T23:20:50.462552+00:00
updated_at: 2026-09-17T23:20:50.462552+00:00
---
## Trigger
复用/改写仓库内别处的冻结 runner 或 worker 契约，且执行环境是新建的 git worktree 或全新 checkout；即将进行第一次端到端启动（dry-run 或 measured run）。

## Discriminator
契约研读阶段读到的被复用源码中，显式硬编码了运行时资产路径（如 PROVIDERS = REPO / "data" / "providers.json"、固定 model 端口），而执行根是一个新 worktree——gitignored 文件在该根中按构造缺失。这两个事实在动手实现之前都已可见，无需任何事后信息。

## Short path
- 读冻结 PLAN/PROTOCOL；未知量：要建什么、复用哪些被点名 artifact——只沿被点名的路径走，不做仓库级枚举。
- 逐个读被点名的复用契约文件；边读边提取其声明的运行时依赖（硬编码 data/config 路径、端口、外部二进制）成清单；未知量：启动时哪些外部资产必须存在。
- 首次启动前，对清单逐项检查其在执行根（worktree，不是编写契约的原 checkout）中是否存在/可解析；未知量：移植后的 runner 能否启动。
- 缺失的 gitignored 资产先物化或加解析回退，再先跑无模型 dry-run；preflight 全过后才排 measured run——让首次启动检验真正的未知量而非基础设施。

## Stop conditions
- 清单上全部声明依赖已在执行根验证存在（或显式改写了解析方式），且无模型 dry-run 端到端通过。
- preflight 干净后启动仍失败——这是真实新 bug 而非移植摩擦，停止套用本方法，转入正常调试。

## Verification
- 移植后的 runner 首次启动能越过初始化，不出现秒挂/启动即退出。
- 任何 measured/model run 被排期之前，dry-run/自检门在新 worktree 内先通过。
- 清单每一项都能回指到被复用源码中的一行（provenance），而非凭对原仓库布局的记忆。

## Counterexamples
- 在原始 checkout 里运行、gitignored 资产本就存在——预检是冗余开销，可直接启动。
- 被复用契约通过 CLI 参数/环境变量解析路径，且新 runner 会覆盖默认值——应核对参数管道而不是硬编码路径。
- 资产由 runner 启动时自动生成或按需拉取——启动前缺失是预期行为，不是缺口。
- 一次性脚本、无外部文件依赖——没有可预检的对象。
