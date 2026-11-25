# main 直写闸 · update-ref 挪 main 判定 · RULE-AI-35 双向实测回执（2026-11-25）

- 用户授权：2026-11-25 20:21「按建议执行」——先定同步规矩（GitHub 合并后统一用
  `git -C <主检出> merge --ff-only origin/main`，被拒即停下问人，不再用 update-ref），
  再把它写进 main 直写闸，按 RULE-AI-35 双向实测。
- 变更：`lane_main_write_guard.check_update_ref_main_move`（新函数）+ 命令闸入口
  `ExecuteCommandTool._lane_main_write_gate` 接线。规则**不以他人 live lane 为条件**，
  拒绝须同时成立：① `git update-ref` 的目标是 main/master（含被 main 检出的 `HEAD`）；
  ② 该分支正被某个工作树检出；③ 新值是远端跟踪分支上已有的提交。
- 基线：`origin/main` = `64e64832838696a040a76bec38c33ecdaee5c5d9`（PR #126 合并提交）。
- 被测：分支 `fix/main-guard-update-ref-sync-20261125` 的工作树，文件 sha256：
  - `src/llm_loop/core/lane_main_write_guard.py` = `d1574771992252f3d7f46f34fee28177a6f7fa6198ee071b4181c18081b435d7`
  - `src/llm_loop/tools/builtin/execute_command.py` = `1a6263f5f5f3e8e02ae8226482ee3bb915b7bb71f7c80a746eb168603af6194b`
  - `tests/unit/test_lane_main_write_guard.py` = `cfab6453d145cab91f867890d14a1a9859d4a629600abd2da9d55d22f94c63bf`
- 解释器：项目 `.venv/bin/python`（3.13.13），`PYTHONPATH=<lane>/src`；git 2.50.1。
- **状态：代码在 lane 分支。写这份回执时宿主进程仍是旧代码，真实 `execute_command`
  入口的端到端实测未做——只能称「代码已提交」，不得称「已生效」。**

## 1. 同步做法实测：`merge --ff-only` vs `update-ref`（scratch 仓库）

探针 `ff-sync-probe2.sh`，sha256
`a164ea362bdb2150a08550618c3be4ce2a34cf63bd4df48d584e4b05c1b531f0`（bare origin +
克隆，分支名用 `trunk` 避开 main 直写闸；每个场景从干净状态出发，由另一个检出扮演
「GitHub 上合并的 PR」）。结论：ff-merge 在各种本地状态下，**要么完成并一并更新暂存区
和工作树，要么整体拒绝、什么都不动**。

| 场景 | 本地状态 | 结果 |
| --- | --- | --- |
| A | 干净且落后 | Fast-forward；HEAD 前进，status 干净，文件内容更新 |
| B | 有会冲突的未提交改动 | `error: Your local changes to the following files would be overwritten by merge … Aborting`，rc=1；HEAD 与本地改动都不变 |
| B' | 问人后放弃本地改动再 ff | Fast-forward |
| C | 无关的已暂存新文件 | Fast-forward；`A  staged.txt` 保留 |
| C2 | 无关的未暂存修改 | Fast-forward；` M b.txt` 保留 |
| D | 未跟踪文件与来的提交新增文件同名 | `error: The following untracked working tree files would be overwritten by merge … Aborting`，rc=1；什么都不动 |
| D' | 移走未跟踪文件后 ff | Fast-forward |
| H | 无冲突的本地修改先 stash，ff，再 pop | Fast-forward；pop 后修改恢复 |
| E | 本地分支含远端没有的提交 | `fatal: Not possible to fast-forward, aborting.`，rc=128；什么都不动 |
| F（对照） | 同样落后且干净，改用 `git update-ref` | HEAD 前进，但 `M  a.txt`、工作树仍是旧内容——**旧树显示成已暂存** |
| G | F 之后再补 ff-merge | `Already up to date.`，暂存区照旧——**修不回来** |

两点补充，都有实测：

- B 的本地改动若与来的提交改的是同一处，`stash → ff → pop` 会在 pop 时留下冲突
  （`UU a.txt`，stash 条目保留），不丢数据但要人解。所以规矩是被拒就停下问人。
