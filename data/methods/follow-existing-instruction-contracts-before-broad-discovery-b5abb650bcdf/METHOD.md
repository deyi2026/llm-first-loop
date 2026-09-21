---
method_id: follow-existing-instruction-contracts-before-broad-discovery-b5abb650bcdf
name: follow-existing-instruction-contracts-before-broad-discovery
description: 重写项目 agent 指令文件时，先读取现有指令文件及其显式引用的规范、规则、测试和命令入口，沿这些 provenance 边确定必须保留的锚点与真实命令；只有这些边断裂、缺失或不足时才扩大仓库枚举。避免为补全上下文而扫描全仓库。
status: candidate
source_model: cognilocal/qwen3.8-flash-next
source_episode_refs: episode:f7469d7b-59d1-494b-955f-c9153320141e:105:2fd66adb6fe1ac3c6a11
evidence_refs: learning:learn:8d5f7f8e0f23
created_at: 2026-09-20T17:50:29.356846+00:00
updated_at: 2026-09-20T17:50:29.356846+00:00
---
## Trigger
用户要求按外部规范和仓库实况重写/更新 agent 指令文件，且仓库已有该文件或类似契约文件。

## Discriminator
现有指令文件是否显式引用 canonical contract、规则 ID、测试或命令入口；这些引用能把搜索从全仓库缩到少数约束来源。

## Short path
- 定位仓库根并读取现有指令文件，识别重复、显式引用和可能硬约束。
- 沿现有文件引用的 canonical contract/规则 ID 读取，并搜索测试/CI 对该文件的断言。
- 只读取能证明真实命令的权威入口（README 运行段、CI 脚本、pyproject/工作流），不枚举无关源码目录。
- 按外部规范重组文件：保留硬锚点，删除重复正文，补实测数字和实际命令。
- 运行针对该文件的测试并检查引用路径/安全模式，满足后停止。

## Stop conditions
- 所有硬断言测试通过且必需锚点存在。
- 真实命令均来自权威来源且可复现。
- 引用路径存在且无敏感路径/密钥命中。

## Verification
- 运行断言指令文件内容的测试。
- 确认必需锚点（canonical doc、rule ID）仍存在。
- 确认引用路径存在且命令来自权威来源。
- 按项目安全扫描模式检查新文件无敏感路径/密钥。

## Counterexamples
- 仓库没有现有指令文件或其引用已失效，需要 broad discovery。
- 现有指令文件与当前 runtime/CI 明显冲突，必须重新建立事实源。
- 任务只是创建最小模板，不需要仓库实况。
- 外部规范与仓库硬约束冲突时，以仓库测试/CI 为准，不机械照搬规范。
