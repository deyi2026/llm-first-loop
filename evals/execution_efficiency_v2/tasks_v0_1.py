"""Frozen EEv2.1 held-out tasks."""

from __future__ import annotations

ARMS_V0_1 = ("A-current", "B-portability-contract")
REPEATS_V0_1 = (1, 2, 3)


def _task(
    tid: str,
    family: str,
    prompt: str,
    setup: str,
    verify: str,
    *,
    first_tools: list[str],
    exact_tools: list[str],
    first_args: dict | None = None,
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
        "first_action_acceptable_tools_v2": exact_tools,
        "first_action_required_arguments_v2": first_args,
    }


TASKS_V0_1 = [
    _task(
        "e21_port_stat_size",
        "portability",
        "使用 execute_command 获取 payload.bin 的精确字节数并把十进制数字写入 size.txt。"
        "不要用 Python，也不要用 read_file 读取 payload.bin 内容。",
        "printf 'alpha\\nbeta\\n' > payload.bin",
        "import os; assert open('size.txt').read().strip()==str(os.path.getsize('payload.bin'))",
        first_tools=["command"],
        exact_tools=["execute_command"],
    ),
    _task(
        "e21_port_regex_count",
        "portability",
        "使用 execute_command 统计 codes.txt 中恰好匹配两个大写字母后接三位数字的行数，"
        "把数字写入 count.txt。不要用 Python。",
        "printf 'AB123\\nxy123\\nCD999\\nZZ12\\nEF000\\n' > codes.txt",
        "assert open('count.txt').read().strip()=='3'",
        first_tools=["command"],
        exact_tools=["execute_command"],
    ),
    _task(
        "e21_port_find_names",
        "portability",
        "使用 execute_command 找出当前目录顶层所有 .txt 普通文件的文件名，按字典序一行一个写入 names.out。"
        "不要包含子目录中的文件，不要用 Python。",
        "mkdir -p sub; printf a > zebra.txt; printf b > alpha.txt; printf c > sub/hidden.txt; printf d > note.md",
        "assert open('names.out').read().splitlines()==['alpha.txt','zebra.txt']",
        first_tools=["command"],
        exact_tools=["execute_command"],
    ),
    _task(
        "e21_wrong_search_files",
        "wrong_tool",
        "文件名未知。第一步必须使用 search_files（不要用 execute_command）查找当前工作区中包含"
        "唯一标记 EEV21-ORCHID-731 的文件；找到后把它的相对路径写入 found.txt。",
        "mkdir -p nest; printf 'plain\\n' > a.log; printf 'EEV21-ORCHID-731\\n' > nest/target.cfg; printf 'pending\\n' > found.txt",
        "assert open('found.txt').read().strip()=='nest/target.cfg'",
        first_tools=["search"],
        exact_tools=["search_files"],
        first_args={"content": "EEV21-ORCHID-731"},
    ),
    _task(
        "e21_wrong_get_schema",
        "wrong_tool",
        "第一步必须调用 get_tool_schema 精确读取 service_control 当前完整 Schema；不要搜索源码、不要猜。"
        "然后把 action 的 enum 值按 Schema 顺序、逗号连接写入 actions.txt。",
        "printf 'pending\\n' > actions.txt",
        "assert open('actions.txt').read().strip()=='status,publish,update,restart,release,adopt,override,verify_acknowledge'",
        first_tools=["read"],
        exact_tools=["get_tool_schema"],
        first_args={"tool_name": "service_control"},
    ),
    _task(
        "e21_edit_snapshot_control",
        "edit_control",
        "把 settings.ini 中唯一的 mode=old 改成 mode=new。必须使用 edit_file 完成修改，不要用 execute_command；"
        "遵守当前 edit_file 的 snapshot/version 契约。",
        "printf 'mode=old\\n' > settings.ini",
        "assert open('settings.ini').read().strip()=='mode=new'",
        first_tools=["read"],
        exact_tools=["read_file"],
        first_args={"snapshot": True},
    ),
]

TASK_BY_ID_V0_1 = {task["id"]: task for task in TASKS_V0_1}


def row_id(task_id: str, arm: str, repeat: int) -> str:
    return f"{task_id}__{arm}__r{repeat}"


def schedule_v0_1() -> list[tuple[dict, str, int]]:
    rows: list[tuple[dict, str, int]] = []
    arms = list(ARMS_V0_1)
    for task_idx, task in enumerate(TASKS_V0_1):
        for repeat in REPEATS_V0_1:
            offset = (task_idx + repeat - 1) % len(arms)
            order = arms[offset:] + arms[:offset]
            rows.extend((task, arm, repeat) for arm in order)
    return rows


def validate_v0_1() -> list[str]:
    errors: list[str] = []
    rows = schedule_v0_1()
    if len(rows) != 36:
        errors.append(f"expected 36 rows, got {len(rows)}")
    ids = [row_id(task["id"], arm, repeat) for task, arm, repeat in rows]
    if len(ids) != len(set(ids)):
        errors.append("duplicate row ids")
    for task in TASKS_V0_1:
        if not task["first_action_acceptable_tools_v2"]:
            errors.append(f"{task['id']}: missing exact first-tool oracle")
        if task["family"] not in {"portability", "wrong_tool", "edit_control"}:
            errors.append(f"{task['id']}: unknown family")
    return errors

