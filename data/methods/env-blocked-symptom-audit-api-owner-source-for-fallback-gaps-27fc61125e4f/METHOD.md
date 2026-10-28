---
method_id: env-blocked-symptom-audit-api-owner-source-for-fallback-gaps-27fc61125e4f
name: env-blocked-symptom-audit-api-owner-source-for-fallback-gaps
description: 遗留问题被描述为『某浏览器/运行时 API 在当前环境挂起或被策略拒绝（autoplay、真实手势、权限弹窗），本环境无法验证，建议真机复现后再定性』时，不要把问题整体挂起到人工验证：环境不可验证≠不可诊断。先读拥有该 API 调用的模块源码，检查两个与环境无关的健壮性问题——挂起路径有无超时兜底与失败如实回调、被拒/挂起状态有无恢复尝试（如 AudioContext.resume）。缺失即定性为值得无条件修复的代码缺陷，修复与环境验证解耦推进。
aliases: 复现不了的环境问题怎么定性, 自动化环境验不了还修不修, 浏览器策略挡住的音频先修恢复路径, 挂死的媒体调用先看有没有超时, 真机验证前的代码级定性, CDP 里麦克风挂死要等真机吗
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:80f5e2cd-19c2-42bb-8bca-1c0a01cc2a48:4223:d2434114e65a53342f0a
evidence_refs: learning:learn:f54af5338ca0
created_at: 2026-10-26T19:44:12.013712+08:00
updated_at: 2026-10-26T19:44:12.013712+08:00
---
## Trigger
问题清单或上游建议把某条症状定性为『环境特例，待真机/人工手势复现后再决定是否修复』，或症状被标注『本（自动化/CDP）环境因浏览器策略无法验证』，且症状文本点名了具体运行时 API

## Discriminator
动手定位前已在手的事实：症状文本点名精确 API（getUserMedia 挂死、AudioContext autoplay/suspended），且拥有方模块经一次目录枚举即可按职责命名定位（micCapture.ts / audioPlayback.ts）。『环境能否验证』与『该 API 调用点是否存在无兜底挂起、无恢复的 suspended 路径』是两个独立未知量，后者纯读源码即可裁决，不需要先在真机复现

## Short path
- 从问题清单提取每条症状点名的 API/机制词；未知量：该调用的拥有方是谁
- 对拥有该功能的模块目录做一次有界枚举，把每个 API 症状映射到 1-2 个拥有方文件（含 wiring/入口文件，确认用户手势路径上是否有预热恢复）
- 直读拥有方源码，只问两个代码级问题：挂起路径有无超时/失败如实回调？被拒绝或挂起状态有无恢复尝试（resume）？
- 若缺失，定性为与运行环境无关的健壮性缺陷，直接进入修复流程；真机/真实手势行为验证登记为独立验收项并行保留，不阻塞合入
- 不为『证明缺陷存在』在自动化环境反复堆 workaround（合成手势、改 autoplay 策略等）

## Stop conditions
- 源码确认调用点已有完整超时兜底与恢复路径 → 定性转移回环境层，停止代码审计，转真机/环境验证
- 调用点位于无源码所有权的第三方依赖（node_modules 等）内 → 代码级修复不可行，转环境验证或上游依赖
- 症状是聚合性能数字（如延迟 50s+）而非具体命名 API 的挂起/拒绝 → 本方法不适用，转链路追踪与测量

## Verification
- 修复后源码可见：挂起路径带超时且失败如实回调；suspended 分支先尝试恢复（resume）再降级
- 真机验证项单独登记并与修复合入解耦，收口报告中修复线与验证线分别可见
- 确认修复不改变环境正常路径下的行为（纯增兜底，不改主流程）

## Counterexamples
- 源码已有超时与 resume，而 headless 环境根本没有音频输入/输出设备 → 源码审计零收获，必须环境层验证
- 症状是『连续对话 TTS 延迟退化到 50s+』这类排队/性能问题而非命名 API 挂起 → 单模块源码审计不适用，需沿 commit→submit→queue 调用链追踪
- getUserMedia 调用封装在第三方 SDK 内部、本仓库无所有权 → 只能环境验证或推动上游
