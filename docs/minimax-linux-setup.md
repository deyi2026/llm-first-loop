# Linux 主机接入 MiniMax 开放平台（国内站）

> 适用对象：Linux 用户级安装（`bash scripts/install_linux.sh`，wheel 发行）或源码安装的 LFL。
> 事实核对时间：2026-11-06。端点、模型与限额以 MiniMax 官方文档为准（文末链接）；本文只记录本仓已在真实主机上跑通的做法。

## 1. 端点与模型

| 用途 | Base URL | LFL 协议 | 官方文档 |
|:---|:---|:---|:---|
| OpenAI 兼容 | `https://api.minimax.cn/v1` | `LLM_WIRE_PROTOCOL=openai`（默认） | https://platform.minimax.cn/docs/api-reference/text-openai-api |
| Anthropic 兼容 | `https://api.minimax.cn/anthropic`（请求落 `/v1/messages`） | `LLM_WIRE_PROTOCOL=anthropic` | https://platform.minimax.cn/docs/api-reference/text-anthropic-api |

Anthropic 兼容接口支持 `MiniMax-M3.1-Flash`、`MiniMax-M3`；其它模型请走标准 MiniMax 接口。

## 2. 配置

Linux 用户级安装的配置文件在 `~/.local/share/lfl/.env`（`lfl paths` 可查实际路径）：

~~~bash
LLM_BASE_URL=https://api.minimax.cn/v1
LLM_API_KEY=<开放平台 API Key；TokenPlan 会员在控制台「管理订阅 → API 密钥」取>
LLM_MODEL=MiniMax-M3.1-Flash
LLM_WIRE_PROTOCOL=openai
~~~

要点：

- **`LLM_MODEL` 写裸模型名**。写全限定 `minimax/MiniMax-M3.1-Flash` 时，运行时客户端发的仍是裸名（OpenAI 兼容端点不接受全限定形式），但 LFL 0.6.37 的 `lfl doctor --online` 会把全限定名原样发出，报 `model_not_found` 假阴性——配置本身是好的。上游已修：doctor 与客户端现在共用同一套 wire 名映射，且只有"已知 provider id"才剥前缀（模型名本身含 `/` 的写法不受影响）。
- **限额在控制台看**。官方速率限制：MiniMax-M3.1-Flash / M3 免费用户 RPM 20、TPM 1,000,000；充值用户 RPM 200、TPM 10,000,000。订阅（TokenPlan）档位与用量在「管理订阅」页。
- 改完配置后 CLI 直接生效；常驻服务（Web / 飞书）需重启进程。

## 3. 服务守护（systemd --user）

Linux 安装器不建 systemd 服务；手工拉起（`nohup`/`setsid`）的进程**没有崩溃自愈、没有开机自启**，且端口占用时新进程会静默退出。

推荐 `~/.config/systemd/user/lfl.service`（用户级，无需 sudo）：

~~~ini
[Unit]
Description=LFL (llm-first-loop) local web service
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=/home/<user>/.local/share/lfl
Environment=LFL_HOME=/home/<user>/.local/share/lfl
Environment=PATH=/home/<user>/.local/bin:/usr/local/bin:/usr/bin:/bin
Environment=PYTHONUNBUFFERED=1
ExecStart=/home/<user>/.local/share/lfl/releases/<VERSION>/venv/bin/lfl start
Restart=on-failure
RestartSec=5s
KillSignal=SIGTERM
TimeoutStopSec=20s

[Install]
WantedBy=default.target
~~~

启用与开机自启：

~~~bash
systemctl --user daemon-reload
systemctl --user enable --now lfl.service
loginctl enable-linger "$USER"   # 注销/重启后用户级单元仍被拉起
~~~

自愈验收（实测口径）：

~~~bash
systemctl --user show lfl.service -p MainPID -p NRestarts
kill -9 "$(systemctl --user show lfl.service -p MainPID --value)"
sleep 12 && systemctl --user show lfl.service -p NRestarts -p MainPID
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8903/health
~~~

`NRestarts` 递增且 `/health` 返回 200，即崩溃自愈生效。切换时先停掉旧的无守护进程，否则新单元会因端口占用启动失败。

## 4. 额度 / 限流巡检（可选）

只读扫描服务日志，把限流与配额命中计数落盘：

~~~bash
~/.local/share/lfl/scripts/quota_watch.sh 30min
# → ~/.local/share/lfl/data/quota_watch.json
#   {"checked_at":..., "window":"30min", "journal_lines":N,
#    "rate_limit_hits":N, "quota_hits":N, "error_lines":N}
~~~

