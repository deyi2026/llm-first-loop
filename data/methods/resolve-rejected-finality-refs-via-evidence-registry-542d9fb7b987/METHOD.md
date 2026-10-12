---
method_id: resolve-rejected-finality-refs-via-evidence-registry-542d9fb7b987
name: resolve-rejected-finality-refs-via-evidence-registry
description: 终局/收口类门禁以引用格式原因（如 status=unsupported_ref）拒绝时，被拒的是引用形态而非事实本身：本会话早前已读到的工具回执（job_output、execute_command 等）已被 evidence 层自动持久化。正确恢复是把每个被拒裸标识符（job id、commit hash）映射到其来源类，用 list_evidence 按来源/时间枚举注册表解析出 evidence:// 规范引用，核对 coverage 后重试；不要用回执措辞做内容搜索找引用，更不要重跑工作或直接申请 waive。门禁引用 schema 一经确认，后续同类收口应首跳即引规范格式。
status: candidate
source_model: glm/glm-5.3
source_episode_refs: episode:ae8c5d92-6fe9-45af-bd9c-ef4912bb21e4:1397:8ebcdb1524cb02c253dd
evidence_refs: learning:learn:1f88c87ed853
created_at: 2026-10-08T10:52:33.342900+08:00
updated_at: 2026-10-08T10:52:33.342900+08:00
---
## Trigger
准备执行需要机器可验证 evidence 引用的终局/收口操作（goal complete、收官断言），或刚收到此类门禁拒绝且 reason 指向引用格式失败（unsupported_ref 类）

## Discriminator
拒绝回执的 reason_code 明确是引用格式校验失败而非事实缺失：所引事实（回归回执、commit stat）在本会话早前工具输出中已取得，且 list_evidence 显示 job_output/execute_command 等输出已自动持久化为 evidence 记录——恢复动作只需改引用解析方式，事实无需重做

## Short path
- 读门禁拒绝回执的 reason_code；若为引用格式类（unsupported_ref），判定底层事实已成立、无需重做
- 把每个被拒裸标识符（job id、commit hash）映射到其证据来源类（job_output / execute_command）
- 用 list_evidence 按来源/最近时间枚举 evidence 注册表取得 evidence:// 引用，而不是用回执措辞做内容搜索
- 核对每条引用的 source/coverage 确实覆盖对应主张（回归计数←job_output；commit stat←execute_command）
- 仅以规范 evidence:// 引用重试收口，门禁接受即停止

## Stop conditions
- 门禁接受（收口成功）
- list_evidence 无匹配记录（产物来自其他会话/已过期）→ 改为重新获取并持久化证据或走人工 waive，不盲目重试
- reason_code 显示事实性缺失而非格式问题 → 本方法不适用，先补证据再谈引用

## Verification
- 门禁接受回执
- 每条 evidence:// 的 source/coverage 与其支撑的主张一一对应
- 两次尝试之间底层事实未变（同一 job 回执、同一 commit），即只修引用未改事实

## Counterexamples
- 拒绝原因是证据不足/事实未验证而非 unsupported_ref：重排版引用无法通过，必须先取得新证据
- 目标产物产生于注册表保留范围之外（list 无记录、freshness 过期）：枚举找不到，需重跑或请求 waive
- 门禁 schema 本身声明接受裸 job:/git: 标识符时：改用 evidence:// 无增益，不应仪式化套用本方法
