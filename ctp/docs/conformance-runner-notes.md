# 一致性 runner 骨架说明（B7）

对应计划 §4.2 B7：三个 runner（V4 / V7 / V8）+ 机器可读 JSON 回执；合成数据跑通；`simulated` 显式标注。
判据出处：SPEC-20261123-CTP-0.9.2 §11.2（V4 双向判据、V7 混合版本墙误读 = 0、V8 按故障类型分派）；
可执行规程见 `docs/conformance/V4-degradation.md`、`V7-version-compat.md`、`V8-fail-closed.md`。

## 1. 回执（receipt.py）

| 字段 | 内容 |
|---|---|
| suite | V4 / V7 / V8 |
| simulated | 恒为 true——v0 只有合成样本，构造回执时传 false 直接报错（不冒充实测） |
| sample_set_sha256 | 样本描述列表（sample_id / fault_type / expected / 图像内容 sha256 / 几何真值）的确定性 JSON 的 sha256 |
| thresholds_used | 调用方给出的阈值与上限；未配置的保留 `[TBD-*]` 标签或记 not_configured |
| counts | 分类型计数 |
| verdict | pass / fail / indeterminate |
| failures / not_exercisable | 硬断言失败清单 / 无法演练的样本及原因 |
| reader | 被测读码器身份（取不到记 unknown，不猜） |

判定规则：有硬断言失败 → fail；无失败但有未演练样本或未配置上限 → indeterminate；否则 pass。

"未配置"不只指没给：调用方给了但不可用的值（None、NaN、bool、非数值、±inf、越界）同样按未配置处理，
并在回执 notes 留痕——不可用的上限不得当作"已配置"而被跳过检查（2026-11-25 测试准入审查 r1 的 P1）。

## 2. 合成样本（synth.py）

由 `ctp_gen.codes.bit_matrix` 渲染单靶灰度图（每格 12 像素、核外 4 格静区，均为测试参数），固定 seed 可复现。

| 故障 | 构造 | 几何真值 |
|---|---|---|
| 裁边 | 裁到边框以内：上+左 / 仅左 / 左+上+右 | 完整角点 1 / 2 / 0（矩形裁剪裁掉整条边，不存在"只裁一个角"） |
| 裁数据列 | 再向内裁一格 | 可见角点 2、数据位可见比例 5/6 |
| 外来码字 | 在合法码上翻转 6 位，直到四个取向下与码表最小汉明距离都 > 5 | 超出纠错能力 |
| 无关图案 | 黑边框 + 随机数据区，同样保证四取向都超出纠错能力 | 非 36h11 |
| 不可读 | 数据区置均匀灰 ± 微噪声，边框保留 | 信息已毁、靶标仍可定位 |

## 3. 三个 runner 各自断言什么

- **V7**：外来码字 / 无关图案被输出任何 ID 即误读；误读必须为 0。已知族样本被拒读不计失败（属漏检侧）。
- **V4**：按调用方阈值把样本分成低于阈值组与达标组。低于阈值组出现任何输出即误读（必须为 0）；
  达标组漏检率 = 未产生观测的达标样本 / 达标样本数；"永不输出"（达标组无一输出）判不通过；
  漏检率上限 `[TBD-V4c]` 与样本量 `[TBD-V4d]` 未配置时只能 indeterminate；`miss_rate_limit` 须为 [0, 1] 内的
  有限数值、`min_sample_size` 须为 ≥ 1 的有限数值，否则按未配置处理。分组阈值 `min_visible_corners`（≥ 0）与
  `min_visible_data_ratio`（[0, 1]）缺失或不可用则直接拒绝运行（分组做不了，不产出回执）。
- **V8**：漏检类（遮挡 / 超纠错 / 不可读）要求"不输出 + 带码报错"；给出 ID 是带错输出，静默是违例。
  伪造 / 层级矛盾类（错 ID、复制靶标、级间位姿矛盾）期望 STOP + 报警，但回退状态机（F-1–F-5）与
  几何互证（M-2b）均未实现——标 not_exercisable，不计入"带错硬接 = 0"的断言范围。
  `include_forgery` 只接受 JSON 布尔：给了 `"false"` / null 之类非布尔值直接拒绝运行，不做 bool() 强转
  （强转会静默改变演练范围）。

## 4. 命令行

在 worktree 根执行（`--simulated` 必填）。`ctp/` 是 src 布局、未安装为包，须把 `ctp/src` 放进 `PYTHONPATH`
（`ctp/tests/conftest.py` 为 pytest 做的是同一件事；不带它会 `ModuleNotFoundError: No module named 'ctp_conformance'`），
解释器用仓库共享 `.venv`（numpy 等依赖已在其中）：

    PYTHONPATH=ctp/src ../../.venv/bin/python -m ctp_conformance.v7 --simulated --reader-spec <spec.json> --out <receipt.json>
    PYTHONPATH=ctp/src ../../.venv/bin/python -m ctp_conformance.v4 --simulated --reader-spec <spec.json> --config '{"min_visible_corners":4,"min_visible_data_ratio":1.0}' --out <receipt.json>
    PYTHONPATH=ctp/src ../../.venv/bin/python -m ctp_conformance.v8 --simulated --reader-spec <spec.json> --n 1000 --out <receipt.json>

`reader-spec.json` 含 thresholds（路径）、camera{fx,fy,cx,cy}、tag_size_m、sigma_px、coverage_factor_k、
reader_id、reader_version、frame_ref。退出码：pass 为 0，其余为 1。

## 5. v0 不能演练的内容（如实）

1. 伪造类与层级矛盾类全部样本（见上）——因此 V8 的 v0 回执恒为 indeterminate。
2. "角点达标但数据位可见比例低于阈值"的样本：裁到数据列必然先裁掉边框角点；当比例阈值 < 1 时该维度
   标 not_exercisable，等 V4 实测。
3. 真实打印件、真实相机、光照 / 入射角 / 距离变化——全部不在此处；门槛判定一律以实测回执为准。
4. 读码器的证据口径是"完整落在图像内"；遮挡但在图像内的数据格计入可见，遮挡造成的位错误由纠错能力
   与 unknown_version 兜底。这是偏严方向的近似，V4 实测须复核。

## 6. 与其他任务的关系

读码器按协议注入（`read(image, *, timestamp, ...)` → `ctp_contract.Observation`，失败抛带 `code` 的异常）；
本包顶层不 import `ctp_reader`，单元测试用 `ctp/tests/conformance_stubs.py` 的协议桩。
