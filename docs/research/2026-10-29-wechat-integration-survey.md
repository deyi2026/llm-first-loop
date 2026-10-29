# 微信接入调研（2026-10-29）

## 0. 一句话结论

「接入微信」不是一个技术问题而是**五个方向差异极大的问题**：

- 想要**双向对话**（像飞书那样在 App 里跟 LFL 说话）→ 官方可行且与本仓库飞书桥**同构**的只有 **企业微信智能机器人（API 模式 · WebSocket 长连接）**；
- 想要**在个人微信 App 里**对话 → 只有 **公众号（服务器配置 + 客服消息）** 和 **微信客服** 两条官方路，两者都需要**公网 HTTPS 回调**；
- 只要**单向推送**（把结果/提醒推出去）→ **企微消息推送 webhook**，0.5 人日即可，最便宜；
- **个人微信自动化**（itchat/wechaty/注入）无官方 API，**不建议**。

推荐顺序：**先做企微智能机器人长连接桥**（复用飞书桥骨架），公众号作为"必须待在个人微信里"时的补充路径。

---

## 1. 先核请求：「接入微信」的目标分叉

| # | 目标 | 典型用途 | 对应路径 | 本仓库现状 |
|---|---|---|---|---|
| A | 消息通道（双向） | 手机上跟 LFL 下指令、收回复 | 企微智能机器人 / 企微自建应用 / 公众号 | 飞书桥已具备对等能力，可直接移植 |
| B | 单向推送 | LFL 跑完任务推结果、告警 | 企微消息推送 webhook / 公众号模板消息 | 无 |
| C | 内容发布 | 把 LFL 产出的文章发到公众号 | 公众号发文 | **已有**：`docs/promotion/` 下 mp.weixin.qq.com 浏览器自动化链路 |
| D | 群内 @机器人 | 群里 @LFL 干活 | 企微智能机器人（群聊 chattype=group） | 无 |
| E | 个人号自动化 | 直接用自己微信号收发 | 非官方（逆向/注入/UI 自动化） | 不建议 |

> A 与 C 是两件事：C 已经能用，A 还没有。本报告主要回答 A/D，兼顾 B。

---

## 2. 各路径事实卡（官方文档，采集于 2026-10-29）

### 2.1 企业微信智能机器人（API 模式）—— 最贴合飞书桥

官方明确提供**两种 API 模式**（文档：企业微信开发者中心 → 智能机器人 → 长连接）：

| 特性 | Webhook（短连接） | WebSocket（长连接） |
|---|---|---|
| 服务端要求 | **需要公网可访问的 URL** | **无需固定公网 IP** |
| 加解密 | 需要对消息加解密 | 无需加解密 |
| 延迟/实时性 | 较高 / 一般 | 低 / 好 |
| 复杂度 | 低 | 较高（需维护心跳） |
| 适用场景 | 普通回调 | 高实时性、无固定公网 IP |

长连接要点（均取自官方文档原文）：

- 端点：`wss://openws.work.weixin.qq.com`
- 凭证：**BotID + Secret**（长连接专用 Secret，与回调模式的 Token/EncodingAESKey 不同）
- 建连后先发订阅请求 `aibot_subscribe`（有频率保护，订阅成功后不要反复请求）
- 收消息：`aibot_msg_callback`，body 含 `msgid`（排重）、`aibotid`、`chatid`、`chattype`（`single`/`group`）、`from.userid`、`msgtype`、`text.content`
- 主动推送：`aibot_send_msg` —— 官方定位为"**定时提醒、异步任务通知、告警推送**"，正对 LFL 的异步完成通知
- 流式回复：回复消息带 `finish=true` 结束流式消息
- 消息类型：text / markdown / template_card 等
- 媒体上传：`aibot_upload_media_*`（分片上传，支持图片/语音/视频/普通文件）
- 互斥约束：**同一 Bot 同一时间只能有一个有效长连接**，新连接订阅成功会踢掉旧连接（官方建议主备切换而非并发多连）；**API 模式二选一**，从回调模式切到长连接会使原回调地址失效，反之亦然
- SDK：官方提供 Node.js 与 Python SDK。**Python 侧已核实**：PyPI 包名 `wecom-aibot-python-sdk`（最新 1.0.2，2026-03-23 发布），导入名 `aibot`，覆盖鉴权/心跳/重连/流式/卡片/主动推送/文件解密。（2026-10-29 复核更新；先前记为"PyPI 包名未核"是因按 `aibot-python-sdk` 查询得 404，属包名猜错。详见 `docs/design/DESIGN-20261029-wecom-aibot-bridge-v1.md`）

回调（Webhook）模式要点（文档：主动回复消息）：

- 回调中返回 `response_url`，业务处理完再异步回复：`POST https://qyapi.weixin.qq.com/cgi-bin/aibot/response?response_code=RESPONSE_CODE`
- **每个 response_url 只能调用一次，有效期 1 小时**
- 被动回复消息类型固定为 markdown / template_card；群聊主动回复会自动引用触发回调的用户消息

