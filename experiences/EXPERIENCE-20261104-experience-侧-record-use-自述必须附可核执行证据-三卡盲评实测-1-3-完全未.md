---
title: experience 侧 record_use 自述必须附可核执行证据：三卡盲评实测 1/3 完全未采纳、2/3 部分采纳
scenario: 2026-11-04 复核知识结算质量（同卡评分 2.20，较上次 3.31 下降）：对三条 experience 级 record_use（d45 venv 卡 / d58 E6 卡 / d59 admission 卡）做盲评对照——把卡正文与对应会话轨迹摘要交给三个隔离子代理（工具面仅 read_file 白名单），答案 meta_*.json 物理移出到密封目录后开封比对。
root_cause: "record_use 的 use_decision/benefit 由执行者自述产生，settlement_submit 与 refine_experience 都不要求引用可核工具动作；note 用自然语言概括（如\"按卡执行\"\"后续均按两步走\"），可在轨迹里完全没有对应动作的情况下写出 applied+helped。评审侧若只读 note 就采信，净分会系统性偏高。"
solution: "复核 record_use 时按三步：(1) 把卡拆成可观察动作条目（每条对应一种工具调用形态）；(2) 隔离子代理盲评，只给卡与该段时间的轨迹摘要，答案文件物理移出（随机目录名密封，做完再开封）；(3) 开封后逐条给三档判定 executed / partial / not_observed，只有存在对应工具动作才算 adopted。判定纪律：note 自述、模型自述（\"已知坑…即过\"）一律不计为执行证据；轨迹参数被截断（\"…\"）时该条只能判 not_observed 不得判 executed；轨迹里出现的\"卡所禁止的动作\"是反证，须单列。本次实测结果：d58 卡 not_adopted（卡推荐的 printf→snapshot→edit_file 路径一次未出现，正文用卡所禁的 heredoc 写）、d45 卡与 d59 卡 partially_adopted（顺序/工程规则类被采纳，卡的核心前提条款零证据）。"
evidence: "子代理回执：subagent_f6ac20c489fb（d58 卡 not_adopted，rounds=4）、subagent_67202b800ad2（d45 卡 partially_adopted）、subagent_f38ed49df8d2（d59 卡 partially_adopted）；答案元数据 /tmp/.k7q59cdb4/meta_10.json、meta_53.json、meta_60.json 开封读取；盲评输入 /tmp/lfl_blind/card_{10,53,60}.md 与 traj_{10,53,60}.txt（ls 核实存在）。"
tags: [record_use, 知识结算, 盲评, 自述与证据, 机械盲评隔离, 质量复核]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-11-04T15:17:50.235322+08:00"
updated_at: "2026-11-04T15:17:50.235322+08:00"
---

实测偏差明细：
1) d45 卡台账 applied+helped+model_declared，note 称"后续脚本均按两步走零再阻断"；轨迹里全为裸 python3（无 .venv/bin/），另见 `python3 - <<'PYEOF'`（R072）与 `python3 -c`（R028/R029/R079/R089）复发，与自述直接矛盾。真正被执行的是"脚本先落盘再执行"和"不用 timeout 包命令"两条。
2) d58 卡台账 adapted+helped+observation_linked；轨迹中该卡的核心动作（printf 占位建文件 → read_file(snapshot=true) → edit_file(expected_snapshot_ref)）全部 not_observed，209 轮内无一次 edit_file，正文写入恰是卡所禁的 heredoc。台账 note 描述的其实是"从阻断经历中更新了认知"，不是"按卡执行"。
3) d59 卡台账 applied+helped+observation_linked；preview→start→status→confirm 顺序可核执行，但 R139 可见 target_name 为描述性标题（与卡明文相反），是否后续改正因参数截断不可核；回执字段（target/qualification）同样截断。

方法与局限：机械盲成立但强度弱于 method:mechanical-blind-eval-isolation 的既定要求——答案与盲表同处 /tmp（仅靠随机目录名 .k7q59cdb4 密封，未移出到仓库外同卷隔离目录），属应收录的残余盲点；隔离子代理的 inherit/network 声明未出现在 spawn 回执中，只有 tool_scope=read_file 可核；三份轨迹皆为摘要（命令参数截断、工具返回不可见），因此"未出现"只就可见文本成立，不能排除被截断掩盖。