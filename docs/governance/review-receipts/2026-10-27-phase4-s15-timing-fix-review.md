# Phase4 S15 时序修复独立审查回执（RULE-AI-28 代码闸）

- 日期：2026-10-27
- 审查人：独立审查 subagent（未参与该改动；仅只读 + 执行测试，未修改仓库任何文件）
- 审查子会话 id：`subagent_d8d181602b46`（父会话 `spawn_subagent` 发起，model=glm-5.3，19 rounds / 33 tools）
- 被审产物：repo HEAD=`527d2a747ea96723e77a516b6c6a389034da41af` 工作区未提交改动
  - 唯一修改文件：`tests/phase4/test_m2_inflight_interrupt.py`
  - git hash-object: `fe15f0393d33da56f01ae240fc551a60e80b9faa`（与委派一致）
  - sha256: `48d65b682d4bba8ecc8cf01a7a3b6b07c5aa57e0286e1c02039ff02e513aabda`（与委派一致）
- 结论：**PASS**

## 改动内容
`test_c_s15_race_two_branches` 分支 B：`tool_sleep` 1.5→2.0（`inject_delay=1.25` 不变）+ 注释更新。
A 支（1.45/1.55）与 `_race_sample` 默认值未动。diff 共 6 行（4+/2−），无产品代码/配置/marker 改动。

## 根因判定（独立推导）
分段等待 τ=0.2s（`registry._INTERRUPT_WAIT_SLICE_S`），判定片位于进程 spawn 后标称
1.4/1.6/1.8s；打断成立 ⟺ 注入落点早于某个「future 尚未自然完成」的判定片。
- 旧参数（sleep 1.5）容忍窗口 Δ+β ≤ 0.15s；
- 新参数（sleep 2.0）容忍窗口 Δ+β ≤ 0.55s（最后安全片 1.8s）。
CI 失败样本 `t_effect=9.1ms` ⟹ 注入链整体延迟 ≈0.24s、落在 1.4s 片后、1.5s 自然完成前
→ 判 `natural_first` 属设计语义（事件序真值=回执标注），为构造性时序抖动而非产品回归。
同 run B-1/B-3 与 S13 通过 + 本地 S13 3/3 复跑绿，佐证判定/收割链路健康。

## 独立复跑（命令与统计）
```
cd <repo> && export PYTHONPATH=$PWD/src && .venv/bin/python -m pytest   tests/phase4/test_m2_inflight_interrupt.py::test_c_s15_race_two_branches -q
```
- 串行 ×12：12 通过 / 0 失败（9.53–10.13s/次，时长无膨胀——绿路径工具仍在 ~1.4s 片被终止）
- `-n auto` ×6：6 通过 / 0 失败（10.71–10.98s/次）
- 补充 `::test_a_s13_interrupt_meets_target` ×3：全过
- 合计 21/21 绿。复跑后 `git status -uall` 仅剩被审文件一处 M；报告快照
  `reports/phase4/m2/*.json` 为 HEAD 跟踪基线，防覆写护栏生效，零写入。

## 问题清单
- P0/P1：无
- P2-1 注释建议补 τ 量化后有效安全预算 0.55s（0.70–0.75s 段为自然完成刀锋区）
- P2-2 A 支既有窄翻转窗口（β>0.05s ∧ Δ+β≤0.15s 可致 `interrupt_first` 误判）——既有
  风险，非本次引入；建议后续加「构造有效性自证」断言（复用 M0 perf 脚手架）
- P2-3 `_race_sample` 默认 `tool_sleep=1.5` 已成死默认值

## 七问结论
1 真修根因（0.15→0.55 推导核实）；2 不掩盖（机械事件序+失败签名+同链路旁证）；
3 无新增风险（时长实测不变、30s 充分、A 支风险为既有）；4 注释与行为一致；
5 证据充分（独立复现 21/21）；6 范围合规；7 余量当前够用（≈2.3×），更大余量与
自证断言为非阻塞后续建议。

## 备注（审查过程透明性）
- `search_records` 工具未纳入该子会话工具域，以 `search_files` 有界替代（5 条命中均为
  无关 eval 产物，无适用方法卡）。
- 审查期间一条只读探查组合命令被工具护栏误标为「疑似全量 pytest」（观测性提示，
  未构成放行凭据亦未阻断）；实际执行的测试均为单测切片，与委派范围一致。
