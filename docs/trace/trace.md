# CTP 规范条目—测试用例追溯矩阵（人读版）

- 规范：docs/SPEC-20261123-cooperative-target-protocol-v0.9.md（v0.9.2）第 4–10 章
- 测试资产：ctp/tests/ 16 个测试文件、170 个测试函数（AST 静态计数，明细见孤儿检查节；其中 test_trace_matrix.py 是矩阵自身的元测试，其 3 个用例不属规范覆盖、不入矩阵也不计数；conftest.py 为路径配置非用例；conformance_stubs.py 与 reader_testkit.py 为测试辅助模块非用例；fixtures：合法 10 + 非法 24）；参数化展开后的用例总数不在此手抄——单一真值为 ctp/receipts/ 最新回执
- 一致性规程：docs/conformance/ 已建 9 份（README + V1–V8），实测回执未产生，仍以 test_kind=conformance 的 pending 行预留（共 12 行）
- 机器可读版：trace.csv（列：spec_entry,test_kind,test_id,evidence_path,status,notes）
- 状态口径：covered=已有测试足以支撑条目的可测内容；partial=已有测试仅覆盖条目的一部分（或仅契约/机制侧）；pending=无测试（依赖计量/裁决/实现，或明示无测试义务）
- 条目计数口径：带字母子条的按子条计独立单元（如 C-4b-2）；无子条的按整条计

条目总数 59：covered 13 ｜ partial 11 ｜ pending 35。矩阵数据行 228：covered 112 ｜ partial 70 ｜ pending 46。

## 第 4 章 物理层（11 条：covered 0 / partial 2 / pending 9）

| 条目 | 类型 | 测试/规程 | 证据 | 状态 | 备注 |
|---|---|---|---|---|---|
| P-1a | pending | - | - | pending | 哑光与≥[TBD-P1]对比度属印刷材质计量；待实测定值 |
| P-1b | pending | - | - | pending | 镜面高光抑制属物理测量；无软件测试对象 |
| P-2a | pending | - | - | pending | 角点边长公差[TBD-P2a]待G6定带；生成器仅按名义尺寸出图不涉公差 |
| P-2a | conformance | V3 | docs/conformance/V3-tolerance-band.md | pending | 公差带定带（P2.5/P97.5+25%裕度）与独立留出批次落带验证 |
| P-2b | pending | - | - | pending | 靶标平面度计量待P2批次数据 |
| P-2c | pending | - | - | pending | 安装平面度与贴合要求待施工侧计量 |
| P-3a | pending | - | - | pending | T0=20°C（ISO 1）待工作组形式确认（[TBD-G]） |
| P-3b | unit | test_uncertainty_carries_k_and_one_sigma | ctp/tests/test_contract_valid.py:58 | partial | 热形变须纳入读出不确定度预算——预算通道（k+1σ声明）已实现并测试；热形变专项分量与[TBD-P3a]未落地 |
| P-3c | pending | - | - | pending | 认证样本低膨胀材质选择；无软件测试对象 |
| P-4 | pending | - | - | pending | 认证样本计量标定+证书属实验室流程；V6物理基准未建 |
| P-5a | pending | - | - | pending | 带外制造禁引精度声明属流程管控；依赖V3定带 |
| P-5b | unit | test_generate_is_deterministic | ctp/tests/test_generator.py:106 | partial | 确定性再生成+清单校验构成可核查依据的机制侧；批次抽检报告/认证样本谱系未实现 |
| P-5b | unit | test_manifest_detects_tampering | ctp/tests/test_generator.py:128 | partial | 清单篡改必被检出（sha校验）；尚非完整谱系 |
| P-5b | unit | test_layout_json_carries_frame_ref_tag_coordinates_and_tolerance | ctp/tests/test_generator.py:165 | partial | 公差标注（P-2a/b/c 键 + TBD 占位）与 grade 申报随布局落盘；数值与抽检依据未实现 |

小结：物理层按预期几乎全 pending（数值未冻结、无计量）。唯二 partial 均为「机制侧已备、计量侧未到」：P-3b 的不确定度预算通道、P-5b 的可核查依据机制。

## 第 5 章 编码层（16 条：covered 7 / partial 4 / pending 5）

