---
method_id: explicit-redeclare-target-env-on-generation-switch-6e73ca09c81d
name: explicit-redeclare-target-env-on-generation-switch
description: 部署/重启类脚本常从 ambient 环境变量解析目标根（code/runtime root、generation）。当持久 shell 此前操作过旧目标（旧 worktree、同日旧 .env）而任务已切换到新目标时，直接调用会在残留守卫处被拒（本例 preflight rc=2，LFL_RESTART_* 指向 gen63 旧根）。方法：首次调用前只读探测目标变量；在调用点显式重声明全部目标变量及确认标志，不跨世代继承 ambient。遇 operator-only 控制面动词被拦截时不重试不绕过，产出含已验证参数的精确命令移交操作员。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:fc0ed66c-e669-41c4-94d7-7e05031bbac6:944:54ae4cf3213018255844
evidence_refs: learning:learn:4e689e839913
created_at: 2026-09-22T17:53:25.669504+00:00
updated_at: 2026-09-22T17:53:25.669504+00:00
---
## Trigger
持久 shell 中要调用以环境变量解析目标根/世代的部署、重启或预检脚本，且任务已切换到新目标（新 worktree/新世代/新根），同时存在近期对旧目标的操作痕迹（旧 worktree、同日 .env、会话引用）

## Discriminator
进入调用前已可观察：runbook/.env 模板明示脚本经 env 解析双根且『两处必须保持一致』；磁盘上并存旧世代 worktree（gen63）与本日早间操作痕迹；本次目标为 gen64 新根。三者合并即把『直接跑 preflight』缩为『先只读探测 env、再显式重声明双根+确认标志』。

## Short path
- 按已读 runbook/源码要求准备新目标（新 worktree、.env 模板复制、gitignored artifact 复制）
- 首次调用目标解析类脚本前，只读探测 ambient：env | grep <runbook 列出的目标变量前缀>
- 探测到指向旧目标的残留（或不确定）时，在调用点显式重声明全部目标变量与确认标志后调用；无残留则显式声明后直接调用
- preflight 通过后，用只读 show 核对当前/期望 generation，再进入发布动作
- mutating 动词被 operator-only 边界拦截时：停止重试与绕过，把带已验证参数（含 --expected-generation）的精确命令移交操作员

## Stop conditions
- preflight 双 PASS 且 binding 输出的 code_root/experiences_source 与新目标一致、无 legacy divergence
- 控制面所有权拦截已发生且已产出精确移交命令（模型侧不再推进依赖该步的动作）

## Verification
- binding JSON 中 code_root=新 worktree 根、experiences_source=explicit_env
- 显式声明的双根与脚本回显的生效根一致（无 A3-RESIDUE 拒绝）
- 移交命令的 --expected-generation 与只读 show 显示的当前 generation 一致

## Counterexamples
- 一次性干净 shell（如 CI runner）无 ambient 残留：探测为空，方法只带来无害冗余而非收益
- 脚本目标来自位置参数或配置文件而非环境变量：env 重声明不被读取，应改为调用参数显式化
- ambient 残留与新目标恰好一致（同根复用）：不构成风险，只读探测即可排除，无需预判拒绝
