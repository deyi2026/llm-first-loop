---
title: 压缩摘要待核信号双失真：前提不存在+数字无出处，溯源后关闭而非执行
scenario: "会话压缩摘要列出两个\"未解决信号\"：①param_adjust 09-18 unbounded→40 需绑 promotion 回写规则#8；②计算记录 137 vs 2461 差异待核（回填时刻 08:41+08:00）。用户确认\"先溯源、溯源失败则关闭\"的处理方案后执行。"
root_cause: 压缩摘要生成时引入了无法溯源的条目：一条记录（09-18 param_adjust）在持久层不存在，一对数字（137/2461）在任何持久层均无出处，且摘要引用的载体文件 context.md 本身不存在。摘要被误当作事实源时，会诱发对不存在前提的回写动作或对无出处数字的持续追踪。
solution: "五路溯源后再动作：search_records（param_adjust 全量、change_log、memory 两个数字）+ event_stream（workspace 全窗、修正时区）+ search_archive + search_files 内容搜索 + 文件名定位。信号2 因前提不存在证伪关闭（无需回写，相关原则 RULE-AI-08 现文已含）；信号B 因两侧数字均无出处，结论定为\"差异无法证实为真实风险\"并降级关闭；发现无可编辑载体时改用持久 lesson 闭环，不新建文件制造悬空引用。"
evidence: "search_records(param_adjust)=4条无09-18记录；search_records(change_log,\"promotion\")=零命中；search_records(memory,\"2461\")=仅src 32461行子串；search_records(memory,\"137\")=2条均无关；event_stream(workspace,\"回填\")=仅09-02 EVO-251f059a+本会话调用；search_archive(\"2461/137 计算记录\")=零命中；search_files(\"137 条\")=零命中；search_files(content=2461)=仅无关子串；search_files(context.md)=无匹配"
tags: [context-compression, 溯源, 信号闭环, evidence-discipline, 声明回执]
source: {}
status: active
record_kind: lesson
verification_state: verified
created_at: "2026-09-19T10:46:47.544592+08:00"
updated_at: "2026-09-19T10:46:47.544592+08:00"
---

2026-09-19 接手会话压缩摘要中两个"未解决信号"，执行前溯源，双双失真：

【信号2：param_adjust 绑 promotion 需回写规则#8】证伪关闭。param_adjust 全量仅 4 条（08-22 precheck_enabled、08-24 max_iterations 30 30、09-08/09-09 timeout_s 600 600），无摘要所称 09-18 "unbounded→40" 记录；change_log 查 "promotion" 零命中；所谓"规则#8"实为 RULE-AI-08（观察—判断—行动闭环），其现文本已写明"查到异常指标≠必须调参数"。无需任何回写动作。

【信号B：计算记录 137 vs 2461】无法溯源，按"差异无法证实为真实风险"降级关闭。四层核查：①记忆库 "2461" 唯一命中为 2026-08-15 基线 "src 32461 行"（纯子串）；"137" 命中 2 条（注入块统计、缓存增量命中率 137-352%）均无关；②event_stream scope=workspace 查"回填"，命中全部为 09-02 EVO-251f059a 存量回填及本会话查询调用，摘要所称 09-19 08:41+08:00（00:41 UTC）回填事件不存在（修正时区后覆盖到当前时刻仍无）；③归档 Evidence "2461/137 计算记录" 零命中；④工作区内容搜索 "137 条" 零命中、"2461" 仅锁文件哈希/event_id 无关子串。

【元教训】压缩摘要中的待核信号、数字、记录乃至被引用的载体文件名（本例 context.md 实际不存在）都不能当事实源；摘要只是索引。接手悬置项第一步是溯源，溯源失败的正确结论是"关闭并记录无法证实"，而不是让两个来源不明的数字继续互相对质、或为一个不存在的前提制造回写动作。无可编辑落盘载体时，以本 lesson 为持久闭环记录。