# F18：harness Chrome argv 盘点（2026-10-06 实测）

> 关联：`DESIGN-20261005-browser-channel-hardening.md` §5 S1（F18）、§8-F17
> 结论先行：**26/26 harness 目录全部 attach-only，零自启 Chrome**；v2"四套"口径不实；现网 `.env` 指向的 `:45918` 挂载实例**已死**（无监听进程）；所有会为本仓 harness 供靶的启动路径 argv 均带 `--user-data-dir` ⇒ attestation 全判 **dedicated**，与 S5"全绿"期望无冲突。

## 1. 扫描口径与结果

`evals/browser_smc_*/`（26 目录，v2 文档记 25，实测 26）逐目录扫描 `*.py`/`*.sh`：

| 探测项 | 命中数 |
|---|---|
| `remote-debugging-port` / Chrome Popen 类启动代码 | **0/26** |
| `user-data-dir` | 0/26 |
| `mock-keychain` | 0/26 |

harness 全部通过 `.env` 的 `LFL_BROWSER_PERCEPTION_CDP_URL` attach 既有实例（FC2-C 类 `tool_execution: False` 的甚至不执行 browser 工具）。**没有任何 harness 自己决定 Chrome argv。**

## 2. 真正决定 argv 的三个启动路径（供靶方）

| 启动路径 | argv 带 `--user-data-dir`？ | attestation 预判 | 状态 |
|---|---|---|---|
| `scripts/qualification/smc_browser_live_navigation.py:175-192` | ✓（`:188`）+ mock-keychain/basic | dedicated | 存量，不动 |
| `scripts/launch_browser_profile.sh`（S1 新增） | ✓（固定参数） | dedicated | 本日落档 |
| 用户手工起的主力 Chrome | ✗（默认树） | real | 需 allow-real policy（§4.2），预期行为 |

## 3. 现网挂载实例实测（F17 核心）

`lsof -nP -iTCP:45918 -sTCP:LISTEN` → **无监听进程**。2026-09-18 挂载的那台 Chrome 已退出，`.env` 的 CDP_URL 目前指向死端点（感知工具绑定时才会失败暴露）。修正 F17 预期：

- "shadow soak 观察现网活跃挂载"的对象**当前不存在**；
- S3b shadow 档的对象改为：**下一次**通过 launch 脚本/qualification 拉起的实例（argv 必带 user-data-dir，预期 verdict=dedicated）；
- `.env` TARGET_ID 已于本日 S1 置空（恢复自动绑定容忍度），下次拉起后自动重绑，无需改配置。

## 4. 对 S5 回归期望的影响

无冲突：harness 全绿所需的判定 = 全部供靶 Chrome 判 dedicated ⇒ 由 §2 三路径保证（qual 脚本 + 新 launch 脚本都带 user-data-dir；主力 Chrome 本来就该判 real 且不在 harness 全绿范围内）。v4 §5 S5 无需因 F18 调整期望，仅引用本文档为依据。
