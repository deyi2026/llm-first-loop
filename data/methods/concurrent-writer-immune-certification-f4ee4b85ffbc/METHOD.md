---
method_id: concurrent-writer-immune-certification-f4ee4b85ffbc
name: concurrent-writer-immune-certification
description: 共享工作区有并发会话持续写文件、而审查/准入闸用『现场重算的产物指纹』绑定时，重审-重推会陷入漂移竞速。方法：读闸自身源码找材料构成判别式（本例 include_worktree 仅当 push_head 为 None 或 ==HEAD），据此改选一种让被审材料恰等于不可变目标集合的操作形态（本地标记空提交使 HEAD≠push_head、按 SHA refspec 推送），用故意变异探针验证指纹免疫后再送审，且执行形态与送审形态逐字一致。适用于一切『闸绑定可变共享状态+并发写者』的认证场景。
aliases: 推送审查指纹漂移, sha对不上审查冻结值, 并发会话写文件导致推送被拦, review PASS了但绑定失败, 按提交区间送审推送, 对未跟踪文件免疫的送审
status: candidate
source_model: minimax/MiniMax-M3.1-Flash
source_episode_refs: episode:fd308b28-18c0-4929-b777-f1783be9298c:3356:8dc97fba24cffc01d27d
evidence_refs: learning:learn:02b774ecfe54
created_at: 2026-10-30T10:28:58.584218+08:00
updated_at: 2026-10-30T10:28:58.584218+08:00
---
## Trigger
审查/准入 PASS 回执需与现场重算指纹绑定，指纹覆盖共享工作区可变状态（未跟踪文件/工作树），且已知有并发会话在同一工作区写入（出现过送审后漂移、PASS 无法绑定执行，或担心下一次写入再次打破绑定）

## Discriminator
两个当时已在手的事实：(1) 指纹稳定性探针显示漂移是事件驱动的一次性偏移（连算两次一致但≠冻结值、untracked>0）——按原形态重审必然输给竞速；(2) 闸的判定源码里存在材料构成判别式（include_worktree = push_head is None or push_head == head），显式给出哪种操作形态不含可变工作树

## Short path
- 指纹稳定性探针：同形态连算两次 sha+清点 untracked，判定漂移是持续还是事件驱动
- 读闸源码定位材料构成判别式，确认存在一种操作形态使被审材料只含不可变提交区间
- 构造该形态：本地标记分支+空提交使 HEAD≠push_head，目标动作改为按 SHA 的 refspec
- 故意变异探针验证免疫：写入再删除一个未跟踪文件，各次 sha 完全一致才继续
- 以该精确形态送审；等待期间核对共享分支新提交是否为自己已审区间的后代（不被挟带也不阻塞他人）
- PASS 且回执冻结 sha 与现算一致后，以与送审逐字相同的形态执行；执行后清理本地标记物

## Stop conditions
- 免疫探针显示指纹仍随工作区变动（判别式不成立或运行版本与源码不符）→ 放弃该形态，改为协调并发写入者或等待静默窗口，不反复重审
- 闸源码无材料构成判别式（无条件绑定 HEAD+工作树）→ 本方法不适用
- 执行回执成功且远端目标引用==冻结的 push_src、他人新提交未被挟带 → 停止并清理标记，不再追加确认轮

## Verification
- 准入回执冻结 fingerprint == 执行前现场重算值 == 免疫探针全程观测值
- 实际执行的动作串/refspec 与送审动作逐字一致（形态漂移即须重新送审）
- 推后核对远端目标引用==送审冻结的源提交；共享分支上他人提交为已审区间后代、可自行快进

## Counterexamples
- 独占仓库、无并发写入者：漂移不会发生，标记空提交+refspec 是纯开销，直接 HEAD 推送+一次审查即可
- 闸无条件把指纹绑定到 HEAD+工作树、源码没有可切换的材料形态：改操作形态无效，只能协调写者/串行化/等待静默窗口
- 服务端拒绝非 HEAD refspec（钩子强制从当前分支 fast-forward），或需要上传的就是未提交的工作树内容：本形态不可用
