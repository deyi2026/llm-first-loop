---
method_id: attribute-suite-failures-via-touched-set-and-clean-head-worktree-8d92c40cb6dc
name: attribute-suite-failures-via-touched-set-and-clean-head-worktree
description: 编辑已落地、触面测试全绿但更大范围测试出现失败时的归因闸门。先用失败回执点名的文件/模块/环名与本次触碰文件集求交集，形成可证伪假设（空集→存量债务假设；非空→直接修自己，不做归因实验）；再用 pinned 干净 HEAD 检出做单变量对照证明零因果。对照前先盘点既有 worktree（'already exists' 回执即证明基线环境已存在、可复用），并覆盖 venv 的 editable 路径解析（PYTHONPATH 指向 worktree 的 src），确保基线真的运行基线代码。归因结论附 HEAD hash，比对按测试身份逐一进行，然后停止。区别于通用根因诊断法：本卡是编辑收尾处的确定性归因协议，核心新判别式是触碰集∩失败点名主题。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:f1523846-ee16-4c78-9f53-7abf782eac2b:1054:3521a40a83ef75b772ac
evidence_refs: learning:learn:d3f3976bea6b
created_at: 2026-09-30T00:29:25.766420+08:00
updated_at: 2026-09-30T00:29:25.766420+08:00
---
## Trigger
任务内已完成代码修改且目标触面验证通过后，全量/更大范围测试报告若干失败，需判定这些失败是本次改动引入还是存量提交债，以决定是否阻塞收尾。

## Discriminator
两条当时即可读的事实：(1) 失败回执（traceback/guard 输出）点名具体文件、计数或环名，与本次 diff 触碰文件集求交集即可分出假设方向；(2) `git worktree list` 是既有干净检出的权威清单，新建命令返回的 'already exists' 回执本身即证明基线环境已存在、应复用而非重建。

## Short path
- 对失败测试用 --tb=short 重跑，收集失败身份与回执点名的文件/符号。
- 与本次触碰文件集求交集：空集 → 存量债务假设；非空 → 放弃归因实验，直接修改动。
- `git worktree list` 先盘点既有干净检出；存在 pin 在当前 HEAD 的 worktree 则直接复用，没有才 `git worktree add`。
- 在基线 worktree 上只跑那几个失败测试；venv 为 editable 指向主仓 src 时，用 PYTHONPATH=<worktree>/src 覆盖解析，确保加载的是基线代码。
- 逐一比对失败身份：基线失败集 ⊇ 观察集 ⇒ 记录为存量债务（附 HEAD hash）并停止；任一失败在基线消失 ⇒ 归因本次改动，转修复。

## Stop conditions
- 干净 HEAD（记录 commit hash）上复现同一组失败身份 ⇒ 判定存量债务，登记结论后停止归因。
- 任一失败在基线不出现 ⇒ 归因本次改动，停止归因流程、转入修复。
- 失败点名主题与触碰集相交 ⇒ 属确认级归因，跳过基线实验直接修复。

## Verification
- 基线运行 pin 到具体 HEAD commit 并记录 hash；比对按测试身份逐一进行，不做印象式'应该没问题'。
- 确认基线进程实际加载 worktree 代码（PYTHONPATH 覆盖 editable 安装），而非主仓工作区代码。
- 复用既有 worktree 前核对其 pin 的 commit 与当前 HEAD 一致；不一致则新建对照环境，不得拿旧基线充当当前 HEAD 基线。

## Counterexamples
- 失败 traceback 直接命中自己刚改的文件/函数：无需基线对照，修就是了。
- 失败具 flaky/时间依赖特征：单次基线对照不足以下零因果结论，需重复采样或显式标记，不得套用单次对照流程。
- 工作区无可用 commit 基线（测试依赖未提交生成物、工作区即唯一真相）时，worktree 对照无效，应改用 git stash 往返等其他隔离手段，而非强行套用本卡。
