---
method_id: relocate-code-port-entrypoints-precheck-all-destination-ratchets-a5664c2d7edd
name: relocate-code-port-entrypoints-precheck-all-destination-ratchets
description: 修依赖/架构 guard 违规而把既有函数抽取到新层目录模块时，ratchet 按位置生效：搬入代码必须满足目标层的全部机械规则，不只是触发本次修复的那条。先枚举 guard 测试与 CI gate 脚本里的完整 check 清单，逐点照抄原实现的外部访问正门（如 env 读取走同一 resolver 入口），本地定向验证未覆盖的 ratchet（典型：只在完整 gate 内跑的 env-access 扫描）在跑昂贵完整 gate 前单独预跑，避免完整 gate 跑两次。
aliases: 修架构边还要过哪些守卫, 代码搬层后env检查挂了怎么办, 完整gate跑两次的教训, 搬函数进kernel目录前先盘ratchet, gate脚本先读check清单再跑全量, 新helper文件要过仓库全部机械守卫
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:0288850e-0f1d-4194-baa2-7eaae8d94fd1:0:0d38f4f4dea22b9715c2
evidence_refs: learning:learn:d031388a79a6
created_at: 2026-11-13T17:29:06.757016+08:00
updated_at: 2026-11-13T17:29:06.757016+08:00
---
## Trigger
为消除某条机械架构 guard 违规（如 kernel import 边 AST ratchet）需把既有函数抽取/下沉到新层目录的模块（如 kernel 扫描集内新建 helper），且仓库由多个按路径生效的 ratchet 管理（import 边 baseline、env 访问扫描、函数尺寸 baseline），最终验证由一次昂贵的完整 CI gate 承担。

## Discriminator
触发修复的那条 guard 已证明本仓库规则按位置生效；目标层的完整规则集可在动手前枚举（guard 测试文件与 CI gate 脚本在工作区内可读）；被搬函数的外部访问正门（env 快照入口、路径解析函数）在原实现源码中已经存在、可直接照抄——重写访问方式等于引入一条未对账的新 ratchet 违规。

## Short path
- 枚举目标层规则全集：读 CI gate 脚本的 check 清单 + guard 测试文件，列出新文件必须满足的每条 ratchet（import 边 / env 访问 / 尺寸 baseline / lint / type）
- 通读被搬函数，盘点其全部外部访问点及各自正门入口（import、env 读取、fs 路径解析）
- 新模块逐点复用原入口（env 走原代码同一个 resolver 正门函数、路径解析复用同函数），只重排结构不改访问方式；原层做薄包装保持对外 API 不变
- 定向测试通过后，把本地验证未覆盖的 ratchet（如仅完整 gate 内执行的 env-access 扫描）逐条单独预跑
- 单条全绿后跑一次完整 gate，exit 0 即停，不再追加确认性动作

## Stop conditions
- 完整 gate 一次 exit 0，且 guard baseline / CI 配置文件 diff 为零
- 新位置文件对已枚举的每条 ratchet 单项检查全绿

## Verification
- 对照 gate 脚本 check 清单逐条勾销，确认没有『只在完整 gate 内执行』的检查项未经预跑
- diff 确认新模块的 env/路径访问与原实现走同一正门函数，无新增直连 os.environ 或自拼路径
- guard baseline 文件零改动（本类仓库通常只允许减少、不允许增加）

## Counterexamples
- 仓库只有一条 guard（如仅 import 边测试）：修掉那条边即可，无需全量 ratchet 盘点
- 被搬代码是纯计算、无 env/fs/import 外部访问：没有入口需要移植，只查 import 边
- 完整 gate 秒级可重跑或无法拆成单条检查：预跑无收益，直接迭代跑 gate
- 全新编写而非搬迁存量代码：没有原入口可照抄，应改为先查目标层的 sanctioned-access 规范再实现