| 条目 | 类型 | 测试/规程 | 证据 | 状态 | 备注 |
|---|---|---|---|---|---|
| C-1a | pending | - | - | pending | 前缀公共注册/等价互斥机制未实现；段长[TBD-G] |
| C-1b | unit | test_layout_validation_rejects_bad_payloads | ctp/tests/test_generator.py:87 | partial | 板内索引查重（重复索引拒收）已实现；域级唯一性分配机制未实现 |
| C-1c | pending | - | - | pending | Q9裁决条款（跨机构只需前缀唯一）；随C-1a落地后可测 |
| C-1d | unit | test_layout_roundtrip_through_json | ctp/tests/test_generator.py:100 | partial | 布局logical_mapping（resolution=code）承载分层映射结构；R-1注册表解析路径未实现 |
| C-1d | unit | test_valid_fixture_parses[v03_unresolved_null] | ctp/tests/test_contract_valid.py:26 | partial | unresolved（离线且无快照）状态在契约层可表达且合法 |
| C-1d | unit | test_layout_json_carries_frame_ref_tag_coordinates_and_tolerance | ctp/tests/test_generator.py:165 | partial | 布局 JSON 逐码物理坐标 + frame_ref（参考系引用）；R-1 解析属 B5 |
| C-1d | unit | test_layout_rejects_missing_or_blank_frame_ref | ctp/tests/test_generator.py:195 | partial | frame_ref 缺失/空白拒收（应拦） |
| C-1d | unit | test_layout_from_dict_rejects_tampered_tag_coordinates | ctp/tests/test_generator.py:205 | partial | tags 块与几何不一致即拒收（应拦） |
| C-1d | unit | test_resolver_and_degradation_flag_are_passed_through | ctp/tests/test_reader_observe.py:109 | partial | C-1d 逻辑 ID 经 resolver 解析；注册表解析路径未接 |
| C-2a | unit | test_table_regenerates_from_upstream_source | ctp/tests/test_generator.py:47 | covered | 码表与BSD-2上游源逐字一致（587码字；K4溯源） |
| C-2a | unit | test_family_invariants_hold | ctp/tests/test_generator.py:58 | covered | 587码字+最小汉明距离≥11（可纠≤5位错误） |
| C-2a | unit | test_bit_matrix_structure_matches_convention | ctp/tests/test_generator.py:65 | covered | quiet zone白/核外圈黑边/数据位MSB-first映射 |
| C-2a | unit | test_code_at_rejects_out_of_range | ctp/tests/test_generator.py:82 | covered | 码空间边界拒收（3个参数化例） |
| C-2a | unit | test_layout_validation_rejects_bad_payloads | ctp/tests/test_generator.py:87 | covered | family=42h7拒收——v0仅支持36h11 |
| C-2a | unit | test_rendered_tag_round_trips_through_the_generator_layout | ctp/tests/test_conformance_v7.py:80 | covered | 合成样本位图与生成器布局一致 |
| C-2a | unit | test_corrections_capability_matches_the_family | ctp/tests/test_reader_decode.py:28 | covered | 36h11 纠错能力 = 5、未知位上限 = 10（码族事实） |
| C-2a | unit | test_decodes_without_error | ctp/tests/test_reader_decode.py:67 | covered | B3 解码：合法码零误码解出 |
| C-2a | unit | test_rotated_image_decodes_to_the_same_index | ctp/tests/test_reader_decode.py:77 | covered | B3 解码：90° 整数倍旋转解出同一索引 |
| C-2b | unit | test_erasure_budget_tightens_with_unknown_bits | ctp/tests/test_reader_decode.py:45 | covered | B3 解码：纠错预算内（2t+e≤10）才输出、否则拒读 |
| C-2b | unit | test_corrects_up_to_five_bit_errors | ctp/tests/test_reader_decode.py:85 | covered | B3 解码：纠错预算内（2t+e≤10）才输出、否则拒读 |
| C-2b | unit | test_too_few_known_bits_refuses_to_decode | ctp/tests/test_reader_decode.py:104 | covered | B3 解码：纠错预算内（2t+e≤10）才输出、否则拒读 |
| C-2b | unit | test_partial_data_still_decodes_when_enough_bits_are_known | ctp/tests/test_reader_decode.py:122 | covered | B3 解码：纠错预算内（2t+e≤10）才输出、否则拒读 |
| C-2b | unit | test_translation_noise_and_blur_keep_it_decodable | ctp/tests/test_reader_decode.py:134 | covered | B3 解码：纠错预算内（2t+e≤10）才输出、否则拒读 |
| C-3a | pending | - | - | pending | 36h11位图不含版本位；图案版本字段待码族裁决后设计 |
| C-3b | unit | test_error_code_protocol | ctp/tests/test_conformance_receipt.py:74 | partial | B7 回执：读码器失败须带稳定错误码 |
| C-3b | unit | test_error_codes_are_stable_strings | ctp/tests/test_gate.py:254 | covered | B3/B4 错误码稳定（unknown_version / below_min_readable 等） |
| C-3b | unit | test_patterns_beyond_correction_are_unknown_version | ctp/tests/test_reader_decode.py:92 | covered | B3 解码：超出纠错预算一律 unknown_version，异常不带索引 |
| C-3b | unit | test_blank_and_non_square_regions_are_no_tag_found | ctp/tests/test_reader_decode.py:140 | covered | B3 定位：空白 / 非正方形 / 全黑拒读（no_tag_found） |
| C-3b | unit | test_border_check_rejects_misaligned_grid | ctp/tests/test_reader_decode.py:190 | covered | B3 定位：格阵错位由边框校验拦下 |
| C-3b | unit | test_unknown_version_is_refused_without_an_index | ctp/tests/test_reader_observe.py:102 | covered | B3 读取流程：外来图案 unknown_version 且无索引 |
| C-3c | conformance | V7 | docs/conformance/V7-version-compat.md | pending | 新族版本发布须过混合版本墙（旧版读码器误读=0） |
| C-4a | unit | test_threshold_fields_have_no_numeric_defaults | ctp/tests/test_gate.py:45 | covered | B4 闸门：阈值必填无默认、边界与类型校验、无硬编码门槛 |
| C-4a | unit | test_constructing_without_thresholds_fails | ctp/tests/test_gate.py:57 | covered | B4 闸门：阈值必填无默认、边界与类型校验、无硬编码门槛 |
| C-4a | unit | test_invalid_threshold_values_are_rejected | ctp/tests/test_gate.py:79 | covered | B4 闸门：阈值必填无默认、边界与类型校验、无硬编码门槛 |
| C-4a | unit | test_from_file_rejects_missing_unknown_and_malformed | ctp/tests/test_gate.py:87 | covered | B4 闸门：阈值必填无默认、边界与类型校验、无硬编码门槛 |
| C-4a | unit | test_from_file_roundtrip | ctp/tests/test_gate.py:109 | covered | B4 闸门：阈值必填无默认、边界与类型校验、无硬编码门槛 |
| C-4a | unit | test_exactly_at_thresholds_is_allowed | ctp/tests/test_gate.py:120 | covered | B4 闸门：阈值必填无默认、边界与类型校验、无硬编码门槛 |
| C-4a | unit | test_corners_take_precedence_over_ratio | ctp/tests/test_gate.py:148 | covered | B4 闸门：阈值必填无默认、边界与类型校验、无硬编码门槛 |
| C-4a | unit | test_gate_rejects_invalid_inputs | ctp/tests/test_gate.py:215 | covered | B4 闸门：阈值必填无默认、边界与类型校验、无硬编码门槛 |
| C-4a | unit | test_no_module_level_numeric_constants_in_gate_modules | ctp/tests/test_gate.py:234 | covered | B4 闸门：阈值必填无默认、边界与类型校验、无硬编码门槛 |
| C-4a | unit | test_synthetic_geometry_truth_matches_the_reader_evidence | ctp/tests/test_integration_reader_conformance.py:110 | covered | 集成：合成几何真值与读码器证据逐样本一致 |
| C-4a | unit | test_crop_evidence_counts_only_corners_with_both_border_edges | ctp/tests/test_reader_decode.py:167 | covered | B3 证据口径：完整角点与数据位比例 |
| C-4a | conformance | V4 | docs/conformance/V4-degradation.md | pending | 双向判据①：低于阈值样本误读率=0 |
| C-4b | unit | test_below_threshold_is_suppressed_and_counted | ctp/tests/test_gate.py:138 | covered | B4 闸门：低于阈值不输出并计数 |
| C-4b | unit | test_cropped_sample_decodes_to_its_recorded_index_under_lenient_thresholds | ctp/tests/test_integration_reader_conformance.py:122 | covered | 集成：裁边样本严格阈值抑制、宽松阈值解出真值索引 |
| C-4b | unit | test_gate_suppresses_before_decoding_and_counts_it | ctp/tests/test_reader_observe.py:88 | covered | B3 读取流程：闸门不过就不解码、不输出 |
| C-4b | conformance | V4 | docs/conformance/V4-degradation.md | pending | 低于阈值不输出的实测判据（门槛V4） |
| C-4b-2 | unit | test_receipt_refuses_non_simulated | ctp/tests/test_conformance_receipt.py:39 | partial | B7 回执：拒绝生成非 simulated 回执 |
| C-4b-2 | unit | test_notes_carry_the_simulated_disclaimer | ctp/tests/test_conformance_receipt.py:45 | partial | B7 回执：携带 simulated 免责说明 |
| C-4b-2 | unit | test_pass_with_gate_like_reader_and_configured_limits | ctp/tests/test_conformance_v4.py:25 | partial | B7 V4 runner（合成样本；漏检率上限未配置只能 indeterminate） |
| C-4b-2 | unit | test_never_outputs_is_a_failure | ctp/tests/test_conformance_v4.py:39 | partial | B7 V4 runner（合成样本；漏检率上限未配置只能 indeterminate） |
| C-4b-2 | unit | test_output_below_threshold_is_a_misread | ctp/tests/test_conformance_v4.py:48 | partial | B7 V4 runner（合成样本；漏检率上限未配置只能 indeterminate） |
| C-4b-2 | unit | test_silent_reader_is_a_protocol_failure | ctp/tests/test_conformance_v4.py:56 | partial | B7 V4 runner（合成样本；漏检率上限未配置只能 indeterminate） |
| C-4b-2 | unit | test_unconfigured_limits_yield_indeterminate | ctp/tests/test_conformance_v4.py:63 | partial | B7 V4 runner（合成样本；漏检率上限未配置只能 indeterminate） |
| C-4b-2 | unit | test_exceeding_configured_miss_limit_fails | ctp/tests/test_conformance_v4.py:72 | partial | B7 V4 runner（合成样本；漏检率上限未配置只能 indeterminate） |
| C-4b-2 | unit | test_insufficient_sample_size_is_not_exercisable_not_pass | ctp/tests/test_conformance_v4.py:87 | partial | B7 V4 runner（合成样本；漏检率上限未配置只能 indeterminate） |
| C-4b-2 | unit | test_grouping_follows_the_configured_threshold | ctp/tests/test_conformance_v4.py:98 | partial | B7 V4 runner（合成样本；漏检率上限未配置只能 indeterminate） |
| C-4b-2 | unit | test_grouping_moves_samples_when_threshold_admits_them | ctp/tests/test_conformance_v4.py:109 | partial | B7 V4 runner（合成样本；漏检率上限未配置只能 indeterminate） |
| C-4b-2 | unit | test_ratio_threshold_below_one_discloses_unexercisable_dimension | ctp/tests/test_conformance_v4.py:119 | partial | B7 V4 runner（合成样本；漏检率上限未配置只能 indeterminate） |
| C-4b-2 | unit | test_requires_thresholds_in_config | ctp/tests/test_conformance_v4.py:127 | partial | B7 V4 runner（合成样本；漏检率上限未配置只能 indeterminate） |
| C-4b-2 | unit | test_unusable_optional_limits_are_unconfigured_never_pass | ctp/tests/test_conformance_v4.py:149 | partial | B7 V4 runner（合成样本；不可用上限按未配置处理 → indeterminate，不得判 pass） |
| C-4b-2 | unit | test_unusable_grouping_thresholds_are_rejected | ctp/tests/test_conformance_v4.py:176 | partial | B7 V4 runner（合成样本；分组阈值不可用 → 拒绝运行，不产出回执） |
| C-4b-2 | unit | test_above_thresholds_is_allowed_never_suppressed | ctp/tests/test_gate.py:154 | partial | B4 闸门：达标样本永不被抑制（漏检率须 V4 实测） |
| C-4b-2 | unit | test_shadow_records_near_threshold_without_changing_allowed | ctp/tests/test_gate.py:165 | partial | K7 影子通道：记近阈候选但不改判定 |
| C-4b-2 | unit | test_shadow_band_applies_to_ratio_too | ctp/tests/test_gate.py:188 | partial | K7 影子通道：比例维度的近阈带 |
| C-4b-2 | unit | test_shadow_disabled_leaves_no_shadow_state | ctp/tests/test_gate.py:196 | partial | K7 影子通道：正式构建不留影子状态 |
| C-4b-2 | unit | test_shadow_log_carries_no_identifying_payload | ctp/tests/test_gate.py:205 | partial | K7 影子通道：日志不含 ID / 观测内容 |
| C-4b-2 | unit | test_v4_with_strict_thresholds_suppresses_and_never_misreads | ctp/tests/test_integration_reader_conformance.py:60 | partial | 集成：严格阈值下零误读、完整样本全读出（合成） |
| C-4b-2 | unit | test_v4_with_lenient_thresholds_reads_the_two_corner_sample_and_stays_honest | ctp/tests/test_integration_reader_conformance.py:73 | partial | 集成：宽松阈值读出裁边样本且如实 indeterminate（合成） |
| C-4b-2 | conformance | V4 | docs/conformance/V4-degradation.md | pending | 双向判据②：防"永不输出"平凡通过 |
| C-4c | pending | - | - | pending | 规范明示劣化预警非本层强制（属健康监测）；无测试义务 |
| C-5 | unit | test_fixture_set_is_not_vacuous | ctp/tests/test_contract_valid.py:21 | covered | 合法样本集非空泛（≥8；实际10例） |
| C-5 | unit | test_valid_fixture_parses | ctp/tests/test_contract_valid.py:26 | covered | v01–v10全样本解析为契约对象（10参数化例） |
| C-5 | unit | test_valid_fixture_parses[v05_extension] | ctp/tests/test_contract_valid.py:26 | covered | x-vendor.*扩展键合法（坏扩展键i20另测拒收） |
| C-5 | unit | test_valid_fixture_parses[v10_schema_version] | ctp/tests/test_contract_valid.py:26 | covered | 观测自带schema_version字段（ctp.c5/0.1） |
| C-5 | unit | test_roundtrip_is_lossless | ctp/tests/test_contract_valid.py:34 | covered | 解析→序列化round-trip无损（10参数化例） |
| C-5 | unit | test_all_c5_fields_present_in_model | ctp/tests/test_contract_valid.py:40 | covered | 九字段齐备（缺一即不合规） |
| C-5 | unit | test_uncertainty_carries_k_and_one_sigma | ctp/tests/test_contract_valid.py:58 | covered | k>0且1σ>0——覆盖因子与1σ同时给出 |
| C-5 | unit | test_v04_covariance_units_are_m2_rad2 | ctp/tests/test_contract_valid.py:66 | covered | 协方差单位钉：平移σ²(m²)/旋转rad(σ_deg)²(rad²) |
| C-5 | unit | test_fixture_set_is_not_vacuous | ctp/tests/test_contract_invalid.py:45 | covered | 非法样本集非空泛（≥8；实际24例） |
| C-5 | unit | test_no_orphan_fixture | ctp/tests/test_contract_invalid.py:49 | covered | fixtures与期望错误码表一一对应 |
| C-5 | unit | test_invalid_fixture_rejected_with_expected_code | ctp/tests/test_contract_invalid.py:55 | covered | 24例非法样本稳定拒收且错误码可复核 |
| C-5 | unit | test_invalid_fixture_rejected_with_expected_code[i06_logical_null_with_code] | ctp/tests/test_contract_invalid.py:55 | covered | linkage：code态logical_id为空拒收（resolution行） |
| C-5 | unit | test_invalid_fixture_rejected_with_expected_code[i07_logical_set_with_unresolved] | ctp/tests/test_contract_invalid.py:55 | covered | linkage：unresolved态logical_id非空拒收（resolution行） |
| C-5 | unit | test_parse_raises_and_reports_path | ctp/tests/test_contract_invalid.py:63 | covered | 异常带字段路径+错误码（24参数化例） |
| C-5 | unit | test_root_must_be_object | ctp/tests/test_contract_invalid.py:72 | covered | 根必须为对象 |
| C-5 | unit | test_nonfinite_numbers_are_rejected | ctp/tests/test_contract_invalid.py:76 | covered | NaN/Inf按type_error拒绝 |
| C-5 | unit | test_schema_is_valid_against_metaschema | ctp/tests/test_schema_parity.py:50 | covered | schema自身合规（Draft2020-12元模式） |
| C-5 | unit | test_schema_accepts_all_valid_fixtures | ctp/tests/test_schema_parity.py:55 | covered | schema层放行全部合法样本（10参数化例） |
| C-5 | unit | test_every_invalid_fixture_is_rejected_by_at_least_one_layer | ctp/tests/test_schema_parity.py:61 | covered | 双层至少一层拒收每例非法样本（24参数化例） |
| C-5 | unit | test_schema_misses_exactly_the_declared_validator_only_set | ctp/tests/test_schema_parity.py:68 | covered | schema/validator分歧集合钉死为六条规则族（防静默漂移） |
| C-5 | unit | test_validator_never_accepts_what_schema_rejects | ctp/tests/test_schema_parity.py:80 | covered | 反向分歧为空集 |
| C-5 | unit | test_rotation_sigma_is_converted_from_degrees | ctp/tests/test_uncertainty.py:64 | covered | 1σ度→弧度换算钉 |
| C-5 | unit | test_template_rejects_degenerate_or_invalid_declarations | ctp/tests/test_uncertainty.py:72 | covered | 非法不确定度声明拒收（空model/k=0/负σ/全零/形状错） |
| C-5 | unit | test_detector_rejects_input_that_breaks_first_order | ctp/tests/test_uncertainty.py:99 | covered | 应拦输入：60°位姿1σ超一阶适用域判不通过（fail-closed） |
| C-5 | unit | test_propagate_rejects_wrong_shapes | ctp/tests/test_uncertainty.py:120 | covered | 协方差传播形状校验 |
| C-5 | unit | test_se3_exp_log_roundtrip | ctp/tests/test_uncertainty.py:129 | covered | SE(3)指数/对数映射round-trip |
| C-5 | unit | test_adjoint_matches_pure_translation_form | ctp/tests/test_uncertainty.py:138 | covered | 纯平移伴射解析式钉 |
| C-5 | unit | test_log_se3_rejects_pi_rotation | ctp/tests/test_uncertainty.py:170 | covered | 180°对数奇异显式报错（fail-closed） |
| C-5 | unit | test_template_rejects_zero_sigma_even_with_covariance | ctp/tests/test_uncertainty.py:180 | covered | 全零1σ附协方差仍拒收（与validator对齐） |
| C-5 | unit | test_jacobian_matches_numeric_differentiation | ctp/tests/test_pixel_uncertainty.py:44 | covered | 像素→位姿雅可比vs数值微分 |
| C-5 | unit | test_well_conditioned_geometry_agrees_with_monte_carlo | ctp/tests/test_pixel_uncertainty.py:59 | covered | 良态位形一阶vs MC逐轴误差≤5% |
| C-5 | unit | test_fronto_parallel_geometry_is_flagged_degenerate | ctp/tests/test_pixel_uncertainty.py:68 | covered | 正对平面退化位形如实判失败（tx 1σ厘米级） |
| C-5 | unit | test_extreme_noise_exceeds_model_domain | ctp/tests/test_pixel_uncertainty.py:83 | covered | 极端噪声超模型域判失败 |
| C-5 | unit | test_covariance_scales_with_sigma_squared | ctp/tests/test_pixel_uncertainty.py:97 | covered | 协方差随σ²缩放 |
| C-5 | unit | test_camera_rejects_points_behind | ctp/tests/test_pixel_uncertainty.py:113 | covered | 相机背后的点拒收 |
| C-5 | unit | test_reader_identity_is_recorded_or_marked_unknown | ctp/tests/test_conformance_receipt.py:87 | partial | B7 回执：记录被测读码器身份 |
| C-5 | unit | test_error_crosses_a_contextlib_context_manager_intact | ctp/tests/test_error_propagation.py:34 | covered | 异常传播回归钉：Contract/Registry/Reader Error 穿过上下文管理器不丢码 |
| C-5 | unit | test_error_crosses_an_exit_stack_and_raise_from | ctp/tests/test_error_propagation.py:44 | covered | 异常传播回归钉：ExitStack + raise from 不丢码 |
| C-5 | unit | test_fields_stay_read_only_after_construction | ctp/tests/test_error_propagation.py:57 | covered | 异常字段构造后只读 |
| C-5 | unit | test_errors_remain_hashable_and_compare_by_fields | ctp/tests/test_error_propagation.py:65 | covered | 异常按字段可哈希 / 可比较 |
| C-5 | unit | test_invalid_inputs_are_rejected_without_coercion | ctp/tests/test_reader_decode.py:154 | covered | B3 输入校验：非 uint8 灰度图显式拒绝 |
| C-5 | unit | test_read_returns_a_conforming_c5_observation | ctp/tests/test_reader_observe.py:31 | covered | B3 读码器端到端：C-5 全字段与 fail-closed |
| C-5 | unit | test_invalid_timestamp_and_degradation_are_rejected | ctp/tests/test_reader_observe.py:119 | covered | B3 读码器端到端：C-5 全字段与 fail-closed |
| C-5 | unit | test_constructor_requires_valid_configuration | ctp/tests/test_reader_observe.py:132 | covered | B3 读码器端到端：C-5 全字段与 fail-closed |
| C-5 | unit | test_self_check_failure_never_returns_a_half_product | ctp/tests/test_reader_observe.py:162 | covered | B3 读码器端到端：C-5 全字段与 fail-closed |
| C-5 | unit | test_float_image_is_rejected_end_to_end | ctp/tests/test_reader_observe.py:174 | covered | B3 读码器端到端：C-5 全字段与 fail-closed |
| C-5 | conformance | V2 | docs/conformance/V2-accuracy.md | pending | 精度—条件曲线3σ判据实测（k与1σ声明一致） |
| C-5a | unit | test_template_declaration_is_accepted_by_c5 | ctp/tests/test_uncertainty.py:37 | covered | 观测=测量+不确定度：声明可直接填C-5并通过解析；"不裁决谁对"为范围条款（融合交上层） |
| C-5b | unit | test_relative_covariance_agrees_with_monte_carlo | ctp/tests/test_uncertainty.py:88 | partial | k·√(u1²+u2²)比较的RSS传播基础已验证（≤5%MC一致）；双读码器实测V6未做 |
| C-5b | unit | test_monte_carlo_is_reproducible | ctp/tests/test_uncertainty.py:112 | partial | MC可复现（V6判据的统计基础） |
| C-5b | unit | test_rotation_only_uncertainty_couples_only_through_force_arm | ctp/tests/test_uncertainty.py:145 | partial | 伴射结构钉（旋转→平移耦合仅经力臂） |
| C-5b | unit | test_singular_covariance_is_typed_failure | ctp/tests/test_uncertainty.py:192 | partial | 奇异协方差类型化失败（应拦）；k·√ 判据可计算性的边界 |
| C-5b | conformance | V6 | docs/conformance/V6-cross-vendor.md | pending | 双合规读码器位姿差判据；N≥[TBD-V6a]通过率≥95% |

