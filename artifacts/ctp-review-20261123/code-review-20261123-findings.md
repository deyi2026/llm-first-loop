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

## 5. 第四轮：全量测试准入终审（subagent_a848428989db，2026-11-24 00:4x）

回执 **PASS / P0=0 / P1=0**（FINGERPRINT 87e5cf20…；前三轮 6+3 项发现逐条 ACCEPTED；配套测试回执落盘 `ctp/receipts/20261124-b1b2-pytest.md`，132 passed / 2.11s）。终轮随 PASS 附带 3 项 P2 与处置：

| 发现 | 定级 | 处置 |
|---|---|---|
| README 目录行写"10 合法 + 22 非法"，语料实为 24 非法 | P2 | 已修：README 计数改 24 |
| `check_first_order_validity` 把一切 `ValueError` 都标 `reason=pi_singularity`（非奇异错误也得到该 reason） | P2 | 已修：se3 新增专属异常 `LogSingularityError`，`log_se3` 抛它、自检只捕它，其余 ValueError 照常传播 |
| NaN 注入测试写法混淆（`.replace(...)` 实际加载 i14）+ 末尾自证断言 | P2 | 已修：直接 `_load("i14_missing_reader_version")`，删自证断言 |

注：该轮无 `data/review_admission/*-full_test.md` 报告文件（工具仅前两轮落盘）；持久锚点为主会话事件日志 action_trace（pass 判定序列，会话 620199be）与回执内 FINGERPRINT 87e5cf20 的一致性。

## 6. 第五轮：合并审查（subagent_bcd74df31265，2026-11-24 11:05）+ 明细复核（subagent_2f37847d66ae）

- 官方合并审查回执 REVISE / p0=3 / p1=1——**四条经明细复核全部不成立（误报）**：其输入是跨分叉两点 diff `5fdd2108..a01b05df`，把 main 侧 PR #109/#110 的推进（EMFILE 修复、容量反馈、Sidebar 可见性、三份治理清单）视差读成分支删除。分支相对 merge-base（a64081687）真实增量为 87 文件全新增、零删除修改；且 lane 队列走三点合并，上述内容合并后保留。
- 明细复核独立发现并确认 **4 条真 P1**，处置如下：

| 发现 | 定级 | 处置 |
|---|---|---|
| P1-1 ctp/ 对三道既有门不可见：pyproject `testpaths=["tests"]` 不含 ctp/tests（全量回归漏跑）、`ruff check ctp/` 现存 6 错（UP042×2 / F841 / I001×3） | P1 | 已修：`testpaths += ctp/tests`（根 pyproject，+1 行）；StrEnum 改写（需 Python ≥3.11，README 已注明）；F841 删除未用变量；I001 三处 import 排序修复；`ruff check ctp/` 清零（回执见下） |
| P1-2 终轮 PASS 无落盘报告文件 | P1 | 已修：本文件 §5 注明工具行为差异 + 事件日志锚点；回执内 FINGERPRINT 交叉引用 |
| P1-3 findings 只记到第二轮、README 计数过时 | P1 | 已修：本 §5/§6 即补齐；README 计数改 24 |
| P1-4 `artifacts/` 在 .gitignore 忽略根下，评审工件目录后续新增文件会静默不进 git status | P1 | 已修：根 .gitignore 加 `!/artifacts/ctp-review-20261123/` 例外 |

处置验证：`ruff check ctp/` → All checks passed；`ctp_calib.log_se3(180°)` → `LogSingularityError`；`check_first_order_validity(60°σ, 200 samples)` → `ok=False`；StrEnum 继承生效。

## 7. 勘误与终修（2026-11-24 11:5x）

第六轮合并审查（subagent_3730efe93bca）裁 1 条 P1，经窄范围明细复核（subagent_f28c095cfbe3）**成立**：

