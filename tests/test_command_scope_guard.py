"""P1-a 命令通道写侧闸的测试（DESIGN-20261030 §16）.

覆盖三层：
1. **判定层**（core/command_scope_guard）：应拦输入必须被拦、放行必须放行、
   已知残余必须显式断言（不假装已拦）。
2. **强制层**（tools/builtin/execute_command）：受限 child 的越权写命令被
   程序级拒绝，且**没有真的执行**。
3. **审计层**（core/write_scope）：未验证路径进 scope_unverified，观测面可见。

2026-10-30 独立审查（REVISE）抓到 P0：首版闸只按 ``argv[0]`` 找写命令，
被 shell 语法绕过（env 前缀、控制流、分组、命令替换、``eval``、``&>``/
``>&``/``>|`` 重定向）。这些绕过逐条落在 ``BLOCKED_CASES`` 里钉住。

门禁自证伪（DESIGN §15.6 教训）：把闸打成空实现后，"应拦输入"用例必须变红——
否则这些用例测的是空转，不是拦截。
"""

from __future__ import annotations

import pytest

from llm_loop.core.command_scope_guard import CommandScopeDecision, check_command_scope
from llm_loop.core.run_context import current_write_scope
from llm_loop.core.write_scope import (
    WriteScope,
    write_scope_audit_reset,
    write_scope_audit_snapshot,
)

WS = "/tmp/llm-p1a-guard-ws"


def _scope(paths=("src/**",), mode="allow", declared=True) -> WriteScope:
    return WriteScope(paths=tuple(paths), mode=mode, declared=declared)


def _check(command: str, scope: WriteScope | None = None, workdir: str = ""):
    return check_command_scope(
        command,
        scope=_scope() if scope is None else scope,
        workspace_root=WS,
        workdir=workdir,
    )


def _tool():
    from llm_loop.tools.builtin.execute_command import ExecuteCommandTool

    return ExecuteCommandTool()


# ── 判定层：应拦输入（RULE-AI-35：每条门禁都要有"应拦输入"实测）───────────

BLOCKED_CASES = [
    ("rm /etc/passwd", "write_target_outside_scope"),
    ("rm -rf /", "write_target_outside_scope"),
    ("rm ../escape.txt", "write_target_outside_scope"),
    ("rm docs/notes.md", "write_target_not_in_allow_list"),
    ("rm $TARGET", "unverifiable_write_target"),
    ("rm *.py", "unverifiable_write_target"),
    ("touch /tmp/x", "write_target_outside_scope"),
    ("echo hi > /tmp/out.txt", "write_target_outside_scope"),
    ("echo hi > ../out.txt", "write_target_outside_scope"),
    ("git commit -m x", "implicit_write_target"),
    ("git add src/x.py", "implicit_write_target"),
    ("xargs rm", "implicit_write_target"),
    ("find . -exec rm {} ;", "unverifiable_write_target"),
    ("sudo rm /etc/x", "write_target_outside_scope"),
    ("sh -c 'rm /etc/x'", "write_target_outside_scope"),
    ("cd /tmp && touch x", "unverifiable_write_target"),
    ("mktemp", "implicit_write_target"),
    # ── shell 语法绕过（独立审查 P0-1/P1-1/P1-2/P1-3 的逐条钉住）────────────
    ("FOO=1 rm /outside/x", "write_target_outside_scope"),
    ("if true; then rm /outside/x; fi", "shell_keyword_construct"),
    ("for i in 1; do rm /outside/x; done", "shell_keyword_construct"),
    ("case x in a) rm /outside/x;; esac", "unmodeled_shell_construct"),
    ("(rm /outside/x)", "unmodeled_shell_construct"),
    ("{ rm /outside/x; }", "unmodeled_shell_construct"),
    ("echo $(rm /outside/x)", "unmodeled_shell_construct"),
    ("eval rm /outside/x", "write_target_outside_scope"),
    ("echo x &> /outside/x", "write_target_outside_scope"),
    ("echo x >& /outside/x", "write_target_outside_scope"),
    ("echo x >| /outside/x", "write_target_outside_scope"),
    ("cp -t /outside src/a.py", "write_target_outside_scope"),
    ("git -C /outside commit -m x", "implicit_write_target"),
    ("git --git-dir=/outside/.git add f", "implicit_write_target"),
    ("find . -name '*.py' -delete", "implicit_write_target"),
    ("find . -fprint /outside/log", "write_target_outside_scope"),
    ("bash -c 'rm /outside/x'", "write_target_outside_scope"),
    ("sh /outside/s.sh", "implicit_write_target"),
    ("cat <<EOF\nrm /outside/x\nEOF", "unmodeled_shell_construct"),
    ("make build", "implicit_write_target"),
    ("pip install x", "implicit_write_target"),
    ("curl -o /outside/x http://h/x", "write_target_outside_scope"),
    ("wget -O /outside/x http://h/x", "write_target_outside_scope"),
    # ── 第二轮独立审查（child subagent_59014ca6ae4f）新指出的绕过向量 ──────
    ("$X", "command_identity_not_literal"),
    ("r{m,} /outside/x", "command_identity_not_literal"),
    ("timeout 10 rm /outside/x", "write_target_outside_scope"),
    ("su -c 'rm /outside/x'", "write_target_outside_scope"),
    ("env -S 'rm /outside/x'", "write_target_outside_scope"),
    ("watch -x rm /outside/x", "write_target_outside_scope"),
    ("find . -exec true {} \\; -delete", "implicit_write_target"),
    (". x.sh", "implicit_write_target"),
    ("source x.sh", "implicit_write_target"),
    ("bash < x.sh", "implicit_write_target"),
    ("rsync --target-directory=/outside src/a.py", "write_target_outside_scope"),
    ("gzip -d /outside/f.gz", "write_target_outside_scope"),
    ("wget http://h/x", "implicit_write_target"),
    ("patch", "implicit_write_target"),
    ("git -c user.name=x commit -m y", "implicit_write_target"),
    ("git archive --output=/outside/x.tar HEAD", "write_target_outside_scope"),
    ("git config --file=/outside/c user.name x", "implicit_write_target"),
    # ── 写工具名单补齐（漏进名单＝漏检：名单外默认按只读放行）────────────────
    ("scp /outside/x src/y", "implicit_write_target"),
    ("perl -i -pe 's/a/b/' /outside/x.py", "write_target_outside_scope"),
    ("7z x archive.7z", "implicit_write_target"),
    ("hg update", "implicit_write_target"),
    ("openssl enc -in a -out /outside/x", "implicit_write_target"),
    ("sqlite3 db.sqlite 'VACUUM'", "implicit_write_target"),
    ("busybox rm /outside/x", "write_target_outside_scope"),
    ("ed /outside/x.py", "write_target_outside_scope"),
    # ── 第三轮独立审查（child subagent_778d47130c3f，候选 46b88717）新向量 ──
    ("cat <(rm /outside/x)", "unmodeled_shell_construct"),
    ("cat >(rm /outside/x)", "unmodeled_shell_construct"),
    ("env -S rm /outside/x", "write_target_outside_scope"),
    ("env --split-string=rm /outside/x", "write_target_outside_scope"),
    ("watch -b rm /outside/x", "write_target_outside_scope"),
    ("watch --beep rm /outside/x", "write_target_outside_scope"),
    ("tar -xf a.tar -C /outside", "write_target_outside_scope"),
    ("tar xf a.tar -C /outside", "write_target_outside_scope"),
    ("tar -xf a.tar", "implicit_write_target"),
    ("sed -i.bak s/a/b/ /outside/f", "write_target_outside_scope"),
    ("sed --in-place=.bak s/a/b/ /outside/f", "write_target_outside_scope"),
    ("sed 'w /outside/x' f", "write_target_outside_scope"),
    ("patch -o /outside/x diff", "write_target_outside_scope"),
    ("zstd -o /outside/x in.zst", "write_target_outside_scope"),
    ("sudo -s", "implicit_write_target"),
    ("sudo -i", "implicit_write_target"),
    ("sudo", "implicit_write_target"),
    ("find . -ok rm {} ;", "unverifiable_write_target"),
    # ── 第四轮独立审查新向量（载体/载荷重解析 + 写族漏列 + 配置注入）──
    ("find . -exec sh -c 'rm /outside/x' ;", "write_target_outside_scope"),
    ("find . -execdir sh -c 'rm /outside/x' ;", "write_target_outside_scope"),
    ("sudo env -S 'rm /outside/x'", "write_target_outside_scope"),
    ("env -S 'rm' /outside/x", "write_target_outside_scope"),
    ("exec -a foo rm /outside/x", "write_target_outside_scope"),
    ("timeout 10 -k 5 rm /outside/x", "write_target_outside_scope"),
    ("timeout -k 5 10 rm /outside/x", "write_target_outside_scope"),
    ("builtin rm /outside/x", "write_target_outside_scope"),
    ("unlink /outside/x", "write_target_outside_scope"),
    ("git -c alias.pwn='!rm /outside/x' pwn", "implicit_write_target"),
    ("git -c core.pager='rm /outside/x' status", "implicit_write_target"),
    ("git --config-env=alias.pwn=EVIL pwn", "implicit_write_target"),
    (
        "GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=alias.pwn "
        "GIT_CONFIG_VALUE_0='!rm /outside/x' git pwn",
        "implicit_write_target",
    ),
    ("time -o /outside/x rm src/x.py", "write_target_outside_scope"),
    ("sort -o /outside/x src/x.py", "write_target_outside_scope"),
    # ── 第四轮独立审查新增向量（2026-10-30）──────────────────────────────
    # 纯写重定向段（无命令）：``> FILE`` / ``2> FILE`` / ``3> FILE``
    ("> /outside/f", "write_target_outside_scope"),
    ("2> /outside/f", "write_target_outside_scope"),
    ("3> /outside/f", "write_target_outside_scope"),
    # sed 脚本来源三形态 + ``s///w`` / ``s///e`` 变体
    ("sed --expression='w /outside/x' in", "write_target_outside_scope"),
    ("sed -f /tmp/evil.sed in", "implicit_write_target"),
    ("sed 's/a/b/w /outside/x' in", "write_target_outside_scope"),
    ("sed 's/a/b/e' in", "implicit_write_target"),
    # ed/ex 的 stdin 脚本（写目标不可静态定位）
    ("ed src/x.py", "implicit_write_target"),
    ("ex -c 'w /outside/x' src/x.py", "write_target_outside_scope"),
    # git 写子命令：封闭名单漏项（remote add / fast-import 曾放行）
    ("git remote add origin /outside/x", "implicit_write_target"),
    ("git fast-import", "implicit_write_target"),
]


