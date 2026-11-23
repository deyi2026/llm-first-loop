# CTP 代码审查（G-A 契约闸 + G-B 代码闸补件）｜2026-11-23

- 审查者：独立只读子代理 subagent_8b581d73c072（glm/glm-5.3，28 轮 / 45 次工具调用）
- 对象：lane-94ae40f6 分支 diff（base 3ceab62ce → head bae4c891f，+6514 行 / 74 文件）
- 触发：官方合并审查（subagent_1bcef7248d6a）回执 REVISE / p1=2 但未展开内容，另派明细审查
- 性质：审查记录（verbatim 收录 + 处置对照）；对应计划 §15.5 G-A/G-B 闸的补件

## 1. 审查结论（verbatim）

### P0

**[P0-1] ctp/tests/fixtures/valid/v04_covariance.json:61,70,79（生成源 _build_fixtures.py:63）** — 合法样本 v04 的旋转协方差对角线是 deg 数值直接平方，与模板钉死的 rad² 单位相差 (180/π)²≈3283 倍；模板规定"给出 covariance_6x6 时以它为准"，该样本按自身规则读出的有效旋转 1σ = 0.03 rad ≈ 1.72°，与同块声明的 `rotation_1sigma_deg: 0.03`（0.03°）矛盾 57 倍。
阻塞理由：这是契约面唯一协方差示例样本（数据正确性/单位混淆 deg vs rad），下游照抄会把 V6 `k·√(u₁²+u₂²)` 阈值算错 3 个数量级；且 schema/README 决议 5 均未声明 covariance_6x6 单位，错误可静默通过。
最小修复：① schema description 与 README 决议 5 补"covariance_6x6 单位 = m² / rad²"；② `_build_fixtures.py` 旋转对角改 `math.radians(0.03)**2` 并重新生成 v04；③（可选）加"σ 与协方差对角不一致"测试钉住单位。

### P1

**[P1-1] docs/PLAN-20261123-ctp-implementation.md:472** — v0.3a 把 `pytest ctp/tests → 105 passed` 写成"执行回执"，但分支内不存在任何回执文件：`ctp/receipts/` 不存在（PLAN §15.2 L409 把它定为回执写区），artifacts/ 里也没有任何 pytest 输出摘要；且 head 静态收集数为 122 用例（105 是 1624fff67 时点 B1-only 测试面，B2 两笔提交加了 17 个用例后未更新）。
阻塞理由：违反计划自身 §12.2/§15.6 三件套与 §3.2 D2–D4"测试回执"、D6–D7"数值对比回执"验收；B2 的 MC 对比结论同样无落盘回执。
最小修复：补 `ctp/receipts/` 回执文件（命令、环境、完整输出、head SHA）；同步把 v0.3a 行数字改为当前测试面实况。

**[P1-2] docs/PLAN-20261123-ctp-implementation.md:450-451 vs artifacts/ 现状** — B1/B2 已交付并入 lane，但 §15.5 规定的 G-A 契约闸与 G-B 代码闸没有任何工件：artifacts/ 只有文档审查（盲审对象是 SPEC/PROP/DESIGN/PLAN，无 ctp_contract/ctp_calib/schema 字样）。
阻塞理由：违反 §15.1-3"合并前必须有回执"与"实现与审查分离"；B1 六条"契约决定（待 G2 追认）"从未经独立核对。
最小修复：合并前补一份覆盖 ctp/ 代码的独立审查工件并落盘（本文件即为该工件）。

**[P1-3] ctp/src/ctp_calib/uncertainty.py:103-104（对照 129-130）** — `relative_covariance` 文档与实现自称"左扰动"，实际返回相对位姿 T_ba 的**右扰动**切空间协方差（MC 残差 `log(nominal_inverse @ perturbed)` 即 T̃=T_ba·exp(ξ′)），与 se3.py 模块头（L5"扰动为左扰动 T̃ = exp(ξ^) T"）和 pixel.py 的左扰动残差（L147 `log(solved @ pose⁻¹)`）约定相反。
阻塞理由：线性式与 MC 同用一套（错也一致，测试发现不了），但 V6 要求两个独立实现互对一致性——按文档/模块左扰动约定复刻的第二实现会得到差一个 Ad 共轭的逐轴 σ，帧不一致直接污染 F-3/V6 判据。
最小修复：把 docstring 改为"右扰动（T_ba 体/靶标系）残差"；在 uncertainty-declaration-template.md 注明输出的切空间帧。