- **P1-4 首次修复形态是 git 死行**：`/artifacts/`（带尾斜杠）排除目录本身，git 不再下钻，`!/artifacts/ctp-review-20261123/` 永不求值——`git check-ignore` 实证仍命中 `:46:/artifacts/`。本表 §6 对 P1-4 的"已修"声明在当时形态下不成立，特此勘误。
- **终修**：`.gitignore` `/artifacts/` → `/artifacts/*`（例外行原样保留），与本仓 `data/*` + `!data/methods/` 既有惯例同构。核验：`git check-ignore artifacts/ctp-review-20261123/NEW-RECEIPT.md` 退出码 1（未被忽略，例外生效）。
- 同轮排查确认不成立的其他候选：testpaths 扩容打红 CI（uv.lock 含 numpy/jsonschema）、pyright/ruff 门禁范围声明矛盾（§6 未作该声明）、回执与 git 事实一致性、StrEnum 版本兼容——均逐一排除，依据见复核记录。

## 8. Wave-2 全量测试准入审查（subagent_84e2886b6b17，2026-11-24）

对象：lane-4bbd8c8e 分支 ctp-wave2-20261124（head cdbd4d95c：B6 生成器 + B5 注册表 + A2 规程 + A3 矩阵，scope=[ctp, docs/conformance, docs/trace]）。回执 REVISE / P0=0 / P1=1 / P2=4（报告 `data/review_admission/subagent_84e2886b6b17-full_test.md`，候选指纹 5c8d3756…）。发现与处置：

| 发现 | 定级 | 处置 |
|---|---|---|
| 同一提交内"文档↔代码"矛盾：A3 交付基于陈旧树盘点（B5/A2 未入其快照），coverage-summary 声称"注册表未实现/R-1..R-5 pending/6 测试文件/45 函数/143 例/conformance 空目录"与实际提交树相反；ctp/README 状态行停在 B1+B2、目录树缺 ctp_gen/ctp_registry/upstream/receipts、K4"不 vendor"与 apriltag-tag36h11.c vendored 事实矛盾、依赖段缺 reportlab/pypdf/cryptography | P1 | 已修：README 重写状态/性质/目录树/依赖/K4 vendor 例外（注明待 G2 裁决）；trace.csv/trace.md/coverage-summary 重定基——R-1..R-6 → covered（证据 test_registry.py 行号）、计数 7 文件/69 函数/185 例、条目 9 covered/9 partial/41 pending、行级 47/15/51、第 6 章 6 covered、缺口 §2/§3 重写为现状 |
| 墓碑 retire 事件无权威校验（任何能写 JSONL 的写者可追加 retire 封死绑定 = DoS 面；已文档化但优先级低） | P2 | 已修：`RegistryStore(retire_verifier=...)` 钩子（默认 None=SPEC 最小语义，不发明规范要求）；registry-notes TODO-G2 将该项升为首位并写明 DoS 机理；新增应拦用例 test_retire_verifier_vetoes_retire |
| `monte_carlo_pose_from_pixels` 的残差 `log_se3` 在 try 外，θ→π 奇异会穿透 `check_first_order_pixel` | P2 | 已修：残差并入 try，命中奇异=样本出域，排除并计数（excluded>0 → ok=False，不静默丢样本）；docstring 同步 |
| `_render_pdf` 对所有页用 layouts[0].page，混页静默裁剪 | P2 | 已修：入口对混页尺寸 fail-closed `ValueError`；新增应拦用例 test_render_rejects_mixed_page_sizes |
| test_uncertainty.py 两个测试定义在 `__main__` 卫语之后，脚本模式执行不到 | P2 | 已修：卫语移到文件末尾，两个测试回归收集序 |
| （附带）i16 NaN fixture 与"JSON 文本层不可表达"措辞张力 | P2 | 说明：i16 依赖 Python json 的扩展字面量 NaN 解析，非标准 JSON 文本；R4 规则族的声明口径不变 |

## 9. Wave-2 测试准入 r2（subagent_5a5be205c44e，2026-11-24）

回执 REVISE / P0=0 / P1=1 / P2=3（报告 `data/review_admission/subagent_5a5be205c44e-full_test.md`，指纹 eb626558…）。r1 的 5 项处置经复核全部生效。残留与处置：