def test_blocked_cases_depend_on_the_gate(monkeypatch) -> None:
    """门禁自证伪（DESIGN §15.6）：把判定层打成空实现后，每个应拦输入都必须放行。

    否则这批用例测的是空转（被别的因素挡住），不是拦截——第三轮审查新增 19 条
    向量后，这条自检才真正覆盖到它们。
    """
    import llm_loop.core.command_scope_guard as guard_mod

    monkeypatch.setattr(
        guard_mod._Scanner, "scan", lambda self, command: CommandScopeDecision(True)
    )
    for command, _expected_reason in BLOCKED_CASES:
        decision = guard_mod.check_command_scope(
            command, scope=_scope(), workspace_root=WS
        )
        assert decision.allowed, f"闸被关掉后仍被拦 ⇒ 该用例不是测拦截：{command}"


@pytest.mark.parametrize("command,expected_reason", BLOCKED_CASES)
def test_blocked_write_commands_are_rejected(command: str, expected_reason: str) -> None:
    decision = _check(command)
    assert decision.allowed is False, command
    assert decision.reason == expected_reason, (command, decision.reason, decision.detail)


ALLOWED_CASES = [
    "ls -la",
    "cat src/x.py",
    "git status",
    "git log --oneline -3",
    "pytest -q",
    "rm src/x.py",
    "echo hi > src/out.txt",
    "echo x 2>&1",
    "ls |& grep x",
    "cd src && ls",
    "grep -rn TODO src/",
    "python -c \"print(1)\"",
    # 载体链与写族分类的放行侧（第四轮审查补入）
    "sort src/x.py",
    "env FOO=1 rm src/x.py",
    "timeout 10 rm src/x.py",
    "sudo rm src/x.py",
    "git -c user.name=someone log --oneline",
    # 第四轮审查：git 改为「读白名单放行、其余按写处理」后，
    # 家族内有只读形态的子命令必须仍放行（remote -v / worktree list …）
    "git remote -v",
    "git remote show origin",
    "git worktree list",
    "git diff --stat",
    "git rev-parse HEAD",
]


@pytest.mark.parametrize("command", ALLOWED_CASES)
def test_read_only_and_in_scope_writes_are_allowed(command: str) -> None:
    decision = _check(command)
    assert decision.allowed is True, (command, decision.reason, decision.detail)


