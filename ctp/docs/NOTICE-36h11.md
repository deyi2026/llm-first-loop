# 归属声明：36h11 码表与读码器（B3 / B6）

## 36h11 码字来源

- 上游项目：AprilTag 3（仓库 AprilRobotics/apriltag）
- 许可：BSD 2-Clause（版权 The Regents of the University of Michigan，2013–2016）
- 入库位置：`ctp/docs/upstream/apriltag-tag36h11.c`（上游码表数据文件，许可头完整保留）
- 本仓使用方式：`ctp/src/ctp_gen/tag36h11_table.py` 从该文件读取 587 个 36 位码字、36 个数据位坐标
  （`BIT_X` / `BIT_Y`，取值 1–6）与码族常量（最小汉明距离 11、边框宽 8、总宽 10）。

## 读码器（ctp_reader）与生成器（ctp_gen）的代码来源

- `ctp_gen`（位图渲染、布局、清单）与 `ctp_reader`（定位、解码、位姿、闸门）均为本项目原创实现，
  **未复制** AprilTag 的检测器 / 解码器源码；两者只消费上述码表数据。
- 依赖：`numpy`（数值）、`cryptography`（注册表签名，与读码器无关）。读码器本身不依赖 OpenCV。

## 义务与待裁决

- 分发时须保留上游版权声明、许可条件与免责声明（BSD-2 条款）；本文件与上游文件头的许可文本共同构成该保留。
- 是否以"入库上游数据文件"的形式长期保留（而非改为纯生成或其他分发方式），待契约闸（G2）裁决；
  在裁决前，本目录是"不复制第三方源码"（计划 K4 / 风险 R-04）的唯一显式例外。