小结：C-2a/C-2b/C-3b/C-4a/C-4b/C-5/C-5a 已 covered（B3 读码器与 B4 闸门落地）；C-1b/C-1d/C-4b-2/C-5b 为 partial（分配机制、注册表解析路径、漏检率实测、V6 实测未做）；C-1a/C-1c/C-3a/C-3c/C-4c 仍 pending。

## 第 6 章 语义层（6 条：covered 6 / partial 0 / pending 0）

| 条目 | 类型 | 测试/规程 | 证据 | 状态 | 备注 |
|---|---|---|---|---|---|
| R-1 | unit | test_roundtrip_deterministic_json | ctp/tests/test_registry.py:82 | covered | B5 记录：字段集+签名+确定性 JSON roundtrip 与非法字段拒绝 |
| R-1 | unit | test_rejects_invalid_fields | ctp/tests/test_registry.py:108 | covered | 非法字段显式拒收（9 个参数化应拦例：周期/版本/时区/日期/ID/签名格式） |
| R-1 | unit | test_rejects_unknown_and_missing_dict_keys | ctp/tests/test_registry.py:115 | covered | from_dict 缺键/多键均拒收 |
| R-2 | unit | test_append_then_replay_chain_consistent | ctp/tests/test_registry.py:132 | covered | append-only：链一致/改写检测/删行检测/无删除改写 API |
| R-2 | unit | test_no_delete_or_rewrite_api | ctp/tests/test_registry.py:149 | covered | 无删除/改写接口（append-only 的结构保证） |
| R-2 | unit | test_rewritten_line_detected_as_tampered | ctp/tests/test_registry.py:163 | covered | 改写行被检出（payload_tampered） |
| R-2 | unit | test_deleted_line_breaks_chain | ctp/tests/test_registry.py:177 | covered | 删行断链（chain_broken） |
| R-2 | unit | test_unsigned_register_refused_at_append | ctp/tests/test_registry.py:189 | covered | 无签名记录拒入链 |
| R-2 | unit | test_version_regression_refused | ctp/tests/test_registry.py:195 | covered | record_version 不递增即拒 |
| R-2 | unit | test_supersede_appends_new_version | ctp/tests/test_registry.py:202 | covered | 更新=追加新版本事件 |
| R-3 | unit | test_retire_creates_terminal_tombstone | ctp/tests/test_registry.py:215 | covered | 墓碑终态/复用拒绝/未知ID拒绝/绑定拒绝；权威签名钩子=TODO-G2 首位 |
| R-3 | unit | test_tombstoned_id_reuse_refused | ctp/tests/test_registry.py:232 | covered | 墓碑 ID 复用拒收（tombstone_reuse） |
| R-3 | unit | test_retire_unknown_id_refused | ctp/tests/test_registry.py:244 | covered | 报废未知 ID 拒收 |
| R-3 | unit | test_bind_tombstoned_id_refused | ctp/tests/test_registry.py:253 | covered | 墓碑 ID 语义绑定拒收 |
| R-3 | unit | test_retire_verifier_vetoes_retire | ctp/tests/test_registry.py:474 | covered | retire_verifier 钩子拒未授权报废（DoS 面缓解） |
| R-4 | unit | test_offline_verification_succeeds | ctp/tests/test_registry.py:282 | covered | 两级签名快照：离线校验/篡改快照/篡改记录/坏链与无签名 |
| R-4 | unit | test_tampered_snapshot_rejected | ctp/tests/test_registry.py:290 | covered | 篡改快照→快照级验签失败 |
| R-4 | unit | test_tampered_record_inside_snapshot_rejected | ctp/tests/test_registry.py:300 | covered | 篡改单条记录→记录级验签失败 |
| R-4 | unit | test_broken_and_unsigned_snapshots_rejected | ctp/tests/test_registry.py:310 | covered | 结构损坏/未签名快照拒收 |
| R-4 | unit | test_snapshot_created_at_requires_iso8601_with_timezone | ctp/tests/test_registry.py:325 | covered | created_at 非带时区 ISO 8601 即拒（应拦） |
| R-4 | unit | test_snapshot_excludes_tombstoned_id_even_if_reregistered | ctp/tests/test_registry.py:336 | covered | 手写链重登记的墓碑 ID 不回快照（应拦） |
| R-5 | unit | test_bind_signed_record_succeeds | ctp/tests/test_registry.py:361 | covered | 语义绑定验签：篡改/无签名/未知ID/错权威/链完整性 |
| R-5 | unit | test_tampered_record_fails_signature | ctp/tests/test_registry.py:368 | covered | 篡改记录验签失败 |
| R-5 | unit | test_unsigned_record_binding_refused | ctp/tests/test_registry.py:376 | covered | 无签名记录拒绝语义绑定 |
| R-5 | unit | test_unknown_id_binding_refused | ctp/tests/test_registry.py:389 | covered | 未知 ID 拒绝绑定 |
| R-5 | unit | test_wrong_authority_key_rejected | ctp/tests/test_registry.py:395 | covered | 错权威公钥拒收 |
| R-5 | unit | test_binding_requires_chain_integrity | ctp/tests/test_registry.py:402 | covered | 链不完整拒绝绑定 |
| R-6 | unit | test_two_level_classification | ctp/tests/test_registry.py:429 | covered | 两级时效（待复验/2×周期隔离）按 PROP G5 提案实现待追认；quarantine 契约通道另测；强制等级[TBD-G] |
| R-6 | unit | test_period_comes_from_record_not_constant | ctp/tests/test_registry.py:434 | covered | 复验周期取自记录而非常量 |
| R-6 | unit | test_no_hardcoded_period_defaults | ctp/tests/test_registry.py:440 | covered | 反射断言无硬编码周期默认值 |
| R-6 | unit | test_quarantine_blocks_binding_with_g5_note | ctp/tests/test_registry.py:451 | covered | 2× 周期超期隔离并带 G5 待追认标注 |
| R-6 | unit | test_pending_revalidation_does_not_block_binding | ctp/tests/test_registry.py:460 | covered | 一级待复验不拦绑定（G5 提案） |
| R-6 | unit | test_naive_now_rejected | ctp/tests/test_registry.py:467 | covered | 无时区 now 拒收 |

