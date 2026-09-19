---
method_id: control-plane-record-before-broad-probe-3fccf9490882
name: control-plane-record-before-broad-probe
description: 核实托管动作（restart/deploy/service-control）是否执行、当前 live 是什么时，先读控制面权威记录——action 状态文件与执行回执——取得精确 status/pid/port/git_head，再据此做定向存活探测；不要先跑宽模式 ps/端口扫描（输出易被截断产生假阴性，误导出“服务不在”的结论），也不要在记录与源码语义已回答问题后继续枚举次要工件（如全部陈旧锁）。宽扫描未命中目标通常是探测方式错，而非事实。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:16a8c1d8-ae5f-4244-8906-98819ee583ec:928:4aa2e8c60dac96fcd9fe
evidence_refs: learning:learn:e45a70800676
created_at: 2026-09-18T19:09:35.310604+00:00
updated_at: 2026-09-18T19:09:35.310604+00:00
---
## Trigger
需要确认一个由控制面管理的动作（重启/部署/服务切换）的执行终态与当前运行进程，或用户要求“让某动作进入执行”而需核实放行条件时

## Discriminator
存在按 action_id 命名的权威状态记录（含 status 字段，如 waiting_for_idle）与执行回执（含 pid/port/git_head）；status 直接判定“已执行还是等待”，回执 pid 是存活探测的精确参数。宽 ps 被 head 截断且未命中目标进程，本身即提示应改查权威记录，而非换参数重扫环境

## Short path
- 读部署/动作的权威记录（CAS 部署回执或 action 状态文件）→ 解答“该动作是否已确认/执行到哪一步”
- status 为等待类状态（如 waiting_for_idle）即知未执行，不应期待新进程出现，转而解释等待条件
- 读最近一次执行回执 → 取得当前 live 进程的 pid/port/git_head
- 用回执中的精确标识做定向探测（按 pid/解释器绝对路径/端口）→ 解答“当前服务是否健在”
- 需放行语义时 grep 控制面源码中该状态的超时/fail-closed 定义 → 解答“本会话退出后能否自动放行”
- 终态、live 进程、放行条件三项事实齐备即停止并主动收尾（让 idle 窗口打开），不做后置充分性枚举

## Stop conditions
- 动作终态、当前 live 进程、放行条件均已由权威记录与源码语义确认
- 定向探测命中的 pid/端口与回执一致
- 确认等待卡点是自己所在会话（活动 run）后，立即结束而不再产生任何新调用

## Verification
- 状态文件 status、回执 git_head/pid、部署记录 generation 三者相互一致
- 定向 ps/lsof 结果与回执 pid/port 一一对应
- 若 status=waiting 且唯一活动 run 是本会话，结论应为“退出即放行”，而非继续环境探测

## Counterexamples
- 无控制面记录的手工/一次性脚本进程：只能环境探测，记录优先不适用
- 问题恰关于记录覆盖不到的对象（孤儿进程、端口占用者、资源占用）：必须环境扫描
- 记录可能过期不可信（回执落盘后进程又崩溃）：记录仅提供候选 pid，仍需活探测交叉验证
- 控制面 schema 未知或已改版：应先花一次调用确认记录结构，否则会读错字段得出假结论