> 对 LFL 的意义：飞书桥的三大能力——**长连接免公网、流式过程可见、完成后主动推送**——企微智能机器人都具备。映射几乎是一一对应的。

### 2.2 企业微信自建应用

- 接收消息需在后台配置**回调 URL（公网 HTTPS）+ 加解密**（文档 path/90238 一节）
- 主动发消息：`/cgi-bin/message/send`，凭 `access_token` + `agentid`（文档 path/90236）
- 支持单聊/群聊/应用消息；微工作台消息存在文本长度限制（如 20 字节）
- 需要**企业主体 + 应用审批 + agentid/secret**，比智能机器人重

### 2.3 企微消息推送（群机器人 webhook）—— 最便宜的单向方案

- 端点：`https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=KEY`
- 官方限制原文：「**每个消息推送发送的消息不能超过 20 条/分钟**」（文档页标题现为「消息推送配置说明」）
- 支持 markdown_v2、template_card 等类型
- **只能发不能收** → 不能当对话通道

### 2.4 公众号（仓库已在用发文链路）

- 官方文档站已重构：原"公众号"文档拆为**公众号（原订阅号）**与**服务号**两套（`developers.weixin.qq.com/doc/subscription/`）
- 官方明确公众号开发分两类：**调用服务端 API**（主动，如发送客服消息）与**事件与消息推送**（微信服务器推给开发者服务器）
- 门槛：部分高级接口需**微信认证**；官方提供**测试号**（扫码即得）用于零成本打通链路
- 接收消息需在公众号后台开启服务器配置（URL + Token + EncodingAESKey），消息以 XML 推送
- 仓库现状：`docs/promotion/` 下已有 mp.weixin.qq.com 登录态自动化发文脚本（`_pub_wx_agentnow.py` / `_rrsi_wx.py` 等，token 直接写在脚本里）——**这是浏览器自动化，不是 API 通道**

### 2.5 个人微信自动化（不建议）

- 无官方 API。`wechaty-puppet-wechat` 官方 README 明确其限制：**不支持新注册账号**（Web 微信已下线）、**不支持企业微信消息收发**
- 社区现实方案是商业 puppet（padlocal 等付费 token）或本地注入/UI 自动化
- 本机相关事实：本机有 macOS 微信客户端，`desktop_perceive` 是**只读**感知（无点击/键入），所以走 UI 自动化需要另写一套驱动，且微信升级即失效、有封号风控
- **结论：不做。** 如确需个人号收发，唯一可接受的是本地单账号自用 + 明确接受封号风险

### 2.6 微信客服

- 企微开发者中心存在完整客服 API 段（客服账号列表/增删改/分配会话、App 跳转微信客服等，path/94661 起）
- 微信用户侧发起会话、企业侧 API 收发 → 是"个人微信里对话"的另一条官方路
- 前提：企业微信主体 + 客服账号配置

---

## 3. 与本仓库的映射（文件级落点）

飞书桥是 `src/llm_loop/feishu/`。**注意分工（已核实）**：`lark_oapi` 只用于 `feishu/rest.py` 的 REST 出站调用（发消息、建文档、表情回应等）；WS 长连接是飞书侧自研的 `_WsConnector`（连接/心跳/重连/收帧/队列/看门狗）。因此微信桥可平移的是**会话映射、引擎调用、线程与队列模型**；传输层应改用官方 `aibot` SDK 而非平移 `_WsConnector`。

| 能力 | 飞书侧现有实现（已核实） | 微信侧对应改造 |
|---|---|---|
| 配置 | `feishu/config.py`（env：`FEISHU_APP_ID/SECRET/WS_ENABLED/SESSION_MAP_PATH/CHUNK_LIMIT/TYPING_ACK/STREAMING/OWNER_OPEN_ID`） | 新 `wecom/config.py`：`WECOM_BOT_ID/WECOM_SECRET/WECOM_MODE(ws|webhook)` |
| 传输 | `feishu/bridge.py`（`_WsConnector`：连接/心跳/重连/收帧/队列/看门狗） | 新 `wecom/bridge.py`：aibot WS 客户端（订阅、回调分发、心跳重连、**单连接互斥**处理） |
| 会话映射 | `feishu/session_map.py`（open_id/chat_id → LFL sid） | 新 `wecom/session_map.py`（userid/chatid → sid） |
| 消息→引擎 | `feishu/handlers.py` | 复用引擎调用层，仅替换入参格式与出参渲染 |
| 流式过程 | `feishu/streaming_card.py` + `card_utils.py`（飞书卡片） | 企微为**流式消息 + finish 标志**，无卡片交互 |
| 主动发送 | `feishu/rest.py` | `aibot_send_msg`（长连接）/ `message/send`（自建应用）/ webhook（单向） |
| 审批指令 | `feishu/approval.py`（私聊 + open_id 白名单解析演进建议） | 按 userid 白名单平移 |
| 出站工具 | `introspection/registry_feishu.py` + `tools_feishu_outbound.py` → `send_feishu_message` | 新 `send_wecom_message`（注册链路同构） |
| Web→通道推送 | `web/feishu_push.py` | 新 `web/wecom_push.py` |
| 服务治理 | `tools/builtin/service_control.py`：`service` 枚举 `web/feishu/learning` | 枚举加 `wecom`（多处硬编码需同步） |
| 启动脚本 | `scripts/dsh_feishu.sh`（DSH 侧独立 profile） | `scripts/dsh_wecom.sh`（同构改写） |
| 客户端配置 | `runtime.toml` `[web]` 段 + `.env` 注入（`restart_system.sh` 注入） | 同构新增 `[wecom]` |

