# S0 Harness 独立审查（run_s0.py，只读）· 2026-10-19

范围：run_s0.py（360 行，sha256=e8e50ec0…，与 GATE-AMENDMENT-v2.md 绑定一致）及其依赖 build_pool_p28.py CHECKS/run_checks（39-121 行）、agent_harness.py SOLVER_RULES/MODEL/LOCK（55-131 行）、GATE-AMENDMENT-v2.md。calls.jsonl 只做聚合：205 行（ok=204/fail=1），ok 行零重复 key，prompt_version 全 p2，no_card:orig ok≈100:104，no_card prompt_chars 中位 763 vs orig 2456，card_sha256 仅 orig 臂有值。方法论检索：search_records 工具不可用，N/A。

## VERDICT: PASS（P0=0）

1) 配对与 D/R：dedupe 同 key 留最早 ok（run_s0.py:263-273）；非 ok 行剔除（:212-213）；case_pass=非 None 检查严格 AND（:215-217）；void 仅空文本（build_pool_p28.py:100-102）→ 4 check 全 None → passes 空 → case_pass=False，void 不可能计为 pass；v1.1-1.3 void 早退保 None（run_s0.py:67-68,89-90,116-117）。缺臂对剔除（:236）；D/R 对称定义（:237-238）。
2) prompt 对称性：卡只在 orig 臂注入（:143-147,188），no_card 为"本次不提供方法卡。"，无卡内容泄漏；receipt 夹具两臂逐字相同（:52-56），question/host 同源；SOLVER_RULES（agent_harness.py:112-113）与 PROMPT_TMPL 均无"回复A/B/C"类标记，no_card 臂 c2 无 prompt 侧放水；PROMPT_VERSION=p2（:38,198）与 card_sha256（:199）已记录。c2 泄漏结论：无泄漏；v1.0 c2 漏检"回复A"属检测器缺陷，由修正案 D1 处理。
3) grader：v1.0≡B.run_checks（:61-62），builder sha256=a4c1ff50… 与 FREEZE 一致=冻结版。v1.1 OPT_LABEL_V11（:41）会把普通有序列表"1./一./a)"计为选项（对称、压 D）；v1.2 c2 尾 300 窗内 URL"?"可假阳（:91-93），c4 C4_V12（:77,94-100）"已上线/已注册"可误击站点描述、且丢 v1.0 的"已写入/已读完整篇"（对称、压 D）；v1.3 C2_V13（:104,118-121）"告诉我"、"按+数字"假阳（对称、压 D），"回复A"类为 orig 倾向但被旧版 D≥R 方向一致性约束。均不构成 D 虚增到 ≥30 的通路（loosening 主向是压 D）。
4) 并发/落盘：append 在 threading.Lock 下单进程安全（:169-174；agent_harness.py:65）；跨进程不安全；done_keys 只认 ok（:177-181），fail 重跑自动补。当前唯一 fail s0|orig_card|P28-002|r1（4 次超时）→ 该对剔除、paired≤119，非标签偏倚。
5) 本轮可用性：机制层面 D/R 估计可信 YES；终值须等进程 78271 完成（205/240 行进中）并补跑 P28-002 orig；无需作废重跑。冻结时点 v1.0 D=4<R=21（GATE §2 引），若终值保持则落"mixed"标签，属结果非缺陷。
6) 修正案区分：gate_both（:279,316）=旧口径四版合取并列报告；修正案主判据（v1.3 D≥30 + 旧版 D≥R）需由 D_case_level/R_case_level 现算，脚本不打印"S0 PASS"类标签，无误报 PASS 歧义；报告必须按修正案 §2 标签并附旧口径。

## P1（不阻塞本轮 D/R）
- run_s0.py:303,351 逐行 json.loads 无坏行护栏，一行损坏即崩 summary。
- agent_harness.py:65 锁仅线程级：78271 存活期启动第二实例会交错写/重复跑，须操作纪律保证。
- run_s0.py:41 v1.1 c3 普通有序列表误计为选项。
- run_s0.py:77 v1.2 c4 站点描述误击（"已上线/已注册"）且漏"已写入/已读完整篇"。
- run_s0.py:104 v1.3 c2 "告诉我"假阳、问号匹配 URL"?"（含 v1.0，build_pool_p28.py:48）。
- s0|orig_card|P28-002|r1 超时未补：进程退出后重跑 run_s0 即自动补齐。

## ROUND USABLE: YES（终值前不得引用部分结果作结论）
