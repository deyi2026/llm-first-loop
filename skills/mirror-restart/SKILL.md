---
name: mirror-restart
description: 镜像区常驻服务（web :8903 + 飞书桥 + Learning Plane worker）重启/启动的标准操作——先选通道（计划性=service_control 受理制；紧急/自愈=脚本），六大禁忌、四步验证、故障对照表。需要重启/启动/修复镜像服务时先加载本技能。
---
# 镜像服务重启（标准操作）

## 第零步：选通道（2026-09-24 起双通道并存）

| 场景 | 通道 | 操作 |
|---|---|---|
| **代码变更后的计划重启**（提交了新代码/版本要生效） | 权威通道（service_control） | `publish`（clean tree + git_head + dist hash 绑定）→ `restart` 受理 → 终态核对 |
| 崩溃恢复/进程挂死/无守护拉起/抢回端口 | 脚本/守护（本 skill 主体） | 下面的 `restart_mirror.sh`；guard launchd 守护已恢复常驻（v0.6.20）会自动拉起 |

**权威通道纪律**：受理回执 ≠ 完成——restart 异步两阶段（先等发起会话结束、再等目标空闲），终态三入口核对（`service_control status` / `event_stream(query=service_action_terminal)` / `data/restart-receipt.log`）；failed 终态须 `verify_acknowledge` 销账。详见 web-self-restart-triage §Step 4。

**三服务通道矩阵**（权威/脚本 target 同名，验证探针各不同）：

| 服务 | 权威/脚本 target | 就绪验证探针 | 特殊纪律 |
|---|---|---|---|
| web | `web` | 端口 `lsof -tiTCP:8903` + `/health`（401 也是响应） | 重启会断宿主会话（权威通道在会话结束后执行） |
| 飞书桥 | `feishu` | 心跳 `data/feishu_heartbeat.json`：`state=connected` 且 pid=新进程（WS 握手波动 15~55s 属正常） | 停止判定源=心跳 pid；不影响会话 |
| Learning Plane | `learning` | manifest `data/runtime/runtime_manifest.learning.json`：`service=learning` 且 pid=新进程（无端口/无心跳，30s 就绪窗） | 权威通道有空闲门（gate：等在飞任务排空）；不影响会话 |

## 紧急/脚本方式

```bash
cd /Users/yyj/Project/llm-first-loop-mirror
bash scripts/restart_mirror.sh status   # 先看现状
bash scripts/restart_mirror.sh all      # 全量重启（web + 飞书）
bash scripts/restart_mirror.sh web      # 只 web
bash scripts/restart_mirror.sh feishu   # 只飞书
bash scripts/restart_mirror.sh learning # 只 Learning Plane worker
```

**紧急场景用这个脚本**——包括：崩溃恢复、代用户强制重启、抢回端口、守护失效时的手动拉起。不要自创启动方式，不要"这次很简单就直接跑 python"。**计划性重启不要用脚本**（绕过部署绑定，旧代码/半改工作区可能被拉起）。

## 为什么必须用脚本（内置六层防御，每层都是实证事故）

1. **按端口杀**（`lsof -tiTCP:8903`）——主/镜像进程命令行几乎相同，模式匹配必误杀
2. **PYTHONPATH=镜像 src 显式注入**——共享 venv 的 editable .pth 属旧主区（协议 §3），不注入就跑旧主区代码
3. **跨区残留清理**（PYTHONPATH / LFL_DATA_DIR / DATA_DIR / DSH_HOME / FEISHU_APP_ID+SECRET）——环境残留是历次串区事故根源；注意 `DATA_DIR` 与 `LFL_DATA_DIR` 是**两个不同的键、两套消费者**，清理必须成对
4. **凭证配套加载**——防"旧主区 app_id + 镜像 secret"错配对（预检 10014）
5. **nohup 脱离会话进程树**——AI 的工具 shell 退出时不会清理它，服务不陪葬
6. **启动后自动验证**——web health 轮询 + 飞书心跳轮询（90s 窗口，连上即刻返回）

## 六大禁忌（全部实证过）

