# S1 影子期校准报告（2026-11-05）

对象：`lane_gate.evaluate_s1_gate`（S1 十条机检）。目的：满足 DESIGN-20261105 §4.4.1
影子期要求——`≥10 次 dry-run`、人工判定与机检判定**一致率 100%**、**零漏拦**（机检放行而人判拒绝 = 一票否决）。

## 1. 结论

- 场景数：**19**（覆盖十条机检逐条 + 3 个边界）
- verdict 一致：**19/19**
- auto_allowed 一致：**19/19**
- 漏拦（false allow）：**0**
- 误拦（false deny）：**0**

判定：**满足**进入 S1 前置条件（一致率 100% 且漏拦 0）。注意：满足前置条件 ≠ 已开启；
`lane_auto_merge` 仍默认 `false`，开启需显式配置并承担 §4.4.1 责任。

## 2. 场景对照表

| id | 场景 | 人判 | 机判 | 人 allowed | 机 allowed | 拦下的 check | 依据 |
|---|---|---|---|---|---|---|---|
| C01 | 全绿+开关开+allowlist 覆盖 | pass | pass | True | True | — | 十条全满足→自动 |
| C02 | main.broken=true | fail | fail | False | False | s1_01 | 第1条 |
| C03 | 部署窗口内 | fail | fail | False | False | s1_01 | 第1条 |
| C04 | merge-tree 冲突=2 | fail | fail | False | False | s1_02 | 第2条 |
| C05 | patch_digest 不匹配 | fail | fail | False | False | s1_03 | 第3条 |
| C06 | base 旧+impacted 级复验 pass | pass | pass | True | True | — | 第3条：需 scope=impacted 且复验 pass |
| C07 | base 旧且无 impacted 复验 | fail | fail | False | False | s1_03 | 第3条 |
| C08 | 审查 verdict=fail | fail | fail | False | False | s1_04 | 第4条 |
| C09 | 审查绑定 sha 不匹配 | fail | fail | False | False | s1_04 | 第4条 |
| C10 | 改动路径不在 allowlist | fail | fail | False | False | s1_05 | 第5条 |
| C11 | 改动路径命中 sealed(rules) | fail | fail | False | False | s1_06 | 第6条 |
| C12 | 批次超 K=3 | fail | fail | False | False | s1_07 | 第7条 |
| C13 | 有 need=block 协助请求 | fail | fail | False | False | s1_08 | 第8条 |
| C14 | 其他 lane 持重叠 claim | fail | fail | False | False | s1_09 | 第9条 |
| C15 | merge_plan.no_ff=false | fail | fail | False | False | s1_10 | 第10条 |
| C16 | merge_plan.parent 非 main head | fail | fail | False | False | s1_10 | 第10条 |
| C17 | 协助/claim 数据源未接入(None) | fail | fail | False | False | s1_08, s1_09 | skip≠pass，依赖不可用不放行 |
| C18 | 空 allowlist（默认） | fail | fail | False | False | s1_05 | 第5条：默认空=全不自动→path_not_allowed |
| C19 | 开关关但 allowlist 已配 | pass | pass | False | False | — | 全过但不自动，回落 S0 |

## 3. 校准过程中澄清的两个判定口径（已回写设计文档 §15）

### 3.1 第 3 条 impacted 级复验是**双条件**

`base_sha != main_head` 时，仅 `impacted_result="pass"` 不够，必须同时 `scope="impacted"`。
首轮校准我把 C06 只设了 `impacted_result`，机检判 fail；核对 `_check_s1_03` 后确认
**机检正确、人工判定错误**——「impacted 级复验」在 D3 表里就是 `scope=impacted` 的回执。

### 3.2 空 `auto_merge_allowlist` 判 `path_not_allowed`，不是「只是不自动」

文档第 5 条写「默认空 = 全不自动」。实现把它落成 `s1_05 fail(path_not_allowed)`，
而非 `verdict=pass` + `allowed=false`。二者语义不同但都不放行：
前者报「路径不被允许」，后者报「开关关闭」。校准采用实现口径（fail-closed 更保守），
并新增 C19 单独覆盖「开关关但 allowlist 已配」→ `verdict=pass, allowed=false`。

## 4. 方法学边界（如实标注，勿高估）

- 本校准的 19 个场景**由同一模型构造**，人工判定与机检实现出自同一认知源，
  存在共同盲区风险；它证明的是「实现与文档规则一致」，**不证明**「规则本身覆盖了真实世界的失败模式」。
- 未使用历史真实合并案例做对照（仓库内没有可复现的 10 次合并事件流）。
- 因此：本报告足以支撑「可以开启 S1 试运行」，但**不足以**宣称「S1 判定质量已在真实分布上验证」。
- 建议的补强：开启后前 10 次自动判定全部记 `shadow_compare`，与人工事后判定对账；发现分歧即回落 S0。

## 5. 复现

```bash
.venv/bin/python scripts/lane_gate_shadow_calibration.py
```

脚本内人工判定先于机检写定（见文件头注释），结果写 `work/shadow_calibration_result.json`。