小结：B5 注册表原型落地后 R-1–R-6 全部 covered（test_registry.py；用例数以最新回执为准）；残余治理项（墓碑权威签名 DoS 面、R-6 强制等级）登记于 ctp/docs/registry-notes.md TODO-G2。

## 第 7 章 组合层（7 条：covered 0 / partial 3 / pending 4）

| 条目 | 类型 | 测试/规程 | 证据 | 状态 | 备注 |
|---|---|---|---|---|---|
| M-1 | unit | test_noise_free_solve_returns_nominal_pose | ctp/tests/test_pixel_uncertainty.py:105 | partial | 单靶6DoF解算可达（无噪声解算回名义位姿）；"不作唯一安全证据"为部署规则（T-3）无单测对象 |
| M-1 | unit | test_pose_is_fronto_parallel_at_the_expected_depth | ctp/tests/test_reader_observe.py:48 | partial | M-1 单靶 6DoF 观测（正对位姿与深度）；安全决策限制属部署规则 |
| M-1 | unit | test_translation_moves_the_position_by_back_projection | ctp/tests/test_reader_observe.py:59 | partial | M-1 单靶 6DoF 观测（平移反投影） |
| M-1 | unit | test_rotated_image_gives_the_matching_quarter_turn_pose | ctp/tests/test_reader_observe.py:70 | partial | M-1 单靶 6DoF 观测（旋转姿态 = Rz(r·90°)） |
| M-1 | unit | test_tag_size_scales_the_estimated_depth | ctp/tests/test_reader_observe.py:82 | partial | M-1 单靶 6DoF 观测（尺度—深度关系） |
| M-2a | pending | - | - | pending | 成对几何关系登记与公差[TBD-M2]未实现（布局仅隐式网格几何） |
| M-2b | pending | - | - | pending | 几何互证→F-3回退报警逻辑未实现 |
| M-3 | unit | test_layout_validation_rejects_bad_payloads | ctp/tests/test_generator.py:87 | partial | 板级组合结构校验（重复/越界/数量/物理放不下）；递归几何互证未实现 |
| M-3 | unit | test_generate_pdf_is_valid_and_paged | ctp/tests/test_generator.py:117 | partial | 多板分页物理载体（A4横放≈842pt钉） |
| M-3 | unit | test_render_rejects_mixed_page_sizes | ctp/tests/test_generator.py:140 | partial | 混页尺寸显式拒绝（防静默裁剪；应拦） |
| M-4 | pending | - | - | pending | 标定室为可选设施；规范明示可不作协议合规要求 |
| M-5a | pending | - | - | pending | 投影模态未实现 |
| M-5b | unit | test_valid_fixture_parses[v02_resolved_coarse] | ctp/tests/test_contract_valid.py:26 | partial | coarse降级标记契约通道已测；投影前提自检与V5判据未实现 |
| M-5b | unit | test_invalid_fixture_rejected_with_expected_code[i05_degradation_trailing_space] | ctp/tests/test_contract_invalid.py:55 | partial | 降级枚举严格性（尾随空格拒收） |
| M-5b | conformance | V5 | docs/conformance/V5-projection.md | pending | 前提不满足须判粗对齐+coarse标记；无标记即不通过 |

