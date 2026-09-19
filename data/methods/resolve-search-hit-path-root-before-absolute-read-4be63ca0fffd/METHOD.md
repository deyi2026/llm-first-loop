---
method_id: resolve-search-hit-path-root-before-absolute-read-4be63ca0fffd
name: resolve-search-hit-path-root-before-absolute-read
description: 当 search/discovery 工具返回相对路径命中（如 llm_loop/resources/governor.py）时，路径根（src/ 等前缀）是未验证未知量：先做一次廉价根确认（list 顶层或按搜索根解析），再构造绝对路径去 read/edit。若 read 失败回执带有"该路径此前已登记不存在(TTL)"类负向登记，禁止继续同形路径猜测，必须切换定位策略（list/根确认），而不是换一个同类猜测或重扫宽搜索。本集：命中相对路径后直接拼工作区根导致 file-not-exist（该路径形已登记不存在），被迫二次宽搜索（30 命中）才定位 src/ 根。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:8264c548-85f1-4132-ad60-06764dbeb232:1004:6ccceddb03977a04ee2e
evidence_refs: learning:learn:e4078935b042
created_at: 2026-09-18T15:25:01.840478+00:00
updated_at: 2026-09-18T15:25:01.840478+00:00
---
## Trigger
search/list 类工具返回不含工作区根的相对路径命中，且下一步需要用 read/edit 打开其中某个具体文件

## Discriminator
命中路径缺少已被验证的根组件（如此前从未确认过 src/ 前缀）；或 read 失败回执明示该路径形已登记不存在且在 TTL 内——即同形猜测近期已失败过，继续枚举同形候选不会产生新信息

## Short path
- search 命中目标模块后，先判断命中是否为相对路径且根未验证；不确定则一次 list 顶层目录确认真实根（未知量：文件绝对路径的根）
- 用确认后的根直接批量 read 目标实现与同根已知关联文件（实现+调用方），而不是逐个猜路径
- 若 read 失败且回执带负向登记（已登记不存在+TTL），立即停止同形猜测，下一个动作改为 list/根确认，而非另一次路径拼接种或重复宽枚举
- 实现语义（non-preemptive、foreground barrier、requeue 语义）读齐后停止发现，进入契约核对与编码

## Stop conditions
- 绝对路径一次 read 成功且 snapshot 确认 workspace_path_state=current_match，路径定位关闭
- 同形路径已被负向登记：不再产生任何同根猜测，直到用独立手段（list）重建根
- 实现、调用方、契约枚举、journal 语义均已从已验证根读到，进入编辑阶段

## Verification
- 本次任务内所有 read/edit 均从同一已验证根出发，无第二次同形 file-not-exist 重试
- 负向登记回执后的下一个动作是根确认/list，而不是再猜一个路径
- 最终打开的文件与 search 命中的模块名/符号一致（provenance 一致）

## Counterexamples
- search 工具返回绝对路径，或本会话已有同根成功 read 记录 -> 直接读，额外 list 是浪费动作
- 回执显式提示文件可能刚被创建（负向登记的例外条款）-> 允许一次重读确认而非切换策略
- 目标位于仓库约定规范位置（根目录 pyproject/README 等）-> 无需根解析，直接读
