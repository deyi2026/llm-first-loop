# 凭据清单报告：.env.bak-* 备份文件（2026-09-09）

**范围**：仓库根目录 22 个 `.env.bak-*` 备份文件（2026-08-17 → 2026-09-04）。
**方法**：只读静态扫描；仅提取变量**名**与文件元数据（mtime/size/变量数），
本报告**不含任何变量值**。机密类判定 = 变量名含
key/token/secret/password/cookie/appid/dsn/credential/auth。

## 1. 总体结论

- **Git 暴露面 = 0**：全部 22 个备份均未被 git 跟踪（`git ls-files` 仅命中
  `.env.example`），权限均为 `-rw-------`（600，仅 owner 可读）。
- **`.env.example`（git 跟踪、公开模板）无泄漏**：LLM_API_KEY 为 6 字符占位
  （与 live 35 字符真实值不等）；EMBEDDING_API_KEY 为 6 字符无数字占位
  （live 同名值亦为同一占位符——live 本身即占位，非泄漏）。
- 暴露等级：**本地磁盘冗余副本**，风险=误打包/误提交/越权读盘，非已发生泄漏。

## 2. 逐文件清单（22 个）

| 文件 | mtime | 大小B | 变量数 | 机密类变量 |
|---|---|---|---|---|
| .env.bak-20260817-150456 | 08-17 15:04 | 9197 | 58 | DEEPSEEK, EMBEDDING, FEISHU_APP_SECRET, KIMI, LLM, MINIMAX (_API_KEY) |
| .env.bak-20260817-224529 | 08-17 22:45 | 9753 | 60 | 同上 |
| .env.bak-20260819-153445 | 08-19 15:34 | 10362 | 58 | 上 + XAI |
| .env.bak-20260819-2357-current-400K | 08-19 22:35 | 10721 | 59 | 上 + XAI |
| .env.bak-20260820-053209-effort-high | 08-20 03:43 | 10449 | 59 | 上 + XAI |
| .env.bak-20260820-094652-tail-1 | 08-20 05:36 | 10448 | 59 | 上 + XAI |
| .env.bak-20260820-100748-tail-1-keep | 08-20 09:46 | 10402 | 59 | 上 + XAI |
| .env.bak-20260820190337-grokfix | 08-20 19:03 | 10605 | 60 | 上 + XAI + **ANTHROPIC_AUTH_TOKEN** |
| .env.bak-twofold-20260819-223458 | 08-19 22:34 | 10548 | 59 | 基础6 + XAI |
| .env.bak-20260821-400k | 08-21 07:44 | 10537 | 59 | 基础6（XAI 移除） |
| .env.bak-reasoning-20260821101036 | 08-21 10:10 | 10530 | 59 | 基础6 |
| .env.bak-fs-20260818-015322 | 08-18 01:53 | 9520 | 52 | 基础6 |
| .env.bak-feishu-20260822144120 | 08-22 14:41 | 11167 | 63 | 基础6 + LMS |
| .env.bak-mapretrieve-20260822210550 | 08-22 21:05 | 11778 | 67 | 基础6 + LMS |
| .env.bak-precheck-20260822230704 | 08-22 23:07 | 11916 | 67 | 基础6 + LMS |
| .env.bak-owner | 08-23 08:17 | 12204 | 69 | 基础6 + LMS |
| .env.bak-20260823-owner-fix | 08-23 22:34 | 12204 | 69 | 基础6 + LMS |
| .env.bak-20260824-165100-budget400k-ratio05 | 08-24 16:51 | 12206 | 68 | 基础6 + LMS |
| .env.bak-20260825-094408-key-reset | 08-25 09:44 | 12431 | 69 | 基础6 + LMS |
| .env.bak-20260825-094422-key-retry | 08-25 09:44 | 12361 | 69 | 基础6 + LMS |
| .env.bak-20260825-094630-mcp-fix | 08-25 09:46 | 12431 | 69 | 基础6 + LMS |
| .env.bak-20260904-150052-tunnel-stop | 09-04 15:00 | 14143 | 74 | 基础6 + LMS + COGNILOCAL + GLM + MXNOOK |

（基础6 = DEEPSEEK/EMBEDDING/KIMI/LLM/MINIMAX _API_KEY + FEISHU_APP_SECRET）

## 3. 机密类变量并集与时间线

12 个机密类变量在备份中出现。关键时间线：

