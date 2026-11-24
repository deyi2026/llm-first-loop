# CTP 一致性测试规程索引（V1–V8）

- 文档编号：CONF-CTP-INDEX-0.1
- 日期：2026-11-24
- 对应任务：PLAN-20261123-CTP-0.3 §3.1 A2（durable task TASK-e9f14fe1-002）
- 判据真相源：`docs/SPEC-20261123-cooperative-target-protocol-v0.9.md`（SPEC-20261123-CTP-0.9.2）。本目录任何表述与 SPEC 冲突时，以 SPEC 为准。
- 状态：全部规程**待实测**。SPEC 头部声明"结构冻结、数值未冻结……实测前禁止对外宣称任何性能数字"。

## 1. V1–V8 规程总表

| 编号 | 门槛名 | 判据条号（SPEC） | 主要依赖 | 状态 | 规程文件 |
|---|---|---|---|---|---|
| V1 | 自检时延（非合规判据） | §11.2 V1；§11.1-d；§13.1 Q1 | B3（读码器封装）；台架计量段 [需外部]（对应计划任务 C1） | 待实测 | [V1-latency.md](V1-latency.md) |
| V2 | 定位精度 | §11.2 V2；§5 C-5（uncertainty）；§11.1-b；§9 F-2（[TBD-F2] 像素口径，与 V2 分离） | C0 计量档期、B3、B2 [需外部]（对应 C2） | 待实测 | [V2-accuracy.md](V2-accuracy.md) |
| V3 | 公差带 | §11.2 V3；§4 P-2 / P-4 / P-5；§14 [TBD-V3α/β]、[TBD-P2a–c] | 独立制造批次 + 独立留出批次、C0 [需外部]（对应 C7） | 待实测 | [V3-tolerance-band.md](V3-tolerance-band.md) |
| V4 | 降级行为 | §11.2 V4；§5 C-4（a / b / b-2）；§11.1-e；§14 [TBD-V4a–d] | B4（阈值 + 双向抑制 + K7 影子通道）、B7（V4 runner）（对应 C3） | 待实测 | [V4-degradation.md](V4-degradation.md) |
| V5 | 投影标定 | §11.2 V5；§7 M-5；§5 C-5（degradation_flag）；§9 F-2 | 投影仪、B3 [需外部]（对应 C8）；PLAN 决策点 D-10 待裁决 | 待实测 | [V5-projection.md](V5-projection.md) |
| V6 | 跨厂商一致性 | §11.2 V6；§5 C-5 附加 b；§4 P-4（认证样本） | 第二独立实现（P2 预验证 → P3 正式，D-07 待裁决）、B2、认证样本 [需外部]（对应 C6） | 待实测 | [V6-cross-vendor.md](V6-cross-vendor.md) |
| V7 | 版本兼容 | §11.2 V7；§5 C-3；§10 VC-3 | B3 + 第二版本族图案（对应 C5） | 待实测 | [V7-version-compat.md](V7-version-compat.md) |
| V8 | fail-closed | §11.2 V8；§9 F-3 / F-4；§8 T-2 / T-4；§7 M-2 | B7（V8 runner）、C2（已验证的不确定度）、回退状态机实现（对应 C4） | 待实测 | [V8-fail-closed.md](V8-fail-closed.md) |

门槛名列中的括号注记仅为定位用简称；判据一律以各规程 §1 的逐字引用为准。

## 2. 如何读规程

每份规程固定六节，缺一即不完整（对应 PLAN §3.1 A2 验收口径"判据与 SPEC 11.2 逐字对应；含样本/设备/步骤/判据/回执/失败处置"）：

1. **目的与判据引用**——逐字摘录 SPEC §11.2 对应门槛行及相关条目原文（保留条号、行内加粗与代码标记），不改写、不转述；V1 额外写明"非合规判据"。
2. **前提与样本**——列出依赖的 B 任务（PLAN §4.2 / §5.2）、外部资源标记（`[可自执行]` / `[需外部]` / `[需裁决]`，PLAN §0.2 口径）与样本构造方式；V3 写明独立批次与留出批次，V4 写双向判据两组样本。
3. **设备与工具**——软件命令与版本口径；凡涉计量真值、台架、制造批次、第二实现、投影仪的项目标注 `[需外部]`。
4. **步骤**——编号步骤，标注失败中断点；遇需签字或外部资源的边界，登记阻塞并停下，不用"继续推进"代替签字（PLAN §12.5）。每份 §4 末尾另有一条**最小冒烟步骤**（A2 验收项）：无全量资源时先跑通样本链路与回执，**不产生门槛证据**，冒烟回执的 `simulated` 必须为 `true`。
5. **回执格式**——JSON 字段清单；V4 / V7 / V8 必须含 `simulated` 标注字段，其余门槛亦建议统一携带。
6. **失败处置**——按 SPEC §11.2 验证纪律：修订设计或补测，不放宽门槛。

