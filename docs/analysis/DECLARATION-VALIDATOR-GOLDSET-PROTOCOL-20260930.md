# Declaration Validator Gold-Set Protocol（冻结版，2026-09-30）

> **冻结状态**：本文档为 P3 gold set 的准入协议与分类纪律冻结版（Git tracked）。
> 临时调查细节与 5 条人工判断保留在 `docs/local/TAXONOMY-20260930-declaration-false-cohort.md`；
> 两处不一致时以本文档为准。冻结解除条件见 §5。

## 1. 背景与动机

- `honesty_rate` 已于 EVO-20260930 修复为条件率（分母 = 有声明检查记录），
  本协议约束**下一层**：False 归因与抽取器/匹配器改动的准入。
- 核心事实：False 桶不是单一"抽取器问题桶"，是流水线
  （claim detection / evidence attribution / receipt matching 三层故障并存）。
- 历史惯性（禁止重演）：0815 以来每次误报治理都往"加豁免正则/盲扩词表"方向走，
  无 recall 度量兜底——本协议以双门取代该惯性。

## 2. 冻结的词表与豁免纪律

1. 抽取器词表（29 个声明动词）冻结：不为单条误报盲扩词、盲加豁免。
2. 任何豁免（句式特征、inline-code、引用等）必须：
   a. 基于文本 provenance/结构事实，不猜语义；
   b. 配 gold-set 反例（真执行声明不被该豁免放过的用例）。
3. 已有豁免基线：fence/表格/引用行/inline code span（动词全落 span 内才豁免，
   EVO-20260930）。

## 3. gold set 构成要求（≥100 条）

必须覆盖：
1. 已验证**真阳性**（真实幻觉，含身份声明类——历史上曾正确捕获，不可为降误报豁免）；
2. 否定句（"未执行 X"）；
3. 计划句（"接下来将执行 X"）；
4. 引用/inline-code 引用（转述历史审计/证据文本，EVO-20260930 已修边界）；
5. 状态描述句（"待处理：N"类，非行为声明）；
6. 建议句（"建议删除 X"，非已执行动作）；
7. 产物完成声明（"DOCX 已生成"——匹配面问题）；
8. 对产物内容的事实陈述（"条款 X 已写入协议"——evidence attribution 层）。

## 4. 双门验收（每次抽取器/matcher 改动）

1. 报 precision **和** recall 双指标；
2. precision 修复不得以 recall（放过真实幻觉）为代价且无度量可查；
3. taxonomy 稳定判据：连续两批人工标注分布一致，方可冻结 v1。

## 5. 观察口径纪律（报告措辞）

- seed 标注结果只写 `0/5 observed in this labeled seed` 形态，
  **不得**外推为"当前 validator 真实幻觉率 0%"（False-only 样本 + 单时间窗无患病率意义）；
- honesty 数字仅按当前 `validator_version` cohort 解读（消费侧隔离 EVO-20260930.1），
  重启过渡期当前代次 <5 条 claim-bearing 行时如实 N/A。

## 6. 后续（P3 启动前置）

- 当前代次（`validator_version=2026.09.30`）累计 20–30 条 claim-bearing 行后，
  再评估启动 100+ gold set 标注与 P4 per-claim verdict 结构改造。
