---
method_id: subagent-three-layer-diagnose-and-spawn-playbook-87273b2b3118
name: subagent-three-layer-diagnose-and-spawn-playbook
description: 子代理工具调不动/绕弯/token浪费时的诊断与预防：三层定位+spawn铁律+byte-exact任务书+止损规则+等待纪律。机制锚见 docs/PLAYBOOK-20261014-subagent-capability.md（其"三层机制速查"=①工具面②能力声明③执行权，与本卡三层诊断同构；该文覆盖三层机制与 spawn 配置纪律，不覆盖本卡的分诊映射/止损规则/byte-exact 任务书/等待纪律）
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:10512259-8254-4f0b-afcd-84e2484e4bfc:0:1d64e4e4a9fbaeb8f01d
freshness_refs: evidence://v1/5e7b4d8fca6cf18798a05ab796bf4c342d6c95c9bbcc41bfbdfd1d12c0becb24,docs/PLAYBOOK-20261014-subagent-capability.md
created_at: 2026-10-25T23:01:13.307425+08:00
updated_at: 2026-10-30T14:14:50.671046+08:00
---
诊断决策树（工具调不动时按层定位）：
1) 拒绝文案含"白名单/声明外" → 工具面：requires.tools 没列全，父重派列全（child 内无法自救）
2) spawn 直接拒绝+能力矩阵提示 → 能力层：补 network/fs/session_continuity 声明
3) "run lease fenced / effect authority 丢失" → 执行权：lease 断由父接管；白名单已含 execute_command 仍全拒则疑平台 bug，发最小探针（task=跑 pwd 原文回报）确认，勿反复重派
4) 止损：同类失败 2 次必停手换路（dsh_task 同步通道/父自己做）
spawn 铁律：tools 要么省略键、要么列全，绝不传 []（键存在即截断到空集，child 锁死）；能力按需显式声明（缺口启动前 fail-fast）；model 带 provider 前缀。
任务书：父先取证，编辑写成 byte-exact old/new，agent 机械执行+验收；开放探索任务缩小范围或分批；必给 acceptance 自检清单；context 只传必要背景不传密钥。
等待纪律：subagent_result(wait_seconds=30) 贴上限阻塞等待+窗口内做父侧准备；禁零等待自旋、禁翻父流找子进度；父回合结束→child cancelled_on_model_final，等 child 别结束回合；等待型任务改 spawn-per-turn（child 无 sleep 原语）。
适用边界：父 run 活跃期间；能力面结论有时效（2026-10-25 实测 execute_command 可用，围栏 bug 47773fff5 已修复），怀疑平台问题先最小探针再下结论。