- 真实仓库上也遇到一次 E：20:41 本地 main（`ab05f9608`，另一个会话 20:33 把它的 lane
  快进合进了本地 main）与 origin/main（`64e648328`）分叉，ff-merge 回
  `fatal: Not possible to fast-forward, aborting.`，什么都没动。

A / F / G 三行也写进了单元测试
`test_ff_merge_updates_index_and_worktree_unlike_update_ref`。

## 2. RULE-AI-35 双向实测

### 2.1 单元测试（新增 10 条，10 passed）

定向命令：`python -m pytest tests/unit/test_lane_main_write_guard.py -q -k "update_ref or ff_merge"`
→ `10 passed, 168 deselected`。

应拦（`reason=main_ref_pointer_move`，`reason_code=main_update_ref_stale_worktree`）：

- `test_update_ref_main_to_remote_commit_denied_without_lanes`：账本里没有他人 lane 也拦；
  文案含 `` `git -C <检出> merge --ff-only origin/main` ``。
- `test_update_ref_main_variants_denied`：12 种写法全部拦——完整 ref、`-m <msg>`、`-C <dir>`、
  新值写 `origin/main` / `FETCH_HEAD`、`fetch … && update-ref …`、`cd … &&`、`main`、
  `heads/main`、`HEAD`、`M=…; git -C $M …`、`--stdin` 脚本。
- `test_update_ref_master_denied`。
- `test_tool_gate_denies_update_ref_main_via_wiring`：经 `ExecuteCommandTool._lane_main_write_gate`，
  `error_type=lane_main_write_denied`；同一入口对 ff-merge 命令和对 feat 分支的 update-ref 放行。

应放行：

- `test_update_ref_local_only_commit_allowed`：新值是本地独有提交（plumbing 合并），他人 lane 在场也不拦。
- `test_update_ref_non_sync_targets_allowed`：别的分支、`-d`、没挪动、新值读不出、没给新值。
- `test_update_ref_main_allowed_when_not_checked_out`：main 没被任何工作树检出。
- `test_update_ref_main_allowed_without_remote_tracking`：没有远端跟踪分支包含新值。

回归：`test_update_ref_is_not_a_commit_or_push_hit`（update-ref 进解析后不得被既有两条规则
当成 commit/push；同一本账下 `git push origin main` 确实被拦，保证这个 None 不是规则没开）。

### 2.2 对真实仓库状态实测（函数级，未部署）

探针 `rule35-live-probe.py`（原文见 §4.1），sha256
`817d54ffa95f767e599b2cf48e3c39c3000b900f4e5662d5268fb3b2d4796372`。只调用判定函数，不执行任何 git 写。
上下文：workdir = `<RUNTIME_ROOT>`（共享主检出目录，路径见拒绝文案）；main = `ab05f9608…`；
origin/main = `64e648328…`；他人 live lane 30 条；main 检出在该目录。结果 `failures: 0`。

应拦 5/5 BLOCK。其中 17:08 和 20:18 两条是当天事件流水里的原样命令（sha 换成完整值）；
`origin/main` 那条和 `64e648328…` 那条是同形态构造；`-m "sync local main …"` 那条是按
reflog 消息的形态构造的（06:48 那次没有找到完整命令）：

| 输入 | 结果 |
| --- | --- |
| `git update-ref refs/heads/main 64e648328…` | BLOCK |
| `M=/Users/…/llm-first-loop-mirror; git -C $M update-ref refs/heads/main 1f0601e9d…`（17:08 那条） | BLOCK |
| `git fetch origin 2>&1 \| tail -2 && git update-ref refs/heads/main 717c8def2… && echo ok`（20:18 那条） | BLOCK |
| `git update-ref refs/heads/main origin/main` | BLOCK |
| `git -C /Users/…/llm-first-loop-mirror update-ref -m "sync local main to origin/main (PR #119 merged)" refs/heads/main 843eeeadf` | BLOCK |

应放行 4/4 PASS：

