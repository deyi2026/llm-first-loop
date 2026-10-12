---
method_id: resolve-relative-hit-root-before-broad-scan-c3745aa4df44
name: resolve-relative-hit-root-before-broad-scan
description: 当期望路径在 cwd 确定性不存在、但文件名搜索返回相对路径命中时，真正的未知量不是"文件在磁盘哪里"，而是"该相对命中属于哪个 checkout/worktree/镜像根"。先用一条命令枚举候选根（git worktree list + 兄弟项目目录），逐根 stat 定位唯一属主，再在属主根内用 git status/branch/HEAD 验证落盘状态。避免全盘 find、重复访问已登记不存在的路径。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:5d5ca284-3a97-4bd1-8ff4-ad803e0987fd:85:22acaf8e8509c2b50a8a
evidence_refs: learning:learn:d8b3cbd8cbd6
created_at: 2026-09-17T17:13:34.492777+00:00
updated_at: 2026-09-17T17:13:34.492777+00:00
---
## Trigger
目标 artifact 的预期相对路径在当前 checkout 返回确定性 not-exist（非超时/权限），同时 search_files 以相对路径命中该文件名；仓库存在镜像/兄弟目录/.worktrees 等多根结构。

## Discriminator
进入摩擦点前已同时可见两条事实：(1) cwd 的 git toplevel 下 ls 明确报目录不存在 → 不在本 checkout；(2) 搜索命中是相对路径 → 搜索索引根 ≠ cwd 根。二者把候选空间从"全盘扫描"缩成"解析索引根是哪一个"；且工具失败回执已登记该路径不存在（TTL 24h）并明确建议停止重试该路径。

## Short path
- 在 cwd 以 toplevel 相对路径 ls/stat 确认缺失，拿到确定性失败回执——建立"不在本 checkout"事实
- 由相对命中导出唯一未知量：索引根是谁；一条命令枚举候选根：git worktree list + ls -d 兄弟项目目录（如 ~/Project/<name>*）
- 在每个候选根下 stat 该相对路径，定位唯一包含它的属主根
- 在属主根内执行 git status --short / branch --show-current / HEAD 对比 main tip，确认 untracked、detached 与相对 delta
- 核对文件行数/字节数与上轮产出一致后停止发现，汇报位置、丢失风险与依赖排序的后续建议

## Stop conditions
- 唯一属主根已找到，且其 git 状态（tracked/untracked、HEAD 与 main 关系、相对 delta）已验证
- 所有已知候选根均不包含该文件——此时才允许扩大到全盘搜索或向用户求证

## Verification
- 属主根内文件行数/字节数与上轮产出记录一致
- git status 显示的改动集合与预期（纯新增目录、无其他 delta）一致
- 无第二个候选根同时包含该文件（属主唯一性）

## Counterexamples
- cwd 下 stat 直接成功 → 无根歧义，直接继续任务，不做根枚举
- 搜索工具返回绝对路径 → 根已解析，本方法多余
- 单 checkout 项目、无 worktree/兄弟目录且索引未命中 → 全盘 find 才是正当手段
- 失败回执可能陈旧（文件刚被创建）→ 应先重新 read 确认，而非根枚举
- 用户问题不依赖 artifact 物理位置（纯咨询/文档任务）→ 无需定位
