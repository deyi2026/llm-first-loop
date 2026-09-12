#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""smx — 语义 shell 执行器（语义操控框架 shell 域 PoC · R1）

对应设计: docs/DESIGN-20260911-semantic-manipulation-framework.md
四契约映射:
  感知  stat 快照 + 机械 diff（快照版本对）。不做命令语义解析推断副作用（P4：解释必须可回验）。
  标识  文件路径 = 天然稳定 ID；run_id = 一次执行的稳定 ID；
        stdout/stderr 落盘为文件，路径即 ID（不冒用 evidence:// 命名空间，复用 read_file 回验通道）。
  动作  exec / bg+collect / wait。wait 为一等动作：模型声明条件谓词与超时，轮询由程序执行。
  反馈  语义 diff + 退出码链（PIPESTATUS）+ 回执 JSON 落盘可重放（smx show <run_id>）。

R1 范围（按"语义 ID 是否需要框架维护"切分）:
  in : 文件域（路径天然稳定 ID）、wait 条件谓词、后台任务时间窗 diff。
  out: 进程卡片 / job_id 语义体系（R2，需框架自维护 ID 映射）。

安全边界（按 REVIEW-20260912-security.md 修正）: smx 本体含直接执行通道（exec/bg 内部为
bash -c，自身无硬安全边界）——「继承 execute_command 安全边界」仅在 smx 经 execute_command
调用的实验用法下成立，不能宣称 smx 不提供越权能力。因此并入形态限定为「感知层工具」:
wait / 前后快照 diff / 回执查询；exec/bg 不进工具面，执行动作维持经 execute_command。
感知面自身限制: 文件系统只读元数据（lstat/scandir）；wait 端口探测限 loopback 白名单
（127.0.0.1/::1/localhost，S2）；run_id 白名单拒路径穿越（S3）；快照物化受 budget 上界约束（S4）。

