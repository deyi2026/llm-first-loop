---
method_id: verify-grant-per-surface-real-probes-then-audit-residual-flag-c098dbce83f2
name: verify-grant-per-surface-real-probes-then-audit-residual-flag
description: 用户宣布权限已授权并要求确认时，裁决依据是责任进程自己的真实调用结果而非布尔信任位（该位在责任进程模型下已知假阴/假阳双向失真）。按授权声称覆盖的能力面逐面做最小真实探测：读面用跨应用 snapshot、操作面用 dry_run 验证寻址与门控而不产生注入副作用、并核对 pid 判断是否即时生效（未变即撤销『需重启』建议）。真实调用全部成功而信任位仍为 false 时，用该位对应的精确 API 名在责任仓库做一次精确检索找记录在案的反例，把反常分类为已知问题而非新故障。汇报逐面标注已验证/未验证，dry_run 不等于真实注入，未测面交用户裁决。
aliases: 授权好了怎么确认真的生效了, ax_trusted 还是 false 但调用成功, 怎么验证辅助功能授权已生效, 标志位说没权限实际能用信哪个, 授权后要不要重启进程才生效, dry_run 点击算验证过操作权限吗
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:80a9ad77-9a07-4f8b-9da4-49adb180bd96:1455:7a5d915356436ba1269a
evidence_refs: learning:learn:79bc1159ff14
created_at: 2026-11-04T15:43:48.079130+08:00
updated_at: 2026-11-04T15:43:48.079130+08:00
---
## Trigger
用户/上游宣布某项权限或授权已补齐并要求确认（如『已经授权了，你看一下』），需要判定授权是否真生效、覆盖哪些能力面、还有哪些面未验证。

## Discriminator
同一权威 status 回执内的矛盾信号：能力位可用（can_read_ax/can_list_windows=true）而布尔信任位 false——该矛盾在当时即可判定信任位不能作裁决依据；叠加此前真实失败错误码（如 -25204），唯一权威是责任进程自己的真实调用回执。

## Short path
- 取一条权威 status 回执：列出授权声称覆盖的能力面（读 AX、操作寻址/注入、捕获）与进程 pid，作为验证清单。
- 读面：对已知窗口做真实 snapshot（最好再加一个跨应用目标），以 ok/error_code 而非信任位裁决。
- 操作面：用 dry_run（risk_class=act、签发 confirm_token）验证寻址与门控，不产生真实注入副作用。
- 若真实调用全部成功而信任位仍 false：用该位对应的精确 API 标识符在责任仓库做一次精确内容检索，找记录在案的反例注释/测试断言，把反常分类为『已知问题』或『新故障』。
- 核对 pid 前后一致且探测通过 ⇒ 授权对当前会话即时生效，撤销任何先前『需重启』建议。
- 汇报逐面标注已验证/未验证（dry_run≠真实注入），未测面交用户裁决而非默认全通。

## Stop conditions
- 每个声称的能力面都拿到真实回执（成功或权威错误码），且残余标志位反常已被分类为已知问题/新故障。
- 不为已成功的面追加确认性探测（一个跨应用第二样本即止）。

## Verification
- 真实调用回执 ok 且 error_code 由失败码转为 0、degraded 为空。
- 仓库检索命中可引用的记录反例（文件:行号+日期），方向与本次观察一致（假阴或假阳）。
- dry_run 回执含 confirm_token 与 risk_class=act，证明到达门控而未注入。
- pid 前后一致且能力即时可用。

## Counterexamples
- 任务是排查真实失败而非确认授权（『缺权限』前提未证伪）时，先做单点最小同类操作证伪前提，不铺全表面矩阵。
- 信任位为 true 而真实调用失败（假阳性）时，没有『残余假阴性需考古』一步，直接以错误码走故障定位（如授权方决策日志）。
- 授权只覆盖单一能力面（如仅屏幕捕获）时，一次真实捕获即止，不构造验证矩阵。
- 环境无责任仓库/文档可考时，降级为『标志位不作为依据』的一句话结论，不做宽泛考古搜索。
- 真实注入本身就是要验证的目标且用户接受副作用时，dry_run 不足，需用户明示后做一次无害真实点击收尾。
