# CTP 规范条目—测试用例追溯矩阵（人读版）

- 规范：docs/SPEC-20261123-cooperative-target-protocol-v0.9.md（v0.9.2）第 4–10 章
- 测试资产：ctp/tests/ 8 个测试文件、83 个测试函数（AST 静态计数，明细见孤儿检查节；其中 test_trace_matrix.py 是矩阵自身的元测试，其 3 个用例不属规范覆盖、不入矩阵也不计数；conftest.py 为路径配置非用例；fixtures：合法 10 + 非法 24）；参数化展开后的用例总数不在此手抄——单一真值为 ctp/receipts/ 最新回执
- 一致性规程：docs/conformance/ 已建 9 份（README + V1–V8），实测回执未产生，仍以 test_kind=conformance 的 pending 行预留（共 12 行）
- 机器可读版：trace.csv（列：spec_entry,test_kind,test_id,evidence_path,status,notes）
- 状态口径：covered=已有测试足以支撑条目的可测内容；partial=已有测试仅覆盖条目的一部分（或仅契约/机制侧）；pending=无测试（依赖计量/裁决/实现，或明示无测试义务）
- 条目计数口径：带字母子条的按子条计独立单元（如 C-4b-2）；无子条的按整条计

条目总数 59：covered 9 ｜ partial 9 ｜ pending 41。矩阵数据行 146：covered 74 ｜ partial 21 ｜ pending 51。

## 第 4 章 物理层（11 条：covered 0 / partial 2 / pending 9）

| 条目 | 类型 | 测试/规程 | 证据 | 状态 | 备注 |
|---|---|---|---|---|---|
| P-1a | pending | - | - | pending | 哑光与≥[TBD-P1]对比度属印刷材质计量 |
| P-1b | pending | - | - | pending | 镜面高光抑制属物理测量 |
| P-2a | pending | - | - | pending | [TBD-P2a]待G6定带 |
| P-2a | conformance | V3 | docs/conformance/V3-tolerance-band.md | pending | 定带+留出批次落带 |
| P-2b | pending | - | - | pending | 平面度计量待P2 |
| P-2c | pending | - | - | pending | 安装侧计量 |
| P-3a | pending | - | - | pending | T0=20°C待工作组确认 |
| P-3b | unit | test_uncertainty_carries_k_and_one_sigma | ctp/tests/test_contract_valid.py:58 | partial | 预算通道已测；热形变分量未落地 |
| P-3c | pending | - | - | pending | 材质选择无测试对象 |
| P-4 | pending | - | - | pending | 计量标定+证书属实验室流程 |
| P-5a | pending | - | - | pending | 依赖V3定带 |
| P-5b | unit | test_generate_is_deterministic | ctp/tests/test_generator.py:106 | partial | 确定性再生成=机制侧依据 |
| P-5b | unit | test_manifest_detects_tampering | ctp/tests/test_generator.py:128 | partial | 清单防篡改；非完整谱系 |
| P-5b | unit | test_layout_json_carries_frame_ref_tag_coordinates_and_tolerance | ctp/tests/test_generator.py:165 | partial | 公差标注（P-2a/b/c 键 + TBD 占位）与 grade 申报随布局落盘；数值与抽检依据未实现 |

小结：物理层按预期几乎全 pending（数值未冻结、无计量）。唯二 partial 均为「机制侧已备、计量侧未到」：P-3b 的不确定度预算通道、P-5b 的可核查依据机制。

## 第 5 章 编码层（16 条：covered 3 / partial 3 / pending 10）