| 输入 | 结果 |
| --- | --- |
| `git fetch origin && git -C /Users/…/llm-first-loop-mirror merge --ff-only origin/main`（用户确认的同步命令） | PASS |
| `git -C /Users/…/llm-first-loop-mirror update-ref refs/heads/feat/model-routing-pluggable-20261125 origin/feat/…`（别的分支） | PASS |
| `git -C /Users/…/llm-first-loop-mirror update-ref refs/heads/main ab05f9608…`（本地 main 现值，没挪动） | PASS |
| `… update-ref refs/heads/main ab05f9608… 717c8def2…`（带旧值 CAS，新值是本地独有提交——20:33 那次 lane 合并的提交） | PASS |

定稿前复跑（源码此后只改了说明文字与注释；此时本地 main 已等于 origin/main = `64e648328…`）：
对最终代码用 `rule35-live-probe-final.py` 再跑一遍，应拦 5/5 BLOCK、应放行 5/5 PASS，`failures: 0`；
定向单元 10 passed。相对 §4.1 的探针只改了几行输入：应拦里两条「挪到 origin/main」的输入换成了远端
历史上的旧提交（main 已等于 origin/main 时它们没挪动），另加一条 `cd … &&` 写法；应放行里加了
「没挪动」的同步形态 `git update-ref refs/heads/main origin/main`。

首轮探针有一条 PASS 是我输入写错：17:08 那条的完整 sha 我手抄成了 `…569eb5a1b7f25`，
仓库里不存在这个对象，判定函数按「新值读不出 → 放行」处理。换成真实 sha
`1f0601e9d0225bfb66160e9fb2a569eba176cf99` 后 BLOCK。这条同时是 §3 第一条残余的实例。

## 3. 未覆盖与残余（已知，未修）

- 新值读不出就放行：`$(git rev-parse origin/main)` 这类命令替换、尚未 fetch 到本地的 sha、
  `--stdin -z` 脚本。拒绝只基于已证事实，这是有意的取舍。
- `reset --soft/--mixed <commit>` 在 main 检出里挪 main：同一类后果（只动指针或不动工作树），没收。
- `update-ref -d` 删 main 引用：不是「同步」，没收。
- `git branch -f main` / `fetch origin main:main`：main 被检出时 git 自己拒绝，不需要收。
- `-C $VAR` 解析不出真实目录时按命令 workdir 判：对别的仓库做 update-ref 会被按本仓库判，
  拒绝文案里的检出路径会不对。
- 命令文本落进解析器的保守哨兵（`eval`、`bash -c`、不透明 token 等）时，本规则读不到
  update-ref 段，不触发。这是既有解析器的边界，合并审查指出后补记。
- `git update-ref --stdin < 脚本文件`：命令文本里没有 ref 名，读不到。
- `workdir=None` 时新规则直接放行。命令闸调用点在调用前已把 None 换成工作区根（无工作区时为进程
  cwd），经工具入口不会出现 None；只有直接调用函数才会遇到（合并审查指出后补）。
- **端到端未测**：真实 `execute_command` 入口要走已部署的新代码。部署后的补测做法：在 scratch
  克隆上发应拦输入（闸失效时也只动 scratch 的 main），应看到 `[main 直写拒绝] main_ref_pointer_move`。

## 4. 探针原文

入库副本做了脱敏：本机绝对路径换成 `<RUNTIME_ROOT>`；sha256 是脱敏前原文件的。

### 4.1 `rule35-live-probe.py`

