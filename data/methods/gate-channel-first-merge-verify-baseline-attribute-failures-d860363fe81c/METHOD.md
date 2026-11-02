---
method_id: gate-channel-first-merge-verify-baseline-attribute-failures-d860363fe81c
name: gate-channel-first-merge-verify-baseline-attribute-failures
description: 在自带门禁脚本的仓库里验证『分支合入已前进的主干是否安全/过杆』时，先从 gate 脚本一次完整读取中提取每步的权威命令与判定口径（含静态诊断棘轮/冻结 ledger），再在 tmp scratch 合并树上逐字复用这些命令；不要用裸工具 CLI 当等价物——棘轮仓里裸 pyright/ruff 会产出大量已在历史账内的 raw error，制造需要事后口径订正的噪声（本集：裸跑 20 条 error，随后三读 ci_gate.sh 才找到权威通道）。合并树上出现的任何红，先比对失败指向文件与合并改动文件集是否相交，再在目标分支干净检出上复现同一用例：同红=存量、异红=合并引入，结论按口径分别陈述。
aliases: 合并前先抄 ci_gate 的命令跑, 裸 pyright 报一堆错先看是不是棘轮口径, 合并树红了先在干净 main 复现, pre-merge 按仓库权威门禁口径验证, 分清失败是合并引入还是主干存量
status: candidate
source_model: minimax/MiniMax-M3.1-Flash
source_episode_refs: episode:c2df336a-eb98-4baa-9220-9e80d36e4ee2:1616:2b082a1ae3e780b57f7f
evidence_refs: learning:learn:63b575a285d8
created_at: 2026-10-31T21:17:52.269973+08:00
updated_at: 2026-10-31T21:17:52.269973+08:00
---
## Trigger
需要在带 CI/门禁脚本（如 ci_gate.sh）的仓库里，对『分支/补丁合入当前已前进的主干后是否仍过杆、是否引入回归』给出可裁决结论；或合并树验证中出现静态检查/测试红，且不确定是本次合并引入还是主干存量。

## Discriminator
首次接触 gate 脚本的回执（哪怕只读了头部）已显式枚举完整门禁链与各步名称（如 ruff→环境声明→pyright→tier0→全量 pytest），这本身证明『什么算过』由该脚本逐字定义；一次完整读取或按步名 grep 实际命令行，即可在运行任何检查前锁定权威通道，避免先跑裸 CLI 得到噪声、再回头找口径。

## Short path
- 定向核验待证事实本身（补丁/变更是否落盘：mtime、行数增量、独有标记 grep），不采信『已 apply』自述
- 从已读文档回执中已有的 commit/基线/worktree 路径直查状态与领先数，并用 merge-tree 预演冲突，未知量：结构上可否合
- 一次读全 gate 脚本（或按步名 grep 实际命令），提取每步权威命令与口径（静态诊断走哪个包装脚本/哪个 ledger），未知量：本仓『过』的定义
- 在 tmp scratch 合并树合入目标分支，逐字运行权威命令，未知量：合并树过不过本仓自己的杆
- 对任何红先做文件集相交判断（失败指向文件 ∩ 合并改动文件），再到目标分支干净检出复现同一用例：同红=存量、异红=合并引入
- 结论按通道分开陈述（权威口径为准；引用过裸 CLI 数字须标注口径），停止

## Stop conditions
- 各门禁步在权威口径下均有明确判定（过/红+归因完成），且每个红都有『谁引入』的基线证据
- 结构性结论已达成（冲突预演 rc、合并改动文件与主树脏文件无交集）且无需执行发布/合并动作

## Verification
- 确认实际运行的静态诊断命令与 gate 脚本逐字一致（同一包装脚本、同一 ledger），而非裸工具直跑
- 干净基线复现的失败与合并树上的失败为同一条用例、报错文本一致，才可判定为存量
- 最终报告中每个红都标注口径来源与归因证据

## Counterexamples
- 仓库没有可发现的 gate/CI 定义（无 ci_gate.sh、无 CI 配置）——裸工具输出就是唯一口径，不必先找脚本
- 验证目标是局部性质（某函数/文件能否编译、单个测试是否过）而非『整树过杆』——裸 pyright/ruff/pytest 恰是正确通道
- 失败报错已显式命名仅存在于其中一侧的文件/符号（如 import 仅 main 才有的模块）——报错文本自身已完成归因，基线复现收益趋零
- 门禁脚本本身正是本轮要修改的对象——其口径不是稳定权威，应按新定义验证