def test_write_tool_prefix_rule_blocks_same_family_variants() -> None:
    """写工具按**动词前缀**归类（第四轮审查：逐个罗列名字必然漏项）。

    名单外默认按只读处理是**放行**方向——写工具漏进名单＝漏检。除名单外还有
    前缀规则（rm*/mk*/unlink*），覆盖同类工具及其变体。
    """
    for command in (
        "unlink /outside/x",
        "rmdir /outside/x",
        "mkfifo /outside/x",
        "mknod /outside/x",
        "mkswap /outside/x",
    ):
        decision = _check(command)
        assert decision.allowed is False, command


def test_carrier_option_semantics_do_not_swallow_inner_payload() -> None:
    """内层命令的选项必须由**内层命令自己的语义**解析（第四轮审查 P0-1）。

    ``sudo env -S 'rm x'`` 里的 ``-S`` 是 env 的载荷型选项，不是 sudo 的布尔
    开关——按外层语义吞掉它就会丢掉载荷语义（写命令被漏检）。
    """
    decision = _check("sudo env -S 'rm /outside/x'")
    assert decision.allowed is False, decision
    assert decision.reason == "write_target_outside_scope", decision.reason


def test_git_config_injection_is_treated_as_payload() -> None:
    """git 的配置注入是**可执行载荷**：alias 的 shell 形态与 pager 都要重解析。

    第六轮独立审查 P1-3 起：``alias.*`` / ``core.pager`` 是**可执行载荷**，
    其执行时机与工作目录不可静态确定 ⇒ 一律按 ``implicit_write_target`` 拒
    （不再依赖"载荷的写目标恰好越界"才拦 —— 否则相对路径载荷会漏）。
    """
    for command in (
        "git -c alias.pwn='!rm /outside/x' pwn",
        "git -c core.pager='rm /outside/x' status",
        # 载荷写目标恰在 scope 内（相对路径）也必须拦
        "git -c alias.pwn='!rm -rf ./x' pwn",
    ):
        decision = _check(command)
        assert decision.allowed is False, command
        assert decision.reason == "implicit_write_target", (command, decision.reason)


def test_undeclared_scope_allows_everything() -> None:
    """未受限会话零行为变化：父会话的命令不受本闸影响。"""
    assert check_command_scope("rm /etc/passwd", scope=None, workspace_root=WS).allowed
    undeclared = check_command_scope(
        "rm /etc/passwd", scope=_scope(declared=False), workspace_root=WS
    )
    assert undeclared.allowed is True


def test_explicit_readonly_scope_blocks_every_write() -> None:
    decision = _check("rm src/x.py", scope=_scope(paths=()))
    assert decision.allowed is False
    assert decision.reason == "write_target_not_in_allow_list"


def test_deny_mode_blocks_denied_path() -> None:
    decision = _check("rm src/secret/a.txt", scope=_scope(paths=("src/secret/**",), mode="deny"))
    assert decision.allowed is False
    assert decision.reason == "write_target_denied_by_deny_list"


def test_interpreter_payload_is_documented_residual() -> None:
    """解释器任意代码是 P1-a 的已知残余——显式断言，不假装已拦。

    P1-b（剔除整个命令工具）能挡住这一条；P1-a 选了灵活性，故残余必须被写进
    文档并被测试钉住，而不是靠"闸应该能挡住"的误解。
    """
    decision = _check("python -c \"open('/etc/x','w')\"")
    assert decision.allowed is True


def test_read_side_out_of_scope_literal_is_audited_not_blocked() -> None:
    decision = _check("cat /etc/passwd")
    assert decision.allowed is True
    assert any("/etc/passwd" in path for path, _reason in decision.unverified)


def test_explicit_relative_out_of_scope_is_audited() -> None:
    decision = _check("cat ../../etc/passwd")
    assert decision.allowed is True
    assert any("../../etc/passwd" in path for path, _reason in decision.unverified)


def test_unverified_entries_carry_reason() -> None:
    """审计条目必须自带原因（不得把原因塞进 path 字段——P2-3 卫生）。"""
    decision = _check("cat /etc/passwd")
    assert decision.unverified
    for path, reason in decision.unverified:
        assert isinstance(path, str) and path
        assert isinstance(reason, str) and reason
        assert "scope_unverified" not in reason


def test_shell_interpreter_c_payload_is_parsed_not_trusted() -> None:
    """``sh -c 'rm /outside/x'``：载荷必须重解析，不能只信 argv[0]。"""
    decision = _check("sh -c 'rm /outside/x'")
    assert decision.allowed is False
    assert decision.reason == "write_target_outside_scope"


def test_shell_interpreter_read_payload_is_allowed_and_audited() -> None:
    decision = _check("sh -c 'cat /etc/passwd'")
    assert decision.allowed is True
    assert any("/etc/passwd" in path for path, _reason in decision.unverified)


def test_git_read_subcommand_with_global_flag_is_allowed() -> None:
    """git 全局选项（-C/--git-dir）不得让读子命令被误判成写子命令。"""
    decision = _check("git -C /outside status")
    assert decision.allowed is True, (decision.reason, decision.detail)


def test_fd_duplicate_is_not_treated_as_write_target() -> None:
    """``2>&1`` 是 fd 复制，不是写目标（首版把 >& 当成未知写法而漏判）。"""
    decision = _check("echo x 2>&1")
    assert decision.allowed is True
    assert not decision.unverified


def test_env_prefix_assignment_is_stripped_before_classification() -> None:
    decision = _check("FOO=1 rm src/x.py")
    assert decision.allowed is True, (decision.reason, decision.detail)


def test_eval_payload_is_parsed() -> None:
    decision = _check("eval 'rm /outside/x'")
    assert decision.allowed is False
    assert decision.reason == "write_target_outside_scope"


def test_unparsable_command_is_rejected_fail_closed() -> None:
    decision = _check("echo 'unclosed")
    assert decision.allowed is False
    assert decision.reason == "unparsable_command"


# ── 强制层：受限 child 的越权写命令被程序级拒绝，且没有真的执行 ────────────


def test_restricted_child_out_of_scope_write_is_rejected_and_not_executed(tmp_path) -> None:
    victim = tmp_path / "victim.txt"
    victim.write_text("x", encoding="utf-8")
    tool = _tool()
    scope = WriteScope(paths=("src/**",), mode="allow", declared=True)
    token = current_write_scope.set(scope)
    try:
        result = tool.execute(command=f"rm {victim}")
    finally:
        current_write_scope.reset(token)
    assert result.error_type == "write_scope_violation", result.content
    assert victim.exists(), "被拒的命令不得真的执行"


