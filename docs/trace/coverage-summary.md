# CTP 追溯矩阵覆盖总结（A3 交付，Wave-3 更新）

依据：SPEC-20261123-cooperative-target-protocol-v0.9.md（v0.9.2）第 4–10 章；ctp/tests/ 十六个测试文件只读盘点（2026-11-25；含 B3 读码器、B4 闸门、B7 一致性 runner、集成与异常传播回归钉；conformance_stubs.py 与 reader_testkit.py 为测试辅助模块非用例；docs/conformance/ 9 份规程已建、实测回执未产生）。

## 一、总体覆盖统计

条目计数口径：带字母子条（a/b/c、b-2）计独立可追溯单元；无子条按整条计。

| 章 | 层 | 条目数 | covered | partial | pending |
|---|---|---|---|---|---|
| 4 | 物理层 P-* | 11 | 0 | 2 | 9 |
| 5 | 编码层 C-* | 16 | 7 | 4 | 5 |
| 6 | 语义层 R-* | 6 | 6 | 0 | 0 |
| 7 | 组合层 M-* | 7 | 0 | 3 | 4 |
| 8 | 威胁模型 T-* | 9 | 0 | 0 | 9 |
| 9 | 回退状态机 F-* | 7 | 0 | 1 | 6 |
| 10 | 版本兼容 VC-* | 3 | 0 | 1 | 2 |
| 合计 | | 59 | 13（22.0%） | 11（18.6%） | 35（59.3%） |

covered 条目（13）：C-2a（36h11 码族与码空间）、C-2b（纠错预算内解码）、C-3b（unknown version 不输出 ID）、C-4a（阈值必填可配置）、C-4b（低于阈值不输出）、C-5（读取输出契约）、C-5a（观测=测量+不确定度）；R-1–R-6（B5 注册表原型）。

partial 条目（11）：P-3b、P-5b、C-1b、C-1d、C-4b-2、C-5b、M-1、M-3、M-5b、F-3、VC-3（逐条理由见第三节）。

测试资产：16 个测试文件 / 167 个测试函数（AST 静态计数：contract_valid 6、contract_invalid 6、schema_parity 5、uncertainty 13、pixel_uncertainty 7、generator 13、registry 33、gate 16、reader_decode 13、reader_observe 12、error_propagation 4、conformance_receipt 7、conformance_v7 6、conformance_v4 11、conformance_v8 8、integration_reader_conformance 7；每个函数在矩阵中有独立行）；参数化展开后的用例总数不在本文件手抄具体数字——单一真值为 ctp/receipts/ 最新回执（手抄计数已两轮漂移，r1/r2 审查 P1-1/P2-2，改引用制）；conformance 规程 9 份已建（docs/conformance/），V1–V8 以 12 行 pending 占位待实测回执。

矩阵规模：225 数据行 = unit 167 + pending 占位 46 + conformance 12；行级状态 covered 112 / partial 67 / pending 46。

## 二、pending 清单（35 条，按依赖分组）

A. 待计量/实测（10 条）——数值空缺须 P2 计量或门槛实测填充：
- P-1a：对比度 [TBD-P1] 计量；P-1b：镜面高光物理测量
- P-2a / P-2b / P-2c：公差带 [TBD-P2a–c]，依赖 G6 定带规则与批次抽检（V3）
- P-3c、P-4：认证样本材质与计量标定（实验室流程；P-4 同时是 V6 前置）
- P-5a：带外禁引精度声明，依赖 V3 定带后的流程管控
- F-2：MID→NEAR 角点残差阈值 [TBD-F2] 计量
- C-3c：新图案族版本的 V7 混合版本墙实测（规程 docs/conformance/V7-version-compat.md 已建，实测待跑）

B. 待工作组裁决（5 条）——[TBD-G] 类，需决策不需实测：
- C-1a / C-1c：前缀/本地段位长与分配机制（治理章程）
- C-3a：版本位载体设计待码族裁决
- P-3a：T0=20°C 工作组形式确认
- VC-2：规范/族版本解耦机制待码族裁决

C. 待实现（11 条）——载体（状态机 / 几何互证 / 投影模态）未落地：
- M-2a / M-2b：阵列成对几何登记 [TBD-M2] 与互证回退
- M-5a：投影模态
- T-4a（依赖 R-5）、T-4b（依赖 M-2b）、T-4d（依赖 a+b）、T-5（可校验通道）
- F-1 / F-4a / F-4b / F-4c：回退状态机本体与失败出口

