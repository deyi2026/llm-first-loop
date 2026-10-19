# 独立审查：analyze_s0.py（S0 离线汇总脚本）

- 日期：2026-10-19 · 审查者：独立只读子代理 · 对象：`evals/methodcard_rsi_v1/s0_p28/analyze_s0.py`（527 行）
- 复核命令：`python3 analyze_s0.py --calls /tmp/calls_snapshot_1949.jsonl --out /tmp/t3_review.json --now 2026-10-19T19:50:00+08:00`（exit=0）
- 基准比对：/tmp/analysis_a.json 核心字段零差异；同 --now 两次运行 `cmp` 逐字节一致。

## VERDICT: PASS（无 P0；3 项 P1）

## 逐项结论（file:line 均指 analyze_s0.py）

1. **Wilson/McNemar**：`wilson_ci`（79-89）为标准 Wilson score 闭式；独立参考式 5 组全等：0/10→[0,0.277533]、15/50→[0.191036,0.437504]、0/1↔1/1 对称（0.793451/0.206549）、10/10→[0.722467,1]；n=0 记 None 不插补 [0,1]（81-83）。`mcnemar_exact_two_sided_p`（92-102）用 math.comb 精确双侧（小 p 值求和法）：(3,9)=598/4096=0.14599609375、(0,10)=2/1024 精确相等；(0,0)→None。
2. **D/R 权威来源**：头条数字全部 `dict(S.summarize_one(rows, g))`（216-229），无自算 case_pass；去重用 `S.dedupe`（208 ≡ run_s0.py:263/277）；自建 pair_map（129-133）仅用于分层/缺失列举，且有 `pairing_structure_matches_summarize_one` 交叉校验（281-282，输出 True=103 对）。
3. **两套闸门**：旧口径 `all(gate_pass_D_ge_30)`（304,315 ≡ run_s0.py:279）；新口径 v1.3 D≥30 且 v1.0/1.1/1.2 各 D≥R（308-310），与修正案 §1 逐条对应；三标签（47-49）经程序化比对**逐字**见于 GATE-AMENDMENT-v2.md §2；全文 grep 无 "S0 PASS/通过/有效" 等表外裁决语；v1.0 方向偏差按要求并列（325-326）。本快照：v1.3 D=21<30 → label=NULL，正确。
4. **c2 审计**：v1.0/v1.3 判定直接调 `S.GRADERS[...](text)[0]["c2"]`（159-160），无 bool() 包裹；`A_RE|B_RE` 模式串与 `run_s0.C2_V13`（run_s0.py:104）逐字相等且 7 条样例行为一致，运行时逐行等价校验 `split_consistent=True`；计数自洽：sum(classes)=flipped（32/42），zero_marker=stayed_false（12/33）。
5. **c3 分层**：按 `no_card` 长度分箱（232-234）与四分位（255-273，bisect_left 分配互斥完备）；各层 D/R/paired 求和=总数（四版 bin 三项 + quartiles 三项一致性标志全 True，283-298）；子集仍经 summarize_one 同源计算，自检可信。
6. **CLI/副作用**：`--calls/--out/--require-complete/--markdown/--now`（491-502）；只写 `--out`（513-515；默认 results/analysis_s0.json 为其自身输出）；不回写 calls/pool/results；`sys.dont_write_bytecode=True`（35）防 __pycache__；直接 import 仅 stdlib+run_s0（21-39），无 requests/urllib/socket；run_s0 传递依赖 agent_harness 的 urlopen 仅在函数体内、此代码路径不触及（两次离线运行秒回且逐字节一致可证）。退出码 0/2/3 符合文档。
7. **确定性**：sort_keys JSON + 注入 --now（now_injected=True）；两次运行 cmp 逐字节一致；无时间/随机/集合序泄漏。

## P1（不影响终值数字/标签，建议修）

- **P1-1** analyze_s0.py:308-310,324：paired<120（本快照 103/120）仍输出终局式冻结 label，gates 段落自身无"数据未完成"注记（仅 meta.paired/missing 与 stdout 头部提示）；建议 label 旁附 incomplete 注记或仅在 --require-complete 通过后输出。
- **P1-2** analyze_s0.py:112-133：load_calls 不校验行 schema，可解析但缺 key/instance_id/arm 的行会在 pair_map/dedupe 处 KeyError 崩溃（fail-loud，不会产出错数，但宜给结构化错误与退出码 2）。
- **P1-3** analyze_s0.py:60,175-179：c 类描述隐含"v1.0 c2=末200裸问号"；实际 v1.0 c2 还有 end_tag 分支且问号 regex 更严（build_pool_p28.py:107-109），此类 flipped 行保守落入 e_other（不致错归因），建议在 e 类 desc 注明"含 v1.0 更严问号规则之差"。

## 环境纪律
- 只读审查：未改动任何既有文件；仅新建本报告与 /tmp/t3_review*.json；未联网；未触碰进程 78271（分析用 /tmp 快照）。
- 读取量：analyze_s0.py 全文 527 行 + run_s0.py 定位段落约 140 行 + 修正案 §1-§2 18 行 ≈ 685 行（≤700）。