---

## 4. 推荐方案与阶段计划（估算是估算，非事实）

**M0 · 最小可用（约 1~2 人日）**
企微智能机器人长连接 + 文本收发：新建 `src/llm_loop/wecom/{config,bridge,session_map,handlers}.py` + `scripts/dsh_wecom.sh`。
验收：企微单聊发「你好」→ 收到回复；`aibot_send_msg` 能主动推一条。

**M1 · 通道完整（约 3~5 人日）**
流式回复、会话续接、审批指令、web→企微推送、`send_wecom_message` 工具注册、`service_control` 纳管与重启路径。

**M2 · 个人微信入口（约 2~3 人日，仅当确认需要时）**
公众号服务器配置（需公网 HTTPS；本机已装 `cloudflared`、`ngrok`，`frpc/caddy/tailscale` 未装）或微信客服。

**B 案 · 只要单向（≈0.5 人日）**
企微消息推送 webhook：LFL 侧写一个 `POST qyapi.weixin.qq.com/cgi-bin/webhook/send` 的工具，零长连接、零公网依赖；注意 20 条/分钟。

---

## 5. 需要你决定的三件事

1. **入口在哪**：个人微信 App（→ 公众号 / 微信客服）还是企业微信 App（→ 智能机器人）？这决定全部技术选型。
2. **方向**：只要 LFL→你（单向推送，最快）还是双向对话？
3. **主体**：能否用企业微信（智能机器人与客服都要企业主体）；公众号是否已有/能否认证（仓库已有发文链路可复用登录态）。

---

## 6. 未核验 / 不确定项（诚实标注）

- ~~企微智能机器人 Python SDK 的正式分发形态：官方仅给 `aibot_demo_python.tar.gz`，**PyPI 包名与版本未核**（可能需自行 vendor）~~ → **已于 2026-10-29 复核解决**：PyPI 包名 `wecom-aibot-python-sdk`，版本 1.0.2（2026-03-23），导入名 `aibot`。无需自行 vendor。
- 个人微信用户能否**直接在微信 App 内**与企微智能机器人对话：未找到官方明确表述，本次调研**未核到**（置信度中等）
- 公众号客服消息的 48 小时窗口在当前文档版本的具体措辞：未逐条核到
- 企微自建应用「微信端接收企业微信消息」的确切限制表述：未逐条核到
- 微信开放文档站改版后「接收消息」具体页面 URL 未定位（已核到公众号指南根页的两类对接划分）
- 第三方 puppet / UI 自动化的最新可用性与封号概率：无权威来源，本报告不做量化

---

## 7. 引用清单（全部采集于 2026-10-29）

企业微信开发者中心：
- 智能机器人长连接 https://developer.work.weixin.qq.com/document/path/101463
- 智能机器人·API 模式概述 https://developer.work.weixin.qq.com/document/path/101039
- 主动回复消息 https://developer.work.weixin.qq.com/document/path/101138
- 被动回复消息 https://developer.work.weixin.qq.com/document/path/101031
- 回调与回复的加解密方案 https://developer.work.weixin.qq.com/document/path/101033
- 自建应用与智能机器人的对接 https://developer.work.weixin.qq.com/document/path/101521
- 接收消息（自建应用） https://developer.work.weixin.qq.com/document/path/90238
- 发送应用消息 https://developer.work.weixin.qq.com/document/path/90236
- 消息推送配置说明（群机器人） https://developer.work.weixin.qq.com/document/path/91770

微信开放文档：
- 公众号（订阅号）开发指南 https://developers.weixin.qq.com/doc/subscription/

社区（仅用于说明风险面，非推荐）：
- wechaty-puppet-wechat（README 列明账号与能力限制） https://github.com/wechaty/wechaty-puppet-wechat

本仓库一手事实：
- `src/llm_loop/feishu/`（config/bridge/handlers/session_map/rest/approval/streaming_card/card_utils 等）
- `src/llm_loop/introspection/registry_feishu.py`、`tools_feishu_outbound.py`（`send_feishu_message` 工具）
- `src/llm_loop/web/feishu_push.py`、`src/llm_loop/tools/builtin/service_control.py`（服务枚举）
- `scripts/dsh_feishu.sh`、`scripts/feishu_smoke.py`
- `docs/promotion/`（已有 mp.weixin.qq.com 发文自动化）
