# LINT-S1B：正交 filler 卡污染检查

- 日期：2026-10-19
- 对象：`s1b_orth/cards/filler_orth.md`（对照 `s1_gold_filler/cards/gold.md`）
- 脚本：`s1b_orth/lint_s1b.py`；机读结果：`s1b_orth/lint_s1b.json`

## 结果

| 项 | gold | filler_orth | 差值 | 判定 |
|---|---|---|---|---|
| 字符数 | 744 | 757 | 1.75% | PASS（<10%） |
| CJK 字符 | 388 | 375 | 3.35% | PASS |
| UTF-8 字节 | 1638 | 1583 | -55 | PASS |

- 同结构：六节（Trigger / Discriminator / Short path / Stop conditions / Verification / Counterexamples）齐全，无缺节。
- 内容无关：禁用词扫描 0 命中（链接/正文/抓取、你想/要不要、选项/二选一、发布/推送/注册、成本/可逆/边界、暂停/先校验）。
- 近重：与 `pool_p28.jsonl` 的 120 个 question 做 8-gram 比对，最大覆盖率 0.0、最大 Jaccard 0.0（阈值 ≤0.3）。
- 不自引：卡文不含任一实例 URL、标题、S0 回复原文或答案措辞。

## 与旧 filler 的正交性

旧 filler（CSV schema 校验）的行为链：校验 → 冲突则暂停 → 请确认 → 再写入。
新 filler（列表排序去重）的行为链：读数 → 排序 → 重写 → 计数。
新卡没有「等待用户裁决」的停点，也没有「给互斥选项」的分支，因此不会像旧 filler 那样把谨慎程度一并抬高。

## 备注

- 首版 Discriminator 含「耗时」，被 lint 判为成本词，已改为「更易出错」；本文件对应修改后的冻结版本。