| 发现 | 定级 | 处置 |
|---|---|---|
| conformance README §4 仍基于陈旧树：声称"未落地：B5 注册表"、find 复核只列三包——与本提交同树的 ctp_registry 矛盾（r1 P1 的同类新实例） | P1 | 已修：README 已落地清单改为 B1/B2/B5/B6 四包 + find ctp/src 复核口径；未落地收敛为 B3/B4/B7/B8 |
| coverage-summary §二 结尾残留"规程未建、docs/conformance/ 为空"旧句 | P2 | 已修：改为"规程已建、实测回执未产生；V4/V7/V8 依赖 B7 runner" |
| 计数漂移：185 与自身明细求和不一致（uncertainty 实为 12）；trace.md 孤儿检查 generator 9 函数（实为 10） | P2 | 已修：改为引用制——AST 静态函数数（7 文件/77 函数，逐文件列出）可直接机检；参数化用例总数不再多处手抄，单一真值=ctp/receipts/ 最新回执 |
| 墓碑 retire 默认仍无权威校验（已文档化+钩子+测试+TODO-G2 首位） | P2 | 维持：reviewer 自评"accepted risk for a prototype pending WG ruling"；工作组裁决前不发明规范要求 |

## 10. Wave-2 测试准入 r3 PASS 后的执行发现（2026-11-24）

r3（subagent_6014966192ff）回执 PASS 后首次真实执行测试即暴露**收集期 ImportError**——`ctp_gen` 包根未导出 `layout_from_dict`（layout.py:89 已定义，`__init__.py` 导入清单与 `__all__` 均缺失），test_generator.py:24 从包根导入失败，整个收集中断。这是 B6 提交（4e2a8e5de）自带的缺陷，三轮只读审查均未执行测试故未暴露；同时首次前台执行消耗了 r3 资格且 60s 墙钟超时丢失输出（执行侧教训：受闸命令一律 run_in_background）。

处置：`ctp_gen/__init__.py` 补导出 `layout_from_dict`（导入行 + `__all__`）；补模块级导入自检（7 个测试文件 import 全通过，exit=0）；本项随 r4 审查重走准入后以后台方式重跑全量测试落回执。

## 11. Wave-2 测试准入 r4（subagent_5fe38d0fec27，2026-11-24）

回执 REVISE / P0=0 / P1=1 / P2=4（报告 `data/review_admission/subagent_5fe38d0fec27-full_test.md`，指纹 cd52f0b9…）。发现与处置：

| 发现 | 定级 | 处置 |
|---|---|---|
| coverage-summary.md 记账数字自相矛盾且与 CSV 矛盾：§1 称 test_registry "24 函数 / 42 例"而孤儿节为 31；kind 拆分 "unit 63 + pending 38" 而 CSV 实为 62 / 39；§2A 称 V7 "规程未建"而 V7-version-compat.md 已随补丁入库；trace.csv R-2 行称"等 4 例"而该族有 7 个测试方法——且所引回执只覆盖 B1+B2，不含任何 registry 计数 | P1 | 已修：删除全部手抄"等N例 / 24 函数 42 例"，用例数一律指向最新回执（引用制）；kind 拆分改 62 / 39 / 12；V7 行改"规程已建、实测待跑"；R-5/R-6 证据行号随新增测试同步为 361 / 429；静态函数数同步为 80（uncertainty 13、registry 33） |
| snapshot.py `created_at` 只查非空字符串，任意值可被铸造并签名 | P2 | 已修：改用 R-1 同口径 `_parse_tz_datetime`（ISO 8601 + 时区）；新增应拦用例 test_snapshot_created_at_requires_iso8601_with_timezone |
| `build_snapshot` 未做墓碑终态过滤，手写 register→retire→register 链可让墓碑 ID 回到快照 records | P2 | 已修：records 过滤 `tid not in tombstones`（与 `_latest_records` 同口径）；新增应拦用例 test_snapshot_excludes_tombstoned_id_even_if_reregistered |
| 过 PSD 容差但奇异的协方差（某轴 1σ=0）使 Cholesky 裸抛 LinAlgError | P2 | 已修：Monte Carlo 入口转类型化 ValueError；`check_first_order_validity` 增 `except ValueError → ok=False, reason=invalid_covariance`；新增应拦用例 test_singular_covariance_is_typed_failure |
| lint：TagSpec 注释"默认 10 mm"与 generator-notes（gap 6 / margin 10）矛盾；render.py 未用 `_sha256_bytes`；store.py `import hashlib` 位置与无占位 f-string | P2 | 已修：注释改为"必填，取值见 generator-notes"；删除未用函数及其 hashlib 导入（全仓无其他引用）；hashlib 归位 stdlib 块；f-string 补上底层异常 |

