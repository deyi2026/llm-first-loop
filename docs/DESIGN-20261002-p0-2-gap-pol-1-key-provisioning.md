# GAP-POL-1 Key 预置与轮换策略 — Mini-Design（收口）

Date: 2026-10-02
Status: **FROZEN — 机制已由 B1（`d005f275a`）/修正（`3a0de911c`）/C1（`25b737ce3`）落地，本文冻结策略裁决与运行手册**
上游：`docs/DESIGN-20261002-p0-2-provider-settlement-coverage-plan.md` §2 GAP-POL-1（"key 来源与轮换策略单独 mini-design"留白）
权威：代码为机制权威（`src/llm_loop/resources/content_digest.py`）；本文是策略层，冲突以代码为准并回改本文。

## 1. 已实现机制（事实摘要）

- 解析顺序：显式 args > env `LFL_CONTENT_HMAC_SECRET`（hex，≥16B）+ `LFL_CONTENT_HMAC_KEY_ID`（默认 `env`）> key file `<LFL_DATA_DIR|data>/keys/content_hmac.json`。
- key file：`algorithm=hmac-sha256`、`key_id=k1-<8hex>`、`secret_hex`（32B）、`created_at`（host-local 权威，`3a0de911c`）；0600、O_EXCL temp + `os.replace` 原子创建，race-loser 解析 winner 结果。
- 无进程级缓存：文件替换后下一次 resolve 生效；热路径持有 `ContentHmacKey` 实例（进程内一致）。
- 观测层铁律（C1）：settlement/prepared/normalized_response_hmac 全部调用点 `allow_create=False`——**观测绝不副作用创建 key 材料**；无 key 时字段诚实省略（debug log），primitive 自身 fail-loud。
- `key_id` 随 digest 落盘：轮换可观测、跨期不等价是特性不是缺陷。
- `.gitignore`：`data/*` 仅豁免 `data/methods/` → `data/keys/` 永不入库。

## 2. 策略裁决

1. **默认路径 = 本地 key file**（单机/自托管场景）；env 注入保留给受限 FS/容器/no-persist 场景。不引入 KMS/外部 secret manager（明确不做）。
2. **多进程一致性**：web/feishu/learning/CLI 各自 resolve 同一路径；原子创建保证首建收敛；运行期轮换要求 write-temp + `os.replace`（同 primitive 语义），不得原地覆写。
3. **轮换 runbook**：生成新 key file（新 `key_id`）→ temp+replace → 重启进程（热路径实例持旧 key，重启保证同进程内不跨期）→ 新事件携带新 `key_id`。旧 digest 与新 digest 不等价属预期；对账按 `key_id` 分期。
4. **备份/丢失语义**：key 属 `data/*`（ignored），`recover_from_backup` 不承诺恢复；key 丢失 = 历史 digest 不可再验证（仍可与同期新事件比对），不视为数据损坏事件。
5. **双 key 重叠窗口：不做**。若未来需要"轮换期验证旧 digest"，扩展 key file 为数组 + 旧 key 只读验证——HOLD，无当前需求。

## 3. 激活 runbook（owner 显式动作）

观测层 `allow_create=False` 意味着 key 预置是 **owner 侧显式动作**，不是首次调用的副作用：

```
.venv/bin/python -c "from llm_loop.resources.content_digest import resolve_content_hmac_key; k=resolve_content_hmac_key(allow_create=True); print('key_id:', k.key_id)"
```

- 生成后 `data/keys/content_hmac.json`（0600）即被所有 shadow 调用点解析到，prepared/settled 的 `*_hmac` 字段开始落盘。
- **未预置时的正确表现**：字段诚实省略 + debug log；这不是回归，是 fail-open 设计。
- §4 验收断言 4（payload_hmac 覆盖率 ≥99%）的**前置条件**即本 runbook 已执行。

## 4. 验收映射

- 机制回归：B1 gates（含 key 轮换单测）、C1 `test_transport_settled_facts.py` 10/10。
- 本文无新增代码；策略变更需回改本文并单独 commit。
