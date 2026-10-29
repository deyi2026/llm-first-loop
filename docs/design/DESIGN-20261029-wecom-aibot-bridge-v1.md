# DESIGN-20261029 — 企业微信智能机器人双向对话桥（WeCom AIBot Bridge）

- 状态：设计稿（待实现）
- 日期：2026-10-29
- 决策输入（用户已确认）：入口 = 企业微信 App → 智能机器人；方向 = 双向对话；主体 = 企业微信可用
- 上游调研：`docs/research/2026-10-29-wechat-integration-survey.md`
- 事实基线：本设计所有「已核实」条目均有本轮工具回执支撑；「未核实」条目显式标注

---

## 一、范围与非目标

### 目标
在企业微信 App 内，与 LFL 双向对话：用户在企微给机器人发消息 → LFL 处理并回复；LFL 侧异步任务完成后可主动推送通知。

### 非目标（本设计不覆盖）
- 个人微信 App 内对话（无等价官方通道，需公众号/客服另立设计）
- 公众号内容发布（仓库已有 `docs/promotion/` mp.weixin 链路，不重复建设）
- 企微消息推送 webhook（单向场景，与本设计选型不同）
- itchat/wechaty 类个人号自动化（无官方 API，风险与合规成本高）

### 选型结论
采用**企业微信智能机器人 · WebSocket 长连接（API 模式）**。

理由（已核实）：
1. 免公网 IP、免加解密——本机可直接连，无需隧道
2. 官方 Python SDK 存在且成熟度可用：`wecom-aibot-python-sdk` 1.0.2（2026-03-23 发布，PyPI），导入名 `aibot`，覆盖鉴权/心跳/重连/流式/卡片/主动推送/文件解密
3. 与本仓库飞书桥的能力面几乎一一对应，可平移骨架

---

## 二、已核实事实基线

### 2.1 官方 SDK（已核实：PyPI JSON + 解包 wheel 源码）

| 项 | 事实 |
|---|---|
| 包名 | `wecom-aibot-python-sdk`（**不是** `aibot-python-sdk`——按后者查 PyPI 得 404） |
| 版本 / 发布日 | 1.0.2 / 2026-03-23 |
| 导入名 | `aibot`（`from aibot import WSClient, WSClientOptions, generate_req_id`） |
| 模块构成 | `client.py` `ws.py` `api.py` `types.py` `message_handler.py` `crypto_utils.py` `logger.py` `utils.py` |
| 依赖 | `websockets>=12.0`、`aiohttp>=3.9`、`pyee>=11.0`、`cryptography>=42.0`、`certifi` |
| Python | `>=3.8`（本仓库 `requires-python >=3.13`，兼容） |
| 许可 | wheel 内含 `licenses/LICENSE`（1038 B）——**具体授权条款未逐字核**，商用前需人工确认 |

客户端公开方法（读 `aibot/client.py` 源码逐个核对签名）：

| 方法 | 签名要点 | 用途 |
|---|---|---|
| `connect()` | `async` → `WSClient` | 建连 + 自动 `aibot_subscribe` |
| `disconnect()` | 同步 | 主动断开 |
| `reply(frame, body, cmd=None)` | 透传 `frame.headers.req_id` | 通用回复 |
| `reply_stream(frame, stream_id, content, finish=False, msg_item=None)` | 同一次回调刷新须**共用同一 req_id** | 流式回复 |
| `reply_welcome(frame, body)` | 仅 `enter_chat` 事件，5 秒内 | 欢迎语 |
| `reply_template_card(frame, body)` | 模板卡片 | 结构化回复 |
| `reply_stream_with_card(...)` | 流式 + 卡片组合 | 组合回复 |
| `update_template_card(frame, body)` | 卡片点击事件后 5 秒内 | 卡片更新 |
| `send_message(chatid, body)` | 主动推送，`body` 支持 markdown/template_card | 异步通知 |
| `download_file(url, aes_key=None)` | 返回 `(bytes, filename)` | 附件下载解密 |

事件（pyee emitter，由 `aibot/message_handler.py` 分发）：
`message` / `message.text` / `message.image` / `message.mixed` / `message.voice` / `message.file`；
`event` / `event.enter_chat` / `event.template_card_event` / `event.feedback_event`。
连接层回调属性：`on_connected` / `on_authenticated` / `on_disconnected` / `on_message` / `on_reconnecting` / `on_error`。

