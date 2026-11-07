# Peer 通道实施交接（lfl.peer.v1）

设计和契约真值源：`docs/DESIGN-20261107-deepin-remote-takeover-agent-interop.md`（1378 行，勿整篇灌上下文）
与 `docs/schemas/lfl.peer.v1/`；校验：`python3 scripts/verify_peer_schemas.py`（30 checks PASS，1 skipped）。

## 边界
- 做 P1（pairing/manifest/四道闸/执行/artifact/控制端工具）；P2 不做；P0 只出 runbook（deepin 未验证）。
- 协同：不碰 `src/llm_loop/runtime/*` 与 `tests/unit/test_install_upgrade_recovery.py`（GOAL-20261107-59104e61 在改）。
- 分支 `feat/peer-channel-20261107` / lane-bf158530。

## 已落地（commit）
- `0656d92a5` 设计 v3 + schemas + verify 脚本
- `f722f51be` models/errors/state（36 个封闭 reason_code）
- `3fe488d21` kinds 注册表 + 契约不变量测试
- `d5bf6eb01` store/admission（flock + 原子替换 + generation；admission O_EXCL 不可覆盖）
- `46cf7a562` 存储测试（`pytest tests/peer -q` = 15 passed，ruff 干净）
- T3 `peer/auth.py` + `peer/pair.py` + 41 条测试（`pytest tests/peer -q` = 56 passed, 2 skipped）

## 认证契约（逐字取自 DESIGN §5.8.3；改=契约变更）
头：`X-Peer-Node-Id` / `X-Peer-Ts` / `X-Peer-Nonce` / `X-Peer-Sig`。
canonical（5 行，`\n` 连接，字段含换行即拒）：
`METHOD(大写)` / `PATH(含 query、不含 host)` / `SHA256_HEX(BODY)` / `TS(epoch 秒)` / `NONCE(32 hex)`。
signature = `base64(HMAC-SHA256(K_oe, canonical))`。
时间窗 ±300s；nonce 缓存 600s、按 node_id 分桶、LRU 上限 10000。
校验顺序（本身是安全属性）：头齐全 → 节点已知 → 时间窗 → 验签 → nonce 落账
（先验签再落账，防未认证方用垃圾 nonce 污染重放窗）。
边界：对称密钥认证（K_oe 泄露=该方向可被完全冒充）；重放窗为进程内内存（重启清空，仅剩时间窗）。

> 勘误（2026-11-07 晚）：本文件上一版把四头名与 canonical 写成了自创形式
> （`X-LFL-Peer-*` / 8 行 / hex 签名 / 300s 窗）。实现已按 §5.8.3 改正，测试覆盖
> 5 行布局、base64 形态、600s/LRU 上限。教训：写代码前先读定契约的那一节。

## 短指纹派生（两侧必须一致）
`base64.b32encode(sha256(ed25519_pubkey_raw).digest()[:20])` → 32 字符（A-Z2-7）→ 每 4 字符 `-` 连接。
PAIR-CONFIRM 的 `link_secret` 由**控制端**生成（32 随机字节 base64），受控端 0600 落盘。
`build_offer`/`build_confirm` 输出已用 jsonschema 实测过 `pair-offer` / `pair-confirm` schema（非仅形状自检）。

## 不变量（改代码前必读）
1. `non_idempotent` ⇒ `supervised_only`（`test_peer_contract.py` 强制）。
2. 任务态以 `receipt.schema.json` 为准：拼写 `cancelled`（两 l）；`expired` 不是任务态，grant 过期 = `denied + grant_expired`。
3. 闸序：认证 → 策略 → 授权 → admission 落盘 → 执行 → 回执；拒绝先于副作用。
4. 错误码封闭：只用 `errors.REASON_CODES`（36 个）；新增=改契约+升版本。
5. manifest 不含文件内容/密钥/系统信息；`inject_type != none` ⇒ `capture_only=True`。

## 下一步
1. ~~T3 auth/pair~~（已完成）；`web/peer_routes.py`（build_router，GET `/api/peer/manifest` 四头 HMAC；store 鸭子类型：read_secret/get_node/node_state/list_grants/touch_node）挪到挂载那一步一起做。
2. T4：`peer/policy.py`（闸2/3）、`executor.py`、`artifacts.py`；fs.read 首切片，复用 write_scope/sandbox。
3. T5：`tools/builtin/peer_tools.py`（peer_list/dispatch/task/fetch）。
4. 挂载：`web/routes.py` `include_router`（不带 require_api_key，认证由 peer HMAC 承担）+ `web/peer_routes.py`；共享大文件单独提交并 rebase。
5. T6：T1–T10/U1–U10 应拦输入实测 + 全量 pytest + RULE-AI-28 独立审查 → lane 合并。

## 运行时限制（实测）
子代理上下文预检在 `tokens_in≈180k` 时直接失败且无 `search_archive` 兜底。委派时只给 ≤3 个小文件、
禁止整篇读设计文档、单任务 ≤30 轮；否则主代理直写。