小结：板级组合的结构与载体有 partial 支撑；阵列级登记互证（M-2）与投影模态（M-5a）未动工。

## 第 8 章 威胁模型（9 条：covered 0 / partial 0 / pending 9）

| 条目 | 类型 | 测试/规程 | 证据 | 状态 | 备注 |
|---|---|---|---|---|---|
| T-1 | pending | - | - | pending | 保护资产定义条目；由R-*/T-4间接承载 |
| T-2 | pending | - | - | pending | 对手模型D1–D3；测试载体为V8注入故障集（未建） |
| T-3 | pending | - | - | pending | 部署侧安全边界；V8伪造类期望行为为其测试载体 |
| T-4a | pending | - | - | pending | 语义层签名（依赖R-5）未实现 |
| T-4b | pending | - | - | pending | 几何互证（依赖M-2b）未实现 |
| T-4c | pending | - | - | pending | 物理访问控制属场景设施；无软件测试对象 |
| T-4d | pending | - | - | pending | 开放环境a+b+风险评估记录未实现 |
| T-5 | pending | - | - | pending | 可校验通道/离线快照通道未实现 |
| T-6 | pending | - | - | pending | 资料性条目；属治理文档无测试义务 |

小结：威胁模型整体依赖 R-5/M-2b/V8 三个未落地载体，9 条全 pending 属结构性现状，非遗漏登记。