## 12. Wave-2 测试准入 r5 审查者超时与 r6 审查切片收窄（2026-11-24，如实声明）

r5（subagent_4b59fb2dc085，候选 4238b9b8…，切片 = `ctp` + `docs/conformance` + `docs/trace` 全量，材料 30.4 万字符）首轮与其自动重试**均以 reviewer_timeout 失败**——宿主回执原文："LLM 流式总时长超限（>600s）；各 read 间隔均未超时——provider 持续滴流不收敛，已机械截断"。两次都未产出任何审查结论（review_answer_chars=148），**不构成 PASS 也不构成 REVISE**，r4 处置在本轮未获独立复核。

处置：同条件第三次重试预期仍会超时，故 r6（subagent_33409f675de7，候选 d4d8cff2…）**收窄审查切片**以缩短材料（30.4 万 → 24.6 万字符）。移出本轮切片的两块及其依据：

| 移出内容 | 体量 | 依据 | 残余风险 |
|---|---|---|---|
| `ctp/docs/upstream/apriltag-tag36h11.c` | 714 行 | vendored 第三方码表数据，不参与测试逻辑；r4 已核"保留完整 BSD-2 许可头、tag36h11_table.py 抽查与上游一致" | 低：数据文件，自 r4 起未改动 |
| `docs/conformance/`（README + V1–V8） | 846 行 | 书面规程，不参与测试执行；r1/r2 两次 P1 均针对其陈旧表述并已修复，r3/r4 对其内容无新发现 | 低-中：本轮修订未碰这些文件（r4 修复只动 docs/trace），但其最新表述在本轮无独立复核 |

仍在切片内全审：`ctp/src`、`ctp/tests`、`ctp/schema`、`ctp/README.md`、`ctp/docs/{registry-notes,generator-notes,uncertainty-declaration-template}.md`、`ctp/receipts`、`docs/trace`（含 r4 P1 的计数修复）。

兜底：这两块仍属 lane-4bbd8c8e 的合并范围，合并审查（merge_review_start）按 lane 全量 diff 复核；若合并审查同样超时，不得据此视为已审。

**r6 结果**：PASS（候选 `d4d8cff2…`，head `e085e3bd3`，运行时工作树干净）。随后以后台任务执行与 target 逐字一致的命令：`190 passed in 2.30s`，退出码 0——这是 Wave-2 自 B6 提交以来**第一次真实全量通过**。完整回执见 `ctp/receipts/20261124-wave2-pytest.md`（用例总数 190 为单一真值）。

过程勘误（如实记录）：r6 受理后我曾误改 worktree 内一个切片外的已跟踪文件（本文件），会让"切片外内容摘要"在消费时失配；发现后立即 `git checkout` 恢复到提交态、文本暂存主仓 scratch，测试通过后才补回——未影响 r6 资格的有效性。

## 14. Wave-2 合并前验收补齐与自查发现（2026-11-24，推送前）

对照 durable task 的验收条目逐项核对 B6 / A2，并自查 A3。三项补齐、一项**自查发现的实质缺陷**：

