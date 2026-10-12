# smx — 语义 shell 执行器（R1 PoC）

对应设计：`docs/DESIGN-20260911-semantic-manipulation-framework.md`
验证计划：`docs/tasks/VALIDATE-20260911-smx-poc.md`

## 定位

把「裸 shell 回执只有退出码+输出」升级为语义回执：**diff + 退出码链 + 落盘可回验**。
程序只做确定性采集（stat 快照、机械比对、轮询谓词），不做语义解释（P3/P4）。
smx 本体只读文件元数据与本地端口连通性；命令执行经调用方 shell 通道，安全边界完全继承该通道。

## 用法

```bash
python3 tools/smx/smx.py exec 'cmd' [--root DIR] [--watch PATH ...] [--depth 2] [--budget 5000] [--timeout S] [--json]
python3 tools/smx/smx.py bg   'cmd' ...        # 后台启动；diff 延迟到 collect
python3 tools/smx/smx.py collect RUN_ID        # 收尾：时间窗 diff + 退出码链
python3 tools/smx/smx.py wait (--file-exists P|--file-gone P|--file-contains P T|--port-open N) [--timeout S] [--interval S]
python3 tools/smx/smx.py show RUN_ID           # 重放已存回执
```

2026-09-12 生产迭代（dogfood 反馈，实测 7/7 冒烟 + selftest 回归）：

```bash
# --script FILE|'-'：exec/bg 命令改从文件/stdin 读——文本直达内层 bash，不经外层 shell 展开
printf 'echo "dollar0=$0"' | python3 tools/smx/smx.py exec --script -   # $0=bash，不再被外层吃掉
# --inline N：exec/collect/show 的 stdout ≤N 行且 ≤64KiB 时终端内联（默认 0=关；纯呈现层，receipt schema 不变）
python3 tools/smx/smx.py exec 'git log --oneline -5' --inline 5          # 免 exec→read_file 二跳
```

## 回执要点

- `rc` / `rc_chain`：整体退出码 + 最后一个管道各段退出码（PIPESTATUS，经 fd3 旁路，stdout 零污染）。
- `changed`：前后快照机械 diff（created/deleted/modified），全量在 `changed.json`。
- `stdout/stderr`：落盘文件，**路径即 ID**——直接 `read_file` 回验，不冒用 evidence://。
- `scope`：root/depth/budget/entries/截断标注；`ignored` 一行汇总。
- `out_of_scope_refs`：命令文本中绝对路径的机械提取，**启发式、非完整**。
- receipt 落盘 `.smx/runs/<run_id>/receipt.json`，`show` 可重放。

## 诚实边界（如实标注，不静默降级）

1. **净状态语义**：diff 是两个快照版本间的净变化——窗口内创建又删除的瞬时变化不可见。
2. `rc_chain` 只反映脚本中**最后一个管道**；脚本含多条管道时早期链不可见；整体 `rc` 始终准确。
3. 脚本 `exit N`/`exec`/覆盖 EXIT trap 时 meta 缺失：`meta_missing=true`，chain 标不可用。
4. 预算触顶 → `truncated=True` 显式标注；scope 外全称「未观察」，不逐条列。
5. wait 为纯观察动作，无 diff。
6. `--inline` 是呈现层：超行或超 64KiB 自动降级为路径提示；进程仍在跑、stdout 为空均不内联。回执永远完整落盘，内联与否不影响回验。

## 实测（2026-09-11，macOS 本机）

| 用例 | 结果 |
|---|---|
| `ls /no/such | head -3` | `rc=0 chain=[1]`——抓到旧 shell 吞掉的管道中段失败 |
| 4 项 fs 变更（mkdir/cp/rm） | `changed: +demo +demo/b.txt ~root`，无需重跑 ls |
| wait 命中/超时 | satisfied=True / exit=2 |
| bg→collect | running 态禁 diff；终态时间窗 diff + rc 链 |
| 快照开销 | 2.8ms/千条目；3000 文件 8.4ms；真实仓库 depth2 17ms |