已知诚实限制: 窗口 diff 是"净状态"语义——窗口内创建又删除的瞬时变化不可见；
rc_chain 反映脚本中最后一个管道的各段退出码（bash PIPESTATUS 语义），整体 rc 始终准确；
collect 的 alive 判定用 kill(pid,0)，极端 PID 复用可误判 running（保守误判只延迟 collect，
不损坏数据，S5.2 已知限制）；bg 无超时上限、killpg 不及 daemonize 子进程（S5.3/5.4 已知限制）；
file_contains 只检前 8MiB（S5.5）。
"""
import argparse
import hashlib
import heapq
import json
import os
import re
import signal
import socket
import subprocess
import sys
import time
from datetime import datetime

SCHEMA = "smx.receipt/1"
SNAP_SCHEMA = "smx.snapshot/1"
RUNROOT = ".smx"
IGNORES = [".git", "node_modules", "__pycache__", ".venv", ".smx"]
ABS_RE = re.compile(r"(?<![\w:/])(?:~|/[A-Za-z0-9._~+-]+)(?:/[A-Za-z0-9._~+-]+)*")
LOOPBACK_HOSTS = {"127.0.0.1", "::1", "localhost"}
RUN_ID_RE = re.compile(r"[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+)*")
FC_CAP = 8 * 1024 * 1024  # file_contains 单次读取上限（S5.5）
INLINE_BYTE_CAP = 64 * 1024  # --inline 体积护栏：stdout 文件超此字节数不内联（防超长行爆屏）


# ---------- 基础工具 ----------

def now_iso():
    return datetime.now().astimezone().isoformat(timespec="milliseconds")


def new_run_id():
    return "r" + datetime.now().strftime("%Y%m%d-%H%M%S-") + os.urandom(2).hex()


def sha12(obj):
    return hashlib.sha256(
        json.dumps(obj, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()[:12]


def rel(key, root):
    if key == root:
        return "."
    if key.startswith(root + os.sep):
        return key[len(root) + 1:]
    return key


def line_count(data: bytes) -> int:
    if not data:
        return 0
    n = data.count(b"\n")
    if not data.endswith(b"\n"):
        n += 1
    return n


def out_of_scope_refs(cmd, root):
    """scope 外启发式：机械提取命令文本中的绝对路径/~ 路径。非完整（P4：标注启发式）。"""
    seen, out = set(), []
    for m in ABS_RE.finditer(cmd):
        p = m.group(0)
        if p == "~":
            continue
        ap = os.path.abspath(os.path.expanduser(p))
        if ap == root or ap.startswith(root + os.sep):
            continue
        if p not in seen:
            seen.add(p)
            out.append(p)
    return out[:8]


# ---------- 快照与 diff（感官：机械采集，无解释） ----------

def _entry(st, is_dir, is_link):
    return {"t": "d" if is_dir else ("l" if is_link else "f"),
            "s": None if is_dir else st.st_size,
            "m": st.st_mtime_ns}


def take_snapshot(roots, depth, budget):
    """roots: [(root_id, abspath)]。entries: {abs_path: {t,s,m}}，元数据含截断标注。"""
    entries, meta, remaining = {}, [], budget
    for rid, rp in roots:
        m = {"id": rid, "root": rp, "count": 0, "truncated": False, "note": None}
        meta.append(m)
        if remaining <= 0:
            m["note"] = "budget_exhausted_before_start"
            continue
        if not os.path.exists(rp):
            m["note"] = "not_found"
            continue
        try:
            st = os.lstat(rp)
            entries[rp] = _entry(st, os.path.isdir(rp) and not os.path.islink(rp), os.path.islink(rp))
            m["count"] += 1
            remaining -= 1
        except OSError as e:
            m["note"] = "lstat_error:%s" % e.errno
            continue
        stack = [(rp, 0)]
        while stack and remaining > 0:
            d, dep = stack.pop()
            if dep >= depth:
                continue
            try:
                # S4: 有界物化——巨型目录只取预算内最小键序（nsmallest 流式淘汰，内存 O(k)）
                it = heapq.nsmallest(remaining + len(IGNORES), os.scandir(d), key=lambda x: x.name)
            except OSError as e:
                m.setdefault("walk_errors", []).append("%s:%s" % (d, e.errno))
                continue
            for ent in it:
                if ent.name in IGNORES:
                    continue
                p = ent.path
                try:
                    isd = ent.is_dir(follow_symlinks=False)
                    isl = ent.is_symlink()
                    stt = ent.stat(follow_symlinks=False)
                    entries[p] = _entry(stt, isd, isl)
                except OSError as e:
                    m.setdefault("walk_errors", []).append("%s:%s" % (p, e.errno))
                    continue
                m["count"] += 1
                remaining -= 1
                if isd:
                    stack.append((p, dep + 1))
                if remaining <= 0:
                    m["truncated"] = True
                    stack = []
                    break
    return entries, meta


def diff_pair(before, after):
    created = sorted(set(after) - set(before))
    deleted = sorted(set(before) - set(after))
    modified = []
    for p in sorted(set(before) & set(after)):
        b, a = before[p], after[p]
        ch = [n for n in ("t", "s", "m") if b.get(n) != a.get(n)]
        if ch:
            modified.append({"path": p, "changed": ch})
    return {"created": created, "deleted": deleted, "modified": modified}


# ---------- bash 包装：退出码链经 fd3 旁路捕获，stdout 零污染 ----------

def build_wrapper(cmd, nonce, fd):
    mark = "__SMX_META_%s__" % nonce
    return (
        "__smx_emit() { declare -a __SMX_PS=(\"${PIPESTATUS[@]}\"); __SMX_RC=$?; "
        "printf '%s rc=%%s pipe=%%s\\n' \"$__SMX_RC\" \"$(IFS=,; echo \"${__SMX_PS[*]}\")\" >&%d; }\n" % (mark, fd)
        + "trap __smx_emit EXIT\n"
        + cmd + "\n"
    )


def parse_meta(path, nonce):
    mark = "__SMX_META_%s__" % nonce
    try:
        with open(path, "r", errors="replace") as f:
            txt = f.read()
    except OSError:
        return None
    for line in reversed(txt.splitlines()):
        if line.startswith(mark):
            d = {}
            for part in line.split()[1:]:
                k, _, v = part.partition("=")
                d[k] = v
            try:
                return {"rc": int(d.get("rc", "255")),
                        "chain": [int(x) for x in d.get("pipe", "").split(",") if x]}
            except ValueError:
                return None
    return None


# ---------- 回执 ----------

def check_run_id(rid):
    """S3: run_id 白名单（[A-Za-z0-9_.-] 且拒分隔符/../..片段），阻断 collect/show 路径穿越。"""
    if not rid or not RUN_ID_RE.fullmatch(rid):
        print("run_id 非法（白名单 [A-Za-z0-9_.-]，禁 / \\ 与 .. 片段）: %r" % (rid,), file=sys.stderr)
        raise SystemExit(2)


def run_dir(root, run_id):
    rd = os.path.join(root, RUNROOT, "runs", run_id)
    os.makedirs(rd, exist_ok=True)
    return rd


def write_snapshot(rd, name, entries, meta):
    obj = {"schema": SNAP_SCHEMA, "taken_at": now_iso(), "roots_meta": meta, "entries": entries}
    path = os.path.join(rd, name)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, sort_keys=True, ensure_ascii=False)
    return path, sha12(obj)


def changed_display(diff, root, cap=20):
    rows = [("+" + rel(p, root)) for p in diff["created"]]
    rows += [("-" + rel(p, root)) for p in diff["deleted"]]
    rows += [("~" + rel(c["path"], root) + " [" + ",".join(c["changed"]) + "]")
             for c in diff["modified"]]
    truncated = len(rows) > cap
    return rows[:cap], truncated, len(rows)


def emit(rcp, as_json, path):
    if as_json:
        print(json.dumps(rcp, sort_keys=True, ensure_ascii=False, indent=1))
    else:
        print_summary(rcp, path)
    return 0


def print_summary(rcp, path):
    root = rcp.get("scope", {}).get("root", "")
    k = rcp["kind"]
    print("[smx %s] %s" % (k, rcp["run_id"]))
    if k == "exec":
        print("  rc=%s chain=%s%s" % (rcp["rc"], rcp.get("rc_chain"),
                                      " TIMED_OUT" if rcp.get("timed_out") else ""))
        if rcp.get("meta_missing"):
            print("  note: meta_missing (脚本 exit/exec/覆盖 EXIT trap)，chain 不可用，rc 为 bash 返回值")
        print("  stdout %dL -> %s" % (rcp["stdout_lines"], rcp["stdout_path"]))
        print("  stderr %dL -> %s" % (rcp["stderr_lines"], rcp["stderr_path"]))
    elif k == "bg_launch":
        print("  pid=%s launched_at=%s" % (rcp.get("pid"), rcp.get("launched_at")))
        print("  stdout -> %s / stderr -> %s" % (rcp["stdout_path"], rcp["stderr_path"]))
    elif k == "collect":
        print("  running=%s rc=%s chain=%s" % (rcp.get("running"), rcp.get("rc"), rcp.get("rc_chain")))
        if rcp.get("time_window"):
            print("  window: %s -> %s (%s)" % (rcp["time_window"]["from"], rcp["time_window"]["to"],
                                               rcp["time_window"]["semantics"]))
    elif k == "wait":
        print("  condition=%s satisfied=%s waited_ms=%s timeout=%ss"
              % (rcp["condition"], rcp["satisfied"], rcp["waited_ms"], rcp["timeout_s"]))
        if rcp.get("detail"):
            print("  detail: %s" % rcp["detail"])
    d = rcp.get("diff")
    if d is not None and d.get("applicable"):
        rows, trunc, total = changed_display(d["full_diff"], root) if "full_diff" in d else ([], False, 0)
        cc = d["counts"]
        print("  changed: +%d / -%d / ~%d%s" % (cc["created"], cc["deleted"], cc["modified"],
                                                ("  (显示 %d/%d, 全量: %s)" % (len(rows), total, d["full_list_path"])) if total else ""))
        for r in rows:
            print("    " + r)
    elif d is not None:
        print("  diff: not_applicable (%s)" % d.get("reason"))
        if k == "wait":
            print("        wait 为纯观察动作，不修改世界状态")
    sc = rcp.get("scope")
    if sc:
        print("  scope: %s depth=%d entries %s->%s budget=%d truncated=%s watch=%s"
              % (sc["root"], sc["depth"], sc["entries_before"], sc["entries_after"],
                 sc["budget"], sc["truncated_any"], sc.get("extra_roots", [])))
    if rcp.get("ignored"):
        print("  ignored: %s" % " ".join(rcp["ignored"]))
    if rcp.get("out_of_scope_refs"):
        print("  out_of_scope(heuristic,non-exhaustive): %s" % " ".join(rcp["out_of_scope_refs"]))
    if rcp.get("timings"):
        print("  timings: %s" % json.dumps(rcp["timings"], ensure_ascii=False))
    print("  receipt: %s" % path)


def finish_receipt(rcp, rd, root, args, bmeta, ameta, diff, before_path, before_ver,
                   after_path, after_ver):
    cc = {"created": len(diff["created"]), "deleted": len(diff["deleted"]),
          "modified": len(diff["modified"])}
    full = os.path.join(rd, "changed.json")
    with open(full, "w", encoding="utf-8") as f:
        json.dump(diff, f, sort_keys=True, ensure_ascii=False)
    rows, trunc, total = changed_display(diff, root)
    rcp["diff"] = {
        "model": "snapshot_pair",
        "applicable": True,
        "before_ver": before_ver, "after_ver": after_ver,
        "before_path": before_path, "after_path": after_path,
        "counts": cc, "display": rows, "display_truncated": trunc,
        "full_list_path": full,
    }
    rcp["scope"] = {
        "root": root, "depth": args.depth, "budget": args.budget,
        "entries_before": sum(m["count"] for m in bmeta),
        "entries_after": sum(m["count"] for m in ameta),
        "truncated_any": any(m["truncated"] or (m.get("note")) for m in bmeta + ameta),
        "roots_meta": {"before": bmeta, "after": ameta},
        "extra_roots": args.watch or [],
    }
    rcp["ignored"] = IGNORES
    rcp["out_of_scope_refs"] = out_of_scope_refs(rcp.get("command", ""), root)


# ---------- 动作 ----------

def spawn(root, rd, cmd, nonce):
    metaf = open(os.path.join(rd, "meta.txt"), "w")
    outp = open(os.path.join(rd, "stdout.txt"), "wb")
    errp = open(os.path.join(rd, "stderr.txt"), "wb")
    proc = subprocess.Popen(
        ["bash", "-c", build_wrapper(cmd, nonce, metaf.fileno())], cwd=root,
        stdout=outp, stderr=errp, pass_fds=(metaf.fileno(),), start_new_session=True)
    return proc, metaf, outp, errp


def resolve_cmd(args):
    """cmd 位置参数 XOR --script FILE（'-'=stdin）：返回命令文本。
    --script 文本不经任何外层 shell 展开直达内层 bash——解决多层 quoting 脆弱（$0 被展开等）。"""
    if getattr(args, "script", None) is not None:
        if args.cmd:
            sys.exit("smx: cmd 位置参数与 --script 互斥，二选一")
        if args.script == "-":
            cmd = sys.stdin.read()
        else:
            try:
                with open(args.script, encoding="utf-8") as f:
                    cmd = f.read()
            except OSError as e:
                sys.exit("smx: --script %s 读取失败: %s" % (args.script, e))
    else:
        cmd = args.cmd or ""
    if not cmd.strip():
        sys.exit("smx: 命令为空（需 cmd 位置参数或 --script FILE）")
    return cmd


def print_inline(path, limit):
    """--inline N：stdout ≤N 行且体积 ≤INLINE_BYTE_CAP 时直接内联打印。
    纯呈现优化——回执仍完整落盘（路径即 ID），不改 receipt schema。"""
    if limit <= 0 or not path or not os.path.exists(path):
        return
    with open(path, "rb") as f:
        data = f.read()
    n = line_count(data)
    if n == 0:
        return
    if n > limit:
        print("  (stdout %dL > --inline %d，不内联)" % (n, limit))
        return
    if len(data) > INLINE_BYTE_CAP:
        print("  (stdout %dL ≤ %d 但 %dB > %dB cap，不内联)" % (n, limit, len(data), INLINE_BYTE_CAP))
        return
    print("  ---- stdout inline (%dL) ----" % n)
    for ln in data.decode("utf-8", "replace").splitlines():
        print("  | " + ln)
    print("  ---- end inline ----")


def cmd_exec(args):
    root = os.path.abspath(args.root or os.getcwd())
    run_id = new_run_id()
    rd = run_dir(root, run_id)
    cmd = resolve_cmd(args)
    rs = [("main", root)] + [("w%d" % i, os.path.abspath(w)) for i, w in enumerate(args.watch or [])]
    nonce = os.urandom(3).hex()

    t = time.time()
    before, bmeta = take_snapshot(rs, args.depth, args.budget)
    snap_before_ms = round((time.time() - t) * 1000, 1)
    before_path, before_ver = write_snapshot(rd, "before.json", before, bmeta)

    started = now_iso()
    t = time.time()
    proc, metaf, outp, errp = spawn(root, rd, cmd, nonce)
    timed_out = False
    try:
        rc = proc.wait(timeout=args.timeout if args.timeout and args.timeout > 0 else None)
    except subprocess.TimeoutExpired:
        timed_out = True
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except Exception:
            pass
        rc = proc.wait()
    duration_ms = round((time.time() - t) * 1000, 1)
    for fh in (metaf, outp, errp):
        fh.close()

    t = time.time()
    after, ameta = take_snapshot(rs, args.depth, args.budget)
    snap_after_ms = round((time.time() - t) * 1000, 1)
    after_path, after_ver = write_snapshot(rd, "after.json", after, ameta)

    meta = parse_meta(os.path.join(rd, "meta.txt"), nonce)
    with open(os.path.join(rd, "stdout.txt"), "rb") as f:
        outb = f.read()
    with open(os.path.join(rd, "stderr.txt"), "rb") as f:
        errb = f.read()

    diff = diff_pair(before, after)
    rcp = {"schema": SCHEMA, "kind": "exec", "run_id": run_id, "command": cmd,
           "root": root, "cwd": root, "started_at": started, "ended_at": now_iso(),
           "rc": rc, "rc_chain": meta["chain"] if meta else None,
           "meta_missing": meta is None, "timed_out": timed_out,
           "stdout_path": os.path.join(rd, "stdout.txt"), "stderr_path": os.path.join(rd, "stderr.txt"),
           "stdout_lines": line_count(outb), "stderr_lines": line_count(errb),
           "timings": {"snap_before_ms": snap_before_ms, "cmd_ms": duration_ms,
                       "snap_after_ms": snap_after_ms}}
    finish_receipt(rcp, rd, root, args, bmeta, ameta, diff, before_path, before_ver,
                   after_path, after_ver)
    rpath = os.path.join(rd, "receipt.json")
    with open(rpath, "w", encoding="utf-8") as f:
        json.dump(rcp, f, sort_keys=True, ensure_ascii=False, indent=1)
    emit(rcp, args.json, rpath)
    if not args.json:
        print_inline(rcp["stdout_path"], args.inline)
    return 0 if (rc == 0 and not timed_out) else 1


def cmd_bg(args):
    root = os.path.abspath(args.root or os.getcwd())
    run_id = new_run_id()
    rd = run_dir(root, run_id)
    cmd = resolve_cmd(args)
    rs = [("main", root)] + [("w%d" % i, os.path.abspath(w)) for i, w in enumerate(args.watch or [])]
    nonce = os.urandom(3).hex()
    before, bmeta = take_snapshot(rs, args.depth, args.budget)
    before_path, before_ver = write_snapshot(rd, "before.json", before, bmeta)
    proc, metaf, outp, errp = spawn(root, rd, cmd, nonce)
    pid = proc.pid
    for fh in (metaf, outp, errp):
        fh.close()
    rcp = {"schema": SCHEMA, "kind": "bg_launch", "run_id": run_id, "command": cmd,
           "root": root, "pid": pid, "launched_at": now_iso(), "nonce": nonce,
           "scope_roots": rs, "depth": args.depth, "budget": args.budget,
           "stdout_path": os.path.join(rd, "stdout.txt"), "stderr_path": os.path.join(rd, "stderr.txt"),
           "diff": {"model": "snapshot_pair", "applicable": False,
                    "reason": "background: 无 after 时刻，collect 时按时间窗取净状态",
                    "before_path": before_path, "before_ver": before_ver},
           "ignored": IGNORES, "out_of_scope_refs": out_of_scope_refs(cmd, root)}
    rpath = os.path.join(rd, "receipt.json")
    with open(rpath, "w", encoding="utf-8") as f:
        json.dump(rcp, f, sort_keys=True, ensure_ascii=False, indent=1)
    with open(os.path.join(rd, "pid"), "w") as f:
        f.write(str(pid))
    emit(rcp, args.json, rpath)
    return 0


def cmd_collect(args):
    root = os.path.abspath(args.root or os.getcwd())
    check_run_id(args.run_id)
    rd = os.path.join(root, RUNROOT, "runs", args.run_id)
    rpath = os.path.join(rd, "receipt.json")
    with open(rpath, encoding="utf-8") as f:
        bg = json.load(f)
    if bg.get("kind") != "bg_launch":
        print("run %s 不是 bg_launch（kind=%s）" % (args.run_id, bg.get("kind")), file=sys.stderr)
        return 2
    try:
        with open(os.path.join(rd, "pid")) as f:
            pid = int(f.read().strip())
    except (OSError, ValueError):
        pid = None
    alive = False
    if pid is not None:
        try:
            os.kill(pid, 0)
            alive = True
        except ProcessLookupError:
            alive = False
        except PermissionError:
            alive = True
    rcp = {"schema": SCHEMA, "kind": "collect", "run_id": args.run_id,
           "command": bg["command"], "root": root, "pid": pid, "alive": alive,
           "collected_at": now_iso()}
    if alive:
        rcp["running"] = True
        rcp["note"] = "进程仍在运行；稍后再次 collect。未取 diff（避免把半途状态当终态）"
        emit(rcp, args.json, rpath)
        return 0
    with open(bg["diff"]["before_path"], encoding="utf-8") as f:
        before = json.load(f)["entries"]
    integrity_ok = sha12({"entries": before}) == bg["diff"]["before_ver"]
    t = time.time()
    after, ameta = take_snapshot([tuple(r) for r in bg["scope_roots"]], bg["depth"], bg["budget"])
    snap_ms = round((time.time() - t) * 1000, 1)
    after_path, after_ver = write_snapshot(rd, "after.json", after, ameta)
    meta = parse_meta(os.path.join(rd, "meta.txt"), bg["nonce"])
    diff = diff_pair(before, after)

    class NS:
        pass
    ns = NS()
    ns.depth, ns.budget, ns.watch = bg["depth"], bg["budget"], None
    rcp.update({"running": False, "rc": (meta or {}).get("rc"), "rc_chain": (meta or {}).get("chain"),
                "meta_missing": meta is None,
                "time_window": {"from": bg["launched_at"], "to": rcp["collected_at"],
                                "semantics": "net_state_since_launch（窗口内创建又删除的瞬时变化不可见）"},
                "integrity_before_sha_match": integrity_ok,
                "timings": {"snap_collect_ms": snap_ms}})
    finish_receipt(rcp, rd, root, ns, bg_scope_meta(bg), ameta, diff,
                   bg["diff"]["before_path"], bg["diff"]["before_ver"], after_path, after_ver)
    with open(rpath, "w", encoding="utf-8") as f:
        json.dump(rcp, f, sort_keys=True, ensure_ascii=False, indent=1)
    emit(rcp, args.json, rpath)
    if not args.json:
        print_inline(os.path.join(rd, "stdout.txt"), args.inline)
    rc = rcp.get("rc")
    return 0 if rc == 0 else (1 if rc is not None else 0)


def bg_scope_meta(bg):
    try:
        with open(bg["diff"]["before_path"], encoding="utf-8") as f:
            return json.load(f)["roots_meta"]
    except OSError:
        return []


def check_wait(args):
    if args.file_exists:
        return os.path.exists(args.file_exists), ("file_exists: %s" % args.file_exists)
    if args.file_gone:
        return not os.path.exists(args.file_gone), ("file_gone: %s" % args.file_gone)
    if args.file_contains:
        p, text = args.file_contains
        try:
            with open(p, "rb") as f:  # S5.5: 读取上限 8MiB，防 GB 级文件×0.3s 轮询
                data = f.read(FC_CAP + 1)
            capped = len(data) > FC_CAP
            ok = text in data[:FC_CAP].decode("utf-8", errors="replace")
            return ok, ("file_contains: %s :: %r%s" % (
                p, text, " (capped 8MiB, 尾部未检)" if capped else ""))
        except OSError as e:
            return False, ("file_contains: 读取失败 %s (%s)" % (p, e.errno))
    if args.port_open is not None:
        try:
            with socket.create_connection((args.host, args.port_open), timeout=1.0):
                return True, ("port_open: %s:%s" % (args.host, args.port_open))
        except OSError as e:
            return False, ("port_open: %s:%s (%s)" % (args.host, args.port_open, e.__class__.__name__))
    return False, "no_predicate"


def cmd_wait(args):
    if args.port_open is not None and args.host not in LOOPBACK_HOSTS:
        # S2: 端口谓词限 loopback 白名单（与宣称语义一致），拒任意 host 外连探测
        print("--port-open 仅允许 loopback host（127.0.0.1/::1/localhost），拒绝 %r" % args.host,
              file=sys.stderr)
        return 2
    cond = {"file_exists": args.file_exists, "file_gone": args.file_gone,
            "file_contains": list(args.file_contains) if args.file_contains else None,
            "port_open": args.port_open, "host": args.host}
    t0 = time.time()
    deadline = t0 + args.timeout
    ok, detail = False, ""
    while True:
        ok, detail = check_wait(args)
        if ok or time.time() >= deadline:
            break
        time.sleep(args.interval)
    waited_ms = round((time.time() - t0) * 1000, 1)
    root = os.path.abspath(args.root or os.getcwd())
    run_id = new_run_id()
    rd = run_dir(root, run_id)
    rcp = {"schema": SCHEMA, "kind": "wait", "run_id": run_id,
           "condition": json.dumps(cond, ensure_ascii=False),
           "satisfied": ok, "waited_ms": waited_ms, "timeout_s": args.timeout,
           "detail": detail, "at": now_iso(), "diff": None,
           "note": "wait 为纯观察动作：不修改世界状态，无 diff；smx 仅读取元数据/探测端口"}
    rpath = os.path.join(rd, "receipt.json")
    with open(rpath, "w", encoding="utf-8") as f:
        json.dump(rcp, f, sort_keys=True, ensure_ascii=False, indent=1)
    emit(rcp, args.json, rpath)
    return 0 if ok else 2


def cmd_show(args):
    root = os.path.abspath(args.root or os.getcwd())
    check_run_id(args.run_id)
    rpath = os.path.join(root, RUNROOT, "runs", args.run_id, "receipt.json")
    with open(rpath, encoding="utf-8") as f:
        rcp = json.load(f)
    emit(rcp, args.json, rpath)
    if not args.json and rcp.get("kind") in ("exec", "collect"):
        print_inline(rcp.get("stdout_path") or os.path.join(root, RUNROOT, "runs", args.run_id, "stdout.txt"),
                     args.inline)
    return 0


def main():
    import sys
    p = argparse.ArgumentParser(prog="smx", description="语义 shell 执行器（R1 PoC）")
    sub = p.add_subparsers(dest="action", required=True)

    def common(sp, with_timeout=False):
        sp.add_argument("--root", default=None, help="scope 根目录（默认 cwd）")
        sp.add_argument("--depth", type=int, default=2, help="快照深度（默认 2，浅层）")
        sp.add_argument("--budget", type=int, default=5000, help="stat 条目预算上限（默认 5000）")
        sp.add_argument("--watch", action="append", default=None, metavar="PATH",
                        help="额外观察路径（可多次）")
        sp.add_argument("--json", action="store_true", help="输出完整回执 JSON")
        if with_timeout:
            sp.add_argument("--timeout", type=float, default=0, help="秒；0=不限时")

    pe = sub.add_parser("exec", help="前台执行 + 前后快照 diff")
    pe.add_argument("cmd", nargs="?", default=None)
    pe.add_argument("--script", metavar="FILE",
                    help="命令从文件读（'-'=stdin），规避多层 shell quoting；与 cmd 互斥")
    pe.add_argument("--inline", type=int, default=0, metavar="N",
                    help="stdout ≤N 行且 ≤64KiB 时内联打印（默认 0=关；仅呈现，不改回执）")
    common(pe, with_timeout=True)

    pb = sub.add_parser("bg", help="后台执行（diff 延迟到 collect）")
    pb.add_argument("cmd", nargs="?", default=None)
    pb.add_argument("--script", metavar="FILE",
                    help="命令从文件读（'-'=stdin），规避多层 shell quoting；与 cmd 互斥")
    common(pb)

    pc = sub.add_parser("collect", help="收尾后台任务：时间窗 diff + 退出码链")
    pc.add_argument("run_id")
    pc.add_argument("--root", default=None)
    pc.add_argument("--json", action="store_true")
    pc.add_argument("--inline", type=int, default=0, metavar="N",
                    help="stdout ≤N 行内联打印（默认 0=关；进程仍运行时不内联）")

    pw = sub.add_parser("wait", help="一等等待动作：条件谓词 + 超时（程序轮询）")
    g = pw.add_mutually_exclusive_group(required=True)
    g.add_argument("--file-exists", metavar="PATH")
    g.add_argument("--file-gone", metavar="PATH")
    g.add_argument("--file-contains", nargs=2, metavar=("PATH", "TEXT"))
    g.add_argument("--port-open", type=int, metavar="PORT")
    pw.add_argument("--host", default="127.0.0.1",
                    help="仅 loopback（127.0.0.1/::1/localhost），其他值拒绝（S2）")
    pw.add_argument("--timeout", type=float, default=10.0)
    pw.add_argument("--interval", type=float, default=0.3)
    pw.add_argument("--root", default=None)
    pw.add_argument("--json", action="store_true")

    ps = sub.add_parser("show", help="重放已存回执")
    ps.add_argument("run_id")
    ps.add_argument("--root", default=None)
    ps.add_argument("--json", action="store_true")
    ps.add_argument("--inline", type=int, default=0, metavar="N",
                    help="重放时 stdout ≤N 行内联打印（默认 0=关；仅 exec/collect 回执）")

    a = p.parse_args()
    fn = {"exec": cmd_exec, "bg": cmd_bg, "collect": cmd_collect,
          "wait": cmd_wait, "show": cmd_show}[a.action]
    sys.exit(fn(a))


if __name__ == "__main__":
    main()