def test_restricted_child_shell_bypass_is_rejected_and_not_executed(tmp_path) -> None:
    """绕过形态在强制层同样必须被拒（否则判定层与强制层脱节）。"""
    victim = tmp_path / "victim.txt"
    victim.write_text("x", encoding="utf-8")
    tool = _tool()
    scope = WriteScope(paths=("src/**",), mode="allow", declared=True)
    token = current_write_scope.set(scope)
    try:
        result = tool.execute(command=f"FOO=1 rm {victim}")
    finally:
        current_write_scope.reset(token)
    assert result.error_type == "write_scope_violation", result.content
    assert victim.exists(), "被拒的命令不得真的执行"


def test_restricted_child_read_only_command_is_not_blocked() -> None:
    tool = _tool()
    scope = WriteScope(paths=("src/**",), mode="allow", declared=True)
    token = current_write_scope.set(scope)
    try:
        result = tool.execute(command="echo hello-p1a")
    finally:
        current_write_scope.reset(token)
    assert result.error_type != "write_scope_violation"
    assert "hello-p1a" in (result.content or "")


def test_unrestricted_session_command_behavior_unchanged() -> None:
    tool = _tool()
    result = tool.execute(command="echo hello-unrestricted")
    assert result.error_type != "write_scope_violation"
    assert "hello-unrestricted" in (result.content or "")


def test_self_falsification_disabled_gate_actually_executes_write(tmp_path, monkeypatch) -> None:
    """门禁自证伪：闸被关掉后命令应**真的执行**。

    否则"应拦输入"用例测的是空转——这正是 DESIGN §15.6 记录的门禁自欺形态。
    """
    import llm_loop.tools.builtin.execute_command as ec_mod

    victim = tmp_path / "victim.txt"
    victim.write_text("x", encoding="utf-8")
    monkeypatch.setattr(
        ec_mod, "check_command_scope", lambda *a, **k: CommandScopeDecision(True)
    )
    tool = _tool()
    scope = WriteScope(paths=("src/**",), mode="allow", declared=True)
    token = current_write_scope.set(scope)
    try:
        tool.execute(command=f"rm {victim}")
    finally:
        current_write_scope.reset(token)
    assert not victim.exists(), "闸关掉后写命令应真的发生（否则应拦用例测的是空转）"


# ── 审计层：未验证路径进 scope_unverified ──────────────────────────────────


def test_scope_unverified_is_recorded_in_audit_snapshot() -> None:
    write_scope_audit_reset()
    tool = _tool()
    scope = WriteScope(paths=("src/**",), mode="allow", declared=True)
    token = current_write_scope.set(scope)
    try:
        tool.execute(command="cat /etc/passwd")
    finally:
        current_write_scope.reset(token)
    snapshot = write_scope_audit_snapshot()
    assert snapshot["scope_unverified_count"] >= 1
    assert any("/etc/passwd" in item["path"] for item in snapshot["scope_unverified"])
    write_scope_audit_reset()


def test_rejected_command_does_not_record_unverified_audit() -> None:
    """被拒的命令不应留下"已放行"语义的审计痕迹（P2-3 卫生）。"""
    write_scope_audit_reset()
    tool = _tool()
    scope = WriteScope(paths=("src/**",), mode="allow", declared=True)
    token = current_write_scope.set(scope)
    try:
        result = tool.execute(command="cat /etc/passwd && rm /outside/x")
    finally:
        current_write_scope.reset(token)
    assert result.error_type == "write_scope_violation"
    snapshot = write_scope_audit_snapshot()
    assert snapshot["scope_unverified_count"] == 0, snapshot
    write_scope_audit_reset()


def test_audit_is_capped_and_dropped_entries_are_counted() -> None:
    """P2-4：进程内审计有上限，超限条目**计数丢弃**（不静默、不无界增长）。"""
    from llm_loop.core.write_scope import (
        _AUDIT_MAX_ENTRIES,
        write_scope_audit_record_unverified,
    )

    write_scope_audit_reset()
    overflow = 10
    for index in range(_AUDIT_MAX_ENTRIES + overflow):
        write_scope_audit_record_unverified(f"/outside/{index}", "scope_unverified")
    snapshot = write_scope_audit_snapshot()
    assert snapshot["scope_unverified_count"] == _AUDIT_MAX_ENTRIES, snapshot
    assert snapshot["audit_dropped_count"] == overflow, snapshot
    write_scope_audit_reset()


# ── 第五轮独立审查（REVISE：P0=4 / P1=4 / P2=3）回归锁 ────────────────────
#
# 判定基准：**全域 scope**（paths=("**",)）。此前用受限 scope 时，
# 这些向量虽被拒，但拒的是错误的原因（拒了操作数而非真实写目标），
# 换到真实越界路径就放行 ⇒ 必须以全域 scope 断言"必须被拒"。

R5_BLOCKED_CASES = [
    # P0-1：载体携带的赋值（env GIT_CONFIG_* 注入可执行 alias）
    (
        "env GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=alias.pwn "
        "GIT_CONFIG_VALUE_0='!rm -rf /outside' git log",
        "implicit_write_target",
    ),
    # P0-2：find -fprint0 与 -fprint 同族（落盘）
    ("find . -fprint0 /outside/x", "write_target_outside_scope"),
    # P0-3：perl 聚集形态就地编辑（-pi / -pie / -i.bak）
    ("perl -pi -e 's/a/b/' /outside/x", "write_target_outside_scope"),
    ("perl -pie -e 's/a/b/' /outside/x", "write_target_outside_scope"),
    # P0-4：tar 创建模式的归档文件才是写目标
    ("tar -c --file=/outside/x.tar a", "write_target_outside_scope"),
    ("tar cf /outside/x.tar a", "write_target_outside_scope"),
    # P1-1：env -C / sudo -D 换目录后相对写目标不可再按原 cwd 解析
    ("env -C /outside touch x", "unverifiable_write_target"),
    ("sudo -D /outside touch x", "unverifiable_write_target"),
    # P1-2：ln -t 是 --target-directory（链接建到 DIR 下）
    ("ln -t /outside a", "write_target_outside_scope"),
    # P1-3：curl --remote-name-all 与 -O/--remote-name 同族
    ("curl --remote-name-all https://example.com/x", "implicit_write_target"),
    # P1-4：git symbolic-ref 写形态（改写 .git/HEAD）
    ("git symbolic-ref HEAD refs/heads/x", "implicit_write_target"),
    # P2-1：同形载体/工具仍漏建模
    ("script /outside/log rm /outside/x", "write_target_outside_scope"),
    ("fish -c 'rm /outside/x'", "write_target_outside_scope"),
    ("gcc -o /outside/x a.c", "write_target_outside_scope"),
]