| 项 | 事实 | 处置 |
|---|---|---|
| B6 验收第 2 条（布局 JSON 含每个码的 target_index、物理坐标、参考系定义引用） | `Layout` 无参考系字段；逐码坐标只是可推导、未显式写出 | `frame_ref` 设为**必填**（缺失/空白即拒，无默认值）；`layout.json` 新增 `tags`（逐码左上角 + 中心坐标）、`coordinate_frame`（原点页面左上角 / x 右 / y 下 / mm）；`layout_from_dict` 对手改的 `tags` 块拒收；清单 `boards[]` 记 `frame_ref`。新增 3 个测试（1 正例 + 2 应拦） |
| B6 验收第 1/4 条（输入含公差等级；公差标注对应 P-2、数值留 TBD） | 输出无任何公差标注 | `tolerance_grade` 可选申报（未申报如实写 `unspecified`，不代填）；`tolerance` 块键对应 `P-2a/P-2b/P-2c`，值恒为 SPEC 现行 TBD 占位编号，**不是数值** |
| B6 验收第 3 条（打印后能被 B3 读通） | **仍未满足**——B3 未落地 | 不标 done；随 B3 一并闭合 |
| A2 验收第 4 条（每份含一条最小冒烟步骤） | 8 份规程均无 | 各补「S1 冒烟一次」：共用冒烟板命令（README §2）+ 本门槛特有一步 + 明确止步点；V5 / V6 两条命令与冒烟板命令均在本机以仓库 `.venv` 实测（输出 `manifest_ok True` / `coarse` / `first_order_ok True`）。冒烟只证明流程能跑通，回执 `simulated: true`，**不产生门槛证据** |
| **A3 自查：矩阵「无孤儿」声明为假** | 用脚本把 83 个测试函数逐名对照 `trace.csv`，**31 个函数未出现在矩阵中**——r1 重定基时 R-1–R-6 行写成「某测试 等」，把同族其余成员藏起来了；此前孤儿检查采信了人读结论，r1–r6 六轮审查均未发现 | 补 33 行（27 条 R-* 成员、C-1d ×3、P-5b、M-3、C-5b），每个函数单独具名；去掉概括性的「等」；生成器既有引用行号因辅助函数增行整体 +1；行级计数更正为 146 行 / covered 74 / partial 21 / pending 51；脚本复查孤儿 0 |
| 计划 §1.2 两条陈旧行 | 仍写「三份文档未入库」「仅 B1 落地」，与 Wave-1 已合入 main 的事实相反 | 更正并标 as-of 2026-11-24 19:00 |

教训（写给后续执行者，非审查发现）：**概括性的「等」与「无孤儿」声明不相容**；孤儿检查必须用脚本逐名对照并保留可复跑的检查，不采信人读汇总。

## 15. Wave-3 测试准入审查 r1（subagent_cac6e9cc3c4c，2026-11-25 01:48）与修订

候选：lane 分支并入 trunk `4f1157055` 后的 `be8a93ba`（候选提交 `33706b68` 为其第一父；两侧改动文件零重叠）。切片：`ctp/src`、`ctp/tests`、`ctp/docs`、`docs/trace`（200,267 字符，指纹 `4e88fa5a…`）。

**结果**：REVISE，P0 = 0 / P1 = 1 / P2 = 3。报告：`data/review_admission/subagent_cac6e9cc3c4c-full_test.md`。

