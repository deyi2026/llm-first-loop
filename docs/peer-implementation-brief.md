# Peer 通道实施交接（lfl.peer.v1）

设计和契约真值源：`docs/DESIGN-20261107-deepin-remote-takeover-agent-interop.md`（1378 行，勿整篇灌上下文）
与 `docs/schemas/lfl.peer.v1/`；校验：`python3 scripts/verify_peer_schemas.py`（30 checks PASS，1 skipped）。

## 边界
- 做 P1（pairing/manifest/四道闸/执行/artifact/控制端工具）；P2 不做；P0 只出 runbook（deepin 未验证）。
- 协同：不碰 `src/llm_loop/runtime/*` 与 `tests/unit/test_install_upgrade_recovery.py`（GOAL-20261107-59104e61 在改）。
- 分支 `feat/peer-channel-20261107` / lane-bf158530。

## 已落地（commit）

> **SHA 时点说明（2026-11-08T13:00 补）**：本文件及 `docs/PEER-P0-T6-acceptance-20261108.md`、
> `docs/playbooks/PEER-P0-session-takeover-runbook.md` 中的提交短 SHA 均为 **rebase 之前**的时点值
> （rebase 前分支 tip = `425d4107a`）。为把 lane 的 base 从 `ee339e74d` 前移到 `cc8b0bc6c`，本分支
> 已于 2026-11-08 12:57 全量 rebase（22 提交），**所有 SHA 已重写**，上述短 SHA 在主线上不可解析。
> 查对应提交请按主题行（`git log --oneline`）匹配；patch 内容 rebase 前后逐字相同（已核 sha256 相等）。

- `0656d92a5` 设计 v3 + schemas + verify 脚本
- `f722f51be` models/errors/state（36 个封闭 reason_code）
- `3fe488d21` kinds 注册表 + 契约不变量测试
- `d5bf6eb01` store/admission（flock + 原子替换 + generation；admission O_EXCL 不可覆盖）
- `46cf7a562` 存储测试（`pytest tests/peer -q` = 15 passed，ruff 干净）
- T3 `peer/auth.py` + `peer/pair.py` + 41 条测试（`pytest tests/peer -q` = 56 passed, 2 skipped）
- T4 `peer/service.py` + `web/peer_routes.py` + `scripts/peer_serve.py`（独立 uvicorn + live 冒烟 19 项）
- T5 `20bae4dd4` 控制端四工具 + `web/_mount_peer_routes` 挂主 app；修 T4 回执可见性缺陷（`pytest tests/peer -q` = 137 passed, 3 skipped）
- T7 `2b27f475a`/`de8c933a9` `docs/playbooks/PEER-P0-session-takeover-runbook.md`（P0 会话接管 SOP + U8/U9 处置；**未在 deepin 实机实测**，文首与 §7/§8 逐项标注）

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

## 编排层（service.py）与一次契约缺陷修复
- `service.py`：manifest 构建 + submit 编排（形状校验 → 幂等查账 → 选租约 → 闸2/闸3 →
  落 submitted → 落 admitted 准入 → CAS 消耗额度 → queued/running/执行 → 回执）。
  拒绝与失败都返回带封闭 `reason_code` + `suggested_next` 的回执，不抛到 HTTP 层。
- `suggestions.py` 是 `reason-codes.json` 的生成物（测试断言键集合一致，防两处漂移）。
- 缺陷：`manifest.schema.json` 的 `allOf[0].if` 把 `inject_click` 写在了顶层而非 `desktop` 内，
  导致条件恒真、**任何 manifest 都被强制 `screenshot: true`**。已修正嵌套，并实测
  "inject_click=true + screenshot=false" 会被拒绝（不是只改不断言）。
  `scripts/verify_peer_schemas.py` 修复后仍 `RESULT: PASS (30 checks, 1 skipped)`。

## live 冒烟（真实 HTTP + 真实签名，2026-11-07）
`scripts/peer_serve.py`（独立 uvicorn 入口，未配对则拒启动）已跑通：
manifest 200 / 无签名 401 `peer_bad_signature` / 提交 fs.read → `succeeded` /
按 ref 取回产物字节完全一致 / 重放同 nonce 401 `peer_replay_detected` /
过期时间戳 401 `peer_stale_signature` / `/etc/hosts` 读取请求 return `denied` +
`path_outside_allowed_paths`。脚本在 `/tmp`（一次性冒烟，不进仓库），
仓库内可复核的是 125 条单测（含 TestClient 端到端 10 条）。

## T5 控制端四工具 + 主 app 挂载（commit 20bae4dd4）

**工具面**（`tools/builtin/peer_tools.py`，仅 `LFL_PEER_ENABLED=1` 注册；关闭时工具面与既有行为零变化）：
- `peer_list() -> {local_node_id, peers[]}`：逐个 GET manifest；`kinds` 原样保留 KindSpec 对象
  （`{kind, idempotency_class, supervised_only, params_schema_hint}`），不可达节点带
  `health=unreachable` + `reason_code`，不伪造在线。
- `peer_dispatch(peer_id, kind, params, expect?, deadline_s?)`：派单前**本地前置校验**
  `kind ∈ manifest.kinds`（缺失或不匹配即 `policy_task_kind_not_allowed`，fail-closed，不盲发）；
  `effect_id` 由 `sha256(run_key + canonical(peer,kind,params))` 派生（`eff_`+40 hex），
  同一 run 幂等、换参数即新任务——模型不需要记 effect_id。
