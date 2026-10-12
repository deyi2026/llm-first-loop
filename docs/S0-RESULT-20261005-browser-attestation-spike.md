# S0 结果：attestation 机制 spike（2026-10-05/06）

> 关联：`DESIGN-20261005-browser-channel-hardening.md` v4 §5 S0（v4-G2 前置门）
> 结论：**选 ② host 侧进程 attestation（lsof→PID→ps argv）**。S3 解锁。
> 原始数据：`data/runtime/s0-attestation-results/{no-flag,flag}-{headed,headless}.json`（四态各一次独立 Chrome 实例，一次性隔离 profile，about:blank）
> 探针：`scripts/spike/s0_browser_attestation_probe.py`（可复跑）

## 1. 实测矩阵（Chrome 154.0.8037.93 稳定版，macOS 26.5.1）

| 组合 | `Browser.getBrowserCommandLine`（browser 级 ws 短连） | `navigator.webdriver`（page ws） | host 侧 lsof→PID→ps -ww |
|---|---|---|---|
| 无 flag / headed | **ServerError** `code=-32000` "Command line not returned because --enable-automation not set."（8.5ms） | false | ✓ 完整 argv 含 `--user-data-dir`，总 40.4ms |
| **有 flag** / headed | ✓ 成功，返回完整 arguments（9.4ms） | **true** | ✓ 总 29.1ms |
| 无 flag / headless | **ServerError** 同上（5.5ms） | false | ✓ 总 21.8ms |
| **有 flag** / headless | ✓ 成功（5.0ms） | **true** | ✓ 总 21.0ms |

关键事实：

1. **门控在稳定版 Chrome 154 上成立**，与 Chromium 主干 `browser_handler.cc:676-695` 源码一致——v4-G2 的阻断级担忧在本机当前版本实测坐实：照 v3 直上 getBrowserCommandLine 方案，所有不带 flag 的合法 dedicated 全部拿不到命令行。
2. **副作用面实测**：加 `--enable-automation` ⇒ 所有页面 `navigator.webdriver=true`（2/2 组合）。其余已知副作用（headed 下 "Chrome is being controlled..." infobar）为 Chromium 文档化行为，CDP 不可编程验证，未实测；对真实站点的反自动化检测面 = webdriver=true 这一标准 bot 信号，spike 未对真实站点测试（不预设结论，但风险方向明确为负）。
3. **host 侧路径四态全绿**：`lsof -Fp -iTCP:<port> -sTCP:LISTEN` 恰好返回一个监听 PID（= Chrome 主进程），`ps -ww -o command=` 返回未截断完整 argv（含 `--user-data-dir` 与启动 flag 全集），总成本 21-40ms，一次性，不进热路径。
4. 附带核验：`/json/version` 返回 **dict**（F16b 的 dict helper 需求坐实）；browser 级 `webSocketDebuggerUrl` 的 UUID 段每次浏览器进程实例不同（S3a binding 用字段有效）。

## 2. 结论：选 ②，理由

- **零页面环境副作用**：dedicated profile 不加 `--enable-automation` ⇒ `navigator.webdriver` 保持 false ⇒ R1 核心场景（专用 profile 内显式登录后浏览 Gmail 等真实站点）不引入反自动化信号。选 ① 则每个 dedicated 会话都带 webdriver=true，直接伤害 R1 主用例。
- **对三类浏览器来源统一**：本 launch 脚本起的、用户自己起的主力 Chrome、harness/qualification 直连起的——argv 是同一真理源，判定器不需要浏览器"配合"。
- **与威胁模型解耦更彻底**（v4 §4.3）：不依赖浏览器自报；伪造面从"控制浏览器进程"上移到"控制宿主 lsof/ps 调用路径"，后者等价于已控制本进程，无增量暴露。
- **向 S5b（pipe）平滑演化**：pipe 模式下无 TCP 端口 ⇒ lsof 不可用，但那时 Chrome 由 host 进程自己 spawn，**spawn 时记录 argv 即 attestation**（更强制、更早）；判定函数（argv→verdict）两代共用，只有取 argv 的通道换代。
- 成本 21-40ms 一次性，在 §4.3 预算内。

①（加 flag）与 ③（其他机制）否决记录：① 的机械可行性已证明（flag 态 2/2 成功）但副作用面不可接受（上表第 2 行）；③ 无增量——② 已覆盖全部场景且最简。

## 3. 给 S3b 的实现约束（本 spike 产生的新增事实）

1. **监听 PID 唯一性策略**：四态实测均恰好 1 个监听 PID；实现时 `lsof` 返回 0 个或 >1 个 ⇒ **fail-closed 判 real**（不取"第一个"）。
2. **argv 解析**：macOS 用 `ps -ww -o command=`（防截断）；Linux 优先 `/proc/<pid>/cmdline`（实现留接口，本仓目标平台 macOS）。
3. **ps 输出含空格路径**：本机 Chrome 二进制路径含空格，argv 切分不能简单 `split()` 判首参——判定器只匹配 `--user-data-dir`（`=` 值形态）与分隔形态两种 token 形态（v4 §4.3 已列，此处实证提醒）。
4. **跨用户边界**：`ps` 读他用户进程 argv 在默认 macOS 配置可能受限——单用户本机场景成立，多用户部署属范围外（记入 S3b 代码注释即可）。
5. attestation 源记录字段：`argv_sha256` 应对 **host 侧 ps argv**（而非浏览器自报）计算；`checked_at` 仅审计。

## 4. 状态

- S3（S3a/S3b）**解锁**。
- v4 §4.1 launch 脚本设计不变（不加 `--enable-automation`）。
- 设计文档 §4.3/§5 S0 行已同步本结论。
