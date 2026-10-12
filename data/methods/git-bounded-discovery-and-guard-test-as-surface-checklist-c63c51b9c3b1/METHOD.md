---
method_id: git-bounded-discovery-and-guard-test-as-surface-checklist-c63c51b9c3b1
name: git-bounded-discovery-and-guard-test-as-surface-checklist
description: 在 git 管理的仓库中需要定位『必须同步修改的全部表面』（版本号、配置键、协议字段）时：若已有证据表明全仓 FS grep 会超时、且目录布局未确认，不要凭记忆猜子目录——猜错的 grep 配合 2>/dev/null 表现为静默零命中，唯一信号可能只是 __pycache__ 里陈旧 .pyc 文件名。改用索引有界搜索：`git grep -n <token>` / `git ls-files | grep -i <keyword>`，一步拿到全部跟踪文件命中；若命中守卫/一致性测试，先读它——其断言就是权威变更清单；改完以运行该测试 + `git grep` 旧值清零收尾。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:179b3184-5b65-4276-8ed8-58ad424043e6:1094:a8943772b3b908b9ba6a
evidence_refs: learning:learn:dcbd1ef2f30c
created_at: 2026-10-12T10:04:35.295571+08:00
updated_at: 2026-10-12T10:04:35.295571+08:00
---
## Trigger
需要在仓库中枚举『哪些文件构成一个必须同步修改的表面集合』（如版本面、配置键），同时：(a) 已知全仓文件系统 grep 会超时/不可行；(b) 目标所在目录布局未经确认。

## Discriminator
进入搜索前当时已可见的两条事实：(1) 仓库是 git 管理的——`git merge-base` 等命令刚刚成功执行，索引级搜索即刻可用；(2) 本集明言『避免全仓 grep 再超时』，且随后对 `webui/*` 的目录猜测返回零条源码命中，只捞到 `tests/unit/__pycache__/test_version_consistency.*.pyc` 这类陈旧产物路径。两者共同把工具选择从『猜目录的 FS grep』收窄为『git 索引搜索 → 读守卫测试』。

## Short path
- git merge-base 确认可 fast-forward（本集已做，保留）。
- 用 `git grep -n SERVICE_VERSION`（或 `git ls-files | grep -i version`）替代猜目录的 FS grep：一步同时命中 `src/llm_loop/web/routes.py:528`（注释直接指向版本一致性测试）和 `tests/unit/test_version_consistency.py`，无需目录猜测、无静默零命中。
- 读守卫测试，取权威表面清单：pyproject / web SERVICE_VERSION / README 中英 / CHANGELOG 标题格式 `## v{x.y.z} `（含尾随空格）。
- git log / git show 补齐 CHANGELOG 时间线与提交内容（本集已做）。
- 按清单编辑全部表面 + 插入 CHANGELOG 条目，运行守卫测试验证后停止发现。

## Stop conditions
- 守卫测试覆盖的表面全部改完且测试通过（本集：版本一致性测试 2 passed）。
- `git grep <旧值>` 无残留命中（历史 changelog 段落除外）。

## Verification
- 运行仓库自带的一致性/守卫测试，而不是只目视 diff。
- 用 `git grep` 检索旧版本字符串，确认无遗漏表面。
- 合并前用 merge-base/分支拓扑确认合并方式（本集已做）。

## Counterexamples
- 目标在未跟踪文件、构建生成物或子模块中：git grep 搜不到，必须做有界 FS 搜索，本方法不适用或需补充 FS 覆盖。
- 已经确知目标文件的精确路径：直接读取/编辑，跳过任何发现步骤。
- 极小仓库或非 git 目录：FS grep 成本可忽略，无需切换到索引搜索。
- 守卫测试本身过期、未覆盖新增表面（如新 README）：不能把测试当完整清单，须以 git grep 全 token 复核为准。