### 证据核查结论

105 passed 回执不存在（分支内无 `ctp/receipts/`、无任何 pytest 输出文件）；105 恰等于 1624fff67（B1-only）时的收集数（23+47+35），B2 加 17 用例后 head 静态计数 122；审查者自身执行 pytest 被 RULE-AI-28 宿主准入阻断（无审查资格），"122 项是否全部 passed"未独立复核。

### 非阻塞观察

1. `UncertaintyTemplate` 允许"covariance_6x6 非零 + 1σ 全零"组合逃避退化检查，`declaration()` 会产出被自家校验器判 `degenerate_uncertainty` 的声明。
2. test_uncertainty.py:143-148 用 pose=I 测"Adjoint 写错顺序"，但 Ad(I)=I，测不到注释声称的目的。
3. adjudication-and-revision-log.md:60 称修订脚本在 `.scratch/`，实际入库于 `revision-scripts/`（5 份）——路径与数量漂移。
4. ctp/README.md:7 计划锚点仍写 v0.2，PLAN 已到 v0.3a。
5. SPEC F-3 与 PROP G3 互相以对方为"k=2 冻结"出处（循环引用，数值一致）。

其余核查项：B2 数值抽查（exp/log、Adjoint、左扰动雅可比 ∂p/∂ω=−[p]×、GN 更新、MC 残差定义、σ² 缩放）未发现符号/转置/单位错误；B1 与 SPEC C-5 九字段、resolution↔logical_id 联动、k 与 1σ 同给、fail-closed 一致性未发现问题；决议单 8 份未发现自创数值或把建议写成决议；许可方面未发现无声明第三方代码。

## 2. 处置对照（2026-11-23，由 lane 推进者落账）

| 发现 | 定级 | 处置 | 落点 |
|---|---|---|---|
| P0-1 v04 旋转协方差 deg² | P0 | 已修：生成器旋转对角改 `math.radians(σ)**2`，重生成 fixtures；schema 补单位描述；README 决议 5 补单位；新增回归钉 `test_v04_covariance_units_are_m2_rad2` | `_build_fixtures.py` / `v04_covariance.json` / `observation.schema.json` / `README.md` / `test_contract_valid.py` |
| P1-1 回执缺失 + 计数漂移 | P1 | 已修：本补件落地后重跑测试并落 `ctp/receipts/`（命令/环境/输出/head SHA）；计划加 v0.3b 行更正 105→实测数 | `ctp/receipts/`、PLAN §16 |
| P1-2 G-A/G-B 审查工件缺失 | P1 | 已修：本文件即补件（含 verbatim 发现与处置），合并审查另由官方 reviewer 复核 | 本文件 |
| P1-3 relative_covariance 帧口径 | P1 | 已修：docstring 改右扰动口径（含推导）；模板补派生量切空间帧说明；代码本身与 MC 一致，未改数值行为 | `uncertainty.py` / `uncertainty-declaration-template.md` |
| 观察 1 协方差+全零 σ 逃逸退化检查 | 非阻塞 | 已修：`__post_init__` 补"1σ 与协方差对角全零即拒绝" | `uncertainty.py` |
| 观察 2 恒等位形测试无效 | 非阻塞 | 已修：改为零力臂/非零力臂双向断言 | `test_uncertainty.py` |
| 观察 3 归档路径漂移 | 非阻塞 | 已修：日志补"归档勘误"节 | `adjudication-and-revision-log.md` §5 |
| 观察 4 README 锚点版本旧 | 非阻塞 | 已修：v0.2 → v0.3b | `README.md` |
| 观察 5 F-3/PROP 循环引用 | 非阻塞 | 未动：数值一致无害；记入 v1.0 定稿清理项（E1 规范定稿时锚到 SPEC 变更历史行） | PLAN §16 v0.3b 备注 |

