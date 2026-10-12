---
title: 账本驱动例行 prune：命中≥3 且 0 applied 或连续 rejected≥2 → archive 并留痕（首轮 2026-10-10 空集）
scenario: method/experience 库累积 739+359 张卡，其中 method 侧 706 张 candidate 从未 qualification、绝大多数从未被使用；库增长无反向修剪通道，检索面信噪比随存量单调下降。
root_cause: 知识库只增不减导致 complexity 累积；usage ledger 已被监控（usage_ledger_lost=0）但从未作为修剪决策输入；RRSI 对照确认 prune 机制缺失是三类过拟合中唯一无等价物的一项。
solution: 例行维护轮（建议月度）跑账本筛查：某 method 在 usage.jsonl 被记录命中≥3 次而 0 次 applied，或连续≥2 次 rejected → method_manage transition=hold/invalidate 并留痕；experience 侧等账本补齐后同理（refine_experience archive）。archive 必须留 note 说明数据依据，可回滚。
evidence: "data/methods/usage.jsonl（2026-10-10 读全文 7 条：method_ref 均为 method:，decision=applied×6/adapted×1，0 rejected）；data/methods/.usage_watermark.json count=7；event_stream(scope=workspace) 查询 search_records kind=experience 无结构化命中账本。"
tags: [prune, usage-ledger, maintenance, complexity-control, knowledge-hygiene]
source: {}
status: active
record_kind: lesson
verification_state: unverified
created_at: "2026-10-10T08:49:42.804748+08:00"
updated_at: "2026-10-10T08:49:42.804748+08:00"
---

首轮执行记录（2026-10-10）：method 侧 usage.jsonl 7 条全为 applied/adapted、0 rejected、8 张卡有 usage，规则命中集为空，无修剪动作（如实记录，不为凑数而 archive）。experiences 侧无 usage/检索命中账本（event_stream 仅存 action_trace 决策片段，无命中日志），规则对该侧暂不可执行——已知 gap，若要补齐需另行演进提案（本卡不夹带该变量）。适用边界：仅用于例行维护轮，不做实时自动 archive；archive 决策仍需模型判读账本后逐张执行，防止误杀低频高价值卡。反例防线：命中≥3 的卡若 note 显示"检索后判断不适用但卡本身针对别的场景有效"，不应 archive，应降级为"按需 exact-ref"。当前性验证：跑 python3 -c "import json; rows=[json.loads(l) for l in open('data/methods/usage.jsonl')]; print('rejected=',sum(1 for r in rows if r.get('decision')=='rejected'), 'total=',len(rows))" 应得 rejected=0 total=7；rejected>0 或 total 显著增长时重跑规则筛查。