| 条目 | 类型 | 测试/规程 | 证据 | 状态 | 备注 |
|---|---|---|---|---|---|
| C-1a | pending | - | - | pending | 前缀注册/互斥机制未实现 |
| C-1b | unit | test_layout_validation_rejects_bad_payloads | ctp/tests/test_generator.py:87 | partial | 板内查重已实现；域级分配未实现 |
| C-1c | pending | - | - | pending | Q9裁决条款；随C-1a落地 |
| C-1d | unit | test_layout_roundtrip_through_json | ctp/tests/test_generator.py:100 | partial | 分层映射结构；R-1解析未实现 |
| C-1d | unit | test_valid_fixture_parses[v03_unresolved_null] | ctp/tests/test_contract_valid.py:26 | partial | unresolved状态契约层可表达 |
| C-1d | unit | test_layout_json_carries_frame_ref_tag_coordinates_and_tolerance | ctp/tests/test_generator.py:165 | partial | 布局 JSON 逐码物理坐标 + frame_ref（参考系引用）；R-1 解析属 B5 |
| C-1d | unit | test_layout_rejects_missing_or_blank_frame_ref | ctp/tests/test_generator.py:195 | partial | frame_ref 缺失/空白拒收（应拦） |
| C-1d | unit | test_layout_from_dict_rejects_tampered_tag_coordinates | ctp/tests/test_generator.py:205 | partial | tags 块与几何不一致即拒收（应拦） |
| C-2a | unit | test_table_regenerates_from_upstream_source | ctp/tests/test_generator.py:47 | covered | 码表与上游逐字一致 |
| C-2a | unit | test_family_invariants_hold | ctp/tests/test_generator.py:58 | covered | 587码字、min Hamming≥11 |
| C-2a | unit | test_bit_matrix_structure_matches_convention | ctp/tests/test_generator.py:65 | covered | 位图结构约定 |
| C-2a | unit | test_code_at_rejects_out_of_range | ctp/tests/test_generator.py:82 | covered | 码空间边界（3例） |
| C-2a | unit | test_layout_validation_rejects_bad_payloads | ctp/tests/test_generator.py:87 | covered | family=42h7拒收 |
| C-2b | pending | - | - | pending | 解码纠错行为未实现 |
| C-3a | pending | - | - | pending | 版本位未进36h11位图 |
| C-3b | pending | - | - | pending | 读码器未实现 |
| C-3c | conformance | V7 | docs/conformance/V7-version-compat.md | pending | 混合版本墙门禁 |
| C-4a | pending | - | - | pending | [TBD-V4a/V4b]未定 |
| C-4a | conformance | V4 | docs/conformance/V4-degradation.md | pending | 误读率=0判据 |
| C-4b | pending | - | - | pending | 输出抑制行为未实现 |
| C-4b | conformance | V4 | docs/conformance/V4-degradation.md | pending | 宁可漏检不可错读实测 |
| C-4b-2 | pending | - | - | pending | 漏检率统计须实测 |
| C-4b-2 | conformance | V4 | docs/conformance/V4-degradation.md | pending | 防「永不输出」 |
| C-4c | pending | - | - | pending | 非本层强制；无测试义务 |
| C-5 | unit | test_fixture_set_is_not_vacuous 等 8 例 | ctp/tests/test_contract_valid.py:21–66 | covered | 合法侧：非空泛/解析/round-trip/九字段/k+1σ/协方差单位/v05扩展/v10版本字段 |
| C-5 | unit | test_fixture_set_is_not_vacuous 等 8 例 | ctp/tests/test_contract_invalid.py:45–76 | covered | 非法侧：24例错误码稳定/路径可复核/linkage（i06/i07）/根类型/非有限数 |
| C-5 | unit | test_schema_is_valid_against_metaschema 等 5 例 | ctp/tests/test_schema_parity.py:50–80 | covered | schema/validator双实现等价、分歧集合钉死（跨语言合规基础） |
| C-5 | unit | test_rotation_sigma_is_converted_from_degrees 等 8 例 | ctp/tests/test_uncertainty.py:64–184 | covered | 不确定度声明/传播/SE(3)数学载体/fail-closed应拦输入 |
| C-5 | unit | test_jacobian_matches_numeric_differentiation 等 6 例 | ctp/tests/test_pixel_uncertainty.py:44–113 | covered | 像素→位姿推导：雅可比/MC一致/退化如实判失败/σ²缩放 |
| C-5 | conformance | V2 | docs/conformance/V2-accuracy.md | pending | 精度—条件曲线3σ实测 |
| C-5a | unit | test_template_declaration_is_accepted_by_c5 | ctp/tests/test_uncertainty.py:37 | covered | 观测=测量+不确定度；声明可直接填C-5 |
| C-5b | unit | test_relative_covariance_agrees_with_monte_carlo | ctp/tests/test_uncertainty.py:88 | partial | RSS传播基础已验证；双读码器V6未做 |
| C-5b | unit | test_monte_carlo_is_reproducible | ctp/tests/test_uncertainty.py:112 | partial | V6统计基础 |
| C-5b | unit | test_rotation_only_uncertainty_couples_only_through_force_arm | ctp/tests/test_uncertainty.py:145 | partial | 伴射结构钉 |
| C-5b | conformance | V6 | docs/conformance/V6-cross-vendor.md | pending | 跨厂商一致性判据 |
| C-5b | unit | test_singular_covariance_is_typed_failure | ctp/tests/test_uncertainty.py:192 | partial | 奇异协方差类型化失败（应拦）；k·√ 判据可计算性的边界 |