## 第 9 章 回退状态机（7 条：covered 0 / partial 1 / pending 6）

| 条目 | 类型 | 测试/规程 | 证据 | 状态 | 备注 |
|---|---|---|---|---|---|
| F-1 | pending | - | - | pending | 回退状态机未实现 |
| F-2 | pending | - | - | pending | 交接条件判定未实现；[TBD-F2]角点残差阈值待计量 |
| F-3 | unit | test_relative_covariance_agrees_with_monte_carlo | ctp/tests/test_uncertainty.py:88 | partial | k×RSS阈值数学基础（相对协方差传播）已验证；阈值判定/回退动作/带错硬接禁令的执行未实现 |
| F-3 | unit | test_verdict_precedence | ctp/tests/test_conformance_receipt.py:49 | partial | B7 回执：fail > indeterminate > pass 的判定优先级 |
| F-3 | unit | test_refusing_reader_leaves_forgery_unexercised | ctp/tests/test_conformance_v8.py:18 | partial | B7 V8 runner（漏检类可演练；伪造类未演练） |
| F-3 | unit | test_fault_types_are_dispatched_and_counted | ctp/tests/test_conformance_v8.py:33 | partial | B7 V8 runner（漏检类可演练；伪造类未演练） |
| F-3 | unit | test_output_on_unreadable_sample_is_a_failure | ctp/tests/test_conformance_v8.py:42 | partial | B7 V8 runner（漏检类可演练；伪造类未演练） |
| F-3 | unit | test_silent_reader_is_a_failure | ctp/tests/test_conformance_v8.py:51 | partial | B7 V8 runner（漏检类可演练；伪造类未演练） |
| F-3 | unit | test_untyped_exception_counts_as_silent | ctp/tests/test_conformance_v8.py:60 | partial | B7 V8 runner（漏检类可演练；伪造类未演练） |
| F-3 | unit | test_forgery_excluded_allows_pass_for_leak_class_only | ctp/tests/test_conformance_v8.py:68 | partial | B7 V8 runner（漏检类可演练；伪造类未演练） |
| F-3 | unit | test_unreadable_sample_keeps_border_but_destroys_data | ctp/tests/test_conformance_v8.py:76 | partial | B7 V8 runner（漏检类可演练；伪造类未演练） |
| F-3 | unit | test_rejects_non_positive_n | ctp/tests/test_conformance_v8.py:88 | partial | B7 V8 runner（漏检类可演练；伪造类未演练） |
| F-3 | unit | test_non_boolean_include_forgery_is_rejected | ctp/tests/test_conformance_v8.py:94 | partial | B7 V8 runner（漏检类可演练；伪造类未演练；非布尔 include_forgery 拒绝运行） |
| F-3 | unit | test_v8_real_reader_refuses_every_leak_sample | ctp/tests/test_integration_reader_conformance.py:85 | partial | 集成：漏检类全部拒读、无带错输出、无静默（合成） |
| F-3 | unit | test_v8_with_forgery_samples_is_indeterminate_not_pass | ctp/tests/test_integration_reader_conformance.py:98 | partial | 集成：伪造类未演练 → indeterminate（合成） |
| F-3 | conformance | V8 | docs/conformance/V8-fail-closed.md | pending | 注入1000故障样本验证带错硬接=0（只验不校准） |
| F-4a | pending | - | - | pending | FAR重试N≤3→STOP未实现 |
| F-4a | conformance | V1 | docs/conformance/V1-latency.md | pending | 时延分布（超时预算声明输入；非合规判据） |
| F-4b | pending | - | - | pending | MID/NEAR逐级回退未实现 |
| F-4c | pending | - | - | pending | STOP=停止+报警+人工介入（无默认通过出口）未实现 |
| F-4c | conformance | V8 | docs/conformance/V8-fail-closed.md | pending | 伪造/层级矛盾类故障→STOP+报警 |
| F-5 | pending | - | - | pending | 资料性状态图；随F-1–F-4实现 |

