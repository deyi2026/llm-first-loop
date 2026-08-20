# SWE-bench Django batch13 评测报告（2026-08-20）

## 摘要
- batch13（10 实例）本地验证 **10/10 全绿**
- 官方 harness 容器终验 **9/10 resolved**；13820 **pending_revisit**（本地 563 OK；容器 3 次重验失败——r1 ImportError 疑镜像环境差异、r2/r3 namespace 包未跳过；容器实测 py3.11.5 测试环境 loader 类名 NamespaceLoader，判断应命中却未命中，疑 patch 应用/load_disk 路径，待断点排查）
- 剩余 **70 实例**（batch14-20）

## 实例明细
| 实例 | 修复要点 | 本地 | 容器 |
|---|---|---|---|
| 13810 | MiddlewareNotUsed 副作用：adapted_handler 临时变量，实例化成功才更新 handler | 33 OK | resolved |
| 13820 | frozen 环境迁移：loader 类名 endswith('NamespaceLoader') 判 namespace | 563 OK | ⏸ pending_revisit |
| 13821 | SQLite 最低版本 3.8.3→3.9.0 | 32 OK | resolved |
| 13837 | autoreload get_child_arguments 加 __main__.__spec__.parent（任意 -m 包） | 78 OK | resolved |
| 13925 | W042 继承 pk 误报：_check_default_pk 加 not _meta.parents | 26 OK | resolved |
| 14007 | insert returning 应用 field converters（from_db_value） | 15 OK | resolved |
| 14017 | Q 与 conditional 组合：_combine 接受 + 空 Q 反转 + deconstruct 简化（对齐 3.2.2） | 157 OK | resolved |
| 14034 | MultiWidget required 按子字段（require_all_fields 门控 + is_required） | 13 OK | resolved |
| 14053 | staticfiles post_process yielded 去重 | 32 OK | resolved |
| 14140 | Q.deconstruct 单 child 非下标崩溃：简化为 args=tuple(children) | 115 OK | resolved |

## 落盘
- predictions: `data/swe_results/django_batch13_predictions.jsonl`（10 条）
- patches: `/tmp/swe_lfl_patches/django__django-<id>.patch`
- 计划: `data/swe_results/django_remaining_plan.json`（batch13_status done=10，剩余 70 实例）
- 经验: `EXPERIENCE-20260820-swe-bench-django-batch13-10-q-conditional-multiwid.md`
- 交接: `data/compressed_archive/handoff_20260820-094014/handoff.md`（SWE batch13 段，含 13820 r3 收尾指引）

## 测试基建说明（触发标签: [测试基建] [改动披露] [回归报告] [验证声明]）
- 本批次未改动 src/、docs/ai_rules.md、test_ai_rules_sync.py 等程序面（SWE 任务在 /tmp/swe_instances/ 独立 django 实例内修复，不涉及主项目）
- 容器终验使用 swebench 官方 harness（run_lfl_batch13_official.py），镜像 --platform linux/amd64
- 13820 r3 重验：run_lfl_13820_r3_official.py（RUN_ID=django-lfl-batch13-r3-13820-20260820），结果在 logs/run_evaluation/
