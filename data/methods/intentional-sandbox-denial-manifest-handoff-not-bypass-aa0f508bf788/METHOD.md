---
method_id: intentional-sandbox-denial-manifest-handoff-not-bypass-aa0f508bf788
name: intentional-sandbox-denial-manifest-handoff-not-bypass
description: 变更型 git/写操作被环境边界拒绝、且协调指令明确声明这是有意保留的安全边界、将由另一权限主体经独立已授权通道接管被阻断操作时，即使方法库里有重锚主仓根、换场地、workdir 重定址等可行技巧也一律不部署。交付物从『完成变更』切换为『原样保留未提交状态＋精确交接清单』：逐文件变更与行数、staged/未staged 混合 index 现状如实披露、测试/lint/diff --check 结果、本机无法验证的范围如实声明并建议接管方复跑，然后停止。
aliases: commit被沙箱拦下且父侧接管时怎么收尾, 边界是有意的不许绕过时交什么, 留给上级提交的未提交变更交接清单, 对方说权限主体不同别当自己被授权, 被点名禁止绕沙箱后的正确停点, 沙箱拒绝改交接模式不打重锚
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:ee5a281a-1ecd-46c0-a2e5-22d79041772d:147:b0b188d53558f0d78733
evidence_refs: learning:learn:c6efe21071bc
created_at: 2026-11-14T15:27:43.287452+08:00
updated_at: 2026-11-14T15:27:43.287452+08:00
---
## Trigger
git commit 等变更操作被沙箱拒绝后，协调指令同时出现三类信号：①声明该拒绝是有意安全边界（『这正是需要保留的边界』）；②枚举禁止的绕过手段（EXEC_SANDBOX=none、软链、sudo、手改 gitdir、灾难令牌、扩白名单）；③点名另一权限主体将通过独立已授权通道执行被阻断的 add/commit，并重申『不同权限主体≠你的沙盒被授权』。

## Discriminator
指令文本中的边界重申＋接管通道命名本身：这条当时已知事实把候选空间从『多种已知 git 写重锚/换场技巧任选其一』一次缩成『产出交接清单并停止』。若拒绝回执旁没有这份声明，它只是普通 EPERM 故障，重锚/换场方法照常适用。

## Short path
- 逐条复述约束（不绕沙盒／保留未提交变更／输出清单后停止）确认理解，不请求扩权、不申请灾难令牌、不自行试白名单
- 只执行明确授权的剩余验证动作（diff --check、专项测试、ruff、pyright），不再触碰任何 git 写链路或重试被拒操作
- 产出交接清单：逐文件变更与行数、index 现状（哪些已 staged、哪些未 staged 及成因）、各检查器结果
- 如实声明本机不可复验的范围（如无 bwrap 的 canary 未本地复跑），基于对方环境事实＋代码构造下结论并建议接管方复跑，不用推断冒充实测
- 明示未做的禁区动作（未改 main／未 push／未发布／未重启／未绕沙盒），然后停止

## Stop conditions
- 授权清单内的验证动作全部拿到回执且 diff --check 干净
- 清单已包含 staged/未staged 状态披露与不可验证范围声明
- 已停止：不再发起任何 git 写、白名单变更或对被拒操作的重试

## Verification
- git diff --check 退出码 0，输出文件集与清单逐项一致
- git status 的 staged/未staged 划分与清单披露一致；接管方 add+commit 后的 diff 总量应等于清单合计行数
- 报告中的测试/静态检查数字逐字来自最近一次工具回执，不凭记忆改写

## Counterexamples
- 拒绝未被声明为有意边界、也无接管主体点名：这是普通 EPERM 故障，重锚主仓根/GIT_DIR、换可写场地的既有方法照常适用，不应直接放弃排障
- 协调方要求你把提交动作写成幂等脚本交其执行：交付物是脚本本身（printf 单行＋bash -n 校验），而非状态清单
- 工作树混有大量无关在途文件：先按 status --porcelain 全量清单做抢救分类，交接清单只是其经裁剪的子集
