"""Frozen EEv2.2 held-out tasks.

The portability family is intentionally the same workload as EEv2.1 for paired
cross-model replication.  The wrong-tool family is new and does not name the desired
tool in the prompt.  Edit-control pre-registers one neutral locator side-step before
the decisive snapshot read.
"""

from __future__ import annotations

ARMS_V0_2 = ("A-current", "B-portability-contract")
REPEATS_V0_2 = (1, 2, 3)


def _task(
    tid: str,
    family: str,
    prompt: str,
    setup: str,
    verify: str,
    *,
    first_tools: list[str],
    decision_tools: list[str],
    decision_args: dict | None = None,
    neutral_prefix_tools: list[str] | None = None,
    neutral_prefix_max: int = 0,
    source_task_id: str | None = None,
    timeout_s: int = 180,
) -> dict:
    return {
        "id": tid,
        "family": family,
        "prompt": prompt,
        "setup": setup,
        "verify": verify,
        "timeout_s": timeout_s,
        "first_tools": first_tools,
        "expected_failures": [],
        "effect_probe": None,
        "source_task_id": source_task_id,
        "decision_acceptable_tools_v22": decision_tools,
        "decision_required_arguments_v22": decision_args,
        "neutral_prefix_tools_v22": neutral_prefix_tools or [],
        "neutral_prefix_max_v22": int(neutral_prefix_max),
    }


TASKS_V0_2 = [
    # Exact EEv2.1 portability workloads, relabeled only for dataset identity.
    _task(
        "e22_port_stat_size",
        "portability",
        "使用 execute_command 获取 payload.bin 的精确字节数并把十进制数字写入 size.txt。"
        "不要用 Python，也不要用 read_file 读取 payload.bin 内容。",
        "printf 'alpha\\nbeta\\n' > payload.bin",
        "import os; assert open('size.txt').read().strip()==str(os.path.getsize('payload.bin'))",
        first_tools=["command"],
        decision_tools=["execute_command"],
        source_task_id="e21_port_stat_size",
    ),
    _task(
        "e22_port_regex_count",
        "portability",
        "使用 execute_command 统计 codes.txt 中恰好匹配两个大写字母后接三位数字的行数，"
        "把数字写入 count.txt。不要用 Python。",
        "printf 'AB123\\nxy123\\nCD999\\nZZ12\\nEF000\\n' > codes.txt",
        "assert open('count.txt').read().strip()=='3'",
        first_tools=["command"],
        decision_tools=["execute_command"],
        source_task_id="e21_port_regex_count",
    ),
    _task(
        "e22_port_find_names",
        "portability",
        "使用 execute_command 找出当前目录顶层所有 .txt 普通文件的文件名，按字典序一行一个写入 names.out。"
        "不要包含子目录中的文件，不要用 Python。",
        "mkdir -p sub; printf a > zebra.txt; printf b > alpha.txt; printf c > sub/hidden.txt; printf d > note.md",
        "assert open('names.out').read().splitlines()==['alpha.txt','zebra.txt']",
        first_tools=["command"],
        decision_tools=["execute_command"],
        source_task_id="e21_port_find_names",
    ),
    # Naturalistic wrong-tool holdouts: the user need is explicit, the tool name is not.
    _task(
        "e22_wrong_find_marker",
        "wrong_tool",
        "工作区里有且仅有一个文件包含唯一标记 EEV22-CEDAR-517，文件名未知。"
        "找出这个文件的相对路径并写入 found.txt。不要执行 shell 命令，也不要把所有文件逐个打开扫描。",
        "mkdir -p nest; printf 'plain\\n' > a.log; printf 'EEV22-CEDAR-517\\n' > nest/target.cfg; printf 'pending\\n' > found.txt",
        "assert open('found.txt').read().strip()=='nest/target.cfg'",
        first_tools=["search"],
        decision_tools=["search_files"],
        decision_args={"content": "EEV22-CEDAR-517"},
    ),
    _task(
        "e22_wrong_live_schema",
        "wrong_tool",
        "请依据运行时当前实际暴露的 service_control 参数契约，列出 action 的全部允许值，"
        "按契约顺序用逗号连接写入 actions.txt。不能从源码、文档或记忆推断，必须以运行时暴露事实为准。",
        "printf 'pending\\n' > actions.txt",
        "assert open('actions.txt').read().strip()=='status,publish,update,restart,release,adopt,override,verify_acknowledge'",
        first_tools=["read"],
        decision_tools=["get_tool_schema"],
        decision_args={"tool_name": "service_control"},
    ),
    _task(
        "e22_edit_snapshot_control",
        "edit_control",
        "把 settings.ini 中唯一的 mode=old 改成 mode=new。必须走版本安全的文件编辑流程，"
        "不得用 shell 命令直接改文件；如果需要先定位文件，可以先做一次只读定位。",
        "printf 'mode=old\\n' > settings.ini",
        "assert open('settings.ini').read().strip()=='mode=new'",
        first_tools=["read"],
        decision_tools=["read_file"],
        decision_args={"snapshot": True},
        neutral_prefix_tools=["search_files"],
        neutral_prefix_max=1,
    ),
]

TASK_BY_ID_V0_2 = {task["id"]: task for task in TASKS_V0_2}


def row_id(task_id: str, arm: str, repeat: int) -> str:
    return f"{task_id}__{arm}__r{repeat}"


def schedule_v0_2() -> list[tuple[dict, str, int]]:
    rows: list[tuple[dict, str, int]] = []
    arms = list(ARMS_V0_2)
    for task_idx, task in enumerate(TASKS_V0_2):
        for repeat in REPEATS_V0_2:
            offset = (task_idx + repeat - 1) % len(arms)
            order = arms[offset:] + arms[:offset]
            rows.extend((task, arm, repeat) for arm in order)
    return rows


def validate_v0_2() -> list[str]:
    errors: list[str] = []
    rows = schedule_v0_2()
    if len(rows) != 36:
        errors.append(f"expected 36 rows, got {len(rows)}")
    ids = [row_id(task["id"], arm, repeat) for task, arm, repeat in rows]
    if len(ids) != len(set(ids)):
        errors.append("duplicate row ids")
    for task in TASKS_V0_2:
        if not task["decision_acceptable_tools_v22"]:
            errors.append(f"{task['id']}: missing decisive-tool oracle")
        if task["family"] not in {"portability", "wrong_tool", "edit_control"}:
            errors.append(f"{task['id']}: unknown family")
        if task["neutral_prefix_max_v22"] < 0:
            errors.append(f"{task['id']}: invalid neutral prefix max")
        if task["family"] == "wrong_tool":
            prompt = str(task["prompt"])
            for tool in task["decision_acceptable_tools_v22"]:
                if tool in prompt:
                    errors.append(f"{task['id']}: prompt leaks target tool {tool}")
    return errors