配置项 `WSClientOptions`：`bot_id`、`secret`、`reconnect_interval`（默认 1000ms）、`max_reconnect_attempts`（默认 10，-1 无限）、`heartbeat_interval`（默认 30000ms）、`request_timeout`（默认 10000ms）、`ws_url`、`logger`。

### 2.2 协议（已核实：官方文档 path/101463 全文）

- WS 端点：`wss://openws.work.weixin.qq.com`
- **单机器人同时只能有一个长连接**：新连接完成 `aibot_subscribe` 会踢掉旧连接，旧连接收到 `disconnected_event` 后被服务端主动断开
- API 模式二选一：长连接 ⟷ 接收消息回调地址；切换会使另一模式失效
- 命令面：`aibot_subscribe` / `aibot_msg_callback` / `aibot_event_callback` / `aibot_respond_msg` / `aibot_respond_welcome_msg` / `aibot_respond_update_msg` / `aibot_send_msg` / `ping`
- 消息类型回调：`text` `image` `mixed` `voice` `file` `video`
- `from.userid` 明文与否取决于机器人创建者是否企业超级管理员；否则为加密 userid（可经自建应用转明文）
- `body.compat_info` 存在 ⇒ 非普通用户消息（`ai_assistant` / `channel` 来源）
- 加密：AES-256-CBC，PKCS#7 填充至 32 字节倍数，IV = aeskey 前 16 字节；下载 URL 5 分钟内有效
- 流式：同一次回调的所有刷新共用同一 `req_id`；`stream.id` 标识流式消息；**开始流式后 10 分钟内必须 `finish=true`**
- 回复窗口：收到回调后 **24 小时**内可向该会话回复
- 频率：回复 + 主动推送合计 **30 条/分钟、1000 条/小时**（按会话）
- 主动推送前置条件：用户须先在会话中给机器人发过消息
- `aibot_send_msg` 的 `chat_type`：1=单聊（chatid 填 userid）、2=群聊（填 chatid）、0 或不填=兼容（优先按群聊解析）
- `aibot_send_msg` 的 `msgtype` 支持 `template_card` / `markdown` / `file` / `image` / `voice` / `video`
- `markdown.content` 最长 20480 字节（utf-8）
- 欢迎语仅适用 `enter_chat`，事件回调后 5 秒内必须发
- 卡片更新仅适用 `template_card_event`，5 秒内必须发

### 2.3 本仓库现状（已核实）

| 项 | 事实 |
|---|---|
| 依赖 | `websockets>=14.0` 已在（满足 SDK 的 `>=12.0`）；`lark-oapi>=1.7.2` 为飞书侧；`pycryptodome>=3.23` 已有 |
| 飞书桥 | `src/llm_loop/feishu/` 12 模块：`bridge.py`(1419行) `handlers.py`(983行) `session_map.py`(163行) `config.py` `rest.py` `cross_sync.py` `streaming_card.py` `approval.py` `compensation.py` `restart_guard.py` `resume.py` `card_utils.py` `__init__.py` `__main__.py` |
| 消息契约 | `FeishuMessage` dataclass（`message_id`/`sender_id`/`chat_id`/`msg_type`/`text`/`is_group`/`sender_type`/`file_key`/`file_name`/`raw`/`reply_receive_id`/`reply_receive_id_type`）；`ReplyFn = Callable[[str, str, str], None]` = (receive_id, text, receive_id_type) |
| 会话映射 | `SessionMap` 键：私聊 `p:{open_id}` / 群聊 `g:{chat_id}`；持久化 JSON + RLock；`owner_open_id` 支持与 Web 端共享同一会话；`_mark_channel` 标记 `feishu:p2p:*` / `feishu:group:*` |
| 桥进程模型 | 单 worker 线程 + 有界队列（`_MAX_MSG_QUEUE` 默认 64），事件回调只 marshal 入队——**LLM 推理可达分钟级，不能阻塞 SDK 的 asyncio loop**（否则心跳停发被服务端 3003 断开）；优雅退出 `wait(10)+drain(3) ≤ GRACE_S(15)` |
| 出站工具 | `src/llm_loop/introspection/tools_feishu_outbound.py` 定义 `SEND_FEISHU_MESSAGE_TOOL_DEF` 等；`registry_feishu.py` 挂载 |
| 服务治理 | `src/llm_loop/tools/builtin/service_control.py`：`service` 枚举 `("web","feishu","learning")`，`target` 枚举 `("web","feishu","learning","all")` |
| 测试 | `tests/feishu/` 有对应测试目录（`test_bridge.py`/`test_config.py`/`test_handlers.py` 等） |
| 仓库痕迹 | `src/` 下无任何 `wecom`/`weixin` 引用——干净起点，无既有冲突 |