**冒烟板命令（各规程冒烟步骤 (a) 共用；仓库根目录执行）**——打印输出目录与 `manifest_ok True`，目录内应有 `layout.json` / `board-matrices.json` / `target-board.pdf` / `manifest.json` 四件。2026-11-24 在 lane 工作树以仓库 `.venv` 解释器（Python 3.13）实测通过；板上每个码的物理坐标与参考系引用见 `layout.json` 的 `tags` / `frame_ref`。

```bash
./.venv/bin/python -c "import sys, tempfile; sys.path.insert(0, 'ctp/src'); from ctp_gen import Layout, PageSpec, TagSpec, generate, verify_manifest; out = tempfile.mkdtemp(prefix='ctp-smoke-'); generate([Layout(board_index=0, rows=2, cols=3, target_indices=(0, 1, 2, 3, 4, 5), page=PageSpec(297.0, 210.0, 10.0), tag=TagSpec(40.0, 6.0), frame_ref='frame:smoke/board')], out); print(out); print('manifest_ok', verify_manifest(out)['ok'])"
```

读法纪律：

- 规程只回答"怎么测、怎么判、怎么留证"；一切判据以 SPEC 原文为准，本目录不产生新判据；
- SPEC 带 `[TBD-…]` 标记的数值在对应门槛实测或工作组裁决前为空缺，"禁止以经验值填充"（SPEC §0 头部）；本目录所有 [TBD-*] 编号原样保留，并标注"待实测 / 待裁决回填"；回填按 SPEC §0.2 流程执行（保留 TBD 编号，在其后追加取值与回执编号）；
- 本目录不出现 SPEC / PLAN 之外的发明数值；样本量除 SPEC 已写明者（V3 N ≥ [TBD-V3β]、V4 N ≥ [TBD-V4d]、V6 N ≥ [TBD-V6a]、V8 注入 1000 个故障样本）外，一律写"由工作组定"；
- V1 是**非合规判据**（SPEC §11.2 V1 行原文标注），只作 11.1-d 声明与 V8 期望行为输入；
- 测试面分类按 SPEC §11.3：V4 / V7 / V8 属软件测试（合成数据先行）、V3 / V6 属物理测试、V1 / V2 / V5 属计量测试；"simulated 不得写成'实测'"（PLAN §0.4）。

## 3. 回执落盘约定

- 回执目录：`ctp/receipts/`（与现有 `ctp/receipts/20261124-b1b2-pytest.md` 同目录、同格式口径）；
- 文件名：`YYYYMMDD-V<编号>-<简述>.md`（例：`20261201-v4-degradation-synthetic.md`）；runner 产出的机器可读 JSON 以同名 `.json` 落盘，并在 md 回执内引用其路径；
- 每份回执必须包含：
  1. **命令**：verbatim（含工作目录与 lane worktree 内等价写法）；
  2. **环境**：OS、解释器与关键库版本、被测读码器 reader_id / reader_version；
  3. **输出**：verbatim 摘录 + 退出码；
  4. **head SHA**：运行时工作树 HEAD；若有未提交增量，必须声明"head + 增量"并保证运行后立即整体入库、入库内容与被测内容一致（对齐 `20261124-b1b2-pytest.md` 的"运行时基线"口径）；
  5. **simulated 标注**：V4 / V7 / V8 回执必填 `simulated: true|false`；缺标注按"未验证"处理（PLAN §15.5 G-C 回执闸）；
  6. **覆盖面与边界**：写明本次覆盖的判据子项与未测部分；
- "测试结果必须以全量实测回执归档；评审共识不构成'验证通过'"（SPEC §11.3-d）；
- 回执 JSON 字段若与 C-5 读取输出契约重叠，字段名以 `ctp/schema/observation.schema.json`（B1 已冻结，schema_version `ctp.c5/0.1`，九字段全必填）为准；新增回执字段走 T2 契约变更单（PLAN §15.2"共享面谁写"口径）。

## 4. 现状基线（as-of 2026-11-24，本 run 复核）

- 已落地：B1（C-5 契约）、B2（不确定度声明与传播）、B5（注册表原型 R-1–R-6）、B6（图案生成工具链）——由本 run `find ctp/src` 复核（`ctp_contract` / `ctp_calib` / `ctp_gen` / `ctp_registry` 四包与 schema；历史测试回执见 `ctp/receipts/`，最新计数以最新回执为准）；
- 未落地：B3 读码器、B4 阈值与双向抑制、B7 一致性 runner、B8 端到端探针——因此 V1–V8 全部"待实测"，V4 / V7 / V8 的合成面（B7 runner 路径）亦未具备；
- 工作组未组建（0 项 `[TBD-G]` 取得决议编号）、无计量档期、无第二实现（PLAN §1.2，as-of 2026-11-23 20:20 +08:00，此后每次开工先复核）。
