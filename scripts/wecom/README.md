# 企微桥端到端验证工具

三个脚本，按顺序用：

## 1. wecom_sdk_probe.py —— 网络/鉴权探针（不需桥接代码）

验证 SDK 能否连上企微并完成鉴权订阅。用于第一时间区分
「网络/鉴权/协议问题」与「桥接代码问题」。

前置：主区 `.env` 写入凭据：

    WECHAT_BOT_ID=<你的 BotID>
    WECHAT_BOT_SECRET=<你的 Secret>

运行：

    .venv/bin/python scripts/wecom/wecom_sdk_probe.py

输出 `PROBE_OK: 已连接并完成鉴权订阅` 表示连接层正常。

## 2. wecom_protocol_e2e.py —— 协议层端到端（不联网、不需凭据）

构造真实格式的企微回调帧，走 dispatcher → handler → 假引擎 → 回复，
验证 M0 核心目标在协议层成立：文本回复、req_id 绑定、多轮同 session、
video 不被静默丢弃、compat_info 被跳过。

运行：

    PYTHONPATH=$PWD/src .venv/bin/python scripts/wecom/wecom_protocol_e2e.py

## 3. wecom_bridge_inproc.py —— 进程内全链路（不联网、不需凭据）

用假 SDK 客户端驱动真实 WeComBridge，验证
SDK 回调 → 有界队列 → 单 worker 线程 → dispatcher → 假引擎 → 回复
的完整链路，以及 req_id 绑定与退出无残留线程。

运行：

    PYTHONPATH=$PWD/src .venv/bin/python scripts/wecom/wecom_bridge_inproc.py

## 真实端到端（需凭据 + 人工在企微 App 发消息）

    PYTHONPATH=$PWD/src .venv/bin/python -m llm_loop.runtime.launch wecom

然后在企业微信 App 里给机器人发一句话，应收到 LFL 的回复。

注意：运行时若提示 identity 影子模式告警，说明加载的是 `.releases/` 下的
发布快照而非工作树；此时用 `PYTHONPATH=$PWD/src` 指定工作树代码。