---

## 三、SDK 能力缺口（已核实：逐模块读源码比对官方文档）

以下三处 **SDK 未覆盖**，必须在本仓库侧补齐，否则会出现静默行为差异：

| 缺口 | 官方协议 | SDK 现状 | 应对 |
|---|---|---|---|
| `video` 消息类型 | 支持回调 | `types.py` `MessageType` 仅 text/image/mixed/voice/file；`message_handler.py` 无 video 分支 → **落到 `unhandled` 分支静默丢弃** | 本仓库侧直接监听 `message` 原始事件（SDK `emitter.emit("message", frame)` 对所有消息类型都触发），自行按 `msgtype` 分发，不依赖 SDK 的细分事件 |
| `disconnected_event` | 连接被踢时推送 | `EventType` 枚举无此项；SDK 会 emit `event` 但不发 `event.disconnected_event` | 监听 SDK 的原始 `event` 事件，解析 `body.event.eventtype == "disconnected_event"` 自行处理（触发重连/告警） |
| `compat_info` | 标识非普通用户消息 | SDK 不解析该字段 | 本仓库侧解析 `body.compat_info`，非空则跳过（避免智能助理/频道消息误触发机器人） |

**结论：SDK 用于连接管理（鉴权/心跳/重连/加解密/文件下载），消息分发与语义判断在本仓库侧实现。** 这样既复用官方连接层，又不把协议缺口带进生产。

---

## 四、架构设计

### 4.1 模块布局

```
src/llm_loop/wecom/
├── __init__.py        # build_bridge / start_bridge / main（对齐 feishu/__init__.py）
├── __main__.py        # 进程入口
├── config.py          # WeComConfig + load_wecom_config()
├── session_map.py     # 会话映射（键 p:{userid} / g:{chatid}）
├── messages.py        # WeComMessage dataclass + 帧解包
├── dispatcher.py      # 帧 → WeComMessage 分发（含 SDK 缺口补齐）
├── handlers.py        # WeComMessageHandler（引擎调用 + 回复）
└── bridge.py          # WeComBridge（SDK 连接生命周期 + 单 worker 线程 + 队列）
```

刻意**不**新建 `rest.py`：企微侧无 REST 出站通道，一切走 WS。

### 4.2 关键契约

```python
@dataclass
class WeComMessage:
    message_id: str
    sender_id: str            # from.userid（可能是加密 userid）
    chat_id: str              # 群聊 chatid；单聊为空
    chat_type: str            # "single" / "group"
    msg_type: str             # text / image / mixed / voice / file / video
    text: str = ""
    is_group: bool = False
    sender_type: str = ""     # user / app（防循环）
    file_url: str | None = None
    file_aeskey: str | None = None
    file_name: str = ""
    raw: dict[str, Any] | None = None
    reply_receive_id: str = ""        # 群聊 chatid / 单聊 userid
    reply_receive_id_type: str = ""   # "chatid" / "userid"
    req_id: str = ""                  # 本次回调 req_id —— 流式回复必须透传
```

`req_id` 是飞书侧没有的**新增必备字段**：企微回复靠透传 `req_id` 关联同一次回调，流式刷新还须共用同一 req_id。

回复回调签名（与飞书不同，因为企微回复必须绑定 req_id）：

```python
# 流式回复需要 req_id，故 reply_fn 接收 req_id 作为首参
WeComReplyFn = Callable[[str, str, str, str], None]  # (req_id, receive_id, text, receive_id_type)
```

主动推送走独立通道（不依赖回调）：

```python
WeComPushFn = Callable[[str, str, str], None]  # (chat_id, chat_type, text)
```

### 4.3 会话键与推送目标

| 场景 | 映射键 | 推送目标 |
|---|---|---|
| 单聊 | `p:{userid}` | `chatid=userid`, `chat_type=1` |
| 群聊 | `g:{chatid}` | `chatid=chatid`, `chat_type=2` |

`SessionMap` 平移飞书实现，键前缀 `p:`/`g:` 沿用，但**必须用独立映射文件**——与飞书会话文件路径不能共用，避免跨通道污染。`owner_userid` 复刻 `owner_open_id` 的跨端共享语义：owner 单聊与 Web 共享同一 session。

