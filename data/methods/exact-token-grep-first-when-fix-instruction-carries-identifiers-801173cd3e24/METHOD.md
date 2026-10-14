---
method_id: exact-token-grep-first-when-fix-instruction-carries-identifiers-801173cd3e24
name: exact-token-grep-first-when-fix-instruction-carries-identifiers
description: 当修复/修改指令本身已携带近唯一的代码标识符（具体函数名、状态变量名、行号）时，这些 token 就是现成的 provenance edge：第一步直接用 rg/grep 精确检索（排除 node_modules/.git）定位文件并重锚定行号，不要先走全库 search_files 类宽搜索；宽工具单次超时后立即切换到精确检索，不用相同参数重复重试。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:a8175f76-978e-491c-9cb6-58ac1695215c:1:93d06d37b0092e718421
evidence_refs: learning:learn:3ab71d17dae8
created_at: 2026-10-13T21:22:30.162760+08:00
updated_at: 2026-10-13T21:22:30.162760+08:00
---
## Trigger
修复/审查指令文本本身包含可直接检索的近唯一代码标识符（具体函数名、状态变量名、行号），任务是在代码库中定位并修改对应实现

## Discriminator
指令中已有的标识符组合（如 onRunStarted + newSessionPending + 具体行号）在库内近乎唯一，在第一次调用工具之前就足以把定位空间从全库缩到一两个文件；因此任何全库枚举式搜索都只会扩大搜索面并承担超时成本

## Short path
- 从指令提取标识符 token，rg -n '<token>'（带排除 glob）一次性拿到目标文件与当前行号，并将用户提供的行号与当前源码重锚定（可能来自旧版本）
- 只读定位点上下文，确认结构事实（如 guard 语句与被其拦截的清理语句的相对位置），验证用户诊断与当前代码一致
- 若修复跨前后端契约，用同一标识符（如 new_session）检索对端 schema/路由，确认语义契约后再动手
- 应用最小修改并补回归测试覆盖原触发组合
- 跑定向测试与类型检查；无关失败用暂存隔离归因，确认后停止

## Stop conditions
- 当前源码结构已确认与指令诊断一致（行号重锚定吻合），且定向测试与类型检查全绿
- 宽搜索工具单次超时后不再以相同参数重试，已降级为精确标识符检索

## Verification
- 用户行号与当前文件实际结构对齐；不一致时以当前源码为准并说明偏差，不机械按行号修改
- 新增回归测试能复现原 bug 触发组合并通过

## Counterexamples
- 用户只描述模糊症状（如'页面偶尔卡住'）而无任何标识符 → 没有 token 可精确检索，目录/宽搜索才是合理首步
- 标识符过于通用（handler、init 等）会导致 grep 洪泛 → 需路径/文件类型限定，方法收益消失
- 环境无 shell/rg、仅有封装搜索工具 → 该方法不可用，超时切换策略也不适用
- 用户行号来自另一分支或旧版本且代码已重构 → 必须以当前源码重锚定，不能按行号直接改
