# 超时修复：最新main隔离集成（2026-10-17）

状态：隔离集成与受影响回归通过；独立合并审查待结算。未合main、未推送、未发布或重启。

- 新基线：`98cd1d1f7413c0213fbf2de25392c712781e6a8e`，较原41f基线仅增加P1 doctor两提交，变动cli/config/doctor/安装文档及对应测试/回执。AGENTS、安全手册与合并技能未变。
- 新分支：`fix/llm-timeout-main-98cd-20261017`。原修复及审查阻断留痕分别无冲突移植为`a701224f9`与`5a1b378fe`。原冻结分支保持不变。
- 四个修复代码/测试文件全文SHA不变，组合指纹`346563ad78647bbb7556ac04c5e18c61aab1c86355b471edf4979a0bf16408f5`；与上游变动路径无交叉。
- 17个受影响测试文件真实309 passed，exit0，17.34秒；覆盖超时与取消/settlement、既有故障矩阵及新doctor/config/application/factory/架构。Ruff和diff-check通过。
- 原完整R9的基线仍为41f：9297passed/146skip/1个并行失败，原脚本串行复核6/6通过后exit0；该日志已按原SHA复制保全。不能把原R9称为98cd新全量。
- 新基线是否需进一步全量及当前是否可合并，交独立合并审查按实际依赖与RULE-AI-34判定；主仓仍有其他Agent活跃未提交工作，不能仅凭路径不交叉直接切换main。
- 证据：`docs/governance/receipts/RECEIPT-20261017-llm-timeout-main-98cd-focused.json`，绑定focused原始日志SHA与当时main状态。

恢复条件：主仓写入所有者协调完成并自行提交/迁移；重新核验最新main、候选、审查覆盖和树状态。若main再次前进，先更新候选并复跑受影响gate，再取得最新merge PASS后执行合并及合并后冒烟。