@pytest.mark.parametrize("command,expected_reason", R5_BLOCKED_CASES)
def test_r5_review_bypasses_are_blocked_under_full_domain_scope(
    command: str, expected_reason: str
) -> None:
    """第五轮审查复现向量：全域 scope 下必须被拒（拒因须正确）。"""
    decision = _check(command, scope=_scope(paths=("**",)))
    assert decision.allowed is False, (command, decision.reason, decision.detail)
    assert decision.reason == expected_reason, (command, decision.reason, decision.detail)


@pytest.mark.parametrize(
    "command",
    [
        # P1-4 的**读形态**仍须放行：只有 1 个位置参数 = 读当前 symbolic ref
        "git symbolic-ref HEAD",
        # P0-4 的解包形态（不是创建）仍按解包判定：解包到 cwd 时写目标
        # 不可静态定位 ⇒ 拒（既有口径，本轮未改）；指定 -C 后目标可定位 ⇒ 放行
        "tar -xf a.tar -C src",
        # P2-1：gcc 无 -o 时不产出指定输出文件（仍按编译器默认处理）
        "gcc --version",
        # P1-1：env -C 不带写命令时不误伤读命令
        "env -C src ls",
    ],
)
def test_r5_review_fixes_do_not_over_block_read_forms(command: str) -> None:
    decision = _check(command, scope=_scope(paths=("**",)))
    assert decision.allowed is True, (command, decision.reason, decision.detail)


# ── 第六轮独立审查（REVISE：P0=0 / P1=3 / P2=5）回归锁 ──────────────────────
#
# P1-1：tar 的**粘连短选项簇**（``-cvf`` / ``-czf``）里的 f 也是归档路径 ——
#   `_flag_value` 是 token 精确匹配，认不出粘连簇 ⇒ 曾取错操作数而放行越界归档写。
# P1-2：``script -c CMD`` 的载荷由**选项**携带（此前只按 ``script FILE cmd…`` 取
#   cmd_tokens[2:] ⇒ ``-c`` 形态的 CMD 被整体漏扫）。
# P1-3：``git -c alias.*=…`` 是**可执行 alias**：载荷写目标恰在 scope 内
#   （相对路径）时也不得放行 —— 执行时机与工作目录不可静态确定。
# P2-1/P2-2：载体选项区（命令名之前）与内层命令的操作数必须分开看 ——
#   ``env grep -C 2 pat`` 的 ``-C`` 是 grep 的上下文行数，不是 env 的 chdir；
#   ``env ls GIT_CONFIG_COUNT=1`` 里那是 ls 的参数，不是 env 的环境变量赋值。

R6_BLOCKED_CASES = [
    ("tar -cvf /outside/x.tar a", "write_target_outside_scope"),
    ("tar -czf /outside/x.tar.gz a", "write_target_outside_scope"),
    ("script -c 'rm /outside/x' log", "write_target_outside_scope"),
    ("script -c 'rm /outside/x'", "write_target_outside_scope"),
    ("git -c alias.log='!rm -rf ./x' log", "implicit_write_target"),
    ("git -c 'alias.log=!rm -rf ./x' log", "implicit_write_target"),
    ("git -c core.pager='sh -c \"rm -rf ./x\"' log", "implicit_write_target"),
]


@pytest.mark.parametrize("command,expected_reason", R6_BLOCKED_CASES)
def test_r6_review_bypasses_are_blocked_under_full_domain_scope(
    command: str, expected_reason: str
) -> None:
    """第六轮审查复现向量：全域 scope 下必须被拦（拒因须正确）。"""
    decision = _check(command, scope=_scope(paths=("**",)))
    assert decision.allowed is False, (command, decision.reason, decision.detail)
    assert decision.reason == expected_reason, (command, decision.reason, decision.detail)


@pytest.mark.parametrize(
    "command",
    [
        # P2-1：env 的 -C 只能取**载体自身选项区**；内层 grep 的 -C 不是 env 的
        "env grep -C 2 pat",
        # P2-2：内层命令的操作数不是 env 的环境变量赋值
        "env ls GIT_CONFIG_COUNT=1",
        # P2-3：perl 把 -version 当长选项名（不是开关簇）⇒ 不是就地编辑
        "perl -version",
        "perl -Mstrict -e 'print 1'",
        # P2-4：git reflog / fast-export 是真只读（写形态由动作分族拦）
        "git reflog",
        "git reflog show",
        "git fast-export --all",
    ],
)
def test_r6_review_fixes_do_not_over_block_read_forms(command: str) -> None:
    decision = _check(command, scope=_scope(paths=("**",)))
    assert decision.allowed is True, (command, decision.reason, decision.detail)


@pytest.mark.parametrize(
    "command",
    [
        # P2-4：reflog 的写形态仍须拦（expire / delete 改写 reflog 文件）
        "git reflog expire --all",
        "git reflog delete HEAD@{1}",
    ],
)
def test_r6_git_reflog_write_forms_are_blocked(command: str) -> None:
    decision = _check(command, scope=_scope(paths=("**",)))
    assert decision.allowed is False, (command, decision.reason, decision.detail)
    assert decision.reason == "implicit_write_target", (command, decision.reason)


# ── 第七轮独立审查（REVISE：P0=0 / P1=4 / P2=3）回归锁 ──────────────────────
#
# P1-1：选项识别只做 **token 精确匹配** ⇒ 漏掉 getopt 的两种形态：
#   - **粘连簇**：``sed -nf`` / ``-ne`` / ``-nfe``（``-n`` 开关 + ``-f``/``-e`` 取值）、
#     ``curl -sSo``（``-s``/``-S`` 开关 + ``-o`` 取值）；
#   - **长选项唯一前缀缩写**：``--fi``（= ``--file``）/ ``--expressio=``、
#     ``--extrac``（= ``--extract``）/ ``--remote-name-a``（= ``--remote-name-all``）。
#   ⇒ 改走族模型（``llm_loop.core.command_options``）按 getopt 语义解析。
# P1-2：``script -c CMD FILE`` 的 **FILE 是 typescript 写目标** —— 此前在 ``-c``
#   分支提前 return ⇒ FILE 从未被判定（无 FILE 时 GNU script 写 ``./typescript``）。
# P1-3：``_perl_inplace`` 的**簇长上限 3** ⇒ 漏掉 ``perl -lpie`` / ``-pain`` 聚集形态
#   （perl 的短开关可任意聚集）。
# P1-4：``git fast-export --export-marks=FILE`` 写 marks 文件 ⇒ 写目标须过 scope 判定。