```python
"""RULE-AI-35 实测：对真实仓库状态跑应拦 / 应放行输入。只读：只调用判定函数，不执行任何 git 写。"""
import subprocess
import sys

sys.path.insert(0, sys.argv[1])
from llm_loop.core import lane_main_write_guard as g  # noqa: E402

MIRROR = "<RUNTIME_ROOT>"
# 宿主 settings.audit_dir = <runtime root>/data/audit；探针进程没有 .env，直接给路径。
audit = MIRROR + "/data/audit"
session = "rule35-probe-session"


def ro(*args: str) -> str:
    return subprocess.run(
        ["git", "-C", MIRROR, *args], check=True, capture_output=True, text=True
    ).stdout.strip()


print("== 上下文 ==")
print("workdir   :", MIRROR)
print("audit_dir :", audit)
print("main      :", ro("rev-parse", "refs/heads/main"))
print("origin/main:", ro("rev-parse", "refs/remotes/origin/main"))
print("others lanes:", len(g._active_other_lanes(audit, session)))
print("main checkout:", g._main_checkout_worktree(MIRROR, "main"))

should_block = [
    "git update-ref refs/heads/main 64e64832838696a040a76bec38c33ecdaee5c5d9",
    "M=<RUNTIME_ROOT>; git -C $M update-ref refs/heads/main"
    " 1f0601e9d0225bfb66160e9fb2a569eba176cf99",
    "git fetch origin 2>&1 | tail -2 && git update-ref refs/heads/main"
    " 717c8def258b725c36042b9c0f22f0575d91c2e6 && echo ok",
    "git update-ref refs/heads/main origin/main",
    'git -C <RUNTIME_ROOT> update-ref -m'
    ' "sync local main to origin/main (PR #119 merged)" refs/heads/main 843eeeadf',
]
should_pass = [
    "git fetch origin && git -C <RUNTIME_ROOT> merge --ff-only"
    " origin/main",
    "git -C <RUNTIME_ROOT> update-ref"
    " refs/heads/feat/model-routing-pluggable-20261125"
    " origin/feat/model-routing-pluggable-20261125",
    "git -C <RUNTIME_ROOT> update-ref refs/heads/main"
    " ab05f960876bd68d350f7761b92638739586fec9",
    "git -C <RUNTIME_ROOT> update-ref refs/heads/main"
    " ab05f960876bd68d350f7761b92638739586fec9 717c8def258b725c36042b9c0f22f0575d91c2e6",
]

failures = 0
print("\n== 应拦 ==")
for cmd in should_block:
    out = g.check_update_ref_main_move(
        cmd, audit_dir=audit, session_id=session, workdir=MIRROR
    )
    ok = out is not None
    failures += 0 if ok else 1
    print(("BLOCK " if ok else "PASS  "), cmd)
    if out is not None:
        print("        reason=%s code=%s lanes=%d" % (out["reason"], out["reason_code"], len(out["lanes"])))
        print("        detail:", out["detail"].split("。")[0][:160], "…")

print("\n== 应放行 ==")
for cmd in should_pass:
    out = g.check_update_ref_main_move(
        cmd, audit_dir=audit, session_id=session, workdir=MIRROR
    )
    ok = out is None
    failures += 0 if ok else 1
    print(("PASS  " if ok else "BLOCK "), cmd)
    if out is not None:
        print("        detail:", out["detail"][:200])

print("\nfailures:", failures)
sys.exit(1 if failures else 0)
```

### 4.2 `ff-sync-probe2.sh`