| # | 禁忌 | 后果 |
|---|---|---|
| 1 | 在自己 shell 里直接 `python -m llm_loop.feishu` / `llm_loop.web`（前台或裸 `&`） | **shell 退出进程陪葬**——日志特征：「已启动→已停止」中间零错误（2026-08-30 实证） |
| 2 | `launchctl submit` 执行重启命令 | launchd **无限重拉**，服务循环重启 100+ 次（2026-08-28 实证） |
| 3 | `pkill -f "llm_loop.web"` 之类模式杀 | **旧主区服务陪葬**（两区命令行无法区分） |
| 4 | `cd 旧主区 && WEB_PORT=8903 nohup …` 跨区起服务 | **端口劫持**：镜像 web 显示旧主区内容（2026-08-29 实证） |
| 5 | 改完代码/.env 不重启就宣称生效 | 运行进程仍是旧代码旧配置（提交≠生效，重启才生效） |
| 6 | 见脚本告警"⚠️ 未见 connected"就反复重启 | WS 握手正常波动 15~55s，以**心跳文件**为准，告警多为时序误报 |

## 重启后五验（全过才算完成）

```bash
bash scripts/restart_mirror.sh status        # ① 全绿：web ✅ feishu ✅ 旧主区 8902 ✅
curl -s http://127.0.0.1:8903/health | python3 -m json.tool | head -12
#   ② identity.workspace = /Users/yyj/Project/llm-first-loop-mirror、git_head = 当前 HEAD
curl -s http://127.0.0.1:8903/api/v1/sessions | head -c 400
#   ③ 抽查 session_id 在镜像 data/sessions/ 命中（防 DATA_DIR 残留串区）
python3 -c "import json; d=json.load(open('data/feishu_heartbeat.json')); print(d['state'], d['pid'])"
#   ④ 心跳 state=connected 且 pid = 新进程号
python3 -c "import json; d=json.load(open('data/runtime/runtime_manifest.learning.json')); print(d['service'], d['pid'])" && tail -3 data/learning.log
#   ⑤ learning manifest service=learning 且 pid=新进程号；learning.log 无 ERROR
```

## 常见故障对照表

| 症状 | 根因 | 处置 |
|---|---|---|
| 日志「已启动→已停止」零错误 | shell 清理陪葬 | 用脚本重启（本技能§1） |
| 预检失败 `10014 app secret invalid` | 凭证错配对（残留）或凭证真失效 | 先 `curl POST open.feishu.cn/.../tenant_access_token/internal` 验证文件凭证：code=0 → 是环境残留（脚本已防御，说明你没走脚本）；code≠0 → 凭证真失效，上报用户 |
| `Errno 48 address already in use` | 端口被占 | 脚本会按端口先杀；手动场景 `lsof -tiTCP:8903 -sTCP:LISTEN` 找 pid 再 kill |
| 启动即 ImportError / TypeError | **半改工作区**（API 与引用方脱节） | 查 `git status`；已知垫片搜「运维垫片」注释；不要现场造 API，找运维/用户 |
| web 显示旧主区内容 | 环境残留 DATA_DIR / 旧主区代码 / 端口劫持 | `ps eww -o command= -p <pid> \| tr ' ' '\n' \| grep -E '^(PWD\|PYTHONPATH\|DATA_DIR)='` 三要素定身份，然后用脚本重启 |
| `port 无监听进程` 但服务明明在 | WEB_PORT 解析为空串 | 脚本已修（resolver 查询带 PYTHONPATH + 空值兜底）；看到此输出立即停手排查，勿继续 |

## 自重启特别说明

- **权威通道下（默认）**：`publish` → `restart` 受理后**不会**立刻断你的会话——动作先等 requester 会话结束再执行（两阶段）。把结论写完、回复用户即可；断流发生在会话之后，是设计行为。
- **脚本通道下**：你的会话宿主就是 web 进程，`restart_mirror.sh web`/`all` 会立刻重启宿主、会话断流——这是预期行为，nohup 机制保证服务起来后不依赖你的会话；断流前把结论写完。
- 只重启 `feishu` 不影响你的会话。
- 重启是**幂等**的：不确定状态时直接 `status` 查看，别猜。
- **改完代码的重启顺序**（提交→生效闭环）：commit → （动过 webui 则 `npm run build`）→ `publish` → `restart` 受理 → 会话结束执行 → 终态核对。**版本三件套**：CHANGELOG 条目 + pyproject bump + git tag 同次提交，缺任一项横幅显示 `-dev` 后缀（2026-09-24 实证：只写 CHANGELOG 不 bump/tag，横幅停在 v0.6.15-dev.253）。

## 一句话

**计划重启走 service_control（publish→restart→核对），紧急恢复 `restart_mirror.sh` 是答案。所有"更聪明"的自创方式（setsid/launchctl/裸 python/cd+WEB_PORT）都已实证翻车。**