### 4.4 线程模型（照搬飞书已验证的结论）

飞书桥的注释记录了一个真实故障：事件回调内同步跑分钟级推理 → SDK asyncio loop 被阻塞 → 心跳停发 → 服务端 3003 断开。**企微侧同理会中招**（同样有 30s 心跳与 `max_reconnect_attempts`）。

因此：
- SDK 的 asyncio loop 独立跑在一个线程（`asyncio.run` 封装）
- SDK 事件回调**只做 marshal + 入队**（有界队列，容量对齐 `_MAX_MSG_QUEUE=64`）
- 单 worker 线程从队列取消息 → 调 `LoopEngine.run` → 回队列结果
- 回复动作从 worker 线程投递回 asyncio loop（`asyncio.run_coroutine_threadsafe`）执行

### 4.5 主动推送（异步通知）落地方式

`send_message(chatid, body)` 的实现是 `full_body = {"chatid": chatid, **body}`——**`chat_type` 必须由调用方放进 `body`**，`send_message` 不自动填。封装层显式处理，避免单聊/群聊解析歧义。

限流：30 条/分钟、1000 条/小时按会话。企业微信侧按会话计数，本仓库侧加一个简单的按会话令牌桶做前置节流（fail-open 记日志，不阻断）。

---

## 五、实施计划

人日为**估算**，非事实；实际以任务完成度为准。

### M0 — 打通链路（可验证最小闭环）
目标：企微发一句话，LFL 在企微回一句话。

| 步骤 | 产出 | 完成判据 |
|---|---|---|
| M0-1 | 加依赖 `wecom-aibot-python-sdk==1.0.2` | `uv pip install` 成功，`import aibot` 可用 |
| M0-2 | `config.py`：`WeComConfig` + `load_wecom_config()`（env: `WECHAT_BOT_ID` / `WECHAT_BOT_SECRET` / `WECHAT_SESSION_MAP_PATH` / `WECHAT_OWNER_USERID`——键名对齐官方 SDK `wecom-aibot-python-sdk` README，实现以此为准） | 配置可从 env 加载，缺 `bot_id`/`secret` 时明确报错 |
| M0-3 | `messages.py` + `dispatcher.py`：帧 → `WeComMessage`；含三处 SDK 缺口补齐（video / disconnected_event / compat_info） | 单元测试覆盖 text/image/video/compat_info 四类帧 |
| M0-4 | `bridge.py`：SDK 连接 + 事件回调只入队 + 单 worker 线程 + 优雅退出 | 断开后可干净退出，无残留线程 |
| M0-5 | `handlers.py`：接 `LoopEngine`，走通一次问答 | 企微发出消息，LFL 回复内容正确 |
| M0-6 | `session_map.py`：会话键映射，持久化 | 同一 userid 两次对话落到同一 session |

**M0 需要用户提供**：企业微信管理后台创建智能机器人，取 `BotID` + `Secret`。这是唯一的人工前置。

### M1 — 双向对话完整体验
| 步骤 | 产出 | 完成判据 |
|---|---|---|
| M1-1 | 流式回复：`reply_stream` + 同 req_id 刷新 | 长回复渐进呈现，非一次性 |
| M1-2 | 欢迎语（`enter_chat` 5 秒内）与卡片回复 | 新用户进群收到欢迎语 |
| M1-3 | 附件：图片/文件下载解密（`download_file`）→ 交引擎 | 发一张图，LFL 能识别内容 |
| M1-4 | `send_wecom_message` 工具注册（`introspection/tools_wecom_outbound.py` + `registry_wecom.py`） | LFL 可在对话中主动给用户推消息 |
| M1-5 | 限流令牌桶 + 超限降级 | 超 30 条/分钟不触发服务端错误 |
| M1-6 | `service_control` 增 `wecom` 枚举（`service` 与 `target` 两处） | `service_control(action="status", service="wecom")` 可用 |

### M2 — 收尾与生产化
| 步骤 | 产出 | 完成判据 |
|---|---|---|
| M2-1 | `scripts/dsh_wecom.sh` 启动脚本（对齐 `scripts/dsh_feishu.sh`） | 一条命令拉起/停止 |
| M2-2 | 断线重连 + `disconnected_event` 告警 | 手动 kill 连接后自动恢复 |
| M2-3 | `tests/wecom/` 测试目录 | 与 `tests/feishu/` 对齐 |
| M2-4 | 运维文档（配置项、常见故障、限流表现） | 新机器可照文档部署 |