- **XAI_API_KEY**：仅 08-19 → 08-20 窗口（8 个文件），08-21 起移除。
- **ANTHROPIC_AUTH_TOKEN**：仅 `grokfix` 一处（08-20），随后移除。
- **LMS_API_KEY**：08-22 引入，此后常驻。
- **COGNILOCAL / GLM / MXNOOK _API_KEY**：09-04 引入（最新备份）。
- DEEPSEEK / EMBEDDING / FEISHU_APP_SECRET / KIMI / LLM / MINIMAX：全程常驻。

## 4. 与 live `.env` 的交叉核对

live 含 11 个 provider 机密 + `WEB_LOGIN_PASSWORD_HASH`（备份中未见，为后期
新增），且 `FEISHU_APP_SECRET` 在 live 中**重复出现两次**（其一为死条目，
建议合并时留意）。备份与 live 的并集轮换评估：

- **已从 live 移除但备份仍留值 → 轮换/吊销候选**（若 provider 侧仍有效）：
  `XAI_API_KEY`、`ANTHROPIC_AUTH_TOKEN`。
- **live 仍在用 → 无需因本清单轮换**（暴露仅限本地 600 权限副本）；
  是否轮换取决于用户对"历史副本含旧值（如 08-25 key-reset 前的旧 key）"
  的态度——**key-reset/retry 命名暗示 08-25 存在换 key 事件，旧值或已失效**。

## 5. 处置建议（待用户裁决，本报告不执行任何清除）

1. **推荐**：22 个备份压缩为单一加密归档（如 age/7z 加密）移出仓库树，
   原地删除明文副本；保留最近 1 个如需快速回滚。
2. 若确认 08-25 前旧 key 已在 provider 侧吊销，可仅删除 08-17 → 08-24 的
   16 个文件，保留 08-25 之后 6 个。
3. 轮换 `XAI_API_KEY`、`ANTHROPIC_AUTH_TOKEN`（若账户仍有效）。
4. live `.env` 清理 `FEISHU_APP_SECRET` 重复条目。

---
*生成方式：只读扫描（stat + grep 变量名），未读取/输出任何变量值。*

## 6. 处置执行记录（2026-09-09，用户授权「执行ABCD」项 b）

用户放行推荐方案（加密归档移出 + 明文删除）。执行时发现**报告清单与磁盘
漂移**，如实记录：

- **磁盘实际存在 16 个**（非 22）：归档仓库 `llm-first-loop-archived-20260908`
  根 15 + mirror 根 1。已全盘清场搜索（backups/、ops-backups/、lfl-* 兄弟
  目录、~/.Trash、/private/tmp），无其他藏匿点。
- 正文 22 个清单中 **12 个已不在磁盘**（20260821-400k、feishu/mapretrieve/
  precheck/owner 系列、budget400k、key-reset/retry、mcp-fix、tunnel-stop、
  reasoning-20260821101036 等，即 08-21~09-04 大半段），推测在 09-08 主仓
  归档迁移前后已被清理；**磁盘另有 6 个未列入正文**：grok-removed-20260820194446、
  20260825-100321、cachehit-20260821130117、reasoning-20260821101546
  （正文 101036 的近似变体）、点号命名的 20260820183420 与 mirror 的
  20260820182933（三者内容相同，sha256=d4fffc4c…）。grokfix 时间戳亦有
  出入（正文 190337 vs 磁盘 191008，大小一致）。
- **处置以磁盘现状为准：16 个全部归档后删除**，不放过任何现存明文；
  12 个"清单有盘上无"文件无需处置（本就不存在）。

执行与验证：

1. 16 条 sha256 基线 → 打包（保留来源前缀 archived/、mirror/，附 ORIGIN.txt
   与清单）→ `openssl enc -aes-256-cbc -pbkdf2 -iter 200000` 加密。
2. 解密复核：16/16 hash 与原件**全部一致**，之后才删除明文。
3. 归档位置：`~/.lfl-secure-archive/envbak-20260909.tar.gz.enc`
   （目录 700 / 文件 600）；同目录 `MANIFEST-sha256.txt`（仅名称+hash）。
4. 口令：随机 32B；Keychain 写入失败（无 GUI 会话）降级为同目录
   `PASSPHRASE.txt`（600）。建议用户登录后手动移入 Keychain 并删除该文件。
5. 删除后复查：两仓根目录仅余 `.env` 与 `.env.example`；两仓 git status
   零变化（备份本就 untracked/ignored）。

未执行（超出本项授权，维持待裁决）：XAI/ANTHROPIC 轮换吊销、live `.env`
FEISHU_APP_SECRET 重复条目清理。

---
*附录 6 为执行记录；全程未输出任何变量值或口令。*