处置后测试结果见 `ctp/receipts/`（若该目录为空，则以本文件 §1 证据核查结论为准：未验证）。

## 3. 第二轮：全量测试准入审查（subagent_6e660f5756ad，2026-11-23 23:53）

回执 REVISE / P0=0 / P1=1 / P2=5（报告 `data/review_admission/subagent_6e660f5756ad-full_test.md`，候选指纹 a2554b41…）。发现与处置：

| 发现 | 定级 | 处置 |
|---|---|---|
| schema↔validator 分歧集合口径不一致：schema description 列"四条"validator-only 规则，validate.py docstring 写"三条" | P1 | 已修：两处统一为同一份四条清单（四元数模长、协方差对称、全零不确定度、非有限数拒绝）；parity 测试头注释同步；补程序内 NaN 注入测试 `test_nonfinite_numbers_are_rejected`（fixture 覆盖不了第四条） |
| `se3.log_se3` 在 θ→π 奇异无防护，近 π 返回垃圾值 | P2 | 已修：θ > π−1e-9 显式 `ValueError` + docstring 声明边界；补应拦输入测试 `test_log_se3_rejects_pi_rotation` |
| 模板退化检查口径与 C-5 validator 不一致（协方差给出时放行全零 1σ） | P2 | 已修：模板无条件拒绝全零 1σ（与 validator 对齐）；补应拦输入测试 `test_template_rejects_zero_sigma_even_with_covariance` |
| PSD 推给 B2 但 B2 未实现；MC 对非 PSD 报裸 `LinAlgError` | P2 | 已修：模板层 eigvalsh 下界校验；`monte_carlo_relative` 入口对称 + PSD 预检并给出可读错误；README 决议 5 改为如实口径 |
| 模板自检片段用裸 `python -c`，与 README 规定 runner 不一致 | P2 | 已修：统一为 `./.venv/bin/python -c` 并注明在仓库根目录执行 |
| README"零第三方代码（K4）"与 numpy/jsonschema 依赖表述冲突 | P2 | 已修：改为"不 vendor 第三方源码；运行依赖 numpy、测试依赖 jsonschema（依赖声明，非复制源码）" |

## 4. 第三轮：全量测试准入复审（subagent_92d0af67a505，2026-11-24 00:0x）

上轮 6 项处置全部被复核 ACCEPTED；残留 1 P1 + 2 P2（报告 `data/review_admission/subagent_92d0af67a505-full_test.md`，候选指纹 ae845f33…）：

| 发现 | 定级 | 处置 |
|---|---|---|
| 分歧集合声明仍不完整：时间戳**日历/偏移语义**（`2026-13-45T25:00:00+08:60` 过 schema pattern、被 fromisoformat 拒）与 **target_index 整数值浮点**（2020-12 integer 接受 `42.0`，`_is_int` 拒绝）两类分歧未声明、无 fixture 钉 | P1 | 已修：分歧集合四条 → **六条规则族**（R1 模长/R2 对称+非负对角/R3 全零/R4 非有限/R5 日历语义/R6 整数值浮点），schema description、validate.py docstring、parity 测试头三处同一份清单；新增 fixture i23（`format_error`）/i24（`type_error`）并把 VALIDATOR_ONLY 扩为六个 fixture、逐条标注规则映射 |
| 模板自检片段迁移到仓库根后 `'src'` 相对路径失效 | P2 | 已修：改为 `sys.path.insert(0,'ctp/src')` |
| `monte_carlo_relative` 未守护 θ→π 奇异：大 σ 采样命中时自检会中断而非判不通过 | P2 | 已修：`check_first_order_validity` 捕获该 ValueError 转为 `ok=False + reason=pi_singularity`（fail-closed 判定）；MC 直接调用方在 docstring 中要求自行缩小适用域；探测器测试兼容两种失败形态 |
