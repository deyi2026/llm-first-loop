# experiences/ 资格线（Qualification Line）— 2026-09-18 拆分

本目录是 save_experience 之外的**文件形态经验库**（历史遗留 + 批量导入）。active/archived 的判定不再依赖读取者自行推断，按以下显式资格线执行。

## Active 资格（满足其一）

| 档位 | 判据 | 标注 |
|---|---|---|
| **verified** | frontmatter `verification_state: verified` + evidence 字段含 commit/测试/事件引用 | 已有字段 |
| **methodology self-evident** | 无运行证据，但方法论步骤可机械复现、或正文含实测数字/具体事件细节（如 byte 0xbc、系数 0.5 vs 0.6、t/s 实测） | `qualification: <date> batchN: retained（methodology self-evident…）` |
| **legacy 保留** | 2026-08 前旧条目，被 20260906/20260918 审计逐条判定 retained | 同上格式 |

## Archive 条件（满足其一即归档，保留全文可追溯）

1. `status: invalid`（已被证伪）→ 收尾为 `archived` + `archived_reason: lifecycle-batch1`
2. 占位/流水账（solution 无方法论、无细节，如 "Baseline numbers recorded"）→ `lifecycle-batch2`
3. sha256 全文重复组的非首成员 → `lifecycle-duplicate`
4. superseded（被更新条目/规则替代）→ 标注被替代者引用

## 归档方式

改 `status: archived` + `archived_at: <date>` + `archived_reason: <批次+依据>`。**不删除文件**（审计可追溯）。审计快照落 `data/audit/experience_lifecycle_<date>.json`（data/ 不入库）。

## 历史批次

- 20260906 审计：151 文件（120 active/31 archived），先例见 data/audit/
- 20260918 batch1：4 invalid → archived（机械收尾）
- 20260918 batch2/3：13 条逐条审 → 12 retained + 1 archived（占位流水账）