```bash
#!/bin/bash
# 探针2：每个场景从干净状态出发；验证 ff-merge 在各种本地状态下“要么安全完成、要么整体拒绝不动”。
# scratch 仓库；分支名用 trunk，避开 main 直写闸。只写 .tmp-probe 下的 scratch，不碰本仓库。
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
BASE="$HERE/ff2-sync-$(date +%H%M%S)"
mkdir -p "$BASE"
git init -q --bare "$BASE/origin.git"
git --git-dir="$BASE/origin.git" symbolic-ref HEAD refs/heads/trunk
git init -q -b trunk "$BASE/clone"
cd "$BASE/clone" || exit 1
git config user.email probe@example.com
git config user.name probe
git config commit.gpgsign false
echo a1 > a.txt
echo b1 > b.txt
git add . >/dev/null
git commit -q -m c1
git remote add origin "$BASE/origin.git"
git push -q origin trunk
git clone -q "$BASE/origin.git" "$BASE/other"
cd "$BASE/other" || exit 1
git config user.email probe@example.com
git config user.name probe
state() { echo "rc=$? HEAD=$(git rev-parse --short HEAD) origin/trunk=$(git rev-parse --short origin/trunk) status=[$(git status --short | tr '\n' ' ')] a.txt=$(cat a.txt) b.txt=$(cat b.txt)"; }
# 让 origin 前进一步（改 a.txt）并 fetch
pr() { cd "$BASE/other" || exit 1; echo "$1" > a.txt; git commit -q -am "$2"; git push -q origin trunk; cd "$BASE/clone" || exit 1; git fetch -q origin; }

pr a2 c2
echo "### A 干净检出+落后"
git merge --ff-only origin/trunk; state

pr a3 c3
echo a-local > a.txt
echo "### B 有会冲突的未提交改动（a.txt）"
git merge --ff-only origin/trunk; state
echo "### B' 问人后决定放弃本地改动：git checkout -- a.txt 再 ff"
git checkout -q -- a.txt
git merge --ff-only origin/trunk; state

pr a4 c4
echo x > staged.txt
git add staged.txt
echo "### C 无关的已暂存新文件（staged.txt）"
git merge --ff-only origin/trunk; state

pr a5 c5
echo b-local > b.txt
echo "### C2 无关的未暂存修改（b.txt）"
git merge --ff-only origin/trunk; state

cd "$BASE/other" || exit 1
echo a6 > a.txt
echo from-pr > new.txt
git add new.txt
git commit -q -am c6
git push -q origin trunk
cd "$BASE/clone" || exit 1
git fetch -q origin
echo local-untracked > new.txt
echo "### D 未跟踪文件与来的提交新增文件同名（new.txt）"
git merge --ff-only origin/trunk; state
echo "### D' 移走未跟踪文件后 ff"
rm new.txt
git merge --ff-only origin/trunk; state

pr a7 c7
git stash -q
echo "### H 本地无冲突修改（b.txt）先 stash，再 ff，再 pop"
git merge --ff-only origin/trunk; state
git stash pop -q
echo "after pop: status=[$(git status --short | tr '\n' ' ')] b.txt=$(cat b.txt)"

pr a8 c8
echo a-local-commit > a.txt
git commit -q -am local-c9
echo "### E 本地分支含远端没有的提交（分叉）"
git merge --ff-only origin/trunk; state
git reset -q --hard origin/trunk

pr a9 c9
echo "### F 对照：同样落后且干净，用 git update-ref refs/heads/trunk origin/trunk"
git update-ref refs/heads/trunk origin/trunk; state
echo "### G F 之后补 ff-merge 能否修复暂存区/工作树"
git merge --ff-only origin/trunk; state
echo "BASE=$BASE"
```

### 4.3 `rule35-live-probe.py` 输出

