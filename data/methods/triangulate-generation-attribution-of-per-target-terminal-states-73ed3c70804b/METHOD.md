---
method_id: triangulate-generation-attribution-of-per-target-terminal-states-73ed3c70804b
name: triangulate-generation-attribution-of-per-target-terminal-states
description: 控制面/编排工具的 status 回执常按目标列出 succeeded/failed 等终态，却不带代际或时间戳归属。不要把它读作『当前 desired 代的动作结果』。用当时已有的物理事实做归属三角定位：目标进程实际启动时间、兄弟目标的动作时间窗、告警里的 stable 时间戳。若目标进程启动时间落在旧代窗口而兄弟落在当前代窗口，则该 succeeded 极可能是旧代动作的遗留终态；此时候选只剩『上游从未下发动作』与『下发但被误验证』两支，用一次针对动作时间戳的定向查询（event_stream/动作详情）区分，而不是重读同一份回执或直接采信某个下游机制假设（如验证层失明）。据此再选修复面：漏发→权威入口补发并绑代际 CAS；误验证→先修验证层。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:152a76d5-3fea-40cf-8a6d-00de8ac369c2:72:d79745ea05b694e2a4c7
evidence_refs: learning:learn:198960d082a8
created_at: 2026-09-24T06:57:17.954983+00:00
updated_at: 2026-09-24T06:57:17.954983+00:00
---
## Trigger
status/编排回执按目标列出 per-target 终态（succeeded/failed 等），且输出中该终态不带 generation/时间戳归属；同时存在告警或物理事实（进程 pid/启动时间、git head、stable 代号）与该终态的表面含义矛盾。

## Discriminator
目标进程实际启动时间（ps STARTED）是否落在当前 desired 代的动作时间窗内：若它与旧代 stable/告警时间戳吻合，而兄弟目标进程启动时间落在新代窗口，则该 per-target succeeded 是旧代遗留终态的概率极高；剩余未知量收缩为唯一一个——『当前代是否给该目标下发过任何 action』，可由一次动作 id/时间戳查询闭合，无需宽枚举或重读回执。

## Short path
- 先记录事实：回执的 per-target 终态缺失代际归属，暂不把它解读为当前代结果
- 用 ps 取各目标进程 pid/启动时间/git head，与告警 stable 时间戳、兄弟目标动作窗对齐，判定该终态的时间归属
- 若归属仍二义（漏发 vs 误验证）：一次定向查询该目标在当前代窗口内是否存在任何 action（event_stream 时间戳或动作详情），闭合归属
- 按归属结论选动作面：上游漏发→走权威控制入口补发并绑 expected_generation CAS；误验证→先查验证探针再动手
- 异步动作受理≠完成：终态以工具 status + 独立 ps + head 三方一致为准，逐项对账告警症状后停止

## Stop conditions
- 已用动作时间戳确认该目标在当前 desired 代内是否有 action，终态归属歧义消除
- 物理事实（pid、启动时间、git head、stable 代）与工具 verify 字段三方一致，且告警的每个症状逐项清零

## Verification
- 把回执中的 per-target succeeded 与其动作 id 的事件时间戳/所属代交叉核对（event_stream 或 action 详情），确认归属而非仅看终态字样
- 用独立 ps 复核新进程 pid、启动时间、运行代码 head 是否与工具回执的 verify 字段一致

## Counterexamples
- 回执的 per-target 终态本身带显式 generation/时间戳字段：直接读归属即可，无需三角定位
- 进程启动时间落在新代窗口但运行旧代码（code_root/symlink 未更新或启动脚本加载旧树）：启动时间三角会错误排除上游问题，必须核对 head/version 而非只看时间
- 单目标系统无兄弟时间窗可比，或告警与 ps 时间基不一致（时钟偏移）：跳过三角，直接按动作 id 查时间戳归属