| 级别 | 发现 | 处置 |
|---|---|---|
| **P1-1** | V4 verdict integrity：`v4.run` 用 `config.get(..., NOT_CONFIGURED)` 取 `miss_rate_limit` / `min_sample_size` 且从不校验；`is_limit()` 拒收非数值，于是不可用值让上限检查被跳过，而 `finalize()` 只认 `"not_configured"` / `"[TBD-*"` 两个字符串哨兵为未配置——带着一个无法使用的上限判 `verdict=pass`。必填的 `min_visible_corners` / `min_visible_data_ratio` 有同类缺口（NaN 比较恒假，全部样本落到达标组） | `v4.py` 新增 `_in_range` / `_required_threshold` / `_optional_limit`：必填分组阈值缺失或不是区间内有限数值 → `ValueError`（拒绝运行，不产出回执）；可选上限提供了但不可用 → 归一为未配置 + notes 留痕 → `indeterminate`。区间：`min_visible_corners ≥ 0`、`min_visible_data_ratio ∈ [0, 1]`、`miss_rate_limit ∈ [0, 1]`、`min_sample_size ≥ 1`；`[TBD-*` 哨兵原样保留 |
| P2-1 | `synth.crop_corners` docstring 写「可见角点 3 / 2 / 1」，与 `_VISIBLE_CORNERS`（1 / 2 / 0）、`geometry()`、说明文档与集成期望矛盾 | docstring 更正为 1 / 2 / 0，并说明矩形裁剪裁掉的是整条边 |
| P2-2 | 命令行文档假定 `python -m ctp_conformance.v4` 可从 worktree 根导入，未说明机制 | 说明文档 §4 补 `PYTHONPATH=ctp/src` 与原因（src 布局、未安装为包；`conftest.py` 为 pytest 做的是同一件事）；本机实测：带则可导入，不带报 `ModuleNotFoundError` |
| P2-3 | `conftest.py` 把测试目录追加到 `sys.path` 以暴露 `conformance_stubs` / `reader_testkit`，属模块遮蔽向量（仅测试作用域、名字不易撞） | **不改结构**：可行的替代要么把 `ctp/` 放进 path（引入顶层名 `tests`，可能遮蔽仓库自身的 `tests`），要么给辅助模块建包并改全部导入。在 docstring 如实记录取舍（一律 append、辅助模块名带用途前缀） |

**同根排查（审查未点名，修订时自查发现，一并处置）**：

- `min_sample_size` 给 0 / 负数时「样本量不足」检查恒不触发——与 P1-1 同根，纳入 `_optional_limit`（须 ≥ 1）。
- `v8.run` 用 `bool(config.get("include_forgery", True))` 强转：传 `"false"` 得 True、传 `null` 得 False，静默改变演练范围（范围一变回执不可比）。改为只接受 JSON 布尔，否则 `ValueError`。

**修订前后对照（一手实测；旧版 `v4.py` 取自 `33706b68`，以 `build_samples(0)` + `conformance_stubs.StubReader / gate_like(4, 1.0)` 驱动；复跑脚本留档于主仓 `.ctp-scratch/takeover/oldcheck.py`，不入库）**：

| 输入（其余项取合法值） | 修订前 | 修订后 |
|---|---|---|
| `miss_rate_limit` = None / NaN / True / `"0.1"` / 2.0 / inf（6 种） | **6 种全部 `pass`** | 6 种全部 `indeterminate` |
| `min_sample_size` = None / NaN / True / `"100"` / 0 / -5（6 种） | **6 种全部 `pass`** | 6 种全部 `indeterminate` |
| `min_visible_data_ratio` = NaN | **`pass`** | `ValueError` |
| 分组阈值 = True / 越界 / NaN（角点数） | 带着错误分组出 `fail` | `ValueError` |
| 分组阈值 = None / 非数值字符串 | `TypeError` 崩溃 | `ValueError`（明确报错） |
| 合法值（0.0 / 1 / 4 / 1.0） | `pass` | `pass`（行为不变） |

**回归钉**（3 个函数，逐名入追溯矩阵：`conformance_v4` 11→13、`conformance_v8` 8→9，测试函数 167→170，矩阵 225→228）：`test_unusable_optional_limits_are_unconfigured_never_pass`（12 例）、`test_unusable_grouping_thresholds_are_rejected`（10 例）、`test_non_boolean_include_forgery_is_rejected`（5 例）。定向验证：这两个文件 46 passed，`test_trace_matrix.py` 3 passed。

残余（不在本次修订范围，如实登记）：`ctp/` 下 40 个 ruff 提示（`I001` 22、`UP037` 7 等，其中 12 个在已合并的 Wave-2 文件 `ctp_registry/*`）。CI 的 ruff 历史债棘轮范围是 `src tests scripts`，不含 `ctp/`；本机该闸 R9 ruff PASS（new = 0）。未顺手修——那会把 27 个文件的格式改动混进本次审查面，宜另立小任务。

