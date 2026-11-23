# CTP 参考实现（C-5 契约面）

本目录是 CTP 协议的参考实现，**不并入 `llm_loop` 包**，按"可整目录迁出为独立 repo"组织
（计划 §13.1 D-01 暂定 B）。当前完成 B1（C-5 读取输出契约）与 B2（不确定度声明与协方差传播）。

- 规范锚点：`docs/SPEC-20261123-cooperative-target-protocol-v0.9.md` v0.9.2 §5 C-5、§11.1-c、§11.2 V2/V4
- 计划锚点：`docs/PLAN-20261123-ctp-implementation.md` v0.3b §4.2 B1/B2、§15 执行编排
- 性质：契约 + 校验器 + 样本 + 不确定度数学；**不含**检测算法（B3）、阈值抑制（B4）

## 目录

```
ctp/
├── schema/observation.schema.json   # 规范性产物（JSON Schema 2020-12）
├── src/ctp_contract/                # 契约（零第三方依赖）
│   ├── model.py                     # Observation / Pose / Uncertainty / 枚举
│   ├── validate.py                  # collect_errors / parse_observation
│   └── errors.py                    # 稳定错误码
├── src/ctp_calib/                   # B2 不确定度数学（依赖 numpy）
│   ├── se3.py                       # 四元数 / exp-log / Adjoint（左扰动，[v,ω] 顺序）
│   ├── uncertainty.py               # 声明模板、一阶传播、蒙特卡洛自检
│   └── pixel.py                     # 角点像素噪声 → 6DoF 协方差（雅可比 + 真解算 MC）
├── docs/uncertainty-declaration-template.md  # 11.1-c 填写模板
└── tests/                           # 10 合法 + 22 非法样本 + schema 一致性 + B2 数学（含退化位形边界）
```

`ctp_contract` 保持零第三方依赖（契约要能跨语言重写）；`ctp_calib` 只为参考实现与自检服务，
依赖 `numpy`（仓库 `.venv` 已具备）。

## 跑测试

```bash
./.venv/bin/python -m pytest ctp/tests -q
```

不依赖安装：`ctp/tests/conftest.py` 把 `ctp/src` 追加进 `sys.path`；仓库 `.venv` 已带
`jsonschema` 与测试运行器。打包（`pyproject.toml`）留到迁出为独立 repo 时补，当前不落。

## 契约决定（待 G2 追认）

SPEC C-5 规定了九个必填字段，但以下实现细节在规范里没有写死，本实现取值如下。这些不是
规范的扩充，而是"契约落地必须先选一个"的工程决定；G2 契约闸时逐条追认或改写：

| # | 决定 | 理由 | 反例风险 |
|---|---|---|---|
| 1 | 顶层与 `uncertainty` 内允许 `x-` 前缀扩展字段，其余未知字段报 `unknown_field` | 拼写错误（`pose_t`）必须报错，不能静默丢弃；`x-` 给实现方留扩展位 | 若 G2 决定禁止扩展，去掉 `patternProperties` 即可 |
| 2 | 可选 `schema_version`，取值固定 `ctp.c5/0.1` | 契约自身需要版本位；缺省不填（不注入默认值） | 取值变更需升位并改 schema |
| 3 | 四元数模长容差 1e-3 | 拒绝非旋转四元数，但不因浮点误差误杀 | 容差数字是本实现决定，非规范数值 |
| 4 | 六路 1σ 全为 0 判 `degenerate_uncertainty` | 零不确定度会让 V6 阈值 `k·√(u₁²+u₂²)` 退化为 0，等于放弃声明 | 若确有零噪声场景，需工作组裁决 |
| 5 | `covariance_6x6` 可选，要求对称、对角非负；**单位 m²/rad²**（顺序 `[tx,ty,tz,rx,ry,rz]`），给出时以它为准 | B2 传播需要协方差；对称与符号是可机检的最小约束；单位与 1σ 的 deg 口径不同，必须显式声明（P0-1 教训） | PSD 在 B2 模板与 MC 入口已校验（特征值下界）；契约层只查对称（跨语言最小集，见 schema 分歧集合声明） |
| 6 | `timestamp` 必须带 UTC 偏移 | 采集时刻无时区即不可比；V1/V2 都要用它排序 | 若上游只给本地时间，必须补偏移后输出 |

## 错误码

`missing_field`、`type_error`、`unknown_field`、`enum_error`、`range_error`、
`linkage_error`、`format_error`、`quaternion_not_unit`、`timestamp_missing_timezone`、
`covariance_not_symmetric`、`degenerate_uncertainty`。

错误码是契约的一部分：实现方拒绝输出时必须给出可复核的码与字段路径，不得用默认值填充后
静默通过（K6 fail-closed）。

## 明确不做

- 不判断"读数是否正确"——观测是测量值 + 不确定度，不是真值（C-5 附加要求 a）；
- 不给任何性能数字——精度、时延阈值均为 `[TBD-*]`，实测前禁止宣称（SPEC §0.2）；
- 不 vendor 第三方源码（K4 指不复制源码入库）；运行依赖 numpy、测试依赖 jsonschema，均为常规依赖声明而非复制源码。