---

## 六、风险与对策

| 风险 | 等级 | 对策 |
|---|---|---|
| **单连接独占**：同一机器人同时只能一个长连接。若 LFL 主进程 + DSH 子代理同时起桥，后者会踢掉前者 | 高 | 桥进程内加单实例锁（本地文件锁）；`dsh_wecom.sh` 不独立起桥，改为复用主进程 |
| **SDK 未覆盖 video / disconnected_event / compat_info** | 中 | 已在 §3 给出对策：本仓库侧监听原始 `message`/`event` 事件自行分发 |
| **阻塞 loop 导致 3003 断开** | 中 | §4.4 线程模型：事件回调只入队；加心跳存活监控 |
| **加密 userid**：非超管创建的机器人 userid 为密文，无法与企微后台成员对应 | 中 | 权限设计中要求「机器人创建者为企业超级管理员」；或经自建应用转明文 userid |
| **主动推送前置条件**：用户未先发过消息时无法推送 | 中 | 推送前检查该会话是否已有用户交互，无则降级为不推送并记日志 |
| **24 小时回复窗口**：超过窗口回复会失败 | 低 | 会话映射记录 `last_message_ts`，超窗提前改走主动推送或提示用户 |
| **10 分钟流式窗口**：长任务流式未收尾会被判超时 | 低 | 流式刷新前置检查，超时自动 `finish=true` 收尾 |
| **SDK 许可条款未逐字核** | 低 | 商用前人工确认；内部使用风险低 |
| **依赖新增**：`aiohttp` / `pyee` / `cryptography` 进入依赖树 | 低 | 与现有 `websockets` / `pycryptodome` 无冲突；`cryptography` 与 `pycryptodome` 并存需注意二者 API 不同 |
| **系统代理劫持 WS 连接**：`websockets`≥15 自动读系统代理，macOS 的 `socks` 项优先级高于 `https`，会把 `wss://` 改写为 `socks5h://` 并要求装 `python-socks`，否则连接层直接失败 | 中 | **已实测复现并修复**：`bridge.start()` 连接前调 `ensure_proxy_bypass()` 把 SDK 默认端点主机（`aibot.ws.DEFAULT_WS_URL`）加入 `no_proxy`，强制直连——与本设计「本机直连、无需隧道」前提一致，不依赖本机代理软件是否在跑。实测：修复前报 `python-socks is required to use a SOCKS proxy`，修复后握手成功、服务端返回 853000 凭据错误（即网络层已通） |

---

## 七、未核实项（实施前需人工确认）

1. **SDK 授权条款**——wheel 内 LICENSE 存在但未逐字核，商用前确认。
2. **机器人创建者权限要求**——`from.userid` 是否明文取决于创建者是否超级管理员，需在真实企业后台确认。
3. **`disconnected_event` 的实际触发时机**——文档说明被踢时推送，但具体时序未实测。
4. **SDK 与真实服务端的心跳/重连行为**——文档与源码一致，但未做真实连接验证（需真实 BotID/Secret）。
5. **`aibot_send_msg` 在无 `chat_type` 时的实际解析**——文档说"兼容模式优先按群聊解析"，单聊场景需实测确认。

---

## 八、验收标准（M0 完成定义）

- [ ] 企微 App 内给机器人发文本，收到 LFL 回复
- [ ] 同一用户连续两次对话，落到同一 session（`session_map.json` 可验证）
- [ ] 进程收到 SIGTERM 后 15 秒内干净退出
- [ ] 断开网络后恢复，桥自动重连
- [ ] `compat_info` 非空的消息不会触发机器人回复
- [ ] video 类型消息被正确解析（不静默丢弃）
- [ ] `tests/wecom/` 单测通过
- [ ] 仓库无 `wecom` 相关 lint/类型错误

---

## 附：与上游调研的差异（诚实说明）

`docs/research/2026-10-29-wechat-integration-survey.md` 当时记录「企微 Python SDK 的正式分发形态未核（PyPI 包名未核）」，并给出「`lark_oapi` 那套 WS 桥骨架可直接平移」的推断。

本轮已核实：官方 SDK 确实存在且在 PyPI 上正式分发，包名 `wecom-aibot-python-sdk`。因此**协议层不自研**，改为复用官方 SDK 的连接管理；飞书桥的骨架平移仍成立，但平移的是**会话/引擎/线程模型**部分，而非协议层。