小结：编码层是当前覆盖重心。C-5（输出契约，35 行 unit 证据）、C-5a、C-2a（36h11 码族）covered；C-1b/C-1d/C-5b partial——均为「结构/数学已测、注册表解析或双实体实测未到」。C-2b/C-3*/C-4* 依赖读码器与阈值实测，pending。

## 第 6 章 语义层（6 条：covered 6 / partial 0 / pending 0）

| 条目 | 类型 | 测试/规程 | 证据 | 状态 | 备注 |
|---|---|---|---|---|---|
| R-1 | unit | test_roundtrip_deterministic_json | ctp/tests/test_registry.py:82 | covered | B5 记录：字段集+签名+确定性 JSON |
| R-1 | unit | test_rejects_invalid_fields | ctp/tests/test_registry.py:108 | covered | 非法字段显式拒收（9 个参数化应拦例：周期/版本/时区/日期/ID/签名格式） |
| R-1 | unit | test_rejects_unknown_and_missing_dict_keys | ctp/tests/test_registry.py:115 | covered | from_dict 缺键/多键均拒收 |
| R-2 | unit | test_append_then_replay_chain_consistent | ctp/tests/test_registry.py:132 | covered | append-only：链一致/改写/删行检测 |
| R-2 | unit | test_no_delete_or_rewrite_api | ctp/tests/test_registry.py:149 | covered | 无删除/改写接口（append-only 的结构保证） |
| R-2 | unit | test_rewritten_line_detected_as_tampered | ctp/tests/test_registry.py:163 | covered | 改写行被检出（payload_tampered） |
| R-2 | unit | test_deleted_line_breaks_chain | ctp/tests/test_registry.py:177 | covered | 删行断链（chain_broken） |
| R-2 | unit | test_unsigned_register_refused_at_append | ctp/tests/test_registry.py:189 | covered | 无签名记录拒入链 |
| R-2 | unit | test_version_regression_refused | ctp/tests/test_registry.py:195 | covered | record_version 不递增即拒 |
| R-2 | unit | test_supersede_appends_new_version | ctp/tests/test_registry.py:202 | covered | 更新=追加新版本事件 |
| R-3 | unit | test_retire_creates_terminal_tombstone | ctp/tests/test_registry.py:215 | covered | 墓碑终态/复用拒绝；权威签名钩子=TODO-G2 首位 |
| R-3 | unit | test_tombstoned_id_reuse_refused | ctp/tests/test_registry.py:232 | covered | 墓碑 ID 复用拒收（tombstone_reuse） |
| R-3 | unit | test_retire_unknown_id_refused | ctp/tests/test_registry.py:244 | covered | 报废未知 ID 拒收 |
| R-3 | unit | test_bind_tombstoned_id_refused | ctp/tests/test_registry.py:253 | covered | 墓碑 ID 语义绑定拒收 |
| R-3 | unit | test_retire_verifier_vetoes_retire | ctp/tests/test_registry.py:474 | covered | retire_verifier 钩子拒未授权报废（DoS 面缓解） |
| R-4 | unit | test_offline_verification_succeeds | ctp/tests/test_registry.py:282 | covered | 两级签名快照与离线校验 |
| R-4 | unit | test_tampered_snapshot_rejected | ctp/tests/test_registry.py:290 | covered | 篡改快照→快照级验签失败 |
| R-4 | unit | test_tampered_record_inside_snapshot_rejected | ctp/tests/test_registry.py:300 | covered | 篡改单条记录→记录级验签失败 |
| R-4 | unit | test_broken_and_unsigned_snapshots_rejected | ctp/tests/test_registry.py:310 | covered | 结构损坏/未签名快照拒收 |
| R-4 | unit | test_snapshot_created_at_requires_iso8601_with_timezone | ctp/tests/test_registry.py:325 | covered | created_at 非带时区 ISO 8601 即拒（应拦） |
| R-4 | unit | test_snapshot_excludes_tombstoned_id_even_if_reregistered | ctp/tests/test_registry.py:336 | covered | 手写链重登记的墓碑 ID 不回快照（应拦） |
| R-5 | unit | test_bind_signed_record_succeeds | ctp/tests/test_registry.py:361 | covered | 绑定验签：篡改/无签名/错权威 |
| R-5 | unit | test_tampered_record_fails_signature | ctp/tests/test_registry.py:368 | covered | 篡改记录验签失败 |
| R-5 | unit | test_unsigned_record_binding_refused | ctp/tests/test_registry.py:376 | covered | 无签名记录拒绝语义绑定 |
| R-5 | unit | test_unknown_id_binding_refused | ctp/tests/test_registry.py:389 | covered | 未知 ID 拒绝绑定 |
| R-5 | unit | test_wrong_authority_key_rejected | ctp/tests/test_registry.py:395 | covered | 错权威公钥拒收 |
| R-5 | unit | test_binding_requires_chain_integrity | ctp/tests/test_registry.py:402 | covered | 链不完整拒绝绑定 |
| R-6 | unit | test_two_level_classification | ctp/tests/test_registry.py:429 | covered | 两级时效（PROP G5 提案待追认）；强制等级[TBD-G] |
| R-6 | unit | test_period_comes_from_record_not_constant | ctp/tests/test_registry.py:434 | covered | 复验周期取自记录而非常量 |
| R-6 | unit | test_no_hardcoded_period_defaults | ctp/tests/test_registry.py:440 | covered | 反射断言无硬编码周期默认值 |
| R-6 | unit | test_quarantine_blocks_binding_with_g5_note | ctp/tests/test_registry.py:451 | covered | 2× 周期超期隔离并带 G5 待追认标注 |
| R-6 | unit | test_pending_revalidation_does_not_block_binding | ctp/tests/test_registry.py:460 | covered | 一级待复验不拦绑定（G5 提案） |
| R-6 | unit | test_naive_now_rejected | ctp/tests/test_registry.py:467 | covered | 无时区 now 拒收 |

