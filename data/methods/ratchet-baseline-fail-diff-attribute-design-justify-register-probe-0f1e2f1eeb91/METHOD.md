---
method_id: ratchet-baseline-fail-diff-attribute-design-justify-register-probe-0f1e2f1eeb91
name: ratchet-baseline-fail-diff-attribute-design-justify-register-probe
description: 单向 ratchet/allowlist 基线门（env 访问签名、lint 例外、依赖计数等只减不增的基线测试）因新增条目变红时，不要先宽泛搜文档或读扫描器实现。基线 fixture 自身就是惯例文档：①做 current-inventory 与 baseline 的集合差，拿到精确新增签名与计数 delta；②对新增签名做 git 归因，区分本次改动与分支既有提交；③用签名中的符号/env key 定点 grep 设计文档，确认该访问为设计语义必需且无法走既有 helper；④按基线既有条目 schema（phase/parent_commit/design_ref/review_rationale/新键）做最小登记，只调受影响计数；⑤注入一次性探针访问证明门禁仍拒绝未登记项，删除后复绿。查不到设计依据时停止登记，转重构或上报 owner。
aliases: 棘轮基线红了怎么登记, env 访问基线新增签名, ratchet 门禁失败 受审登记, 基线豁免还是重构怎么判, one-way ratchet new signature admission, 基线登记后验证门还咬人
status: candidate
source_model: deepseek/deepseek-v4-flash
source_episode_refs: episode:c7e4e166-3401-45cd-9402-77e522055d10:820:cecb68ac9f106d1f8c45
evidence_refs: learning:learn:d4c22d99731b
created_at: 2026-10-28T23:11:52.014038+08:00
updated_at: 2026-10-28T23:11:52.014038+08:00
---
## Trigger
仓库的单向 ratchet/allowlist 基线门（如 runtime env 访问签名基线测试）因新增签名/条目而失败，失败回执已点名具体新条目、所在文件与断言（新增/扩大即红）

## Discriminator
基线 fixture 的 baseline_context/历史受审条目已完整展示受审登记 schema（phase、parent_commit、design_ref、review_rationale、reviewed_new_signatures），且既有 rationale 已示范『无法用单 key helper 表达→登记为受审债务』的接受理由——这把『怎么让门过』缩成差分、归因、设计依据三个定点未知量，无需关键词宽搜、读扫描器源码或重找基线路径

## Short path
- 跑 current-inventory vs baseline 的集合差脚本 → 拿到精确的新增签名列表与计数 delta（未知量：到底新增了什么）
- 对新增签名所在文件做 git 归因（log/区间 diff），区分『我本次改动』与『分支既有提交引入』（未知量：谁引入的、是否在我职责内）
- 用签名中的符号名/env key（如 _set_default_model_locked|LLM_MODEL）定点 grep 设计文档对应条款 → 确认访问是设计语义必需、且无法用仓库既有单 key helper 表达（未知量：该登记还是该重构）
- 按基线既有条目 schema 写入登记：phase/parent_commit/design_ref/review_rationale + 新签名键，只上调受影响计数，不删既有键
- 重跑门禁测试 → 转绿
- 注入一次性探针（临时在 src 放一处 raw env 读）确认门禁仍判新增而失败，删除探针后复绿——证明登记是逐条受审、不是整体豁免

## Stop conditions
- 门禁测试转绿，且探针注入→红、删除→绿 实测 ratchet 仍单向有效
- 设计文档查不到要求 raw 访问的语义依据，或新签名可用既有 helper 表达 → 停止登记，转 helper 重构或上报 owner 决定
- 归因显示计数漂移来自扫描器/分类规则变化而非新签名 → 走基线再生成/对齐路径，不做逐签名登记
- 登记涉及他人维护的设计取舍（如是否该改走统一 helper）→ 交付时显式列出该决定点，不替 owner 定

## Verification
- 重跑该基线门测试全部通过
- git diff 基线文件：只新增预期条目键与最小计数变化，无既有键被删
- 探针实验证明未登记的新访问仍会让门失败（登记≠豁免）
- 归因用的 git 区间 diff 为空能排除本次改动引入

## Counterexamples
- 新签名完全可用既有单 key helper 表达、设计文档也无 raw-env 语义要求 → 登记等于洗白回归，应重构而非登记
- 基线 fixture 中没有任何历史受审条目（无既定惯例可循）→ 不自造 schema，先取得 owner 显式决定再动基线
- 失败由自己本次未提交的改动直接引入 → 先尝试把访问收敛进 helper，只有归因到既有提交且语义必需时才考虑登记
- 计数变化源于扫描器升级重分类既有访问（无新签名）→ 问题是基线与扫描器版本错配，逐签名登记是错误药方