- `peer_task(peer_id, task_id)`：取回执；`peer_fetch(peer_id, ref, to_path?)`：按 ref 取字节，
  重算 sha256 与 ref 不符即 `artifact_digest_mismatch`；默认落 `<peer_data_dir>/inbox/<sha256>`，
  给 `to_path` 才写工作区且必须先过 `current_write_scope`（拒绝 → `path_outside_allowed_paths`）。
- 传输层 `peer/client.py`：`base_url` 强制纯 origin（带路径/query 拒绝——canonical PATH 与
  服务端 `request.url.path` 必须逐字节一致）；所有非 2xx 映射封闭 reason_code；不重试。

**主 app 挂载**（`web/__init__.py::_mount_peer_routes`）：`LFL_PEER_ENABLED=1` 时挂
`build_peer_router`（不套 `require_api_key`，只认四头 HMAC）。配置六项：
`LFL_PEER_NODE_ID`（空则 `lfl-<hostname>`）/ `LFL_PEER_DISPLAY_NAME` / `LFL_PEER_DATA_DIR`
（空则 `<data_dir>/peer`）/ `LFL_PEER_TIMEOUT_S` / `LFL_PEER_KINDS`（空集=不开放任何 kind）/
`LFL_PEER_ENABLED`。`secret_for` 必须经 `secret_key_from_store` 转 bytes（`auth.sign` 直接把
secret 当 HMAC key 用）。

**修 T4 遗留缺陷（T5 联调暴露）**：T4 的 `get_receipt` 只比对 `task.node_id`（= 执行节点），
导致跨节点派单方永远读不到自己的回执（同 node_id 自测才通过）。改正：
- `post_task` 的 `requested_by` 由服务端按认证身份写入（payload 同名字段可伪造，不采信）；
- `get_task_for(node_id, task_id)` 与 `artifact_visible_to` 以 `requested_by`（旧数据回退
  `node_id`）判可见性。

**测试事实**：`tests/peer/test_peer_client.py` 11 条，用 TestClient 扮远端 + monkeypatch
`httpx.request`，签名/nonce/幂等/白名单/写侧拒绝全走真实路由栈；`pytest tests/peer -q` =
137 passed, 3 skipped；ruff 干净。**真实网络形态（独立进程 + 真端口）的应拦实测在 T6 做**，
本切片不宣称"闸已生效"。

## 下一步
1. ~~T3 auth/pair/manifest~~ / ~~T4 闸2-3 + artifact + 只读执行器~~ / ~~编排层 + HTTP 面 + live 冒烟~~（已完成）。
2. ~~T5 客户端工具 + 挂载主 app~~（已完成，见上节）。
3. ~~T7 deepin runbook~~（已完成：`docs/playbooks/PEER-P0-session-takeover-runbook.md`，未实测已标注）。
4. ~~T6 T1–T10/U1–U10 应拦实测~~（完成：`scripts/peer_acceptance.py` 真进程/真端口/真 HMAC，
   29 条 = PASS 25 / N/A 4 / FAIL 0，结果与 8 条实测缺陷见
   `docs/PEER-P0-T6-acceptance-20261108.md`；U4/U7/U9b/U8b 与 U5 的副作用前提**未覆盖**）。
5. ~~T8 lane 合并审查 → 入 main~~（完成：已合入 main；T8 三项验收在 main@52853d6c4 复跑全绿——
   `verify_peer_schemas.py` PASS(30,1 skipped)、`pytest -k peer` 225 passed、合并树==lane 树）。
6. T9-a ~~`fs.write` 执行器 + 闸4 写域门~~（完成，分支 `feat/peer-fs-write-gate-20261108`
   @65e44778f；**宣告面未开**：`EXECUTABLE_KINDS` 仍只读两种、manifest 不声称可写、
   准入 `supervised=False` 仍 `requires_supervised_execution`。闸4 写域由
   `LFL_PEER_WRITE_ROOT` 显式声明，**未声明即全拒**；与闸3 各自独立拒绝
   （域外但租约内→`sandbox_denied`；租约外但域内→`path_outside_allowed_paths`）。
   测试：`pytest tests -k peer` 246 passed / 5 skipped）。
7. T9-b 待做：有人在场通道（supervised 准入 + 本机确认）+ 宣告面开启。
   设计已落 `docs/DESIGN-20261108-peer-supervision-channel.md`（仅设计，未实施）：
   默认关闭（`LFL_PEER_SUPERVISION=0`）、新增 `awaiting_supervision` 非终局态、
   TTY CLI 逐次确认且票据绑定 `params_digest`、执行前重判闸3、宣告按
   "handler ∩ 本节点配置完备"条件化。宣告面须与契约 P1 修复的
   `example-kinds==registry` 零漂移检查同批落地（**该检查当前尚未落地**）。
   重测范围更正：**U5（部分副作用后 kill -9）**属本任务；**U7（`desktop.type` 注入）
   与 `fs.write` 无关，属 P2-B 桌面面**——上一版把 U5/U7 并列写在此处，是错的。

## 运行时限制（实测）
子代理上下文预检在 `tokens_in≈180k` 时直接失败且无 `search_archive` 兜底。委派时只给 ≤3 个小文件、
禁止整篇读设计文档、单任务 ≤30 轮；否则主代理直写。