小结：B5 注册表原型落地后 R-1–R-6 全部 covered（test_registry.py；用例数以最新回执为准）；残余治理项（墓碑权威签名 DoS 面、R-6 强制等级）登记于 ctp/docs/registry-notes.md TODO-G2。

## 第 7 章 组合层（7 条：covered 0 / partial 3 / pending 4）

| 条目 | 类型 | 测试/规程 | 证据 | 状态 | 备注 |
|---|---|---|---|---|---|
| M-1 | unit | test_noise_free_solve_returns_nominal_pose | ctp/tests/test_pixel_uncertainty.py:105 | partial | 单靶6DoF解算已测；安全边界为部署规则 |
| M-2a | pending | - | - | pending | 成对几何登记与[TBD-M2]未实现 |
| M-2b | pending | - | - | pending | 互证→F-3回退未实现 |
| M-3 | unit | test_layout_validation_rejects_bad_payloads | ctp/tests/test_generator.py:87 | partial | 板级结构校验；递归互证未实现 |
| M-3 | unit | test_generate_pdf_is_valid_and_paged | ctp/tests/test_generator.py:117 | partial | 多板分页物理载体 |
| M-3 | unit | test_render_rejects_mixed_page_sizes | ctp/tests/test_generator.py:140 | partial | 混页尺寸显式拒绝（防静默裁剪；应拦） |
| M-4 | pending | - | - | pending | 可选设施；无合规要求 |
| M-5a | pending | - | - | pending | 投影模态未实现 |
| M-5b | unit | test_valid_fixture_parses[v02_resolved_coarse] | ctp/tests/test_contract_valid.py:26 | partial | coarse契约通道；前提自检未实现 |
| M-5b | unit | test_invalid_fixture_rejected_with_expected_code[i05_degradation_trailing_space] | ctp/tests/test_contract_invalid.py:55 | partial | 降级枚举严格性 |
| M-5b | conformance | V5 | docs/conformance/V5-projection.md | pending | 投影前提判据 |

