---
name: mirror-restart
description: 镜像区常驻服务（web :8903 + 飞书桥）重启/启动的标准操作——唯一正确命令、六大禁忌、四步验证、故障对照表。需要重启/启动/修复镜像服务时先加载本技能。
---
# 镜像服务重启（标准操作）

## 唯一正确方式

```bash
cd /Users/yyj/Project/llm-first-loop-mirror
bash scripts/restart_mirror.sh status   # 先看现状
bash scripts/restart_mirror.sh all      # 全量重启（web + 飞书）
bash scripts/restart_mirror.sh web      # 只 web
bash scripts/restart_mirror.sh feishu   # 只飞书
```

**任何场景都用这个脚本**——包括：自重启（改完代码/.env 生效）、代用户重启、崩溃恢复、抢回端口。不要自创启动方式，不要"这次很简单就直接跑 python"。

## 为什么必须用脚本（内置六层防御，每层都是实证事故）

1. **按端口杀**（`lsof -tiTCP:8903`）——主/镜像进程命令行几乎相同，模式匹配必误杀
2. **PYTHONPATH=镜像 src 显式注入**——共享 venv 的 editable .pth 属主区（协议 §3），不注入就跑主区代码
3. **跨区残留清理**（PYTHONPATH / LFL_DATA_DIR / DATA_DIR / DSH_HOME / FEISHU_APP_ID+SECRET）——环境残留是历次串区事故根源；注意 `DATA_DIR` 与 `LFL_DATA_DIR` 是**两个不同的键、两套消费者**，清理必须成对
4. **凭证配套加载**——防"主区 app_id + 镜像 secret"错配对（预检 10014）
5. **nohup 脱离会话进程树**——AI 的工具 shell 退出时不会清理它，服务不陪葬
6. **启动后自动验证**——web health 轮询 + 飞书心跳轮询（90s 窗口，连上即刻返回）

## 六大禁忌（全部实证过）

| # | 禁忌 | 后果 |
|---|---|---|
| 1 | 在自己 shell 里直接 `python -m llm_loop.feishu` / `llm_loop.web`（前台或裸 `&`） | **shell 退出进程陪葬**——日志特征：「已启动→已停止」中间零错误（2026-08-30 实证） |
| 2 | `launchctl submit` 执行重启命令 | launchd **无限重拉**，服务循环重启 100+ 次（2026-08-28 实证） |
| 3 | `pkill -f "llm_loop.web"` 之类模式杀 | **主区服务陪葬**（两区命令行无法区分） |
| 4 | `cd 主区 && WEB_PORT=8903 nohup …` 跨区起服务 | **端口劫持**：镜像 web 显示主区内容（2026-08-29 实证） |
| 5 | 改完代码/.env 不重启就宣称生效 | 运行进程仍是旧代码旧配置（提交≠生效，重启才生效） |
| 6 | 见脚本告警"⚠️ 未见 connected"就反复重启 | WS 握手正常波动 15~55s，以**心跳文件**为准，告警多为时序误报 |

## 重启后四验（全过才算完成）

```bash
bash scripts/restart_mirror.sh status        # ① 全绿：web ✅ feishu ✅ 主区 8902 ✅
curl -s http://127.0.0.1:8903/health | python3 -m json.tool | head -12
#   ② identity.workspace = /Users/yyj/Project/llm-first-loop-mirror、git_head = 当前 HEAD
curl -s http://127.0.0.1:8903/api/v1/sessions | head -c 400
#   ③ 抽查 session_id 在镜像 data/sessions/ 命中（防 DATA_DIR 残留串区）
python3 -c "import json; d=json.load(open('data/feishu_heartbeat.json')); print(d['state'], d['pid'])"
#   ④ 心跳 state=connected 且 pid = 新进程号
```

## 常见故障对照表

| 症状 | 根因 | 处置 |
|---|---|---|
| 日志「已启动→已停止」零错误 | shell 清理陪葬 | 用脚本重启（本技能§1） |
| 预检失败 `10014 app secret invalid` | 凭证错配对（残留）或凭证真失效 | 先 `curl POST open.feishu.cn/.../tenant_access_token/internal` 验证文件凭证：code=0 → 是环境残留（脚本已防御，说明你没走脚本）；code≠0 → 凭证真失效，上报用户 |
| `Errno 48 address already in use` | 端口被占 | 脚本会按端口先杀；手动场景 `lsof -tiTCP:8903 -sTCP:LISTEN` 找 pid 再 kill |
| 启动即 ImportError / TypeError | **半改工作区**（API 与引用方脱节） | 查 `git status`；已知垫片搜「运维垫片」注释；不要现场造 API，找运维/用户 |
| web 显示主区内容 | 环境残留 DATA_DIR / 主区代码 / 端口劫持 | `ps eww -o command= -p <pid> \| tr ' ' '\n' \| grep -E '^(PWD\|PYTHONPATH\|DATA_DIR)='` 三要素定身份，然后用脚本重启 |
| `port 无监听进程` 但服务明明在 | WEB_PORT 解析为空串 | 脚本已修（resolver 查询带 PYTHONPATH + 空值兜底）；看到此输出立即停手排查，勿继续 |

## 自重启特别说明

- **你的会话宿主就是 web 进程**：`restart_mirror.sh web` 或 `all` 会重启宿主，你的会话会断流——这是预期行为，脚本 nohup 机制保证服务起来后不依赖你的会话；断流前把结论写完。
- 只重启 `feishu` 不影响你的会话。
- 重启是**幂等**的：不确定状态时直接 `status` 查看，别猜。

## 一句话

**`restart_mirror.sh` 就是答案。所有"更聪明"的自创方式（setsid/launchctl/裸 python/cd+WEB_PORT）都已实证翻车。**