配合 `~/.config/systemd/user/lfl-quota-watch.{service,timer}`（`OnUnitActiveSec=30min`）定时执行，命中数进 journald（tag `lfl-quota-watch`）。这是观测手段，不替代控制台的额度看板。

脚本与单元文件的完整内容（便于在其它主机复现）：

~~~bash
#!/usr/bin/env bash
# LFL MiniMax 额度/限流巡检：只读扫描 lfl.service 日志，不改业务状态。
set -uo pipefail
SINCE="${1:-30min}"
UNIT="lfl.service"
HOME_DIR="${LFL_HOME:-$HOME/.local/share/lfl}"
OUT="$HOME_DIR/data/quota_watch.json"
LOG="$(journalctl --user -u "$UNIT" --since "-$SINCE" --no-pager 2>/dev/null || true)"
lines=$(printf "%s\n" "$LOG" | grep -c "" || true)
rate=$(printf "%s\n" "$LOG" | grep -c -i -E "429|rate[ _-]?limit|限流|too many requests|quota exhausted" || true)
quota=$(printf "%s\n" "$LOG" | grep -c -i -E "quota|insufficient|配额|billing|balance" || true)
errs=$(printf "%s\n" "$LOG" | grep -c -i -E "llmhttperror|llmnetworkerror|traceback" || true)
ts=$(date -Iseconds)
mkdir -p "$(dirname "$OUT")"
printf "{\"checked_at\":\"%s\",\"window\":\"%s\",\"journal_lines\":%s,\"rate_limit_hits\":%s,\"quota_hits\":%s,\"error_lines\":%s}\n" "$ts" "$SINCE" "$lines" "$rate" "$quota" "$errs" > "$OUT"
logger -t lfl-quota-watch "window=$SINCE lines=$lines rate_limit=$rate quota=$quota errors=$errs" 2>/dev/null || true
cat "$OUT"
~~~

~~~ini
# ~/.config/systemd/user/lfl-quota-watch.service
[Unit]
Description=LFL MiniMax quota/rate-limit watch (oneshot)
After=lfl.service

[Service]
Type=oneshot
ExecStart=<HOME>/.local/share/lfl/scripts/quota_watch.sh 30min
~~~

~~~ini
# ~/.config/systemd/user/lfl-quota-watch.timer
[Unit]
Description=LFL MiniMax quota/rate-limit watch (periodic)

[Timer]
OnBootSec=5min
OnUnitActiveSec=30min
AccuracySec=1min
Unit=lfl-quota-watch.service

[Install]
WantedBy=timers.target
~~~

启用：`systemctl --user enable --now lfl-quota-watch.timer`。

## 5. wheel 安装的资产路径坑（0.6.37）

**现象**：wheel 安装的主机上，`lfl doctor` 报「规则索引 0 条、方法 0 条、技能 0 个」，会话实际在裸跑通用提示。

**原因**：wheel 安装的代码根（`_CODE_ROOT`）解析到解释器库目录，其下没有 `docs/`、`skills/`、`methods/`；随包资产在 site-packages 的 `llm_loop/_bundled/` 里。

**临时绕过**：把 `llm_loop/_bundled/{docs,skills,methods}` 建软链到 `~/.local/share/lfl/assets/`，并在 `.env` 显式写 `DOCS_DIR` / `SKILLS_DIR` / `METHOD_SEED_DIR`。

**上游修复**：`runtime/paths.py` 增加 package bundle 回退（显式 env > 代码根 > 随包 bundle），并新增 `docs_source` / `skills_source` / `method_seed_source` 标明来源；升级到含该修复的版本后，软链与 `.env` 里的三项路径都不再需要。

## 6. 上线核验清单

~~~bash
lfl doctor --online                 # 在线体检：应报 ok（模型名不再假报 model_not_found）
lfl paths                            # 确认 DOCS_DIR / SKILLS_DIR / METHOD_SEED_DIR 指向存在的目录
systemctl --user status lfl.service  # active (running) + MainPID
curl -s http://127.0.0.1:8903/health # 200
~~~

## 参考

- MiniMax Anthropic 兼容接口：https://platform.minimax.cn/docs/api-reference/text-anthropic-api
- MiniMax OpenAI 兼容接口：https://platform.minimax.cn/docs/api-reference/text-openai-api
- MiniMax 速率限制：https://platform.minimax.cn/docs/guides/rate-limits
- LFL 配置参考：`docs/configuration.md`；安装与发行：`docs/installation.md`
