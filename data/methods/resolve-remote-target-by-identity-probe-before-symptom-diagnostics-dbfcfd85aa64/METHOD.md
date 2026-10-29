---
method_id: resolve-remote-target-by-identity-probe-before-symptom-diagnostics-dbfcfd85aa64
name: resolve-remote-target-by-identity-probe-before-symptom-diagnostics
description: 用户报告的症状发生在另一台机器上（如『linux输入法切换不了』而本机回执全是 macOS sandbox-exec）时，把『哪台机器、怎么连』当作必须最先解决的未知量：用回执平台注记判定目标非本机（不花调用再探测本地 OS），用记忆/经验记录中的主机身份（发行版+用户+场景）作匹配键，用 ssh config+known_hosts 圈出少量候选，再用一次 BatchMode 短超时连接读取 os-release/whoami 与记忆身份对齐，命中者即权威目标。身份匹配是裁决者，连通超时只在另有身份命中者时才用于排除。目标钉死后才开始症状级只读诊断；机制验证健康则按用户可观察症状分支收尾，不盲查。
aliases: 用户说的linux不是这台电脑, 那台deepin机器怎么连上去, 先找到出问题的远程机器再诊断, ssh候选IP挑出目标, 问用户要IP还是自己找主机
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:c7e4e166-3401-45cd-9402-77e522055d10:1112:4448c73075119f2cd3d9
evidence_refs: learning:learn:4b28c1374fc8
created_at: 2026-10-29T10:10:52.038247+08:00
updated_at: 2026-10-29T10:10:52.038247+08:00
---
## Trigger
用户症状指向一台非当前操作环境的机器（本机工具回执的平台注记已证明本机不是目标平台），且记忆或 SSH 元数据中存在候选主机线索（近期远程操作经验、known_hosts、ssh config include）

## Discriminator
三条当时已在手的事实可把『哪台机器』缩到一两个可一次探测的候选：(1) 每条工具回执的平台注记（macOS sandbox-exec）已证明本机不是那台 Linux，无需再探测本地 OS；(2) 记忆命中行已给出目标主机身份键（局域网 Linux 主机 Deepin 25、具体场景），全量水合该记录不会增加地址信息；(3) ~/.ssh/config 与 known_hosts 仅列出极少量候选地址

## Short path
- 读现有回执的平台注记判定目标不在本机，不再消耗调用探测本地 OS 或全量水合与地址无关的记忆记录
- 检索记忆中与目标机器相关的记录，只提取主机身份键：发行版/用户名/hostname/近期场景
- 读 ~/.ssh/config（含 include 的别名）与 known_hosts，圈出全部候选地址（含超时不可达者）
- 对每个候选做一次 BatchMode 短超时 SSH，连通即读 os-release/whoami/hostname 与记忆身份对齐；身份命中者为权威目标，超时候选仅在已另有身份命中者时排除
- 只对命中主机做只读症状诊断（进程/环境/配置/机制级验证）；机制层验证健康后停止盲查，转为按用户可观察症状（全局热键/单应用/引擎输出）分支并附已验证的保底手段

## Stop conditions
- 身份对齐的唯一候选已连通且只读诊断完成，症状已收敛到需用户提供的可观察现象（按了什么键、哪个应用、什么表现）
- 候选间身份无法区分（多台同发行版同用户、或全部不可达）→ 停止逐个探测，直接向用户要目标地址或症状描述

## Verification
- SSH 回读的 os-release/用户名/hostname 与记忆记录中的主机身份逐项一致（本例 Deepin 25 / yyj）
- 每个被排除候选的排除依据明确（超时且另有身份命中者 / 身份不符），而非以『先连上的那台』为准
- 症状级结论（如 dbus 切换成功、当前输入法）来自对命中主机的直接回读，而非本机或记忆推断

## Counterexamples
- 本机回执显示本机就是目标平台（agent 就跑在那台 Linux 上）→ 跳过主机解析，直接本地诊断
- known_hosts 大量陈旧 IP 且记忆中无主机身份键 → 身份探测无裁决力，应直接问用户而不是逐台探测
- 多台可达主机身份相同（同为 Deepin 25 同用户名）→ 不能以连接顺序裁决，须用 hostname 等更强区分键或问用户
- 目标在跳板机之后或仅用户本人环境可达 → 本机探测不可达不等于不是目标，连通性证据此时没有裁决力，应改问用户
