---
method_id: resolve-runtime-dir-via-config-chain-on-path-miss-c761762815e9
name: resolve-runtime-dir-via-config-chain-on-path-miss
description: 预检需要确认运行时数据目录（经验库/方法库/缓存等）位置时，若按约定猜测的路径 ls 返回 No such file，而此前工具输出中的装配代码已把该目录表示为配置解析产物（factory 把 runtime_paths.<x>_dir 注入 store），则停止继续猜约定路径、find 宽枚举和重复 grep：沿 resolver→显式 env 覆盖→真实目录 的解析链一次查证。仓库存在多个同名目录副本（worktree/.releases 旧副本）时，解析链还是唯一能消歧的权威，枚举可能命中过期副本。用约 3 次窄查询（读 resolver、grep env、ls 终点目录）替代猜测失败后的 5-6 轮扩散搜索。附：勿把网络探活与文件系统扫描捆进一条无独立超时的命令，超时不可归因。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:8bc1cbb3-5fe5-44cb-9818-3acb329d2acb:454:a2ae1008f8cf99c28e9a
evidence_refs: learning:learn:1bd08dc67127
created_at: 2026-10-11T18:13:54.584534+08:00
updated_at: 2026-10-11T18:13:54.584534+08:00
---
## Trigger
预检/定位某运行时数据目录时，约定猜测路径（如 data/<name>/）首次 ls/grep 返回 No such file；同时此前已看到的装配/工厂代码显示该目录是配置解析字段（如 ExperienceStore(_runtime_paths.experiences_dir, ...)），即目录位置由 resolver 决定而非固定约定。

## Discriminator
factory 片段已把目录绑定为 `_runtime_paths.experiences_dir`（ExperienceStore 构造参数）——该事实在猜测之前已在屏上：目录位置是 resolver 输出（显式 env 覆盖优先、否则按 state/data 推导），约定猜测无依据；后续还证实仓库内有多个同名 experiences/ 目录（./experiences、.codeartsdoer、.releases×3），宽枚举必带选错旧副本的歧义，只有 env 覆盖值能唯一钉活实例。

## Short path
- 未知量=目录解析到哪：一次 grep resolver 源码（paths.py）中该字段的解析逻辑
- 从解析逻辑读出显式覆盖变量名（EXPERIENCES_DIR），grep 配置文件（.env）确认是否覆盖及取值
- 对解析出的唯一真实目录执行 ls|wc 并确认目标内容（如 387 条卡、目标卡文件名在列）
- 目录+内容证据闭合后停止发现，回到原任务（改配置→重启）

## Stop conditions
- 解析链终点目录存在、计数与目标条目可见，目录未知量已闭合
- resolver 表明无显式覆盖、推导默认即猜测路径且已命中目标内容

## Verification
- 实际 ls 的路径与 resolver 推导（env 显式值或推导默认）逐字符一致
- 多副本场景下确认所用目录是 env/当前运行实例指向的那个，而非 .releases 等旧副本
- 目标内容存在性以终点目录的真实回执（计数+条目名）为准

## Counterexamples
- 约定路径首猜即命中且含目标内容：直接使用，不为走解析链而绕路
- 目标是源码内固定相对路径、与 resolver 无关：直接 grep/find 更快
- resolver 源码不可读或解析逻辑多层间接、成本超过一次 find：先 find 一次再收敛也是合理短路径
- 任务/用户已显式给出目录路径：跳过解析，直接校验给定路径