R7_BLOCKED_CASES = [
    ("sed -nf /tmp/evil.sed in", "implicit_write_target"),
    ("sed -e 's/a/b/' -ne 'w /outside/x' in", "write_target_outside_scope"),
    ("sed --fi /tmp/evil.sed in", "implicit_write_target"),
    ("sed --expressio='w /outside/x' in", "write_target_outside_scope"),
    ("tar --extrac -f /tmp/a.tar", "implicit_write_target"),
    ("curl --remote-name-a https://example.com/x", "implicit_write_target"),
    ("script -c 'true' /outside/leak.log", "write_target_outside_scope"),
    ("perl -lpie 's/a/b/' /outside/x", "write_target_outside_scope"),
    ("perl -pain -e 's/a/b/' /outside/x", "write_target_outside_scope"),
    ("perl -f -i /outside/x", "implicit_write_target"),
    ("git fast-export --export-marks=/outside/marks --all", "write_target_outside_scope"),
]


@pytest.mark.parametrize("command,expected_reason", R7_BLOCKED_CASES)
def test_r7_review_bypasses_are_blocked_under_full_domain_scope(
    command: str, expected_reason: str
) -> None:
    """第七轮审查复现向量：全域 scope 下必须被拦（拒因须正确）。"""
    decision = _check(command, scope=_scope(paths=("**",)))
    assert decision.allowed is False, (command, decision.reason, decision.detail)
    assert decision.reason == expected_reason, (command, decision.reason, decision.detail)


R7_ALLOWED_CASES = [
    "sed -n 's/a/b/' in",
    "sed --quiet 's/a/b/' in",
    "sed 's/a/b/' in",
    "perl -version",
    "perl -e 'print 1'",
    "perl -Mstrict -e 'print 1'",
    "curl https://example.com/x",
    "git fast-export --all",
]


@pytest.mark.parametrize("command", R7_ALLOWED_CASES)
def test_r7_review_fixes_do_not_over_block_read_forms(command: str) -> None:
    """第七轮修复不得误伤读形态（族模型不能把读命令判成写）。"""
    decision = _check(command, scope=_scope(paths=("**",)))
    assert decision.allowed is True, (command, decision.reason, decision.detail)


# ── 第七轮 P2-2（推闸审查）：载体选项区启发式此前**无测试** ⇒ 补回归锁 ──────
#
# 载体（env / sudo / nice …）的"选项区" = 载体自身选项 + 赋值前缀；判定据此决定
# ① cwd 是否不可静态定位（env -C / sudo -D）② 是否含被禁的赋值注入
# （``GIT_CONFIG_COUNT=1`` 之类）。此前这两条启发式**没有任何测试** ⇒ 行为漂移不可见。
# 第七轮自审另发现：cwd 变更判定只做**精确匹配** ⇒ ``env --chdir=/outside touch x``
# 的 cwd 变化未被识别 ⇒ 相对写目标 ``x`` 仍按原 cwd 判定为工作区内 ⇒ **越界写放行**
# ⇒ 补齐 ``--opt=DIR`` 与短选项粘连形态（``-C/outside``）。

R7_CARRIER_OPTION_ZONE_CASES = [
    # 内层的 ``-C`` 属于内层命令（grep），不属于 env ⇒ 不得误判
    ("env grep -C 2 pat file", True, ""),
    ("env FOO=1 ls /tmp", True, ""),
    # cwd 不可静态定位 ⇒ 相对写目标不可判定 ⇒ 拦
    ("env -C /outside touch x", False, "unverifiable_write_target"),
    ("env --chdir /outside touch x", False, "unverifiable_write_target"),
    ("env --chdir=/outside touch x", False, "unverifiable_write_target"),
    ("env -C/outside touch x", False, "unverifiable_write_target"),
    # 被禁的赋值注入（GIT_* 会被内层 git 读取）⇒ 拦（fail-closed 可用性代价）
    ("env GIT_CONFIG_COUNT=1 ls git", False, "implicit_write_target"),
]


@pytest.mark.parametrize("command,expected_allowed,expected_reason", R7_CARRIER_OPTION_ZONE_CASES)
def test_r7_carrier_option_zone_heuristics(
    command: str, expected_allowed: bool, expected_reason: str
) -> None:
    """载体选项区启发式（cwd 变更 / 赋值注入）必须有测试钉住。"""
    decision = _check(command, scope=_scope(paths=("**",)))
    assert decision.allowed is expected_allowed, (command, decision.reason, decision.detail)
    if expected_reason:
        assert decision.reason == expected_reason, (command, decision.reason, decision.detail)


# ── 第八轮独立审查（REVISE，P0=0/P1=5/P2=5）逐条修的回归锁 ─────────────────
#
# P1-1 ``sed -i -f FILE`` 回归：``-i`` 分支早退 ⇒ 绕过了 ``-f`` 的 fail-closed。
# P1-2 tar：``-g`` 快照文件是写目标；模式未知（簇截断/取值吞字母）必须 fail-closed；
#        ``-F/--info-script`` 会执行脚本 ⇒ fail-closed。
# P1-3 script：``-t/--log-timing``、``--log-in/--log-io/--log-out`` 等日志文件是写目标。
# P1-4 sed/ed 脚本语法：换行分隔的 ``w FILE``、独立 ``e CMD``、ex 竖线链。
# P1-5 wget/curl：``-a/--append-output`` 是写目标；**未识别选项一律 fail-closed**
#        （curl/wget/tar/script 与 sed/perl 统一口径）。

