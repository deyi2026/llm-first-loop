---
method_id: reattribute-timeout-from-failure-record-then-reprobe-blocker-1ddb093d286c
name: reattribute-timeout-from-failure-record-then-reprobe-blocker
description: 重试一个此前以超时/忙碌类失败告终的受管控制动作（重启/部署/队列类）时，不要沿用上一轮对话里的口头归因直接重发。先用一次权威失败记录读取拿到字面 gate 名与阻塞物计数（哪一阶段、什么在忙），把 gate 名对齐当前源码状态词汇以修正归因，再用该 gate 的同一原语探测阻塞物现值，据此预测本次是否会复发，然后才重发并交接验收。受理后不再探索启动器参数或仓库里目标不符的手工重启脚本。硬校验类错误（绑定/CAS）不适用，走对应修复路径。
aliases: 重试前先查上次到底卡在哪一阶段, 上次超时的真实原因, 失败台账对账后再重发, 重发重启单前数一下锁还剩几把, 别信上一轮的失败解释
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:cf1db8d6-5f5a-449e-9226-c1bdc6b0fa97:1880:3e0bc90cbf1bb00037c2
evidence_refs: learning:learn:544a7b11046e
created_at: 2026-10-23T07:37:10.930882+08:00
updated_at: 2026-10-23T07:37:10.930882+08:00
---
## Trigger
重试一个此前以超时/忙碌类失败告终的受管控制动作，且上一轮对话或记忆中已存在对该失败原因的口头归因待检验；用户只给极简指令（如『重启X吧』）。

## Discriminator
重发前已在手的两条事实：失败记录原文显式给出超时发生的 gate 名与阻塞物计数（如 'target still busy after 900s: active run locks: 2' ⇒ 卡在第二阶段 idle 门而非 requester 门）；且该阻塞物可用 gate 使用的同一原语即时探测（active_run_locks 现值=1，仅剩本会话），复发与否当下可判。

## Short path
- 确认这是对上次失败动作的重试；第一未知量：上次到底败在哪一阶段——读权威失败记录原文（非对话记忆），取 gate 名+阻塞物字面值
- 把记录里的 gate 名与当前源码状态词汇对齐（waiting_for_idle ≠ waiting_for_requester_exit），修正上一轮归因
- 用该 gate 的同一原语探测阻塞物现值（run locks 计数），得出『本次是否复发』的可检验预测
- 经管理通道重发动作取回执（action_id/generation/状态）；若非终态，按既有 gate 语义把执行交接给本轮结束并附验收步骤
- 停止：不再展开启动器 argparse、目录枚举或与目标进程身份不符的手工重启脚本

## Stop conditions
- 失败记录 gate 名与阻塞物现值都已取得、重发已受理 → 停止探索，输出修正归因+复发预测+下轮验收项
- 记录显示硬校验错误（绑定/CAS/pin 过期）而非忙碌超时 → 转入对应修复路径（如先 publish 新代），不再探测忙碌度
- 阻塞物无法从当前位置用同一原语探测 → 直接重发，交给 gate 本身裁决，不为代理指标消耗调用

## Verification
- 重试后实际穿越的阶段/终态与预测一致；若再次超时且阶段不同，说明归因仍错，回失败记录重读
- 阻塞物探测使用与 gate 相同的原语/数据源（同一函数或同一锁目录），而非代理指标
- 向用户复述的失败原因与失败记录原文逐字一致，不再沿用旧对话口径

## Counterexamples
- 上次失败是 CAS/绑定校验硬错误：重发必再被拒，探测锁数毫无信息量，应先解决 pin/desired 绑定
- 首次尝试、无历史失败记录：没有可再归因的对象，直接走正常提交路径
- 失败记录的状态词汇已被后续 schema 改名，字面 gate 名不再映射当前代码：须先从源码重推语义，而非按旧记录直译
- 阻塞物即本会话自身且按设计在回合结束自动释放：探测仍有用，但预测应是『必然自动清空』，不需要为消它做任何额外动作