D. 无测试义务/资料性（9 条）——规范明示非强制或属治理/部署侧：
- C-4c（劣化预警非本层强制）、M-4（标定室可选）、T-1（资产定义）、T-2 / T-3（载体为 V8，见 A/C 组关联）、T-4c（物理访问控制）、T-6（残余风险资料性）、F-5（状态图资料性）、VC-1（版本治理流程）

另：8 个门槛 V1–V8 全部 pending 实测（规程已建于 docs/conformance/，V4 / V7 / V8 的 runner 骨架已建且只用合成样本，实测回执未产生）；V2 / V3 / V6 需计量与认证样本。

## 三、partial 判定清单与理由（11 条）

1. P-3b：热形变须纳入不确定度预算——预算通道（k+1σ 声明+传播）已实现并测试（test_uncertainty_carries_k_and_one_sigma 等），但无热形变专项分量用例，[TBD-P3a] 待计量。
2. P-5b：可核查依据——确定性再生成（test_generate_is_deterministic）与清单防篡改（test_manifest_detects_tampering）构成机制侧证据；规范要求的批次抽检报告/认证样本谱系未实现。
3. C-1b：本地段唯一性——板内索引查重已实现（layout 重复索引拒收）；持有前缀机构的域级分配机制未实现。
4. C-1d：码内容量分层映射——契约/生成器侧已测；B3 提供 resolver 钩子（resolved / unresolved 已测），注册表解析路径尚未接通。
5. C-5b：双读码器一致性——k·√(u1²+u2²) 的 RSS 传播与 MC 验证已测（≤5% 一致）；两个合规读码器实体对比与 V6 实测未做。
（R-6 经 B5 落地后移入 covered；两级时效按 PROP G5 提案实现，强制等级 [TBD-G] 待裁。）
6. M-1：单靶 6DoF——B3 读码器已产出并测试 6DoF 观测（正对位姿、平移反投影、90° 旋转姿态）；「不应作唯一安全证据」为部署规则（T-3），无单测对象；平面 PnP 二义性（G7）未消解。
7. M-3：板/笼组合——板级结构校验与多板分页载体已测；「按 M-2 递归互证」未实现。
8. M-5b：投影模态降级——coarse 标记契约通道（v02 合法+i05 枚举严格）已测；投影前提自检与 V5 判据未实现。
9. F-3：带错硬接禁令——k×RSS 阈值的数学基础已验证；V8 runner 可演练漏检类（真读码器合成样本零带错输出、零静默），伪造/层级矛盾类未演练；阈值判定回路、回退动作与禁令执行未实现（依赖状态机）。
10. C-4b-2：达标侧漏检率受限——闸门保证达标样本永不被抑制，V4 runner 能统计漏检率；但 [TBD-V4c] / [TBD-V4d] 未配置，且比例阈值维度在合成样本上无法单独演练，漏检率只能等 V4 实测。
11. VC-3：发布门禁——V7 runner 已能对外来码字统计误读（真读码器合成样本零误读）；正式门禁须真实混合版本靶标墙实测。

## 已知缺口与建议（6 条）

1. 读码器只到 v0：B3 仅支持轴对齐单枚 36h11 的合成图；任意角度、透视、多靶同图、平面 PnP 二义性消解、真实打印件与相机实测（B8）、第二实现互比（V6）均未做。
2. 语义层已由 B5 落地（R-1–R-6 covered）；残余治理项：墓碑权威签名（DoS 面——任何能写 JSONL 的写者可追加 retire 封死绑定；retire_verifier 钩子已备，TODO-G2 首位）与 R-6 强制等级终裁。
3. 一致性 runner 只有合成样本：V4 / V7 / V8 的回执恒为 simulated；伪造/层级矛盾类样本依赖状态机与几何互证，未演练，V8 的 v0 回执恒为 indeterminate。
4. 状态机 F-1–F-5 未实现而 F-3 数学已备：建议实现最小回退判定回路（两级位姿差 vs k×RSS）以承接 V8；这是当前「数学已验证但行为零覆盖」的最大断层。
5. P-* 全 pending 属预期（数值未冻结、禁止经验值填充），但 P-3b 的热形变入预算可先落软件侧用例（uncertainty model 增加热分量声明并测试非负/单位），不必等 [TBD-P3a] 计量。
6. 异常类设计缺陷已修一处、同类排查未做：ContractError / RegistryError / ReaderError 曾是 frozen dataclass，穿过 contextlib 类上下文管理器时被 FrozenInstanceError 顶替而丢失错误码；本波改为字段只读的普通 dataclass 并加回归钉。全仓其余 frozen dataclass 异常的同类排查不在本波范围。
