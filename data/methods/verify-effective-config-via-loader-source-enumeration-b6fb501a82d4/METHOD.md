---
method_id: verify-effective-config-via-loader-source-enumeration-b6fb501a82d4
name: verify-effective-config-via-loader-source-enumeration
description: 验证某配置键在运行进程的生效配置中已移除/存在（重启验收类任务）时，不要靠文件名搜索或猜 .env 来发现候选配置文件：任务上下文中已有的键名本身是单跳可靠边——grep 进 loader/resolver 源码即得到封闭来源集合、优先级与候选路径清单，把『接线可能藏在哪』从全仓库多副本缩成 pinned 进程根下少数几个来源的逐项检查。文件名搜索的 miss 可能是假阴性（本集 search_files 找不到实际存在于根目录的 runtime.toml），不能当证据。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:fd840981-a906-404c-8c80-1c3452e1c66a:634:f35a911bd0f036b108bc
evidence_refs: learning:learn:9c6153153875
created_at: 2026-10-09T22:06:40.676180+08:00
updated_at: 2026-10-09T22:06:40.676180+08:00
---
## Trigger
需要对运行中进程核实某配置键确实已不存在（或存在）于生效配置——典型如删除接线/开关后的重启验收；且仓库存在多份同名配置副本（工作区/tmp/releases）或文件名搜索结果可疑时。

## Discriminator
当时已知可 grep 的键名（上回合结论中的 task_budget_canary_config 及其 env 投影名）：一次源码 grep 即命中 resolver 注册点，给出封闭来源与优先级（runtime.toml > legacy .env > defaults，含回退路径）及缺键默认语义；而文件名搜索已表现为假阴性（pattern=runtime.toml 无匹配但文件在根目录存在），两条边当时都在手，前者未被优先使用。

## Short path
- 精确表述未知量：『键 K 是否在进程 P 的生效配置中』，而非『所有配置文件在哪』
- 用已知键名 grep loader/resolver 源码 → 从注册点提取封闭来源列表、优先级、候选路径（含 home/回退路径）
- lsof/proc 钉住进程 cwd/runtime_root，确定清单内哪些文件实例是活的
- 只对清单内来源逐项检查键 K（若键为 env-projected，含进程真实 environ），并读取缺键时的 loader 默认语义（缺失→None→OFF）
- 逐来源回报『无 K + 默认语义』即完成核验，停止

## Stop conditions
- loader 清单内全部来源（含回退/home 路径，及进程 env 若键为 env-projected）均已查过键 K，且缺键默认语义已知 → 停止，不再追加文件名搜索或目录枚举
- 若存在生效配置快照函数/端点（如 business_config_snapshot）可直接读取 → 直接读快照并停止

## Verification
- 被检查的文件实例与 lsof 钉住的进程 cwd/runtime_root 一致，不是 tmp/releases 下的副本
- 『接线为空』结论附 loader 缺键语义（缺失→None→OFF），使文件级缺键足以推出运行时无接线
- /health 的 git_head 与工作区 HEAD 一致，排除『新进程跑旧代码』的混淆

## Counterexamples
- 已有生效配置快照可读（快照端点/函数直接输出全部有效键）→ 直接读快照，无需重建来源清单
- 键不经 resolver 注册，而是散落的 os.environ/getenv 直读、或来自部署层（systemd/容器 env、外部配置服务）→ 源码清单不封闭，必须改查进程真实 environ/部署清单
- 任务本身就是发现同名文件去编辑/清理 → 文件系统发现即目标，源码枚举不适用