R8_BLOCKED_CASES = [
    # P1-1：``-i`` 早退曾让 ``-f`` 的 fail-closed 失效
    ("sed -i -f /tmp/evil.sed in", "implicit_write_target"),
    # P1-2：tar 家族
    ("tar -g /outside/snap -cf a.tar d", "write_target_outside_scope"),
    ("tar -Zxf a.tar", "implicit_write_target"),
    ("tar -Qxf a.tar", "implicit_write_target"),
    ("tar -F /tmp/evil.sh -cf a.tar d", "implicit_write_target"),
    # P1-3：script 的日志/计时文件
    ("script --log-in /outside/x", "write_target_outside_scope"),
    ("script -t /outside/timing.log cmd", "write_target_outside_scope"),
    # P1-4：sed/ed 脚本语法
    ("sed -e 's/a/b/\nw /outside/x' in", "write_target_outside_scope"),
    ("sed -e 'e rm -rf /tmp/x' in", "implicit_write_target"),
    ("ed -c '%s/a/b/|w /outside/x|q' in", "write_target_outside_scope"),
    # P1-5：wget/curl 残差 + 未识别选项统一 fail-closed
    ("wget -a /outside/log https://example.com/x", "write_target_outside_scope"),
    ("curl --totally-unknown https://example.com/x", "implicit_write_target"),
    ("tar --totally-unknown -cf a.tar d", "implicit_write_target"),
]


@pytest.mark.parametrize("command,expected_reason", R8_BLOCKED_CASES)
def test_r8_review_bypasses_are_blocked_under_full_domain_scope(
    command: str, expected_reason: str
) -> None:
    """第八轮审查复现向量：全域 scope 下必须被拦（拒因须正确）。"""
    decision = _check(command, scope=_scope(paths=("**",)))
    assert decision.allowed is False, (command, decision.reason, decision.detail)
    assert decision.reason == expected_reason, (command, decision.reason, decision.detail)


R8_ALLOWED_CASES = [
    "sed -n 's/a/b/' in",
    "sed -e 's/a/b/g' in",
    "sed 's/a/b/' in",
    "curl -sSL https://example.com/x",
    "curl --compressed -o out.txt https://example.com/x",
    "wget -O out.txt https://example.com/x",
    "tar -tf a.tar",
    "tar -cf a.tar b",
    "script -q cmd",
    "perl -e 'print 1'",
    "perl -Mstrict -e 'print 1'",
]


@pytest.mark.parametrize("command", R8_ALLOWED_CASES)
def test_r8_review_fixes_do_not_over_block_read_forms(command: str) -> None:
    """第八轮修复不得误伤读形态（族模型不能把读命令判成写）。"""
    decision = _check(command, scope=_scope(paths=("**",)))
    assert decision.allowed is True, (command, decision.reason, decision.detail)


# ── 第八轮 P2-3：长选项**前缀歧义**时的取值候选优先规则边界 ──────────────────
#
# 规则：长选项前缀匹配到多个候选时，只要**任一候选取值**且写法不是 ``--name=value``，
# 下一个 token 就被当作该选项的值消费（getopt 保守取法）⇒ 副作用是「操作数被吞成
# 值」。方向是**过拦**（fail-closed），但必须钉住，否则规则漂移不可见。

R8_PREFIX_AMBIGUITY_CASES = [
    # ``--outp`` 同时前缀匹配 --output/--output-dir（都取值）⇒ 下一个 token 被消费成值
    ("curl --outp out.txt https://example.com/x", True),
    # 同上，但被吞掉的 token 落在 scope 外 ⇒ 写目标越界 ⇒ 拦
    ("curl --outp /outside/out.txt https://example.com/x", False),
]


@pytest.mark.parametrize("command,expected_allowed", R8_PREFIX_AMBIGUITY_CASES)
def test_r8_prefix_ambiguity_value_candidate_priority(
    command: str, expected_allowed: bool
) -> None:
    """前缀歧义长选项的取值候选优先规则（过拦方向）必须被钉住。"""
    decision = _check(command, scope=_scope(paths=("**",)))
    assert decision.allowed is expected_allowed, (command, decision.reason, decision.detail)


# ── 第九轮独立审查（REVISE，P0=0/P1=4/P2=6）逐条修的回归锁 ─────────────────
#
# P1-1 getopt **附着形态**（``-tDIR`` / ``-oFILE`` / ``-dDIR``）此前走
#      ``_flag_value``（token 精确匹配）⇒ 越界写被放行。
# P1-2 sed 未闭合的 ``s`` 命令此前 ``break`` ⇒ 脚本后半段整体不再扫描。
# P1-3 大写 ``W``（sed 写模式空间首行 / ex 追加写）此前未建模。
# P1-4 ``GIT_CONFIG_PARAMETERS`` 此前未纳入注入拦截。
# P2-3 载荷命令串引号不闭合此前会抛 ValueError（判定崩掉）⇒ 改为 fail-closed。
# 自审新发现（第九轮）：``FamilyOptions.short_spec`` 查表用裸字母、表里登记成
#      ``"-o"`` ⇒ 比较恒不成立 ⇒ **所有短选项都被当成未知字母** ⇒ 取值型选项
#      取不到值（附着形态判不出来）+ 每个短选项都触发 ``unresolved``。

R9_BLOCKED_CASES = [
    # P1-1：附着形态
    ("cp -t/outside src", "write_target_outside_scope"),
    ("gcc -o/outside/x a.c", "write_target_outside_scope"),
    ("sort -o/outside/x in", "write_target_outside_scope"),
    ("patch -o/outside/x a.patch", "write_target_outside_scope"),
    ("unzip -d/outside a.zip", "write_target_outside_scope"),
    ("gzip -o/outside/x in", "write_target_outside_scope"),
    ("time -o/outside/x ls", "write_target_outside_scope"),
    ("git archive -o/outside/x HEAD", "write_target_outside_scope"),
    # P1-2：未闭合的 s 不再中断整段扫描
    ("sed -e 's/a/b\nw /outside/x' in", "write_target_outside_scope"),
    # P1-3：大写 W
    ("sed 'W /outside/x' in", "write_target_outside_scope"),
    ("ed -c 'W /outside/x' in", "write_target_outside_scope"),
    # P1-4：GIT_CONFIG_PARAMETERS
    (
        "GIT_CONFIG_PARAMETERS='alias.pwn=!rm -rf /outside' git log",
        "implicit_write_target",
    ),
    # P2-3：载荷串引号不闭合 ⇒ fail-closed（不再抛 ValueError）
    ("script -c 'echo \"unclosed' out.txt", "implicit_write_target"),
]


@pytest.mark.parametrize("command,expected_reason", R9_BLOCKED_CASES)
def test_r9_review_bypasses_are_blocked_under_full_domain_scope(
    command: str, expected_reason: str
) -> None:
    """第九轮审查复现向量：全域 scope 下必须被拦（拒因须正确）。"""
    decision = _check(command, scope=_scope(paths=("**",)))
    assert decision.allowed is False, (command, decision.reason, decision.detail)
    assert decision.reason == expected_reason, (command, decision.reason, decision.detail)


