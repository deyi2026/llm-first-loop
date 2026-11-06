# merge gate 回执 · GOAL-20261106-a6fde1bf（文档 lane v2）

- 审查者：独立合并审查子代理 `subagent_b6e998513956`（GLM-5.3，只读）
- 被审分支：`docs/minimax-linux-setup-v2`（head `ffd130b21226fcf82ecf78117a223cd10322504c`）
- 基线：`main` = `3e7ff86ef26ce8243dce174a24cb44f4d62eaec0`（merge-base == main）

## 回执 JSON

```json
{
  "gate": "merge",
  "reviewer": "subagent_b6e998513956",
  "verdict": "PASS",
  "goal_id": "GOAL-20261106-a6fde1bf",
  "branch": "docs/minimax-linux-setup-v2",
  "based_on_main": true,
  "commits": ["ffd130b21226fcf82ecf78117a223cd10322504c"],
  "merge_mode": "ff",
  "conflicts_resolved": [],
  "focused_gates": [
    "merge-review-gate PASS（六条清单全通；敏感扫描零命中）",
    "仓内一致性复核：install_linux.sh 无 pip.conf/索引/UV_ 配置（L636-640 裸 uv pip install）→ §6 断言成立",
    "仓内一致性复核：install_linux.sh 无 assets/_bundled/ln -s 逻辑 → 软链需手工重指向的断言成立",
    "路径与安装布局一致：releases/LFL-<ver>/venv、.LFL-active-version、--python 3.13",
    "纯文档：无测试义务；敏感扫描（内网地址/密钥样式/凭据赋值）零命中"
  ],
  "main_sha_after": "ffd130b21226fcf82ecf78117a223cd10322504c",
  "branch_disposition": "deleted：已 ff 入 main，reflog 可追溯",
  "verify_receipt_id": "lane-dc5ec3ae:3e7ff86e"
}
```

## 审查结论（原文要点）

单提交 `ffd130b2`，文档 166→205 行（+42/-3，净 +39），五要点全部落盘：L55/L83 `Restart=always` 与实测注、L50-52 ExecStart 版本 pin 与 sed 回滚警示、L156-163 assets 重指向、L168-186 §6 uv/pip 双索引与可达性验证、L192-196 §7 补 doctor 注/Restart/assets。分支卫生：worktree 干净、仅动 1 个文件；基线新鲜（merge-base == main），ff 可行；章节 1-7 与参考连续，无 TODO 残留。

## 本轮修订的由来（主机实测）

1. `Restart=on-failure` 不覆盖**干净退出**：uvicorn 优雅关闭超时后以 exit 0 结束 → systemd 判 success → 不重启 → `/health` 000、服务无声消失。单元改 `Restart=always`。
2. `ExecStart` 必须按版本目录写死：宿主升级流程第 3 步用 sed 改写版本路径并 grep 校验，手改成 `~/.local/bin/lfl` 会触发回滚。
3. `assets` 软链不随版本切换更新：安装器无维护逻辑，升级后需手工重指向活动版本的 `_bundled`。
4. 主机出网：uv 不读 `~/.pip/pip.conf`；镜像不可达时 `uv pip install` 无限等待（CPU≈0、site-packages 为空），会把升级流程拖死并造成服务长时间中断（升级流程在装之前已先 stop 服务）。

## 合并执行留痕

- 合并前 main：`3e7ff86ef26ce8243dce174a24cb44f4d62eaec0`
- 合并方式：`git merge --ff-only docs/minimax-linux-setup-v2`（1 file changed, 42 insertions(+), 3 deletions(-)）
- 合并后 main：`ffd130b21226fcf82ecf78117a223cd10322504c`
- 合并后冒烟：`git show main:docs/minimax-linux-setup.md | wc -l` → **205**；L55 = `Restart=always`；L168 = `## 6. 主机出网与包索引（uv 与 pip 是两套）`
