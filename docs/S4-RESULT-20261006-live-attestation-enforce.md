# S4 结果：live attestation enforce 首次全链实测（2026-10-06）

部署：web generation 178（git decb4d906，PID 63085，00:54:17 起，matches_desired=true）。
配置：`LFL_BROWSER_PERCEPTION_CDP_URL=http://127.0.0.1:9229`，`LFL_BROWSER_PROFILE_CLASS=`（dedicated 默认档），`LFL_BROWSER_ATTESTATION_MODE=enforce`。

## 实测结果

1. **首次绑定 attestation 落盘**：`data/browser_perception/attestation.json`
   verdict=dedicated，argv_sha256=681e1a76661ca54e…（与 S0 预核一致），checked_at 2026-10-06T00:57:01+08:00。
2. **感知/执行同宿主一致性**（bsnap-475 链）：
   - perceive snapshot（00:57:01）与 operate 目标解析 match_count=1（具名 link "LFL Middleware Lab 0.2"）；
   - 回执 `scope_relation=same`（同 scope b116fe0b660802e414ac710f），操作后 diff 已捕获；
   - 滚动效果本身为空（changed:0，容器无滚动量，receipt effect=failed）——不影响绑定结论。
   - 附带确认：错误 target（document/"chatgpt.com"、document/"ChatGPT"）match_count=0 即刻 halted，无模糊重绑。
3. **负向复核（生产代码 attest_debug_url + BindingPolicy.deny_real(enforce)）**：
   - 探针 9231（user-data-dir=默认树内、路径含空格）：ps→shlex 截断 ⇒ 解析失败 fail-closed ⇒ verdict=real ⇒ enforce 拒绑；
   - 探针 9232（无空格 symlink → realpath 落默认树内）：verdict=real（落默认/授权树内）⇒ enforce 拒绑；
   - 阳性对照 9229（真实态）：verdict=dedicated ⇒ 放行。
   探针进程与目录已全部清理，默认树无残留。
4. **终态**：.env 保持 :9229；真实态 Chrome（PID 45369，chatgpt-web-chrome-profile）未受影响。

## 新发现（非阻塞，fail-closed 方向）→ **已于同日修复**

`ps -ww -o command=` + `shlex.split` 对含空格的 `--user-data-dir=V` 值在空格处截断 ⇒ 解析失败 ⇒ fail-closed real。
安全方向正确（宁可误拒不误放），但**dedicated profile 路径含空格时 enforce 下不可绑定**。

**修复（2026-10-06）**：argv 采集改走平台原生 NUL 分隔源——macOS `sysctl(KERN_PROCARGS2)`
（原文误记"该平台无 NUL 分隔 argv 可读"，实际 `ps` 自身即读该源）、Linux `/proc/<pid>/cmdline`；
`ps`+`shlex` 降为兜底（原生源失败时 warning + 回落，fail-closed 契约不变）。
代码 `src/llm_loop/browser/attestation.py`（`_parse_proc_cmdline`/`_parse_procargs2`/`_native_argv`/`_pid_argv`）。

修复后探针复核（生产代码 `attest_debug_url` + `BindingPolicy.deny_real(enforce)`，同日）：
- **P1** 空格 dedicated profile（`/tmp/attest fix dir/profile with space`）：verdict=dedicated ⇒ 放行（修复目标，原误拒）；
- **P2** 无空格 dedicated profile：verdict=dedicated ⇒ 放行（回归无退化）；
- **N1b** 活监听 + 含空格 profile 位于授权树内（PATHS 附加树）：verdict=real ⇒ 拒绑（安全方向未松动）；
- **9229 生产实例**只读复核：verdict=dedicated（argv[0] 二进制路径含空格现为单 token，argv_sha256 相应变化，仅审计指纹用途）。
单测：`tests/unit/test_browser_attestation_v01.py` §6（解析器/兜底/端到端/真进程冒烟）28 passed。

## 唤醒链说明

本轮验证原计划经 schedule wake 在重启后自动续跑；实测 wake 未触发（wake 属同会话一次性续跑，run 终止即失效，重启等待恰好跨过该边界）。实际由用户手动续跑完成。后续跨重启的自动验证不应依赖 schedule wake。