小结：板级组合的结构与载体有 partial 支撑；阵列级登记互证（M-2）与投影模态（M-5a）未动工。

## 第 8 章 威胁模型（9 条：covered 0 / partial 0 / pending 9）

| 条目 | 类型 | 测试/规程 | 证据 | 状态 | 备注 |
|---|---|---|---|---|---|
| T-1 | pending | - | - | pending | 资产定义条目；间接承载 |
| T-2 | pending | - | - | pending | 载体为V8注入故障集 |
| T-3 | pending | - | - | pending | 载体为V8伪造类期望行为 |
| T-4a | pending | - | - | pending | 依赖R-5 |
| T-4b | pending | - | - | pending | 依赖M-2b |
| T-4c | pending | - | - | pending | 场景设施无软件对象 |
| T-4d | pending | - | - | pending | 依赖a+b与风险评估 |
| T-5 | pending | - | - | pending | 信道防护未实现 |
| T-6 | pending | - | - | pending | 资料性；治理文档 |

小结：威胁模型整体依赖 R-5/M-2b/V8 三个未落地载体，9 条全 pending 属结构性现状，非遗漏登记。

## 第 9 章 回退状态机（7 条：covered 0 / partial 1 / pending 6）

| 条目 | 类型 | 测试/规程 | 证据 | 状态 | 备注 |
|---|---|---|---|---|---|
| F-1 | pending | - | - | pending | 状态机未实现 |
| F-2 | pending | - | - | pending | 交接判定未实现；[TBD-F2]待计量 |
| F-3 | unit | test_relative_covariance_agrees_with_monte_carlo | ctp/tests/test_uncertainty.py:88 | partial | k×RSS数学基础已验证；判定/回退/禁令执行未实现 |
| F-3 | conformance | V8 | docs/conformance/V8-fail-closed.md | pending | 带错硬接=0（只验不校准） |
| F-4a | pending | - | - | pending | FAR重试→STOP未实现 |
| F-4a | conformance | V1 | docs/conformance/V1-latency.md | pending | 时延分布（非合规判据） |
| F-4b | pending | - | - | pending | 逐级回退未实现 |
| F-4c | pending | - | - | pending | STOP出口未实现 |
| F-4c | conformance | V8 | docs/conformance/V8-fail-closed.md | pending | 伪造类→STOP+报警 |
| F-5 | pending | - | - | pending | 资料性图示；随F-1–F-4 |

小结：F-3 的阈值数学（相对协方差传播+MC 验证）已备，但状态机本体（F-1/F-2/F-4）零实现。

## 第 10 章 版本与兼容（3 条：covered 0 / partial 0 / pending 3）

| 条目 | 类型 | 测试/规程 | 证据 | 状态 | 备注 |
|---|---|---|---|---|---|
| VC-1 | pending | - | - | pending | 治理流程无代码载体 |
| VC-2 | pending | - | - | pending | 待码族裁决；v10的schema_version仅为数据格式版本 |
| VC-3 | conformance | V7 | docs/conformance/V7-version-compat.md | pending | 发布门禁误读=0 |

小结：版本兼容全依赖 V7 门禁与治理流程，pending。

## 孤儿检查

83 个测试函数全部归属，**每个函数在矩阵中有独立行**（多归属函数按条目拆多行；AST 静态计数 + 脚本逐名孤儿检查 0 孤儿）：contract_valid 6、contract_invalid 6、schema_parity 5、uncertainty 13、pixel_uncertainty 7、generator 13、registry 33。此前 R-1–R-6 行以「某测试 等」概括同族成员，导致 31 个函数未具名（隐藏孤儿），2026-11-24 复核时补全。第 4–10 章 59 个条目每条至少 1 行，无未归属条目。
