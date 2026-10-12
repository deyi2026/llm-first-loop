---
method_id: trace-symptom-literal-through-ui-to-error-code-606326fe00d7
name: trace-symptom-literal-through-ui-to-error-code
description: 用户逐字引用了失败提示时，先用该字面量定位展示层命中处；命中行所在的 handler 会给出触发它的 API 调用与错误码分支，把『全仓 grep 后端』缩成对单一错误码/异常名的定点检索。同时在含 .worktrees/ 等源码副本目录的仓库中，后端检索必须限定活跃源码根，否则结果被陈旧副本淹没。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:16fe103b-bd92-4cdd-984a-f6cd5b45235c:303:6b7448c384e0183ed2b6
evidence_refs: learning:learn:6506e547f8c2
created_at: 2026-09-20T17:10:15.809527+00:00
updated_at: 2026-09-20T17:10:15.809527+00:00
---
## Trigger
用户报告的问题带有逐字的 UI 错误/提示文案，需要在大型代码库中定位该用户可见行为的产生点与阻塞机制

## Discriminator
精确文案已在展示层小文件（如侧边栏组件，仅两百行）命中，且同文件内存在多条不同文案（对应不同错误分支）；仓库根下可见多个 .worktrees/ 源码副本目录——此时读 handler 提取 endpoint+错误码，比跨全仓的多 token grep 更快收敛

## Short path
- 用用户引用的精确文案在展示层检索，定位命中行（不同文案=不同错误分支，一并记录）
- 读命中行所在组件/handler 及其 fetch 封装，提取被调用的 endpoint 与区分各文案的错误码条件
- 用该错误码/异常名在后端限定活跃源码根（排除 .worktrees 副本）内做单 token 检索，直接得到 raise 点与异常类定义
- 读 raise 点所在函数（如 workspace_transition / 准入守卫），确认阻塞机制（如全局 fail-fast、全局布尔态）
- 对第二个症状复用同一链条：先找其 UI 入口与共享错误码，若共用同一后端 raise 点则先读该点再分叉到前端状态管理
- 两个症状均有『文案→错误码→具体代码行』因果链后停止检索，进入修复

## Stop conditions
- 每个用户可见症状都已具备完整的『UI 文案 → API 调用 → 错误码 → 后端 raise 点/前端卡死代码』链条
- 展示层 handler 显示多个症状由同一机制产生且该机制已被读到具体实现

## Verification
- 确认后端检索命中路径位于活跃源码根（非 .worktrees/ 或其他副本目录）
- 确认用户引用的文案与错误码分支一一对应（不同文案映射不同分支，而非同码混用）
- 确认 raise 点的守卫条件（全局 vs 会话级）与用户描述的触发场景（推理中/编辑中）一致

## Counterexamples
- 错误文案由后端原样下发、前端不做错误码分支时，UI handler 无法判别来源，应直接以后端字面量在活跃源码根检索
- 用户只是转述而非逐字引用症状时，字面量检索可能落空，需要复现或语义检索后再走此链
- 文案来自第三方依赖/框架而非本仓库时，两层都搜不到，应转向依赖版本源码或运行时日志