```text
== 上下文 ==
workdir   : <RUNTIME_ROOT>
audit_dir : <RUNTIME_ROOT>/data/audit
main      : ab05f960876bd68d350f7761b92638739586fec9
origin/main: 64e64832838696a040a76bec38c33ecdaee5c5d9
others lanes: 30
main checkout: <RUNTIME_ROOT>

== 应拦 ==
BLOCK  git update-ref refs/heads/main 64e64832838696a040a76bec38c33ecdaee5c5d9
        reason=main_ref_pointer_move code=main_update_ref_stale_worktree lanes=5
        detail: 命令用 git update-ref 挪 refs/heads/main，而 main 正检出在 <RUNTIME_ROOT>：update-ref 只移指针，不更新该检出的暂存区和工作树，会把旧树显示成反向“已暂存”、运行期工作树停在旧代码 …
BLOCK  M=<RUNTIME_ROOT>; git -C $M update-ref refs/heads/main 1f0601e9d0225bfb66160e9fb2a569eba176cf99
        reason=main_ref_pointer_move code=main_update_ref_stale_worktree lanes=5
        detail: 命令用 git update-ref 挪 refs/heads/main，而 main 正检出在 <RUNTIME_ROOT>：update-ref 只移指针，不更新该检出的暂存区和工作树，会把旧树显示成反向“已暂存”、运行期工作树停在旧代码 …
BLOCK  git fetch origin 2>&1 | tail -2 && git update-ref refs/heads/main 717c8def258b725c36042b9c0f22f0575d91c2e6 && echo ok
        reason=main_ref_pointer_move code=main_update_ref_stale_worktree lanes=5
        detail: 命令用 git update-ref 挪 refs/heads/main，而 main 正检出在 <RUNTIME_ROOT>：update-ref 只移指针，不更新该检出的暂存区和工作树，会把旧树显示成反向“已暂存”、运行期工作树停在旧代码 …
BLOCK  git update-ref refs/heads/main origin/main
        reason=main_ref_pointer_move code=main_update_ref_stale_worktree lanes=5
        detail: 命令用 git update-ref 挪 refs/heads/main，而 main 正检出在 <RUNTIME_ROOT>：update-ref 只移指针，不更新该检出的暂存区和工作树，会把旧树显示成反向“已暂存”、运行期工作树停在旧代码 …
BLOCK  git -C <RUNTIME_ROOT> update-ref -m "sync local main to origin/main (PR #119 merged)" refs/heads/main 843eeeadf
        reason=main_ref_pointer_move code=main_update_ref_stale_worktree lanes=5
        detail: 命令用 git update-ref 挪 refs/heads/main，而 main 正检出在 <RUNTIME_ROOT>：update-ref 只移指针，不更新该检出的暂存区和工作树，会把旧树显示成反向“已暂存”、运行期工作树停在旧代码 …

== 应放行 ==
PASS   git fetch origin && git -C <RUNTIME_ROOT> merge --ff-only origin/main
PASS   git -C <RUNTIME_ROOT> update-ref refs/heads/feat/model-routing-pluggable-20261125 origin/feat/model-routing-pluggable-20261125
PASS   git -C <RUNTIME_ROOT> update-ref refs/heads/main ab05f960876bd68d350f7761b92638739586fec9
PASS   git -C <RUNTIME_ROOT> update-ref refs/heads/main ab05f960876bd68d350f7761b92638739586fec9 717c8def258b725c36042b9c0f22f0575d91c2e6

failures: 0
```

## 5. 审查记录（补记）

- RULE-AI-28：full_test 审查与 git_push 审查都走过并通过。每多一个提交，push 审查资格就作废，
  要重发；git_push 审查不能按 paths 切片，回 `push_batch_full_review_required`，得整树发起。
- 独立合并审查两次 REVISE，都是 p0=0、p1=1，都没有指出代码缺陷：
  - 第一次（head `adba4cf26`，child `subagent_a44620d860b1`）。P1：测试执行证据与回执绑定没有
    获得独立确认——全量门禁回执里的被测提交是 `31bb13ea2`，不是被审 head；解释是父代理自述；
    只读审查员不能跑测试。它同时指出保守哨兵边界没写进 §3（已补）。
  - 第二次（head `e0098760a`，child `subagent_bf2054f86e28`）。同一类 P1：它没有 shell，也读不了
    evidence 引用，「此后只有文档变化」对它仍是自述。它已核的部分：`_lane_main_write_gate`、判定
    新增段、`_collect_main_write_hits` / `_main_write_targets` 的 update-ref 分支与冻结 diff 一致；
    子进程均为固定参数列表，`_rev_sha` 有 `_SAFE_REV_RE` 防选项注入；没有发现安全或回归缺陷。
    它没核完的三点和处置：
    ① `workdir=None` 时新规则直接放行，§3 没列——调用点在调用前已把 None 换成工作区根，已补进 §3；
    ② `_git_verbs` 与模块说明还写着「只认 commit/push」——已改；
    ③ 代码注释写「一天六次」，与这里说的七次不一致——已改成七次。
- 绑定怎么做（吸取两次 P1）：回执放进分支就必然晚于被测提交，只能自述。所以全量门禁回执不再
  进分支：代码、测试、本回执、架构清单全部定稿并提交之后，在那个提交本身上重跑
  `bash scripts/ci_gate.sh`，回执贴在 PR #128 的评论里；远端 CI 对同一 head 的结果是独立佐证。
  本回执只承担 RULE-AI-35 的实测记录，不承担全量门禁的绑定。
