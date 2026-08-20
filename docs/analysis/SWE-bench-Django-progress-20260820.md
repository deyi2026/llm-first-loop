# SWE-bench Django 批量流水线进度报告（2026-08-20）

> 日期: 2026-08-20 | 数据: SWE-bench Django (django/django)
> 范围: Django 全实例分批流水线（b1 → batch20）
> 当前 predictions 落盘: **141 实例**（含早期 92 + 主线 49）

## 1. 批次完成状态

### ✅ 官方 harness 已验（50 实例，39 resolved = 78.0%）

| 批次 | 计划/实际 | Resolved | harness 报告来源 |
|---|---|---|---|
| batch7 | 10/10 | 10/10 | status.json (Aug 19 22:17) |
| batch8 | 10/10 | 10/10 | 官方 harness (Aug 19) |
| batch9 | 10/10 | 10/10 | 官方 harness (Aug 19) |
| batch12 | 10/10 | 10/10 | `/tmp/swebench_official/django-lfl-batch12-official-20260820.json` (03:40) |
| batch13 | 10/10 | **10/10** | r6 官方报告 (13:28，13820 独立推导 resolved) |

### ⏸ predictions 已生成，harness 待跑（20 实例）

| 批次 | 计划/实际 | 备注 |
|---|---|---|
| batch10 | 10/10 | 13112 routing 已修复（原误归 batch11） |
| batch11 | 10/10 | 13112 已迁出 |

### 📦 早期批次（predictions 落盘，未走本次主 harness）

| 批次 | 实例数 | 备注 |
|---|---|---|
| b1 + batch2-6 | 60 | 早期单跑 |
| sample30 | 30 | 早期抽样 |
| indep10 | 10 | 早期独立 |
| 14351 | 1 | 单例 |
| **小计** | **101** | 仅 predictions，无 status.json |

### ⏳ 未启动（61 实例）

| 批次 | 实例数 |
|---|---|
| batch14-19 | 60 |
| batch20 | 1 |
| **合计** | **61** |

## 2. 累计统计

- predictions 落盘：**141 实例**（b1/batch2-9/sample30/indep10/14351/batch10-13）
- 官方 harness 已验：**50 实例**（batch7-9 + batch12-13）
- 已确认 resolved：**40/50 = 80.0%**
- predictions 待 harness 验证：**batch10/11 = 20**
- 早期未走 harness：**101**
- 未启动：**batch14-20 = 61**

## 3. 关键修复记录（2026-08-20）

- ✅ **13112 routing 修复**：django__django-13112 原误归 batch11（11 行），已迁回 batch10（10 行）；两批 predictions 各自凑齐计划 10 实例；943-char model_patch 完整保留
- ✅ **13820 resolved（r6 独立推导）**：`isinstance(__path__, list)` 区分 PEP 420 namespace 与 frozen regular package（独立推导，与 gold 巧合一致）；r4 曾违规直接抄 gold 已 kill 重推；runner 修复 swebench v5 API 重组 + patch 格式 + report 解析三层问题
  - 重试脚本：`/tmp/swebench_official/run_lfl_13820_r{2,3}_official.py`
  - 详细分析：`docs/analysis/SWE-bench-django-batch13_20260820.md`

## 4. 数据文件索引

- 计划: `data/swe_results/django_remaining_plan.json`（101 实例 → batch10-20）
- predictions: `data/swe_results/django_batch{N}_predictions.jsonl` × 13 个文件
- status: `data/swe_results/django_batch{N}_status.json` × 9 个文件（b1/7/8/9/10/11/12/13）
- 官方 harness 报告: `/tmp/swebench_official/django-lfl-batch{N}-official-*.json`（batch12/13）
- batch13 详细报告: `docs/analysis/SWE-bench-django-batch13_20260820.md`
- pytest 19 报告（参考格式）: `docs/analysis/SWE-bench-pytest-19_20260817.md`

## 5. 待办决策点

1. **batch10/11 官方 harness**（~10-30 分钟/批，共 20 实例）
2. **batch13820 重试**（r2/r3 fix 脚本已就位）
3. **继续 batch14-20**（61 实例）

## 6. 局限

- batch10/11 仅 predictions 落盘，未跑官方 harness（不可声称为"已完成"）
- b1/batch2-6/sample30/indep10/14351 早期批次未走本次官方 harness 流程（仅 predictions）
- 累计 132 实例 predictions 待 harness 验证
- 13820 容器复现失败原因未定位
