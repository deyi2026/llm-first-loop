# Rule28 全量测试门禁回执（2026-10-20）

## 目标
- 覆盖范围：EVO-20261020-91de7f8c（browser 寻址/闸门窗口限制）+ EVO-20261020-b1c00127（子代理通道熔断）两批已 executing 改动的提交产物
- 被审提交：44a331eaa（两 EVO 主体）→ 首跑失败后修复 b0f22cf1a

## 独立审查准入（Host review_admission，一次性资格）
| 轮次 | reviewer | 冻结候选 SHA | verdict | P0/P1 | 备注 |
|---|---|---|---|---|---|
| 1（44a331eaa） | subagent_518f197f6733 | f8508b2a… | PASS | 0/0 | Host 核真实完成+SHA+P0/P1 后签发资格 |
| 2（b0f22cf1a 窄复审） | subagent_d2879385d810 | 2fec2cf1… | PASS | 0/0 | 产物变化后按新指纹窄复审 |

## 全量 ci_gate 结果
### 第 1 轮（16:22，44a331eaa）——FAIL（exit 1）
- [1/5] ruff PASS（历史债 67→34，new=0，还清 33）→ [2/5] env-pin PASS（909 文件 0 违规）→ [3/5] pyright FAIL：`browser_semantic_operation.py` 新增 `reportReturnType`（`object` 不可赋给 `dict[str, Any] | None`）
- 根因：EVO-91de7f8c 提交前仅跑 ruff+定向 pytest，未跑 pyright ratchet
- 修复：b0f22cf1a `_identity_search_safe` 对动态调用结果 `isinstance` 收窄（duck-type 替身下静态返回 object）；单文件 pyright 0 诊断、11/11 特性测试过

### 第 2 轮（16:29，b0f22cf1a）——PASS（exit 0）
- ruff：historical=67, current=34, new=0, touched clean
- env-pin：909 文件 0 违规
- pyright：historical=45, current=11, new=0, touched clean
- tier0 预检：319 passed
- 全量 pytest（xdist）：**9643 passed, 137 skipped**，216.99s
- 审计告警：51 处测试内真实 provider base_url 样例（低风险，仅告警不阻断）

## 教训（已入学习系统）
提交前静态检查必须全链路（ruff+pyright+定向测试），动态 getattr 调用返回值需 isinstance 收窄。
