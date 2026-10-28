---
method_id: child-id-c0edbb4e93c1
name: 审查回执命名必须嵌入 child_id 防覆盖
description: 审查回执/报告文件名必须含 child_id（运行时唯一），防同名覆盖导致"上一轮审查产物不可回溯"。时间戳不够（同秒碰撞），child_id 才唯一。
status: active
source_model: glm/glm-5.3
source_episode_refs: episode:35effbfe-0312-45d2-a1bd-0418c1706ecd:91:09b2dff8eb8e9c779245
freshness_refs: docs/promotion/receipts/20261018-daily18-publish.json,docs/promotion/receipts/20261018-daily18-toutiao-local.json
created_at: 2026-10-18T21:01:05.493533+08:00
updated_at: 2026-10-18T23:31:58.426641+08:00
---
## Trigger
需要 spawn 独立审查/评审子代理并让其落盘回执或报告文件（docs/promotion/receipts/ 等），且同一主题可能多轮审查。

## Discriminator
文件名仅由日期+主题构成（如 20261018-daily18-independent-review.json）而无运行时唯一 token；或两轮审查共用同一文件名。时间戳方案在同秒并发下仍可碰撞，不作为首选键。

## Short path
1) 确定回执目录；2) 文件名固定为 <date>-<topic>-<child_id>.json（child_id 即 spawn_subagent 返回的 subagent_xxx）；3) 在给子代理的任务书里显式写明该完整路径，不留给子代理自选；4) 落盘前 ls 确认路径不与既有文件冲突。

## Stop conditions
子代理无写盘能力（required_tools=[] 只回文本）或一次性草稿不需要回溯时，不适用本方法，按原流程。

## Verification
当前性验证：ls docs/promotion/receipts/ ——历史反例（不含 child_id 的同名族）仍在；采用本方法后新回执应匹配 *-subagent_*.json 且同主题两轮审查文件名不同。

## Counterexamples
2026-10-18 第 18 期发布复盘：第二个审查子代理沿用了第一个的回执路径，直接覆盖了第一份审查报告，第一份 PASS 覆盖的确切产物事后不可回溯。