小结：F-3 的阈值数学（相对协方差传播+MC 验证）已备，但状态机本体（F-1/F-2/F-4）零实现。

## 第 10 章 版本与兼容（3 条：covered 0 / partial 1 / pending 2）

| 条目 | 类型 | 测试/规程 | 证据 | 状态 | 备注 |
|---|---|---|---|---|---|
| VC-1 | pending | - | - | pending | 规范版本治理流程；无代码载体 |
| VC-2 | pending | - | - | pending | 规范/族版本解耦待码族裁决（C-2 [TBD-G]）；观测schema_version（v10）仅为数据格式版本非本条证据 |
| VC-3 | unit | test_sample_set_hash_is_deterministic_and_sensitive | ctp/tests/test_conformance_receipt.py:29 | partial | B7 回执：样本集哈希确定且敏感 |
| VC-3 | unit | test_write_roundtrip | ctp/tests/test_conformance_receipt.py:64 | partial | B7 回执：JSON 落盘往返一致 |
| VC-3 | unit | test_foreign_and_unrelated_patterns_are_beyond_correction | ctp/tests/test_conformance_v7.py:25 | partial | B7 V7 runner（合成样本，未实测） |
| VC-3 | unit | test_samples_are_deterministic_and_seed_sensitive | ctp/tests/test_conformance_v7.py:37 | partial | B7 V7 runner（合成样本，未实测） |
| VC-3 | unit | test_pass_when_every_foreign_sample_is_refused | ctp/tests/test_conformance_v7.py:47 | partial | B7 V7 runner（合成样本，未实测） |
| VC-3 | unit | test_fail_when_foreign_sample_outputs_any_id | ctp/tests/test_conformance_v7.py:61 | partial | B7 V7 runner（合成样本，未实测） |
| VC-3 | unit | test_silent_refusal_is_not_a_misread_but_is_counted | ctp/tests/test_conformance_v7.py:70 | partial | B7 V7 runner（合成样本，未实测） |
| VC-3 | unit | test_v7_passes_with_the_real_reader | ctp/tests/test_integration_reader_conformance.py:48 | partial | 集成：真读码器对外来码字零误读（合成） |
| VC-3 | conformance | V7 | docs/conformance/V7-version-compat.md | pending | 发布门禁：混合版本墙误读=0无豁免通道 |

小结：VC-3 有了 V7 runner 骨架（合成样本，未实测）→ partial；VC-1 / VC-2 仍依赖治理流程与码族裁决。

## 孤儿检查

170 个测试函数全部归属，**每个函数在矩阵中有独立行**（多归属函数按条目拆多行；AST 静态计数 + 脚本逐名孤儿检查 0 孤儿）：conformance_receipt 7、conformance_v4 13、conformance_v7 6、conformance_v8 9、contract_invalid 6、contract_valid 6、error_propagation 4、gate 16、generator 13、integration_reader_conformance 7、pixel_uncertainty 7、reader_decode 13、reader_observe 12、registry 33、schema_parity 5、uncertainty 13。此前 R-1–R-6 行以「某测试 等」概括同族成员，导致 31 个函数未具名（隐藏孤儿），2026-11-24 复核时补全；Wave-3 新增的函数（闸门 / 读码器 / 一致性 runner / 集成 / 异常传播回归钉）于 2026-11-25 逐名入表；同日测试准入审查 r1 修订新增 3 个回归钉（V4 不可用配置 2 个、V8 非布尔 include_forgery 1 个）亦逐名入表。第 4–10 章 59 个条目每条至少 1 行，无未归属条目。
