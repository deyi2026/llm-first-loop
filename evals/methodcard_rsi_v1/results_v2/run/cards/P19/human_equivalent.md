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
满足以下全部三条时使用：
- 核实对象是由控制面管理的动作（重启/部署/服务切换），且有 action_id 或以 action_id 命名的状态记录可定位
- 待答问题属于三类之一：动作是否已执行/执行到哪步（对应 Short path 步骤 1）；当前 live 进程是什么（步骤 2–3）；等待类动作何时被放行（步骤 4）
- 控制面会为此类动作落盘状态文件与执行回执，或可用一次调用确认记录目录存在

出现任一情况则不使用（改走 Counterexamples 给出的替代路径）：
- 目标为手工启动或一次性脚本进程，无控制面记录
- 问题恰关于记录覆盖不到的对象（孤儿进程、未知端口占用者、资源占用）
- 记录 schema 未知或已知改版，且尚未花一次调用确认其结构

## Discriminator
- 存在按 action_id 命名的权威状态记录（含 status 字段，如 waiting_for_idle）与执行回执（含 pid/port/git_head），即可走本方法
- 判定规则：等待类 status 直接判定“未执行”，无需等待或寻找新进程；回执 pid 是存活探测的精确入参
- 反向信号：宽 ps 被 head 截断且未命中目标进程，本身即提示应改查权威记录，而非换参数重扫环境

## Short path
1. **读权威记录**：定位以 action_id 命名的状态文件（或 CAS 部署回执），读出 status 字段（如 waiting_for_idle/executed/failed）→ 解答“动作是否已确认/执行到哪一步”。若 status 为等待类，直接落结论“未执行、等待中”，跳过步骤 3，转步骤 4；不等待新进程出现。
2. **读最近一次执行回执**：提取 pid、port、git_head，并与部署记录的 generation 交叉核对，确认回执对应当前 generation 而非历史部署。
3. **定向存活探测**（只用回执给出的精确标识，禁用宽扫描）：按 pid（`ps -p <pid>`，或核对 /proc/\<pid\> 的解释器绝对路径）、按端口（`lsof -i:<port>` 或 `ss -ltnp`）。命中判据：探测到的 pid/port 与回执一致。未命中时先按“记录过期”处理（回执落盘后进程又崩溃）：以回执标识为锚补一次环境探测交叉验证；仍不命中才判定探测方式有误，不得直接得出“服务不在”，也不得改跑宽 ps 或全端口扫描。
4. **放行语义**（仅 status 为等待类时需要）：以 status 字符串本身为关键词 grep 控制面源码，读出该状态的超时与 fail-closed 定义 → 解答“本会话退出后能否自动放行”。
5. **收尾**：把三项事实——动作终态、live 进程（或等待状态）、放行条件——写入结论。若确认等待卡点是自己所在会话（活动 run），立即停止发出任何新调用，让 idle 窗口打开；不做后置枚举（陈旧锁、历史文件等次要工件）。

## Stop conditions
三项全部满足才算完成，任一未满足时不得宣布完成，也不得用宽扫描补洞：
- SC1（终态）：权威记录的 status 已读取并唯一判定“已执行/等待中”；涉及放行时，该状态在源码中的超时/fail-closed 定义也已确认
- SC2（live 进程）：定向探测命中与回执一致——pid 相同、port 由该 pid 持有，且回执 git_head/generation 对应当前部署
- SC3（放行卡点）：若 status 为等待类且唯一活动 run 是本会话，本会话已停止发出任何新调用、即将退出

## Verification
每项对应一个 Stop condition，逐条可核验：
- V1（↔SC1）：状态文件 status、回执 git_head/pid、部署记录 generation 三者相互一致，无相互矛盾的记录；引用的源码定义能在控制面源码中按 status 字符串定位到
- V2（↔SC2）：定向 ps/lsof/ss 的返回与回执 pid/port 一一对应，且不存在与回执矛盾、又无解释的额外监听者；若走的是“记录过期→补探测”路径，结论须显式写明记录与探测的交叉验证结果，而非只引其一
- V3（↔SC3）：若 status=waiting 且唯一活动 run 是本会话，最终结论呈“退出即放行”形式，会话此后无任何新调用，且过程中未执行过宽模式 ps 或全端口扫描

## Counterexamples
- 无控制面记录的手工/一次性脚本进程：只能环境探测，记录优先不适用
- 问题恰关于记录覆盖不到的对象（孤儿进程、端口占用者、资源占用）：必须环境扫描
- 记录可能过期不可信（回执落盘后进程又崩溃）：记录仅提供候选 pid，仍需活探测交叉验证，两者一致方可下结论
- 控制面 schema 未知或已改版：先花一次调用确认记录结构与字段名（status 枚举值），否则会读错字段得出假结论