## 16. Wave-3 测试准入审查 r3（subagent_524af23f7ebf，2026-11-25 08:45–08:53，候选重放到 main `6349346d` 之后）

**缘由**：Wave-3 候选原 head `d9d1c55df` 的基线是 main `4f1157055`。主干前进到 `6349346d` 后，把 3 个非合并提交线性重放过去（`eb88b6b92` / `b591d8f9b` / `9dc0dee72`，内容不变，相对主干的差异前后一致：40 files，+4014 / −130）。r2 的 PASS 绑定的是重放前的候选指纹，对重放后的候选不构成放行依据；按 RULE-AI-28 对当前候选重新发起测试准入。

**受理与结论**：child `subagent_524af23f7ebf`（独立只读审查者，模型 glm/glm-5.3-flash），切片为 lane 全量 diff（11 条路径，切片外 tracked / untracked 均为 0），候选指纹 `429a47b1b8c9c2852c96032eb828b6c68e0377568c3d9fb2e53876caa9c3ab83`；执行前 status 回执 **PASS**，P0=0 / P1=0 / P2=4，指纹与受理时一致。

**发现（审查者原文要旨，P2 四条；均只归档、不在本次修订范围——P2 不阻塞入库，且修订会改变已测候选）**：

| 编号 | 位置 | 问题 | 处置 |
|---|---|---|---|
| P2-1 | `docs/trace/coverage-summary.md` 第 26 行 | 构成行「228 数据行 = unit 170 + pending 占位 46 + conformance 12」与它描述的 trace.csv 不符：按 diff 计 unit 182、pending 占位 34、conformance 12。总数 228、条目计数 13 / 11 / 35、逐文件函数数（合计 170）均正确；现有机检不覆盖这一拆分行 | 留待下一波修订文档：改为「unit 182 + pending 占位 34 + conformance 12」 |
| P2-2 | `docs/trace/trace.csv` 第 76、77、209 行 | 两条新增 C-4b-2 回归钉行的 `spec_entry` 带前导空格（" C-4b-2"），这两行与新增的 F-3 行 notes 带尾随空格；宽松解析下无碍，严格或外部解析器可能分出幽灵条目 | 留待下一波规范化空白 |
| P2-3 | `ctp/src/ctp_conformance/receipt.py` `is_limit` | 文档写「已配置的有限数值」，实现只拒绝 NaN，`is_limit(float("inf"))` 返回 True。当前所有 V4 调用都经 `_optional_limit` / `_in_range`（有 `math.isfinite`）屏蔽，但它是导出的辅助函数，新调用方直接用会漏掉 inf 限值检查——正是 r1 P1 修的那类问题 | 留待下一波：补有限性检查，或改名 / 改文档 |
| P2-4 | `ctp/src/ctp_conformance/v8.py` `run` | `n = int(config["n"])` 仍静默强转（`"1000"` 可用、`10.9` 被截断），与同函数刚收紧的 `include_forgery` 不一致 | 留待下一波：只接受非布尔的 int |

审查者另有一条不计入的观察：V4 runner 接受的分组阈值定义域（角点数 ≥ 0、比例 ∈ [0, 1]）宽于闸门 `ThresholdConfig`（≥ 1、(0, 1]），已在 conformance-runner-notes 说明；用闸门非法阈值跑 runner 只会出 `indeterminate`，不会报配置错误。

**审查者核对无问题的面（要旨）**：r1 P1 修订的三处实现与回归钉一致；V8 `include_forgery` 严格布尔；异常类改法在三个文件中等价且已被回归钉钉住；几何与文档一致；36h11 纠错预算与最小已知位数的论断成立；回执 343 与点阵算术、§15 的 46、函数清单合计 170、矩阵 228 及状态行 112 / 70 / 46 可复算；治理清单的变更路径划分无遗漏；36h11 归属声明完备；无密钥、网络、子进程或运行时导入面。

**随后的全量运行**：`pytest ctp/tests` → **343 passed in 2.72s**（退出码 0），回执 `ctp/receipts/20261125-wave3-pytest.md`。
