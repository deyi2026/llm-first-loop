# 图案生成工具链 v0（B6）说明

## 交付物与用法

`ctp_gen.generate(layouts, outdir)` 产出四件：`layout.json`（布局）、
`board-matrices.json`（每靶 10×10 位图真值，B3 的对照锚点）、`target-board.pdf`
（打印版式）、`manifest.json`（哈希清单）。`ctp_gen.verify_manifest(outdir)` 复核。

## 码字来源（K4 / R-04）

- 表与位映射逐字取自 `ctp/docs/upstream/apriltag-tag36h11.c`（AprilRobotics/apriltag，
  **BSD-2-Clause**，Copyright 2013-2016 The Regents of The University of Michigan；
  文件头保留完整许可与版权声明）。
- 提取脚本生成 `ctp/src/ctp_gen/tag36h11_table.py`；
  `test_generator.py::test_table_regenerates_from_upstream_source` 钉死两者一致。
- 未使用无 LICENSE 的 apriltag-generation 仓库（SPEC §12.1-a 的红线）。
- 自检：587 码、36 bit、成对最小汉明距离实测 = 11（与族声明一致）。

## 渲染口径（钉定，B3 必须一致）

- 10×10 单元格 = 1 圈白 quiet zone + 8×8 核（外圈黑边）+ 6×6 数据区；
- bit i（0 起，**MSB 在前**：bit 0 = 码字第 35 位）落在 `(BIT_X[i]+1, BIT_Y[i]+1)`；
- 与 AprilTag 官方检测器的**互操作位序**未经实测验证——V6 跨实现前必须复核，
  复核前 B3 以本文档与 `board-matrices.json` 为唯一真值。

## 参考系、逐码坐标与公差标注（B6 验收项，2026-11-24 补齐）

- `frame_ref`（**必填**）：本板坐标系的参考系定义引用（SPEC §2「参考系定义」= 靶标坐标系相对其所属
  对象坐标系的安装几何描述），与 R-1 记录、C-5 pose 的 `frame_ref` 同口径。生成器只校验非空、不解析；
  缺失或空白即拒绝，不做默认值填充。解析（引用 → 安装几何）属 R-1 / B5。
- `coordinate_frame` + `tags`：`layout.json` 逐码显式给出 `target_index`、左上角 `x_mm/y_mm`
  （渲染口径）与中心 `center_x_mm/center_y_mm`（B3 位姿解算用）；原点 = 页面左上角，x 向右、
  y 向下，单位 mm。`tags` 是几何的派生块——文件内给出时必须与网格几何一致，手改坐标会被
  `layout_from_dict` 拒绝（`test_layout_from_dict_rejects_tampered_tag_coordinates`）。
- `tolerance`：`P-2a`（角点边长制造公差）/ `P-2b`（平面度）/ `P-2c`（安装平面度）三个键对应
  SPEC P-2 子条，值恒为 SPEC 现行的 TBD 占位编号 `[TBD-P2a/b/c]`——**不是数值**，工作组回填前
  不得改写为经验值；SPEC v1.0 回填后须同步更新 `TOLERANCE_PLACEHOLDERS`。
  `grade` 是申报方给的公差等级标签（自由文本），未申报时如实写 `unspecified`（P-5：未申报等级的
  靶标不得引用精度声明）。
- `LAYOUT_VERSION` 保持 1：v0 未发布、无存量消费者，上述字段并入首版，不另升位。

## 分层映射（G1 口径）

- 码内承载 `target_index`（板内索引，域 0..586，对应 C-5 `target_index`）；
- `logical_id`（前缀+本地段 48bit）不在码内，由 B5 注册表按板级登记解析
  （`layout.logical_mapping` 预留该绑定说明）。

## 单位与确定性

- 版面物理量一律 mm；PDF 输出换算为 pt（A3 = 842×1191pt）；
- `reportlab.rl_config.invariant = 1` 关闭时间戳，实测 layout/matrices/PDF 三件
  **字节级可复现**（`test_generate_is_deterministic` 钉住）。

## 明确不做 / 待决

- 打印公差、材质、对比度门槛 = `[TBD-P1/P2*]`，归 SPEC 物理层，不在生成器设定；
- "打印后可被 B3 读通"的验收在 B3 落地后回填回执（计划 §4.2 B6 行）；
- `gap_mm`/`margin_mm` 为工程默认（6/10mm），可调，非规范数值。