R9_ALLOWED_CASES = [
    "sort -o out.txt in",
    "gzip in",
    "unzip -d outdir a.zip",
    "sed -n 's/a/b/' in",
    "patch -o out.txt a.patch",
    "git reflog",
    "git symbolic-ref HEAD",
    "git remote -v",
    "gcc --version",
]


@pytest.mark.parametrize("command", R9_ALLOWED_CASES)
def test_r9_review_fixes_do_not_over_block_read_forms(command: str) -> None:
    """第九轮修复不得误伤读形态（含 short_spec 修复带回的 4 条既有读形态）。"""
    decision = _check(command, scope=_scope(paths=("**",)))
    assert decision.allowed is True, (command, decision.reason, decision.detail)


# ── 第十轮独立审查（REVISE，P0=0/P1=2/P2=4）逐条修的回归锁 ─────────────────
#
# P1-1 ed/ex 内联脚本的写/执行形态不全：只认 ``w FILE`` ⇒ 漏 ``w! FILE`` /
#      ``w >> FILE`` / ``save FILE`` / ``saveas FILE``；且把 ``w !CMD``（管道给
#      shell）当成相对文件名 ⇒ 落在 scope 内 ⇒ 放行。
# P1-2 sed 独立 ``e`` 命令的**分隔符**形态（``e;`` / ``e}`` / ``e``+换行）漏检。
# P2-4 CARRIER_SPECS["script"] 把 ``-f/--flush`` 列成取值型 ⇒ 与 SCRIPT_OPTIONS
#      自相矛盾 ⇒ ``script -f out.txt cmd`` 的 typescript 目标被吞。

R10_BLOCKED_CASES = [
    ("ex -c 'w! /outside/x' src/x.py", "write_target_outside_scope"),
    ("ex -c 'w >> /outside/x' src/x.py", "write_target_outside_scope"),
    ("ex -c 'save /outside/x' src/x.py", "write_target_outside_scope"),
    ("ex -c 'saveas /outside/x' src/x.py", "write_target_outside_scope"),
    ("ed -c 'w !rm -rf /outside/x' f", "implicit_write_target"),
    ("ex -c 'r !rm -rf /outside/x' f", "implicit_write_target"),
    ("ex -c 'e rm -rf /outside/x' f", "implicit_write_target"),
    ("sed 'e;' in", "implicit_write_target"),
    ("sed 'e;w /outside/x' in", "implicit_write_target"),
]


@pytest.mark.parametrize("command,expected_reason", R10_BLOCKED_CASES)
def test_r10_review_bypasses_are_blocked_under_full_domain_scope(
    command: str, expected_reason: str
) -> None:
    """第十轮审查复现向量：全域 scope 下必须被拦（拒因须正确）。"""
    decision = _check(command, scope=_scope(paths=("**",)))
    assert decision.allowed is False, (command, decision.reason, decision.detail)
    assert decision.reason == expected_reason, (command, decision.reason, decision.detail)


R10_ALLOWED_CASES = [
    "ed -c 'w out.txt' f",
    "ex -c 'wq' f",
    "sed 'p' in",
]


@pytest.mark.parametrize("command", R10_ALLOWED_CASES)
def test_r10_review_fixes_do_not_over_block_read_forms(command: str) -> None:
    """第十轮修复不得误伤：``w`` 写相对文件 / ``wq``（写并退出）/ 普通 sed。"""
    decision = _check(command, scope=_scope(paths=("**",)))
    assert decision.allowed is True, (command, decision.reason, decision.detail)


# ── 第十一轮独立审查（REVISE，P0=0/P1=1/P2=4）逐条修的回归锁 ────────────────
#
# P1-1 ed/ex 内联脚本仍漏**多字母写命令**（``wq`` / ``wn`` / ``wa`` / ``wall`` /
#      ``x`` / ``xit`` / ``xall``）与 ``+cmd`` **启动通道**（``ex +'w …' f``）；
#      且「未建模的命令词」此前静默放行 ⇒ 越界写逃逸。
# P2-1 tar 的 ``-I/--use-compress-program`` 是**执行载荷**，口径必须与
#      ``-F/--info-script`` 一致（fail-closed）。
# P2-2 ``script`` 无 FILE 时写当前目录的 ``typescript`` ⇒ 默认写目标未判定。
# P2-3 ``GIT_REMOTE_READ_ACTIONS`` 里的 ``-v/--verbose`` 是死条目（已删）。

R11_BLOCKED_CASES = [
    ("ex -c 'wq /outside/x' src/x.py", "write_target_outside_scope"),
    ("ex -c 'wn /outside/x' src/x.py", "write_target_outside_scope"),
    ("ex -c 'x /outside/x' src/x.py", "write_target_outside_scope"),
    ("ex -c 'wall /outside/x' src/x.py", "write_target_outside_scope"),
    ("ex +'w /outside/x' src/x.py", "write_target_outside_scope"),
    ("ex -c 'nosuchcmd' src/x.py", "implicit_write_target"),
    ("ex -c 'sh rm -rf /outside/x' src/x.py", "implicit_write_target"),
    ("tar -I /outside/prog -cf a.tar f", "implicit_write_target"),
    ("tar --use-compress-program=/outside/prog -cf a.tar f", "implicit_write_target"),
]


@pytest.mark.parametrize("command,expected_reason", R11_BLOCKED_CASES)
def test_r11_review_bypasses_are_blocked_under_full_domain_scope(
    command: str, expected_reason: str
) -> None:
    """第十一轮审查复现向量：全域 scope 下必须被拦（拒因须正确）。"""
    decision = _check(command, scope=_scope(paths=("**",)))
    assert decision.allowed is False, (command, decision.reason, decision.detail)
    assert decision.reason == expected_reason, (command, decision.reason, decision.detail)


R11_ALLOWED_CASES = [
    "ex -c 'wq' src/x.py",
    "ex -c 'p' src/x.py",
    "ex -c '1,2d' src/x.py",
]


@pytest.mark.parametrize("command", R11_ALLOWED_CASES)
def test_r11_review_fixes_do_not_over_block_read_forms(command: str) -> None:
    """第十一轮修复不得误伤：``wq``（写回原文件）/ 打印 / 缓冲区删除。"""
    decision = _check(command, scope=_scope(paths=("**",)))
    assert decision.allowed is True, (command, decision.reason, decision.detail)
